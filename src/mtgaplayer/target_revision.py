"""One observed Select update -> separately current revised target stage.

Subordinate bounded context on the existing StageObserver/reducer; no reader,
history ledger, target solver, encoder or input authority.
"""
import copy

from .semantic_samples import _need, _keys
from .raw_log import _id
from .request_parameters import LiteralRefs
from .response_evidence import _current_verified_raw_request, _paired_response, _paired_terminal_submit
from .decision_consumer import EXECUTION
from . import choice_continuation as first, semantic_targets as targets, semantic_activate_targets as history

FIELD = 'revised_choice_continuation'
PRIVATE = '_revised_choice_continuation'
PROVENANCE = 'mtgaplayer.revised-choice-continuation.v1'
VERSION = 'mtgaplayer.current-target-revision.v1'
SCOPE = 'one_consumed_select_update_to_separately_current_one_selected_revision'
FACTS = ('historical_parent_action_consumed', 'first_child_request_consumed',
    'selection_update_observed', 'current_revised_child_verified', 'current_selected_literal_consistent')
DENIALS = {**first.DENIALS, 'first_child_current': False, 'full_select_domain_verified': False,
    'complete_target_selection_legality_verified': False, 'client_final_submit_observed': False,
    'future_result_used_for_revised_constraints': False}


def _selection(payload, binding, request):
    """Preserve every reviewed field before calling the old response checker."""
    _keys(payload, ('type', 'respId', 'gameStateId', 'selectTargetsResp'))
    _need(payload['type'] == 'ClientMessageType_SelectTargetsResp' and
        type(payload['respId']) is int and payload['respId'] == binding['request_id'] and
        type(payload['gameStateId']) is int and payload['gameStateId'] == binding['game_state_id'])
    _keys(payload['selectTargetsResp'], ('target',)); target = payload['selectTargetsResp']['target']
    _keys(target, ('targetIdx', 'targets')); first._positive(target['targetIdx'])
    _need(type(target['targets']) is list and len(target['targets']) == 1)
    entry = target['targets'][0]
    _need(type(entry) is dict and set(entry) in ({'targetInstanceId', 'legalAction'},
        {'targetInstanceId', 'legalAction', 'highlight'}))
    first._positive(entry['targetInstanceId'])
    _need(entry['legalAction'] == targets.SELECT and
        ('highlight' not in entry or type(entry['highlight']) is str and len(entry['highlight']) <= 128))
    reply = targets.response(payload, {'type': binding['request_type']}, request, LiteralRefs(), ())['payload']
    _need(reply['operation'] == 'selection_update')
    return {'request_binding': copy.deepcopy(binding), 'response_type': payload['type'],
        'target': copy.deepcopy(target)}, reply


def _payload(update):
    _keys(update, ('request_binding', 'response_type', 'target'))
    binding = update['request_binding']
    return {'type': update['response_type'], 'respId': binding['request_id'],
        'gameStateId': binding['game_state_id'], 'selectTargetsResp': {'target': copy.deepcopy(update['target'])}}


def _observe_revised(message, visible, seat):
    observed = first._observe_target_fields(message, visible, seat)
    value = observed['constraints']; presence = observed['field_presence']
    _need(all(presence[k] for k in ('minTargets', 'maxTargets', 'selectedTargets')) and
        all(type(value[k]) is int and value[k] == 1 for k in ('min_targets', 'max_targets', 'selected_count')) and
        len(value['entries']) == 1 and value['entries'][0]['legal_action'] == targets.UNSELECT)
    return observed


def _selected_check(request, visible, seat, stack):
    keys = ('source_object_ref', 'ability_grp_ref', 'targeting_ability_grp_ref', 'target_idx', 'targeting_player')
    proposed = {k: request[k] for k in keys}; proposed['object_refs'] = targets.literal_selected(request)
    return targets.check_current_selected_set(request, proposed, visible, seat, stack)[0]


def _signature(reducer, ident):
    from .decision_consumer import _bounded_json
    obj = reducer.objects[ident]; zone = reducer.zones[obj['zoneId']]
    _need(obj.get('visibility') == zone.get('visibility') == 'Visibility_Public' and
        sum(ident in z.get('objectInstanceIds', []) for z in reducer.zones.values()) == 1)
    value = {'object': {k: obj.get(k) for k in ('instanceId', 'grpId', 'type', 'parentId', 'zoneId',
        'visibility', 'ownerSeatId', 'controllerSeatId', 'uniqueAbilities')},
        'zone': {k: zone.get(k) for k in ('zoneId', 'type', 'visibility')}}
    _bounded_json(value)
    return copy.deepcopy(value)


def _target_identity(reducer, ident):
    obj = reducer.objects[ident]
    _need(obj['type'] in ('GameObjectType_Card', 'GameObjectType_Token'))
    return {'object_ref': ident, 'card_ref': obj['grpId'] if obj['type'] == 'GameObjectType_Card' else None, 'object_type': obj['type'],
        'zone_ref': obj['zoneId'], 'owner_seat': obj['ownerSeatId'], 'controller_seat': obj['controllerSeatId']}


class RevisionStage:
    def __init__(self, reducer):
        self.reducer = reducer
        self.reset()

    def reset(self):
        if self.reducer.request is not None: self.reducer.request.pop(PRIVATE, None)
        self.cached = self.prepared = self.pending = self.active = None
        self.terminal = None; self.client_submit_observed = False; self.age = 0
        self.suppressed = False

    def _invalidate_record(self):
        self.reset()
        self.suppressed = True

    def prepare(self, record, active_first):
        from .decision_consumer import _bounded_json
        self.suppressed = False
        self.prepared = self.terminal = None; self.client_submit_observed = False
        if self.pending is not None:
            self.age += 1
            if self.age > 64: self.reset()
        if type(record) is not dict: self._invalidate_record(); return
        transports = set(record) & {'payload', 'authenticateResponse', 'matchGameRoomStateChangedEvent', 'greToClientEvent'}
        if len(transports) > 1: self._invalidate_record(); return
        if transports & {'authenticateResponse', 'matchGameRoomStateChangedEvent'}: self._invalidate_record(); return
        payload = record.get('payload')
        if 'payload' in record and type(payload) is not dict: self._invalidate_record(); return
        if type(payload) is not dict:
            gre = record.get('greToClientEvent')
            messages = gre.get('greToClientMessages') if type(gre) is dict else None
            if type(messages) is list and any(type(m) is dict and type(m.get('gameStateMessage')) is dict and
                    history._same(m['gameStateMessage'].get('gameStateId'), self.reducer.version) for m in messages):
                # Identical Diff retransmissions are silent reducer no-ops;
                # they still break this finite revision lineage.
                self._invalidate_record()
            return
        if payload.get('type') == 'ClientMessageType_UIMessage': return
        try:
            _bounded_json(record)
            if self.active is not None:
                request = _current_verified_raw_request(self.reducer, self.cached['message'])
                if payload.get('type') == 'ClientMessageType_SubmitTargetsReq':
                    _keys(payload, ('type', 'respId', 'gameStateId'))
                    _need(request is not None and type(payload['respId']) is int and type(payload['gameStateId']) is int)
                    terminal = {'before': copy.deepcopy(request), 'payload': copy.deepcopy(payload), 'scope': first._scope(self.reducer)}
                    self.reset(); self.terminal = terminal; return
                self.reset(); return
            _need(active_first is not None and self.cached is not None and self.pending is None)
            request = _current_verified_raw_request(self.reducer, self.cached['message'])
            _need(request is not None and history._same(active_first, request.get(first.PRIVATE)) and
                history._same(active_first['binding'], first._binding(self.reducer, request)))
            update, reply = _selection(payload, active_first['binding'], active_first['child_observation']['constraints'])
            ident = reply['entries'][0]['object_ref']; ability = active_first['stack_ability']
            signatures = {i: _signature(self.reducer, i) for i in (ability['parent_object_ref'], ability['object_ref'], ident)}
            prepared = {'before': copy.deepcopy(request), 'payload': copy.deepcopy(payload),
                'scope': first._scope(self.reducer), 'first_child': copy.deepcopy(active_first),
                'selection_update': update, 'reply': reply, 'signatures': signatures,
                'selected_target_identity': _target_identity(self.reducer, ident)}
            self.reset(); self.prepared = prepared
        except (ValueError, TypeError, KeyError, IndexError, RecursionError):
            self._invalidate_record()

    def after_apply(self):
        r = self.reducer; saved = self.prepared; self.prepared = None
        if saved is not None:
            if (first._scope(r) == saved['scope'] and r.request is None and
                    _paired_response(r, saved['before'], saved['payload'], 'ClientMessageType_SelectTargetsResp')):
                self.pending = saved; self.age = 0
            else: self.reset()
        terminal = self.terminal; self.terminal = None
        if terminal is not None:
            self.client_submit_observed = (first._scope(r) == terminal['scope'] and
                _paired_terminal_submit(r, terminal['before'], terminal['payload']))

    def observe(self, event, details, active_first):
        r = self.reducer
        if self.suppressed: return
        if event in ('continuity_error', 'unsupported_broadcast_request'): self._invalidate_record(); return
        if event == 'request_ended':
            if r.request is not None: r.request.pop(PRIVATE, None)
            self.active = self.cached = None
            if details['disposition'] != 'consumed': self._invalidate_record()
            return
        try:
            if event == 'state_accepted':
                if details['kind'] != 'diff': self._invalidate_record(); return
                if self.pending is None: return
                saved = self.pending; gs = details['message']
                _need('intervening_diff_count' not in saved and first._scope(r) == saved['scope'] and
                    history._same(gs['prevGameStateId'], saved['first_child']['binding']['game_state_id']))
                _need(all(history._same(_signature(r, i), signature) for i, signature in saved['signatures'].items()))
                saved['intervening_diff_count'] = 1; saved['state_id'] = r.version
                return
            if event != 'request_accepted': return
            message = details['message']; request = _current_verified_raw_request(r, message)
            _need(request is not None and not details['is_retransmission'])
            if active_first is not None:
                self.reset(); self.cached = {'message': copy.deepcopy(message)}; return
            saved = self.pending; self.pending = None
            _need(saved is not None and saved.get('intervening_diff_count') == 1 and
                first._scope(r) == saved['scope'] and request['game_state_id'] == saved['state_id'])
            _need(all(history._same(_signature(r, i), signature) for i, signature in saved['signatures'].items()))
            visible = history._public(r, LiteralRefs(), ())['objects']
            observation = _observe_revised(message, visible, r.seat)
            old = saved['first_child']['child_observation']['constraints']; current = observation['constraints']
            _need(history._revision_binding_matches(old, current) and history._selection_revision_matches(saved['reply'], current) and
                history._same(current, request.get('_request_parameters')))
            value = {'schema_version': PROVENANCE, 'binding': first._binding(r, request),
                'first_child': saved['first_child'], 'selection_update': saved['selection_update'],
                'revised_observation': observation, 'selected_target_identity': saved['selected_target_identity'],
                'intervening_diff_count': 1}
            stack = r.document(include_decision_state=True)['current']['_public_stack']
            _need(_selected_check(current, visible, r.seat, stack) == 'verified_known_constraints')
            self.active = value; self.cached = {'message': copy.deepcopy(message)}; request[PRIVATE] = copy.deepcopy(value)
        except (ValueError, TypeError, KeyError, IndexError, RecursionError):
            self._invalidate_record()


def check(value, binding, params, visible, stack):
    from .decision_consumer import _binding as check_binding, _integer
    if value is None: return
    _keys(value, ('schema_version', 'binding', 'first_child', 'selection_update', 'revised_observation',
        'selected_target_identity', 'intervening_diff_count'))
    _need(value['schema_version'] == PROVENANCE and history._same(value['binding'], binding))
    check_binding(binding, complete=True); f = value['first_child']; old_binding = f['binding']
    first.check(f, old_binding, {'profile': targets.PROFILE, 'targets': f['child_observation']['constraints']}, visible, stack)
    _need(binding['request_type'] == 'GREMessageType_SelectTargetsReq' and binding['request_id'] is not None and
        binding['request_id'] not in (old_binding['request_id'], f['parent']['binding']['request_id']) and
        binding['game_state_id'] > old_binding['game_state_id'] and
        all(history._same(binding[k], old_binding[k]) for k in ('source_generation', 'match', 'game', 'self_seat')) and
        type(value['intervening_diff_count']) is int and value['intervening_diff_count'] == 1)
    update, reply = _selection(_payload(value['selection_update']), old_binding, f['child_observation']['constraints'])
    _need(history._same(update, value['selection_update']))
    objects = [{'object_ref': o['instance_id'], 'zone': o['zone']} for o in visible]
    observed = _observe_revised(first._raw_child(value['revised_observation'], binding), objects, binding['self_seat'])
    current = observed['constraints']
    _need(history._same(observed, value['revised_observation']) and type(params) is dict and params['profile'] == targets.PROFILE and
        history._same(params['targets'], current) and history._revision_binding_matches(f['child_observation']['constraints'], current) and
        history._selection_revision_matches(reply, current) and _selected_check(current, objects, binding['self_seat'], stack) == 'verified_known_constraints')
    identity = value['selected_target_identity']
    _keys(identity, ('object_ref', 'card_ref', 'object_type', 'zone_ref', 'owner_seat', 'controller_seat'))
    for key in ('object_ref', 'zone_ref'): first._positive(identity[key])
    if identity['object_type'] == 'GameObjectType_Card': first._positive(identity['card_ref'])
    else: _need(identity['card_ref'] is None)
    for key in ('owner_seat', 'controller_seat'): _integer(identity[key], 1, 2)
    _need(identity['object_type'] in ('GameObjectType_Card', 'GameObjectType_Token') and identity['object_ref'] == targets.literal_selected(current)[0])
    target = next(o for o in visible if o['instance_id'] == identity['object_ref'])
    _need(target['zone'] == 'ZoneType_Battlefield' and history._same(target['card_id'], identity['card_ref']) and
        target['owner_seat'] == identity['owner_seat'] and target['controller_seat'] == identity['controller_seat'])


def unknown(reason, ref=None):
    return {'schema_version': VERSION, 'scope': SCOPE, 'status': 'insufficient_evidence', 'reason': reason,
        'source_snapshot_ref': copy.deepcopy(ref), 'request_binding': None, 'continuation': None,
        **dict.fromkeys(FACTS, False), 'request_local_selected_set_status': 'insufficient_evidence',
        'read_only': True, **DENIALS, **EXECUTION}


def evaluate_revision(state, *, source_snapshot_ref=None):
    from .decision_consumer import _bounded_json, _state, _reference
    try:
        _bounded_json(state); _state(state, state['binding'])
        _need(state['status'] == 'state_and_request_observed' and state['binding']['request_id'] is not None and state['source']['stopped'] is not True)
        if source_snapshot_ref is not None:
            _reference(source_snapshot_ref, source_snapshot_ref['session_id'], source_snapshot_ref['sequence'], snapshot=True)
            _need(history._same(source_snapshot_ref['binding'], state['binding']))
        if state['schema_version'] != 'mtgaplayer.decision-state.v14' or state[FIELD] is None:
            return unknown('current_revised_stage_not_observed', source_snapshot_ref)
        result = unknown('actual_selection_and_separately_current_revised_request', source_snapshot_ref)
        result.update(status='current_revision_relationship_consistent', request_binding=copy.deepcopy(state['binding']),
            continuation=copy.deepcopy(state[FIELD]), **dict.fromkeys(FACTS, True), request_local_selected_set_status='verified_known_constraints')
        _bounded_json(result); return result
    except (ValueError, TypeError, KeyError, IndexError, StopIteration, RecursionError, OverflowError):
        return unknown('state_or_revised_stage_evidence_invalid')


def assess_current_revision(consumer):
    from .choice_candidates import _assess_current_report
    return _assess_current_report(consumer, evaluate_revision, unknown)
