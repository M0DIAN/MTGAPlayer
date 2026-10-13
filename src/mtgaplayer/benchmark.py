"""Launch actual independent Windows harness and retain all raw observations."""
from collections import Counter
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4
from .files import atomic
from .native import Adapter, NativeBlocked, probe, save_bmp
from .player import Reader, run_loop
from .visual import wait_for_frame


def distribution(values):
    if not values:
        return None
    values = sorted(values)
    return {**{f'p{q}': values[max(0, math.ceil(q / 100 * len(values)) - 1)]
               for q in (50, 95, 99)}, 'max': values[-1], 'n': len(values)}


def summarize(rows, startup_ms):
    status = Counter(row['status'] for row in rows)
    success = [r for r in rows if r['status'] == 'confirmed']
    def times(items, first, last):
        return [(r[last] - r[first]) * 1000 for r in items
                if r.get(first) is not None and r.get(last) is not None]
    durations = times(success, 'opportunity_at', 'confirm')
    compound = sum(r['action'] == 'cast' for r in success)
    action_counts = Counter(r['action'] for r in success)
    valid_timestamps = all(r.get('opportunity_at') is not None and
                           all(r.get(k) is not None for k in ('observed', 'state_ready', 'decision_end',
                                                            'first_input', 'last_input', 'confirm')) and
                           r['opportunity_at'] <= r['observed'] <= r['state_ready'] <= r['decision_end'] <=
                           r['first_input'] <= r['last_input'] <= r['confirm'] for r in success)
    acceptance = (len(success) >= 30 and compound >= 10 and len(success) == len(rows) and
                  {'land', 'cast', 'pass'} <= set(action_counts) and
                  valid_timestamps and bool(durations) and max(durations) <= 3000)
    return {'scope': 'native_synthetic_harness_only', 'opportunities': len(rows),
            'status_counts': {key: status[key] for key in ('confirmed', 'fail', 'unsupported',
                              'timeout', 'paused', 'cancelled', 'uncertain')},
            'unfinished': sum(r.get('ended_at') is None for r in rows),
            'compound_confirmed': compound, 'action_counts': dict(action_counts),
            'startup_ms': startup_ms, 'success_end_to_end_ms': distribution(durations),
            'all_ended_opportunities_ms': distribution(times(rows, 'opportunity_at', 'ended_at')),
            'before_input_ms': distribution(times(rows, 'opportunity_at', 'first_input')),
            'input_ms': distribution(times(rows, 'first_input', 'last_input')),
            'after_input_ms': distribution(times(rows, 'last_input', 'confirm')),
            'ordered_seven_timestamps': valid_timestamps if success else None,
            'NATIVE_HARNESS': 'PASS' if acceptance else 'FAIL',
            'LATENCY': 'PASS_SUPPORTED_SET' if acceptance else 'NOT_ESTABLISHED',
            'LIVE_MTGA': 'NOT_RUN', 'MTGA_object_location': 'NOT_IMPLEMENTED'}


def run(directory, count=30, scenario='normal', duration=90):
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    nonce = uuid4().hex
    start = time.monotonic()
    process, adapter, reader = None, None, None
    report = {'NATIVE_HARNESS': 'BLOCKED_NATIVE', 'LATENCY': 'NOT_MEASURED', 'LIVE_MTGA': 'NOT_RUN',
              'native_probe': probe(), 'rows': 0}
    try:
        with (directory / 'harness.stdout.txt').open('w') as stdout, (directory / 'harness.stderr.txt').open('w') as stderr:
            # Windows venv python.exe is a redirector with a different child
            # PID. Launch the same base interpreter directly so HWND ownership
            # can be checked against Popen.pid, not an unverified supplied PID.
            environment = os.environ.copy()
            environment['PYTHONPATH'] = str(Path(__file__).resolve().parents[1])
            process = subprocess.Popen([getattr(sys, '_base_executable', sys.executable), '-m', 'mtgaplayer', 'harness', '--directory',
                         str(directory), '--nonce', nonce, '--count', str(count), '--scenario', scenario],
                         stdout=stdout, stderr=stderr, env=environment)
            deadline = time.monotonic() + 8
            while not (directory / 'handshake.json').exists():
                if process.poll() is not None:
                    raise NativeBlocked('harness_exit_before_handshake')
                if time.monotonic() > deadline:
                    raise NativeBlocked('harness_start_timeout')
                time.sleep(0.05)
            handshake = json.loads((directory / 'handshake.json').read_text())
            if handshake['nonce'] != nonce:
                raise NativeBlocked('nonce_mismatch')
            adapter = Adapter(handshake, process.pid, directory)
            # Harness activates only itself. The player never steals focus.
            adapter.check()
            reader = Reader(directory / 'normalized.jsonl')
            initial = reader.sample()
            # Handshake binds the process, not DWM presentation. Reuse the
            # bounded startup deadline; only matching, stable pixels are ready.
            frame, _, initial = wait_for_frame(adapter, nonce, reader.sample, deadline,
                    required=[o['id'] for o in initial.get('objects', [])
                              if o['zone'] in {'hand', 'battlefield'}],
                    stop=lambda: (directory / 'stop').exists(), expected=initial)
            save_bmp(directory / 'harness-initial.bmp', frame)
            startup_ms = (time.monotonic() - start) * 1000
            rows = run_loop(reader, adapter, nonce, directory / 'opportunities.jsonl', count, duration,
                            lambda: (directory / 'stop').exists())
            report = {**summarize(rows, startup_ms), 'native_probe': report['native_probe'],
                      'harness_pid': process.pid, 'player_pid': __import__('os').getpid(),
                      'python': sys.version, 'scenario': scenario, 'client_size': [820, 580],
                      'protocol': 'markers-v1', 'producer_complete':
                      json.loads((directory / 'complete.json').read_text()) if
                      (directory / 'complete.json').exists() else None}
            if rows and rows[-1]['status'] == 'confirmed':
                save_bmp(directory / 'harness-final.bmp', adapter.capture())
    except (NativeBlocked, OSError, ValueError, KeyError, InterruptedError) as exc:
        report['reason'] = str(exc)
        # Even when startup prevents input, preserve any produced opportunities.
        if (directory / 'normalized.jsonl').exists() and not (directory / 'opportunities.jsonl').exists():
            reader = Reader(directory / 'normalized.jsonl')
            reader.sample()
            paused_rows = []
            with (directory / 'opportunities.jsonl').open('w') as stream:
                for key, req in reader.opportunities.items():
                    row = {'opportunity_id': req['opportunity_id'], 'request_key': list(key),
                           'opportunity_at': req['opportunity_at'], 'observed': reader.observed[key],
                           'state_ready': None, 'decision_end': None, 'first_input': None,
                           'last_input': None, 'confirm': None, 'ended_at': time.monotonic(),
                           'status': 'timeout' if isinstance(exc, TimeoutError) else
                                     'cancelled' if isinstance(exc, InterruptedError) else 'paused',
                           'action': None, 'reason': str(exc)}
                    stream.write(json.dumps(row) + '\n')
                    paused_rows.append(row)
            report = {**report, **summarize(paused_rows, None),
                      'NATIVE_HARNESS': 'BLOCKED_NATIVE', 'LATENCY': 'NOT_MEASURED',
                      'startup_failed_ms': (time.monotonic() - start) * 1000,
                      'rows': len(paused_rows)}
    finally:
        if adapter:
            adapter.release()
        if process:
            (directory / 'stop').touch()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait(timeout=3)
            report['harness_exit_code'] = process.returncode
        report['total_run_ms'] = (time.monotonic() - start) * 1000
        if reader is not None:
            # Preserve reducer last_valid/first_error on failure, as well as
            # the control-layer reason. No stale projection is action-ready.
            diagnostic = reader.reducer.document()
            diagnostic['input_authorized_now'] = False  # this run has ended
            atomic(directory / 'state-diagnostic.json', diagnostic)
            report['state_diagnostic'] = 'state-diagnostic.json'
        atomic(directory / 'report.json', report)
    return report
