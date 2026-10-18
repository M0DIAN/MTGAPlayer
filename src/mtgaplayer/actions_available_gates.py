"""Opt-in historical diagnostics over existing frozen evidence, never policy.

Conditions overlap; a static next gate is not a legality/cause assessment.
Only fixed reviewed field names and scalar type classes leave this module.
"""
from collections import Counter

from .decision_advisor import _extract_actions, _graph_issue, _preference, SIMPLE_TYPE_POLICY
from .cast_activate_associations import _prompt

VERSION = 'mtgaplayer.actions-available-gate-analysis.v1'
REQUEST = 'GREMessageType_ActionsAvailableReq'
MESSAGE = frozenset(('type', 'systemSeatIds', 'msgId', 'gameStateId', 'actionsAvailableReq'))
PAYLOAD = frozenset(('actions', 'inactiveActions'))
FIELDS = {'message': MESSAGE | {'prompt'}, 'payload': PAYLOAD,
          'message.prompt': frozenset(('promptId', 'parameters'))}
CONDITIONS = ('unknown_request_fields', 'complex_cast_or_activate', 'non_simple_actions',
    'multiple_active_rows', 'candidate_source_incomplete', 'structurally_unreviewed',
    'reviewed_local_candidate_present', 'complete_legal_candidate_missing',
    'tactical_basis_unverified', 'source_visibility_unverified',
    'source_card_identity_disagreement', 'source_card_identity_unknown',
    'current_binding_problem', 'graph_conflict')


def _type(value):
    return {dict:'object', list:'array', str:'string', int:'integer', bool:'boolean',
            float:'number', type(None):'null'}.get(type(value), 'other')


class ActionsAvailableGates:
    def __init__(self):
        self.observed = 0
        self.primary = Counter(); self.static = Counter(); self.fields = Counter()
        self.presence = {k:Counter() for k in ('other_payload_fields_present',
            'other_message_fields_present', 'unknown_request_fields_present')}
        self.conditions = {k:Counter() for k in CONDITIONS}
        self.overlap = Counter(); self.categories = Counter(); self.coverage = Counter()
        self.prompt = Counter(); self.unknown_field_requests = Counter()
        self.inventory_valid_requests = self.overlap_omitted = 0

    def _fields(self, value, scope):
        if type(value) is not dict:return
        unknown = False
        for key, child in value.items():
            name = key if key in FIELDS[scope] else '_unreviewed_field'
            self.fields[(scope, name, _type(child))] += 1
            unknown |= name == '_unreviewed_field'
        if unknown:self.unknown_field_requests[scope] += 1

    def observe(self, message, request, options, decision, state, ref):
        if request['type'] != REQUEST:return
        self.observed += 1
        self.primary[decision['reason'] or 'unspecified'] += 1
        inventory = request.get('action_inventory')
        projection = state['legal_action_space']['immediate_frontier']['projection'] if state else None
        for name in self.presence:
            source = projection if name == 'unknown_request_fields_present' else inventory
            value = source.get(name) if type(source) is dict else None
            self.presence[name]['true' if value is True else 'false' if value is False else 'unknown'] += 1
        self._fields(message, 'message')
        self._fields(message.get('actionsAvailableReq'), 'payload')
        if 'prompt' in message:
            self._fields(message['prompt'], 'message.prompt')
            try:_prompt(message['prompt'])
            except (ValueError, TypeError, KeyError):self.prompt['unreviewed_shape'] += 1
            else:self.prompt['reviewed_nonzero_uint32_parameters_absent_shape'] += 1
            # Shape is not proof of prompt routing or that it is display-only.
            self.prompt['routing_meaning_still_unknown'] += 1
        else:self.prompt['absent'] += 1
        facts = dict.fromkeys(CONDITIONS)
        facts['unknown_request_fields'] = (projection.get('unknown_request_fields_present')
            if type(projection) is dict and type(projection.get('unknown_request_fields_present')) is bool else None)
        binding = options.get('request_binding')
        facts['current_binding_problem'] = not (state is not None and binding == state['binding'] and
            options.get('source_snapshot_ref') == ref == decision.get('source_snapshot_ref') and
            decision.get('request_binding') == binding)
        facts['tactical_basis_unverified'] = bool(set(decision['unresolved']) &
            {'strategic_utility_unknown', 'effects_and_tactics_unverified'})
        coverage = options['coverage']; sources = coverage['sources']
        incomplete = coverage['truncated'] is True or coverage['omitted_constructed_options'] > 0 or any(
            s['truncated'] is True or s['omitted_constructed_options'] > 0 for s in sources)
        # Complete offered rows and full legal proposals are different domains.
        facts['candidate_source_incomplete'] = True if incomplete else None
        reviewed = [o for o in options['options'] if o['evidence_level'] == 'known_constraints_verified']
        facts['reviewed_local_candidate_present'] = bool(reviewed)
        self.coverage['requests_with_reviewed_local_options' if reviewed else 'requests_without_reviewed_local_options'] += 1
        for kind in {o['kind'] for o in reviewed}:self.coverage['requests_with_local_kind.'+kind] += 1
        # No existing field enumerates complete legal Cast/Activate proposals.
        # Unknown is not zero and never turns membership into a full action.
        facts['complete_legal_candidate_missing'] = None
        try:
            rows = _extract_actions(state); issue = _graph_issue(state, rows)
        except (ValueError, TypeError, KeyError, IndexError):
            self.static['inventory_not_established'] += 1
        else:
            self.inventory_valid_requests += 1
            types = {r['engine_action_type'] for r in rows}
            for name in ('ActionType_Cast','ActionType_Activate','ActionType_Play'):
                if name in types:self.categories[name] += 1
            facts.update(complex_cast_or_activate=bool(types & {'ActionType_Cast','ActionType_Activate'}),
                non_simple_actions=bool(types-{'ActionType_Pass','ActionType_Play'}),
                multiple_active_rows=len(rows)>1,
                structurally_unreviewed=any(not r['structurally_interpreted'] for r in rows),
                source_visibility_unverified=any(r['source_link_status'] not in ('visible_unique','not_applicable') for r in rows),
                source_card_identity_disagreement=any(r.get('source_card_identity_agreement') is False for r in rows),
                source_card_identity_unknown=any(r['source_link_status']!='not_applicable' and
                    r.get('source_card_identity_agreement') is None for r in rows), graph_conflict=issue is not None)
            if not incomplete:
                count = coverage['engine_offered_count']
                facts['candidate_source_incomplete'] = (False if type(count) is int and count==len(rows) and
                    len([o for o in options['options'] if o['kind']=='engine_action'])==len(rows) else None)
            _, reason = _preference(rows, SIMPLE_TYPE_POLICY, True, issue, False)
            self.static[reason or 'research_preference_under_static_assumptions'] += 1
        for name, value in facts.items():
            self.conditions[name]['true' if value is True else 'false' if value is False else 'unknown'] += 1
        # At most 2**14 distinct fixed masks; input already capped by history.
        mask = tuple(name for name in CONDITIONS if facts[name] is True)
        if mask in self.overlap or len(self.overlap)<128:self.overlap[mask] += 1
        else:self.overlap_omitted += 1

    def report(self):
        tri = lambda counts: {k:counts[k] for k in ('true','false','unknown')}
        return {'schema_version':VERSION, 'actions_available_observed':self.observed,
            'unit':'distinct authenticated current own ActionsAvailable request at first acceptance',
            'primary_refusal_distribution':dict(sorted(self.primary.items())),
            'unknown_request_field_presence':{k:tri(v) for k,v in self.presence.items()},
            'field_types':[{'scope':s,'field':f,'type':t,'occurrences':n}
                for (s,f,t),n in sorted(self.fields.items())],
            'unreviewed_field_name_requests':dict(sorted(self.unknown_field_requests.items())),
            'complex_action_presence':{k:{'true':self.categories[k],
                'false':self.inventory_valid_requests-self.categories[k],
                'unknown':self.observed-self.inventory_valid_requests} for k in
                ('ActionType_Cast','ActionType_Activate','ActionType_Play')},
            'overlapping_gate_counts':{k:tri(v) for k,v in self.conditions.items()},
            'multiple_competing_actions':tri(self.conditions['multiple_active_rows']),
            'competition_scope':'multiple offered active rows, not multiple verified complete legal actions',
            'structurally_unreviewed_requests':tri(self.conditions['structurally_unreviewed']),
            'reviewed_candidate_coverage':{'unit':'requests with returned locally verified options; kinds kept separate',
                **dict(sorted(self.coverage.items())), 'complete_legal_candidate_count':None,
                'legal_domain_complete':None},
            'tactical_basis_unverified':tri(self.conditions['tactical_basis_unverified']),
            'overlap_patterns':[{'conditions':list(mask),'requests':n} for mask,n in sorted(self.overlap.items())],
            'overlap_pattern_limit':128,'overlap_requests_omitted':self.overlap_omitted,
            'static_counterfactual_after_field_gate':dict(sorted(self.static.items())),
            'static_analysis_scope':'existing Advisor with unknown-field argument false; no state mutation, legality validation or causal benefit',
            'field_semantics_reviewed':{'envelope_identity':'existing authenticated reducer gate',
                'actions_inventory':'existing typed active/inactive observation; no complete legality',
                'prompt_structure':dict(sorted(self.prompt.items())),
                'prompt_reference':'MP61 finite offered associations only, not general display-only semantics'},
            'field_semantics_still_unknown':{'prompt_routing_or_request_meaning':self.prompt['routing_meaning_still_unknown'],
                'unreviewed_field_names':dict(sorted(self.unknown_field_requests.items())),
                'display_only_classification_proven':False},
            'conditions_are_not_causal_attribution':True,'default_policy_changed':False,
            'continuity_scope':'accepted authenticated current requests only; prior rejected states are outside this denominator; parent diagnostics retain continuity errors',
            'complete_legality_verified':False,'read_only':True,'input_sent':False}
