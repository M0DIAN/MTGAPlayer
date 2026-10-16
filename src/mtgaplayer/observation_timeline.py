"""Offline protocol evidence and marker candidates, never marker causality.

Consumes the existing local collector wrapper. RawReducer and the established
response/choice gates remain the only protocol and action interpreters. Source
log timestamps are not used as capture clocks or network-delay measurements.
"""
import copy
import hashlib
import json
from pathlib import Path
import tempfile

from .raw_log import RawFollower, RawReducer
from .response_evidence import (_current_verified_request, _current_verified_raw_request,
    _paired_response, _paired_combat_submit, _paired_terminal_submit)
from .semantic_evidence import _complex_classify
from . import semantic_samples as samples


SCHEMA = 'mtgaplayer.observation-timeline.v1'
MARKER_ACTIONS = {'play_land': 'ActionType_Play', 'cast_targeted': 'ActionType_Cast',
    'cast_no_target': 'ActionType_Cast', 'activate': 'ActionType_Activate',
    'pass_priority': 'ActionType_Pass', 'declare_attackers': 'declare_attackers',
    'declare_blockers': 'declare_blockers'}
PHASES = {'Phase_Beginning', 'Phase_Main1', 'Phase_Combat', 'Phase_Main2', 'Phase_Ending'}
STEPS = {'Step_Untap', 'Step_Upkeep', 'Step_Draw', 'Step_BeginCombat', 'Step_DeclareAttack',
    'Step_DeclareBlock', 'Step_FirstStrikeDamage', 'Step_CombatDamage', 'Step_EndCombat',
    'Step_End', 'Step_Cleanup', 'Step_None'}
CLASSES = ('protocol_supported_unique', 'multiple_candidates', 'temporal_only', 'unreliable')
MARKER_TYPES = set(MARKER_ACTIONS) | {'observe_resolution'}


def _ns(clock):
    value = clock.get('monotonic_ns') if isinstance(clock, dict) else None
    return value if type(value) is int and value >= 0 else None


def _context(reducer):
    turn = reducer.turn
    priority = turn.get('priorityPlayer')
    return {'phase': turn.get('phase') if turn.get('phase') in PHASES else None,
        'step': turn.get('step') if turn.get('step') in STEPS else None,
        'turn_number': turn.get('turnNumber'),
        'own_priority_player': priority == reducer.seat if type(priority) is int and priority in (1,2) else None}


def _ref(row, message=None, state=False):
    index = None
    if message is not None:
        gre = row['entry'].get('greToClientEvent', {})
        for position, item in enumerate(gre.get('greToClientMessages', [])):
            if isinstance(item, dict) and (item.get('gameStateMessage') is message if state else item is message):
                index = position
                break
    return {'file': 'raw_records.jsonl', 'record_id': row['record_id'],
            'poll_id': row['poll_id'], 'generation': row['source']['generation'],
            'gre_message_index': index}


def _polls(journal, null_polls):
    result, previous, previous_id, first_generation = [], None, None, set()
    for row in journal:
        if row.get('event') != 'poll_complete':
            continue
        acquired = _ns(row.get('log_acquired'))
        finish = acquired if acquired is not None else _ns(row.get('poll_completed'))
        begin = previous if previous is not None else _ns(row.get('poll_started'))
        generation = row.get('source', {}).get('generation')
        history = row.get('reset') is True
        reset_after_startup = history and bool(first_generation)
        if generation is not None:
            first_generation.add(generation)
        reasons = []
        ident = row.get('poll_id')
        if type(ident) is not int or ident < 1:
            raise ValueError('invalid_completed_poll_id')
        if previous_id is not None and ident != previous_id + 1 or previous_id is None and ident != 1:
            reasons.append('missing_or_unordered_poll_journal_interval')
        if begin is None or finish is None or begin > finish:
            reasons.append('poll_clock_missing_or_reversed')
        if row.get('partial_record') is not False:
            reasons.append('partial_or_unknown_source_tail')
        if row.get('framing_errors') != 0:
            reasons.append('framing_errors_or_unknown_integrity')
        if row.get('log_error') is not None:
            reasons.append('log_read_failed')
        if row.get('reducer_error') is not None:
            reasons.append('reducer_state_unreliable')
        if row.get('poll_id') in null_polls:
            reasons.append('malformed_raw_record')
        if reset_after_startup:
            reasons.append('source_reset_after_startup')
        result.append({'poll_id': row.get('poll_id'), 'begin': begin, 'end': finish,
            'generation': generation, 'history': history, 'reasons': reasons})
        if acquired is not None:
            previous = acquired
        previous_id = ident
    return result


def _overlap(poll, begin, end):
    return poll['begin'] is not None and poll['end'] is not None and poll['begin'] <= end and poll['end'] >= begin


def _marker_groups(markers):
    groups, pending, seen = [], None, set()
    def add(before, after, reasons):
        present = before or after
        kind = present[1].get('event_type')
        if not isinstance(kind, str) or kind not in MARKER_TYPES:
            kind = None
            reasons = [*reasons, 'unsupported_marker_type']
        groups.append({'marker_group': len(groups) + 1, 'marker_type': kind,
            'marker_line_before': before[0] if before else None,
            'marker_line_after': after[0] if after else None,
            'begin': _ns(before[1]) if before else None, 'end': _ns(after[1]) if after else None,
            'reasons': reasons})
    for line, marker in enumerate(markers, 1):
        if not isinstance(marker, dict):
            add(None, (line, {}), ['malformed_marker'])
            continue
        ident = marker.get('event_id')
        if not isinstance(ident, str) or not ident:
            add(None, (line, marker), ['marker_event_id_missing_or_invalid'])
            continue
        duplicate = ident is not None and ident in seen
        if ident is not None:
            seen.add(ident)
        if duplicate:
            add(None, (line, marker), ['duplicate_marker_event'])
        elif marker.get('phase') == 'before':
            if pending is not None:
                add(pending, None, ['missing_after_marker'])
            pending = (line, marker)
        elif marker.get('phase') == 'after' and pending is not None and marker.get('event_type') == pending[1].get('event_type'):
            reasons = []
            begin, end = _ns(pending[1]), _ns(marker)
            if begin is None or end is None or begin > end:
                reasons.append('marker_clock_missing_or_reversed')
            add(pending, (line, marker), reasons)
            pending = None
        else:
            add(None, (line, marker), ['missing_or_incompatible_before_marker'])
    if pending is not None:
        add(pending, None, ['missing_after_marker'])
    return groups


def _attach_semantic_export(pairs, records, semantic_source, work_directory):
    """Reuse the reviewed exporter/trace; authenticate its exact input values.

    Supported pairs are enumerated using the exporter's own request/response
    projection helpers. Their order can be joined only when all source values,
    gate counts and supported sample counts agree; otherwise withhold the join.
    """
    if semantic_source is None:
        return {'status': 'not_run', 'reason': 'stable_original_source_not_supplied'}
    if len({row['source']['generation'] for row in records}) != 1:
        return {'status': 'withheld', 'reason': 'multiple_source_generations'}
    try:
        path = Path(semantic_source)
        source_before = samples._metadata(path.stat())
        limit = 64 * 1024 * 1024
        if source_before[2] > limit:
            return {'status': 'withheld', 'reason': 'semantic_source_history_limit'}
        with path.open('rb') as stream:
            source_bytes = stream.read(limit + 1)
        if len(source_bytes) != source_before[2] or samples._metadata(path.stat()) != source_before:
            return {'status': 'withheld', 'reason': 'semantic_source_changed_during_copy'}
        hash_before = hashlib.sha256(source_bytes).hexdigest()
        workspace = (Path(work_directory) if work_directory is not None else
            Path(__file__).resolve().parents[2] / 'artifacts' / 'local-observation-timeline-work')
        workspace.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='private-semantic-', dir=workspace) as temporary:
            frozen = Path(temporary) / 'source.log'
            frozen.write_bytes(source_bytes)
            copy_metadata = samples._metadata(frozen.stat())
            follower = RawFollower(frozen)
            _, source_rows = follower.poll()
            if (follower.framer.partial or follower.framer.errors or
                    source_rows != [row['entry'] for row in records]):
                return {'status': 'withheld', 'reason': 'source_values_order_or_framing_differ'}
            document = samples.collect_samples(frozen, schema_version=4,
                max_samples=256, origin='unclassified_local')
            replay = samples.replay_samples(document)
            if (samples._metadata(frozen.stat()) != copy_metadata or
                    hashlib.sha256(frozen.read_bytes()).hexdigest() != hash_before):
                return {'status': 'withheld', 'reason': 'semantic_source_changed_across_reads'}
    except (OSError, ValueError):
        return {'status': 'withheld', 'reason': 'existing_semantic_export_rejected_source'}
    supported = [pair for pair in pairs if pair['_semantic_supported']]
    if (len(supported) != len(document['samples']) or len(pairs) != document['counts']['matched_pairs'] or
            document['counts']['sample_limit_omissions']):
        return {'status': 'withheld', 'reason': 'semantic_gate_or_supported_order_count_mismatch'}
    for pair, sample, result in zip(supported, document['samples'], replay['samples']):
        selected = sample['response']['payload'].get('action', {})
        if selected.get('action_type') != pair['action_type'] and selected:
            return {'status': 'withheld', 'reason': 'semantic_action_order_mismatch'}
    for pair, result in zip(supported, replay['samples']):
        pair['semantic_trace'] = {'schema_version': document['schema_version'],
            'sample_index': result['sample_index'], 'successor_status': result['successor_status'],
            'trace_status': result.get('trace_status'), 'cast_evidence': result.get('cast_evidence'),
            'existing_export_input_values_verified': True,
            'marker_action_causality_verified': False}
    return {'status': 'verified_existing_export', 'counts': document['counts'],
            'source_bytes_sha256': hash_before,
            'source_mode': 'bounded_private_stable_copy',
            'source_values_and_order_verified': True, 'artifact_checks_passed': replay['artifact_checks_passed']}


def analyze_timeline(records, markers, *, poll_journal, semantic_source=None,
                     semantic_work_directory=None, integrity_reasons=()):
    """Return protocol edges and conservative marker candidates from frozen rows.

    IDs in bindings are local protocol evidence. Account/match identities,
    objects, raw payloads, user notes and log timestamp values are not exported.
    ``semantic_source`` is optional immutable original Player.log evidence, not
    a second source to be joined by time. It must equal every wrapper entry.
    """
    previous_id = 0
    for row in records:
        if (not isinstance(row, dict) or type(row.get('record_id')) is not int or
                row['record_id'] <= previous_id or type(row.get('poll_id')) is not int or
                not isinstance(row.get('source'), dict) or
                type(row['source'].get('generation')) is not int or 'entry' not in row or
                row['entry'] is not None and not isinstance(row['entry'], dict)):
            raise ValueError('invalid_or_unordered_raw_wrapper_metadata')
        previous_id = row['record_id']
    null_polls = {row['poll_id'] for row in records if row['entry'] is None}
    polls = _polls(poll_journal, null_polls)
    poll_by_id = {row['poll_id']: row for row in polls}
    input_reasons = list(integrity_reasons)
    for row in records:
        poll = poll_by_id.get(row['poll_id'])
        if poll is None or poll['generation'] != row['source']['generation']:
            input_reasons.append('wrapper_poll_generation_missing_or_inconsistent')
        if poll is not None and _ns(row.get('collected')) != poll['end']:
            input_reasons.append('wrapper_collection_clock_disagrees_with_poll')
    pairs, accepted, scopes, pending, continuity_polls = [], {}, {}, [], set()
    current, generation = None, None

    def end_pending(status, source=None):
        for pair in pending:
            pair['continuous_successor'] = {'status': status, 'source': source,
                                           'gameplay_effect_verified': False}
        pending.clear()

    def observe(event, details):
        scope = samples._scope(reducer)
        if event == 'continuity_error':
            continuity_polls.add(current['poll_id'])
            end_pending('interrupted')
        elif event == 'state_accepted' and details['kind'] != 'full_retransmit':
            for pair in pending:
                gs = details.get('message', {})
                continuous = (pair['_scope'] == scope and details['kind'] == 'diff' and
                              gs.get('prevGameStateId') == pair['binding']['game_state_id'])
                pair['continuous_successor'] = {'status': 'continuous_state_observed' if continuous else
                    'full_baseline_not_continuous' if details['kind'] == 'full' else 'interrupted',
                    'source': _ref(current, gs, state=True), 'gameplay_effect_verified': False}
            pending.clear()
        elif event == 'request_accepted':
            end_pending('next_request_without_intervening_state')
            req = details['request']
            accepted[(scope, req['id'], req['game_state_id'])] = {
                'source': _ref(current, details['message']),
                'authenticated': _current_verified_raw_request(reducer, details['message']) is not None,
                'continuity': req.get('_continuity_verified') is True,
                'message': copy.deepcopy(details['message']), 'request': copy.deepcopy(req),
                'context': _context(reducer)}

    reducer = RawReducer(observer=observe, include_state_messages=True, include_request_parameters=True)
    for current in records:
        next_generation = current['source']['generation']
        if generation != next_generation:
            end_pending('interrupted')
            reducer.reset(next_generation)
            generation = next_generation
            accepted.clear()
        before = copy.deepcopy(_current_verified_request(reducer))
        entry = current['entry']
        reducer.apply(entry)
        for pair in list(pending):
            if pair['_scope'] != samples._scope(reducer) or reducer.error is not None:
                end_pending('interrupted')
                break
        payload = entry.get('payload') if isinstance(entry, dict) else None
        strict, combat, terminal = (_paired_response(reducer, before, payload),
            _paired_combat_submit(reducer, before, payload), _paired_terminal_submit(reducer, before, payload))
        if not (strict or combat or terminal):
            continue
        scope = samples._scope(reducer)
        saved = accepted.get((scope, before['id'], before['game_state_id']))
        if saved is None:
            continue
        scopes.setdefault(scope, len(scopes) + 1)
        action, identity, truncated, opaque, _ = _complex_classify(before, payload)
        if combat:
            action = samples.KINDS.get(before['type'], 'unsupported')
            identity = 'not_applicable_combat_submission'
        mixed = any(key in entry for key in ('greToClientEvent','authenticateResponse','matchGameRoomStateChangedEvent'))
        raw_actions = payload.get('performActionResp', {}).get('actions', [])
        chosen = raw_actions[0] if isinstance(raw_actions, list) and len(raw_actions) == 1 and isinstance(raw_actions[0], dict) else {}
        target_status = ('missing' if 'targets' not in chosen else 'explicitly_empty' if chosen['targets'] == [] else
                         'nonempty_observed' if isinstance(chosen['targets'], list) else 'unsupported_shape')
        request_poll = saved['source']['poll_id']
        relevant = [poll for poll in polls if request_poll <= poll['poll_id'] <= current['poll_id']]
        source_reasons = sorted({reason for poll in relevant for reason in poll['reasons']})
        if not relevant or any(ident not in poll_by_id for ident in range(request_poll, current['poll_id'] + 1)):
            source_reasons.append('missing_poll_integrity_evidence')
        if any(request_poll <= ident <= current['poll_id'] for ident in continuity_polls):
            source_reasons.append('reducer_continuity_error')
        if mixed:
            source_reasons.append('mixed_record_ordering_unsupported')
        pair = {'protocol_pair': len(pairs) + 1, 'request_source': saved['source'],
            'response_source': _ref(current), 'request_type': before['type'], 'response_type': payload['type'],
            'binding': {'generation': generation, 'scope_ref': scopes[scope],
                'game_state_id': before['game_state_id'], 'request_id': before['id']},
            'exact_request_response_pair': True, 'raw_request_content_authenticated': saved['authenticated'],
            'request_continuity_verified': saved['continuity'],
            'confirmation': 'client_submission_only', 'action_type': action,
            'choice_identity': identity, 'choice_parameters_truncated': truncated,
            'opaque_parameter_contents_unknown': opaque, 'targets_field': target_status,
            'targeted_or_targetless_spell_verified': False, 'request_context': saved['context'],
            'source_integrity_reasons': source_reasons,
            'continuous_successor': {'status': 'not_observed', 'source': None, 'gameplay_effect_verified': False},
            'semantic_trace': None, 'marker_action_causality_verified': False,
            '_scope': scope, '_semantic_supported': False}
        # These are the existing producer's projectors, not another decoder.
        if saved['authenticated'] and saved['continuity'] and not mixed:
            try:
                refs = samples._Refs()
                snapshot = samples._snapshot(reducer, refs, scope)
                projected = samples._request(saved['message'], saved['request'], refs, scope, 4, snapshot)
                if before['type'] == 'GREMessageType_SelectTargetsReq':
                    from .semantic_targets import response
                    response(payload, before, projected['payload'], refs, scope)
                else:
                    samples._response(payload, before, refs, scope, 4)
                pair['_semantic_supported'] = True
            except samples.SampleError:
                pass
        pairs.append(pair)
        pending.append(pair)

    semantic = _attach_semantic_export(pairs, records, semantic_source, semantic_work_directory)
    results = []
    for group in _marker_groups(markers):
        reasons = list(group['reasons']) + input_reasons
        begin, end = group['begin'], group['end']
        overlapping = [poll for poll in polls if begin is not None and end is not None and _overlap(poll, begin, end)]
        reasons.extend(reason for poll in overlapping for reason in poll['reasons'])
        if any(poll['poll_id'] in continuity_polls for poll in overlapping):
            reasons.append('reducer_continuity_error')
        if not overlapping:
            reasons.append('missing_comparable_poll_interval')
        elif min(poll['begin'] for poll in overlapping) > begin or max(poll['end'] for poll in overlapping) < end:
            reasons.append('marker_interval_not_fully_observed')
        generations = {poll['generation'] for poll in overlapping}
        if len(generations) != 1 or None in generations:
            reasons.append('source_generation_unknown_or_changed')
        expected = MARKER_ACTIONS.get(group['marker_type'])
        temporal, candidates = [], []
        for pair in pairs:
            poll = poll_by_id.get(pair['response_source']['poll_id'])
            if not poll or begin is None or end is None or not _overlap(poll, begin, end):
                continue
            temporal.append(pair['protocol_pair'])
            if pair['action_type'] != expected or poll['history']:
                continue
            reasons.extend(pair['source_integrity_reasons'])
            if not pair['raw_request_content_authenticated'] or not pair['request_continuity_verified']:
                reasons.append('request_authentication_or_continuity_unverified')
                continue
            if pair['choice_identity'] in ('unique', 'multiple'):
                candidates.append(pair)
        if not temporal:
            reasons.append('no_temporal_protocol_observation')
        if reasons:
            classification = 'unreliable'
        elif len(candidates) == 1 and candidates[0]['choice_identity'] == 'unique':
            classification = 'protocol_supported_unique'
        elif candidates:
            classification = 'multiple_candidates'
        else:
            classification = 'temporal_only'
        results.append({key: group[key] for key in ('marker_group','marker_type','marker_line_before','marker_line_after')} |
            {'classification': classification, 'action_family': expected,
             'candidate_count': len(candidates), 'candidate_protocol_pairs': [pair['protocol_pair'] for pair in candidates],
             'candidate_response_record_ids': [pair['response_source']['record_id'] for pair in candidates],
             'temporal_protocol_pairs': temporal, 'integrity_reasons': sorted(set(reasons)),
             'marker_action_causality_verified': False,
             'targeted_vs_targetless_verified': False if expected == 'ActionType_Cast' else None})
    return {'schema_version': SCHEMA, 'record_count': len(records), 'marker_event_count': len(markers),
        'protocol_pairs': [{key: value for key, value in pair.items() if not key.startswith('_')} for pair in pairs],
        'marker_associations': results,
        'classification_counts': {name: sum(row['classification'] == name for row in results) for name in CLASSES},
        'semantic_export': semantic, 'marker_action_causality_verified': False,
        'time_basis': 'local_monotonic_poll_detection_intervals_only; not_actual_action_occurrence_bounds',
        'source_timestamp_clock': 'unknown; raw_source_timestamps_not_used_for_matching',
        'network_delay_seconds': None, 'server_acceptance_verified': False,
        'read_only': True, 'input_sent': False}


def analyze_snapshot(directory, *, semantic_source=None, semantic_work_directory=None):
    """Read a previously frozen collector snapshot; never modify its evidence."""
    directory = Path(directory)
    manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))
    reasons = []
    required = ('raw_records.jsonl','action_markers.jsonl','poll_journal.jsonl')
    data = {}
    for name in required:
        content = (directory / name).read_bytes()
        expected = manifest.get('files', {}).get(name, {}).get('sha256')
        if expected is None or hashlib.sha256(content).hexdigest() != expected:
            reasons.append('snapshot_hash_missing_or_mismatched')
        if content and not content.endswith(b'\n'):
            raise ValueError('snapshot_contains_incomplete_wrapper_line')
        data[name] = [json.loads(line) for line in content.splitlines()]
    return analyze_timeline(data['raw_records.jsonl'], data['action_markers.jsonl'],
        poll_journal=data['poll_journal.jsonl'], semantic_source=semantic_source,
        semantic_work_directory=semantic_work_directory,
        integrity_reasons=reasons)


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('snapshot', type=Path)
    parser.add_argument('--semantic-source', type=Path)
    parser.add_argument('--output', type=Path, required=True, help='NEW local analysis JSON; does not replace evidence')
    args = parser.parse_args(argv)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result = analyze_snapshot(args.snapshot, semantic_source=args.semantic_source,
                              semantic_work_directory=args.output.parent)
    with args.output.open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'protocol_pairs': len(result['protocol_pairs']),
        'classification_counts': result['classification_counts'], 'input_sent': False}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
