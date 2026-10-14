"""Opt-in read-only timing/continuity baseline; no per-poll document output.

Uses the production follower, reducer and projections. Private identities are
kept in memory solely for request deduplication and never enter the report.
"""
import hashlib
import json
import math
from pathlib import Path
import platform
import subprocess
import time

from .raw_log import RawFollower, RawReducer
from .decision_input import build_decision_input
from .cli import _project_action_frontier, _project_choice_graph


PHASES = ('startup_history', 'incremental', 'empty_poll', 'partial_append',
          'file_reset', 'baseline_recovery')
STAGES = ('poll_read_framing_ms', 'reducer_apply_ms', 'state_projection_ms',
          'decision_input_ms', 'action_frontier_ms', 'choice_graph_ms',
          'internal_pipeline_ms')
KINDS = ('actions_available', 'select_n', 'other')
_KINDS = {'GREMessageType_ActionsAvailableReq': 'actions_available',
          'GREMessageType_SelectNReq': 'select_n'}
_ERRORS = frozenset({
    'no_full_baseline', 'await_full_baseline', 'partial_raw_record_waiting',
    'malformed_raw_record', 'invalid_authenticateResponse',
    'invalid_matchGameRoomStateChangedEvent', 'invalid_greToClientEvent',
    'invalid_auth_identity', 'client_identity_changed',
    'room_identity_or_state_invalid', 'room_seat_conflict',
    'self_seat_unverified', 'invalid_gre_messages', 'invalid_gre_message',
    'missing_game_state_payload', 'gre_recipient_or_self_seat_unverified',
    'invalid_request_type', 'request_identity_missing',
    'conflicting_request_identity', 'unsupported_game_state',
    'game_state_id_missing', 'invalid_game_info', 'game_identity_unverified',
    'identity_conflict', 'full_identity_missing', 'conflicting_duplicate_state',
    'state_gap_or_missing_full', 'state_rollback', 'invalid_gameObjects',
    'invalid_zones', 'invalid_players', 'duplicate_gameObjects',
    'duplicate_zones', 'duplicate_players', 'invalid_deleted_ids',
    'invalid_zone_membership', 'object_zone_conflict', 'invalid_zone_type',
    'invalid_zone_owner', 'invalid_zone_viewers', 'missing_object_visibility',
    'invalid_object_zone', 'invalid_card_id', 'invalid_object_visibility',
    'invalid_object_viewers', 'invalid_object_seat', 'invalid_object_tapped',
    'invalid_player_seat', 'invalid_player_life', 'invalid_state_fields',
    'invalid_turn_seat', 'invalid_turn_number', 'invalid_game_stage',
    'incomplete_full_schema', 'raw_history_limit_exceeded',
})
_COUNTS = (
    'polls', 'json_records', 'gre_messages', 'polls_with_added_bytes',
    'recordless_polls', 'partial_polls', 'valid_snapshots', 'invalid_snapshots',
    'source_initializations', 'file_resets', 'state_acceptances',
    'full_baseline_acquisitions', 'full_baseline_recoveries',
    'continuity_error_events', 'unknown_or_unsupported_requests',
    'unsupported_broadcast_requests', 'snapshots_without_request',
    'polls_observed_request_but_no_final_request',
    'polls_observed_request_not_in_final_snapshot',
    'frontier_no_request_polls', 'choice_graph_no_request_polls',
    'late_poll_starts', 'missed_deadlines',
)
_REQUEST_COUNTS = (
    'observed_unique', 'supported_unique', 'unsupported_unique',
    'snapshot_polls', 'snapshot_supported_polls', 'snapshot_unsupported_polls',
    'not_in_final_poll_snapshot_unique', 'consumed_unique', 'superseded_unique',
    'frontier_success_snapshot_polls', 'frontier_unsupported_snapshot_polls',
    'frontier_unique_request_coverage', 'choice_graph_success_snapshot_polls',
    'choice_graph_unsupported_snapshot_polls', 'choice_graph_not_applicable_snapshot_polls',
    'choice_graph_unique_request_coverage',
)


def quantiles(values):
    """Nearest rank: sorted[ceil(p*N)-1], with null quantiles for N=0."""
    ordered = sorted(values)
    result = {'sample_count': len(ordered)}
    for label, fraction in (('p50_ms', .50), ('p95_ms', .95), ('p99_ms', .99)):
        result[label] = ordered[math.ceil(fraction * len(ordered)) - 1] if ordered else None
    result['max_ms'] = ordered[-1] if ordered else None
    return result


def _error(reason):
    return reason if isinstance(reason, str) and reason in _ERRORS else 'other'


def _identity(request):
    binding = request['binding']
    return tuple(binding.get(name) for name in
                 ('generation', 'match', 'game', 'game_state_id', 'self_seat')) + (request['id'],)


def _bucket():
    return {'counts': dict.fromkeys(_COUNTS, 0),
            'requests': {kind: dict.fromkeys(_REQUEST_COUNTS, 0) for kind in KINDS},
            'continuity_errors': {}, 'snapshot_errors': {},
            'timings_ms': {stage: [] for stage in STAGES},
            'scheduler_ms': {name: [] for name in
                             ('actual_poll_interval', 'start_lateness', 'interval_jitter')}}


def code_version():
    """Hash code only, never the selected log. No filesystem paths emitted."""
    source = Path(__file__).resolve().parent
    digest = hashlib.sha256()
    for name in ('raw_log.py', 'decision_input.py', 'action_frontier.py',
                 'action_gaps.py', 'choice_graph.py', 'semantic_evidence.py',
                 'cli.py', 'live_performance.py'):
        digest.update(name.encode('ascii') + b'\0' + (source / name).read_bytes())
    head = None
    try:
        result = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=source,
                                capture_output=True, text=True, check=False)
        candidate = result.stdout.strip()
        if result.returncode == 0 and len(candidate) == 40 and all(
                char in '0123456789abcdef' for char in candidate):
            head = candidate
    except OSError:
        pass
    return {'git_head': head, 'pipeline_source_sha256': digest.hexdigest()}


class PerformanceBaseline:
    """One production pipeline pass per poll; only fixed-category aggregates escape."""

    def __init__(self, path, interval=.25, max_history_bytes=64 * 1024 * 1024,
                 clock_ns=None):
        if not math.isfinite(interval) or not 0 < interval <= 60 or round(interval * 1_000_000_000) < 1:
            raise ValueError('invalid_performance_bounds')
        self.clock_ns = clock_ns or time.perf_counter_ns
        self.interval_ns = round(interval * 1_000_000_000)
        self.follower = RawFollower(path, max_history_bytes)
        self.reducer = RawReducer(observer=self._observe)
        self.buckets = {name: _bucket() for name in ('all_polls',) + PHASES}
        self._events = []
        self._seen = set()
        self._ended = {'consumed': set(), 'superseded': set()}
        self._covered = {'frontier': set(), 'choice_graph': set()}
        self._previous_start = None
        self.poll_attempts = 0

    def _observe(self, event, details):
        if event in ('request_accepted', 'request_ended'):
            request = details['request']
            self._events.append((event, {
                'identity': _identity(request),
                'kind': _KINDS.get(request['type'], 'other'),
                'supported': request.get('supported') is True,
                'disposition': details.get('disposition'),
            }))
        elif event == 'continuity_error':
            self._events.append((event, {'reason': _error(details['reason'])}))
        elif event in ('gre_messages', 'state_accepted', 'unsupported_broadcast_request'):
            self._events.append((event, details))

    def poll(self, scheduled_ns=None, missed_deadlines=0):
        self.poll_attempts += 1
        start = self.clock_ns()
        self._events = []
        previous_offset = self.follower.offset
        reset, records = self.follower.poll()
        after_read = self.clock_ns()
        added_bytes = self.follower.offset if reset else self.follower.offset - previous_offset
        if reset:
            self.reducer.reset(self.follower.generation)
        apply_ns = 0
        for record in records:
            before_apply = self.clock_ns()
            self.reducer.apply(record)
            apply_ns += self.clock_ns() - before_apply
        before_projection = self.clock_ns()
        document = self.reducer.document(include_frontier_rows=True)
        if self.follower.framer.partial:
            # Diagnostic last_valid is never used to repair current.
            document['current'] = {'valid': False, 'actionable': False}
            document['error'] = 'partial_raw_record_waiting'
        document['source'] = {'format': 'player-log-gre-v1', 'mode': 'watch',
                              'generation': self.follower.generation,
                              'byte_offset': self.follower.offset,
                              'phase': 'history' if reset else 'append',
                              'input_sent': False, 'executor_connected': False,
                              'partial_record': self.follower.framer.partial}
        after_projection = self.clock_ns()
        document['decision_input'] = build_decision_input(document)
        after_decision = self.clock_ns()
        _project_action_frontier(document)
        after_frontier = self.clock_ns()
        _project_choice_graph(document)
        after_graph = self.clock_ns()
        first = self.buckets['all_polls']['counts']['polls'] == 0
        rebuilding = any(event == 'state_accepted' and details['baseline'] != 'none'
                         for event, details in self._events)
        phase = ('startup_history' if first else 'file_reset' if reset else
                 'baseline_recovery' if rebuilding else 'incremental' if records else
                 'partial_append' if added_bytes else 'empty_poll')
        targets = (self.buckets['all_polls'], self.buckets[phase])
        self._tally(targets, document, len(records), added_bytes, reset, first)
        for bucket in targets:
            scheduler = bucket['scheduler_ms']
            if self._previous_start is not None:
                delta = start - self._previous_start
                scheduler['actual_poll_interval'].append(delta / 1_000_000)
                scheduler['interval_jitter'].append(abs(delta - self.interval_ns) / 1_000_000)
            if scheduled_ns is not None:
                lateness = max(0, start - scheduled_ns)
                scheduler['start_lateness'].append(lateness / 1_000_000)
                bucket['counts']['late_poll_starts'] += int(lateness > 0)
            bucket['counts']['missed_deadlines'] += missed_deadlines
            timings = bucket['timings_ms']
            for stage, ns in zip(STAGES[:-1], (
                    after_read - start, apply_ns, after_projection - before_projection,
                    after_decision - after_projection, after_frontier - after_decision,
                    after_graph - after_frontier)):
                timings[stage].append(ns / 1_000_000)
        self._previous_start = start
        internal_ms = (self.clock_ns() - start) / 1_000_000
        for bucket in targets:
            bucket['timings_ms']['internal_pipeline_ms'].append(internal_ms)
        return phase

    def _tally(self, targets, document, record_count, added_bytes, reset, first):
        def count(name, amount=1):
            for bucket in targets:
                bucket['counts'][name] += amount

        def request_count(kind, name, amount=1):
            for bucket in targets:
                bucket['requests'][kind][name] += amount

        def error_count(group, reason):
            for bucket in targets:
                mapping = bucket[group]
                mapping[reason] = mapping.get(reason, 0) + 1

        count('polls')
        count('json_records', record_count)
        count('polls_with_added_bytes', int(added_bytes > 0))
        count('recordless_polls', int(record_count == 0))
        count('partial_polls', int(self.follower.framer.partial))
        count('source_initializations', int(first and reset))
        count('file_resets', int(reset and not first))
        current = document['current']
        count('valid_snapshots' if current.get('valid') is True else 'invalid_snapshots')
        if document['error'] is not None:
            error_count('snapshot_errors', _error(document['error']))
        newly_observed = {}
        for event, details in self._events:
            if event == 'gre_messages':
                count('gre_messages', details['count'])
            elif event == 'continuity_error':
                count('continuity_error_events')
                error_count('continuity_errors', details['reason'])
            elif event == 'unsupported_broadcast_request':
                count('unsupported_broadcast_requests')
            elif event == 'state_accepted':
                count('state_acceptances')
                if details['baseline'] in ('acquired', 'recovered'):
                    count('full_baseline_' + ('acquisitions' if details['baseline'] == 'acquired'
                                              else 'recoveries'))
            elif event == 'request_accepted':
                identity, kind = details['identity'], details['kind']
                if identity in self._seen:
                    continue
                self._seen.add(identity)
                newly_observed[identity] = kind
                request_count(kind, 'observed_unique')
                request_count(kind, 'supported_unique' if details['supported'] else 'unsupported_unique')
                if kind == 'other' or not details['supported']:
                    count('unknown_or_unsupported_requests')
            elif event == 'request_ended':
                identity, kind = details['identity'], details['kind']
                disposition = details['disposition']
                if identity not in self._ended[disposition]:
                    self._ended[disposition].add(identity)
                    request_count(kind, disposition + '_unique')
        request = current.get('request') if current.get('valid') is True else None
        identity = _identity(request) if request is not None else None
        absent = {key: kind for key, kind in newly_observed.items() if key != identity}
        for kind in absent.values():
            request_count(kind, 'not_in_final_poll_snapshot_unique')
        count('polls_observed_request_not_in_final_snapshot', int(bool(absent)))
        if request is None:
            count('snapshots_without_request')
            count('polls_observed_request_but_no_final_request', int(bool(newly_observed)))
            count('frontier_no_request_polls')
            count('choice_graph_no_request_polls')
            return
        kind = _KINDS.get(request['type'], 'other')
        request_count(kind, 'snapshot_polls')
        request_count(kind, 'snapshot_supported_polls' if request['supported'] else 'snapshot_unsupported_polls')
        frontier = document['action_frontier']
        frontier_success = (isinstance(frontier, dict) and
                            frontier.get('immediate_completeness') == 'partial')
        request_count(kind, 'frontier_success_snapshot_polls' if frontier_success
                      else 'frontier_unsupported_snapshot_polls')
        if frontier_success and identity not in self._covered['frontier']:
            self._covered['frontier'].add(identity)
            request_count(kind, 'frontier_unique_request_coverage')
        graph = document['choice_graph']
        if kind != 'actions_available':
            # Existing graph API has no SelectN root support; do not invent it.
            request_count(kind, 'choice_graph_not_applicable_snapshot_polls')
        elif isinstance(graph, dict):
            request_count(kind, 'choice_graph_success_snapshot_polls')
            if identity not in self._covered['choice_graph']:
                self._covered['choice_graph'].add(identity)
                request_count(kind, 'choice_graph_unique_request_coverage')
        else:
            request_count(kind, 'choice_graph_unsupported_snapshot_polls')

    def summary(self):
        result = {}
        for name, bucket in self.buckets.items():
            result[name] = {key: value for key, value in bucket.items()
                            if key not in ('timings_ms', 'scheduler_ms')}
            result[name]['timings_ms'] = {stage: quantiles(values)
                                          for stage, values in bucket['timings_ms'].items()}
            result[name]['scheduler_ms'] = {metric: quantiles(values)
                                            for metric, values in bucket['scheduler_ms'].items()}
        return result


def run(path, duration=600, interval=.25, max_history_bytes=64 * 1024 * 1024,
        *, clock_ns=None, sleep=None):
    """Run to an absolute monotonic deadline, with no watch sample limit.

    Short durations are accepted by this Python API for deterministic tests;
    the public CLI deliberately permits only 600..900 seconds.
    """
    if (not math.isfinite(duration) or duration <= 0 or not math.isfinite(interval) or
            not 0 < interval <= 60 or round(interval * 1_000_000_000) < 1 or
            not 1 <= max_history_bytes <= 1024 * 1024 * 1024):
        raise ValueError('invalid_performance_bounds')
    clock_ns, sleep = clock_ns or time.perf_counter_ns, sleep or time.sleep
    monitor = PerformanceBaseline(path, interval, max_history_bytes, clock_ns)
    version = code_version()
    started = clock_ns()
    deadline = started + round(duration * 1_000_000_000)
    scheduled = started
    pending_missed = 0
    trailing_missed = 0
    stop_reason, failure = 'duration_elapsed', None
    try:
        while scheduled < deadline:
            now = clock_ns()
            if now < scheduled:
                sleep((scheduled - now) / 1_000_000_000)
            if clock_ns() >= deadline:
                # Oversleep can leave scheduled slots unexecuted. Earlier
                # pending skips also have no subsequent poll to own them.
                trailing_missed = pending_missed + (
                    deadline - scheduled + monitor.interval_ns - 1) // monitor.interval_ns
                break
            monitor.poll(scheduled, pending_missed)
            scheduled += monitor.interval_ns
            now = clock_ns()
            # Skip elapsed scheduling slots instead of bursting catch-up polls.
            pending_missed = 0
            while scheduled < now and scheduled < deadline:
                pending_missed += 1
                scheduled += monitor.interval_ns
            trailing_missed = pending_missed
        remaining = deadline - clock_ns()
        if remaining > 0:
            sleep(remaining / 1_000_000_000)
    except KeyboardInterrupt:
        stop_reason = 'keyboard_interrupt'
    except Exception as exc:
        # No raw exception text, path or GRE payload may escape this command.
        stop_reason = 'pipeline_error'
        failure = (_error(str(exc)) if isinstance(exc, ValueError) else
                   'source_io_error' if isinstance(exc, OSError) else 'other')
    ended = clock_ns()
    # If the last slots were skipped, no subsequent poll exists to own them.
    before_summary = clock_ns()
    report = {
        'schema': 'mtga-live-readonly-performance-v1',
        'environment': {'os': platform.system(), 'os_release': platform.release(),
                        'architecture': platform.machine(), 'python': platform.python_version()},
        'code_version': version,
        'configuration': {'duration_seconds': duration, 'interval_seconds': interval,
                          'max_history_bytes': max_history_bytes},
        'elapsed_seconds': (ended - started) / 1_000_000_000,
        'stopped': True, 'stop_reason': stop_reason, 'failure_category': failure,
        'trailing_missed_deadlines': trailing_missed,
        'poll_attempts': monitor.poll_attempts,
        'incomplete_poll_attempts': monitor.poll_attempts - monitor.buckets['all_polls']['counts']['polls'],
        'groups': monitor.summary(),
        'definitions': {
            'quantile': 'nearest_rank_sorted_ceil_p_times_n_minus_one; empty=null',
            'phase_precedence': list(PHASES[:1]) + ['file_reset', 'baseline_recovery',
                                                    'incremental', 'partial_append', 'empty_poll'],
            'startup_history': 'first poll including initial source initialization',
            'file_reset': 'later follower replacement/truncation/reset poll',
            'baseline_recovery': 'non-startup/reset poll with successful Full baseline acquisition or recovery',
            'incremental': 'complete JSON records; excludes startup/reset/baseline recovery',
            'partial_append': 'new bytes but no complete JSON record; may include ignored non-JSON bytes',
            'empty_poll': 'no new bytes and no complete JSON record; pending partial may remain',
            'json_records': 'framer outputs including malformed sentinel; not GRE message count',
            'partial_polls': 'framer has unfinished record at poll end, regardless of added bytes',
            'state_acceptances': 'accepted new Full/Diff or successful identical-Full recovery; not idle snapshots',
            'continuity_error_events': 'each production reducer invalidate call, including repeated errors',
            'observed_unique': 'authenticated accepted request identity, including unsupported; transient requests retained',
            'supported_unique': 'production Reducer supported flag; ActionsAvailable stays false (action_details_unverified) even with partial Frontier/Graph',
            'not_in_final_poll_snapshot_unique': 'newly observed request absent from valid current at same poll end',
            'request_coverage': 'first successful final-poll projection per unique request; transient requests may have zero coverage',
            'snapshot_polls': 'repeated idle snapshots count here, never as unique request coverage',
            'graph_success': 'existing graph object built; may have zero complex nodes; no legality claim',
            'select_n_graph': 'not_applicable_existing_api; no root SelectN graph support',
            'internal_pipeline_ms': 'poll+reset+all apply+one document+DecisionInput+Frontier+Graph+collector overhead; no sleep/summary/serialization/output',
            'reducer_apply_ms': 'sum of per-record apply timings per poll; zero when no records; reset only in internal',
            'interval_jitter': 'absolute actual start-to-start interval minus configured interval',
            'start_lateness': 'max(0, actual start minus assigned deadline)',
            'missed_deadlines': 'skipped elapsed schedule slots; per-poll counts exclude trailing slots',
            'poll_attempts': 'includes interrupted/failed incomplete polls; group polls count completed pipelines',
        },
        'game_event_to_log_write_ms': None,
        'true_end_to_end_ms': None,
        'read_only': True, 'input_sent': False, 'executor_connected': False,
        'execution_ready': False, 'legal_choice_verified': False,
        'report_output_write_ms': None,
    }
    report['summary_build_ms'] = (clock_ns() - before_summary) / 1_000_000
    return report


def serialize_report(report, clock_ns=None):
    """Serialize the aggregate once; append its measured cost outside payload."""
    clock_ns = clock_ns or time.perf_counter_ns
    start = clock_ns()
    payload = json.dumps(report, ensure_ascii=True, separators=(',', ':'))
    elapsed = (clock_ns() - start) / 1_000_000
    return payload[:-1] + ',"summary_serialization_ms":' + json.dumps(elapsed) + '}'
