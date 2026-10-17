"""First observed consumed Activate -> separately current target request.

One bounded observer of the existing reducer. No history ledger, speculative
branch, response encoder or input authority. The first child ends this context.
"""
import copy

from .semantic_samples import _need, _keys, IDS
from .raw_log import _id
from .request_parameters import LiteralRefs
from . import semantic_targets as targets, semantic_activate as activate
from . import semantic_activate_targets as history
from .response_evidence import _current_verified_raw_request, _paired_response
from .decision_consumer import EXECUTION

FIELD = 'choice_continuation'
PRIVATE = '_choice_continuation'
PROVENANCE = 'mtgaplayer.choice-continuation.v1'
VERSION = 'mtgaplayer.current-choice-continuation.v1'
SCOPE = 'consumed_actual_activate_to_first_current_target_request_only'
DENIALS = dict.fromkeys(('parent_current', 'complete_legal_choice_verified', 'complete_legality_verified',
    'overall_payability_verified', 'complete_payment_verified', 'target_domain_complete_verified',
    'rules_causation_verified', 'unique_ability_identity_continuation_verified',
    'response_encoding_verified', 'server_acceptance_verified', 'future_result_used_for_child_constraints',
    'raw_source_reauthenticated'), False)


def _binding(reducer, request):
    return {'source_generation': reducer.generation, 'match': reducer.match, 'game': reducer.game,
        'self_seat': reducer.seat, 'game_state_id': request['game_state_id'],
        'request_id': request['id'], 'request_type': request['type']}


def _scope(reducer):
    return reducer.generation, reducer.match, reducer.game, reducer.seat


def _positive(value):
    _need(_id(value) and value > 0)


def _prompt(value, *, number=False):
    _keys(value, ('promptId', 'parameters') if number else ('promptId',))
    _need(type(value['promptId']) is int and 0 < value['promptId'] < 2**32)
    if number:
        _need(type(value['parameters']) is list and len(value['parameters']) == 1)
        parameter = value['parameters'][0]
        _keys(parameter, ('parameterName', 'type', 'numberValue'))
        _need(type(parameter['parameterName']) is str and 0 < len(parameter['parameterName']) <= 128 and
            parameter['type'] == 'ParameterType_Number' and type(parameter['numberValue']) is int and
            -(2**31) <= parameter['numberValue'] < 2**31)


def _observe_child(message, visible, seat):
    """Validate every witnessed field before using the existing target projector."""
    _need(type(message) is dict and not set(message) - {'type', 'msgId', 'gameStateId', 'systemSeatIds',
        'prompt', 'selectTargetsReq', 'allowCancel', 'allowUndo'} and message['type'] == 'GREMessageType_SelectTargetsReq')
    _prompt(message['prompt'])
    body = message['selectTargetsReq']; _keys(body, ('sourceId', 'abilityGrpId', 'targets'))
    _need(type(body['targets']) is list and len(body['targets']) == 1)
    slot = body['targets'][0]
    _need(type(slot) is dict and {'targetIdx', 'targets', 'prompt', 'targetingAbilityGrpId', 'targetingPlayer'} <= slot.keys() and
        not set(slot) - {'targetIdx', 'targets', 'prompt', 'targetingAbilityGrpId', 'targetingPlayer', 'minTargets', 'maxTargets', 'selectedTargets'})
    _prompt(slot['prompt'], number=True)
    for key in ('sourceId', 'abilityGrpId'): _positive(body[key])
    for key in ('targetIdx', 'targetingAbilityGrpId'): _positive(slot[key])
    for key in ('minTargets', 'maxTargets', 'selectedTargets'):
        if key in slot: _need(type(slot[key]) is int and 0 <= slot[key] <= 256)
    _need(type(slot['targets']) is list and 1 <= len(slot['targets']) <= 64)
    for entry in slot['targets']:
        _need(type(entry) is dict and set(entry) in ({'targetInstanceId', 'legalAction'},
            {'targetInstanceId', 'legalAction', 'highlight'}))
        _positive(entry['targetInstanceId'])
        _need(entry['legalAction'] in (targets.SELECT, targets.UNSELECT) and
            ('highlight' not in entry or type(entry['highlight']) is str and len(entry['highlight']) <= 128))
    observed = {'constraints': targets.project_request(message, visible, seat, LiteralRefs(), ()),
        'envelope_prompt': copy.deepcopy(message['prompt']), 'slot_prompt': copy.deepcopy(slot['prompt']),
        'target_entries': copy.deepcopy(slot['targets']),
        'field_presence': {key: key in slot for key in ('minTargets', 'maxTargets', 'selectedTargets')}}
    observed['field_presence']['allowUndo'] = 'allowUndo' in message
    # This new context covers the witnessed first child only. Other menus keep
    # the existing target validator, without treating all offers as a selection.
    constraints = observed['constraints']
    _need(constraints['min_targets'] == constraints['max_targets'] == 1 and
        constraints['selected_count'] is None and 'selectedTargets' not in slot and
        len(constraints['entries']) == 1 and constraints['entries'][0]['legal_action'] == targets.SELECT)
    return observed


def _raw_child(observation, binding):
    """Lossless reconstruction of the finite child observation, for cross-checks."""
    _keys(observation, ('constraints', 'envelope_prompt', 'slot_prompt', 'target_entries', 'field_presence'))
    value = observation['constraints']; presence = observation['field_presence']
    _keys(presence, ('minTargets', 'maxTargets', 'selectedTargets', 'allowUndo'))
    _need(all(type(v) is bool for v in presence.values()))
    slot = {'targetIdx': value['target_idx'], 'targetingAbilityGrpId': value['targeting_ability_grp_ref'],
        'targetingPlayer': value['targeting_player'], 'targets': observation['target_entries'], 'prompt': observation['slot_prompt']}
    for raw, projected in (('minTargets', 'min_targets'), ('maxTargets', 'max_targets'), ('selectedTargets', 'selected_count')):
        if presence[raw]: slot[raw] = value[projected]
        else: _need(value[projected] is None)
    result = {'type': binding['request_type'], 'msgId': binding['request_id'], 'gameStateId': binding['game_state_id'],
        'systemSeatIds': [binding['self_seat']], 'prompt': observation['envelope_prompt'],
        'selectTargetsReq': {'sourceId': value['source_object_ref'], 'abilityGrpId': value['ability_grp_ref'], 'targets': [slot]},
        'allowCancel': value['allow_cancel']}
    if presence['allowUndo']: result['allowUndo'] = value['allow_undo']
    else: _need(value['allow_undo'] is None)
    return result


class StageObserver:
    """Private opt-in prepare/apply/finish instrumentation, like TapObserver."""
    def __init__(self, reducer):
        self.reducer = reducer
        self.reset()

    def reset(self):
        if self.reducer.request is not None: self.reducer.request.pop(PRIVATE, None)
        self.cached = self.prepared = self.pending = self.active = None
        self.age = 0

    def _clear(self):
        if self.reducer.request is not None: self.reducer.request.pop(PRIVATE, None)
        self.reset()

    def prepare(self, record):
        from .decision_consumer import _bounded_json
        self.prepared = None
        if self.pending is not None:
            self.age += 1
            if self.age > 64: self._clear()
        payload = record.get('payload') if type(record) is dict else None
        if not isinstance(payload, dict): return
        if any(k in record for k in ('authenticateResponse', 'matchGameRoomStateChangedEvent', 'greToClientEvent')):
            self._clear(); return
        # Existing response evidence treats standalone UIMessage as telemetry,
        # not a submitted choice. It supplies no continuation evidence.
        if payload.get('type') == 'ClientMessageType_UIMessage': return
        if payload.get('type') in ('ClientMessageType_CancelActionReq', 'ClientMessageType_UndoReq'):
            self._clear(); return
        if self.active is not None:
            # This finite child context ends at any subsequent client reply;
            # unsupported replies cannot leave a displayed proof alive.
            self._clear(); return
        # Any further submission ends a pending first-child edge. Never use an
        # old consumed-set entry to re-arm it after a duplicate or wrong reply.
        self.pending = None
        try:
            _bounded_json(record)
            _need(not any(k in record for k in ('authenticateResponse', 'matchGameRoomStateChangedEvent', 'greToClientEvent')))
            _keys(payload, ('type', 'respId', 'gameStateId', 'performActionResp'))
            _need(payload['type'] == 'ClientMessageType_PerformActionResp' and self.cached is not None)
            saved = self.cached; request = _current_verified_raw_request(self.reducer, saved['message'])
            _need(request is not None and request['_continuity_verified'] is True)
            _keys(payload['performActionResp'], ('actions', 'autoPassPriority'))
            _need(payload['performActionResp']['autoPassPriority'] == 'AutoPassPriority_Yes' and
                type(payload['performActionResp']['actions']) is list and len(payload['performActionResp']['actions']) == 1)
            selected = payload['performActionResp']['actions'][0]
            position = history._exact_selected_position(saved['message']['actionsAvailableReq']['actions'], selected)
            _need(set(selected) == {'actionType', *IDS, 'shouldStop', 'manaCost', 'autoTapSolution', 'targets'})
            literal = targets.action(history._without_highlight(selected), LiteralRefs(), ())
            history._check_visible_action(literal, saved['public'], self.reducer.seat)
            source = self.reducer.objects[selected['instanceId']]
            from .action_target_menus import public_battlefield_refs
            _need(source['instanceId'] in public_battlefield_refs(self.reducer) and source['grpId'] == selected['grpId'] and
                source.get('ownerSeatId') == source.get('controllerSeatId') == self.reducer.seat and
                activate.ability_observation(selected, source.get('uniqueAbilities')) == 'verified_observed_pair' and
                len([z for z in self.reducer.zones.values() if source['instanceId'] in z.get('objectInstanceIds', [])]) == 1)
            _prompt(saved['message']['prompt'])
            _need(len(self.reducer.objects) <= 4096)
            parent = {'binding': _binding(self.reducer, request), 'list_position': position,
                'active_action_count': len(saved['message']['actionsAvailableReq']['actions']),
                'identifier_refs': copy.deepcopy(literal['identifier_refs']), 'flags': copy.deepcopy(literal['flags']),
                'target_idx': literal['parameters']['targets'][0]['targetIdx'], 'source_zone_ref': source['zoneId'],
                'prompt': copy.deepcopy(saved['message']['prompt']), 'response_type': payload['type'],
                'auto_pass_priority': payload['performActionResp']['autoPassPriority'], 'current': False}
            self.prepared = {'request': copy.deepcopy(request), 'payload': copy.deepcopy(payload), 'parent': parent,
                'scope': _scope(self.reducer), 'public': saved['public'], 'literal': literal,
                'source_signature': self._source_signature(source), 'object_ids': set(self.reducer.objects)}
        except (ValueError, TypeError, KeyError, IndexError, RecursionError):
            self._clear()

    def after_apply(self):
        prepared = self.prepared; self.prepared = None
        if (prepared is not None and _scope(self.reducer) == prepared['scope'] and self.reducer.request is None and
                _paired_response(self.reducer, prepared['request'], prepared['payload'], 'ClientMessageType_PerformActionResp')):
            self.pending = prepared; self.cached = None; self.age = 0
        elif prepared is not None:
            self._clear()

    @staticmethod
    def _source_signature(source):
        return {k: source.get(k) for k in ('instanceId', 'grpId', 'type', 'zoneId', 'visibility', 'ownerSeatId', 'controllerSeatId')}

    def observe(self, event, details):
        r = self.reducer
        if event in ('continuity_error', 'unsupported_broadcast_request'): self._clear(); return
        if event == 'request_ended':
            self.cached = self.active = None
            details['request'].pop(PRIVATE, None)
            if details['disposition'] != 'consumed': self.pending = self.prepared = None
            return
        try:
            if event == 'state_accepted':
                if details['kind'] != 'diff': self._clear(); return
                if self.pending is None: return
                saved = self.pending; gs = details['message']
                _need(details['kind'] == 'diff' and _scope(r) == saved['scope'] and 'ability' not in saved and
                    gs['prevGameStateId'] == saved['parent']['binding']['game_state_id'])
                current = history._public(r, LiteralRefs(), ())
                source = r.objects[saved['parent']['identifier_refs']['instanceId']]
                _need(history._same(self._source_signature(source), saved['source_signature']))
                facts, status, _ = activate.facts(gs, r, LiteralRefs(), (), saved['public'], current, saved['literal'], [])
                created = [f for f in facts if f['kind'] == 'ability_created']
                _need(status == 'reviewed_activate_subset' and len(created) == 1)
                ident = created[0]['ability_object_ref']; obj = r.objects[ident]; zone = r.zones[obj['zoneId']]
                from .semantic_cast import _detail
                annotations = [a for a in gs['annotations'] if type(a) is dict and a.get('type') == ['AnnotationType_AbilityInstanceCreated'] and
                    a.get('affectedIds') == [ident] and a.get('affectorId') == source['instanceId']]
                _need(len(annotations) == 1 and _detail(annotations[0])['source_zone'] == saved['parent']['source_zone_ref'])
                previous = saved['object_ids']
                competing = [i for i, o in r.objects.items() if i not in previous and
                    o.get('type') == 'GameObjectType_Ability' and o.get('parentId') == source['instanceId'] and
                    o.get('grpId') == saved['parent']['identifier_refs']['abilityGrpId']]
                _need(competing == [ident] and obj.get('visibility') == zone.get('visibility') == 'Visibility_Public' and
                    zone.get('type') == 'ZoneType_Stack' and obj.get('controllerSeatId') == r.seat and
                    len([z for z in r.zones.values() if ident in z.get('objectInstanceIds', [])]) == 1)
                saved['ability'] = {'object_ref': ident, 'parent_object_ref': obj['parentId'], 'ability_grp_ref': obj['grpId'],
                    'zone_ref': obj['zoneId'], 'created_state_id': r.version, 'controller_seat': obj['controllerSeatId']}
                return
            if event != 'request_accepted': return
            message = details['message']; request = _current_verified_raw_request(r, message)
            _need(request is not None)
            if details['is_retransmission']:
                if self.active is not None and history._same(self.active['binding'], _binding(r, request)):
                    request[PRIVATE] = copy.deepcopy(self.active)
                return
            self.cached = self.active = None
            if request['type'] == 'GREMessageType_ActionsAvailableReq':
                from .cast_activate_associations import PROFILE
                params = request.get('_request_parameters')
                _need(type(params) is dict and params.get('profile') == PROFILE)
                from .decision_consumer import _bounded_json
                _bounded_json(message)
                self.pending = None
                self.cached = {'message': copy.deepcopy(message), 'public': history._public(r, LiteralRefs(), ())}
                return
            saved = self.pending; self.pending = None
            _need(saved is not None and 'ability' in saved and _scope(r) == saved['scope'])
            observation = _observe_child(message, history._public(r, LiteralRefs(), ())['objects'], r.seat)
            _need(history._target_link_matches(observation['constraints'], saved['literal'], saved['ability']['object_ref']) and
                history._same(observation['constraints'], request.get('_request_parameters')))
            value = {'schema_version': PROVENANCE, 'binding': _binding(r, request), 'parent': saved['parent'],
                'stack_ability': saved['ability'], 'child_observation': observation}
            self.active = value; request[PRIVATE] = copy.deepcopy(value)
        except (ValueError, TypeError, KeyError, IndexError, RecursionError):
            self._clear()


def check(value, binding, params, visible, stack):
    """Portable consistency only; raw/digest/annotation gates belong to producer."""
    from .decision_consumer import _binding as check_binding, _integer
    if value is None: return
    _keys(value, ('schema_version', 'binding', 'parent', 'stack_ability', 'child_observation'))
    _need(value['schema_version'] == PROVENANCE and history._same(value['binding'], binding))
    check_binding(value['binding'], complete=True)
    _need(binding['request_type'] == 'GREMessageType_SelectTargetsReq' and binding['request_id'] is not None)
    p = value['parent']; a = value['stack_ability']
    _keys(p, ('binding', 'list_position', 'active_action_count', 'identifier_refs', 'flags', 'target_idx',
        'source_zone_ref', 'prompt', 'response_type', 'auto_pass_priority', 'current'))
    check_binding(p['binding'], complete=True)
    _need(p['binding']['request_type'] == 'GREMessageType_ActionsAvailableReq' and p['binding']['request_id'] is not None and
        p['binding']['request_id'] != binding['request_id'] and p['binding']['game_state_id'] < binding['game_state_id'] and
        all(history._same(p['binding'][k], binding[k]) for k in ('source_generation', 'match', 'game', 'self_seat')) and
        p['current'] is False and p['response_type'] == 'ClientMessageType_PerformActionResp' and p['auto_pass_priority'] == 'AutoPassPriority_Yes')
    _integer(p['active_action_count'], 1, 256); _integer(p['list_position'], 0, p['active_action_count'] - 1)
    _keys(p['identifier_refs'], IDS)
    for v in p['identifier_refs'].values(): _positive(v)
    _keys(p['flags'], ('shouldStop',)); _need(type(p['flags']['shouldStop']) is bool)
    _positive(p['target_idx']); _positive(p['source_zone_ref']); _prompt(p['prompt'])
    _keys(a, ('object_ref', 'parent_object_ref', 'ability_grp_ref', 'zone_ref', 'created_state_id', 'controller_seat'))
    for k in a: _positive(a[k])
    _need(a['controller_seat'] == binding['self_seat'] and a['created_state_id'] == binding['game_state_id'] and
        a['parent_object_ref'] == p['identifier_refs']['instanceId'] and a['ability_grp_ref'] == p['identifier_refs']['abilityGrpId'])
    objects = {o['instance_id']: o for o in visible}; source = objects.get(a['parent_object_ref']); ability = objects.get(a['object_ref'])
    _need(source is not None and source['zone'] == 'ZoneType_Battlefield' and source['card_id'] == p['identifier_refs']['grpId'] and
        source['owner_seat'] == source['controller_seat'] == binding['self_seat'] and ability is not None and
        ability['zone'] == 'ZoneType_Stack' and ability['controller_seat'] == binding['self_seat'])
    _need(stack['availability'] == 'observed' and stack['zone_id'] == a['zone_ref'] and
        len([m for m in stack['members'] if m['instance_id'] == a['object_ref'] and m['object_type'] == 'GameObjectType_Ability']) == 1)
    observed = _observe_child(_raw_child(value['child_observation'], binding),
        [{'object_ref': o['instance_id'], 'zone': o['zone']} for o in visible], binding['self_seat'])
    _need(history._same(observed, value['child_observation']) and type(params) is dict and params['profile'] == targets.PROFILE and
        history._same(params['targets'], observed['constraints']) and observed['constraints']['source_object_ref'] == a['object_ref'] and
        observed['constraints']['ability_grp_ref'] == a['ability_grp_ref'] and observed['constraints']['target_idx'] == p['target_idx'])


def unknown(reason, ref=None):
    return {'schema_version': VERSION, 'scope': SCOPE, 'status': 'insufficient_evidence', 'reason': reason,
        'source_snapshot_ref': copy.deepcopy(ref), 'request_binding': None, 'historical_parent': None,
        'stack_ability': None, 'child_observation': None, 'historical_selected_parent_observed': False,
        'current_child_request_verified': False, 'continuation_relationship_consistent': False,
        'request_local_membership_count_status': 'insufficient_evidence', 'read_only': True, **DENIALS, **EXECUTION}


def evaluate_continuation(state, *, source_snapshot_ref=None):
    from .decision_consumer import _bounded_json, _state, _reference
    try:
        _bounded_json(state); _state(state, state['binding'])
        if (state['status'] != 'state_and_request_observed' or state['binding']['request_id'] is None or
                state['source']['stopped'] is True):
            return unknown('current_child_request_not_observed')
        if source_snapshot_ref is not None:
            _reference(source_snapshot_ref, source_snapshot_ref['session_id'], source_snapshot_ref['sequence'], snapshot=True)
            _need(history._same(source_snapshot_ref['binding'], state['binding']))
        if state['schema_version'] != 'mtgaplayer.decision-state.v13' or state[FIELD] is None:
            return unknown('first_current_child_continuation_not_observed', source_snapshot_ref)
        value = state[FIELD]; constraints = value['child_observation']['constraints']; entries = constraints['entries']
        # This is the old request-local checker, not a new legal-target solver.
        local = targets.check_final_set(constraints, {'source_object_ref': constraints['source_object_ref'],
            'target_idx': constraints['target_idx'], 'object_refs': [e['object_ref'] for e in entries]})[0]
        result = unknown('observed_parent_and_separately_current_child', source_snapshot_ref)
        result.update(status='continuation_relationship_consistent', request_binding=copy.deepcopy(state['binding']),
            historical_parent=copy.deepcopy(value['parent']), stack_ability=copy.deepcopy(value['stack_ability']),
            child_observation=copy.deepcopy(value['child_observation']), historical_selected_parent_observed=True,
            current_child_request_verified=True, continuation_relationship_consistent=True, request_local_membership_count_status=local)
        _bounded_json(result); return result
    except (ValueError, TypeError, KeyError, IndexError, RecursionError, OverflowError):
        return unknown('state_or_continuation_evidence_invalid')


def assess_current_continuation(consumer):
    from .choice_candidates import _assess_current_report
    return _assess_current_report(consumer, evaluate_continuation, unknown)
