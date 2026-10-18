"""Count-only frozen-policy comparison on the existing bounded RevisionStage.

No parser, second ledger, state, target solver or current permission. Incomplete
and rejected attempts stay uncomparable; unlinked selected requests are not
silently grouped into invented episodes.
"""
from collections import Counter
import time

from . import semantic_targets as targets
from .semantic_activate_targets import _same
from .target_revision import _selection
from .choice_continuation import _binding
from .response_evidence import _paired_response, _paired_terminal_submit
from .decision_consumer import EXECUTION

COUNTS = ('target_requests_observed','first_stage_select_requests','current_select_domain_absent_requests',
    'current_select_domain_unknown_requests','explicit_quantity_requests','selected_count_observed_requests',
    'current_selected_literal_requests','only_unselect_requests','multiple_complete_proposal_requests',
    'locally_reviewed_option_requests','request_parameters_unavailable',
    'paired_selection_response_envelopes','strictly_paired_selection_updates','unreviewed_selection_response_envelopes',
    'verified_revised_stage_relationships','strictly_paired_terminal_submits','historical_reviewed_target_sets_submitted',
    'comparable_shadow_target_preferences','historical_target_agreements','historical_target_disagreements')


class TargetStageCompletions:
    def __init__(self):
        self.counts = Counter(); self.reasons = Counter(); self.completed_sources = Counter()
        self.elapsed_ns = 0

    def freeze(self, request, options, decision, revision):
        start=time.perf_counter_ns();c=self.counts;c['target_requests_observed'] += 1
        self.reasons[decision['reason']] += 1
        params=request.get('_request_parameters')
        if params is None:
            c['request_parameters_unavailable'] += 1;c['current_select_domain_unknown_requests'] += 1
        else:
            entries=params.get('entries')
            select=bool(entries) and all(row['legal_action']==targets.SELECT for row in entries)
            c['first_stage_select_requests' if select else 'current_select_domain_absent_requests'] += 1
            c['explicit_quantity_requests'] += all(params[k] is not None for k in ('min_targets','max_targets'))
            c['selected_count_observed_requests'] += params['selected_count'] is not None
            c['current_selected_literal_requests'] += targets.literal_selected(params) is not None
            c['only_unselect_requests'] += bool(entries) and all(row['legal_action']==targets.UNSELECT for row in entries)
        c['multiple_complete_proposal_requests'] += sum(o['kind']=='final_target_set' for o in options['options']) > 1
        c['locally_reviewed_option_requests'] += bool(options['coverage']['reviewed_candidate_count'])
        binding=options['request_binding'];ref=options['source_snapshot_ref']
        if binding is not None and ref is not None and _same(ref['binding'],binding):
            selected=[o for o in options['options'] if o['option_key']==decision['preferred_option_key']]
            revision.freeze_shadow(binding,ref,decision,selected[0] if len(selected)==1 else None)
            if revision.completion_context is not None and _same(
                    revision.completion_context['revised_request_binding'],binding):
                c['verified_revised_stage_relationships'] += 1
        self.elapsed_ns += time.perf_counter_ns()-start

    def response(self,reducer,before,payload,mixed):
        start=time.perf_counter_ns()
        if not mixed and before is not None and before['type']=='GREMessageType_SelectTargetsReq' and type(payload) is dict:
            if _paired_response(reducer,before,payload):
                self.counts['paired_selection_response_envelopes'] += 1
                try:_selection(payload,_binding(reducer,before),before['_request_parameters'])
                except (ValueError,KeyError,TypeError):self.counts['unreviewed_selection_response_envelopes'] += 1
                else:self.counts['strictly_paired_selection_updates'] += 1
            if _paired_terminal_submit(reducer,before,payload):self.counts['strictly_paired_terminal_submits'] += 1
        self.elapsed_ns += time.perf_counter_ns()-start

    def completed(self,completion):
        start=time.perf_counter_ns()
        if completion is not None:
            first=completion['first_request_binding'];revised=completion['revised_request_binding']
            ref=completion.get('revised_snapshot_ref')
            if (ref is not None and _same(ref['binding'],revised) and
                    completion['update_record'] < completion['revised_record'] == completion['revised_frozen_record'] < completion['terminal_record']):
                self.counts['historical_reviewed_target_sets_submitted'] += 1
                self.completed_sources[completion['source_kind']] += 1
                frozen=completion['frozen_shadow']
                if self._comparable(frozen,completion,first):
                    self.counts['comparable_shadow_target_preferences'] += 1
                    chosen=frozen['selected_option']['proposal']['proposed_final_target_set']['object_refs']
                    self.counts['historical_target_agreements' if _same(chosen,completion['selected_object_refs']) else
                        'historical_target_disagreements'] += 1
        self.elapsed_ns += time.perf_counter_ns()-start

    @staticmethod
    def _comparable(frozen,completion,first):
        if frozen is None or frozen['selected_option'] is None:return False
        from .shadow_decision import POLICY
        decision=frozen['decision'];option=frozen['selected_option'];proposal=option['proposal'];ref=frozen['snapshot_ref']
        if not (frozen['record_ordinal'] < completion['update_record'] and
                _same(frozen['binding'],first) and _same(ref['binding'],first) and
                _same(decision['request_binding'],first) and _same(decision['source_snapshot_ref'],ref) and
                decision['status']=='research_preference' and decision['policy_version']==POLICY and
                option['kind']=='final_target_set' and option['evidence_level']=='known_constraints_verified' and
                option['research_eligible'] is True and _same(option['option_key'],decision['preferred_option_key']) and
                _same(option['request_binding'],first) and _same(option['source_snapshot_ref'],ref) and
                proposal is not None and _same(proposal['request_identity'],first) and
                _same(proposal['source_snapshot_ref'],ref) and
                all(option[k] is False and decision[k] is False for k in EXECUTION)):
            return False
        proposed=proposal['proposed_final_target_set']
        return (targets.check_final_set(completion['first_constraints'],proposed)[0]=='verified_known_constraints' and
            _same(proposed['source_object_ref'],completion['source_object_ref']) and
            _same(proposed['target_idx'],completion['target_idx']))

    def report(self):
        c=self.counts
        return {'schema_version':'mtgaplayer.historical-target-stage-completions.v1',
            'units':{'requests':'unique authenticated own request, first accepted observation',
                'updates_and_submits':'strictly paired and reducer-consumed submissions; not server acceptance',
                'episodes':'one reviewed first-stage Select request starts a bounded attempt; selected-only requests are unlinked',
                'comparison':'only completed, linked, frozen-before-update full-set preference episodes',
                'overlap':'classification counts overlap; do not add request/submission/episode units'},
            **{key:c[key] for key in COUNTS},'primary_policy_reasons':dict(sorted(self.reasons.items())),
            'completed_source_types':dict(sorted(self.completed_sources.items())),
            'uncomparable_target_episodes':c['first_stage_select_requests']-c['comparable_shadow_target_preferences'],
            'episodes_without_reviewed_terminal':c['first_stage_select_requests']-c['historical_reviewed_target_sets_submitted'],
            'terminal_submits_without_reviewed_episode':c['strictly_paired_terminal_submits']-c['historical_reviewed_target_sets_submitted'],
            'selected_literal_requests_without_verified_revision':c['current_selected_literal_requests']-c['verified_revised_stage_relationships'],
            'unknown_unlinked_episode_count':None,
            'complete_target_legality_verified':False,'complete_action_legality_verified':False,
            'agreement_is_not_correctness_or_optimality':True,'historical_only':True,'read_only':True,**EXECUTION}
