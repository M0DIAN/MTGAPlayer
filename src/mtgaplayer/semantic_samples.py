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
from .response_evidence import _current_verified_request, _current_verified_raw_request, _paired_response
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


def _request(message, request, refs, scope):
    kind = KINDS.get(request['type'])
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
        'type', 'systemSeatIds', 'msgId', 'gameStateId', 'actionsAvailableReq'}, 'request_unsupported')
    payload = message.get('actionsAvailableReq')
    _need(type(payload) is dict and not set(payload) - {'actions', 'inactiveActions'}, 'request_unsupported')
    rows = payload.get('actions')
    _need(type(rows) is list and len(rows) <= 256, 'request_unsupported')
    # Whole inventory or nothing; never drop bad rows or opaque parameters.
    return {'kind': kind, 'payload': {'actions': [_action(row, refs, scope) for row in rows]}}


def _response(payload, request, refs, scope):
    if request['type'] == 'GREMessageType_SelectNReq':
        validation = _selectn_known_constraints(request, payload)
        _need(validation['validation_level'] != 'violated_known_constraints', 'known_constraints_violated')
        _need(validation['validation_level'] == 'verified_known_constraints', 'response_unsupported')
        return {'kind': 'select_n', 'payload': {'selected_object_refs': [
            refs.ref('object', scope, i) for i in payload['selectNResp']['ids']]}}
    _need(set(payload) == {'type', 'respId', 'gameStateId', 'performActionResp'}, 'response_unsupported')
    body = payload['performActionResp']
    _need(type(body) is dict and set(body) == {'actions'} and type(body['actions']) is list and
          len(body['actions']) == 1, 'response_unsupported')
    try:
        action = _action(body['actions'][0], refs, scope)
    except SampleError:
        raise SampleError('response_unsupported') from None
    return {'kind': 'actions_available', 'payload': {'action': action}}


def _scope(reducer):
    return (reducer.generation, reducer.match, reducer.game, reducer.seat)


def _metadata(stat):
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


def collect_samples(path, *, origin='unclassified_local', max_samples=16,
                    max_history_bytes=64 * 1024 * 1024):
    """One bounded offline read; all records are framed before values publish.

    Source consistency is metadata/boundary consistency, not a byte fingerprint.
    At most max_samples pairs are retained; omissions are explicit counts.
    """
    _need(origin in ORIGINS and type(max_samples) is int and 1 <= max_samples <= 256 and
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
    active, pending = None, None
    reducer = None

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
        elif event == 'state_accepted':
            active = None
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
                projected = _request(message, request, refs, scope)
            except SampleError as exc:
                active = {'identity': (request['id'], request['game_state_id']), 'reason': str(exc)}
            else:
                active = {'identity': (request['id'], request['game_state_id']), 'scope': scope,
                    'request_ref': refs.ref('request', scope, request['id']), 'before': snap, 'request': projected}

    reducer = RawReducer(observer=observe)
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
        if not _paired_response(reducer, before, payload):
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
            response = _response(payload, before, refs, captured['scope'])
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
        finish('interrupted')
        samples.append(episode)
        pending = episode
    for sample in samples:
        sample.pop('_scope')
    result = {'schema_version': VERSION, 'projection': copy.deepcopy(PROJECTION),
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


def _replay_samples(document):
    """Validate/replay exported choices, NOT private GRE authentication/effects."""
    _keys(document, ('schema_version', 'projection', 'source', 'counts', 'unsupported_reasons', 'samples', 'read_only', 'execution'))
    _need(document['schema_version'] == VERSION and document['read_only'] is True and
          document['execution'] == EXECUTION and all(type(v) is bool for v in document['execution'].values()))
    _need(document['projection'] == PROJECTION and document['projection']['raw_equivalent'] is False)
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
    reports = []
    for index, sample in enumerate(document['samples']):
        _keys(sample, ('identity', 'before', 'request', 'response', 'successor', 'provenance'))
        _keys(sample['identity'], ('match_ref', 'game', 'self_seat', 'request_ref'))
        _need(all(_id(v) and v > 0 for v in sample['identity'].values()) and sample['identity']['self_seat'] in (1,2))
        _check_snapshot(sample['before'])
        _need(sample['provenance'] == {'exact_source_pair_verified_by_producer': True,
              'private_auth_revalidated_by_replay': False, 'client_submission_only': True} and
              all(type(v) is bool for v in sample['provenance'].values()))
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
                _need(successor['snapshot']['state_ref'] != sample['before']['state_ref'])
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
