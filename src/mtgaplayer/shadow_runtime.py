"""One owner-thread production watch flow; poll-bound, read-only research only."""
import copy
import math
import threading
import time
from collections import Counter

from .decision_consumer import DecisionConsumer,EXECUTION,_bounded_json
from .decision_publisher import DecisionPublisher,MAX_AGE_NS
from .choice_candidates import _assess_current_report
from .choice_continuation import _binding
from .cast_target_members import _equal
from .response_evidence import _current_verified_raw_request
from .semantic_samples import _need
from .live_performance import quantiles

VERSION='mtgaplayer.current-decision-frame.v1'
TYPES={f'GREMessageType_{name}Req':name for name in ('ActionsAvailable','SelectTargets','SelectN',
    'PayCosts','Search','Group','DeclareAttackers','DeclareBlockers','Mulligan')}
SUPPORTED=set(TYPES)-{'GREMessageType_MulliganReq'}
STAGES=('poll_read_framing','reducer_apply','decision_state_assembly','event_publication',
    'consumer_accept','current_options','applicable_semantic_evidence','shadow_policy',
    'decision_frame_ready','poll_to_frame_ready')
PUBLIC_REASONS=frozenset(('not_started','session_stopped','sample_limit','user_interrupt','source_io_error',
    'pipeline_error','consumer_event_rejected','owner_context_unavailable','owner_thread_required',
    'history_is_not_current_opportunity','source_partial','source_stopped','source_invalid',
    'raw_current_binding_unverified','raw_state_changed_during_frame','frame_report_binding_invalid',
    'current_snapshot_expired_or_changed','current_snapshot_binding_invalid','consumer_stale',
    'consumer_closed','consumer_invalidated','consumer_waiting','consumer_protocol_error',
    'frame_computation_failed','request_strategy_unsupported','request_fields_not_fully_interpreted',
    'complex_actions_present','multiple_competing_actions','combination_or_tactical_basis_unverified',
    'multiple_or_unresolved_target_choices','selected_literal_or_probe_is_not_a_final_proposal',
    'candidate_coverage_truncated_or_omitted','known_constraint_contradiction_observed',
    'unique_reviewed_final_proposal_not_established','insufficient_policy_evidence',
    'unique_complete_proposal_for_reviewed_request_constraints','unique_play_action_type_research_preference'))
PUBLIC_REASONS |= frozenset(('unique_play_not_observed','complex_or_unsupported_candidates',
    'simple_candidate_structure_incomplete','play_source_card_identity_unverified','no_engine_offered_candidates',
    'choice_graph_candidate_conflict','candidate_inventory_invalid','invalid_decision_state',
    'advisor_options_binding_mismatch','advisor_preference_not_in_complete_option_inventory',
    'current_options_not_available_or_binding_invalid','current_view_unavailable',
    'unverified_simple_type_heuristic','requires_current_consumer'))


def _unknown(reason,scope='expired_or_revoked'):
    return {'schema_version':VERSION,'time_scope':scope,'reason':reason,'request_binding':None,
        'source_snapshot_ref':None,'request_type':None,'state_status':None,'request_support':'unknown',
        'engine_offered_coverage':None,'local_evidence_status':{},'current_options':None,'local_evidence':{},
        'unresolved_constraints':None,'shadow_decision':None,'shadow_policy_status':'expired',
        'shadow_preference':None,'abstention_reason':reason,'complete_legal_choices':None,
        'read_only':True,**EXECUTION}


def _raw_stamp(reducer):
    from .target_build import current_build
    from .current_target_request import role_state_witness
    current=reducer.document()['current']
    fields=('instanceId','grpId','type','parentId','zoneId','ownerSeatId','controllerSeatId',
        'visibility','viewers','isTapped','uniqueAbilities','power','toughness')
    return copy.deepcopy((reducer.accepted_digest.hex(),current,current_build(reducer),
        role_state_witness(reducer,(o['id'] for o in current.get('objects',[]))),
        [{k:reducer.objects[o['id']].get(k) for k in fields} for o in current.get('objects',[])]))


def _stamp(reducer,message,state):
    _need(reducer is not None and message is not None,'owner_context_unavailable')
    request=_current_verified_raw_request(reducer,message)
    _need(request is not None and _equal(_binding(reducer,request),state['binding']) and
        request.get('_continuity_verified') is True and reducer._target_state_continuity_verified is True and
        not any(request.get(k) is True for k in ('_target_evidence_interrupted','_cost_evidence_interrupted',
            '_search_evidence_interrupted','_group_evidence_interrupted','_selectn_evidence_interrupted')), 'raw_current_binding_unverified')
    # A visible projection/fingerprint, not a second State or hidden-object lookup.
    return _raw_stamp(reducer)


def _bound(report,binding,ref):
    _need(report['read_only'] is True and all(report[k] is False for k in EXECUTION), 'frame_report_binding_invalid')
    key='current_request_binding' if 'current_request_binding' in report else 'request_binding'
    if key in report:
        _need((report[key] is None and report['source_snapshot_ref'] is None) or
            (_equal(report[key],binding) and _equal(report['source_snapshot_ref'],ref)), 'frame_report_binding_invalid')


class LocalShadowRuntime:
    """Unique production watch, current owner contexts and one active subscription.

    Returned frames are observations at their indicated completed poll. Requery
    current_frame on this owner for freshness; retained dictionaries grant no input.
    A terminal STALE subscription can resume only on a genuinely new append request,
    using fresh Publisher/Consumer instances without replaying or rebuilding raw state.
    """
    def __init__(self,path,*,interval=.25,samples=None,max_history_bytes=64*1024*1024,
                 max_observation_age_ns=5_000_000_000,max_event_silence_ns=5_000_000_000,
                 clock_ns=None,observation_mode='local_log_watch'):
        if (type(interval) not in (int,float) or not math.isfinite(interval) or not 0<=interval<=60 or
                samples is not None and (type(samples) is not int or not 1<=samples<=1000) or
                type(max_history_bytes) is not int or not 1<=max_history_bytes<=1024**3 or
                any(type(n) is not int or not 1<=n<=MAX_AGE_NS for n in (max_observation_age_ns,max_event_silence_ns)) or
                observation_mode not in ('local_log_watch','controlled_stream_replay')):
            raise ValueError('invalid_shadow_runtime_bounds')
        self.path=path;self.interval=interval;self.samples=samples;self.max_history_bytes=max_history_bytes
        self.age=max_observation_age_ns;self.silence=max_event_silence_ns;self.clock=clock_ns or time.perf_counter_ns
        self.mode=observation_mode;self._owner=threading.get_ident();self._started=self._closed=False
        self._reducer=self._message=self._source=self._watch=None;self._metadata={};self._stop_reason='not_started'
        self._in_poll=False;self._attempt_started=None;self._completed_stamp=None
        self._timings={};self._counts=Counter();self._measurements={};self._subscriptions=0;self._new_subscription()

    def _new_subscription(self):
        self.publisher=DecisionPublisher(self.age,self.clock,state_version=15)
        self.consumer=DecisionConsumer(self.silence,self.age,self.clock);self._subscriptions+=1

    def _check_owner(self):
        if threading.get_ident()!=self._owner:raise ValueError('owner_thread_required')

    def _timed(self,name,fn):
        start=self.clock()
        try:return fn()
        finally:self._timings[name]=self.clock()-start

    def _context(self,reducer,message,*,poll_started_ns=None,poll_completed=False):
        self._reducer,self._message=reducer,message
        if poll_started_ns is not None:
            self._attempt_started=poll_started_ns;self._in_poll=True;self._timings={};self._completed_stamp=None
        if poll_completed:
            self._completed_stamp=_raw_stamp(reducer) if message is not None else None

    def current_frame(self):
        result=self._current_frame();result['observation_mode']=self.mode
        return result

    def _current_frame(self):
        if threading.get_ident()!=self._owner:return _unknown('owner_thread_required')
        if self._closed:return _unknown(self._stop_reason)
        if self._source is None:return _unknown('not_started')
        if self._source['phase']!='append':return _unknown('history_is_not_current_opportunity','observed_in_history')
        if self._source['partial_record']:return _unknown('source_partial')
        if self._source['stopped']:return _unknown('source_stopped')
        if self._reducer is None or self._message is None:return _unknown('owner_context_unavailable')
        stamp=None;source=copy.deepcopy(self._source)
        def evaluate(state,*,source_snapshot_ref):
            nonlocal stamp
            stamp=_stamp(self._reducer,self._message,state);binding=state['binding'];ref=source_snapshot_ref
            _need(_equal(stamp,self._completed_stamp),'raw_state_changed_during_frame')
            options=self._timed('current_options',self.consumer.current_decision_options)
            _need(_equal(options['request_binding'],binding) and _equal(options['source_snapshot_ref'],ref), 'frame_report_binding_invalid')
            _bound(options,binding,ref)
            for option in options['options']:_bound(option,binding,ref)
            typ=binding['request_type'];local={}
            def semantics():
                contexts={'GREMessageType_ActionsAvailableReq':('complex_action_intents',{'include_complex_intents':True}),
                    'GREMessageType_SelectTargetsReq':('current_target_evidence',{'current_target_context':(self._reducer,self._message)}),
                    'GREMessageType_SearchReq':('current_search_evidence',{'current_search_context':(self._reducer,self._message)}),
                    'GREMessageType_GroupReq':('current_group_evidence',{'current_group_context':(self._reducer,self._message)})}
                # Preserve the existing Resolution frame; only route the newly
                # reviewed context to its explicit evidence projection.
                selectn=self._message.get('selectNReq')
                if type(selectn) is dict and selectn.get('context')=='SelectionContext_TriggeredAbility':
                    contexts['GREMessageType_SelectNReq']=('current_selectn_evidence',
                        {'current_selectn_context':(self._reducer,self._message)})
                if typ in contexts:
                    key,kwargs=contexts[typ];enriched=self.consumer.current_decision_options(**kwargs)
                    local[key]=enriched.pop(key);_need(_equal(enriched,options),'frame_report_binding_invalid')
                elif typ=='GREMessageType_PayCostsReq':
                    from .current_cost_stage import assess_current_cost_stage
                    local['current_cost_stage']=assess_current_cost_stage(self.consumer,self._reducer,self._message,mana_requirement_match=True)
            self._timed('applicable_semantic_evidence',semantics)
            for report in local.values():_bound(report,binding,ref)
            policy=self._timed('shadow_policy',self.consumer.shadow_decision);_bound(policy,binding,ref)
            _need(_equal(policy['request_binding'],binding) and _equal(policy['source_snapshot_ref'],ref),'frame_report_binding_invalid')
            if policy['status']=='research_preference':
                _need(sum(_equal(o['option_key'],policy['preferred_option_key']) for o in options['options'])==1,'frame_report_binding_invalid')
            _need(_equal(stamp,_stamp(self._reducer,self._message,state)),'raw_state_changed_during_frame')
            result=_unknown('current_request_research_only','current_at_completed_poll')
            result.update(request_binding=copy.deepcopy(binding),source_snapshot_ref=copy.deepcopy(ref),request_type=typ,
                state_status=state['status'],request_support='finite_or_partial' if typ in SUPPORTED else 'unsupported',
                engine_offered_coverage=copy.deepcopy(options['coverage']),current_options=options,local_evidence=local,
                local_evidence_status={k:v['status'] for k,v in local.items()},shadow_decision=policy,
                shadow_policy_status=policy['status'],shadow_preference=copy.deepcopy(policy['preferred_option_key']),
                abstention_reason=None if policy['status']=='research_preference' else policy['reason'],
                unresolved_constraints={'options':copy.deepcopy(options['unresolved']),'policy':copy.deepcopy(policy['unresolved'])})
            _bounded_json(result);return result
        try:
            result=_assess_current_report(self.consumer,evaluate,_unknown)
            if result['time_scope']=='current_at_completed_poll':
                _need(_equal(source,self._source) and source=={'phase':'append','partial_record':False,'stopped':False},
                    'current_snapshot_expired_or_changed')
                view=self.consumer.current_view()
                _need(view['current_snapshot_ref']==result['source_snapshot_ref'] and view['new_request_observed'] is True and
                    _equal(stamp,_stamp(self._reducer,self._message,view['decision_state'])),'raw_state_changed_during_frame')
                after=self.consumer.current_view()
                _need(after['current_snapshot_ref']==result['source_snapshot_ref'] and after['consumer_status']=='OBSERVING',
                    'current_snapshot_expired_or_changed')
            return result
        except (ValueError,TypeError,KeyError,IndexError,RecursionError,UnicodeError,OverflowError):
            return _unknown('frame_computation_failed')

    def _publish(self,document):
        view=self.consumer.current_view()
        if view['consumer_status']=='STALE':
            self.publisher.stop('other_supported_reason')
            # Never renew an expired current request from empty polls/retransmits.
            if not (self._source['phase']=='append' and not self._source['partial_record'] and
                    self._metadata.get('new_final_request') is True and self._message is not None):return
            self._new_subscription()
        events=self._timed('event_publication',lambda:self.publisher.observe(document,self._metadata))
        def accept():
            for event in events:
                if not self.consumer.accept_event(event):
                    if self.consumer.current_view()['consumer_status']=='STALE':return
                    raise ValueError('consumer_event_rejected')
                if event['event_type']=='invalidate':self._counts['invalidations']+=1
        self._timed('consumer_accept',accept)

    def _record(self,frame,labels):
        self._counts['polls']+=1;self._counts[frame['time_scope']]+=1
        self._in_poll=False
        if frame['time_scope']=='current_at_completed_poll':self._counts['current_'+TYPES.get(frame['request_type'],'other')]+=1
        for label in ('all_polls',*labels):
            bucket=self._measurements.setdefault(label,{'poll_count':0,'timings':{k:[] for k in STAGES},'attempted':Counter()})
            bucket['poll_count']+=1
            for stage,value in self._timings.items():
                if stage in STAGES and type(value) is int and value>=0:
                    bucket['attempted'][stage]+=1
                    if len(bucket['timings'][stage])<20000:bucket['timings'][stage].append(value/1e6)

    def performance_report(self):
        self._check_owner()
        return {'scope':'local completed-poll calculation only; nested stages overlap; not MTGA latency',
            'phase_units':'polls; phase labels can overlap and must not be summed',
            'counts':dict(self._counts),'subscriptions':self._subscriptions,
            'phases':{label:{'poll_count':b['poll_count'],'timings_ms':{k:{**quantiles(v),
                'attempted_samples':b['attempted'][k],'omitted_by_cap':b['attempted'][k]-len(v)} for k,v in b['timings'].items()}}
                for label,b in self._measurements.items()},'read_only':True,**EXECUTION}

    def close(self,reason='session_stopped'):
        self._check_owner()
        if self._closed:return
        self._closed=True;self._stop_reason=reason;self._message=self._reducer=None
        try:
            events=self.publisher.stop(reason if reason in ('sample_limit','user_interrupt','source_error') else 'other_supported_reason')
            for event in events:self.consumer.accept_event(event)
        except (ValueError,TypeError,KeyError):
            self._counts['stop_event_failures']+=1
        finally:
            # A bad publication clock/transport must never leave an observing
            # Consumer behind after its owner has irreversibly stopped.
            try:self.consumer.close(reason)
            except (ValueError,TypeError,KeyError):self._counts['stop_consumer_diagnostic_failures']+=1
        self._counts['terminal_revocations']+=1

    def frames(self):
        self._check_owner()
        if self._started:raise ValueError('shadow_runtime_already_started')
        self._started=True;reason='sample_limit' if self.samples is not None else 'session_stopped'
        from .cli import watch
        def observed(metadata):self._metadata=metadata
        self._watch=watch(self.path,self.interval,self.samples,self.max_history_bytes,decision_state=True,
            decision_state_version=15,current_multi_slot_cast=True,_poll_observer=observed,
            _clock_ns=self.clock,_owner_observer=self._context)
        try:
            for document in self._watch:
                self._source={k:document['source'][k] for k in ('phase','partial_record','stopped')}
                self._timings={k:self._metadata[n] for k,n in (('poll_read_framing','poll_read_ns'),
                    ('reducer_apply','reducer_apply_ns'),('decision_state_assembly','decision_state_assembly_ns'))}
                ready_start=self.clock();self._publish(document);frame=self.current_frame()
                self._timings['decision_frame_ready']=self.clock()-ready_start
                self._timings['poll_to_frame_ready']=self.clock()-self._metadata['poll_started_ns']
                labels=['startup_history' if self._source['phase']=='history' else 'incremental_append' if self._metadata.get('owner_bytes_read',0) else 'empty_poll']
                for label,condition in (('request_produced',self._metadata.get('owner_requests_accepted',0)),
                    ('request_consumed',self._metadata.get('owner_requests_consumed',0)),
                    ('invalid_or_revoked',frame['time_scope']=='expired_or_revoked'),('file_reset',self._metadata.get('reset')),
                    ('partial_record',self._source['partial_record'])):
                    if condition:labels.append(label)
                self._record(frame,labels)
                frame.update(observation_mode=self.mode,timings_ns=copy.deepcopy(self._timings),
                    poll_accepted_requests=self._metadata.get('owner_requests_accepted',0),
                    poll_consumed_requests=self._metadata.get('owner_requests_consumed',0))
                yield frame
                if self._closed:break
        except KeyboardInterrupt:reason='user_interrupt'
        except OSError:reason='source_io_error'
        except (ValueError,TypeError,KeyError,IndexError,RecursionError,UnicodeError,OverflowError):reason='pipeline_error'
        finally:
            if self._in_poll:
                self._counts['failed_polls']+=1
                self._timings['poll_to_frame_ready']=self.clock()-self._attempt_started
                self._record(_unknown(reason),['failed_poll'])
            self.close(reason)
            self._watch.close()
        terminal=self.current_frame();terminal.update(observation_mode=self.mode,timings_ns={},poll_accepted_requests=0,poll_consumed_requests=0)
        yield terminal


def safe_summary(frame):
    """Positive whitelist; never serialize owner IDs, refs, payloads or raw reasons."""
    def count(value):return value if type(value) is int and 0<=value<=2**53-1 else None
    def reason(value):return value if value is None or value in PUBLIC_REASONS else 'unreviewed_reason'
    options=frame.get('current_options');coverage=options.get('coverage',{}) if type(options) is dict else {}
    local=frame.get('local_evidence',{});evidence={}
    units=('active_action_row','offered_member','attacker_candidate','blocker_candidate',
        'current_target_entry','discard_offered_member','cost_offered_member')
    source_names={'decision_advisor',*(f'known_candidates_v{n}' for n in range(2,7)),
        'known_candidates_v6.cast_members','known_candidates_v6.activate_payment'}
    source_counts=('candidate_total_for_reviewed_constraints','returned_candidates','offered_member_count',
        'minimum','maximum','selected_count','returned_relations')
    sources=[]
    for source in coverage.get('sources',[]):
        if source.get('source') not in source_names:continue
        stats=source.get('coverage',{})
        entry={'source':source['source'],'unit':source.get('unit') if source.get('unit') in units else None,
            **{k:count(source.get(k)) for k in ('observed','constructed_options','returned_options','omitted_constructed_options')},
            'truncated':source.get('truncated') if type(source.get('truncated')) is bool else None,
            'coverage':{k:count(stats[k]) for k in source_counts if k in stats}}
        for key in ('probe_coverage','member_probes','action_row_coverage'):
            if type(stats.get(key)) is dict:
                entry['coverage'][key]={k:count(stats[key].get(k)) for k in ('observed_probes','examined','verified',
                    'unknown','contradicted','unexamined','omitted_due_to_return_limit','total_active_rows',
                    'reviewed_rows','unknown_rows','contradicted_known_constraint_rows','contradicted_known_relation_rows') if k in stats[key]}
        sources.append(entry)
    fields={'complex_action_intents':('returned_parent_rows','reviewed_target_rows','finite_stage_intent_rows'),
        'current_target_evidence':('returned_proposals','candidate_total_for_reviewed_constraints'),
        'current_search_evidence':('offered_item_count','returned_members','items_to_search_count'),
        'current_group_evidence':('observed_item_count','reviewed_member_count','unresolved_item_count','returned_members'),
        'current_selectn_evidence':('engine_offered_member_count','reviewed_visible_member_count',
            'unresolved_member_count','returned_members','omitted_members')}
    for key,names in fields.items():
        if key not in local:continue
        value=local[key];source=value.get('coverage',{}) if key=='complex_action_intents' else value
        if key=='current_target_evidence' and value.get('schema_version')=='mtgaplayer.current-target-request.v2':
            names=(*names,'verified_player_memberships','verified_public_object_memberships','unresolved_memberships')
        evidence[key]={'status':value.get('status') if value.get('status') in ('observed','insufficient_evidence','partial') else 'unknown',
            'counts':{name:count(source.get(name)) for name in names},'truncated':value.get('truncated') if type(value.get('truncated')) is bool else None}
    if 'current_cost_stage' in local:
        value=local['current_cost_stage'];observed=value.get('status')=='observed'
        evidence['current_cost_stage']={'status':'observed' if observed else 'unknown',
            'mana_requirements':len(value.get('mana_requirements',[])) if observed else None,
            'payment_action_rows':len(value.get('payment_actions',[])) if observed else None,
            'predictive_solutions':len(value.get('predictive_auto_tap_solutions',[])) if observed else None,
            'local_candidate_memberships':len(value.get('local_candidates',[]))}
    return {'schema_version':VERSION,'observation_mode':frame.get('observation_mode') if frame.get('observation_mode') in ('local_log_watch','controlled_stream_replay') else 'unknown',
        'time_scope':frame.get('time_scope') if frame.get('time_scope') in ('current_at_completed_poll','observed_in_history','expired_or_revoked') else 'unknown',
        'request_type':TYPES.get(frame.get('request_type'),'unsupported_request'),
        'shadow_policy_status':frame.get('shadow_policy_status') if frame.get('shadow_policy_status') in ('research_preference','abstain','expired','unsupported') else 'unknown',
        'abstention_reason':reason(frame.get('abstention_reason')),'revocation_reason':None if frame.get('time_scope')=='current_at_completed_poll' else reason(frame.get('reason')),
        'engine_offered_count':count(coverage.get('engine_offered_count')),
        'engine_offered_unit':coverage.get('engine_offered_unit') if coverage.get('engine_offered_unit') in units else None,
        'sources':sources,'evidence_levels':dict(Counter(o.get('evidence_level') for o in options.get('options',[])
            if o.get('evidence_level') in ('engine_offered','structurally_decoded','known_constraints_verified','unsupported'))) if type(options) is dict else {},
        'returned_options':count(coverage.get('returned_options')) if options is not None else None,
        'omitted_constructed_options':count(coverage.get('omitted_constructed_options')) if options is not None else None,
        'truncated':coverage.get('truncated') if type(coverage.get('truncated')) is bool else None,'local_evidence':evidence,
        'timings_ns':{k:v for k,v in frame.get('timings_ns',{}).items() if k in STAGES and type(v) is int and v>=0},
        'complete_legal_choices':None,'read_only':True,**EXECUTION}
