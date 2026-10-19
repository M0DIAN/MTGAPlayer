"""Finite source-edge branch of CastStage; no state owner, ledger or solver.

One frozen parent, consumed selection, four accepted Diffs and one opaque
stacking envelope may precede an independently frozen MP84 target domain.
Source identity never comes from the opaque SelectN response or future targets.
"""
import copy
import weakref

from .semantic_samples import _need, _keys, _snapshot, IDS
from .semantic_activate_targets import _same
from .choice_continuation import _binding, _scope, _prompt
from .response_evidence import _current_verified_raw_request, _paired_response
from .request_parameters import LiteralRefs
from .decision_consumer import EXECUTION, _bounded_json
from .target_build import current_build

VERSION = 'mtgaplayer.historical-parent-target-lineage.v1'
PROFILE = 'cast_hand_stack_resolve_unique_public_pending_ability_to_current_stack_target'
COUNTS = ('frozen_parent_requests', 'strict_parent_responses', 'uniquely_selected_cast',
    'uniquely_selected_activate', 'uniquely_selected_other', 'verified_cast_transfers',
    'verified_cast_resolutions', 'verified_ability_creations', 'verified_pending_to_stack_changes',
    'strict_opaque_stacking_responses', 'parent_child_source_lineages', 'linked_player_target_requests',
    'linked_mp85_target_updates', 'linked_selected_player_targets', 'linked_mp85_complete_stages')
ERRORS = (ValueError, TypeError, KeyError, IndexError, RecursionError, OverflowError)


def _uint(value, *, zero=False):
    _need(type(value) is int and (0 if zero else 1) <= value <= 2**32-1)


def _owns(stage):
    return any(type(value) is dict and any(k in value for k in
        ('lineage_parent', 'lineage_kind', 'lineage_child'))
        for value in (stage.cached, stage.prepared, stage.pending, stage.active))


def _reject(stage):
    stage.clear(); stage.suppressed = True


def _entity(reducer, ident, kind, zone_type, *, hand=False):
    """Only own-visible Hand or independently public source identity fields."""
    _uint(ident); _need(ident not in (1, 2) and len(reducer.zones) <= 512)
    obj = reducer.objects[ident]; zone = reducer.zones[obj['zoneId']]
    for value in (obj['instanceId'], obj['grpId'], obj['zoneId'], zone['zoneId']): _uint(value)
    _need(_same(obj['instanceId'], ident) and _same(zone['zoneId'], obj['zoneId']) and
        obj['type'] == kind and zone['type'] == zone_type and
        all(type(obj[k]) is int and obj[k] == reducer.seat for k in ('ownerSeatId', 'controllerSeatId')))
    if hand:
        # Reuse the Reducer's reviewed own-Hand/viewer/unique-membership proof.
        _need(ident in reducer._cast_source_refs())
        members = zone.get('objectInstanceIds')
        _need(type(members) is list and len(members) <= 512 and len(set(members)) == len(members))
        for value in members: _uint(value)
    else:
        # Pending is inspected through the same strict public identity checker,
        # without inserting it into the visible projection or MP65 candidates.
        from .current_target_request import _role_identity
        _role_identity(reducer, ident, (kind,), zone_type)
    identity = {key: copy.deepcopy(obj.get(key)) for key in ('instanceId', 'grpId', 'type',
        'parentId', 'ownerSeatId', 'controllerSeatId', 'uniqueAbilities')}
    if identity['parentId'] is not None: _uint(identity['parentId'], zero=True)
    return {'identity': identity, 'zone_ref': obj['zoneId'], 'zone_type': zone_type,
        'visibility': obj.get('visibility')}


def _pending_live(stage, saved, *, accepted_state=False):
    frozen = saved['lineage_parent']; consumer = frozen['consumer']()
    _need(consumer is not None and consumer.current_view()['consumer_status'] == 'OBSERVING' and
        _scope(stage.reducer) == saved['scope'] and
        _same(current_build(stage.reducer), frozen['build']) and type(stage.reducer.accepted_digest) is bytes)
    if not accepted_state:
        _need(_same(stage.reducer.version, saved['state_id']) and
            stage.reducer.accepted_digest == saved['state_digest'] and
            set(stage.reducer.objects) == saved['previous_object_ids'])


def _current_parent(stage, frozen):
    from .shadow_runtime import _raw_stamp
    consumer = frozen['consumer'](); _need(consumer is not None)
    request = _current_verified_raw_request(stage.reducer, frozen['message'])
    _need(request is not None and request.get('_continuity_verified') is True and
        _same(_binding(stage.reducer, request), frozen['options']['request_binding']) and
        _same(_raw_stamp(stage.reducer), frozen['stamp']) and
        set(stage.reducer.objects) == frozen['object_ids'] and
        _same(consumer.current_decision_options(), frozen['options']) and
        _same(consumer.shadow_decision(), frozen['policy']))
    view = consumer.current_view()
    _need(view['consumer_status'] == 'OBSERVING' and
        _same(view['current_snapshot_ref'], frozen['options']['source_snapshot_ref']) and
        _same(_raw_stamp(stage.reducer), frozen['stamp']))
    return request


def _selection(rows, selected):
    """The existing full-row plus full-identity uniqueness rule, without cost claims."""
    _need(type(rows) is list and 1 <= len(rows) <= 256 and all(type(row) is dict for row in rows))
    _need(type(selected) is dict and type(selected.get('actionType')) is str)
    kind = selected['actionType']
    required = {'instanceId', 'grpId', 'facetId'} if kind in ('ActionType_Cast', 'ActionType_Play') else (
        set(IDS) if kind == 'ActionType_Activate' else set())
    _need(required <= set(selected))
    identity = {key: selected[key] for key in IDS if key in selected}
    for value in identity.values(): _uint(value)
    full = [i for i, row in enumerate(rows) if _same(row, selected)]
    matches = [i for i, row in enumerate(rows) if row.get('actionType') == kind and
        all(_same(row.get(key), value) for key, value in identity.items())]
    _need(len(full) == 1 and full == matches)
    return full[0], kind, identity


def freeze(stage, consumer, message, options, policy, *, child_evidence=None, revision=None):
    from .shadow_runtime import _raw_stamp
    try:
        _bounded_json(message); _bounded_json(options); _bounded_json(policy)
        _need(type(message) is dict)
        typ = message.get('type')
        if typ not in ('GREMessageType_ActionsAvailableReq', 'GREMessageType_SelectTargetsReq'): return
        if typ == 'GREMessageType_SelectTargetsReq':
            saved = stage.pending
            if saved is None or 'lineage_parent' not in saved: return
            _pending_live(stage, saved)
            _need(saved['phase'] == 4 and saved.get('opaque_consumed') is True and
                _same(saved.get('child_message'), message) and consumer is saved['lineage_parent']['consumer']() and
                revision is not None and revision.cached is not None and 'role_frozen' in revision.cached)
            from .player_target_stages import _current
            frozen = revision.cached['role_frozen']
            _current(revision, frozen)
            ev = frozen['evidence']; constraints = ev['target_constraints']
            _need(_same(child_evidence, ev) and _same(policy, frozen['policy']) and
                _same(consumer.current_decision_options(), options) and
                _same(options['request_binding'], ev['current_request_binding']) and
                _same(options['source_snapshot_ref'], ev['source_snapshot_ref']) and
                ev['complete_current_select_domain_verified'] is True and ev['truncated'] is False and
                ev['unresolved_memberships'] == 0 and ev['verified_player_memberships'] > 0 and
                _same(constraints['target_idx'], 1) and
                _same(ev['version_mapping_evidence'], saved['lineage_parent']['build']) and
                _same(constraints['source_object_ref'], saved['ability_ref']) and
                _same(constraints['ability_grp_ref'], saved['ability']['identity']['grpId']) and
                _same(constraints['targeting_ability_grp_ref'], saved['ability']['identity']['grpId']))
            _source_current(stage, saved, stack=True)
            fact = copy.deepcopy(saved['fact'])
            fact.update(source_lineage_status='parent_child_source_lineage_verified',
                child_request_binding=copy.deepcopy(ev['current_request_binding']),
                child_snapshot_ref=copy.deepcopy(ev['source_snapshot_ref']),
                child_target_domain_status='independently_current_complete_local_role_domain',
                child_target_slot=constraints['target_idx'], child_player_memberships=ev['verified_player_memberships'],
                child_public_object_memberships=ev['verified_public_object_memberships'],
                child_frozen_record=stage.record_ordinal)
            _need(fact['parent_response_record'] < fact['child_frozen_record'])
            _bounded_json(fact)
            frozen['parent_source_lineage'] = copy.deepcopy(fact)
            stage.pending = None; stage.cached = None; stage.active = {'lineage_child': copy.deepcopy(fact)}
            stage.lineage_last = fact
            stage.lineage_counts['parent_child_source_lineages'] += 1
            stage.lineage_counts['linked_player_target_requests'] += 1
            return
        _need(type(stage.reducer.accepted_digest) is bytes)
        request = _current_verified_raw_request(stage.reducer, message)
        _need(request is not None and request.get('_continuity_verified') is True and current_build(stage.reducer) is not None)
        body = message['actionsAvailableReq']; _need(type(body) is dict and not set(body)-{'actions', 'inactiveActions'})
        rows = body['actions']; inactive = body.get('inactiveActions', [])
        _need(type(rows) is list and 1 <= len(rows) <= 256 and all(type(row) is dict for row in rows) and
            type(inactive) is list and len(inactive) <= 256 and all(type(row) is dict for row in inactive))
        if stage.cached and 'lineage_parent' in stage.cached and _same(
                stage.cached['lineage_parent']['options']['request_binding'], options['request_binding']):
            _current_parent(stage, stage.cached['lineage_parent']); return
        frozen = {'message': copy.deepcopy(message), 'options': copy.deepcopy(options), 'policy': copy.deepcopy(policy),
            'stamp': _raw_stamp(stage.reducer), 'consumer': weakref.ref(consumer), 'build': current_build(stage.reducer),
            'frozen_record': stage.record_ordinal, 'before': _snapshot(stage.reducer, LiteralRefs(), ()),
            'object_ids': set(stage.reducer.objects)}
        _need(len(frozen['object_ids']) <= 4096)
        _current_parent(stage, frozen)
        stage.clear(); stage.suppressed = False
        stage.cached = {'message': copy.deepcopy(message), 'lineage_parent': frozen}
        stage.lineage_counts['frozen_parent_requests'] += 1
    except ERRORS:
        _reject(stage)


def prepare(stage, record):
    """Own only the explicit branch's existing CastStage context."""
    if not _owns(stage): return False
    stage.suppressed = False; stage.prepared = None
    if stage.pending is not None:
        stage.age += 1
        if stage.age > 64: _reject(stage); return True
    try:
        _bounded_json(record)
        _need(type(record) is dict)
        # The retained source has the existing RawFramer's match-service
        # wrapper. These are transport metadata, never GRE request identities.
        _need(not set(record)-{'timestamp', 'greToClientEvent', 'payload',
            'clientToMatchServiceMessageType', 'requestId', 'transactionId'})
        transports = set(record) & {'greToClientEvent', 'payload'}
        _need(len(transports) <= 1)
        if set(record) & {'requestId', 'transactionId'}:
            _need({'requestId', 'transactionId', 'timestamp'} <= set(record) and len(transports) == 1 and
                type(record['requestId']) is int and 0 <= record['requestId'] <= 2**53-1 and
                type(record['transactionId']) is str and 1 <= len(record['transactionId']) <= 128)
        if 'clientToMatchServiceMessageType' in record:
            _keys(record, ('clientToMatchServiceMessageType', 'payload', 'requestId', 'timestamp', 'transactionId'))
            _need(record['clientToMatchServiceMessageType'] in (
                'ClientToMatchServiceMessageType_ClientToGREMessage',
                'ClientToMatchServiceMessageType_ClientToGREUIMessage') and
                type(record['payload']) is dict)
            if record['clientToMatchServiceMessageType'] == 'ClientToMatchServiceMessageType_ClientToGREUIMessage':
                _need(record['payload'].get('type') == 'ClientMessageType_UIMessage')
        if 'timestamp' in record:
            _need(type(record['timestamp']) is str and 1 <= len(record['timestamp']) <= 128)
        if 'payload' not in record:
            gre = record.get('greToClientEvent')
            if gre is None: return True
            messages = gre.get('greToClientMessages') if type(gre) is dict else None
            _need(type(messages) is list and 1 <= len(messages) <= 256)
            seen = set()
            for message in messages:
                _need(type(message) is dict)
                gs = message.get('gameStateMessage')
                if gs is not None:
                    _need(type(gs) is dict); ident = gs['gameStateId']; _uint(ident)
                    _need(ident not in seen and not _same(ident, stage.reducer.version)); seen.add(ident)
                if 'msgId' in message:
                    _uint(message['msgId'])
                    _need((stage.reducer.match, stage.reducer.game, message['msgId']) not in stage.reducer.consumed)
            if stage.pending is not None:
                _pending_live(stage, stage.pending)
                _endpoint_before_record(stage, stage.pending)
            return True
        _need('greToClientEvent' not in record)
        payload = record['payload']; _need(type(payload) is dict)
        if payload.get('type') == 'ClientMessageType_UIMessage': return True
        if stage.pending is not None:
            saved = stage.pending; _pending_live(stage, saved)
            _need(saved['phase'] == 3 and saved.get('opaque_request') is not None and not saved.get('opaque_consumed'))
            message = saved['opaque_request']; request = _current_verified_raw_request(stage.reducer, message)
            _need(request is not None and request.get('_continuity_verified') is True)
            binding = _binding(stage.reducer, request)
            _keys(payload, ('type', 'respId', 'gameStateId', 'selectNResp'))
            _need(payload['type'] == 'ClientMessageType_SelectNResp' and
                _same(payload['respId'], binding['request_id']) and _same(payload['gameStateId'], binding['game_state_id']))
            for value in (payload['respId'], payload['gameStateId']): _uint(value)
            _keys(payload['selectNResp'], ('ids', 'useArbitrary'))
            _need(_same(payload['selectNResp']['ids'], [0]) and
                payload['selectNResp']['useArbitrary'] == 'OrderingType_OrderArbitraryOnce')
            _source_current(stage, saved, stack=False)
            stage.pending = None
            stage.prepared = {'lineage_kind': 'opaque', 'saved': saved, 'before': copy.deepcopy(request),
                'payload': copy.deepcopy(payload), 'scope': _scope(stage.reducer)}
            return True
        _need(stage.cached is not None and 'lineage_parent' in stage.cached and stage.active is None)
        frozen = stage.cached['lineage_parent']; request = _current_parent(stage, frozen)
        _keys(payload, ('type', 'respId', 'gameStateId', 'performActionResp'))
        _need(payload['type'] == 'ClientMessageType_PerformActionResp' and
            _same(payload['respId'], request['id']) and _same(payload['gameStateId'], request['game_state_id']))
        for value in (payload['respId'], payload['gameStateId']): _uint(value)
        response = payload['performActionResp']; _keys(response, ('actions', 'autoPassPriority'))
        _need(response['autoPassPriority'] == 'AutoPassPriority_Yes' and
            type(response['actions']) is list and len(response['actions']) == 1)
        selected = response['actions'][0]
        position, kind, identity = _selection(frozen['message']['actionsAvailableReq']['actions'], selected)
        source = _entity(stage.reducer, identity['instanceId'], 'GameObjectType_Card', 'ZoneType_Hand', hand=True
            ) if kind == 'ActionType_Cast' else None
        if source is not None: _need(_same(source['identity']['grpId'], identity['grpId']))
        stage.prepared = {'lineage_kind': 'parent', 'frozen': frozen, 'before': copy.deepcopy(request),
            'payload': copy.deepcopy(payload), 'scope': _scope(stage.reducer), 'position': position,
            'action_type': kind, 'identity': identity, 'source': source}
    except ERRORS:
        _reject(stage)
    return True


def after_apply(stage):
    saved = stage.prepared; stage.prepared = None
    try:
        _need(saved is not None and _scope(stage.reducer) == saved['scope'] and stage.reducer.request is None)
        typ = 'ClientMessageType_PerformActionResp' if saved['lineage_kind'] == 'parent' else 'ClientMessageType_SelectNResp'
        _need(_paired_response(stage.reducer, saved['before'], saved['payload'], typ) and
            _same(stage.reducer.version, saved['before']['game_state_id']))
        if saved['lineage_kind'] == 'opaque':
            pending = saved['saved']; _pending_live(stage, pending); _source_current(stage, pending, stack=False)
            pending['opaque_consumed'] = True
            pending['fact']['intermediate_request'] = {'request_binding': _binding(stage.reducer, saved['before']),
                'offered_ref_count': 3, 'response_type': typ, 'strict_consumption_verified': True,
                'response_construction': 'pinned_arbitrary_once_zero_sentinel', 'member_identity_verified': False,
                'member_selection_legality_verified': False, 'ordering_semantics_verified': False,
                'ability_identity_inferred_from_response': False}
            stage.pending = pending; stage.cached = None
            stage.lineage_counts['strict_opaque_stacking_responses'] += 1
            stage.lineage_last = copy.deepcopy(pending['fact']); return
        frozen = saved['frozen']; _need(_same(current_build(stage.reducer), frozen['build']))
        kind = saved['action_type']; stage.lineage_counts['strict_parent_responses'] += 1
        stage.lineage_counts[{'ActionType_Cast': 'uniquely_selected_cast',
            'ActionType_Activate': 'uniquely_selected_activate'}.get(kind, 'uniquely_selected_other')] += 1
        fact = {'schema_version': VERSION, 'profile': PROFILE,
            'source_lineage_status': 'unverified_pending_source_edges',
            'parent_request_binding': copy.deepcopy(frozen['options']['request_binding']),
            'parent_snapshot_ref': copy.deepcopy(frozen['options']['source_snapshot_ref']),
            'parent_current_opportunity_observed': True, 'parent_action_position': saved['position'], 'parent_action_type': kind,
            'parent_action_identity': copy.deepcopy(saved['identity']), 'parent_active_action_count': len(frozen['message']['actionsAvailableReq']['actions']),
            'parent_inactive_action_count': len(frozen['message']['actionsAvailableReq'].get('inactiveActions', [])),
            'parent_historical_selection_status': 'unique_original_active_row_strictly_consumed',
            'parent_frozen_policy': copy.deepcopy(frozen['policy']), 'parent_frozen_record': frozen['frozen_record'],
            'parent_response_record': stage.record_ordinal, 'source_transition_type': PROFILE, 'source_transition_evidence': [],
            'child_request_binding': None, 'child_snapshot_ref': None, 'child_target_domain_status': None,
            'historical_target_update_status': None, 'historical_terminal_status': None,
            'rules_trigger_causation_verified': False, 'complete_legality_verified': False, 'server_acceptance_verified': False,
            'unresolved_constraints': ['rules_trigger_causation_unknown', 'complete_payment_unknown', 'target_legality_unknown',
                'ordering_semantics_unknown', 'server_acceptance_unknown', 'tactical_value_unknown'],
            'historical_only': True, 'current': False, 'read_only': True, **EXECUTION}
        stage.lineage_last = copy.deepcopy(fact); stage.cached = stage.active = None
        if kind != 'ActionType_Cast': stage.pending = None; return
        _need(frozen['frozen_record'] < stage.record_ordinal and _same(saved['source'],
            _entity(stage.reducer, saved['identity']['instanceId'], 'GameObjectType_Card', 'ZoneType_Hand', hand=True)))
        stage.pending = {'lineage_parent': frozen, 'parent': copy.deepcopy(saved['identity']), 'scope': saved['scope'],
            'source': saved['source'], 'phase': 0, 'state_id': stage.reducer.version, 'fact': fact,
            'before': frozen['before'], 'object_ids': frozen['object_ids'], 'state_digest': stage.reducer.accepted_digest,
            'previous_object_ids': set(stage.reducer.objects)}
        stage.age = 0
    except ERRORS:
        _reject(stage)


def _rows(gs):
    rows = gs.get('annotations', [])
    _need(type(rows) is list and len(rows) <= 512 and all(type(row) is dict and type(row.get('type')) is list for row in rows))
    return rows


def _facts(stage, saved, gs, annotations, related):
    from .semantic_cast import facts
    result, status, omitted = facts({'annotations': annotations}, stage.reducer, LiteralRefs(), (),
        saved['before'], _snapshot(stage.reducer, LiteralRefs(), ()), set(related))
    _need(status == 'reviewed_subset' and omitted == 0)
    return result


def _other_migrations(gs, allowed, tracked):
    from .target_revision import _no_identity_migration
    _no_identity_migration({'annotations': [row for row in _rows(gs) if not any(row is a for a in allowed)]}, tracked)


def _source_current(stage, saved, *, stack):
    r = stage.reducer
    _need(len(r.objects) <= 4096)
    candidates = [i for i, obj in r.objects.items() if obj.get('type') == 'GameObjectType_Ability' and
        _same(obj.get('parentId'), saved['card_ref'])]
    _need(_same(candidates, [saved['ability_ref']]))
    card = _entity(r, saved['card_ref'], 'GameObjectType_Card', 'ZoneType_Battlefield')
    ability = _entity(r, saved['ability_ref'], 'GameObjectType_Ability', 'ZoneType_Stack' if stack else 'ZoneType_Pending')
    _need(_same(card, saved['card']) and _same(ability['identity'], saved['ability']['identity']))
    if stack: _need(_same(ability['zone_ref'], saved['stack_zone_ref']))
    else: _need(_same(ability, saved['ability']))


def _endpoint_before_record(stage, saved):
    r = stage.reducer
    if saved['phase'] == 0:
        _need(_same(_entity(r, saved['parent']['instanceId'], 'GameObjectType_Card',
            'ZoneType_Hand', hand=True), saved['source']))
    elif saved['phase'] in (1, 2):
        _need(_same(_entity(r, saved['card_ref'], 'GameObjectType_Card', 'ZoneType_Stack'), saved['card']))
    else:
        _source_current(stage, saved, stack=saved['phase'] == 4)


def _advance(stage, saved, gs):
    from .semantic_cast import _detail
    r = stage.reducer; phase = saved['phase']; original = saved['parent']['instanceId']; annotations = _rows(gs)
    if phase == 0:
        changed = [a for a in annotations if a['type'] == ['AnnotationType_ObjectIdChanged'] and
            (a.get('affectedIds') == [original] or _detail(a).get('orig_id') == original)]
        _need(len(changed) == 1); detail = _detail(changed[0]); _keys(detail, ('orig_id', 'new_id'))
        new = detail['new_id']; _uint(new)
        _need(_same(detail['orig_id'], original) and new not in saved['object_ids'])
        transfers = [a for a in annotations if a['type'] == ['AnnotationType_ZoneTransfer'] and a.get('affectedIds') == [new]]
        _need(len(transfers) == 1)
        found = _facts(stage, saved, gs, [changed[0], transfers[0]], {original})
        _need(_same(found, [{'kind': 'object_id_changed', 'original_object_ref': original, 'new_object_ref': new},
            {'kind': 'zone_transfer', 'object_ref': new, 'source_zone': 'ZoneType_Hand',
                'destination_zone': 'ZoneType_Stack', 'category': 'CastSpell'}]))
        card = _entity(r, new, 'GameObjectType_Card', 'ZoneType_Stack'); transfer = _detail(transfers[0])
        _need(_same(card['identity']['grpId'], saved['parent']['grpId']) and
            _same(transfer['zone_src'], saved['source']['zone_ref']) and _same(transfer['zone_dest'], card['zone_ref']) and
            r.objects[original]['type'] == 'GameObjectType_Card' and
            _same(r.objects[original]['grpId'], saved['parent']['grpId']) and
            r.zones[r.objects[original]['zoneId']]['type'] == 'ZoneType_Limbo' and
            original not in r.zones[saved['source']['zone_ref']]['objectInstanceIds'])
        _other_migrations(gs, changed+transfers, {original, new})
        saved.update(card_ref=new, card=card, stack_zone_ref=card['zone_ref'])
        edge = {'kind': 'annotated_cast_hand_to_stack_card', 'original_object_ref': original,
            'card_object_ref': new, 'state_id': r.version}
        stage.lineage_counts['verified_cast_transfers'] += 1
    elif phase == 1:
        _other_migrations(gs, [], {original, saved['card_ref']})
        _need(_same(_entity(r, saved['card_ref'], 'GameObjectType_Card', 'ZoneType_Stack'), saved['card']))
        edge = {'kind': 'source_identity_preserved', 'state_id': r.version}
    elif phase == 2:
        card_id = saved['card_ref']; card = _entity(r, card_id, 'GameObjectType_Card', 'ZoneType_Battlefield')
        _need(_same(card['identity'], saved['card']['identity']))
        resolution = [a for a in annotations if a['type'] in (['AnnotationType_ResolutionStart'],
            ['AnnotationType_ResolutionComplete'], ['AnnotationType_ZoneTransfer']) and a.get('affectedIds') == [card_id]]
        found = _facts(stage, saved, gs, resolution, {card_id})
        _need(_same(found, [{'kind': 'resolution_start', 'object_ref': card_id, 'card_id': saved['parent']['grpId']},
            {'kind': 'resolution_complete', 'object_ref': card_id, 'card_id': saved['parent']['grpId']},
            {'kind': 'zone_transfer', 'object_ref': card_id, 'source_zone': 'ZoneType_Stack',
                'destination_zone': 'ZoneType_Battlefield', 'category': 'Resolve'}]))
        transfer = _detail(resolution[-1])
        _need(_same(transfer['zone_src'], saved['stack_zone_ref']) and _same(transfer['zone_dest'], card['zone_ref']))
        created = [a for a in annotations if a['type'] == ['AnnotationType_AbilityInstanceCreated'] and
            a.get('affectorId') == card_id]
        candidates = [i for i, obj in r.objects.items() if
            obj.get('type') == 'GameObjectType_Ability' and _same(obj.get('parentId'), card_id)]
        _need(len(created) == len(candidates) == 1)
        annotation = created[0]; _keys(annotation, ('id', 'affectorId', 'affectedIds', 'type', 'details'))
        _uint(annotation['id']); _uint(annotation['affectorId'])
        _need(_same(annotation['affectedIds'], candidates)); ident = candidates[0]
        # Creation must be new at its immediate accepted predecessor, not just
        # absent at the older parent freeze. This witness contains IDs only.
        _need(ident not in saved['previous_object_ids'])
        ability = _entity(r, ident, 'GameObjectType_Ability', 'ZoneType_Pending')
        creation = _detail(annotation); _keys(creation, ('source_zone',))
        _need(_same(creation['source_zone'], card['zone_ref']))
        pairs = r.objects[card_id].get('uniqueAbilities')
        _need(type(pairs) is list and len(pairs) <= 256 and sum(type(p) is dict and
            _same(p.get('grpId'), ability['identity']['grpId']) for p in pairs) == 1)
        _other_migrations(gs, resolution+created, {original, card_id, ident})
        saved.update(card=card, ability_ref=ident, ability=ability)
        edge = {'kind': 'annotated_resolve_and_unique_public_pending_ability_created',
            'card_object_ref': card_id, 'ability_object_ref': ident, 'ability_grp_ref': ability['identity']['grpId'],
            'state_id': r.version, 'rules_trigger_causation_verified': False}
        stage.lineage_counts['verified_cast_resolutions'] += 1; stage.lineage_counts['verified_ability_creations'] += 1
    else:
        _need(phase == 3 and saved.get('opaque_consumed') is True)
        ident = saved['ability_ref']; _other_migrations(gs, [], {original, saved['card_ref'], ident})
        _source_current(stage, saved, stack=True)
        changed = [obj for obj in gs.get('gameObjects', []) if type(obj) is dict and _same(obj.get('instanceId'), ident)]
        _need(len(changed) == 1 and _same(changed[0].get('zoneId'), saved['stack_zone_ref']))
        zones = gs.get('zones'); _need(type(zones) is list and len(zones) <= 512)
        pending = [z for z in zones if type(z) is dict and _same(z.get('zoneId'), saved['ability']['zone_ref'])]
        stack = [z for z in zones if type(z) is dict and _same(z.get('zoneId'), saved['stack_zone_ref'])]
        _need(len(pending) == len(stack) == 1 and type(pending[0].get('objectInstanceIds')) is list and
            type(stack[0].get('objectInstanceIds')) is list and ident not in pending[0]['objectInstanceIds'] and
            stack[0]['objectInstanceIds'].count(ident) == 1)
        edge = {'kind': 'explicit_state_location_pending_to_stack', 'ability_object_ref': ident,
            'state_id': r.version, 'transfer_annotation_claimed': False}
        stage.lineage_counts['verified_pending_to_stack_changes'] += 1
    saved['fact']['source_transition_evidence'].append(edge)
    _need(len(r.objects) <= 4096)
    saved['phase'] += 1; saved['state_id'] = r.version; saved['state_digest'] = r.accepted_digest
    saved['previous_object_ids'] = set(r.objects)
    saved['before'] = _snapshot(r, LiteralRefs(), ())
    stage.lineage_last = copy.deepcopy(saved['fact'])


def observe(stage, event, details):
    if not _owns(stage): return False
    try:
        if event in ('continuity_error', 'unsupported_broadcast_request'):
            _reject(stage); return True
        if stage.suppressed: return True
        if event == 'request_ended':
            stage.cached = stage.active = None
            if details['disposition'] != 'consumed': stage.pending = stage.prepared = None
            return True
        if event == 'state_accepted':
            saved = stage.pending
            _need(saved is not None and 'lineage_parent' in saved and details['kind'] == 'diff')
            _pending_live(stage, saved, accepted_state=True); gs = details['message']
            _uint(gs['gameStateId']); _uint(gs['prevGameStateId'])
            _need(_same(gs['prevGameStateId'], saved['state_id']))
            _advance(stage, saved, gs); return True
        if event != 'request_accepted': return True
        saved = stage.pending
        _need(saved is not None and 'lineage_parent' in saved and not details['is_retransmission'])
        _pending_live(stage, saved)
        message = details['message']; request = _current_verified_raw_request(stage.reducer, message)
        _need(request is not None and request.get('_continuity_verified') is True and
            _same(request['game_state_id'], saved['state_id']))
        if saved['phase'] == 3:
            _need(saved.get('opaque_request') is None and message['type'] == 'GREMessageType_SelectNReq')
            _keys(message, ('type', 'systemSeatIds', 'msgId', 'gameStateId', 'prompt', 'selectNReq')); _prompt(message['prompt'])
            body = message['selectNReq']; _keys(body, ('minSel', 'maxSel', 'context', 'optionContext',
                'listType', 'ids', 'idType', 'validationType'))
            _need(_same(body['minSel'], 1) and _same(body['maxSel'], 3) and
                body['context'] == 'SelectionContext_TriggeredAbility' and body['optionContext'] == 'OptionContext_Stacking' and
                body['listType'] == 'SelectionListType_Dynamic' and body['idType'] == 'IdType_InstanceId' and
                body['validationType'] == 'SelectionValidationType_NonRepeatable' and
                type(body['ids']) is list and len(body['ids']) == len(set(body['ids'])) == 3)
            for ident in body['ids']: _uint(ident)
            _source_current(stage, saved, stack=False)
            saved['opaque_request'] = copy.deepcopy(message); return True
        _need(saved['phase'] == 4 and saved.get('opaque_consumed') is True and
            saved.get('child_message') is None and message['type'] == 'GREMessageType_SelectTargetsReq')
        _source_current(stage, saved, stack=True)
        saved['child_message'] = copy.deepcopy(message)
    except ERRORS:
        _reject(stage)
    return True


def link_target_fact(stage, target):
    """Join only the same MP85 fact; never change its completion grade."""
    fact = stage.lineage_last
    if type(fact) is not dict or type(target) is not dict or 'parent_source_lineage' not in target: return
    lineage = target['parent_source_lineage']
    if not (_same(lineage.get('parent_request_binding'), fact.get('parent_request_binding')) and
            _same(target.get('first_request_binding'), fact.get('child_request_binding')) and
            _same(target.get('first_snapshot_ref'), fact.get('child_snapshot_ref'))): return
    if fact.get('historical_target_update_status') is None:
        stage.lineage_counts['linked_mp85_target_updates'] += 1
        stage.lineage_counts['linked_selected_player_targets'] += target['historical_selected_role'] == 'verified_player'
        fact['historical_target_update_status'] = 'historical_target_update_verified'
        fact['historically_selected_role'] = target['historical_selected_role']
    if target.get('terminal_consumed') is True and fact.get('historical_terminal_status') is None:
        stage.lineage_counts['linked_mp85_complete_stages'] += 1
        fact['historical_terminal_status'] = 'historical_target_stage_complete'


def report(stage, *, include_last=False):
    _need(type(include_last) is bool)
    c = stage.lineage_counts
    result = {'schema_version': VERSION, 'profile': PROFILE,
        'units': {'parents': 'unique first-current authenticated ActionsAvailable completed-poll freezes',
            'responses': 'strict unique active-row client selections consumed by the single Reducer',
            'source_lineages': 'one supported four-Diff source profile; independent current child freeze',
            'target_stages': 'same MP85 facts; updates are not terminal submissions'},
        **{key: c[key] for key in COUNTS},
        'unlinked_or_interrupted_attempts': c['uniquely_selected_cast']-c['parent_child_source_lineages'],
        'activate_source_transitions': None, 'complete_target_legality': None, 'complete_action_legality': None,
        'rules_trigger_causation_verified': False, 'server_acceptance_verified': False,
        'historical_only': True, 'current': False, 'read_only': True, **EXECUTION}
    if include_last: result['last_historical_fact'] = copy.deepcopy(stage.lineage_last)
    return result
