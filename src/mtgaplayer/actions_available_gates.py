"""Opt-in historical diagnostics over existing frozen evidence, never policy.

Conditions overlap; a static next gate is not a legality/cause assessment.
Only fixed reviewed field names and scalar type classes leave this module.
"""
from collections import Counter
import copy
import time

from .decision_advisor import _extract_actions, _graph_issue, _preference, SIMPLE_TYPE_POLICY
from .cast_activate_associations import _prompt
from .decision_consumer import EXECUTION

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
PROTOCOL_VERSION = 'mtgaplayer.actions-protocol-observation.v1'
ROUTES = ('cannot_take_action', 'opening_hand', 'all_resolution_casts')


def _and(values):
    return False if False in values else True if all(v is True for v in values) else None


def _protocol_observation(message, request, options, decision, state, ref, rows):
    """Ephemeral facts at the existing authenticated historical freeze only.

    This consumes the existing inventory, not a second parser or currentness
    authority. A detached historical result never grants a live opportunity.
    Static predicates refer only to the MP61 inspected build, not running UI.
    """
    from .cast_target_members import _equal
    from .semantic_cast import action
    from .request_parameters import LiteralRefs
    from .semantic_samples import IDS, BOOLS, PARAMS
    from .raw_log import _OBSERVED_ACTION_TYPES
    result = {'schema_version': PROTOCOL_VERSION, 'status': 'insufficient_evidence',
        'scope': 'frozen_authenticated_historical_request_only',
        'request_binding': None, 'source_snapshot_ref': None, 'active_action_rows': None,
        'prompt_structure_verified': False, 'prompt_parameters_present': None,
        'finite_route_predicates_checked': False, 'reviewed_routes': dict.fromkeys(ROUTES),
        'cannot_take_action_inputs': None, 'general_prompt_semantics_unknown': True,
        'loop_roundtrip_assets_unknown': True, 'runtime_route_observed': False,
        'final_route': None, 'float_mana_rows': None, 'unclassified_action_rows': None,
        'complete_legality_verified': False, 'response_encoding_verified': False,
        'execution_ready': False, 'read_only': True, **EXECUTION}
    if state is None or type(rows) is not list or type(ref) is not dict:return result
    binding=state['binding']; legacy=request.get('binding'); body=message.get('actionsAvailableReq')
    expected={'generation':binding['source_generation'], **{k:binding[k] for k in
        ('match','game','game_state_id','self_seat')}, 'ownership_verified':True}
    if (not _equal(legacy,expected) or request.get('current') is not True or
        request.get('_continuity_verified') is not True or request['type'] != REQUEST or
        binding['request_type'] != REQUEST or message.get('type') != REQUEST or
        not _equal(options['request_binding'],binding) or not _equal(decision['request_binding'],binding) or
        not _equal(ref,options['source_snapshot_ref']) or not _equal(ref,decision['source_snapshot_ref']) or
        not _equal(ref.get('binding'),binding) or
        type(message.get('msgId')) is not int or not _equal(message['msgId'],binding['request_id']) or
        type(request['id']) is not int or not _equal(request['id'],binding['request_id']) or
        type(message.get('gameStateId')) is not int or not _equal(message['gameStateId'],binding['game_state_id']) or
        not _equal(message.get('systemSeatIds'),[binding['self_seat']]) or
        type(body) is not dict or type(body.get('actions')) is not list):return result
    actions=body['actions']; inventory=request.get('action_inventory')
    if (type(inventory) is not dict or type(inventory.get('offered_count')) is not int or
        not 0 <= len(rows) <= 256 or len(rows) != len(actions) or len(rows) != inventory['offered_count']):return result
    # Reconcile to the checked original inventory; never filter or deduplicate.
    for position,(raw,row) in enumerate(zip(actions,rows)):
        if type(raw) is not dict or type(row['list_position']) is not int or row['list_position'] != position:return result
        typ=raw.get('actionType')
        label=typ if type(typ) is str and typ in _OBSERVED_ACTION_TYPES else '_unrecognized_action_type'
        if row['engine_action_type'] != label:return result
    result.update(status='observed',request_binding=copy.deepcopy(binding),source_snapshot_ref=copy.deepcopy(ref),
        active_action_rows=len(rows),finite_route_predicates_checked=True,
        unclassified_action_rows=sum(r['engine_action_type']=='_unrecognized_action_type' for r in rows))
    prompt=message.get('prompt')
    result['prompt_parameters_present']='parameters' in prompt if type(prompt) is dict else None
    try:_prompt(prompt)
    except (ValueError,TypeError,KeyError):pass
    else:result['prompt_structure_verified']=True
    # Unknown cancellation/resolving inputs stay unknown; no proto-default guess.
    cancel=message.get('allowCancel')
    cancel_no=True if type(cancel) is str and cancel=='AllowCancel_No' else (
        False if type(cancel) is str and cancel=='AllowCancel_Abort' else None)
    inactive=inventory['inactive_count']
    prompt_match=prompt['promptId']==1134 if result['prompt_structure_verified'] else None
    inputs={'inactive_positive':inactive>0 if type(inactive) is int else None,
        'cancellation_is_no':cancel_no, 'active_count_is_one':len(rows)==1,
        'sole_action_is_pass':len(rows)==1 and rows[0]['engine_action_type']=='ActionType_Pass',
        'resolving_card_present':None, 'prompt_matches_reviewed_constant':prompt_match}
    # OR with an unobserved resolving-card input is true only when prompt matches.
    resolving_or_prompt=True if prompt_match is True else None
    result['cannot_take_action_inputs']=inputs
    result['reviewed_routes']['cannot_take_action']=_and([
        inputs[k] for k in ('inactive_positive','cancellation_is_no','active_count_is_one','sole_action_is_pass')
    ]+[resolving_or_prompt])
    opening=any(type(a.get('actionType')) is str and a['actionType']=='ActionType_OpeningHandAction' for a in actions)
    result['reviewed_routes']['opening_hand']=True if opening else (
        False if inventory['type_labels_complete'] is True else None)
    # These known types fail ActionExtensions.IsCastAction in the inspected code.
    # Absence of such a counterexample does not establish resolution context.
    if any(r['engine_action_type'] in ('ActionType_Activate','ActionType_Activate_Mana',
        'ActionType_FloatMana','ActionType_Play') for r in rows):
        result['reviewed_routes']['all_resolution_casts']=False
    floats=[]; whitelisted={'actionType',*IDS,*BOOLS,*PARAMS}
    for position,raw in enumerate(actions):
        if type(raw.get('actionType')) is not str or raw['actionType']!='ActionType_FloatMana':continue
        strict=False
        try:action(raw,LiteralRefs(),())
        except (ValueError,TypeError,KeyError):pass
        else:strict=True
        provided=sorted(k for k in IDS if k in raw)
        floats.append({'list_position':position,'strict_bare_literal_verified':strict,
            'provided_fields':sorted(k for k in raw if k in whitelisted),
            'unreviewed_fields_present':bool(set(raw)-whitelisted),
            'field_types':{k:_type(raw[k]) for k in sorted(set(raw)&whitelisted)},
            'provided_source_fields':provided,'absent_source_fields':sorted(set(IDS)-set(provided)),
            'source_reference_status':'not_supplied' if not provided else 'explicit_fields_observed',
            'source_applicability':None,'action_semantics_verified':False,
            'payment_legality_verified':False,'response_encoding_verified':False,
            'complete_legality_verified':False,'execution_ready':False, **EXECUTION})
    result['float_mana_rows']=floats
    return result


def _type(value):
    return {dict:'object', list:'array', str:'string', int:'integer', bool:'boolean',
            float:'number', type(None):'null'}.get(type(value), 'other')


class ActionsAvailableGates:
    def __init__(self, protocol_evidence=False):
        if type(protocol_evidence) is not bool:raise ValueError('invalid_protocol_evidence_flag')
        self.protocol = Counter() if protocol_evidence else None
        self.protocol_routes = {k:Counter() for k in ROUTES} if protocol_evidence else None
        self.protocol_types = Counter(); self.protocol_elapsed_ns=0
        self.observed = 0
        self.primary = Counter(); self.static = Counter(); self.fields = Counter()
        self.presence = {k:Counter() for k in ('other_payload_fields_present',
            'other_message_fields_present', 'unknown_request_fields_present')}
        self.conditions = {k:Counter() for k in CONDITIONS}
        self.overlap = Counter(); self.categories = Counter(); self.coverage = Counter()
        self.prompt = Counter(); self.unknown_field_requests = Counter()
        self.row_gaps = {k:Counter() for k in ('structurally_unreviewed',
            'source_visibility_unverified', 'source_card_identity_unknown')}
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
        rows=None
        try:
            rows = _extract_actions(state); issue = _graph_issue(state, rows)
        except (ValueError, TypeError, KeyError, IndexError):
            self.static['inventory_not_established'] += 1
        else:
            self.inventory_valid_requests += 1
            types = {r['engine_action_type'] for r in rows}
            for name in ('ActionType_Cast','ActionType_Activate','ActionType_Play'):
                if name in types:self.categories[name] += 1
            predicates = {'structurally_unreviewed':lambda r:not r['structurally_interpreted'],
                'source_visibility_unverified':lambda r:r['source_link_status'] not in ('visible_unique','not_applicable'),
                'source_card_identity_unknown':lambda r:r['source_link_status']!='not_applicable' and
                    r.get('source_card_identity_agreement') is None}
            for name, predicate in predicates.items():
                for kind in {r['engine_action_type'] for r in rows if predicate(r)}:
                    self.row_gaps[name][kind] += 1
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
        if self.protocol is not None:
            start=time.perf_counter_ns()
            observation=_protocol_observation(message,request,options,decision,state,ref,rows)
            self._protocol_counts(observation)
            self.protocol_elapsed_ns=time.perf_counter_ns()-start
        for name, value in facts.items():
            self.conditions[name]['true' if value is True else 'false' if value is False else 'unknown'] += 1
        # At most 2**14 distinct fixed masks; input already capped by history.
        mask = tuple(name for name in CONDITIONS if facts[name] is True)
        if mask in self.overlap or len(self.overlap)<128:self.overlap[mask] += 1
        else:self.overlap_omitted += 1

    def report(self):
        tri = lambda counts: {k:counts[k] for k in ('true','false','unknown')}
        result = {'schema_version':VERSION, 'actions_available_observed':self.observed,
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
            'row_gap_categories':{'unit':'requests with at least one row of given engine type; overlapping, not causal; only established inventories',
                'inventory_unknown_requests':self.observed-self.inventory_valid_requests,
                'conditions':{k:dict(sorted(v.items())) for k,v in self.row_gaps.items()}},
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
        if self.protocol is not None:result['protocol_evidence']=self._protocol_report()
        return result

    def _protocol_counts(self, observation):
        counts=self.protocol
        if observation['status']!='observed':
            counts['evidence_unavailable_requests']+=1
            for route in self.protocol_routes.values():route['unknown']+=1
            return
        counts['authenticated_inventory_requests']+=1
        counts['prompt_structure_verified_requests']+=observation['prompt_structure_verified']
        finite=False
        for name,value in observation['reviewed_routes'].items():
            self.protocol_routes[name]['excluded' if value is False else 'eligible' if value is True else 'unknown']+=1
            finite |= value is not None
        counts['requests_with_finite_route_predicate_result']+=finite
        counts['unclassified_action_rows']+=observation['unclassified_action_rows']
        rows=observation['float_mana_rows']; counts['float_mana_affected_requests']+=bool(rows)
        counts['float_mana_offered_rows']+=len(rows)
        for row in rows:
            counts['float_mana_strict_bare_literals' if row['strict_bare_literal_verified'] else 'float_mana_other_observed_shapes']+=1
            counts['float_mana_rows_with_explicit_source_fields']+=bool(row['provided_source_fields'])
            for field,typ in row['field_types'].items():self.protocol_types[(field,typ)]+=1

    def _protocol_report(self):
        c=self.protocol;unknown=c['evidence_unavailable_requests']
        return {'schema_version':PROTOCOL_VERSION,'unit':'requests except explicitly labelled active-row counts',
            'actions_available_requests':self.observed,
            **{k:c[k] for k in ('authenticated_inventory_requests','evidence_unavailable_requests',
                'prompt_structure_verified_requests','requests_with_finite_route_predicate_result')},
            **{k:c[k] if not unknown else None for k in ('float_mana_offered_rows','float_mana_strict_bare_literals',
                'float_mana_other_observed_shapes','float_mana_rows_with_explicit_source_fields',
                'float_mana_affected_requests','unclassified_action_rows')},
            'float_mana_source_applicability_verified_rows':None,
            'float_mana_source_applicability_unknown_rows':c['float_mana_offered_rows'] if not unknown else None,
            'float_mana_field_types':[{'field':k,'type':t,'rows':v} for (k,t),v in sorted(self.protocol_types.items())],
            'reviewed_route_predicates':{name:{k:counts[k] for k in ('excluded','eligible','unknown')}
                for name,counts in self.protocol_routes.items()},
            'prompt_general_routing_unknown_requests':self.observed,
            'runtime_route_observed':False,'final_route':None,'source_applicability':None,
            'reference_scope':'MP61 inspected build0.1.14517.1329972 and pinned public descriptor; static predicates, not running UI',
            'source_reference_absence_does_not_prove_non_applicability':True,
            'complete_legality_verified':False,'response_encoding_verified':False,'execution_ready':False,
            'default_policy_changed':False,'read_only':True,**EXECUTION}
