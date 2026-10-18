"""One consumed Cast -> independently current four-member first target request.

Instrumentation of the existing StageObserver/reducer, never a second parser.
Transfer/selection attestations belong to the producer; portable checks establish
consistency, not raw authentication, complete legality, payment or acceptance.
"""
import copy

from .semantic_samples import _need, _keys, _snapshot
from .request_parameters import LiteralRefs
from . import semantic_cast as cast, semantic_targets as targets
from .semantic_activate_targets import _same
from .choice_continuation import _binding, _scope, _positive
from .response_evidence import _current_verified_raw_request, _paired_response
from .decision_consumer import EXECUTION

FIELD = 'cast_choice_continuation'
PRIVATE = '_cast_choice_continuation'
PROVENANCE = 'mtgaplayer.cast-choice-continuation.v1'
VERSION = 'mtgaplayer.current-cast-continuation.v1'
SCOPE = 'consumed_actual_cast_to_first_current_four_member_target_request'
DENIALS = dict.fromkeys(('parent_current', 'complete_legality_verified',
    'complete_legal_choice_verified', 'target_domain_complete_verified',
    'overall_payability_verified', 'complete_payment_verified', 'rules_causation_verified',
    'response_encoding_verified', 'server_acceptance_verified',
    'future_result_used_for_child_constraints', 'raw_source_reauthenticated'), False)


def _child(message, binding, visible):
    """Preserve the actual finite envelope, including absence of selected count."""
    _keys(message, ('type', 'msgId', 'gameStateId', 'systemSeatIds', 'allowCancel', 'allowUndo', 'selectTargetsReq'))
    _need(message['type'] == binding['request_type'] == 'GREMessageType_SelectTargetsReq' and
        _same(message['msgId'], binding['request_id']) and _same(message['gameStateId'], binding['game_state_id']) and
        _same(message['systemSeatIds'], [binding['self_seat']]) and message['allowUndo'] is True)
    body = message['selectTargetsReq']; _keys(body, ('sourceId', 'abilityGrpId', 'targets'))
    _need(type(body['targets']) is list and len(body['targets']) == 1)
    slot = body['targets'][0]
    _keys(slot, ('targetIdx', 'targets', 'minTargets', 'maxTargets', 'targetingAbilityGrpId', 'targetingPlayer'))
    for v in (body['sourceId'], body['abilityGrpId'], slot['targetIdx'], slot['targetingAbilityGrpId']): _positive(v)
    _need(type(slot['minTargets']) is int and type(slot['maxTargets']) is int and
        slot['minTargets'] == slot['maxTargets'] == 1 and type(slot['targets']) is list and len(slot['targets']) == 4)
    for entry in slot['targets']:
        _keys(entry, ('targetInstanceId', 'legalAction'))
        _positive(entry['targetInstanceId']); _need(entry['legalAction'] == targets.SELECT)
    return targets.project_request(message, visible, binding['self_seat'], LiteralRefs(), ())


class CastStage:
    """Bounded subordinate context; one selected row, one Diff, one first child."""
    def __init__(self, reducer):
        self.reducer = reducer
        self.reset()

    def clear(self):
        if self.reducer.request is not None: self.reducer.request.pop(PRIVATE, None)
        self.cached = self.prepared = self.pending = self.active = None
        self.age = 0

    def reset(self):
        self.suppressed = False
        self.clear()

    def prepare(self, record):
        from .decision_consumer import _bounded_json
        self.suppressed = False
        self.prepared = None
        if self.pending is not None:
            self.age += 1
            if self.age > 64: self.clear()
        try:
            _bounded_json(record)
            _need(type(record) is dict and not set(record) - {'timestamp', 'greToClientEvent', 'payload'})
            if 'payload' not in record:
                gre = record.get('greToClientEvent')
                if gre is not None:
                    _need(type(gre) is dict and type(gre.get('greToClientMessages')) is list and len(gre['greToClientMessages']) == 1)
                    message = gre['greToClientMessages'][0]
                    state = message.get('gameStateMessage') if type(message) is dict else None
                    # Identical Diff retransmissions are intentionally silent in
                    # RawReducer. They cannot renew this narrower lineage.
                    if type(state) is dict and _same(state.get('gameStateId'), self.reducer.version):
                        self.clear(); self.suppressed = True
                return
            _need('greToClientEvent' not in record)
            payload = record['payload']
            if type(payload) is dict and payload.get('type') == 'ClientMessageType_UIMessage': return
            if self.active is not None:
                self.clear(); return
            self.pending = None
            _keys(payload, ('type', 'respId', 'gameStateId', 'performActionResp'))
            _need(payload['type'] == 'ClientMessageType_PerformActionResp' and self.cached is not None)
            saved = self.cached
            request = _current_verified_raw_request(self.reducer, saved['message']); _need(request is not None)
            _keys(payload['performActionResp'], ('actions', 'autoPassPriority'))
            response = payload['performActionResp']
            _need(response['autoPassPriority'] == 'AutoPassPriority_Yes' and
                type(response['actions']) is list and len(response['actions']) == 1)
            selected = response['actions'][0]
            from .cast_target_members import _literal
            literal = _literal(selected, 'ActionType_Cast')
            rows = saved['message']['actionsAvailableReq']['actions']
            full = [i for i, row in enumerate(rows) if _same(row, selected)]
            ids = literal['identifier_refs']
            identities = [i for i, row in enumerate(rows) if row.get('actionType') == 'ActionType_Cast' and
                all(_same(row.get(k), v) for k, v in ids.items())]
            _need(len(full) == 1 and full == identities)
            position = full[0]; params = request['_request_parameters']
            _need(any(v['list_position'] == position and _same(v['action'], literal) for v in params['cast_actions']))
            source = self.reducer.objects[ids['instanceId']]; zone = self.reducer.zones[source['zoneId']]
            _need(source['instanceId'] in params['cast_source_refs'] and source['type'] == 'GameObjectType_Card' and
                _same(source['grpId'], ids['grpId']) and source['ownerSeatId'] == source['controllerSeatId'] == self.reducer.seat and
                zone['type'] == 'ZoneType_Hand' and zone['ownerSeatId'] == self.reducer.seat and
                sum(source['instanceId'] in z.get('objectInstanceIds', []) for z in self.reducer.zones.values()) == 1)
            _need(len(literal['parameters']['targets'][0]['targets']) == 4 and len(self.reducer.objects) <= 4096)
            parent = {'binding': _binding(self.reducer, request), 'list_position': position,
                'active_action_count': len(rows), 'inactive_action_count': len(saved['message']['actionsAvailableReq'].get('inactiveActions', [])),
                'action': literal, 'source_zone_ref': source['zoneId'], 'current': False}
            self.prepared = {'request': copy.deepcopy(request), 'payload': copy.deepcopy(payload), 'parent': parent,
                'scope': _scope(self.reducer), 'before': saved['before'], 'object_ids': set(self.reducer.objects)}
        except (ValueError, TypeError, KeyError, IndexError, RecursionError):
            self.clear(); self.suppressed = True

    def after_apply(self):
        prepared = self.prepared; self.prepared = None
        if prepared is not None:
            if (_scope(self.reducer) == prepared['scope'] and self.reducer.request is None and
                    _paired_response(self.reducer, prepared['request'], prepared['payload'], 'ClientMessageType_PerformActionResp')):
                self.pending = prepared; self.cached = None; self.age = 0
            else: self.clear()

    def observe(self, event, details):
        r = self.reducer
        if event in ('continuity_error', 'unsupported_broadcast_request'):
            self.clear(); self.suppressed = True; return
        if self.suppressed: return
        if event == 'request_ended':
            details['request'].pop(PRIVATE, None)
            self.cached = self.active = None
            if details['disposition'] != 'consumed': self.pending = self.prepared = None
            return
        try:
            if event == 'state_accepted':
                if details['kind'] != 'diff' or self.active is not None:
                    self.clear(); self.suppressed = True; return
                if self.pending is None: return
                saved = self.pending; gs = details['message']; parent = saved['parent']
                _need(_scope(r) == saved['scope'] and 'transfer' not in saved and
                    _same(gs['prevGameStateId'], parent['binding']['game_state_id']))
                original = parent['action']['identifier_refs']['instanceId']
                facts, status, omitted = cast.facts(gs, r, LiteralRefs(), (), saved['before'], _snapshot(r, LiteralRefs(), ()), {original})
                _need(status == 'reviewed_subset' and omitted == 0 and len(gs['annotations']) == 2 and
                    len(facts) == 2 and facts[0]['kind'] == 'object_id_changed')
                new = facts[0]['new_object_ref']; _positive(new)
                _need(_same(facts, [{'kind': 'object_id_changed', 'original_object_ref': original, 'new_object_ref': new},
                    {'kind': 'zone_transfer', 'object_ref': new, 'source_zone': 'ZoneType_Hand',
                     'destination_zone': 'ZoneType_Stack', 'category': 'CastSpell'}]) and new not in saved['object_ids'])
                obj = r.objects[new]; zone = r.zones[obj['zoneId']]
                d = cast._detail(gs['annotations'][1])
                _need(_same(d['zone_src'], parent['source_zone_ref']) and _same(d['zone_dest'], obj['zoneId']) and
                    original not in r.zones[parent['source_zone_ref']].get('objectInstanceIds', []) and
                    r.objects[original]['type'] == 'GameObjectType_Card' and
                    r.zones[r.objects[original]['zoneId']]['type'] == 'ZoneType_Limbo' and
                    obj['type'] == 'GameObjectType_Card' and obj['visibility'] == zone['visibility'] == 'Visibility_Public' and
                    zone['type'] == 'ZoneType_Stack' and _same(obj['grpId'], parent['action']['identifier_refs']['grpId']) and
                    obj['ownerSeatId'] == obj['controllerSeatId'] == r.seat and
                    zone.get('objectInstanceIds', []).count(new) == 1 and
                    sum(new in z.get('objectInstanceIds', []) for z in r.zones.values()) == 1)
                saved['transfer'] = {'original_object_ref': original, 'stack_object_ref': new,
                    'source_zone_ref': parent['source_zone_ref'], 'stack_zone_ref': obj['zoneId'], 'observed_state_id': r.version}
                return
            if event != 'request_accepted': return
            message = details['message']; request = _current_verified_raw_request(r, message); _need(request is not None)
            if details['is_retransmission']:
                self.clear(); self.suppressed = True; return
            self.cached = self.active = None
            if request['type'] == 'GREMessageType_ActionsAvailableReq':
                from .cast_target_members import PROFILE
                params = request.get('_request_parameters')
                _need(type(params) is dict and params.get('profile') == PROFILE)
                self.pending = None
                self.cached = {'message': copy.deepcopy(message), 'before': _snapshot(r, LiteralRefs(), ())}
                return
            saved = self.pending; self.pending = None
            _need(saved is not None and 'transfer' in saved and _scope(r) == saved['scope'])
            value = {'schema_version': PROVENANCE, 'binding': _binding(r, request), 'parent': saved['parent'],
                'transfer': saved['transfer'], 'child_message': copy.deepcopy(message)}
            constraints = _child(message, value['binding'], _snapshot(r, LiteralRefs(), ())['objects'])
            _need(_same(constraints, request.get('_request_parameters')) and
                _same(constraints['source_object_ref'], saved['transfer']['stack_object_ref']) and
                _same(constraints['target_idx'], saved['parent']['action']['parameters']['targets'][0]['targetIdx']) and
                _same([e['object_ref'] for e in constraints['entries']],
                    [e['targetInstanceId'] for e in saved['parent']['action']['parameters']['targets'][0]['targets']]))
            self.active = value; request[PRIVATE] = copy.deepcopy(value)
        except (ValueError, TypeError, KeyError, IndexError, RecursionError):
            self.clear(); self.suppressed = True


def check(value, binding, params, visible, stack):
    from .decision_consumer import _binding as check_binding, _integer
    from .cast_target_members import _literal
    from .semantic_activate import raw_action
    if value is None: return
    _keys(value, ('schema_version', 'binding', 'parent', 'transfer', 'child_message'))
    _need(value['schema_version'] == PROVENANCE and _same(value['binding'], binding))
    check_binding(binding, complete=True)
    p = value['parent']; t = value['transfer']
    _keys(p, ('binding', 'list_position', 'active_action_count', 'inactive_action_count', 'action', 'source_zone_ref', 'current'))
    check_binding(p['binding'], complete=True)
    _need(p['binding']['request_type'] == 'GREMessageType_ActionsAvailableReq' and p['binding']['request_id'] is not None and
        p['binding']['request_id'] != binding['request_id'] and p['binding']['game_state_id'] < binding['game_state_id'] and
        all(_same(p['binding'][k], binding[k]) for k in ('source_generation', 'match', 'game', 'self_seat')) and p['current'] is False)
    _integer(p['active_action_count'], 1, 256); _integer(p['inactive_action_count'], 0, 256)
    _integer(p['list_position'], 0, p['active_action_count'] - 1); _positive(p['source_zone_ref'])
    _need(_same(_literal(raw_action(p['action']), 'ActionType_Cast'), p['action']))
    _keys(t, ('original_object_ref', 'stack_object_ref', 'source_zone_ref', 'stack_zone_ref', 'observed_state_id'))
    for v in t.values(): _positive(v)
    ids = p['action']['identifier_refs']; slot = p['action']['parameters']['targets'][0]
    _need(_same(t['original_object_ref'], ids['instanceId']) and t['original_object_ref'] != t['stack_object_ref'] and
        _same(t['source_zone_ref'], p['source_zone_ref']) and _same(t['observed_state_id'], binding['game_state_id']))
    objects = {o['instance_id']: o for o in visible}; obj = objects.get(t['stack_object_ref'])
    _need(obj is not None and obj['zone'] == 'ZoneType_Stack' and _same(obj['card_id'], ids['grpId']) and
        obj['owner_seat'] == obj['controller_seat'] == binding['self_seat'] and t['original_object_ref'] not in objects and
        stack['availability'] == 'observed' and _same(stack['zone_id'], t['stack_zone_ref']) and
        len([m for m in stack['members'] if _same(m['instance_id'], t['stack_object_ref']) and m['object_type'] == 'GameObjectType_Card']) == 1)
    constraints = _child(value['child_message'], binding, [{'object_ref': o['instance_id'], 'zone': o['zone']} for o in visible])
    _need(type(params) is dict and params['profile'] == targets.PROFILE and _same(params['targets'], constraints) and
        _same(constraints['source_object_ref'], t['stack_object_ref']) and _same(constraints['target_idx'], slot['targetIdx']) and
        _same([e['object_ref'] for e in constraints['entries']], [e['targetInstanceId'] for e in slot['targets']]))


def unknown(reason, ref=None):
    return {'schema_version': VERSION, 'scope': SCOPE, 'status': 'insufficient_evidence', 'reason': reason,
        'source_snapshot_ref': copy.deepcopy(ref), 'request_binding': None, 'historical_parent': None, 'transfer': None,
        'historical_selected_parent_observed': False, 'current_child_request_verified': False,
        'engine_offered': False, 'known_constraints_verified': False, 'candidates': [], 'read_only': True, **DENIALS, **EXECUTION}


def evaluate_continuation(state, *, source_snapshot_ref=None):
    from .decision_consumer import _bounded_json, _state, _reference
    from .choice_candidates import enumerate_known_candidates
    try:
        _bounded_json(state); _state(state, state['binding'])
        if (state['schema_version'] != 'mtgaplayer.decision-state.v15' or
                state['status'] != 'state_and_request_observed' or state['source']['stopped'] is True or state[FIELD] is None):
            return unknown('current_cast_first_child_not_observed', source_snapshot_ref)
        if source_snapshot_ref is not None:
            _reference(source_snapshot_ref, source_snapshot_ref['session_id'], source_snapshot_ref['sequence'], snapshot=True)
            _need(_same(source_snapshot_ref['binding'], state['binding']))
        proposals = enumerate_known_candidates(state, source_snapshot_ref=source_snapshot_ref, version=2)
        _need(len(proposals['candidates']) == 4 and all(len(c['proposed_final_target_set']['object_refs']) == 1 for c in proposals['candidates']))
        result = unknown('observed_cast_transfer_and_independently_current_child', source_snapshot_ref)
        result.update(status='continuation_relationship_consistent', request_binding=copy.deepcopy(state['binding']),
            historical_parent=copy.deepcopy(state[FIELD]['parent']), transfer=copy.deepcopy(state[FIELD]['transfer']),
            historical_selected_parent_observed=True, current_child_request_verified=True,
            engine_offered=True, known_constraints_verified=True, candidates=proposals['candidates'])
        _bounded_json(result); return result
    except (ValueError, TypeError, KeyError, IndexError, RecursionError, OverflowError):
        return unknown('state_or_cast_continuation_invalid')


def assess_current_continuation(consumer):
    from .choice_candidates import _assess_current_report
    return _assess_current_report(consumer, evaluate_continuation, unknown)
