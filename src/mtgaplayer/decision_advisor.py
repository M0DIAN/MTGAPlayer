"""Evidence-bounded research advice; no rules solver, response or executor.

State assessment is pure. Current assessment reads the existing consumer once
on its owner thread: a detached old view cannot prove that it is still current.
Advice is snapshot-bound data, never a new opportunity or executable plan.
"""
import copy
from collections import Counter

from .decision_consumer import DecisionConsumer, EXECUTION, _bounded_json, _state
from .decision_state import _bound_readonly, _same_identity

SCHEMA_VERSION = 'mtgaplayer.decision-advice.v1'
EVIDENCE_POLICY = 'evidence_only.v1'
SIMPLE_TYPE_POLICY = 'simple_type_research.v1'
_POLICIES = (EVIDENCE_POLICY, SIMPLE_TYPE_POLICY)
_SIMPLE = ('ActionType_Pass', 'ActionType_Play')
_COMPLEX = ('ActionType_Cast', 'ActionType_Activate', 'ActionType_Activate_Mana')
_TYPES = (*_SIMPLE, *_COMPLEX, 'ActionType_FloatMana', '_unrecognized_action_type')
_PARAMETERS = ('manaCost', 'targets', 'manaPaymentOptions', 'manaSelections', 'autoTapSolution')
_SOURCE_LINKS = ('visible_unique', 'not_in_visible_projection', 'missing_source_instance',
                 'ambiguous_visible_projection', 'unverified', 'not_applicable')
_UNKNOWN = ('complete_legality_unknown', 'strategic_utility_unknown',
            'response_encoding_unknown', 'server_freshness_unknown', 'server_acceptance_unknown')


class _InventoryError(ValueError):
    pass


def _check(value, reason):
    if not value:
        raise _InventoryError(reason)


def _legacy(binding):
    return {'generation': binding['source_generation'], **{k: v for k, v in binding.items()
            if k not in ('source_generation', 'request_type')}}


def _identity(value, binding):
    expected = _legacy(binding)
    return (type(value) is dict and set(expected) <= value.keys() <= set(expected) | {'request_type'}
            and _same_identity(value, expected)
            and ('request_type' not in value or value['request_type'] == binding['request_type']))


def _validate_state(state):
    _bounded_json(state)
    _state(state, state['binding'])
    if not _bound_readonly(state, _legacy(state['binding']), state['binding']['request_type']):
        raise ValueError('invalid_nested_binding_or_authority')


def _coverage(source=None):
    return {'source': source, 'inventory_status': 'unknown', 'offered_count': None,
            'assessed_count': 0, 'inventory_integrity_verified': False,
            'completeness': 'unknown', 'legal_combinations': None}


def _result(policy, current=False, binding=None, snapshot=None):
    return {'schema_version': SCHEMA_VERSION, 'assessment_status': 'abstain',
        'assessment_scope': 'current_snapshot_research_only' if current else 'historical_research_only',
        'historical_research_only': not current, 'new_live_opportunity': False,
        'source_snapshot_ref': copy.deepcopy(snapshot), 'request_identity': copy.deepcopy(binding),
        'policy_version': policy if policy in _POLICIES else 'unsupported',
        'candidate_coverage': _coverage(), 'candidate_assessments': [],
        'preferred_candidate': None, 'preference_basis': None, 'policy_basis': None, 'abstention_reason': None,
        'unresolved': list(_UNKNOWN), 'read_only': True, 'execution': dict(EXECUTION)}


def _abstain(result, reason):
    result['abstention_reason'] = reason
    result['unresolved'] = sorted(set(result['unresolved']))
    return result


def _extract_actions(state):
    """Validate an entire active inventory; never filter or deduplicate rows."""
    binding = state['binding']
    frontier = state['legal_action_space']['immediate_frontier']
    projection = frontier['projection']
    _check(type(projection) is dict and type(projection.get('templates')) is list,
           'active_candidate_array_not_provided')
    rows = projection['templates']
    _check(projection.get('scope') == 'current_authenticated_own_actions_available_request_only',
           'active_candidate_source_unverified')
    _check(_identity(projection.get('request_identity'), binding), 'frontier_identity_mismatch')
    count = projection.get('engine_active_action_count')
    _check(type(count) is int and 0 <= count <= 256 and count == len(rows), 'active_candidate_count_mismatch')
    _check(frontier['availability'] == ('observed' if count else 'confirmed_empty') and
           projection['immediate_completeness'] == 'partial' and projection.get('legal_actions') is None,
           'active_candidate_coverage_conflict')
    visible = Counter(obj['instance_id'] for obj in state['visible_objects'])
    for position, row in enumerate(rows):
        key = row['action_key']
        _check(type(row['list_position']) is int and row['list_position'] == position and
               type(key['list_position']) is int and key['list_position'] == position,
               'active_candidate_position_conflict')
        _check(_identity(row['request_identity'], binding) and _identity(key['request_identity'], binding),
               'action_key_identity_mismatch')
        _check({'structurally_interpreted', 'unknown_parameter_fields_present', 'source_link_status',
                'unsupported_reason', 'visible_object_id', 'next_choice_request'} <= row.keys(),
               'candidate_evidence_not_provided')
        _check(row['engine_action_type'] in _TYPES and row['engine_offered'] is True and
               type(row.get('structurally_interpreted')) is bool and
               type(row.get('unknown_parameter_fields_present')) is bool and
               row.get('source_link_status') in _SOURCE_LINKS and
               (row.get('unsupported_reason') is None or type(row['unsupported_reason']) is str),
               'invalid_candidate_evidence')
        _check(not row['structurally_interpreted'] or row['unsupported_reason'] is None,
               'candidate_interpretation_conflict')
        _check(set(row['observed_parameter_shapes']) <= set(_PARAMETERS) and
               row.get('next_choice_request') is None, 'candidate_parameter_shape_conflict')
        if row['engine_action_type'] not in (*_SIMPLE, *_COMPLEX):
            _check(row['structurally_interpreted'] is False, 'unsupported_type_claims_interpretation')
        source = row.get('visible_object_id')
        _check((row['source_link_status'] == 'visible_unique' and type(source) is int and visible[source] == 1)
               or (row['source_link_status'] != 'visible_unique' and source is None),
               'candidate_source_link_conflict')
        if row['engine_action_type'] == 'ActionType_Pass':
            _check(row['source_link_status'] == 'not_applicable', 'pass_source_link_conflict')
        if row['engine_action_type'] == 'ActionType_Play' and row['structurally_interpreted']:
            _check(row['source_link_status'] == 'visible_unique', 'play_source_link_conflict')
    interpreted = sum(row['structurally_interpreted'] for row in rows)
    _check(type(projection.get('interpreted_action_count')) is int and
           projection['interpreted_action_count'] == interpreted and
           type(projection.get('unsupported_action_count')) is int and
           projection['unsupported_action_count'] == count - interpreted, 'candidate_summary_count_conflict')
    return rows


def _graph_issue(state, rows):
    """Graph can expose a conflict, never supply or complete candidates."""
    graph = state['legal_action_space']['choice_graph']
    if graph is None:
        return None
    positions = set()
    for node in graph['action_nodes']:
        position = node['action_key']['list_position']
        identity = node.get('action_identity')
        if (type(position) is not int or not 0 <= position < len(rows) or position in positions or
                not _identity(node['action_key']['request_identity'], state['binding']) or
                type(identity) is not dict or identity.get('engine_action_type') not in _COMPLEX or
                identity['engine_action_type'] != rows[position]['engine_action_type']):
            return 'choice_graph_candidate_conflict'
        positions.add(position)
    return None


def _classify_actions(rows, binding):
    assessed = []
    for row in rows:
        evidence = ['ENGINE_OFFERED', 'RESPONSE_UNVERIFIED']
        evidence.append('STRUCTURE_INTERPRETED' if row['structurally_interpreted'] else 'UNSUPPORTED_STRUCTURE')
        if row['engine_action_type'] in _COMPLEX or row['observed_parameter_shapes'] or row['unknown_parameter_fields_present']:
            evidence.extend(('PARAMETERS_PARTIAL', 'COMBINATION_UNKNOWN'))
        assessed.append({'action_key': {'request_identity': dict(binding), 'list_position': row['list_position']},
            'request_identity': dict(binding), 'list_position': row['list_position'],
            'engine_action_type': row['engine_action_type'], 'engine_offered': True,
            'structurally_interpreted': row['structurally_interpreted'],
            'source_link_status': row['source_link_status'],
            'unresolved_parameters': list(row['unresolved_parameters']),
            'evidence_quality': evidence, 'highest_evidence_level': 'LA2' if row['structurally_interpreted'] else 'LA1',
            'strategic_utility': None, 'read_only': True, 'execution': dict(EXECUTION)})
    return assessed


def _preference(rows, policy, current, graph_issue):
    if not current:
        return None, 'historical_research_only'
    if graph_issue:
        return None, graph_issue
    if policy == EVIDENCE_POLICY:
        return None, 'evidence_only_policy'
    if not rows:
        return None, 'no_engine_offered_candidates'
    if any(row['engine_action_type'] not in _SIMPLE for row in rows):
        return None, 'complex_or_unsupported_candidates'
    if any(not row['structurally_interpreted'] or row['unsupported_reason'] is not None or
           row['unknown_parameter_fields_present'] or row['observed_parameter_shapes'] for row in rows):
        return None, 'simple_candidate_structure_incomplete'
    plays = [row['list_position'] for row in rows if row['engine_action_type'] == 'ActionType_Play']
    return (plays[0], None) if len(plays) == 1 else (None, 'unique_play_not_observed')


def _other_request(state, result):
    frontier = state['legal_action_space']['immediate_frontier']
    projection, kind, binding = frontier['projection'], frontier['kind'], state['binding']
    if kind == 'select_n':
        if projection is None:
            return _abstain(result, 'select_n_candidates_not_provided')
        _check(frontier['availability'] == ('observed' if projection['offered_instance_ids'] else 'confirmed_empty') and
               frontier['completeness'] == 'partial', 'select_n_candidate_coverage_conflict')
        result['candidate_coverage'].update(source='immediate_frontier.projection.offered_instance_ids',
            inventory_status=frontier['availability'], offered_count=len(projection['offered_instance_ids']),
            assessed_count=len(projection['offered_instance_ids']), inventory_integrity_verified=True, completeness='partial')
        result['candidate_assessments'] = [{
            'option_key': {'request_identity': dict(binding), 'option_position': position},
            'request_identity': dict(binding), 'option_position': position,
            'offered_instance_id': ident, 'identity_scope': 'request_reference_only',
            'engine_offered': True, 'highest_evidence_level': 'LA1',
            'evidence_quality': ['ENGINE_OFFERED', 'COMBINATION_UNKNOWN', 'RESPONSE_UNVERIFIED'],
            'strategic_utility': None, 'read_only': True, 'execution': dict(EXECUTION)}
            for position, ident in enumerate(projection['offered_instance_ids'])]
        result['request_summary'] = {'observed_candidate_count': len(projection['offered_instance_ids']),
            'max_sel_raw': projection['max_sel_raw'], 'min_sel': None, 'combination_legality': None}
        result['unresolved'].extend(('select_n_minimum_unknown', 'select_n_combinations_unknown'))
        return _abstain(result, 'select_n_strategy_unsupported')
    if kind in ('declare_attackers', 'declare_blockers'):
        rows = projection.get('engine_offered_candidates') if type(projection) is dict else None
        _check(type(rows) is list and projection.get('truncated') is False and
               type(projection.get('observed_candidate_count')) is int and
               projection['observed_candidate_count'] == len(rows), 'combat_candidate_inventory_incomplete')
        _check(_identity(projection['request_identity'], binding), 'combat_identity_mismatch')
        _check(frontier['availability'] == ('observed' if rows else 'confirmed_empty') and
               frontier['completeness'] == 'partial', 'combat_candidate_coverage_conflict')
        visible = Counter(obj['instance_id'] for obj in state['visible_objects'])
        public = {obj['instance_id']: obj for obj in state['visible_objects']
                  if visible[obj['instance_id']] == 1 and obj['zone'] == 'ZoneType_Battlefield'}
        def public_reference(value, seat):
            return type(value) is int and value in public and public[value]['controller_seat'] == seat
        assessed = []
        for position, row in enumerate(rows):
            _check(row['candidate_position'] == position and row['candidate_key']['candidate_position'] == position and
                   _identity(row['candidate_key']['request_identity'], binding), 'combat_candidate_key_conflict')
            _check(public_reference(row['candidate_instance_id'], binding['self_seat']) if row['reference_verified']
                   else row['candidate_instance_id'] is None, 'combat_public_reference_conflict')
            edges = row.get('engine_listed_attacker_references')
            _check(edges is None or type(edges) is list, 'combat_relationship_invalid')
            safe_edges = None if edges is None else []
            for index, edge in enumerate(edges or ()):
                _check(type(edge) is dict and
                       {'list_position', 'attacker_instance_id', 'public_reference_verified'} <= edge.keys() and
                       type(edge['list_position']) is int and edge['list_position'] == index and
                       type(edge.get('public_reference_verified')) is bool and
                       (public_reference(edge.get('attacker_instance_id'), 3 - binding['self_seat']) if edge['public_reference_verified']
                        else edge.get('attacker_instance_id') is None), 'combat_relationship_invalid')
                safe_edges.append({k: edge[k] for k in
                    ('list_position', 'attacker_instance_id', 'public_reference_verified')})
            assessed.append({'candidate_key': {'request_identity': dict(binding), 'candidate_position': position},
                'request_identity': dict(binding), 'candidate_position': position,
                'candidate_instance_id': row['candidate_instance_id'], 'reference_verified': row['reference_verified'],
                'engine_listed_attacker_references': safe_edges,
                'evidence_quality': ['ENGINE_OFFERED', 'COMBINATION_UNKNOWN', 'RESPONSE_UNVERIFIED'],
                'strategic_utility': None, 'read_only': True, 'execution': dict(EXECUTION)})
        result['candidate_assessments'] = assessed
        result['candidate_coverage'].update(source='immediate_frontier.projection.engine_offered_candidates',
            inventory_status=frontier['availability'], offered_count=len(rows), assessed_count=len(rows),
            inventory_integrity_verified=True, completeness='partial')
        result['unresolved'].extend(('combat_combinations_unknown', 'mandatory_combat_unknown',
            'attack_target_domain_unknown', 'blocking_order_unknown', 'damage_assignment_unknown'))
        return _abstain(result, 'combat_strategy_unsupported')
    return _abstain(result, 'unsupported_request_type')


def _assess(state, policy, current=False, snapshot=None):
    result = _result(policy, current)
    if policy not in _POLICIES:
        return _abstain(result, 'unsupported_policy_version')
    try:
        _validate_state(state)
    except (ValueError, KeyError, TypeError, RecursionError, UnicodeError):
        return _abstain(result, 'invalid_decision_state')
    binding = state['binding']
    result = _result(policy, current, binding, snapshot)
    if binding['request_id'] is None:
        return _abstain(result, 'current_request_not_provided')
    try:
        if binding['request_type'] != 'GREMessageType_ActionsAvailableReq':
            return _other_request(state, result)
        result['candidate_coverage']['source'] = 'immediate_frontier.projection.templates'
        rows = _extract_actions(state)
        issue = _graph_issue(state, rows)
        result['candidate_assessments'] = _classify_actions(rows, binding)
        result['candidate_coverage'].update(inventory_status='observed' if rows else 'confirmed_empty',
            offered_count=len(rows), assessed_count=len(rows), inventory_integrity_verified=True, completeness='partial')
        if issue:
            result['unresolved'].append(issue)
        position, reason = _preference(rows, policy, current, issue)
        if position is None:
            return _abstain(result, reason)
        result['assessment_status'] = 'research_preference'
        result['preferred_candidate'] = copy.deepcopy(result['candidate_assessments'][position]['action_key'])
        result['preference_basis'] = 'unverified_simple_type_heuristic'
        result['policy_basis'] = result['preference_basis']
        result['unresolved'] = sorted(set(result['unresolved']))
        return result
    except _InventoryError as exc:
        result['candidate_assessments'] = []
        result['candidate_coverage'] = _coverage(result['candidate_coverage']['source'])
        result['unresolved'].append(str(exc))
        return _abstain(result, 'candidate_inventory_invalid')


def assess_decision_state(state: dict, *, policy_version: str = EVIDENCE_POLICY) -> dict:
    """Pure offline structure research. Never grants a current preference."""
    return _assess(state, policy_version)


def assess_current_decision(consumer: DecisionConsumer, *, policy_version: str = EVIDENCE_POLICY) -> dict:
    """Read the existing Consumer on its owner thread, then assess purely.

    Detached dictionaries are rejected: they cannot notice later invalidation.
    Re-evaluate after any state/request/session change; never reuse old advice
    as current. No liveness timing is retained in the deterministic result.
    """
    result = _result(policy_version, current=True)
    if not isinstance(consumer, DecisionConsumer):
        return _abstain(result, 'requires_current_consumer')
    try:
        view = consumer.current_view()
        _bounded_json(view)
        status = view['consumer_status']
        if status != 'OBSERVING':
            return _abstain(result, 'consumer_' + status.lower())
        if view['current_snapshot_ref'] is None or view['decision_state'] is None:
            return _abstain(result, 'current_snapshot_not_provided')
        if view['new_request_observed'] is not True:
            return _abstain(result, 'new_request_not_observed')
        state, ref = view['decision_state'], view['current_snapshot_ref']
        if (view['read_only'] is not True or any(view[k] is not False for k in EXECUTION) or
                view['transport_alive'] is not True or ref['binding'] != state['binding'] or
                ref['session_id'] != view['session_id'] or
                not 1 <= ref['sequence'] <= view['last_sequence'] or
                state['status'] != 'state_and_request_observed' or
                state['source']['mode'] != 'watch' or state['source']['phase'] != 'append' or
                state['source']['stopped'] is not False):
            return _abstain(result, 'current_snapshot_binding_invalid')
        return _assess(state, policy_version, current=True, snapshot=ref)
    except (ValueError, KeyError, TypeError, RecursionError, UnicodeError):
        return _abstain(result, 'current_view_unavailable')
