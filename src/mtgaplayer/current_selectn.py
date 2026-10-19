"""Finite current TriggeredAbility/Stacking members, never complete choices."""
import copy

from .decision_consumer import EXECUTION, _bounded_json
from .response_evidence import _current_verified_raw_request
from .choice_continuation import _binding
from .cast_target_members import _equal
from .cast_activate_associations import _prompt
from .semantic_samples import _keys, _need
from .current_group import _uint, _visible

VERSION = 'mtgaplayer.current-selectn-evidence.v1'
PROFILE = 'observed_triggered_stacking_unresolved_members_explicit_counts'
REQUEST = 'GREMessageType_SelectNReq'
NAMESPACE = 'request_scoped_selectn_member_not_confirmed_object_or_card'
UNKNOWN = ('member_object_identity_unknown', 'source_identity_not_supplied',
    'stacking_order_semantics_unknown', 'complete_combination_constraints_unknown',
    'weight_constraints_unknown', 'cancellation_semantics_unknown', 'prompt_routing_unknown',
    'complete_selectn_legality_unknown', 'strategic_utility_unknown',
    'response_encoding_unknown', 'server_acceptance_unknown')


def unknown(reason):
    return {'schema_version': VERSION, 'status': 'insufficient_evidence', 'reason': reason,
        'profile': None, 'request_binding': None, 'source_snapshot_ref': None,
        'selection_context': None, 'option_context': None, 'id_type': None, 'list_type': None,
        'validation_type': None, 'member_namespace': NAMESPACE,
        'engine_offered_member_count': None, 'engine_offered_members': [],
        'reviewed_visible_members': [], 'reviewed_visible_member_count': 0,
        'unresolved_member_references': [], 'unresolved_member_count': None,
        'observed_quantity_bounds': None, 'reviewed_quantity_bounds': False,
        'current_selected_literals': None, 'source_object_ref': None, 'weight_constraints': None,
        'returned_members': 0, 'omitted_members': None, 'truncated': False,
        'current_local_constraints_verified': False, 'local_constraint_scope': None,
        'reviewed_local_proposals': [], 'complete_proposal_count': None,
        'complete_legal_actions': None, 'historical_response_used': False,
        'unknown_combination_constraints': list(UNKNOWN), 'research_eligible': False,
        'read_only': True, **EXECUTION}


def project_request(message, visible, seat):
    """Observed fields only; numeric instance encoding is not an object join.

    This is deliberately separate from the old Resolution profile. Absent
    fields stay unknown, not protobuf defaults or implicit cancellation/weights.
    """
    _keys(message, ('type', 'systemSeatIds', 'msgId', 'gameStateId', 'prompt', 'selectNReq'))
    _need(message['type'] == REQUEST and type(seat) is int and seat in (1, 2) and
        type(message['systemSeatIds']) is list and len(message['systemSeatIds']) == 1 and
        type(message['systemSeatIds'][0]) is int and message['systemSeatIds'][0] == seat and
        _uint(message['msgId']) and _uint(message['gameStateId']))
    _prompt(message['prompt'])  # Existing finite prompt syntax, no routing claim.
    body = message['selectNReq']
    _keys(body, ('minSel', 'maxSel', 'context', 'optionContext', 'listType', 'ids',
        'idType', 'validationType'))
    ids = body['ids']
    _need(body['context'] == 'SelectionContext_TriggeredAbility' and
        body['optionContext'] == 'OptionContext_Stacking' and
        body['idType'] == 'IdType_InstanceId' and body['listType'] == 'SelectionListType_Dynamic' and
        body['validationType'] == 'SelectionValidationType_NonRepeatable' and
        type(ids) is list and 2 <= len(ids) <= 64 and all(_uint(i) for i in ids) and len(set(ids)) == len(ids) and
        type(body['minSel']) is int and body['minSel'] == 1 and
        type(body['maxSel']) is int and body['maxSel'] == len(ids))
    # Never turn an ID collision into a face, type, zone or source relationship.
    _need(not set(ids) & {o['instance_id'] for o in visible},
        'visible_selectn_member_profile_not_reviewed')
    return {'selection_context': body['context'], 'option_context': body['optionContext'],
        'id_type': body['idType'], 'list_type': body['listType'], 'validation_type': body['validationType'],
        'engine_offered_member_count': len(ids),
        'observed_quantity_bounds': {'minimum': body['minSel'], 'maximum': body['maxSel'],
            'basis': 'explicit_current_minSel_maxSel_only'}}


def _project(reducer, message, state, ref, limit):
    from .raw_log import RawReducer
    if not isinstance(reducer, RawReducer): return unknown('requires_same_current_reducer')
    request = _current_verified_raw_request(reducer, message)
    if request is None or request['type'] != REQUEST or not _equal(_binding(reducer, request), state['binding']):
        return unknown('authenticated_current_selectn_request_not_observed')
    if request.get('_selectn_evidence_interrupted') is True: return unknown('current_selectn_request_interrupted')
    if request.get('_continuity_verified') is not True or reducer._target_state_continuity_verified is not True:
        return unknown('typed_current_selectn_continuity_unverified')
    accepted_digest = reducer.accepted_digest
    _need(type(accepted_digest) is bytes)
    visible = state['visible_objects']; expected = _visible(reducer)
    keys = ('instance_id', 'card_id', 'zone', 'owner_seat', 'controller_seat')
    _need(_equal(expected, [{k: o[k] for k in keys} for o in visible]))
    _bounded_json(message)
    value = project_request(message, visible, state['binding']['self_seat'])
    # Position aliases are meaningful only with this exact request/ref, and
    # deliberately never expose the original GRE numeric member reference.
    members = [{'member_ref': position + 1, 'list_position': position, 'namespace': NAMESPACE,
        'object_ref': None, 'card_id': None, 'zone': None, 'visibility': 'not_in_current_visible_projection',
        'request_binding': copy.deepcopy(state['binding']), 'source_snapshot_ref': copy.deepcopy(ref)}
        for position in range(min(limit, value['engine_offered_member_count']))]
    after = _current_verified_raw_request(reducer, message)
    _need(after is not None and after.get('_selectn_evidence_interrupted') is not True and
        after.get('_continuity_verified') is True and reducer._target_state_continuity_verified is True and
        type(reducer.accepted_digest) is bytes and accepted_digest == reducer.accepted_digest and
        _equal(_binding(reducer, after), state['binding']) and _equal(expected, _visible(reducer)))
    result = unknown('current_selectn_members_and_explicit_count_structure_only')
    result.update(value, status='observed', profile=PROFILE, request_binding=copy.deepcopy(state['binding']),
        source_snapshot_ref=copy.deepcopy(ref), engine_offered_members=members,
        unresolved_member_references=copy.deepcopy(members), unresolved_member_count=value['engine_offered_member_count'],
        reviewed_quantity_bounds=True, returned_members=len(members),
        omitted_members=value['engine_offered_member_count'] - len(members),
        truncated=len(members) < value['engine_offered_member_count'], current_local_constraints_verified=True,
        local_constraint_scope='unique_offered_request_references_and_explicit_minimum_maximum_only')
    _bounded_json(result)
    return result
