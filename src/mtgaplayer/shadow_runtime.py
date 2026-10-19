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
    from .target_build import current_build, current_resource
    from .current_target_request import role_state_witness
    current=reducer.document()['current']
    fields=('instanceId','grpId','type','parentId','zoneId','ownerSeatId','controllerSeatId',
        'visibility','viewers','isTapped','uniqueAbilities','power','toughness','objectSourceGrpId')
    return copy.deepcopy((reducer.accepted_digest.hex(),current,current_build(reducer),current_resource(reducer),
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
                 clock_ns=None,observation_mode='local_log_watch',player_target_stages=False,parent_target_lineage=False,
                 research_policy=None,prepared_rules=None,prepared_references=None):
        from .land_development import POLICY as LAND_POLICY, SWAMP_POLICY
        from .target_effect import POLICY as TARGET_POLICY
        from .unified_research import POLICIES as UNIFIED_POLICIES
        from .rules_index import PreparedRulesIndex
        if (type(interval) not in (int,float) or not math.isfinite(interval) or not 0<=interval<=60 or
                samples is not None and (type(samples) is not int or not 1<=samples<=1000) or
                type(max_history_bytes) is not int or not 1<=max_history_bytes<=1024**3 or
                any(type(n) is not int or not 1<=n<=MAX_AGE_NS for n in (max_observation_age_ns,max_event_silence_ns)) or
                observation_mode not in ('local_log_watch','controlled_stream_replay') or
                type(player_target_stages) is not bool or type(parent_target_lineage) is not bool or
                research_policy not in (None,LAND_POLICY,SWAMP_POLICY,TARGET_POLICY,*UNIFIED_POLICIES) or
                prepared_rules is not None and not isinstance(prepared_rules,PreparedRulesIndex) or
                prepared_references is not None and (research_policy not in UNIFIED_POLICIES or
                    type(prepared_references) is not dict or not set(prepared_references) <= {'land','target_effect'} or
                    any(not isinstance(value,PreparedRulesIndex) for value in prepared_references.values())) or
                research_policy in UNIFIED_POLICIES and prepared_rules is not None):
            raise ValueError('invalid_shadow_runtime_bounds')
        self.path=path;self.interval=interval;self.samples=samples;self.max_history_bytes=max_history_bytes
        self.age=max_observation_age_ns;self.silence=max_event_silence_ns;self.clock=clock_ns or time.perf_counter_ns
        self.mode=observation_mode;self._owner=threading.get_ident();self._started=self._closed=False
        self._reducer=self._message=self._source=self._watch=None;self._metadata={};self._stop_reason='not_started'
        self._in_poll=False;self._attempt_started=None;self._completed_stamp=None
        self.parent_target_lineage=parent_target_lineage
        self.research_policy=research_policy;self.prepared_rules=prepared_rules
        self.prepared_references=dict(prepared_references or {})
        self._research_work=[];self._research_work_attempted=0
        self.player_target_stages=player_target_stages or parent_target_lineage
        self._stage_observer=None;self._player_freeze_attempted=False;self._parent_freeze_attempted=False
        self._player_work=[];self._player_work_attempted=0;self._player_work_previous=0
        self._parent_work=[];self._parent_work_attempted=0;self._parent_work_previous=0
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

    def _context(self,reducer,message,*,poll_started_ns=None,poll_completed=False,stage_observer=None):
        self._reducer,self._message=reducer,message
        if poll_started_ns is not None:
            if (self.player_target_stages and self._stage_observer is not None and
                    self.consumer.current_view()['consumer_status']=='STALE'):
                self._stage_observer.reset()
            self._attempt_started=poll_started_ns;self._in_poll=True;self._timings={};self._completed_stamp=None
            self._player_freeze_attempted=False
            self._parent_freeze_attempted=False
        if poll_completed:
            self._completed_stamp=_raw_stamp(reducer) if message is not None else None
            if self.player_target_stages:self._stage_observer=stage_observer

    def current_frame(self):
        result=self._current_frame();result['observation_mode']=self.mode
        from .unified_research import POLICIES as UNIFIED_POLICIES, _unknown as unified_unknown
        if self.research_policy in UNIFIED_POLICIES:
            if 'unified_research_decision' not in result:
                result['unified_research_decision']=unified_unknown(result['reason'],policy_version=self.research_policy)
        elif self.research_policy is not None and 'research_decision' not in result:
            from .land_development import POLICY as LAND_POLICY, SWAMP_POLICY, _unknown as land_unknown, _swamp_unknown
            from .target_effect import _unknown as target_unknown
            unknown=(_swamp_unknown if self.research_policy==SWAMP_POLICY else
                land_unknown if self.research_policy==LAND_POLICY else target_unknown)
            result['research_decision']=unknown(result['reason'])
            result['research_decision']['status']='expired'
        if (threading.get_ident()==self._owner and self.player_target_stages and self._stage_observer is not None):
            stage=self._stage_observer;revision=stage.revision
            if self.consumer.current_view()['consumer_status']=='STALE':revision.reset()
            if (not self._closed and result['time_scope']=='current_at_completed_poll' and
                    self._metadata.get('new_final_request') is True and not self._player_freeze_attempted):
                self._player_freeze_attempted=True
                evidence=result['local_evidence'].get('current_target_evidence',{})
                stage._revise(revision.freeze_player_targets,self.consumer,self._message,evidence,result['shadow_decision'])
            if (self.parent_target_lineage and not self._closed and result['time_scope']=='current_at_completed_poll' and
                    self._metadata.get('new_final_request') is True and not self._parent_freeze_attempted):
                self._parent_freeze_attempted=True
                stage.freeze_parent_target_lineage(self.consumer,self._message,result['current_options'],
                    result['shadow_decision'],child_evidence=result['local_evidence'].get('current_target_evidence'))
            result['historical_player_target_stages']=revision.player_stage_report()
            if self.parent_target_lineage:
                result['historical_parent_target_lineage']=stage.cast.parent_target_lineage_history()
        return result

    def parent_target_lineage_history(self,*,include_last=False):
        self._check_owner()
        if not self.parent_target_lineage or self._stage_observer is None:return None
        return self._stage_observer.cast.parent_target_lineage_history(include_last=include_last)

    def player_target_stage_history(self,*,include_last=False):
        """Owner-local historical facts; never an actionable current result."""
        self._check_owner()
        if not self.player_target_stages or self._stage_observer is None:return None
        return self._stage_observer.revision.player_stage_report(include_last=include_last)

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
            research=None;unified=None
            if self.research_policy is not None:
                from .land_development import POLICY as LAND_POLICY, SWAMP_POLICY, assess_current_land_development
                from .target_effect import POLICY as TARGET_POLICY, assess_current_target_effect
                from .unified_research import POLICIES as UNIFIED_POLICIES, _applicable_policy, combine_current_research
                selected_policy=self.research_policy;prepared=self.prepared_rules
                dispatch_ns=0
                if self.research_policy in UNIFIED_POLICIES:
                    dispatch_start=self.clock()
                    selected_policy=_applicable_policy(typ,policy_version=self.research_policy)
                    prepared=self.prepared_references.get('land' if selected_policy in (LAND_POLICY,SWAMP_POLICY) else 'target_effect')
                    dispatch_ns=self.clock()-dispatch_start
                if selected_policy is not None:
                    assess=assess_current_land_development if selected_policy in (LAND_POLICY,SWAMP_POLICY) else assess_current_target_effect
                    def applicable_research():
                        if self.research_policy in UNIFIED_POLICIES and selected_policy==LAND_POLICY:
                            from .target_build import current_resource
                            from .land_development import _unknown as land_unknown
                            # The legacy land API remains unchanged. The unified
                            # exact-build runtime cannot inherit a prior catalog
                            # capability for a new or unverified source build.
                            if current_resource(self._reducer) is None:
                                return land_unknown('exact_build_resource_provenance_unverified')
                        return assess(self.consumer,self._reducer,self._message,prepared,
                            policy_version=selected_policy,completed_stamp=self._completed_stamp)
                    research=self._timed('research_policy',applicable_research)
                    _bound(research,binding,ref)
                    if research['status']=='research_preference':
                        reviewed=(options['options'] if selected_policy in (LAND_POLICY,SWAMP_POLICY) else
                            local.get('current_target_evidence',{}).get('local_proposals',[]))
                        _need(sum(_equal(o['option_key'],research['preferred_option_key']) for o in reviewed)==1,
                            'frame_report_binding_invalid')
                if self.research_policy in UNIFIED_POLICIES:
                    dispatch_start=self.clock()
                    try:
                        unified=combine_current_research(options,policy,research,
                            local.get('current_target_evidence'),policy_version=self.research_policy)
                        _bound(unified,binding,ref)
                        _need(unified['status']!='expired','frame_report_binding_invalid')
                    finally:self._timings['unified_dispatch']=dispatch_ns+self.clock()-dispatch_start
            _need(_equal(stamp,_stamp(self._reducer,self._message,state)),'raw_state_changed_during_frame')
            result=_unknown('current_request_research_only','current_at_completed_poll')
            result.update(request_binding=copy.deepcopy(binding),source_snapshot_ref=copy.deepcopy(ref),request_type=typ,
                state_status=state['status'],request_support='finite_or_partial' if typ in SUPPORTED else 'unsupported',
                engine_offered_coverage=copy.deepcopy(options['coverage']),current_options=options,local_evidence=local,
                local_evidence_status={k:v['status'] for k,v in local.items()},shadow_decision=policy,
                shadow_policy_status=policy['status'],shadow_preference=copy.deepcopy(policy['preferred_option_key']),
                abstention_reason=None if policy['status']=='research_preference' else policy['reason'],
                unresolved_constraints={'options':copy.deepcopy(options['unresolved']),'policy':copy.deepcopy(policy['unresolved'])})
            if research is not None:result['research_decision']=research
            if unified is not None:result['unified_research_decision']=unified
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
        from .unified_research import POLICIES as UNIFIED_POLICIES
        stages=STAGES
        if self.research_policy in UNIFIED_POLICIES:
            stages=(*STAGES,'research_policy','unified_dispatch')
            labels=[*labels,'unified_'+(TYPES.get(frame.get('request_type'),'other')
                if frame['time_scope']=='current_at_completed_poll' else 'failed_or_revoked')]
        for label in ('all_polls',*labels):
            bucket=self._measurements.setdefault(label,{'poll_count':0,'timings':{k:[] for k in stages},'attempted':Counter()})
            bucket['poll_count']+=1
            for stage,value in self._timings.items():
                if stage in stages and type(value) is int and value>=0:
                    bucket['attempted'][stage]+=1
                    if len(bucket['timings'][stage])<20000:bucket['timings'][stage].append(value/1e6)

    def performance_report(self):
        self._check_owner()
        result={'scope':'local completed-poll calculation only; nested stages overlap; not MTGA latency',
            'phase_units':'polls; phase labels can overlap and must not be summed',
            'counts':dict(self._counts),'subscriptions':self._subscriptions,
            'phases':{label:{'poll_count':b['poll_count'],'timings_ms':{k:{**quantiles(v),
                'attempted_samples':b['attempted'][k],'omitted_by_cap':b['attempted'][k]-len(v)} for k,v in b['timings'].items()}}
                for label,b in self._measurements.items()},'read_only':True,**EXECUTION}
        if self.player_target_stages:
            result['player_target_stage_ms']={**quantiles(self._player_work),'attempted_samples':self._player_work_attempted,
                'omitted_by_cap':self._player_work_attempted-len(self._player_work)}
        if self.parent_target_lineage:
            result['parent_target_lineage_ms']={**quantiles(self._parent_work),'attempted_samples':self._parent_work_attempted,
                'omitted_by_cap':self._parent_work_attempted-len(self._parent_work)}
        if self.research_policy is not None:
            result['research_policy_ms']={**quantiles(self._research_work),'attempted_samples':self._research_work_attempted,
                'omitted_by_cap':self._research_work_attempted-len(self._research_work)}
        return result

    def close(self,reason='session_stopped'):
        self._check_owner()
        if self._closed:return
        if self._stage_observer is not None:self._stage_observer.reset()
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
            _clock_ns=self.clock,_owner_observer=self._context,
            **({'_player_target_stages':True} if self.player_target_stages else {}),
            **({'_parent_target_lineage':True} if self.parent_target_lineage else {}))
        try:
            for document in self._watch:
                self._source={k:document['source'][k] for k in ('phase','partial_record','stopped')}
                self._timings={k:self._metadata[n] for k,n in (('poll_read_framing','poll_read_ns'),
                    ('reducer_apply','reducer_apply_ns'),('decision_state_assembly','decision_state_assembly_ns'))}
                ready_start=self.clock();self._publish(document);frame=self.current_frame()
                if self.research_policy is not None and 'research_policy' in self._timings:
                    self._research_work_attempted+=1
                    if len(self._research_work)<20000:self._research_work.append(self._timings['research_policy']/1e6)
                if self.player_target_stages and self._stage_observer is not None:
                    total=self._stage_observer.completion_work_ns
                    elapsed=total-self._player_work_previous;self._player_work_previous=total
                    self._player_work_attempted+=1
                    if len(self._player_work)<20000:self._player_work.append(elapsed/1e6)
                    self._timings['player_target_stage']=elapsed
                if self.parent_target_lineage and self._stage_observer is not None:
                    total=self._stage_observer.cast.lineage_work_ns
                    elapsed=total-self._parent_work_previous;self._parent_work_previous=total
                    self._parent_work_attempted+=1
                    if len(self._parent_work)<20000:self._parent_work.append(elapsed/1e6)
                    self._timings['parent_target_lineage']=elapsed
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
    result={'schema_version':VERSION,'observation_mode':frame.get('observation_mode') if frame.get('observation_mode') in ('local_log_watch','controlled_stream_replay') else 'unknown',
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
    history=frame.get('historical_player_target_stages')
    if type(history) is dict:
        result['historical_player_target_stages']={key:count(history.get(key)) for key in (
            'frozen_reviewed_domains','frozen_local_proposals','strictly_paired_target_updates',
            'historically_selected_player_targets','independently_revised_selections',
            'strictly_paired_terminal_submits','fully_linked_historical_stages','unlinked_or_interrupted_stages',
            'historical_comparison_unavailable')}
        result['historical_player_target_stages'].update(historical_choice_agreements=None,
            historical_choice_disagreements=None,complete_target_legality=None,complete_action_legality=None,historical_only=True)
        elapsed=frame.get('timings_ns',{}).get('player_target_stage')
        if type(elapsed) is int and elapsed>=0:result['timings_ns']['player_target_stage']=elapsed
    history=frame.get('historical_parent_target_lineage')
    if type(history) is dict:
        from .parent_target_lineage import COUNTS
        result['historical_parent_target_lineage']={key:count(history.get(key)) for key in (*COUNTS,'unlinked_or_interrupted_attempts')}
        result['historical_parent_target_lineage'].update(activate_source_transitions=None,
            complete_target_legality=None,complete_action_legality=None,historical_only=True)
        elapsed=frame.get('timings_ns',{}).get('parent_target_lineage')
        if type(elapsed) is int and elapsed>=0:result['timings_ns']['parent_target_lineage']=elapsed
    research=frame.get('research_decision')
    if type(research) is dict:
        from .land_development import POLICY as LAND_POLICY,SWAMP_POLICY,REASONS as LAND_REASONS
        from .target_effect import POLICY as TARGET_POLICY,REASONS as TARGET_REASONS
        from .unified_research import REASONS as UNIFIED_REASONS
        policy=research.get('policy_version')
        names=(('active_action_rows','play_offers','verified_play_sources','verified_static_land_candidates','ordinary_profile_candidates')
            if policy in (LAND_POLICY,SWAMP_POLICY) else ('reviewed_target_members','local_proposals','verified_player_targets',
                'verified_public_object_targets','effect_identified') if policy==TARGET_POLICY else ())
        result['research_decision']={'policy_version':policy if policy in (LAND_POLICY,SWAMP_POLICY,TARGET_POLICY) else 'unsupported',
            'status':research.get('status') if research.get('status') in ('research_preference','abstain','expired','unsupported') else 'unknown',
            'reason':research.get('reason') if research.get('reason') in LAND_REASONS|TARGET_REASONS|UNIFIED_REASONS|PUBLIC_REASONS else 'unreviewed_reason',
            'coverage':{key:count(research.get('coverage',{}).get(key)) for key in names},
            'complete_legality_verified':False,'payment_verified':False,'strategic_optimality_verified':False,
            'read_only':True,**EXECUTION}
        elapsed=frame.get('timings_ns',{}).get('research_policy')
        if type(elapsed) is int and elapsed>=0:result['timings_ns']['research_policy']=elapsed
    unified=frame.get('unified_research_decision')
    if type(unified) is dict:
        from .land_development import POLICY as LAND_POLICY,SWAMP_POLICY,REASONS as LAND_REASONS
        from .target_effect import POLICY as TARGET_POLICY,REASONS as TARGET_REASONS
        from .shadow_decision import POLICY as SHADOW_POLICY
        from .unified_research import POLICY as UNIFIED_POLICY,POLICIES as UNIFIED_POLICIES,REASONS as UNIFIED_REASONS
        version=unified.get('policy_version')
        policies=((SHADOW_POLICY,LAND_POLICY if version==UNIFIED_POLICY else SWAMP_POLICY,TARGET_POLICY)
            if version in UNIFIED_POLICIES else ())
        result['unified_research_decision']={'policy_version':version if version in UNIFIED_POLICIES else 'unsupported',
            'selected_policy':unified.get('selected_policy') if unified.get('selected_policy') in policies else None,
            'status':unified.get('status') if unified.get('status') in ('research_preference','abstain','expired','unsupported') else 'unknown',
            'reason':unified.get('reason') if unified.get('reason') in
                LAND_REASONS|TARGET_REASONS|UNIFIED_REASONS|PUBLIC_REASONS else 'unreviewed_reason',
            'conflict':unified.get('reason')=='research_policy_conflict',
            'complete_legality_verified':False,'strategic_optimality_verified':False,
            'server_acceptance_verified':False,'read_only':True,**EXECUTION}
        for key in ('research_policy','unified_dispatch'):
            elapsed=frame.get('timings_ns',{}).get(key)
            if type(elapsed) is int and elapsed>=0:result['timings_ns'][key]=elapsed
    return result
