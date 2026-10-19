"""Explicit owner-context current target observation; no new state or parser.

The legacy public Battlefield slice stays strict. Player referents require the
separate reviewed source-build capability and a collision-free current state.
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
    from .target_build import current_build
    body = message.get('selectTargetsReq')
    slots = body.get('targets') if type(body) is dict else None
    entries = slots[0].get('targets') if type(slots) is list and len(slots) == 1 and type(slots[0]) is dict else None
    battlefield = {o['instance_id'] for o in visible if o['zone'] == 'ZoneType_Battlefield'}
    if current_build(reducer) is not None and type(entries) is list and any(
            type(e) is dict and (e.get('targetInstanceId') in (1, 2) or
                e.get('targetInstanceId') not in battlefield) for e in entries):
        return _project_referents(reducer, message, state, ref, limit, visible)
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


ROLE_VERSION = 'mtgaplayer.current-target-request.v2'
ROLE_PROFILE = 'version_bound_player_and_public_battlefield_target_referents'
_PLAYER_FIELDS = {'lifeTotal', 'systemSeatNumber', 'status', 'manaPool', 'maxHandSize',
    'mulliganCount', 'turnNumber', 'teamId', 'timerIds', 'controllerSeatId',
    'controllerType', 'timeoutCount', 'pipCount', 'pendingMessageType', 'startingLifeTotal'}


def _players_verified(reducer):
    players = reducer.players
    if type(players) is not dict or set(players) != {1, 2} or any(type(k) is not int for k in players):
        return False
    for seat, row in players.items():
        if (type(row) is not dict or set(row)-_PLAYER_FIELDS or
                type(row.get('systemSeatNumber')) is not int or row['systemSeatNumber'] != seat):
            return False
        for key, value in row.items():
            if key in ('status', 'controllerType', 'pendingMessageType'):
                if type(value) is not str: return False
            elif key == 'manaPool':
                if type(value) is not list: return False
            elif key == 'timerIds':
                if type(value) is not list or any(type(v) is not int or not 0 <= v <= 2**32-1 for v in value): return False
            elif key == 'lifeTotal':
                if type(value) is not int or not -2**31 <= value < 2**31: return False
            elif type(value) is not int or not 0 <= value <= 2**32-1:
                return False
        if 'controllerSeatId' in row and row['controllerSeatId'] not in (1, 2): return False
    return True


def _collision_witness(reducer, ids):
    # Existence/membership only. A hidden face is neither read nor exported.
    return [(ident, ident in reducer.objects,
        [z for z, row in sorted(reducer.zones.items()) if ident in row.get('objectInstanceIds', [])])
        for ident in ids]


def role_state_witness(reducer):
    """Private frame freshness dependency, without hidden object payloads.

    Only the two reviewed player IDs can acquire this new role. Include their
    raw existence/zone membership even when the offered domain changes later.
    """
    from .target_build import current_build
    if current_build(reducer) is None:
        return None
    return copy.deepcopy((reducer.players, _collision_witness(reducer, (1, 2))))


def _project_referents(reducer, message, state, ref, limit, visible):
    from .target_build import current_build
    from .semantic_targets import SELECT, UNSELECT, check_referent_final_set
    from .choice_candidates import _bounded_target_sets
    from .decision_options import _option
    digest = reducer.accepted_digest
    _need(type(digest) is bytes)
    version = current_build(reducer)
    _need(version is not None)
    players = copy.deepcopy(reducer.players)
    valid_players = _players_verified(reducer)
    body = message['selectTargetsReq']; slot = body['targets'][0]
    raw_ids = [e['targetInstanceId'] for e in slot['targets']]
    _need(all(type(i) is int and 0 < i <= 2**32-1 for i in raw_ids))
    collision = _collision_witness(reducer, raw_ids)
    public = {o['instance_id']: o for o in visible}
    roles = {}; signatures = {}
    for position, ident in enumerate(raw_ids):
        row = {'target_instance_ref': position+1, 'target_referent_kind': 'unresolved',
            'namespace': 'unresolved_request_member', 'player_seat': None, 'public_object_ref': None,
            'object_type': None, 'zone': None, 'reason': 'target_role_unreviewed', 'list_position': position}
        if ident in (1, 2):
            if not valid_players:
                row['reason'] = 'player_list_unverified'
            elif any(x[1] or x[2] for x in collision if x[0] == ident):
                row['reason'] = 'player_entity_collision'
            else:
                row.update(target_instance_ref=ident, target_referent_kind='verified_player',
                    namespace='version_verified_player_instance', player_seat=ident, reason=None)
        elif ident in public:
            try:
                signature = _identity(reducer, ident, ('GameObjectType_Card', 'GameObjectType_Token'), 'ZoneType_Battlefield')
            except (ValueError, KeyError, TypeError):
                pass
            else:
                signatures[ident] = signature
                row.update(target_instance_ref=ident, target_referent_kind='verified_public_object',
                    namespace='public_game_object', public_object_ref=ident,
                    object_type=reducer.objects[ident]['type'], zone='ZoneType_Battlefield', reason=None)
        roles[ident] = row
    observation = _observe_target_fields(message,
        [{'object_ref': o['instance_id'], 'zone': o['zone']} for o in visible],
        state['binding']['self_seat'], allow_no_cancel=True, referent_roles=roles)
    constraints = observation['constraints']; source = constraints['source_object_ref']
    _need(source not in (1, 2))  # Same entity namespace; lookup priority is no proof.
    signatures[source] = _identity(reducer, source, ('GameObjectType_Ability',), 'ZoneType_Stack')
    source_row = reducer.objects[source]
    _need(all(type(source_row[k]) is int and source_row[k] == state['binding']['self_seat'] for k in
        ('ownerSeatId', 'controllerSeatId')) and source_row['grpId'] == constraints['ability_grp_ref'] == constraints['targeting_ability_grp_ref'])
    _need(all(type(constraints[k]) is int and constraints[k] == 1 for k in ('min_targets', 'max_targets')))
    stack = state['game']['stack']
    _need(stack['availability'] == 'observed' and any(m['instance_id'] == source and
        m['object_type'] == 'GameObjectType_Ability' for m in stack['members']))
    members = constraints['entries']
    unresolved = sum(r['target_referent_kind'] == 'unresolved' for r in members)
    select = all(r['legal_action'] == SELECT for r in members)
    complete = bool(members) and select and unresolved == 0 and constraints['selected_count'] is None
    selected = (copy.deepcopy(members) if len(members) == 1 and
        members[0]['legal_action'] == UNSELECT and type(constraints['selected_count']) is int and
        constraints['selected_count'] == 1 else None)
    proposals = []; total = None; truncated = False
    if complete:
        subsets, total, reason = _bounded_target_sets(members, 1, 1, limit)
        _need(reason is None)
        truncated = total > limit
        if not truncated:
            for position, chosen in enumerate(subsets):
                final = {'source_object_ref': source, 'target_idx': constraints['target_idx'], 'target_referents': chosen}
                validation = check_referent_final_set(constraints, final)
                _need(validation[0] == 'verified_known_constraints')
                proposal = {'schema_version': 'mtgaplayer.current-target-role-proposal.v1',
                    'request_identity': copy.deepcopy(state['binding']), 'source_snapshot_ref': copy.deepcopy(ref),
                    'proposed_current_target_referent_set': copy.deepcopy(final)}
                option = _option(state['binding'], ref, 'reviewed_role_target_set', ROLE_PROFILE, position,
                    proposal=proposal, scope='version_bound_current_offered_role_membership_and_explicit_one_count_only')
                option.update(research_eligible=False, local_validation={'status': validation[0], 'reason': validation[1]}, unresolved=list(UNKNOWN))
                proposals.append(option)
    after = _current_verified_raw_request(reducer, message)
    _need(after is not None and after.get('_target_evidence_interrupted') is not True and
        after.get('_continuity_verified') is True and reducer._target_state_continuity_verified is True and
        _equal(_binding(reducer, after), state['binding']) and type(reducer.accepted_digest) is bytes and digest == reducer.accepted_digest and
        _equal(version, current_build(reducer)) and _equal(players, reducer.players) and
        _equal(collision, _collision_witness(reducer, raw_ids)))
    for ident, signature in signatures.items():
        _need(_equal(signature, _identity(reducer, ident,
            ('GameObjectType_Ability',) if ident == source else ('GameObjectType_Card', 'GameObjectType_Token'),
            'ZoneType_Stack' if ident == source else 'ZoneType_Battlefield')))
    result = unknown('version_bound_current_referent_roles_and_local_constraints_only')
    result.update(schema_version=ROLE_VERSION, status='observed', profile=ROLE_PROFILE,
        current_request_binding=copy.deepcopy(state['binding']), source_snapshot_ref=copy.deepcopy(ref),
        version_mapping_evidence=version, source_identity={'object_ref': source, 'object_type': 'GameObjectType_Ability', 'zone': 'ZoneType_Stack'},
        target_constraints=copy.deepcopy(constraints), target_referents=copy.deepcopy(members),
        current_offered_members=copy.deepcopy([m for m in members if m['legal_action'] == SELECT]),
        current_selected_literal=selected, verified_player_memberships=sum(m['target_referent_kind'] == 'verified_player' for m in members),
        verified_public_object_memberships=sum(m['target_referent_kind'] == 'verified_public_object' for m in members),
        unresolved_memberships=unresolved, complete_current_select_domain_verified=complete,
        candidate_total_for_reviewed_constraints=total, returned_proposals=len(proposals),
        local_proposals=proposals, truncated=truncated, complete_legal_actions=None)
    _bounded_json(result)
    return result
