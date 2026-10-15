"""Bounded synthetic, instrumented local delivery qualification. No live source.

Controller timestamps alone define write -> observed validated consumer result.
Child clocks are used only for their own duration fields. No production module
is changed; probes load through sitecustomize in a controller-owned temp dir.
"""
import argparse
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import queue
import subprocess
import sys
import tempfile
import threading
import time

from mtgaplayer.live_performance import quantiles
from mtgaplayer.raw_log import _key
from delivery_probe import binding_tag

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = Path(__file__).resolve().parent
FIXTURE = ROOT / 'tests/fixtures/player_log_minimal.jsonl'
STAGES = ('poll_read_ns', 'reducer_apply_ns', 'decision_state_assembly_ns',
          'event_publication_ns', 'poll_to_publish_ns', 'consumer_validate_cache_ns', 'probe_view_copy_ns')
OUTPUT_LIMIT = 8 * 1024 * 1024


class QualificationError(Exception):
    pass


def encoded(rows):
    return ''.join(json.dumps(row, separators=(',', ':')) + '\n' for row in rows).encode()


def baseline():
    return [json.loads(line) for line in FIXTURE.read_text(encoding='utf-8').splitlines()][:3]


def request(ident, state_id):
    """Explicit synthetic Pass body in the existing scrubbed own envelope."""
    return {'greToClientEvent': {'greToClientMessages': [{
        'type': 'GREMessageType_ActionsAvailableReq', 'systemSeatIds': [1],
        'msgId': ident, 'gameStateId': state_id,
        'actionsAvailableReq': {'actions': [{'actionType': 'ActionType_Pass'}]}}]}}


def reply(ident, state_id):
    return {'payload': {'type': 'ClientMessageType_PerformActionResp',
                        'respId': ident, 'gameStateId': state_id}}


def advance(state_id, previous):
    return {'greToClientEvent': {'greToClientMessages': [{
        'type': 'GREMessageType_GameStateMessage', 'systemSeatIds': [1],
        'gameStateMessage': {'type': 'GameStateType_Diff', 'gameStateId': state_id,
            'prevGameStateId': previous, 'turnInfo': {'decisionPlayer': 1, 'turnNumber': state_id}}}]}}


def full(state_id, objects=0):
    value = copy.deepcopy(baseline()[2])
    gs = value['greToClientEvent']['greToClientMessages'][0]['gameStateMessage']
    gs['gameStateId'] = state_id
    if objects:
        ids = list(range(10_000, 10_000 + objects))
        next(z for z in gs['zones'] if z['zoneId'] == 31)['objectInstanceIds'] = ids
        gs['gameObjects'] = [{'instanceId': ident, 'grpId': 1000 + index,
            'type': 'GameObjectType_Card', 'zoneId': 31, 'visibility': 'Visibility_Private',
            'ownerSeatId': 1, 'controllerSeatId': 1, 'viewers': [1]} for index, ident in enumerate(ids)]
    return value


def expected_tag(generation, state_id, request_id):
    gs = baseline()[2]['greToClientEvent']['greToClientMessages'][0]['gameStateMessage']
    return binding_tag({'source_generation': generation, 'match': _key(gs['gameInfo']['matchID']),
        'game': 1, 'self_seat': 1, 'game_state_id': state_id, 'request_id': request_id,
        'request_type': None if request_id is None else 'GREMessageType_ActionsAvailableReq'})


def version():
    paths = ('scripts/qualify_delivery.py', 'scripts/qualify_backpressure.py', 'scripts/delivery_probe.py',
             'tests/test_delivery_qualification.py', 'tests/test_consumer_backpressure.py',
             'src/mtgaplayer/raw_log.py', 'src/mtgaplayer/cli.py', 'src/mtgaplayer/decision_state.py',
             'src/mtgaplayer/decision_publisher.py', 'src/mtgaplayer/decision_consumer.py')
    def git(*args):
        return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()
    return {'head': git('rev-parse', 'HEAD'), 'tree': git('rev-parse', 'HEAD^{tree}'),
        'tracked_dirty': bool(git('status', '--porcelain', '--untracked-files=no')),
        'source_sha256': {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in paths if (ROOT / p).is_file()}}


class Session:
    """Two actual -m CLI processes, direct OS pipe, bounded controller readers."""

    def __init__(self, directory, interval, samples, silence_ms=1500, probed=True, pause_file=None,
                 event_probes=True, consumer_role=None, consumer_options=None, age_ms=30000):
        self.directory, self.interval = Path(directory), interval
        self.path = self.directory / 'synthetic.jsonl'
        self.path.write_bytes(encoded(baseline() + [request(40, 1)]))
        self.generation, self.state_id, self.request_id, self.next_request = 1, 1, 40, 41
        self.inbox = queue.Queue(8192)
        self.records, self.events, self.diagnostics, self.polls = [], [], [], {}
        self.output_bytes = 0
        self.failure = None
        self.gate, self.paused = threading.Event(), threading.Event()
        self.gate.set()
        self.reader_stop = threading.Event()
        self.lock = threading.Lock()
        self.probed = probed
        self.event_probes = probed and event_probes
        self.event_kinds = {}
        self.producer_gated = False
        self.terminal_view = None
        self.internal = []
        self.threads = []
        self.processes = []
        env = os.environ.copy()
        if probed:
            hook = self.directory / 'sitecustomize.py'
            hook.write_text('import sys\nsys.path.insert(0, ' + repr(str(SCRIPTS)) + ')\n'
                            'from delivery_probe import install\ninstall()\n', encoding='utf-8')
            env['PYTHONPATH'] = str(self.directory) + os.pathsep + env.get('PYTHONPATH', '')
        self.producer_argv = [sys.executable, '-m', 'mtgaplayer', 'watch', str(self.path),
            '--decision-events', '--samples', str(samples), '--interval', str(interval)]
        self.consumer_argv = [sys.executable, '-m', 'mtgaplayer', 'consume-events',
            '--max-event-silence-ms', str(silence_ms), '--max-observation-age-ms', str(age_ms)]
        self.started = time.perf_counter_ns()
        try:
            producer_env = {**env, 'MTGAPLAYER_DELIVERY_PROBE_ROLE': 'producer'}
            producer_env.pop('MTGAPLAYER_DELIVERY_PAUSE_FILE', None)
            if pause_file is not None:
                producer_env['MTGAPLAYER_DELIVERY_PAUSE_FILE'] = str(pause_file)
            self.producer = subprocess.Popen(self.producer_argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                             cwd=ROOT, env=producer_env)
            self.processes.append(self.producer)
            consumer_env = {**env, 'MTGAPLAYER_DELIVERY_PROBE_ROLE':
                            consumer_role or ('consumer' if self.event_probes else 'consumer_terminal')}
            consumer_env['MTGAPLAYER_CONSUMER_TEST_OPTIONS'] = json.dumps(consumer_options or {})
            if consumer_role == 'consumer_internal':
                consumer_env['MTGAPLAYER_TEST_SLOW_ACCEPT_FILE'] = str(self.directory / 'input_overflow.trigger')
                consumer_env['MTGAPLAYER_TEST_CANCEL_FILE'] = str(self.directory / 'cancel.trigger')
            self.consumer = subprocess.Popen(self.consumer_argv, stdin=self.producer.stdout,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=ROOT, env=consumer_env)
            self.processes.append(self.consumer)
            self.producer.stdout.close()  # The consumer is the only pipe reader.
            for name, stream in (('producer', self.producer.stderr), ('consumer', self.consumer.stdout),
                                 ('consumer_stderr', self.consumer.stderr)):
                thread = threading.Thread(target=self._read, args=(name, stream), daemon=True)
                self.threads.append(thread)
                thread.start()
        except BaseException:
            self.cleanup()
            raise

    def _read(self, name, stream):
        try:
            while not self.reader_stop.is_set():
                if name == 'consumer' and not self.gate.is_set():
                    self.paused.set()
                    self.gate.wait(2)
                    if not self.gate.is_set():
                        self.failure = 'controller_pause_limit'
                        return
                line = stream.readline(2 * 1024 * 1024 + 1)
                observed = time.perf_counter_ns()
                if not line:
                    return
                with self.lock:
                    self.output_bytes += len(line)
                    if self.output_bytes > OUTPUT_LIMIT:
                        self.failure = 'controller_output_limit'
                        return
                try:
                    value = json.loads(line)
                except (ValueError, UnicodeError):
                    if name == 'consumer':
                        self.failure = 'invalid_consumer_output'
                        return
                    value = {'non_json_stderr': True}
                try:
                    self.inbox.put_nowait((name, value, observed))
                except queue.Full:
                    self.failure = 'controller_queue_overflow'
                    return
        except (OSError, ValueError):
            if not self.reader_stop.is_set():
                self.failure = 'controller_read_error'

    def pump(self, timeout=.05):
        if self.failure:
            raise QualificationError(self.failure)
        try:
            name, value, observed = self.inbox.get(timeout=timeout)
        except queue.Empty:
            return
        if value.get('_delivery_poll'):
            for sequence in value['sequences']:
                self.polls[sequence] = value
            self.event_kinds.update(zip(value['sequences'], value['event_types']))
        elif value.get('_delivery_gate'):
            self.producer_gated = True
        elif value.get('_delivery_ack'):
            if (value['sequence'] != len(self.events) + 1 or not value['accepted'] or
                    value['last_sequence'] != value['sequence'] or not value['flags_safe']):
                raise QualificationError('event_order_or_cache_validation')
            value['observed_ns'] = observed
            self.events.append(value)
        elif value.get('_delivery_terminal_view'):
            if value['has_state'] or value['has_reference']:
                raise QualificationError('terminal_cache_not_cleared')
            self.terminal_view = value
        elif value.get('_consumer_internal'):
            value['observed_ns'] = observed
            self.internal.append(value)
        elif name == 'consumer' and 'consumer_status' in value:
            value['observed_ns'] = observed
            self.diagnostics.append(value)

    def wait(self, predicate, timeout=3):
        deadline = time.perf_counter() + timeout
        while not predicate():
            if self.failure:
                raise QualificationError(self.failure)
            if time.perf_counter() >= deadline:
                raise QualificationError('sample_timeout')
            self.pump(min(.05, max(0, deadline - time.perf_counter())))
        return predicate()

    def startup(self):
        if not self.event_probes:
            self.wait(lambda: next((d for d in self.diagnostics if d['consumer_status'] == 'OBSERVING'), None))
            return
        live = self.wait(lambda: next((e for e in self.events if e['event_type'] == 'liveness'), None))
        first = self.events[0]
        if (first['event_type'] != 'snapshot' or first['phase'] != 'history' or
                first['new_request_observed'] or first['binding_tag'] != expected_tag(1, 1, 40)):
            raise QualificationError('startup_history_not_isolated')
        self.records.append({'phase': 'startup', 'category': 'first_history_snapshot', 'outcome': 'verified',
            'launch_to_history_ack_ns': first['observed_ns'] - self.started,
            'input_changes': 0, 'event_order': [e['event_type'] for e in self.events[:2]],
            'event_sequences': [e['sequence'] for e in self.events[:2]],
            'label': 'process_launch_to_history_ack_not_incremental_write_latency'})
        return live

    def write(self, payload, mode='append'):
        before = time.perf_counter_ns()
        if mode == 'replace':
            replacement = self.directory / 'replacement.jsonl'
            replacement.write_bytes(payload)
            os.replace(replacement, self.path)
            after = time.perf_counter_ns()
        else:
            with self.path.open('ab' if mode == 'append' else 'wb', buffering=0) as stream:
                if stream.write(payload) != len(payload):
                    raise QualificationError('short_controlled_write')
                stream.flush()
                after = time.perf_counter_ns()
        return before, after, self.path.stat().st_size

    def change(self, category, rows=None, payload=None, reason=None, state_id=None,
               request_id=None, mode='append', phase='steady', new_request=None, input_changes=1):
        previous_ref = self.events[-1]['reference_sequence']
        payload = encoded(rows) if payload is None else payload
        before, flushed, target = self.write(payload, mode)
        generation = self.generation
        tag = None if state_id is None else expected_tag(generation, state_id, request_id)
        record = {'phase': phase, 'category': category, 'outcome': 'pending',
            'input_changes': input_changes, 'input_bytes': len(payload),
            'target_offset': target, 'source_generation': generation,
            'previous_reference_sequence': previous_ref,
            't_before_write_ns': before, 't_after_flush_ns': flushed}
        self.records.append(record)  # Failures are retained in the denominator.
        try:
            def find():
                for event in self.events:
                    poll = self.polls.get(event['sequence'])
                    if (event['event_type'] == 'liveness' and poll and poll['offset'] == target and
                            poll['generation'] == generation and event['observed_ns'] >= before):
                        return event
                return None
            live = self.wait(find)
            sequences = self.polls[live['sequence']]['sequences']
            group = [e for e in self.events if e['sequence'] in sequences]
            invalidations = [e for e in group if e['event_type'] == 'invalidate']
            snapshots = [e for e in group if e['event_type'] == 'snapshot']
            record.update(event_order=[e['event_type'] for e in group],
                consumer_statuses=[e['status'] for e in group], event_sequences=sequences,
                snapshot_count=len(snapshots), invalidate_count=len(invalidations),
                final_status=live['status'])
            if reason:
                if (len(invalidations) != 1 or invalidations[0]['reason'] != reason or
                        invalidations[0]['revoked_sequence'] != previous_ref or
                        invalidations[0]['reference_sequence'] is not None or invalidations[0]['has_state']):
                    raise QualificationError('incorrect_revocation')
            elif invalidations:
                raise QualificationError('unexpected_revocation')
            if live['binding_tag'] != tag or (tag is None and live['has_state']):
                raise QualificationError('unassociated_result')
            if new_request is not None and live['new_request_observed'] is not new_request:
                raise QualificationError('incorrect_opportunity')
            ack = snapshots[-1] if snapshots else invalidations[0] if invalidations else live
            record.update(outcome='verified', t_consumer_ack_observed_ns=ack['observed_ns'],
                write_to_ack_ns=ack['observed_ns'] - before,
                flush_to_ack_ns=ack['observed_ns'] - flushed,
                event_order=[e['event_type'] for e in group],
                consumer_statuses=[e['status'] for e in group],
                event_sequences=sequences, final_status=live['status'],
                snapshot_count=len(snapshots), invalidate_count=len(invalidations),
                correct_revocation=bool(invalidations),
                invalidation_ns=None if not invalidations else invalidations[0]['observed_ns'] - before)
            if mode != 'append' and snapshots and (snapshots[0]['phase'] != 'history' or snapshots[0]['new_request_observed']):
                raise QualificationError('reset_not_history')
            self.state_id, self.request_id = state_id, request_id
            return group
        except QualificationError as exc:
            record.update(outcome=str(exc))
            raise

    def new(self, phase='setup'):
        ident = self.next_request
        self.next_request += 1
        self.change('new_request', [request(ident, self.state_id)], reason='request_replaced',
            state_id=self.state_id, request_id=ident, new_request=True, phase=phase)
        return ident

    def finish(self, timeout):
        self.wait(lambda: next((d for d in self.diagnostics if d['consumer_status'] in
                  ('CLOSED', 'PROTOCOL_ERROR', 'STALE')), None), timeout)
        self.producer.wait(timeout=2)
        self.consumer.wait(timeout=2)
        # Drain confirmations preceding EOF before producing final counts.
        for thread in self.threads:
            thread.join(timeout=1)
        while not self.inbox.empty():
            self.pump(0)
        if self.failure:
            raise QualificationError(self.failure)
        if self.probed and self.terminal_view is None:
            raise QualificationError('terminal_view_not_confirmed')
        consumed_sequences = sorted({d['last_sequence'] for d in self.diagnostics if d.get('last_sequence', 0) > 0})
        if (consumed_sequences and consumed_sequences != list(range(1, consumed_sequences[-1] + 1))
                and self.diagnostics[-1].get('diagnostics_complete', True)):
            raise QualificationError('diagnostic_sequence_gap')
        consumed_kinds = ([e['event_type'] for e in self.events] if self.event_probes else
                          [self.event_kinds.get(seq) for seq in consumed_sequences])
        return {'producer_exit': self.producer.returncode, 'consumer_exit': self.consumer.returncode,
            'consumer_status': self.diagnostics[-1]['consumer_status'],
            'reason': self.diagnostics[-1]['unresolved'], 'output_bytes': self.output_bytes,
            'last_sequence': self.diagnostics[-1].get('last_sequence'),
            'final_cached_state_present': None if self.terminal_view is None else self.terminal_view['has_state'],
            'terminal_view_confirmation': self.terminal_view,
            'snapshot_count': consumed_kinds.count('snapshot'),
            'invalidate_count': consumed_kinds.count('invalidate')}

    def cleanup(self):
        self.gate.set()
        for process in self.processes:
            if process.poll() is None:
                process.kill()
        for process in self.processes:
            process.wait(timeout=3)
        self.reader_stop.set()
        for thread in self.threads:
            thread.join(timeout=2)
        for process in self.processes:
            for stream in (process.stdout, process.stderr):
                if stream is not None:
                    stream.close()

    def safe_trace(self):
        # Binding digests are association-only memory, never retained in output.
        return [{**{k: v for k, v in e.items() if k not in ('binding_tag', '_delivery_ack')},
                 'poll': self.polls.get(e['sequence'])} for e in self.events]


def distribution(records, field):
    return quantiles([r[field] / 1_000_000 for r in records if r['outcome'] == 'verified' and r.get(field) is not None])


def summarize(records):
    groups = {}
    for record in records:
        key = record['phase'] + '/' + record['category']
        groups.setdefault(key, []).append(record)
    return {key: {'attempts': len(rows), 'verified': sum(r['outcome'] == 'verified' for r in rows),
        'input_changes': sum(r['input_changes'] for r in rows),
        'snapshot_count': sum(r.get('snapshot_count', 0) for r in rows),
        'invalidate_count': sum(r.get('invalidate_count', 0) for r in rows),
        'outcomes': {outcome: sum(r['outcome'] == outcome for r in rows) for outcome in sorted({r['outcome'] for r in rows})},
        'write_to_observed_ms': distribution(rows, 'write_to_ack_ns'),
        'flush_to_observed_ms': distribution(rows, 'flush_to_ack_ns'),
        'launch_to_history_ms': distribution(rows, 'launch_to_history_ack_ns'),
        'invalidation_observed_ms': distribution(rows, 'invalidation_ns')} for key, rows in groups.items()}


def normal(directory, count, interval):
    session = Session(directory, interval, min(1000, count * 3 + 100))
    try:
        session.startup()
        session.change('warmup_consumption', [reply(40, 1)], reason='request_consumed',
                       state_id=1, phase='setup', new_request=False)
        for index in range(count):
            kind = index % 4
            if kind in (0, 1):
                ident = session.next_request
                session.next_request += 1
                session.change('new_request' if kind == 0 else 'request_replaced',
                    [request(ident, session.state_id)], reason='request_replaced',
                    state_id=session.state_id, request_id=ident, new_request=True)
            elif kind == 2:
                session.change('request_consumed', [reply(session.request_id, session.state_id)],
                    reason='request_consumed', state_id=session.state_id, new_request=False)
            else:
                session.change('state_advanced', [advance(session.state_id + 1, session.state_id)],
                    reason='state_advanced', state_id=session.state_id + 1, new_request=False)
        # Dedicated invalidation/recovery paths are not mixed into steady latency.
        session.new()
        state_id = session.state_id
        session.change('continuity_error', [advance(state_id + 1, 999999)], reason='source_invalid', phase='fault')
        session.change('full_recovery', [full(state_id + 1)], state_id=state_id + 1, phase='recovery', new_request=False)
        ident = session.new()
        body = encoded([reply(ident, session.state_id)])
        state_id = session.state_id
        session.change('partial_record', payload=body[:19], reason='source_partial', phase='fault')
        session.change('partial_completion', payload=body[19:], state_id=state_id, phase='recovery', new_request=False)
        session.change('old_request_retransmission', [request(ident, state_id)], state_id=state_id,
                       phase='recovery', new_request=False)
        session.new()
        session.generation += 1
        session.change('file_truncate', baseline(), mode='truncate', reason='source_reset',
                       state_id=1, phase='reset', new_request=False)
        session.new()
        session.generation += 1
        session.change('file_replace', baseline(), mode='replace', reason='source_reset',
                       state_id=1, phase='reset', new_request=False)
        # One GRE frame contains three requests: only the final one is promised.
        ids = list(range(session.next_request, session.next_request + 3))
        combined = request(ids[0], 1)
        combined['greToClientEvent']['greToClientMessages'].extend(
            request(i, 1)['greToClientEvent']['greToClientMessages'][0] for i in ids[1:])
        group = session.change('same_poll_three_requests', [combined], reason='request_replaced',
            state_id=1, request_id=ids[-1], new_request=True, phase='burst', input_changes=3)
        if sum(e['event_type'] == 'snapshot' for e in group) != 1:
            raise QualificationError('poll_coalescing_miscount')
        session.next_request += 3
        # Multiple contiguous GRE Diff records in one controlled OS write.
        group = session.change('multiple_records', [advance(i, i - 1) for i in range(2, 7)],
            reason='state_advanced', state_id=6, phase='burst', input_changes=5, new_request=False)
        session.change('large_full_200_objects', [full(7, 200)], reason='state_advanced',
                       state_id=7, phase='large_frame', new_request=False)
        empty_start = len(session.events)
        session.wait(lambda: len(session.events) >= empty_start + 3)
        empty = session.events[empty_start:empty_start + 3]
        if any(e['event_type'] != 'liveness' for e in empty):
            raise QualificationError('idle_poll_changed_cache')
        session.records.append({'phase': 'idle', 'category': 'unchanged_polls', 'outcome': 'verified',
                                'input_changes': 0, 'polls': 3,
                                'event_sequences': [e['sequence'] for e in empty]})
        before_stop = time.perf_counter_ns()
        terminal = session.finish(max(5, (count * 3 + 100) * interval + 3))
        if terminal['producer_exit'] != 0 or terminal['consumer_exit'] != 0 or terminal['reason'] != ['sample_limit']:
            raise QualificationError('normal_stop_failed')
        stop_ack = next(e for e in session.events if e['event_type'] == 'invalidate' and e['reason'] == 'session_stopped')
        last_observing = next(e for e in reversed(session.events)
                              if e['sequence'] < stop_ack['sequence'] and e['status'] == 'OBSERVING')
        closed_ack = session.events[-1]
        session.records.append({'phase': 'termination', 'category': 'normal_stopped', 'outcome': 'verified',
            'input_changes': 0, 'trigger': 'natural_watch_sample_limit',
            'observed_ns': stop_ack['observed_ns'], 'wait_started_ns': before_stop,
            'last_observing_to_invalidation_ns': stop_ack['observed_ns'] - last_observing['observed_ns'],
            'invalidation_to_closed_ns': closed_ack['observed_ns'] - stop_ack['observed_ns'],
            'note': 'observation gaps only; exact producer-stop trigger latency unknown; no controlled write'})
        phases = {sequence: record['phase'] for record in session.records
                  for sequence in record.get('event_sequences', ())}
        stages = {}
        for event in session.events:
            phase = phases.get(event['sequence'], 'termination' if event['reason'] == 'session_stopped'
                               or event['event_type'] == 'stopped' else 'empty_poll')
            bucket = stages.setdefault(phase, {name: [] for name in STAGES})
            if event['event_type'] == 'liveness':
                for name in STAGES[:5]:
                    if event['timing'][name] is not None:
                        bucket[name].append(event['timing'][name] / 1_000_000)
            for name in STAGES[5:]:
                bucket[name].append(event[name] / 1_000_000)
        return session.records, terminal, {phase: {name: quantiles(values) for name, values in bucket.items()}
                                          for phase, bucket in stages.items()}, session.safe_trace()
    except (QualificationError, OSError, subprocess.TimeoutExpired) as exc:
        reason = str(exc) if isinstance(exc, QualificationError) else 'subprocess_or_IO_error'
        if not session.records or session.records[-1].get('outcome') == 'verified':
            session.records.append({'phase': 'run', 'category': 'failure', 'outcome': reason, 'input_changes': 0})
        return session.records, {'failure': reason, 'producer_exit': session.producer.poll(),
                                 'consumer_exit': session.consumer.poll()}, {}, session.safe_trace()
    finally:
        session.cleanup()


def termination(directory, interval):
    session = Session(directory, interval, 1000)
    try:
        session.startup()
        triggered = time.perf_counter_ns()
        session.producer.kill()
        terminal = session.finish(3)
        if terminal['consumer_exit'] != 1 or terminal['reason'] != ['unexpected_eof']:
            raise QualificationError('abnormal_exit_not_invalidated')
        terminal.update(trigger_to_observed_ms=(session.diagnostics[-1]['observed_ns'] - triggered) / 1_000_000,
                        trigger='controller_kill_to_EOF_observed')
        return terminal
    finally:
        session.cleanup()


def silence(directory):
    """Real producer + consumer pipe: suspend producer without closing handles."""
    # Portable bounded test uses a test-only producer print gate. stdout stays
    # open, so consumer local silence rather than EOF must expire the cache.
    gate_path = Path(directory) / 'producer-gate'
    gate_path.touch()
    session = Session(directory, .01, 1000, silence_ms=150, pause_file=gate_path)
    try:
        session.startup()
        triggered = time.perf_counter_ns()
        gate_path.unlink()
        session.wait(lambda: session.producer_gated, 1)
        session.wait(lambda: next((d for d in session.diagnostics if d['consumer_status'] == 'STALE'), None), 3)
        session.wait(lambda: session.terminal_view, 1)
        session.consumer.wait(timeout=2)
        if session.diagnostics[-1]['unresolved'] != ['event_silence_expired']:
            raise QualificationError('silence_not_expired')
        return {'consumer_exit': session.consumer.returncode, 'producer_alive_at_expiry': session.producer.poll() is None,
            'reason': session.diagnostics[-1]['unresolved'],
            'trigger_to_observed_ms': (session.diagnostics[-1]['observed_ns'] - triggered) / 1_000_000,
            'trigger': 'test_producer_gate_closed_to_local_lease_observed', 'lease_ms': 150,
            'interval_seconds': .01, 'terminal_view_confirmation': session.terminal_view,
            'final_cached_state_present': session.terminal_view['has_state']}
    finally:
        session.cleanup()


def backpressure(directory):
    # No per-event probe output: fill the pipe with production diagnostics only.
    # The additional cache confirmation is emitted *after* terminal diagnostics.
    session = Session(directory, .001, 1000, silence_ms=1000, event_probes=False)
    try:
        session.startup()
        session.gate.clear()
        if not session.paused.wait(1):
            raise QualificationError('backpressure_not_established')
        before, flushed, _ = session.write(encoded([request(41, 1)]))
        time.sleep(.5)  # Bounded unread stdout; at most 1000 producer polls.
        resumed = time.perf_counter_ns()
        session.gate.set()
        terminal = session.finish(4)
        final = terminal['consumer_status']
        if final not in ('PROTOCOL_ERROR', 'STALE', 'CLOSED'):
            raise QualificationError('backpressure_unsafe_final_cache')
        return {**terminal, 'pause_ms': (resumed - before) / 1_000_000,
            'interval_seconds': .001,
            'consumer_per_event_probe_enabled': False,
            'preterminal_stdout': 'unchanged_production_CLI_diagnostics',
            'write_flush_ms': (flushed - before) / 1_000_000,
            'resume_to_terminal_ms': (session.diagnostics[-1]['observed_ns'] - resumed) / 1_000_000,
            'timely_invalidation_while_output_blocked': 'not_guaranteed',
            'bounded_by': {'pause_seconds': .5, 'max_polls': 1000, 'output_bytes_limit': OUTPUT_LIMIT,
                           'post_resume_deadline_seconds': 4},
            'outcome': 'verified_fail_closed_after_resume' if final != 'CLOSED' else 'normal_completion_after_resume'}
    finally:
        session.cleanup()


def qualify(count=200, interval=.01):
    report = {'result': 'MEASUREMENT_BLOCKED', 'code': version(),
        'environment': {'python': platform.python_version(), 'venv': sys.prefix != sys.base_prefix,
                        'project_venv': Path(sys.prefix).resolve() == (ROOT / '.venv').resolve(),
                        'os': platform.platform()},
        'test_type': 'synthetic_local_instrumented_OS_pipe',
        'fixture_classes': ['committed_scrubbed_auth_room_full', 'explicit_synthetic_GRE_variants'],
        'interval_seconds': interval, 'requested_steady_samples': count,
        'boundaries': {'write_to_observed': 'controller before write -> controller reads consumer post-cache probe ack',
            'flush_to_observed': 'controller flush return -> same ack read; no fsync/disk persistence claim',
            'invalidation': 'controller before invalidating write -> actual validated INVALIDATED ack read',
            'startup': 'controller before producer launch -> first history snapshot ack read; separate from increments',
            'cold_start_scope': 'fresh Python processes; filesystem and OS caches are not flushed',
            'clock': 'controller perf_counter_ns only for external deltas; child durations never cross-subtracted',
            'overhead': 'temporary sitecustomize probes, extra cached-view copy and confirmation stdout included'},
        'limits': {'max_output_bytes_per_pair': OUTPUT_LIMIT, 'controller_queue_items': 8192,
                   'max_watch_polls': 1000, 'normal_consumer_silence_ms': 1500,
                   'normal_consumer_observation_ms': 30000},
        'unknown_stages': ['producer_JSON_serialization_stdout', 'consumer_receive_to_decode_queue_wait',
                           'consumer_ack_serialization_stdout', 'controller_decode_and_association',
                           'server_to_log', 'upstream_source_buffering'],
        'read_only': True, 'execution_ready': False, 'input_sent': False, 'private_source_reads': 0}
    records = []
    with tempfile.TemporaryDirectory(prefix='delivery-qualification-') as root:
        def directory(name):
            path = Path(root) / name
            path.mkdir()
            return path
        try:
            records, terminal, stages, trace = normal(directory('normal'), count, interval)
        except (QualificationError, OSError, subprocess.TimeoutExpired):
            records = [{'phase': 'run', 'category': 'failure', 'outcome': 'normal_launch_or_IO_failure', 'input_changes': 0}]
            terminal, stages, trace = {'failure': 'normal_launch_or_IO_failure'}, {}, []
        report['normal_terminal'], report['stages_ms'] = terminal, stages
        def smoke_run():
            smoke = Session(directory('smoke'), interval, 3, probed=False)
            try:
                smoke.startup()
                result = smoke.finish(5)
                if result['producer_exit'] or result['consumer_exit']:
                    raise QualificationError('unmodified_CLI_smoke_failed')
                return result
            finally:
                smoke.cleanup()
        report['scenario_outcomes'] = {}
        for category, operation in (
                ('unmodified_CLI_smoke', smoke_run),
                ('abnormal_exit', lambda: termination(directory('abnormal'), interval)),
                ('silent_open_pipe', lambda: silence(directory('silence'))),
                ('backpressure', lambda: backpressure(directory('backpressure')))):
            try:
                report[category] = operation()
                report['scenario_outcomes'][category] = 'verified'
            except (QualificationError, OSError, subprocess.TimeoutExpired) as exc:
                report['scenario_outcomes'][category] = str(exc) if isinstance(exc, QualificationError) else 'subprocess_or_IO_error'
    report['groups'] = summarize(records)
    steady = [r for r in records if r['phase'] == 'steady']
    failures = [r for r in records if r['outcome'] != 'verified']
    report['counts'] = {'steady_attempted': len(steady), 'steady_verified': sum(r['outcome'] == 'verified' for r in steady),
        'steady_not_attempted_after_failure': max(0, count - len(steady)),
        'all_recorded_attempts': len(records), 'failure_records': len(failures),
        'timeouts': sum(r['outcome'] == 'sample_timeout' for r in records),
        'unassociated': sum(r['outcome'] == 'unassociated_result' for r in records),
        'wrong_revocations': sum(r['outcome'] in ('incorrect_revocation', 'unexpected_revocation') for r in records),
        'event_order_errors': sum(r['outcome'] == 'event_order_or_cache_validation' for r in records)}
    report['counts']['scenario_failures'] = sum(value != 'verified' for value in report['scenario_outcomes'].values())
    report['counts']['scenario_attempts'] = len(report['scenario_outcomes'])
    report['counts']['scenario_timeouts'] = sum(value == 'sample_timeout' for value in report['scenario_outcomes'].values())
    report['counts']['timeouts'] += report['counts']['scenario_timeouts']
    report['counts']['normal_exit_errors'] = int(terminal.get('producer_exit') != 0 or terminal.get('consumer_exit') != 0)
    report['normal_stop_observation'] = next((r for r in records if r['category'] == 'normal_stopped'), None)
    report['steady_write_to_observed_ms'] = distribution(steady, 'write_to_ack_ns')
    report['steady_flush_to_observed_ms'] = distribution(steady, 'flush_to_ack_ns')
    report['explicit_invalidation_observed_ms'] = distribution(records, 'invalidation_ns')
    if not failures and len(steady) == count and 'failure' not in terminal and not report['counts']['scenario_failures']:
        report['result'] = 'QUALIFIED_LOCAL_READONLY'
    return report, records, trace


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--samples', type=int, default=200)
    parser.add_argument('--interval', type=float, default=.01)
    parser.add_argument('--output', type=Path, default=ROOT / 'artifacts/local-mp18-phase4/qualification.json')
    args = parser.parse_args(argv)
    if not 4 <= args.samples <= 250 or args.samples % 4 or not math.isfinite(args.interval) or not .001 <= args.interval <= .25:
        parser.error('samples must be a multiple of four in 4..248; interval .001.. .25 seconds')
    report, records, trace = qualify(args.samples, args.interval)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    args.output.with_name(args.output.stem + '-samples.jsonl').write_text(
        ''.join(json.dumps(row) + '\n' for row in records), encoding='utf-8')
    args.output.with_name(args.output.stem + '-events.jsonl').write_text(
        ''.join(json.dumps(row) + '\n' for row in trace), encoding='utf-8')
    print(json.dumps(report, indent=2))
    return 0 if report['result'] == 'QUALIFIED_LOCAL_READONLY' else 1


if __name__ == '__main__':
    raise SystemExit(main())
