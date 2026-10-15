"""Opt-in, request-bound first action frontier from already projected GRE evidence.

This is an engine-offered structural inventory, never legal choice validation.
No raw GRE object, response encoding, or executor is consumed here.
"""
from collections import Counter
from typing import Literal, TypedDict

from .action_gaps import assess_action_gaps


class ActionTemplate(TypedDict):
    action_key: dict
    request_identity: dict
    list_position: int
    engine_action_type: str
    engine_offered: bool
    structurally_interpreted: bool
    unsupported_reason: str | None
    source_link_status: str
    visible_object_id: int | None
    observed_parameter_shapes: dict
    unknown_parameter_fields_present: bool
    unresolved_parameters: list[str]
    next_choice_request: None
    legal_choice_verified: bool
    execution_ready: bool
    response_encoding_verified: bool
    actionable: bool
    input_sent: bool


class CoverageReport(TypedDict):
    schema: Literal['mtga-action-frontier-v1']
    scope: str
    request_identity: dict
    engine_active_action_count: int | None
    interpreted_action_count: int | None
    unsupported_action_count: int | None
    immediate_completeness: Literal['partial', 'unknown']
    expanded_choice_completeness: Literal['unknown']
    reason: str
    templates: list[ActionTemplate] | None
    legal_actions: None
    read_only: bool
    actionable: bool
    input_sent: bool


_KNOWN = frozenset({
    'ActionType_Pass', 'ActionType_Play', 'ActionType_Cast',
    'ActionType_Activate', 'ActionType_Activate_Mana',
    'ActionType_FloatMana', '_unrecognized_action_type',
})
_PARAMETERS = frozenset({
    'manaCost', 'targets', 'manaPaymentOptions', 'manaSelections',
    'autoTapSolution',
})


def _unknown(identity, reason):
    return {
        'schema': 'mtga-action-frontier-v1',
        'scope': 'current_authenticated_own_request_only',
        'request_identity': identity,
        'engine_active_action_count': None,
        'interpreted_action_count': None,
        'unsupported_action_count': None,
        'immediate_completeness': 'unknown',
        'expanded_choice_completeness': 'unknown',
        'reason': reason,
        'templates': None, 'legal_actions': None,
        'read_only': True, 'actionable': False, 'input_sent': False,
    }


def build_action_frontier(decision_input, frontier_evidence):
    """Build from authenticated current projection and opt-in active row metadata.

    None means no trustworthy current decision input. An unsupported current
    request instead gets unknown coverage and null totals, never a fake zero.
    """
    if not isinstance(decision_input, dict):
        return None
    if (decision_input.get('schema') != 'mtga-readonly-decision-input-v1' or
            decision_input.get('read_only') is not True or
            decision_input.get('actionable') is not False or
            decision_input.get('input_sent') is not False or
            decision_input.get('executor_connected') is not False):
        return None
    binding = decision_input.get('binding')
    request = decision_input.get('request')
    if (not isinstance(binding, dict) or
            binding.get('ownership_verified') is not True or
            not isinstance(request, dict)):
        return None
    identity = {name: binding.get(name) for name in (
        'generation', 'match', 'game', 'game_state_id', 'self_seat',
        'request_id')}
    if request.get('type') != 'GREMessageType_ActionsAvailableReq':
        return _unknown(identity, 'request_type_outside_actions_available_scope')
    inventory = request.get('engine_action_inventory')
    if not isinstance(inventory, dict):
        return _unknown(identity, request.get('unsupported_reason') or
                        'action_inventory_unavailable')
    gaps = assess_action_gaps(decision_input)
    offered = inventory.get('offered_count')
    frontier_rows = (frontier_evidence.get('rows')
                     if isinstance(frontier_evidence, dict) else None)
    if (gaps is None or type(offered) is not int or
            not isinstance(frontier_evidence, dict) or
            frontier_evidence.get('request_identity') != identity or
            not isinstance(frontier_rows, list) or len(frontier_rows) != offered):
        return _unknown(identity, 'active_position_evidence_incomplete')
    described = inventory.get('described_rows')
    if not isinstance(described, list):
        return _unknown(identity, 'described_action_evidence_incomplete')
    described_by_position = {row['list_position']: row for row in described}
    gap_by_position = {row['list_position']: row for row in gaps['actions']}
    if (len(described_by_position) != len(described) or
            len(gap_by_position) != len(gaps['actions']) or
            set(described_by_position) != set(gap_by_position)):
        return _unknown(identity, 'described_action_evidence_conflict')
    counts = Counter()
    templates = []
    for position, row in enumerate(frontier_rows):
        if not isinstance(row, dict):
            return _unknown(identity, 'active_position_evidence_invalid')
        action_type = row.get('action_type')
        parameters = row.get('known_parameter_shapes')
        if (row.get('list_position') != position or action_type not in _KNOWN or
                not isinstance(parameters, dict) or
                set(parameters) - _PARAMETERS or
                type(row.get('other_top_level_fields_present')) is not bool or
                type(row.get('structurally_interpreted')) is not bool):
            return _unknown(identity, 'active_position_evidence_invalid')
        counts[action_type] += 1
        described_row = described_by_position.get(position)
        gap_row = gap_by_position.get(position)
        if described_row is not None and (
                described_row.get('engine_action_type') != action_type or
                gap_row.get('engine_action_type') != action_type):
            return _unknown(identity, 'active_position_evidence_conflict')
        interpreted = row['structurally_interpreted'] and described_row is not None
        if row['structurally_interpreted'] and described_row is None:
            return _unknown(identity, 'described_action_evidence_conflict')
        status = (described_row.get('source_link_status')
                  if described_row is not None else 'unverified')
        visible_id = (described_row.get('visible_object_id')
                      if status == 'visible_unique' else None)
        unresolved = (list(gap_row['rule_gaps']) if gap_row is not None else
                      ['active_engine_row_not_structurally_described'])
        if not interpreted:
            unresolved.append('action_structure_unsupported')
        unresolved.append('future_choice_request_unobserved')
        templates.append({
            'action_key': {'request_identity': identity.copy(),
                           'list_position': position},
            'request_identity': identity.copy(),
            'list_position': position, 'engine_action_type': action_type,
            'engine_offered': True, 'structurally_interpreted': interpreted,
            'unsupported_reason': None if interpreted else (
                'malformed_or_unreviewed_action_shape' if described_row is not None
                else 'action_structure_not_described'),
            'source_link_status': status, 'visible_object_id': visible_id,
            'source_card_identity_agreement': (described_row.get('source_card_identity_agreement')
                if described_row is not None and status == 'visible_unique' and
                type(described_row.get('source_card_identity_agreement')) is bool else None),
            'observed_parameter_shapes': parameters.copy(),
            'unknown_parameter_fields_present': row['other_top_level_fields_present'],
            'unresolved_parameters': sorted(set(unresolved)),
            'next_choice_request': None, 'legal_choice_verified': False,
            'execution_ready': False, 'response_encoding_verified': False,
            'actionable': False, 'input_sent': False,
        })
    listed = {item['action_type']: item['count']
              for item in inventory.get('type_counts', [])}
    if counts != listed:
        return _unknown(identity, 'active_type_counts_conflict')
    interpreted_count = sum(row['structurally_interpreted'] for row in templates)
    return {
        'schema': 'mtga-action-frontier-v1',
        'scope': 'current_authenticated_own_actions_available_request_only',
        'unknown_request_fields_present': (inventory.get('unknown_request_fields_present')
            if type(inventory.get('unknown_request_fields_present')) is bool else None),
        'request_identity': identity,
        'engine_active_action_count': offered,
        'interpreted_action_count': interpreted_count,
        'unsupported_action_count': offered - interpreted_count,
        'immediate_completeness': 'partial',
        'expanded_choice_completeness': 'unknown',
        'reason': 'legal_parameters_and_response_encoding_unverified',
        'templates': templates, 'legal_actions': None,
        'read_only': True, 'actionable': False, 'input_sent': False,
    }
