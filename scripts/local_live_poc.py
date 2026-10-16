"""Private, read-only local MTGA evidence collector; never sends game input.

The production RawFollower/RawReducer are the only GRE parser/state machine.
Record references use poll byte spans, not invented per-record byte offsets.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
# Executing this script must import this fixed checkout, not an editable install
# pointing at another branch which may be under active development.
sys.path.insert(0, str(ROOT / 'src'))
from mtgaplayer.raw_log import RawFollower, RawReducer
from mtgaplayer.response_evidence import _current_verified_request, _paired_response
from mtgaplayer.semantic_evidence import SemanticChoiceCounter, ComplexSemanticChoiceCounter


JSONL_FILES = ('raw_records.jsonl', 'log_observations.jsonl',
               'state_observations.jsonl', 'screenshots.jsonl',
               'poll_journal.jsonl', 'action_markers.jsonl')


def clocks():
    mono = time.monotonic_ns()
    wall = datetime.now(timezone.utc).isoformat(timespec='microseconds')
    return {'wall_time_utc': wall, 'monotonic_ns': mono,
            'clock_pair_sampling': 'monotonic_then_wall_adjacent_calls'}


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def atomic_json(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.replace(temporary, path)


def code_version():
    def git(*args):
        result = subprocess.run(['git', *args], cwd=ROOT, capture_output=True,
                                text=True, check=False)
        return result.stdout.strip() if result.returncode == 0 else None
    files = sorted((ROOT / 'src' / 'mtgaplayer').glob('*.py'))
    files += [Path(__file__)]
    for name in ('live_poc_capture.py', 'live_poc_markers.py'):
        companion = ROOT / 'scripts' / name
        if companion.exists():
            files.append(companion)
    hashes = {str(path.relative_to(ROOT)).replace('\\', '/'): digest(path) for path in files}
    combined = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    return {'git_sha': git('rev-parse', 'HEAD'), 'git_tree': git('rev-parse', 'HEAD^{tree}'),
            'working_tree_dirty': bool(git('status', '--porcelain')),
            'source_sha256': combined, 'source_files_sha256': hashes}


def require_ignored(path):
    """Prevent accidental writing of private evidence into tracked directories."""
    path = Path(path).resolve()
    try:
        relative = path.relative_to(ROOT)
    except ValueError as exc:
        raise ValueError('output_must_be_inside_this_checkout_ignored_artifacts') from exc
    result = subprocess.run(['git', 'check-ignore', '--no-index', '--', str(relative)],
                            cwd=ROOT, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise ValueError('private_output_directory_must_be_git_ignored')
    return path


class Collector:
    """One writer per collector JSONL; the marker UI alone owns marker writes."""

    def __init__(self, log, output, *, interval=1.0, pid=None, hwnd=None,
                 capture_method='printwindow', capture=None, find_window=None):
        if not math.isfinite(interval) or not 0 < interval <= 60:
            raise ValueError('interval_must_be_positive_and_at_most_60')
        self.log, self.output = Path(log).resolve(), Path(output).resolve()
        self.output.mkdir(parents=True, exist_ok=False)
        (self.output / 'screenshots').mkdir()
        self.interval, self.pid, self.hwnd = interval, pid, hwnd
        self.capture_method = capture_method
        if capture is None:
            from live_poc_capture import capture_window, find_mtga_window
            capture, find_window = capture_window, find_mtga_window
        self.capture, self.find_window = capture, find_window
        self.write_lock = threading.RLock()
        self.capture_stop = threading.Event()
        self.capture_thread = None
        self.capture_id = 0
        self.capture_started_ns = None
        self.closed = False
        self.follower = RawFollower(self.log)
        self.events = []
        self.reducer = RawReducer(observer=self._observe,
            include_state_messages=True, include_request_parameters=True)
        self.simple, self.complex = SemanticChoiceCounter(), ComplexSemanticChoiceCounter()
        self.streams = {name: (self.output / name).open('x', encoding='utf-8', newline='\n')
                        for name in JSONL_FILES if name != 'action_markers.jsonl'}
        # Create once; never open the marker writer while collection is running.
        (self.output / 'action_markers.jsonl').touch(exist_ok=False)
        self.poll_id = self.record_id = 0
        self.counts = {'polls': 0, 'records': 0, 'gre_messages': 0,
                       'client_responses': 0, 'malformed_records': 0,
                       'screenshots_completed': 0, 'api_quality_frames': 0, 'capture_failures': 0,
                       'log_errors': 0, 'file_resets_after_startup': 0}
        self.manifest = {'schema_version': 'mtgaplayer.local-live-poc.v1',
            'started': clocks(), 'collector_pid': os.getpid(), 'code': code_version(),
            'log_path_private': str(self.log), 'status': 'running',
            'interval_seconds': interval, 'capture_method': capture_method,
            'read_only': True, 'input_sent': False,
            'private_evidence_do_not_upload': True,
            'raw_storage': 'complete_framed_payloads_and_null_errors_only',
            'raw_bytes_retained': False,
            'source_reference_precision': 'poll_byte_span_not_individual_record_span',
            'source_clock': 'unknown_units_timezone_and_offset; timestamp_preserved_verbatim',
            'partial_json_bytes_retained_by_follower_in_memory_only': True,
            'snapshot_contract': 'completed_poll_prefix_and_completed_screenshot_files'}
        self.manifest['capture_execution'] = ('independent_daemon_thread; Windows_API_timeout_unknown; '
            'a_hung_capture_does_not_block_log_polls; shutdown_join_bounded_250ms')
        atomic_json(self.output / 'manifest.json', self.manifest)

    def _observe(self, event, details):
        self.events.append({'event': event, 'details': copy.deepcopy(details)})

    def write(self, name, row):
        with self.write_lock:
            if self.closed:
                return
            self.streams[name].write(json.dumps(row, ensure_ascii=False, separators=(',', ':')) + '\n')
            self.streams[name].flush()

    def capture_health(self):
        started = self.capture_started_ns
        return {'capture_in_progress': started is not None,
                'capture_in_progress_age_seconds':
                    (time.monotonic_ns() - started) / 1_000_000_000 if started is not None else None,
                'capture_api_timeout': 'unknown',
                'capture_worker_alive': bool(self.capture_thread and self.capture_thread.is_alive())}

    def state_document(self, error_override=None):
        document = self.reducer.document(include_frontier_rows=True, include_decision_state=True)
        if self.follower.framer.partial or error_override is not None:
            document['diagnostic_current_before_source_invalidation'] = document['current']
            document['current'] = {**{key: document['current'].get(key) for key in
                ('match', 'game', 'self_seat', 'game_state_id')},
                'valid': False, 'actionable': False}
            document['error'] = error_override or 'partial_raw_record_waiting'
        return document

    def capture_once(self):
        started = clocks()
        self.capture_id += 1
        self.capture_started_ns = started['monotonic_ns']
        row = {'poll_id': self.poll_id, 'capture_id': self.capture_id, 'capture_started': started,
               'capture_method': self.capture_method}
        target = None
        api_quality_success = False
        temporary = self.output / 'screenshots' / f'{self.capture_id:08d}.pending.png'
        completed = temporary.with_name(f'{self.capture_id:08d}.png')
        try:
            # Revalidate the real window each poll. Capture also checks PID/HWND.
            window = self.find_window() if self.find_window else {}
            pid = self.pid if self.pid is not None else window.get('pid')
            hwnd = self.hwnd if self.hwnd is not None else window.get('hwnd')
            row.update({'pid': pid, 'hwnd': hwnd})
            if not pid or not hwnd:
                raise RuntimeError('mtga_window_not_found')
            result = self.capture(int(hwnd), int(pid), temporary, method=self.capture_method)
            row['capture_result'] = result
            api_quality_success = result.get('status') == 'success'
            row['api_quality_success'] = api_quality_success
            if temporary.is_file() and temporary.stat().st_size:
                os.replace(temporary, completed)
                target = completed
                row.update({'file': str(completed.relative_to(self.output)).replace('\\', '/'),
                            'sha256': digest(completed), 'bytes': completed.stat().st_size,
                            'file_completed': True,
                            'visual_content_verified': False})
                self.counts['screenshots_completed'] += 1
            else:
                row.update({'file_completed': False, 'error': 'capture_produced_no_file'})
        except Exception as exc:
            row.update({'file_completed': False, 'error_type': type(exc).__name__, 'error': str(exc)})
        finally:
            complete_quality_frame = api_quality_success and row.get('file_completed', False)
            self.counts['api_quality_frames'] += int(complete_quality_frame)
            self.counts['capture_failures'] += int(not complete_quality_frame)
            row['capture_completed'] = clocks()
            self.write('screenshots.jsonl', row)
            self.capture_started_ns = None
        return target

    def poll_once(self, *, screenshots=True):
        self.poll_id += 1
        started = clocks()
        previous_offset, previous_generation = self.follower.offset, self.follower.generation
        self.write('poll_journal.jsonl', {'event': 'poll_started', 'poll_id': self.poll_id, **started})
        try:
            reset, records = self.follower.poll()
            acquired = clocks()
            span = {'generation': self.follower.generation,
                    'file_identity': self.follower.identity,
                    'path_private': str(self.log),
                    'byte_start': 0 if reset else previous_offset,
                    'byte_end': self.follower.offset,
                    'precision': 'poll_span_not_record_span',
                    'record_may_begin_in_prior_partial_poll': True}
            if reset:
                self.reducer.reset(self.follower.generation)
                if previous_generation:
                    self.counts['file_resets_after_startup'] += 1
            for index, entry in enumerate(records):
                self.record_id += 1
                ref = {'poll_id': self.poll_id, 'record_id': self.record_id,
                       'record_index_in_poll': index, 'source': span,
                       'collected': acquired}
                raw = {**ref, 'entry': entry,
                       'source_timestamp_raw': entry.get('timestamp') if isinstance(entry, dict) else None,
                       'source_timestamp_clock': 'unknown'}
                self.write('raw_records.jsonl', raw)
                self.events = []
                before = copy.deepcopy(_current_verified_request(self.reducer))
                self.reducer.apply(entry)
                payload = entry.get('payload') if isinstance(entry, dict) else None
                paired = _paired_response(self.reducer, before, payload)
                if paired and payload.get('type') == 'ClientMessageType_PerformActionResp':
                    self.simple.add(before, payload)
                    self.complex.add(before, payload)
                gre = entry.get('greToClientEvent') if isinstance(entry, dict) else None
                messages = gre.get('greToClientMessages') if isinstance(gre, dict) else None
                messages = messages if isinstance(messages, list) else []
                response_type = payload.get('type') if isinstance(payload, dict) else None
                client_response = (isinstance(response_type, str) and
                    response_type.startswith('ClientMessageType_') and response_type.endswith('Resp'))
                summary = {**ref, 'raw_evidence': f'raw_records.jsonl#record_id={self.record_id}',
                    'malformed_record': entry is None,
                    'root_fields': sorted(entry) if isinstance(entry, dict) else [],
                    'gre_message_types': [m.get('type') if isinstance(m, dict) else None for m in messages],
                    'client_response_type': response_type if client_response else None,
                    'exact_current_own_response_paired': paired,
                    'pair_confirmation': 'client_submission_only' if paired else None,
                    'source_timestamp_raw': raw['source_timestamp_raw'],
                    'source_timestamp_clock': 'unknown',
                    'reducer_event_types': [event['event'] for event in self.events]}
                self.write('log_observations.jsonl', summary)
                document = self.state_document()
                self.write('state_observations.jsonl', {**ref,
                    'kind': 'record',
                    'raw_evidence': summary['raw_evidence'],
                    'document': document,
                    'raw_turn_observation': copy.deepcopy(self.reducer.turn),
                    'semantic_observer_events': self.events,
                    'framer_partial_at_poll_end': self.follower.framer.partial,
                    'not_current_if_partial': self.follower.framer.partial})
                self.counts['records'] += 1
                self.counts['gre_messages'] += len(messages)
                self.counts['client_responses'] += int(client_response)
                self.counts['malformed_records'] += int(entry is None)
            log_health = {'reset': reset, 'source': span, 'records': len(records),
                'partial_record': self.follower.framer.partial,
                'framing_errors': self.follower.framer.errors,
                'reducer_error': self.reducer.error,
                'log_acquired': acquired}
        except (OSError, ValueError) as exc:
            self.counts['log_errors'] += 1
            log_health = {'log_error': str(exc), 'log_error_type': type(exc).__name__,
                          'records': 0, 'partial_record': self.follower.framer.partial}
        if screenshots:
            self.capture_once()
        # Empty polls can introduce an incomplete source tail or a read error.
        # Publish an explicit boundary observation rather than leaving the last
        # record's historical valid=true row looking like the newest current.
        self.write('state_observations.jsonl', {
            'kind': 'poll_boundary', 'poll_id': self.poll_id, 'record_id': None,
            'last_record_id': self.record_id, 'collected': clocks(),
            'source': log_health.get('source', {
                'generation': self.follower.generation, 'file_identity': self.follower.identity,
                'path_private': str(self.log), 'byte_end': self.follower.offset,
                'precision': 'last_successfully_read_offset_on_log_error'}),
            'raw_evidence': None, 'semantic_observer_events': [],
            'document': self.state_document('log_read_failed' if 'log_error' in log_health else None),
            'raw_turn_observation': copy.deepcopy(self.reducer.turn),
            'framer_partial_at_poll_end': self.follower.framer.partial,
            'not_current_if_partial': self.follower.framer.partial})
        self.counts['polls'] += 1
        with self.write_lock:
            screenshot_index_bytes = self.streams['screenshots.jsonl'].tell()
        self.write('poll_journal.jsonl', {'event': 'poll_complete', 'poll_id': self.poll_id,
            'poll_started': started, 'poll_completed': clocks(), **log_health,
            'screenshot_index_bytes': screenshot_index_bytes,
            'counts': self.counts.copy(), **self.capture_health()})
        atomic_json(self.output / 'health.json', {'poll_id': self.poll_id,
            'updated': clocks(), 'counts': self.counts.copy(), **log_health,
            **self.capture_health()})

    def close(self, reason='stop_file'):
        self.capture_stop.set()
        if self.capture_thread is not None:
            self.capture_thread.join(timeout=.25)
        with self.write_lock:
            self.closed = True
            for stream in self.streams.values():
                stream.close()
        self.manifest.update({'status': 'stopped', 'stop_reason': reason,
            'stopped': clocks(), 'counts': self.counts,
            'capture_shutdown': self.capture_health(),
            'simple_choice_summary': self.simple.report(),
            'complex_choice_summary': self.complex.report()})
        atomic_json(self.output / 'manifest.json', self.manifest)

    def run(self, duration=0):
        deadline = time.monotonic() + duration if duration else None
        reason = 'stop_file'
        def capture_loop():
            while not self.capture_stop.is_set():
                started = time.monotonic()
                self.capture_once()
                self.capture_stop.wait(max(0, self.interval - (time.monotonic() - started)))
        self.capture_thread = threading.Thread(target=capture_loop, name='read-only-MTGA-capture', daemon=True)
        self.capture_thread.start()
        try:
            while not (self.output / 'stop').exists():
                started = time.monotonic()
                self.poll_once(screenshots=False)
                if deadline is not None and time.monotonic() >= deadline:
                    reason = 'duration_limit'
                    break
                time.sleep(max(0, self.interval - (time.monotonic() - started)))
        except KeyboardInterrupt:
            reason = 'keyboard_interrupt'
        except BaseException:
            reason = 'collector_error'
            raise
        finally:
            self.close(reason)


def complete_rows(path, limit=None):
    """Read a bounded complete-line prefix; never consume an in-progress line."""
    path = Path(path)
    if not path.exists():
        return []
    limit = path.stat().st_size if limit is None else limit
    result = []
    with path.open('rb') as stream:
        while stream.tell() < limit:
            line = stream.readline(limit - stream.tell())
            if not line.endswith(b'\n'):
                break
            result.append((line, json.loads(line)))
    return result


def snapshot(source, output):
    source, output = Path(source).resolve(), Path(output).resolve()
    journal = complete_rows(source / 'poll_journal.jsonl')
    completed = [row for _, row in journal if row.get('event') == 'poll_complete']
    if not completed:
        raise ValueError('no_completed_poll_to_snapshot')
    boundary = completed[-1]
    max_poll = boundary['poll_id']
    cutoff_ns = boundary['poll_completed']['monotonic_ns']
    output.mkdir(parents=True, exist_ok=False)
    (output / 'screenshots').mkdir()
    files = {}
    screenshot_rows = []
    for name in JSONL_FILES:
        selected = []
        limit = boundary.get('screenshot_index_bytes') if name == 'screenshots.jsonl' else None
        for line, row in complete_rows(source / name, limit):
            if name == 'action_markers.jsonl':
                # UI markers have their own writer and clock; keep only markers
                # carrying a comparable monotonic timestamp before the cutoff.
                marker_ns = row.get('monotonic_ns')
                if marker_ns is None and isinstance(row.get('collected'), dict):
                    marker_ns = row['collected'].get('monotonic_ns')
                keep = isinstance(marker_ns, int) and marker_ns <= cutoff_ns
            else:
                keep = row.get('poll_id', max_poll + 1) <= max_poll
                if name == 'screenshots.jsonl':
                    keep = keep and row.get('capture_completed', {}).get('monotonic_ns', cutoff_ns + 1) <= cutoff_ns
            if keep:
                selected.append(line)
                if name == 'screenshots.jsonl':
                    screenshot_rows.append(row)
        target = output / name
        target.write_bytes(b''.join(selected))
        files[name] = {'sha256': digest(target), 'bytes': target.stat().st_size,
                       'complete_lines': len(selected)}
    for row in screenshot_rows:
        if not row.get('file_completed'):
            continue
        relative = Path(row['file'])
        if relative.is_absolute() or '..' in relative.parts or relative.parts[0] != 'screenshots':
            raise ValueError('invalid_screenshot_reference')
        original, target = source / relative, output / relative
        shutil.copyfile(original, target)
        actual = digest(target)
        if actual != row['sha256']:
            raise ValueError('snapshot_screenshot_hash_mismatch')
        files[str(relative).replace('\\', '/')] = {'sha256': actual, 'bytes': target.stat().st_size}
    original_manifest = json.loads((source / 'manifest.json').read_text(encoding='utf-8'))
    atomic_json(output / 'manifest.json', {'schema_version': 'mtgaplayer.local-live-snapshot.v1',
        'created': clocks(), 'source_session_private': str(source),
        'source_manifest': original_manifest, 'completed_poll_id': max_poll,
        'boundary_log_health': {key: boundary.get(key) for key in
            ('partial_record', 'framing_errors', 'source', 'reset', 'records',
             'reducer_error', 'log_error', 'log_error_type', 'log_acquired')},
        'cutoff_monotonic_ns': cutoff_ns, 'files': files,
        'read_only_snapshot': True,
        'consistency': 'all_collector_rows_at_or_before_last_complete_poll; markers_before_cutoff',
        'input_sent': False, 'raw_bytes_retained': False})
    for target in output.rglob('*'):
        if target.is_file():
            target.chmod(stat.S_IREAD)
    return {'snapshot': str(output), 'completed_poll_id': max_poll,
            'files': len(files), 'source_collector_status': original_manifest['status']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command')
    frozen = sub.add_parser('snapshot', help='freeze the last completed collection poll')
    frozen.add_argument('--source', required=True, type=Path)
    frozen.add_argument('--output', required=True, type=Path)
    collect = sub.add_parser('collect', help='read-only collection (default command)')
    collect.add_argument('--log', required=True, type=Path)
    collect.add_argument('--output', required=True, type=Path)
    collect.add_argument('--interval', type=float, default=1)
    collect.add_argument('--duration', type=float, default=0)
    collect.add_argument('--pid', type=int)
    collect.add_argument('--hwnd', type=lambda value: int(value, 0))
    collect.add_argument('--capture-method', choices=('printwindow', 'screen'), default='printwindow')
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0].startswith('-'):
        argv.insert(0, 'collect')
    args = parser.parse_args(argv)
    if args.command == 'snapshot':
        print(json.dumps(snapshot(args.source, require_ignored(args.output)), ensure_ascii=False))
        return 0
    if not math.isfinite(args.duration) or args.duration < 0:
        parser.error('duration must be finite and nonnegative')
    collector = Collector(args.log, require_ignored(args.output), interval=args.interval,
        pid=args.pid, hwnd=args.hwnd, capture_method=args.capture_method)
    print(json.dumps({'session': str(collector.output), 'collector_pid': os.getpid(),
                      'status': 'running', 'input_sent': False}), flush=True)
    collector.run(args.duration)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
