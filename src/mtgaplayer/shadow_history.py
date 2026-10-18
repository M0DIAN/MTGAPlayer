"""Bounded historical simulation, never a live decision opportunity.

One production framer/reducer; freeze policy in the accepted-request callback
before applying another message. Future responses use existing post-consumption
correlators only. Raw bindings, options and payloads never leave this module.
"""
import copy
import hashlib
from collections import Counter
from pathlib import Path
import time

from .raw_log import RawFramer, RawReducer
from .response_evidence import (_current_verified_request, _current_verified_raw_request,
    _identity, _paired_response, _paired_terminal_submit)
from .semantic_evidence import _classify, _complex_classify, _TYPES
from .decision_publisher import DecisionPublisher
from .decision_consumer import DecisionConsumer, EXECUTION
from .live_performance import quantiles, code_version

VERSION = 'mtgaplayer.shadow-history-evaluation.v1'
KINDS = {'GREMessageType_ActionsAvailableReq':'actions_available',
    'GREMessageType_SelectTargetsReq':'select_targets', 'GREMessageType_SelectNReq':'select_n',
    'GREMessageType_PayCostsReq':'pay_costs', 'GREMessageType_DeclareAttackersReq':'declare_attackers',
    'GREMessageType_DeclareBlockersReq':'declare_blockers'}
COUNTS = ('observed_requests','evaluable_requests','research_preferences','abstentions',
    'unsupported','invalid_or_incomplete','expired_or_consumed')
CHOICES = ('historical_choices_observed','historical_choices_uniquely_matched',
    'comparable_policy_preferences','historical_agreements','historical_disagreements','uncomparable')
STAGES = ('read_framing','reducer_apply_including_freeze','state_publisher_consumer',
    'current_decision_options','shadow_policy_api','evaluation_bookkeeping')
MAX_SAMPLES = 20000


def _counter(): return dict.fromkeys(COUNTS, 0)


class _Evaluation:
    def __init__(self, on_freeze=None, actions_available_gates=False, complex_action_intents=False, protocol_evidence=False, current_cost_stages=False):
        from .cli import _observe_combat, _observe_tap, _observe_continuation
        self.ordinal = self.offset = 0; self.on_freeze = on_freeze
        self._consumed_this_record=False
        self.seen = set(); self.ended = set(); self.frozen = None
        self.counts = {kind:_counter() for kind in (*KINDS.values(),'other')}
        self.reasons = {kind:Counter() for kind in self.counts}
        self.abstention_reasons = {kind:Counter() for kind in self.counts}
        self.gaps = {kind:Counter() for kind in self.counts}
        self.action_gaps = {kind:Counter() for kind in sorted(_TYPES)}
        self.action_requests = Counter(); self.choices = Counter(); self.choice_units = Counter()
        self.diagnostics = Counter(); self.timings = {name:[] for name in STAGES}
        self.timing_counts = Counter()
        self.action_gates = None
        self.cost_stages = Counter() if current_cost_stages else None
        self.prior_complex_context = None  # Count-only history, never current authority.
        if current_cost_stages:self.timings['current_cost_stage'] = []
        self.intent_counts = Counter() if complex_action_intents else None
        if complex_action_intents: self.timings['complex_action_intents_cached_api'] = []
        if actions_available_gates:
            from .actions_available_gates import ActionsAvailableGates
            self.action_gates = ActionsAvailableGates(protocol_evidence)
            self.timings['actions_available_gate_analysis'] = []
            if protocol_evidence:self.timings['actions_available_protocol_evidence'] = []
        self.reducer = RawReducer(include_state_messages=True, include_request_parameters=True,
            include_targeted_activate=True, include_current_discard=True, include_target_payment_relation=True,
            include_cast_target_members=True, include_cast_activate_associations=True, include_multi_slot_cast=True)
        self.reducer.reset(1)
        self.combat = _observe_combat(self.reducer); self.tap = _observe_tap(self.reducer)
        self.stage = _observe_continuation(self.reducer, include_cast=True)
        previous = self.reducer.observer
        def observe(event, details):
            if self.cost_stages is not None and (event == 'continuity_error' or
                    event == 'state_accepted' and details['kind'] == 'full'):
                self.prior_complex_context = None
            previous(event, details)
            if event == 'request_accepted': self.freeze(details)
            elif event == 'request_ended': self.end(details['request'])
            elif event == 'continuity_error': self.diagnostics['continuity_errors'] += 1
            elif event == 'unsupported_broadcast_request': self.diagnostics['broadcast_requests_excluded'] += 1
        self.reducer.observer = observe
        self.publisher = DecisionPublisher(86_400_000_000_000,clock_ns=self.clock, session_id='historical-simulation', state_version=15)
        self.consumer = DecisionConsumer(86_400_000_000_000,86_400_000_000_000,self.clock)

    def clock(self): return (self.ordinal+1)*1_000_000

    def timed(self, name, elapsed):
        self.timing_counts[name] += 1
        if len(self.timings[name]) < MAX_SAMPLES:self.timings[name].append(elapsed/1e6)

    def labels(self, counter, labels):
        for label in labels:
            if label in counter or len(counter)<128:counter[label] += 1
            else:self.diagnostics['gap_label_occurrences_omitted_by_cap'] += 1

    def publish(self, *, new=False, partial=False):
        from .cli import _project_decision_state
        start=time.perf_counter_ns();r=self.reducer
        document=r.document(include_frontier_rows=True,include_decision_state=True)
        if partial:
            document['current']={'valid':False,'actionable':False};document['error']='partial_raw_record_waiting'
        document['source']={'format':'player-log-gre-v1','generation':r.generation,'byte_offset':self.offset,
            'mode':'watch','phase':'append','partial_record':partial,'stopped':False,
            'input_sent':False,'executor_connected':False}
        _project_decision_state(r,document,self.combat,False,15)
        now=self.clock()
        metadata={'poll_started_ns':now,'poll_completed_ns':now,'poll_read_ns':0,'reducer_apply_ns':0,
            'decision_state_assembly_ns':0,'state_changed':True,'request_changed':new,
            'new_final_request':new,'request_consumed':self._consumed_this_record}
        previous_ref=self.consumer.current_view()['current_snapshot_ref']
        events=self.publisher.observe(document,metadata)
        for event in events:
            if not self.consumer.accept_event(event):raise ValueError('historical_transport_rejected')
            if event['event_type']=='invalidate':self.diagnostics['consumer_revocations'] += 1
        current=self.consumer.current_view()
        if any(e['event_type']=='invalidate' for e in events):
            if current['current_snapshot_ref']==previous_ref and previous_ref is not None:
                raise ValueError('historical_revocation_failed')
            self.diagnostics['revoked_refs_not_restored'] += 1
        self.timed('state_publisher_consumer',time.perf_counter_ns()-start)

    def end(self, request):
        token=_identity(request)
        if token in self.seen and token not in self.ended:
            self.ended.add(token);self.counts[KINDS.get(request['type'],'other')]['expired_or_consumed'] += 1
        self._consumed_this_record |= (self.reducer.match,self.reducer.game,request['id']) in self.reducer.consumed

    def freeze(self, details):
        request=_current_verified_raw_request(self.reducer,details['message'])
        if request is None:return
        token=_identity(request)
        if token in self.seen:
            self.diagnostics['request_retransmissions_excluded'] += 1;return
        self.seen.add(token);kind=KINDS.get(request['type'],'other');counts=self.counts[kind]
        counts['observed_requests'] += 1
        self.publish(new=True)
        start=time.perf_counter_ns();options=self.consumer.current_decision_options()
        self.timed('current_decision_options',time.perf_counter_ns()-start)
        start=time.perf_counter_ns();decision=self.consumer.shadow_decision()
        self.timed('shadow_policy_api',time.perf_counter_ns()-start)
        if self.cost_stages is not None and kind == 'pay_costs':
            from .current_cost_stage import assess_current_cost_stage, MANA_PROFILE
            from .semantic_effect_cost import PROFILE as NONMANA_PROFILE
            cost_start=time.perf_counter_ns()
            stage=assess_current_cost_stage(self.consumer,self.reducer,details['message'])
            self.timed('current_cost_stage',time.perf_counter_ns()-cost_start)
            c=self.cost_stages;c['pay_costs_requests_observed'] += 1
            profile=stage['cost_request_profile']
            c['reviewed_nonmana_select_profile' if profile==NONMANA_PROFILE else
              'reviewed_mana_payment_stage' if profile==MANA_PROFILE else 'unreviewed_cost_shape'] += 1
            if profile==NONMANA_PROFILE:
                c['local_cost_candidates_observed_requests'] += 1
                c['local_cost_candidate_memberships'] += len(stage['local_candidates'])
            else:c['local_cost_candidates_unknown_requests'] += 1
            if profile==MANA_PROFILE:
                c['observed_mana_requirements'] += len(stage['mana_requirements'])
                c['observed_payment_action_rows'] += len(stage['payment_actions'])
                c['observed_predictive_auto_tap_solutions'] += len(stage['predictive_auto_tap_solutions'])
            if self.prior_complex_context is not None and self.prior_complex_context==token[:4]:
                c['cost_requests_with_prior_paired_complex_context'] += 1
        if self.intent_counts is not None:
            start=time.perf_counter_ns()
            enriched=self.consumer.current_decision_options(include_complex_intents=True)
            # Optional evidence failure must not rewrite MP68's default policy
            # statistics or frozen comparison option. Keep its original view.
            options['complex_action_intents']=enriched['complex_action_intents']
            self.timed('complex_action_intents_cached_api',time.perf_counter_ns()-start)
            if kind == 'actions_available':
                # Authenticated inventory, not MP65's possibly withheld/limited rows.
                inventory=request.get('action_inventory')
                if type(inventory) is dict:
                    self.intent_counts['observed_complex_action_rows'] += sum(row['count']
                        for row in inventory['types'] if row['action_type'] in ('ActionType_Cast','ActionType_Activate'))
                else:self.intent_counts['inventory_unknown_requests'] += 1
                if enriched['request_binding'] is None:self.intent_counts['intent_evidence_unavailable_requests'] += 1
                for name in ('returned_parent_rows','reviewed_target_rows',
                             'predictive_payment_association_rows','finite_stage_intent_rows'):
                    self.intent_counts[name] += options['complex_action_intents']['coverage'][name]
        start=time.perf_counter_ns();status=decision['status']
        if options['status'] not in ('partial','unsupported'):
            counts['invalid_or_incomplete'] += 1
        elif status in ('research_preference','abstain'):
            counts['evaluable_requests'] += 1
            counts['research_preferences' if status=='research_preference' else 'abstentions'] += 1
        elif status=='unsupported':counts['unsupported'] += 1
        else:counts['invalid_or_incomplete'] += 1
        # Reasons/unknowns come directly from existing policy/options, never card text.
        reason=decision['reason'] or 'unspecified'
        if len(self.reasons[kind]) < 128 or reason in self.reasons[kind]:self.reasons[kind][reason] += 1
        if status=='abstain' and options['status'] in ('partial','unsupported'):
            self.labels(self.abstention_reasons[kind],[reason])
        labels=set(decision['unresolved'])
        labels.update(x['reason'] for x in options['unresolved'] if 'reason' in x)
        for option in options['options']:labels.update(option['unresolved'])
        labels=sorted(labels)[:128]
        self.labels(self.gaps[kind],labels)
        # An Advisor structure gate may withhold all MP65 engine options while
        # the existing authenticated inventory still records offered types.
        # Count those observed labels, not zero actions inferred from abstention.
        inventory=request.get('action_inventory')
        categories={row['action_type'] for row in inventory.get('types',[])
                    if type(row.get('count')) is int and row['count']>0} if type(inventory) is dict else set()
        for category in categories & _TYPES:
            self.action_requests[category] += 1;self.labels(self.action_gaps[category],labels)
        selected=[o for o in options['options'] if o['option_key']==decision['preferred_option_key']]
        self.frozen={'token':token,'ordinal':self.ordinal,'decision':copy.deepcopy(decision),
            'selected':copy.deepcopy(selected[0]) if len(selected)==1 else None}
        if self.action_gates is not None and kind == 'actions_available':
            gate_start=time.perf_counter_ns();view=self.consumer.current_view()
            self.action_gates.observe(details['message'],request,options,decision,
                view['decision_state'],view['current_snapshot_ref'])
            self.timed('actions_available_gate_analysis',time.perf_counter_ns()-gate_start)
            if self.action_gates.protocol is not None:
                self.timed('actions_available_protocol_evidence',self.action_gates.protocol_elapsed_ns)
        if self.on_freeze is not None:self.on_freeze(self.ordinal,copy.deepcopy(request),copy.deepcopy(options),copy.deepcopy(decision))
        self.timed('evaluation_bookkeeping',time.perf_counter_ns()-start)

    def compare(self, before, saved, payload, mixed):
        if mixed or before is None or type(payload) is not dict:return
        if self.cost_stages is not None:
            c=self.cost_stages
            if before['type']=='GREMessageType_ActionsAvailableReq' and _paired_response(self.reducer,before,payload):
                typ,result,*_=_complex_classify(before,payload)
                if result=='unique' and typ in ('ActionType_Cast','ActionType_Activate'):
                    c['prior_paired_complex_submissions_observed'] += 1
                    self.prior_complex_context=_identity(before)[:4]
            if before['type']=='GREMessageType_PayCostsReq' and payload.get('type') in (
                    'ClientMessageType_EffectCostResp','ClientMessageType_PerformActionResp',
                    'ClientMessageType_SelectNResp','ClientMessageType_PerformAutoTapActionsResp') and _paired_response(
                        self.reducer,before,payload,expected_type=payload['type']):
                c['historically_paired_cost_responses'] += 1
                c['paired_effect_cost_responses' if payload['type']=='ClientMessageType_EffectCostResp' else
                  'paired_other_cost_child_responses'] += 1
        paired=_paired_response(self.reducer,before,payload) or _paired_terminal_submit(self.reducer,before,payload)
        if not paired:
            typ=payload.get('type')
            if isinstance(typ,str) and typ.startswith('ClientMessageType_') and typ.endswith('Resp'):
                self.diagnostics['unmatched_response_records'] += 1
            return
        self.choices['historical_choices_observed'] += 1
        unique=False;unit='unsupported_submission';typ=None
        if before['type']=='GREMessageType_ActionsAvailableReq':
            typ,result=_classify(before,payload)
            if result!='unique':typ,result,*_=_complex_classify(before,payload)
            unique=result=='unique';unit='offered_action_identity'
        elif before['type']=='GREMessageType_SelectTargetsReq' and payload['type']=='ClientMessageType_SelectTargetsResp':
            from .semantic_targets import response
            from .request_parameters import LiteralRefs
            params=before.get('_request_parameters')
            try:
                decoded=response(payload,before,params,LiteralRefs(),())
                # Legacy helper equality permits bool/float == int. Keep its
                # contract, but require typed GRE identity for this statistic.
                unique=type(decoded['payload']['target_idx']) is int
                if unique:unit='member_update_not_final_set'
            except (ValueError,KeyError,TypeError):pass
        self.choice_units[unit] += 1
        if unique:self.choices['historical_choices_uniquely_matched'] += 1
        comparable=False;agree=False
        if (unique and saved is not None and saved['token']==_identity(before) and saved['ordinal']<self.ordinal and
                saved['decision']['status']=='research_preference' and saved['selected'] is not None):
            preferred=saved['selected']
            # MP66's only ActionsAvailable preference is the reused unique Play.
            # Existing flat classifier proves complete simple-row equality; a
            # complex identity or a member update cannot stand for a final plan.
            if (typ in ('ActionType_Pass','ActionType_Play') and preferred['kind']=='engine_action' and
                    preferred['observation']['engine_action_type']=='ActionType_Play' and
                    _classify(before,payload)[1]=='unique'):
                plays=[r for r in before['action_inventory']['simple_shapes'] if r['action_type']=='ActionType_Play']
                comparable=len(plays)==1 and plays[0]['list_position']==preferred['list_position']
                agree=typ=='ActionType_Play'
        if comparable:
            self.choices['comparable_policy_preferences'] += 1
            self.choices['historical_agreements' if agree else 'historical_disagreements'] += 1
        else:self.choices['uncomparable'] += 1

    def apply(self, record):
        self.ordinal += 1;self._consumed_this_record=False
        before=copy.deepcopy(_current_verified_request(self.reducer));saved=self.frozen
        self.tap.prepare(record);self.stage.prepare(record)
        start=time.perf_counter_ns();self.reducer.apply(record);self.stage.after_apply()
        self.timed('reducer_apply_including_freeze',time.perf_counter_ns()-start)
        start=time.perf_counter_ns()
        payload=record.get('payload') if type(record) is dict else None
        mixed=type(record) is dict and any(k in record for k in ('authenticateResponse','greToClientEvent','matchGameRoomStateChangedEvent'))
        self.compare(before,saved,payload,mixed)
        self.timed('evaluation_bookkeeping',time.perf_counter_ns()-start)
        # Existing Publisher/Consumer revoke after every record, not only at requests.
        self.publish()
        current=_current_verified_request(self.reducer)
        if self.frozen is not None and (current is None or _identity(current)!=self.frozen['token'] or self.reducer.error):
            self.frozen=None


def evaluate_shadow_history(path, *, max_history_bytes=64*1024*1024, max_records=100000,
                            actions_available_gates=False, complex_action_intents=False, protocol_evidence=False,
                            current_cost_stages=False, _on_freeze=None):
    """Explicit owner-selected file. Return aggregate history only, no raw trace."""
    if type(max_history_bytes) is not int or not 1<=max_history_bytes<=1024**3 or type(max_records) is not int or not 1<=max_records<=100000:
        raise ValueError('invalid_historical_evaluation_bounds')
    if type(actions_available_gates) is not bool:raise ValueError('invalid_actions_available_gates_flag')
    if type(complex_action_intents) is not bool:raise ValueError('invalid_complex_action_intents_flag')
    if type(protocol_evidence) is not bool or protocol_evidence and not actions_available_gates:
        raise ValueError('protocol_evidence_requires_actions_available_gates')
    if type(current_cost_stages) is not bool:raise ValueError('invalid_current_cost_stages_flag')
    evaluation=_Evaluation(_on_freeze,actions_available_gates,complex_action_intents,protocol_evidence,current_cost_stages);framer=RawFramer();digest=hashlib.sha256();read_bytes=0;limited=False
    with Path(path).open('rb') as stream:
        import os
        initial=os.fstat(stream.fileno())
        if initial.st_size>max_history_bytes:raise ValueError('historical_source_size_limit')
        remaining=initial.st_size
        while remaining:
            start=time.perf_counter_ns();chunk=stream.readline(min(65536,remaining))
            if not chunk:break
            remaining-=len(chunk)
            read_bytes+=len(chunk);digest.update(chunk);evaluation.offset=read_bytes
            records=framer.feed(chunk)
            evaluation.timed('read_framing',time.perf_counter_ns()-start)
            for record in records:
                if evaluation.ordinal>=max_records:limited=True;break
                evaluation.apply(record)
            if limited:break
        final=os.fstat(stream.fileno())
    stable=(initial.st_size,initial.st_mtime_ns)==(final.st_size,final.st_mtime_ns) and not remaining
    if framer.partial or not stable or limited:
        current=_current_verified_request(evaluation.reducer)
        if current is not None:evaluation.end(current)
        evaluation.publish(partial=True);evaluation.frozen=None
    for event in evaluation.publisher.stop('sample_limit'):
        if not evaluation.consumer.accept_event(event):raise ValueError('historical_stop_rejected')
    if evaluation.consumer.current_decision_options()['options']:raise ValueError('historical_stop_retained_options')
    totals={name:sum(v[name] for v in evaluation.counts.values()) for name in COUNTS}
    observed=totals['observed_requests'];evaluable=totals['evaluable_requests']
    timings={name:{**quantiles(values),'observed_samples':evaluation.timing_counts[name],
        'sample_limit':MAX_SAMPLES,'sample_basis':'first_bounded_samples','truncated':evaluation.timing_counts[name]>len(values)}
        for name,values in evaluation.timings.items()}
    code_digest=hashlib.sha256()
    for source in sorted(Path(__file__).resolve().parent.glob('*.py')):
        code_digest.update(source.name.encode('utf8')+b'\0'+source.read_bytes())
    result = {'schema_version':VERSION,'mode':'historical_simulation','live_decision_opportunity':False,
        'versions':{**code_version(),'evaluation_pipeline_source_sha256':code_digest.hexdigest(),
            'policy':'deterministic_shadow.v1','state':15},
        'source':{'sha256_read_bytes':digest.hexdigest(),'bytes_read':read_bytes,'records_processed':evaluation.ordinal,
            'complete':stable and not limited and not framer.partial and not framer.errors,
            'stable_during_read':stable,'record_limit_reached':limited,'partial_record':framer.partial,'framing_errors':framer.errors},
        'denominators':{'request_unit':'unique authenticated current own request, first accepted observation',
            'evaluation_partition':'observed=evaluable+unsupported+invalid; evaluable=preferences+abstentions',
            'expired_or_consumed':'overlapping lifecycle count, not an evaluation category',
            'choice_unit':'strictly paired reducer-consumed submission, one per request; includes member updates',
            'uncomparable':'paired submissions minus comparable preferences; not all requests',
            'gap_labels':'overlapping request counts from returned unresolved codes; not causal attribution',
            'action_categories':'requests containing known positive inventory type labels; multi-label, not absence of unknown types',
            'leases':'synthetic logical clock; no historical wall-time freshness inferred'},
        'totals':totals,'by_request_type':evaluation.counts,
        'rates':{'research_preference_over_observed':totals['research_preferences']/observed if observed else None,
            'abstention_over_observed':totals['abstentions']/observed if observed else None,
            'research_preference_over_evaluable':totals['research_preferences']/evaluable if evaluable else None,
            'comparable_over_historical_choices':evaluation.choices['comparable_policy_preferences']/evaluation.choices['historical_choices_observed'] if evaluation.choices['historical_choices_observed'] else None,
            'agreement_over_comparable':evaluation.choices['historical_agreements']/evaluation.choices['comparable_policy_preferences'] if evaluation.choices['comparable_policy_preferences'] else None},
        'policy_reasons':{k:dict(sorted(v.items())) for k,v in evaluation.reasons.items()},
        'abstention_reasons':{k:dict(sorted(v.items())) for k,v in evaluation.abstention_reasons.items()},
        'evidence_gap_labels':{k:dict(sorted(v.items())) for k,v in evaluation.gaps.items()},
        'action_categories':{k:{'requests_containing_category':evaluation.action_requests[k],
            'gap_labels':dict(sorted(evaluation.action_gaps[k].items()))} for k in sorted(_TYPES)},
        'historical_comparison':{k:evaluation.choices[k] for k in CHOICES},
        'historical_choice_units':dict(sorted(evaluation.choice_units.items())),
        'comparison_scope':'complete simple Play/Pass identity only; target member updates are not final-set comparisons',
        'agreement_is_not_correctness_win_rate_or_legality':True,
        'diagnostics':dict(sorted(evaluation.diagnostics.items())),'timings_ms':timings,
        'timing_scope':'same-process offline; nested stages overlap; shadow API includes cached MP65/currentness checks; not MTGA latency',
        'unknown_full_legal_action_count':None,'read_only':True,**EXECUTION,'P10':'NOT_RUN'}
    if evaluation.action_gates is not None:result['actions_available_gate_analysis']=evaluation.action_gates.report()
    if evaluation.cost_stages is not None:
        c=evaluation.cost_stages
        result['current_cost_stage_evidence']={
            'unit':'unique authenticated current PayCosts request, first accepted observation; rows counted separately',
            **{key:c[key] for key in ('pay_costs_requests_observed','reviewed_nonmana_select_profile',
                'reviewed_mana_payment_stage','unreviewed_cost_shape','local_cost_candidates_observed_requests',
                'local_cost_candidates_unknown_requests','local_cost_candidate_memberships','observed_mana_requirements',
                'observed_payment_action_rows','observed_predictive_auto_tap_solutions',
                'historically_paired_cost_responses','paired_effect_cost_responses','paired_other_cost_child_responses',
                'prior_paired_complex_submissions_observed','cost_requests_with_prior_paired_complex_context')},
            'strictly_associated_parent_cost_stages':0,'explicit_parent_cost_link_verified':False,
            'causal_relationship_unverified_requests':c['pay_costs_requests_observed'],
            'complete_payment_verified':None,'complete_legal_complex_actions':None,
            'scope':'finite current requirement/object and predictive action observations; prior context is temporal only',
            'policy_unchanged':True}
    if evaluation.intent_counts is not None:
        c=evaluation.intent_counts
        observed=c['observed_complex_action_rows'] if not c['inventory_unknown_requests'] else None
        result['complex_action_intent_coverage']={
            'unit':'original active Cast/Activate action row, at first accepted request; overlapping evidence counts',
            'observed_complex_action_rows':observed,
            **{name:c[name] for name in ('returned_parent_rows','reviewed_target_rows',
                'predictive_payment_association_rows','finite_stage_intent_rows','inventory_unknown_requests',
                'intent_evidence_unavailable_requests')},
            'rows_without_reviewed_target_members':observed-c['reviewed_target_rows'] if observed is not None else None,
            'rows_without_reviewed_payment_association':observed-c['predictive_payment_association_rows'] if observed is not None else None,
            'complete_target_constraints_unverified_rows':observed,
            'complete_payment_unverified_rows':observed,
            'full_legal_complex_actions':None,
            'policy_evaluated_before_intent_assembly':True}
    return result
