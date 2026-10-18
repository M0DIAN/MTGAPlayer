"""Explicit owner-context current target observation; no new state or parser.

Only the witnessed No-cancel, public Stack Ability, public Battlefield 1/1
Select slice is added. Missing references are never reinterpreted as players.
"""
import copy

from .decision_consumer import EXECUTION, _bounded_json
from .choice_continuation import _binding, _observe_target_fields, _positive
from .response_evidence import _current_verified_raw_request
from .cast_target_members import _equal
from .semantic_samples import _need

VERSION = 'mtgaplayer.current-target-request.v1'
PROFILE = 'reviewed_no_cancel_stack_ability_public_battlefield_single_select'
UNKNOWN = ('complete_legality_unknown', 'complete_target_combination_unknown',
    'dynamic_effects_unknown', 'ability_rule_semantics_unknown', 'prompt_routing_unknown',
    'payment_unknown', 'historical_completion_not_inferred', 'response_encoding_unknown',
    'server_acceptance_unknown', 'strategic_utility_unknown')


def unknown(reason):
    return {'schema_version': VERSION, 'status': 'insufficient_evidence', 'reason': reason,
        'profile': None, 'current_request_binding': None, 'source_snapshot_ref': None,
        'source_identity': None, 'target_constraints': None, 'current_offered_members': None,
        'current_selected_literal': None, 'local_proposals': [],
        'candidate_total_for_reviewed_constraints': None, 'returned_proposals': 0,
        'truncated': False, 'complete_target_legality_verified': False,
        'historical_response_used': False, 'unknown': list(UNKNOWN), 'read_only': True, **EXECUTION}


def _identity(reducer, ident, kinds, zone_type):
    from .target_revision import _signature
    _positive(ident)
    value = _signature(reducer, ident)  # Existing public and unique-zone gate.
    obj = reducer.objects[ident]; zone = reducer.zones[obj['zoneId']]
    _need(type(obj['instanceId']) is int and obj['instanceId'] == ident and
        obj['type'] in kinds and zone['type'] == zone_type)
    members = zone.get('objectInstanceIds')
    _need(type(members) is list and len(members) <= 512 and
        all(type(i) is int and i > 0 for i in members) and len(set(members)) == len(members))
    _positive(obj['zoneId'])
    return value


def _project(reducer, message, state, ref, limit):
    """Called within MP65's existing Consumer owner/ref/lease before/after gate."""
    from .raw_log import RawReducer
    if not isinstance(reducer, RawReducer): return unknown('requires_same_current_reducer')
    request = _current_verified_raw_request(reducer, message)
    if (request is None or request['type'] != 'GREMessageType_SelectTargetsReq' or
            not _equal(_binding(reducer, request), state['binding'])):
        return unknown('authenticated_current_target_request_not_observed')
    if request.get('_target_evidence_interrupted') is True:
        return unknown('current_target_request_interrupted')
    if reducer._target_state_continuity_verified is not True:
        return unknown('typed_current_state_continuity_unverified')
    current = reducer.document()['current']; visible = state['visible_objects']
    expected = [{'instance_id': o['id'], 'card_id': o['card_id'], 'zone': o['zone'],
        'owner_seat': o['owner'], 'controller_seat': o['controller']} for o in current['objects']]
    keys = ('instance_id', 'card_id', 'zone', 'owner_seat', 'controller_seat')
    if not _equal(expected, [{k: o[k] for k in keys} for o in visible]):
        return unknown('current_visible_projection_disagrees_with_reducer')
    if request.get('_request_parameters') is not None:
        return unknown('existing_profile_already_supported')
    _bounded_json(message)
    # No/Abort are retained protocol literals (MP71 descriptor receipt). No is
    # not ignored or normalized to Abort; its execution/routing role stays unknown.
    if message.get('allowCancel') != 'AllowCancel_No':
        return unknown('new_no_cancel_profile_not_observed')
    if 'allowUndo' in message: return unknown('undo_field_profile_not_reviewed')
    observation = _observe_target_fields(message,
        [{'object_ref': o['instance_id'], 'zone': o['zone']} for o in visible],
        state['binding']['self_seat'], allow_no_cancel=True)
    constraints = observation['constraints']; ident = constraints['source_object_ref']
    source = reducer.objects[ident]
    _identity(reducer, ident, ('GameObjectType_Ability',), 'ZoneType_Stack')
    _need(_equal(source['grpId'], constraints['ability_grp_ref']) and
        _equal(source['grpId'], constraints['targeting_ability_grp_ref']) and
        all(type(source[k]) is int and source[k] == state['binding']['self_seat'] for k in
            ('ownerSeatId', 'controllerSeatId')))
    stack = state['game']['stack']
    _need(stack['availability'] == 'observed' and any(
        _equal(m['instance_id'], ident) and m['object_type'] == 'GameObjectType_Ability' for m in stack['members']))
    _need(all(type(constraints[k]) is int and constraints[k] == 1 for k in ('min_targets', 'max_targets')) and
        constraints['selected_count'] is None and constraints['entries'] and
        all(e['legal_action'] == 'SelectAction_Select' for e in constraints['entries']))
    identities = {ident: _identity(reducer, ident, ('GameObjectType_Ability',), 'ZoneType_Stack')}
    for entry in constraints['entries']:
        member = entry['object_ref']
        identities[member] = _identity(reducer, member, ('GameObjectType_Card', 'GameObjectType_Token'), 'ZoneType_Battlefield')
    from .choice_candidates import _target_proposals
    from .decision_options import _option
    proposals, total, reason = _target_proposals(constraints, state['binding'], ref, limit)
    if reason: return unknown(reason)
    local = []
    for position, proposal in enumerate(proposals):
        row = _option(state['binding'], ref, 'reviewed_final_target_set', PROFILE, position,
            proposal=proposal, scope='current_single_slot_offered_membership_and_explicit_count_only')
        row['research_eligible'] = False  # No change to MP66's default inputs.
        row['unresolved'] = list(UNKNOWN); local.append(row)
    after = _current_verified_raw_request(reducer, message)
    _need(after is not None and after.get('_target_evidence_interrupted') is not True and
        reducer._target_state_continuity_verified is True and
        _equal(_binding(reducer, after), state['binding']) and
        all(_equal(_identity(reducer, i, ('GameObjectType_Ability',) if i == ident else
            ('GameObjectType_Card', 'GameObjectType_Token'), 'ZoneType_Stack' if i == ident else
            'ZoneType_Battlefield'), signature) for i, signature in identities.items()))
    result = unknown('current_offered_members_and_local_count_only')
    result.update(status='observed', profile=PROFILE,
        current_request_binding=copy.deepcopy(state['binding']), source_snapshot_ref=copy.deepcopy(ref),
        source_identity={'object_ref': ident, 'object_type': 'GameObjectType_Ability',
            'zone': 'ZoneType_Stack', 'ability_grp_ref': constraints['ability_grp_ref']},
        target_constraints=copy.deepcopy(constraints), current_offered_members=copy.deepcopy(constraints['entries']),
        local_proposals=local, candidate_total_for_reviewed_constraints=total,
        returned_proposals=len(local), truncated=len(local)<total)
    _bounded_json(result)
    return result
