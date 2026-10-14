"""Opt-in, read-only constraints on observed GRE choices.

The graph describes request structure and historical temporal edges. It never
enumerates legal parameter combinations or encodes a client response.
"""
from typing import Literal, TypedDict

from .semantic_evidence import _candidate_parameter_bounds


_COMPLEX = frozenset({
    'ActionType_Cast', 'ActionType_Activate', 'ActionType_Activate_Mana',
})
_PARAMETERS = ('targets', 'manaCost', 'manaPaymentOptions',
               'manaSelections', 'autoTapSolution')
_RELATIONS = {'targets': 'target_slots',
              'manaSelections': 'mana_selection_links',
              'autoTapSolution': 'auto_tap_mana_links'}


class ChoiceConstraint(TypedDict):
    action_key: dict
    parameter_category: str
    observed_structure: dict
    observed_quantity_or_domain: dict
    verified_structural_constraints: list[str]
    unresolved: list[str]
    provenance: dict
    validation_level: Literal['observed_structure', 'unsupported',
                              'verified_known_constraints', 'violated_known_constraints',
                              'insufficient_evidence', 'unsupported_protocol']


class ActionNode(TypedDict):
    action_key: dict
    action_identity: dict
    constraints: list[ChoiceConstraint]
    observed_parameters: list[str]
    unresolved_parameters: list[str]
    observed_successors: list[dict]
    successor_observation_status: str
    legal_choice_verified: bool
    response_encoding_verified: bool
    execution_ready: bool
    input_sent: bool


def _constraint(key, name, shape, relation, valid):
    quantity = {'container_element_count': shape.get(
        'auto_tap_actions_count' if name == 'autoTapSolution' else 'element_count')}
    verified = []
    unresolved = []
    if isinstance(relation, dict):
        quantity['total'] = relation.get('total')
        quantity['examined'] = relation.get('examined')
        quantity['truncated'] = relation.get('truncated')
        if name == 'targets':
            quantity['groups'] = [{
                'position': item.get('position'),
                'target_idx_raw': item.get('target_idx_raw'),
                'target_count': item.get('target_count'),
            } for item in relation.get('entries', [])]
            if valid and all(item.get('valid_shape') is True
                             for item in relation.get('entries', [])):
                verified.append('raw_target_groups_have_index_and_array_count')
            unresolved.append('target_domain_and_combination_legality')
        else:
            quantity['active_mana_position_links'] = [{
                'position': item.get('position'),
                'status': item.get('status'),
                'active_mana_position': item.get('active_mana_position')
                if item.get('status') == 'unique_pair' else None,
            } for item in relation.get('entries', [])]
            if valid:
                verified.append('same_request_raw_mana_identity_pair_equality_only')
            unresolved.append('mana_payment_legality')
    elif name in ('manaCost', 'manaPaymentOptions'):
        unresolved.append('cost_contents_and_payment_legality')
    if name == 'manaSelections':
        unresolved.append('mana_selection_semantics')
    if name == 'autoTapSolution':
        unresolved.append('auto_tap_execution')
    if valid:
        verified.append('container_kind_and_count_observed')
    else:
        unresolved.append('malformed_or_truncated_structure')
    return {
        'action_key': key, 'parameter_category': name,
        'observed_structure': {'kind': shape.get('kind')},
        'observed_quantity_or_domain': quantity,
        'verified_structural_constraints': verified,
        'unresolved': sorted(set(unresolved)),
        'provenance': {'source': 'current_authenticated_own_gre_request',
                       'field': 'actionsAvailableReq.actions.' + name,
                       'raw_relation': _RELATIONS.get(name)},
        'validation_level': 'observed_structure' if valid else 'unsupported',
    }


def _node(row, key, observed_shapes, structurally_interpreted, unresolved):
    params = row.get('opaque_parameter_shapes')
    relations = row.get('raw_relations')
    valid, truncated = _candidate_parameter_bounds(row, {
        'known_parameter_shapes': observed_shapes})
    if not isinstance(params, dict) or not isinstance(relations, dict):
        return None
    constraints = []
    for name in _PARAMETERS:
        if name not in params:
            continue
        shape = params[name]
        if not isinstance(shape, dict):
            return None
        relation = relations.get(_RELATIONS[name]) if name in _RELATIONS else None
        constraints.append(_constraint(key, name, shape, relation,
                                       valid and not truncated and
                                       structurally_interpreted))
    unknown = set(unresolved)
    unknown.update(('mode_choice_unverified', 'x_value_unverified',
                    'additional_cost_choice_unverified',
                    'response_encoding_unverified'))
    if not valid or truncated:
        unknown.add('parameter_structure_incomplete')
    return {
        'action_key': key,
        'action_identity': {'engine_action_type': row['action_type'],
                            'raw_identifiers': row.get('raw_identifiers', {}).copy(),
                            'raw_flags_observed_not_discriminators':
                            row.get('raw_flags', {}).copy()},
        'constraints': constraints,
        'observed_parameters': [name for name in _PARAMETERS if name in params],
        'unresolved_parameters': sorted(unknown),
        'observed_successors': [],
        'successor_observation_status': 'unknown',
        'legal_choice_verified': False,
        'response_encoding_verified': False,
        'execution_ready': False,
        'input_sent': False,
    }


def build_historical_source_graph(request):
    """Freeze a matched own request as an offline local graph.

    Caller must first apply the response_evidence exact request/response and
    reducer-consumption gate. This API is not used by count-only CLI output.
    """
    binding = request.get('binding') if isinstance(request, dict) else None
    inventory = request.get('action_inventory') if isinstance(request, dict) else None
    if (not isinstance(binding, dict) or
            binding.get('ownership_verified') is not True or
            request.get('current') is not True or
            request.get('type') != 'GREMessageType_ActionsAvailableReq' or
            not isinstance(inventory, dict)):
        return None
    offered = inventory.get('offered_count')
    rows = inventory.get('complex_raw_shapes')
    frontier_rows = inventory.get('_frontier_rows')
    if (type(offered) is not int or not 0 <= offered <= 256 or
            not isinstance(rows, list) or not isinstance(frontier_rows, list) or
            len(frontier_rows) != offered):
        return None
    identity = {name: binding.get(name) for name in
                ('generation', 'match', 'game', 'game_state_id', 'self_seat')}
    identity['request_id'] = request.get('id')
    nodes, seen = [], set()
    for row in rows:
        if not isinstance(row, dict):
            return None
        position = row.get('list_position')
        if (type(position) is not int or not 0 <= position < offered or
                position in seen or row.get('action_type') not in _COMPLEX or
                not isinstance(frontier_rows[position], dict) or
                frontier_rows[position].get('list_position') != position or
                frontier_rows[position].get('action_type') != row['action_type']):
            return None
        seen.add(position)
        key = {'request_identity': identity.copy(), 'list_position': position}
        frontier = frontier_rows[position]
        node = _node(row, key, frontier.get('known_parameter_shapes'),
                     frontier.get('structurally_interpreted') is True,
                     ('future_choice_request_unobserved',))
        if node is None:
            return None
        nodes.append(node)
    return {
        'schema_version': 'mtga-choice-graph-v1',
        'request_identity': identity,
        'immediate_frontier': {'completeness': 'partial',
                               'engine_active_action_count': offered},
        'expanded_choices': {'completeness': 'unknown',
                             'legal_combinations': None},
        'action_nodes': nodes,
        'observed_successors': [],
        'successor_observation_status': 'unknown',
        'unresolved': ['legal_parameter_combinations_unverified',
                       'successor_causality_unverified'],
        'provenance': {'source': 'historical_authenticated_own_gre_request',
                       'matched_client_submission_only': True},
        'completeness': 'partial',
        'legal_choice_verified': False,
        'response_encoding_verified': False,
        'execution_ready': False,
        'input_sent': False,
        'read_only': True,
    }


def build_choice_graph(decision_input, action_frontier, request):
    """Project bounded complex constraints only for the current request.

    The caller obtains decision_input and frontier from the same reducer
    snapshot. Identity mismatches and unavailable current state return None.
    """
    if (not isinstance(decision_input, dict) or
            not isinstance(action_frontier, dict) or
            not isinstance(request, dict) or
            action_frontier.get('schema') != 'mtga-action-frontier-v1' or
            action_frontier.get('immediate_completeness') != 'partial' or
            decision_input.get('read_only') is not True or
            decision_input.get('actionable') is not False or
            decision_input.get('input_sent') is not False or
            decision_input.get('executor_connected') is not False or
            request.get('current') is not True or
            request.get('type') != 'GREMessageType_ActionsAvailableReq'):
        return None
    binding = decision_input.get('binding')
    identity = action_frontier.get('request_identity')
    raw_binding = request.get('binding')
    decision_request = decision_input.get('request')
    if (not isinstance(binding, dict) or not isinstance(identity, dict) or
            not isinstance(raw_binding, dict) or
            not isinstance(decision_request, dict) or
            binding.get('ownership_verified') is not True or
            raw_binding.get('ownership_verified') is not True or
            any(identity.get(name) != binding.get(name) for name in
                ('generation', 'match', 'game', 'game_state_id',
                 'self_seat', 'request_id')) or
            any(identity.get(name) != raw_binding.get(name) for name in
                ('generation', 'match', 'game', 'game_state_id', 'self_seat')) or
            request.get('id') != identity.get('request_id') or
            request.get('game_state_id') != identity.get('game_state_id') or
            decision_request.get('type') != request.get('type')):
        return None
    inventory = request.get('action_inventory')
    rows = inventory.get('complex_raw_shapes') if isinstance(inventory, dict) else None
    templates = action_frontier.get('templates')
    if not isinstance(rows, list) or not isinstance(templates, list):
        return None
    by_position = {}
    for row in rows:
        if (not isinstance(row, dict) or type(row.get('list_position')) is not int or
                row['list_position'] in by_position or
                row.get('action_type') not in _COMPLEX):
            return None
        by_position[row['list_position']] = row
    nodes = []
    for template in templates:
        position = template.get('list_position')
        if template.get('engine_action_type') not in _COMPLEX:
            continue
        row = by_position.pop(position, None)
        if row is None or row.get('action_type') != template['engine_action_type']:
            return None
        key = template['action_key']
        node = _node(row, key, template.get('observed_parameter_shapes'),
                     template.get('structurally_interpreted') is True,
                     template.get('unresolved_parameters', []))
        if node is None:
            return None
        nodes.append(node)
    if by_position:
        return None
    return {
        'schema_version': 'mtga-choice-graph-v1',
        'request_identity': identity,
        'immediate_frontier': {'completeness': 'partial',
                               'engine_active_action_count':
                               action_frontier['engine_active_action_count']},
        'expanded_choices': {'completeness': 'unknown',
                             'legal_combinations': None},
        'action_nodes': nodes,
        'observed_successors': [],
        'successor_observation_status': 'unknown',
        'unresolved': ['future_choice_request_unobserved',
                       'legal_parameter_combinations_unverified'],
        'provenance': {'source': 'current_authenticated_own_gre_request',
                       'historical_response_used': False},
        'completeness': 'partial',
        'legal_choice_verified': False,
        'response_encoding_verified': False,
        'execution_ready': False,
        'input_sent': False,
        'read_only': True,
    }


CHOICE_VALIDATION_LEVELS = ('verified_known_constraints', 'violated_known_constraints',
                          'insufficient_evidence', 'unsupported_protocol')
_SELECTN_UNRESOLVED = ['min_sel_unknown', 'complete_choice_legality_unverified',
                      'response_encoding_unverified', 'server_acceptance_unverified',
                      'successor_causality_unverified']
_SELECTN_DISABLED = {'complete_legality_verified': False, 'legal_choice_verified': False,
                     'response_encoding_verified': False, 'server_acceptance_verified': False,
                     'execution_ready': False, 'input_sent': False}


def _selectn_known_constraints(request, payload):
    """Validate only AFTER the existing exact own-request/consumption gate.

    Request semantics come from RawReducer, never a second GRE parser. Neither
    an empty selection nor allow_cancel=False proves an unknown minimum.
    """
    def result(level, checks=(), count=None):
        return {'validation_level': level, 'checks': list(checks), 'selected_count': count}

    if request.get('supported') is not True:
        return result('unsupported_protocol')
    selection, candidates = request.get('selection'), request.get('candidates')
    evidence = request.get('candidate_evidence')
    if (not isinstance(selection, dict) or not isinstance(candidates, list) or
            not candidates or not isinstance(evidence, dict)):
        return result('insufficient_evidence')
    if (selection.get('validation_type') != 'SelectionValidationType_NonRepeatable' or
            evidence.get('field') != 'selectNReq.ids' or
            type(selection.get('min_weight')) is not int or
            type(selection.get('max_weight')) is not int):
        return result('unsupported_protocol')
    ids = [c.get('instance_id') if isinstance(c, dict) else None for c in candidates]
    def identifier(value):
        return type(value) is int and 0 <= value <= 2**53 - 1
    maximum = selection.get('max_sel')
    if (not all(identifier(i) for i in ids) or len(set(ids)) != len(ids) or
            type(maximum) is not int or not 1 <= maximum <= len(ids)):
        return result('insufficient_evidence')
    if set(payload) - {'type', 'respId', 'gameStateId', 'selectNResp'}:
        return result('unsupported_protocol')
    if 'selectNResp' not in payload:
        return result('insufficient_evidence')
    response = payload['selectNResp']
    if not isinstance(response, dict):
        return result('violated_known_constraints', [('response_ids_strict_integer_array', False)])
    if set(response) - {'ids'}:
        return result('unsupported_protocol')
    if 'ids' not in response:
        return result('insufficient_evidence')
    selected = response['ids']
    strict = isinstance(selected, list) and all(identifier(i) for i in selected)
    checks = [('exact_current_own_request_and_reducer_consumption', True),
              ('response_ids_strict_integer_array', strict)]
    if not strict:
        return result('violated_known_constraints', checks)
    domain = set(ids)
    checks.extend((('selected_ids_in_current_request_ids', all(i in domain for i in selected)),
                   ('selected_count_lte_confirmed_max_sel', len(selected) <= maximum),
                   ('nonrepeatable_ids_distinct', len(selected) == len(set(selected)))))
    level = ('verified_known_constraints' if all(ok for _, ok in checks)
             else 'violated_known_constraints')
    return result(level, checks, len(selected))


def _build_selectn_constraint_graph(request, validation):
    """Historical request snapshot; caller owns exact gate and source integrity.

    Export only request-offered IDs, never raw object identity or response IDs
    outside that domain. No fabricated ActionsAvailable list_position or edge.
    """
    if (request.get('supported') is not True or
            validation['validation_level'] == 'unsupported_protocol'):
        return None
    binding, selection = request['binding'], request['selection']
    identity = {k: binding[k] for k in
                ('generation', 'match', 'game', 'game_state_id', 'self_seat')}
    identity.update(request_id=request['id'], request_type=request['type'])
    key = {'request_identity': identity.copy()}
    level = validation['validation_level']
    constraint: ChoiceConstraint = {
        'action_key': key, 'parameter_category': 'select_n_instance_ids',
        'observed_structure': {'kind': 'array', 'id_type': selection['id_type'],
                               'validation_type': selection['validation_type']},
        'observed_quantity_or_domain': {
            'candidate_instance_ids': [c['instance_id'] for c in request['candidates']],
            'max_sel': selection['max_sel'], 'min_sel': None},
        'verified_structural_constraints': [name for name, ok in validation['checks'] if ok],
        'unresolved': _SELECTN_UNRESOLVED.copy(),
        'provenance': {'source': 'historical_authenticated_own_gre_request',
                       'field': 'selectNReq.ids', 'request_identity': identity.copy()},
        'validation_level': level,
    }
    return {
        'schema_version': 'mtga-selectn-choice-constraints-v1',
        'request_identity': identity, 'current_request': False,
        'selection_source': {'field': 'selectNReq.ids',
                             'source_instance_id': selection['source_id'],
                             'identities_enriched_from_raw_objects': False},
        'constraints': [constraint],
        'historical_validation': {
            **validation, 'selection_field': 'selectNResp.ids',
            'request_snapshot_at_response': True,
            'checks': [{'constraint': name, 'satisfied': ok}
                       for name, ok in validation['checks']]},
        'engine_offered': True,
        'known_constraint_satisfied': level == 'verified_known_constraints',
        'validation_level': level, 'completeness': 'partial',
        'expanded_choices': {'completeness': 'unknown', 'legal_combinations': None},
        'observed_successors': [], 'unresolved': _SELECTN_UNRESOLVED.copy(),
        'provenance': {'source': 'historical_authenticated_own_gre_request',
                       'exact_request_response_consumption_gate': True,
                       'matched_client_submission_only': True},
        **_SELECTN_DISABLED, 'read_only': True,
    }
