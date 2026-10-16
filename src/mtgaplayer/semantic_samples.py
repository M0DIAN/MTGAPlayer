"""Offline, value-preserving *sanitized* episodes, not raw GRE replay or input.

Only the existing reducer authenticates source messages. Portable replay checks
the exported relationships; it cannot reauthenticate the removed private log.
Nonempty opaque parameters and unknown fields never leave this boundary.
"""
from collections import Counter
import copy
import json
import os
from pathlib import Path
import tempfile

from .decision_consumer import EXECUTION
from .raw_log import RawFollower, RawReducer, _id
from .response_evidence import (_current_verified_request, _current_verified_raw_request,
    _paired_response, _paired_combat_submit, _paired_terminal_submit)
from .choice_graph import _selectn_known_constraints

VERSION = 'mtgaplayer.semantic-samples.v1'
MAX_BYTES = 2 * 1024 * 1024
KINDS = {'GREMessageType_ActionsAvailableReq': 'actions_available',
         'GREMessageType_SelectNReq': 'select_n',
         'GREMessageType_SelectTargetsReq': 'select_targets',
         'GREMessageType_GroupReq': 'group', 'GREMessageType_MulliganReq': 'mulligan',
         'GREMessageType_DeclareAttackersReq': 'declare_attackers',
         'GREMessageType_DeclareBlockersReq': 'declare_blockers'}
ORIGINS = ('unclassified_local', 'retained_scrubbed_real', 'synthetic')
IDS = ('instanceId', 'grpId', 'facetId', 'abilityGrpId', 'uniqueAbilityId')
BOOLS = ('shouldStop', 'isBatchable', 'isManaAbilityWithSideEffect')
PARAMS = ('manaCost', 'targets', 'manaPaymentOptions', 'manaSelections', 'autoTapSolution')
COMPLEX = ('ActionType_Cast', 'ActionType_Activate', 'ActionType_Activate_Mana')
ZONES = ('ZoneType_Hand', 'ZoneType_Battlefield', 'ZoneType_Stack', 'ZoneType_Graveyard', 'ZoneType_Exile')
REASONS = ('request_unsupported', 'response_unsupported', 'known_constraints_violated',
           'snapshot_unsupported', 'mixed_record_ordering', 'source_pair_unavailable')
SUCCESSORS = ('not_observed', 'continuous_state_observed', 'next_request_observed',
              'full_baseline_not_continuous', 'interrupted')
PROJECTION = {'raw_equivalent': False, 'state_fields': 'visible_endpoint_subset',
    'omitted_categories': ['private_identity_and_log_metadata', 'prompt_payloads',
        'hidden_object_identity', 'unfiltered_selection_ids', 'inactive_actions',
        'nonprojected_state_fields'],
    'nonempty_action_parameters': 'unsupported_whole_pair'}


class SampleError(ValueError):
    """Fixed, path/value-free errors suitable for the CLI."""


def _need(ok, reason='invalid_semantic_sample'):
    if not ok:
        raise SampleError(reason)


def _keys(value, names):
    _need(type(value) is dict and set(value) == set(names))


class _Refs:
    def __init__(self):
        self.maps = {}

    def ref(self, domain, scope, value):
        mapping = self.maps.setdefault(domain, {})
        key = (scope, value)
        if key not in mapping:
            mapping[key] = len(mapping) + 1
        return mapping[key]


def _snapshot(reducer, refs, scope):
    # Only the established public projection, never objects/zones working maps.
    current = reducer.document()['current']
    if current.get('valid') is not True or len(current.get('objects', [])) > 512:
        raise SampleError('snapshot_unsupported')
    return {'state_ref': refs.ref('state', scope, current['game_state_id']),
        'players': [{'seat': p['seat'], 'life': p['life']} for p in current['players']],
        'objects': [{'object_ref': refs.ref('object', scope, obj['id']), 'card_id': obj['card_id'],
            'zone': obj['zone'] if obj['zone'] in ZONES else None,
            'owner': obj['owner'], 'controller': obj['controller'], 'tapped': obj['tapped']}
            for obj in current['objects']],
        'turn': {k: current['turn'][k] for k in ('turnNumber', 'activePlayer', 'decisionPlayer')}}


def _action(row, refs, scope):
    _need(type(row) is dict, 'request_unsupported')
    kind = row.get('actionType')
    if kind == 'ActionType_Pass':
        _need(set(row) == {'actionType'}, 'request_unsupported')
    elif kind == 'ActionType_Play':
        _need(set(row) == {'actionType', 'instanceId', 'grpId', 'facetId', 'shouldStop'}, 'request_unsupported')
    else:
        _need(kind in COMPLEX and not set(row) - {'actionType', *IDS, *BOOLS, *PARAMS}, 'request_unsupported')
        required = {'instanceId', 'grpId', 'facetId'}
        if kind != 'ActionType_Cast':
            required.update(('abilityGrpId', 'uniqueAbilityId'))
        _need(required <= row.keys(), 'request_unsupported')
    for key in set(row) & set(IDS):
        _need(_id(row[key]), 'request_unsupported')
    for key in set(row) & set(BOOLS):
        _need(type(row[key]) is bool, 'request_unsupported')
    for key in set(row) & set(PARAMS):
        _need(row[key] == ({'autoTapActions': []} if key == 'autoTapSolution' else []) and
              type(row[key]) is (dict if key == 'autoTapSolution' else list), 'request_unsupported')
    return {'action_type': kind,
        # These are namespace-specific aliases, NOT raw GRE identifiers.
        'identifier_refs': {k: refs.ref('object' if k == 'instanceId' else k, scope, row[k])
                            for k in IDS if k in row},
        'flags': {k: row[k] for k in BOOLS if k in row},
        'observed_empty_parameters': [k for k in PARAMS if k in row]}


def _request(message, request, refs, scope, version=1, snapshot=None, visible_literals=None, search_zone=None):
    if version in (8, 9):
        from . import semantic_search as search
        if message.get('type') == search.REQUEST:
            value = search.project_request(message, visible_literals, scope[3], refs, scope, search_zone)
            search.check_request(value, snapshot['objects'], scope[3])
            return {'kind': search.KIND, 'payload': value}
        return _request(message, request, refs, scope, 7, snapshot, visible_literals)
    if version == 7:
        from . import semantic_effect_cost as effect_cost
        if message.get('type') == effect_cost.REQUEST:
            value = effect_cost.project_request(message, visible_literals, scope[3], refs, scope)
            effect_cost.check_request(value, snapshot['objects'], scope[3])
            return {'kind': effect_cost.KIND, 'payload': value}
        return _request(message, request, refs, scope, 6, snapshot)
    if version == 6:
        from .semantic_hand import project_request
        projected = project_request(message, refs, scope, snapshot)
        return projected if projected is not None else _request(message, request, refs, scope, 4, snapshot)
    kind = KINDS.get(request['type'])
    if version == 5:
        from .semantic_activate import PROFILE, alias_rows
        from .semantic_cast import RequestManaRefs
        evidence = request.get('_request_parameters')
        _need(kind == 'actions_available' and type(evidence) is dict and
              evidence.get('profile') == PROFILE, 'request_unsupported')
        return {'kind': kind, 'payload': {'profile': PROFILE,
            'rows': alias_rows(evidence['rows'], RequestManaRefs(refs, request), scope)}}
    if version >= 3 and kind in ('declare_attackers','declare_blockers'):
        from .semantic_combat import request as combat_request
        try:
            return combat_request(message,request,refs,scope,snapshot)
        except SampleError:
            raise SampleError('request_unsupported') from None
    if version == 4 and kind == 'select_targets':
        from .semantic_targets import project_request
        return {'kind': kind, 'payload': project_request(message, snapshot['objects'], scope[3], refs, scope)}
    if kind == 'select_n':
        _need(request.get('supported') is True, 'request_unsupported')
        selection = request['selection']
        return {'kind': kind, 'payload': {
            'offered_object_refs': [refs.ref('object', scope, c['instance_id']) for c in request['candidates']],
            'source_object_ref': refs.ref('object', scope, selection['source_id']),
            'max_sel': selection['max_sel'], 'min_sel': None,
            **{k: selection[k] for k in ('id_type', 'list_type', 'context', 'option_context')},
            'validation_type': 'SelectionValidationType_NonRepeatable',
            'allow_cancel': False, 'min_weight': selection['min_weight'], 'max_weight': selection['max_weight']}}
    _need(kind == 'actions_available' and not set(message) - {
        'type', 'systemSeatIds', 'msgId', 'gameStateId', 'actionsAvailableReq', *(['prompt'] if version >= 2 else [])}, 'request_unsupported')
    payload = message.get('actionsAvailableReq')
    _need(type(payload) is dict and not set(payload) - {'actions', 'inactiveActions'}, 'request_unsupported')
    rows = payload.get('actions')
    _need(type(rows) is list and len(rows) <= 256, 'request_unsupported')
    # Whole inventory or nothing; never drop bad rows or opaque parameters.
    try:
        if version >= 2:
            from .semantic_cast import action, RequestManaRefs
            refs = RequestManaRefs(refs, request)
            if version == 4:
                from .semantic_targets import action
        else:
            action = _action
        projected = [action(row, refs, scope) for row in rows]
        if version == 4:
            public = {o['object_ref'] for o in snapshot['objects'] if o['zone'] == 'ZoneType_Battlefield'}
            for row in projected:
                for slot in row['parameters'].get('targets', []):
                    _need(all(t['targetInstanceId'] in public for t in slot['targets']), 'request_unsupported')
        return {'kind': kind, 'payload': {'actions': projected}}
    except SampleError:
        raise SampleError('request_unsupported') from None


def _response(payload, request, refs, scope, version=1):
    if version in (8, 9):
        return _response(payload, request, refs, scope, 7)
    if version == 7:
        from . import semantic_effect_cost as effect_cost
        if request['type'] == effect_cost.REQUEST:
            return effect_cost.project_response(payload, request, refs, scope)
        return _response(payload, request, refs, scope, 6)
    if version == 6:
        return _response(payload, request, refs, scope, 4)
    if version >= 3 and request['type'] in ('GREMessageType_DeclareAttackersReq','GREMessageType_DeclareBlockersReq'):
        from .semantic_combat import response as combat_response
        try:
            return combat_response(payload,request)
        except SampleError:
            raise SampleError('response_unsupported') from None
    if request['type'] == 'GREMessageType_SelectNReq':
        validation = _selectn_known_constraints(request, payload)
        _need(validation['validation_level'] != 'violated_known_constraints', 'known_constraints_violated')
        _need(validation['validation_level'] == 'verified_known_constraints', 'response_unsupported')
        return {'kind': 'select_n', 'payload': {'selected_object_refs': [
            refs.ref('object', scope, i) for i in payload['selectNResp']['ids']]}}
    _need(set(payload) == {'type', 'respId', 'gameStateId', 'performActionResp'}, 'response_unsupported')
    body = payload['performActionResp']
    _need(type(body) is dict and set(body) in ([{'actions'}, {'actions','autoPassPriority'}] if version >= 2 else [{'actions'}]) and type(body['actions']) is list and
          len(body['actions']) == 1, 'response_unsupported')
    try:
        if version >= 2:
            from .semantic_cast import action as project_action, RequestManaRefs
            refs = RequestManaRefs(refs, request)
            if version == 4:
                from .semantic_targets import action as project_action
            elif version == 5:
                from .semantic_activate import action as project_action
        else:
            project_action = _action
        action = project_action(body['actions'][0], refs, scope)
        if 'autoPassPriority' in body:
            _need(body['autoPassPriority'] == 'AutoPassPriority_Yes', 'response_unsupported')
    except SampleError:
        raise SampleError('response_unsupported') from None
    return {'kind': 'actions_available', 'payload': {'action': action, **(
        {'auto_pass_priority': body['autoPassPriority']} if 'autoPassPriority' in body else {})}}


def _scope(reducer):
    return (reducer.generation, reducer.match, reducer.game, reducer.seat)


def _metadata(stat):
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


def collect_samples(path, *, origin='unclassified_local', max_samples=16,
                    max_history_bytes=64 * 1024 * 1024, schema_version=1):
    """One bounded offline read; all records are framed before values publish.

    Source consistency is metadata/boundary consistency, not a byte fingerprint.
    At most max_samples pairs are retained; omissions are explicit counts.
    """
    _need(type(schema_version) is int and schema_version in (1, 2, 3, 4, 5, 6, 7, 8, 9) and origin in ORIGINS and type(max_samples) is int and 1 <= max_samples <= 256 and
          type(max_history_bytes) is int and 1 <= max_history_bytes <= 1024**3, 'invalid_export_bounds')
    path = Path(path)
    before_stat = path.stat()
    follower = RawFollower(path, max_history_bytes)
    _, records = follower.poll()
    after_stat = path.stat()
    _need(_metadata(before_stat) == _metadata(after_stat) and follower.offset == before_stat.st_size and
          follower.identity == ((before_stat.st_dev, before_stat.st_ino) if before_stat.st_ino else
                                (before_stat.st_ctime_ns,)), 'source_changed')
    _need(follower.framer.errors == 0 and not follower.framer.partial, 'source_framing_incomplete')
    refs, samples, counts, rejected = _Refs(), [], Counter(), Counter()
    active, pending, tracing = None, None, None
    reducer = None
    if schema_version >= 2:
        from . import semantic_cast as cast
    if schema_version in (6, 7, 8, 9):
        from . import semantic_hand as hand
    if schema_version in (7, 8, 9):
        from . import semantic_effect_cost as effect_cost
    if schema_version in (8, 9):
        from . import semantic_search as search
    if schema_version == 9:
        from . import semantic_effect_cost_result as cost_result

    def end_trace(status, request_ref=None):
        nonlocal tracing
        if tracing is not None:
            tracing['trace']['status'] = status
            tracing['trace']['truncated'] = status == 'limit_reached'
            tracing['trace']['next_request_ref'] = request_ref
            tracing = None

    def finish(status, snapshot=None, request_kind=None, request_ref=None):
        nonlocal pending
        if pending is not None:
            pending['successor'] = {'status': status, 'snapshot': snapshot,
                                    'request_kind': request_kind, 'request_ref': request_ref}
            pending = None

    def observe(event, details):
        nonlocal active
        if event == 'continuity_error':
            active = None
            finish('interrupted')
            end_trace('interrupted')
        elif event == 'state_accepted':
            active = None
            if tracing is not None and details['kind'] != 'full_retransmit':
                if _scope(reducer) != tracing['_scope']:
                    end_trace('interrupted')
                elif details['kind'] != 'diff':
                    end_trace('full_baseline_not_continuous')
                elif len(tracing['trace']['states']) >= cast.TRACE_LIMIT:
                    end_trace('limit_reached')
                else:
                    try:
                        snap = _snapshot(reducer, refs, _scope(reducer))
                        previous = (tracing['trace']['states'][-1]['snapshot'] if tracing['trace']['states'] else tracing['before'])
                        gs = details['message']
                        if schema_version == 5:
                            from .semantic_activate import facts as activate_facts
                            prior_facts = [f for s in tracing['trace']['states'] for f in s['facts']]
                            fact_rows, fact_status, omitted = activate_facts(gs, reducer, refs, _scope(reducer),
                                previous, snap, tracing['response']['payload']['action'], prior_facts)
                        elif schema_version in (8, 9) and search.is_search(tracing['request']):
                            fact_rows, fact_status, omitted = search.facts(gs, reducer, refs, _scope(reducer),
                                previous, snap, tracing['request'], tracing['response'], tracing['_search'])
                        elif schema_version == 9 and effect_cost.is_effect_cost(tracing['request']):
                            fact_rows, fact_status, omitted = cost_result.facts(gs, reducer, refs, _scope(reducer),
                                previous, snap, tracing['response'], tracing['_cost_selected_raw'], tracing['identity']['self_seat'])
                        elif schema_version in (7, 8, 9) and effect_cost.is_effect_cost(tracing['request']):
                            # No annotation/payment interpretation; endpoint only.
                            fact_rows, fact_status, omitted = [], 'visible_snapshot_only', None
                        elif schema_version in (6, 7, 8, 9) and hand.is_hand(tracing['request']):
                            fact_rows, fact_status, omitted = hand.facts(gs, reducer, refs, _scope(reducer),
                                previous, snap, tracing['request'], tracing['response'], tracing['identity']['self_seat'])
                        elif tracing['request']['kind'] in ('declare_attackers','declare_blockers'):
                            from . import semantic_combat as combat
                            fact_rows,fact_status,omitted=combat.facts(gs,refs,_scope(reducer),snap)
                        elif tracing['request']['kind'] == 'select_targets':
                            from .semantic_targets import facts as target_facts
                            fact_rows, fact_status, omitted = target_facts(gs, reducer, refs, _scope(reducer),
                                previous, snap, tracing['request']['payload'])
                        else:
                            selected = tracing['response']['payload'].get('action', {})
                            related = ({selected['identifier_refs']['instanceId']} if 'instanceId' in selected.get('identifier_refs', {}) else set())
                            for tap in selected.get('parameters', {}).get('autoTapSolution', {}).get('autoTapActions', []):
                                related.add(tap['instanceId'])
                            for prior in tracing['trace']['states']:
                                related.update(f['new_object_ref'] for f in prior['facts'] if f['kind'] == 'object_id_changed')
                            fact_rows, fact_status, omitted = cast.facts(gs, reducer, refs, _scope(reducer), previous, snap, related)
                        tracing['trace']['states'].append({'snapshot': snap,
                            'previous_state_ref': refs.ref('state', _scope(reducer), gs['prevGameStateId']),
                            'facts': fact_rows, 'facts_status': fact_status, 'omitted_annotations': omitted})
                        if tracing['request']['kind'] in ('declare_attackers','declare_blockers'):
                            end_trace(combat.FIRST)
                        elif schema_version in (8, 9) and search.is_search(tracing['request']):
                            end_trace(search.FIRST)
                        elif schema_version in (7, 8, 9) and effect_cost.is_effect_cost(tracing['request']):
                            end_trace(effect_cost.FIRST)
                        elif schema_version in (6, 7, 8, 9) and hand.is_hand(tracing['request']):
                            end_trace(hand.FIRST)
                    except (SampleError, KeyError, TypeError):
                        end_trace('interrupted')
            if pending is not None:
                if _scope(reducer) != pending['_scope']:
                    finish('interrupted')
                elif details['kind'] != 'full_retransmit':
                    try:
                        snap = _snapshot(reducer, refs, _scope(reducer))
                    except SampleError:
                        finish('interrupted')
                    else:
                        finish('continuous_state_observed' if details['kind'] == 'diff' else
                               'full_baseline_not_continuous', snap)
        elif event == 'request_accepted':
            message, request = details['message'], details['request']
            if (_current_verified_raw_request(reducer, message) is None or
                    request.get('_continuity_verified') is not True):
                active = None
                return
            scope = _scope(reducer)
            if tracing is not None:
                end_trace('next_request_observed' if scope == tracing['_scope'] else 'interrupted',
                          refs.ref('request', scope, request['id']) if scope == tracing['_scope'] else None)
            if pending is not None:
                if scope != pending['_scope']:
                    finish('interrupted')
                else:
                    try:
                        snap = _snapshot(reducer, refs, scope)
                    except SampleError:
                        finish('interrupted')
                    else:
                        finish('next_request_observed', snap, KINDS.get(request['type'], 'unsupported'),
                               refs.ref('request', scope, request['id']))
            try:
                snap = _snapshot(reducer, refs, scope)
                visible_literals = ([{'object_ref': obj['id'], 'zone': obj['zone'],
                    'owner': obj['owner'], 'controller': obj['controller']}
                    for obj in reducer.document()['current']['objects']] if schema_version in (7, 8, 9) else None)
                search_zone = None
                if schema_version in (8, 9) and message.get('type') == search.REQUEST:
                    raw_search = message.get('searchReq')
                    zone_ids = raw_search.get('zonesToSearch') if type(raw_search) is dict else None
                    if type(zone_ids) is list and len(zone_ids) == 1 and _id(zone_ids[0]):
                        zone = reducer.zones.get(zone_ids[0], {})
                        # Requested-zone labels only; no library membership or
                        # hidden object properties cross this staging boundary.
                        search_zone = {'id': zone_ids[0], 'type': zone.get('type'),
                            'owner': zone.get('ownerSeatId'), 'visibility': zone.get('visibility')}
                projected = _request(message, request, refs, scope, schema_version, snap, visible_literals, search_zone)
            except SampleError as exc:
                active = {'identity': (request['id'], request['game_state_id']), 'reason': str(exc)}
            else:
                active = {'identity': (request['id'], request['game_state_id']), 'scope': scope,
                    'request_ref': refs.ref('request', scope, request['id']), 'before': snap, 'request': projected}
                if schema_version in (8, 9) and search.is_search(projected):
                    active['_search'] = search.private_context(message, refs, scope)

    reducer = RawReducer(observer=observe, include_state_messages=schema_version >= 2,
                         include_request_parameters=schema_version == 5)
    reducer.reset(follower.generation)
    for entry in records:
        before = copy.deepcopy(_current_verified_request(reducer))
        captured = active
        payload = entry.get('payload') if isinstance(entry, dict) else None
        reducer.apply(entry)
        # Room boundaries can revoke a baseline without a continuity callback.
        if pending is not None and (_scope(reducer) != pending['_scope'] or reducer.error is not None or
                reducer.room_state == 'MatchGameRoomStateType_MatchCompleted'):
            finish('interrupted')
        if tracing is not None and (_scope(reducer) != tracing['_scope'] or reducer.error is not None or
                reducer.room_state == 'MatchGameRoomStateType_MatchCompleted'):
            end_trace('interrupted')
        # The new default protocol pair must not change old sample counts,
        # aliases or unsupported/successor labels. KINDS stays legacy-scoped.
        if before is not None and before['type'] == 'GREMessageType_PayCostsReq' and schema_version not in (7, 8, 9):
            continue
        if not (_paired_response(reducer, before, payload) or
                schema_version in (8, 9) and before is not None and before['type'] == search.REQUEST and
                _paired_response(reducer, before, payload, expected_type=search.RESPONSE) or
                schema_version >= 3 and _paired_combat_submit(reducer,before,payload) or
                schema_version in (4, 6, 7, 8, 9) and _paired_terminal_submit(reducer,before,payload)):
            continue
        counts['matched_pairs'] += 1
        if any(key in entry for key in ('greToClientEvent', 'authenticateResponse',
                                        'matchGameRoomStateChangedEvent')):
            rejected['mixed_record_ordering'] += 1
            continue
        if len(samples) >= max_samples:
            counts['sample_limit_omissions'] += 1
            continue
        if captured is None or captured['identity'] != (before['id'], before['game_state_id']):
            rejected['source_pair_unavailable'] += 1
            continue
        if 'reason' in captured:
            rejected[captured['reason']] += 1
            continue
        try:
            if schema_version in (8, 9) and search.is_search(captured['request']):
                response = search.project_response(payload, captured['request'], captured['_search'])
            elif schema_version in (7, 8, 9) and effect_cost.is_effect_cost(captured['request']):
                response = effect_cost.project_response(payload, captured['request'], refs, captured['scope'])
                effect_cost.check_response(response, captured['request'], captured['before']['objects'], captured['scope'][3])
            elif schema_version in (6, 7, 8, 9) and hand.is_hand(captured['request']):
                response = hand.project_response(payload, captured['request'], refs, captured['scope'])
            elif schema_version in (4, 6, 7, 8, 9) and captured['request']['kind'] == 'select_targets':
                from .semantic_targets import response as target_response
                response = target_response(payload, before, captured['request']['payload'], refs, captured['scope'])
            else:
                response = _response(payload, before, refs, captured['scope'], schema_version)
            if schema_version == 5:
                _need(response['payload']['action']['action_type'] == 'ActionType_Activate' and
                          sum(r['literal_action'] == response['payload']['action']
                          for r in captured['request']['payload']['rows']) == 1, 'response_unsupported')
        except SampleError as exc:
            rejected[str(exc)] += 1
            continue
        scope = captured['scope']
        episode = {'identity': {'match_ref': refs.ref('match', (), scope[1]), 'game': scope[2],
            'self_seat': scope[3], 'request_ref': captured['request_ref']},
            'before': captured['before'], 'request': captured['request'], 'response': response,
            'successor': {'status': 'not_observed', 'snapshot': None, 'request_kind': None, 'request_ref': None},
            'provenance': {'exact_source_pair_verified_by_producer': True,
                'private_auth_revalidated_by_replay': False, 'client_submission_only': True}, '_scope': scope}
        if schema_version in (8, 9) and search.is_search(captured['request']):
            episode['_search'] = captured['_search']
        if schema_version == 9 and effect_cost.is_effect_cost(captured['request']):
            episode['_cost_selected_raw'] = payload['effectCostResp']['costSelection']['ids'][0]
        finish('interrupted')
        end_trace('interrupted')
        if schema_version >= 2:
            episode['trace'] = {'status': 'not_observed', 'truncated': False, 'next_request_ref': None, 'states': []}
            tracing = episode
        samples.append(episode)
        pending = episode
    end_trace('eof')
    for sample in samples:
        sample.pop('_scope')
        sample.pop('_search', None)
        sample.pop('_cost_selected_raw', None)
    if schema_version >= 3:
        from . import semantic_combat as combat
    if schema_version == 4:
        from . import semantic_targets as targets
    if schema_version == 5:
        from . import semantic_activate as activate
    result = {'schema_version': VERSION if schema_version == 1 else cast.VERSION if schema_version == 2 else combat.VERSION if schema_version == 3 else targets.VERSION if schema_version == 4 else activate.VERSION if schema_version == 5 else hand.VERSION if schema_version == 6 else effect_cost.VERSION if schema_version == 7 else search.VERSION if schema_version == 8 else cost_result.VERSION,
        'projection': copy.deepcopy(PROJECTION if schema_version == 1 else cast.PROJECTION_V2 if schema_version == 2 else combat.PROJECTION_V3 if schema_version == 3 else targets.projection() if schema_version == 4 else activate.projection() if schema_version == 5 else hand.projection() if schema_version == 6 else effect_cost.projection() if schema_version == 7 else search.projection() if schema_version == 8 else cost_result.projection()),
        'source': {'format': 'player-log-gre-v1',
        'mode': 'offline', 'origin': origin, 'origin_is_user_supplied': True,
        'framing_complete': True, 'framed_records': len(records),
        'raw_gre_replay': False, 'source_auth_revalidated_by_portable_replay': False},
        'counts': {'matched_pairs': counts['matched_pairs'], 'exported': len(samples),
            'sample_limit_omissions': counts['sample_limit_omissions'],
            'unsupported_pairs': sum(rejected.values())},
        'unsupported_reasons': [{'reason': name, 'count': rejected[name]} for name in REASONS if rejected[name]],
        'samples': samples, 'read_only': True, 'execution': dict(EXECUTION)}
    _need(len(json.dumps(result, ensure_ascii=False, allow_nan=False).encode('utf-8')) <= MAX_BYTES,
          'semantic_sample_output_limit')
    replay_samples(result)
    return result


def export_samples(path, output, **options):
    """Publish a NEW file only. No replacement, even if destination races."""
    output = Path(output)
    _need(not output.exists(), 'output_already_exists')
    result = collect_samples(path, **options)
    descriptor, temporary = tempfile.mkstemp(prefix='.semantic-sample-', dir=output.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            json.dump(result, stream, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
            stream.write('\n')
        os.link(temporary, output)  # Atomic, create-if-absent on Linux and NTFS.
    finally:
        Path(temporary).unlink(missing_ok=True)
    return result


def _check_snapshot(value):
    _keys(value, ('state_ref', 'players', 'objects', 'turn'))
    _need(_id(value['state_ref']) and value['state_ref'] > 0)
    _need(type(value['objects']) is list and len(value['objects']) <= 512)
    seen = set()
    for row in value['objects']:
        _keys(row, ('object_ref', 'card_id', 'zone', 'owner', 'controller', 'tapped'))
        _need(_id(row['object_ref']) and row['object_ref'] > 0 and row['object_ref'] not in seen)
        seen.add(row['object_ref'])
        _need(row['card_id'] is None or _id(row['card_id']))
        _need(row['zone'] in (None, *ZONES))
        _need(all(row[k] is None or type(row[k]) is int and row[k] in (1, 2) for k in ('owner', 'controller')))
        _need(row['tapped'] is None or type(row['tapped']) is bool)
    _need(type(value['players']) is list and len(value['players']) <= 2)
    seats = set()
    for row in value['players']:
        _keys(row, ('seat', 'life'))
        _need(type(row['seat']) is int and row['seat'] in (1, 2) and row['seat'] not in seats)
        seats.add(row['seat'])
        _need(row['life'] is None or type(row['life']) is int and abs(row['life']) <= 2**31-1)
    _keys(value['turn'], ('turnNumber', 'activePlayer', 'decisionPlayer'))
    for item in value['turn'].values():
        _need(item is None or _id(item))


def _check_action(row):
    _keys(row, ('action_type', 'identifier_refs', 'flags', 'observed_empty_parameters'))
    ids, flags, params = row['identifier_refs'], row['flags'], row['observed_empty_parameters']
    _need(type(ids) is dict and not set(ids)-set(IDS) and all(_id(i) and i > 0 for i in ids.values()))
    _need(type(flags) is dict and not set(flags)-set(BOOLS) and all(type(v) is bool for v in flags.values()))
    _need(type(params) is list and len(params) <= len(PARAMS) and len(set(params)) == len(params) and
          all(type(k) is str and k in PARAMS for k in params))
    kind = row['action_type']
    if kind == 'ActionType_Pass':
        _need(not ids and not flags and not params)
    elif kind == 'ActionType_Play':
        _need(set(ids) == {'instanceId', 'grpId', 'facetId'} and set(flags) == {'shouldStop'} and not params)
    else:
        required = {'instanceId', 'grpId', 'facetId'}
        if kind != 'ActionType_Cast': required.update(('abilityGrpId', 'uniqueAbilityId'))
        _need(kind in COMPLEX and required <= ids.keys())


def _unique_action_position(actions, chosen):
    matches = [i for i, row in enumerate(actions) if row['action_type'] == chosen['action_type'] and
               (row == chosen if row['action_type'] not in COMPLEX else
                row['identifier_refs'] == chosen['identifier_refs'])]
    return matches[0] if len(matches) == 1 else None


def _check_envelope(document, version, projection):
    _keys(document, ('schema_version', 'projection', 'source', 'counts', 'unsupported_reasons', 'samples', 'read_only', 'execution'))
    _need(document['schema_version'] == version and document['read_only'] is True and
          document['execution'] == EXECUTION and all(type(v) is bool for v in document['execution'].values()))
    _need(document['projection'] == projection and document['projection']['raw_equivalent'] is False)
    source = document['source']
    _keys(source, ('format', 'mode', 'origin', 'origin_is_user_supplied', 'framing_complete', 'framed_records',
                   'raw_gre_replay', 'source_auth_revalidated_by_portable_replay'))
    _need(source['format'] == 'player-log-gre-v1' and source['mode'] == 'offline' and source['origin'] in ORIGINS and
          source['origin_is_user_supplied'] is True and source['framing_complete'] is True and
          _id(source['framed_records']) and source['raw_gre_replay'] is False and
          source['source_auth_revalidated_by_portable_replay'] is False)
    counts = document['counts']
    _keys(counts, ('matched_pairs', 'exported', 'sample_limit_omissions', 'unsupported_pairs'))
    _need(all(_id(v) for v in counts.values()) and counts['matched_pairs'] ==
          counts['exported'] + counts['sample_limit_omissions'] + counts['unsupported_pairs'])
    _need(type(document['unsupported_reasons']) is list and len(document['unsupported_reasons']) <= len(REASONS))
    reasons = set(); total = 0
    for row in document['unsupported_reasons']:
        _keys(row, ('reason', 'count'))
        _need(row['reason'] in REASONS and row['reason'] not in reasons and _id(row['count']) and row['count'] > 0)
        reasons.add(row['reason']); total += row['count']
    _need(total == counts['unsupported_pairs'])
    _need(type(document['samples']) is list and len(document['samples']) == counts['exported'] <= 256)


def _check_episode_base(sample, extras=()):
    _keys(sample, ('identity', 'before', 'request', 'response', 'successor', 'provenance', *extras))
    _keys(sample['identity'], ('match_ref', 'game', 'self_seat', 'request_ref'))
    _need(all(_id(v) and v > 0 for v in sample['identity'].values()) and sample['identity']['self_seat'] in (1,2))
    _check_snapshot(sample['before'])
    _need(sample['provenance'] == {'exact_source_pair_verified_by_producer': True,
          'private_auth_revalidated_by_replay': False, 'client_submission_only': True} and
          all(type(v) is bool for v in sample['provenance'].values()))


def _check_successor(successor, before):
    _keys(successor, ('status', 'snapshot', 'request_kind', 'request_ref'))
    _need(successor['status'] in SUCCESSORS)
    if successor['status'] in ('not_observed', 'interrupted'):
        _need(all(successor[k] is None for k in ('snapshot','request_kind','request_ref')))
    else:
        _check_snapshot(successor['snapshot'])
        if successor['status'] == 'next_request_observed':
            _need(successor['request_kind'] in (*KINDS.values(),'unsupported') and
                  _id(successor['request_ref']) and successor['request_ref'] > 0)
        else:
            _need(successor['request_kind'] is None and successor['request_ref'] is None)
        if successor['status'] == 'continuous_state_observed':
            _need(successor['snapshot']['state_ref'] != before['state_ref'])


def _replay_samples(document):
    """Validate/replay exported choices, NOT private GRE authentication/effects."""
    if type(document) is dict and document.get('schema_version') == 'mtgaplayer.semantic-samples.v9':
        from .semantic_effect_cost_result import replay
        return replay(document)
    if type(document) is dict and document.get('schema_version') == 'mtgaplayer.semantic-samples.v8':
        from .semantic_search import replay
        return replay(document)
    if type(document) is dict and document.get('schema_version') == 'mtgaplayer.semantic-samples.v7':
        from .semantic_effect_cost import replay
        return replay(document)
    if type(document) is dict and document.get('schema_version') == 'mtgaplayer.semantic-samples.v6':
        from .semantic_hand import replay
        return replay(document)
    if type(document) is dict and document.get('schema_version') == 'mtgaplayer.semantic-samples.v5':
        from .semantic_activate import replay
        return replay(document)
    if type(document) is dict and document.get('schema_version') == 'mtgaplayer.semantic-samples.v4':
        from .semantic_targets import replay
        return replay(document)
    if type(document) is dict and document.get('schema_version') == 'mtgaplayer.semantic-samples.v3':
        from .semantic_combat import replay
        return replay(document)
    if type(document) is dict and document.get('schema_version') == 'mtgaplayer.semantic-samples.v2':
        from .semantic_cast import replay
        return replay(document)
    _check_envelope(document, VERSION, PROJECTION)
    reports = []
    for index, sample in enumerate(document['samples']):
        _check_episode_base(sample)
        request, response = sample['request'], sample['response']
        _keys(request, ('kind', 'payload')); _keys(response, ('kind', 'payload'))
        _need(request['kind'] == response['kind'] and request['kind'] in ('select_n', 'actions_available'))
        chosen_positions, action_position = None, None
        if request['kind'] == 'select_n':
            req, resp = request['payload'], response['payload']
            _keys(req, ('offered_object_refs', 'source_object_ref', 'max_sel', 'min_sel', 'validation_type',
                        'allow_cancel', 'min_weight', 'max_weight', 'id_type', 'list_type', 'context', 'option_context'))
            _keys(resp, ('selected_object_refs',))
            offered, chosen = req['offered_object_refs'], resp['selected_object_refs']
            _need(type(offered) is list and 1 <= len(offered) <= 256 and all(_id(i) and i > 0 for i in offered) and
                  len(set(offered)) == len(offered) and _id(req['source_object_ref']) and req['source_object_ref'] > 0)
            _need(type(req['max_sel']) is int and 1 <= req['max_sel'] <= len(offered) and req['min_sel'] is None and
                  req['id_type'] == 'IdType_InstanceId' and req['list_type'] == 'SelectionListType_Dynamic' and
                  req['context'] == 'SelectionContext_Resolution' and req['option_context'] == 'OptionContext_Resolution' and
                  req['validation_type'] == 'SelectionValidationType_NonRepeatable' and req['allow_cancel'] is False and
                  type(req['min_weight']) is int and req['min_weight'] == -2147483648 and
                  type(req['max_weight']) is int and req['max_weight'] == 2147483647)
            _need(type(chosen) is list and len(chosen) <= req['max_sel'] and all(_id(i) and i in offered for i in chosen) and
                  len(set(chosen)) == len(chosen))
            chosen_positions = [offered.index(i) for i in chosen]
        else:
            _keys(request['payload'], ('actions',)); _keys(response['payload'], ('action',))
            actions, chosen = request['payload']['actions'], response['payload']['action']
            _need(type(actions) is list and len(actions) <= 256)
            for row in actions: _check_action(row)
            _check_action(chosen)
            action_position = _unique_action_position(actions, chosen)
        successor = sample['successor']
        _check_successor(successor, sample['before'])
        reports.append({'sample_index': index, 'request_kind': request['kind'],
            'selected_option_positions': chosen_positions, 'selected_action_position': action_position,
            'validation_scope': 'known_select_n_constraints_only' if chosen_positions is not None else
                                'action_identity_correlation_only', 'successor_status': successor['status']})
    return {'schema_version': 'mtgaplayer.semantic-sample-replay.v1', 'samples': reports,
        'artifact_checks_passed': True, 'raw_source_auth_revalidated': False,
        'complete_legality_verified': False, 'server_acceptance_verified': False,
        'read_only': True, 'execution': dict(EXECUTION)}


def replay_samples(document):
    try:
        _need(len(json.dumps(document, allow_nan=False).encode('utf-8')) <= MAX_BYTES,
              'semantic_sample_output_limit')
        return _replay_samples(document)
    except SampleError:
        raise
    except (ValueError, TypeError, KeyError, RecursionError, UnicodeError):
        raise SampleError('invalid_semantic_sample') from None


def load_and_replay(path):
    with Path(path).open('rb') as stream:
        data = stream.read(MAX_BYTES + 1)
    _need(len(data) <= MAX_BYTES, 'semantic_sample_output_limit')
    def pairs(rows):
        result = {}
        for key, value in rows:
            _need(key not in result)
            result[key] = value
        return result
    try:
        document = json.loads(data, object_pairs_hook=pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(SampleError('invalid_semantic_sample')))
        return replay_samples(document)
    except (ValueError, TypeError, KeyError, RecursionError, UnicodeError):
        raise SampleError('invalid_semantic_sample') from None
