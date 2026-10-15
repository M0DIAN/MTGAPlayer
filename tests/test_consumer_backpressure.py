"""Counterexamples for output/core independence; no game or native input."""
import copy
import io
import inspect
import queue
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from mtgaplayer.cli import _emit_consumer_diagnostic
from mtgaplayer.decision_consumer import DecisionConsumer, _DiagnosticOutput, consume_events
from mtgaplayer.decision_publisher import DecisionPublisher
import test_decision_consumer as consumer_fixtures
from test_decision_consumer import encoded

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from qualify_backpressure import run_case


class QueueStream:
    def __init__(self):
        self.lines = queue.Queue()
    def readline(self, size):
        return self.lines.get()
    def send(self, event):
        self.lines.put(encoded([event]))


class ConsumerBackpressureTests(unittest.TestCase):
    setUp = consumer_fixtures.DecisionConsumerTests.setUp

    def blocked_run(self, consumer=None, emit_error=None, **options):
        consumer = consumer or DecisionConsumer(2_000_000_000, 2_000_000_000)
        stream, gate, entered, cleared = QueueStream(), threading.Event(), threading.Event(), threading.Event()
        output, transitions, accepted, result = [], [], [], []
        original_clear, original_accept = consumer._clear, consumer.accept_event
        def clear(status, reason):
            original_clear(status, reason)
            transitions.append((status, reason, consumer._state, consumer._ref, threading.get_ident()))
            if status in ('CLOSED', 'STALE', 'PROTOCOL_ERROR'):
                cleared.set()
        def accept(event, **kwargs):
            value = original_accept(event, **kwargs)
            accepted.append((event['sequence'], value))
            return value
        def emit(value):
            entered.set()
            gate.wait(3)
            if emit_error is not None:
                raise emit_error
            output.append(value)
        def run():
            try:
                result.append(consume_events(stream, emit, consumer, tick_seconds=.002, **options))
            except BaseException as exc:
                result.append(exc)
        consumer._clear, consumer.accept_event = clear, accept
        stream.send(self.snapshot)
        core = threading.Thread(target=run, name='test-consumer-core')
        core.start()
        def cleanup():
            gate.set()
            stream.lines.put('')
            core.join(3)
            for thread in threading.enumerate():
                if thread.name == 'decision-diagnostic-writer':
                    thread.join(1)
        self.addCleanup(cleanup)
        self.assertTrue(entered.wait(1))
        return consumer, stream, gate, cleared, output, transitions, accepted, result, core

    def wait_for(self, predicate):
        deadline = time.monotonic() + 1
        while not predicate() and time.monotonic() < deadline:
            time.sleep(.002)
        self.assertTrue(predicate())

    def test_strict_events_and_protocol_error_while_emit_blocked(self):
        c, stream, gate, clear, output, transitions, accepted, result, core = self.blocked_run()
        stream.send(self.live)
        self.wait_for(lambda: len(accepted) == 2)
        bad = copy.deepcopy(self.live)
        bad['sequence'] = 4
        stream.send(bad)
        self.assertTrue(clear.wait(1))
        self.assertFalse(gate.is_set())
        self.assertEqual(accepted, [(1, True), (2, True), (4, False)])
        self.assertEqual(transitions[-1][:4], ('PROTOCOL_ERROR', 'invalid_event_or_stream_order', None, None))
        self.assertEqual(transitions[-1][4], core.ident)
        gate.set()
        core.join(2)
        self.assertEqual(result, [1])
        self.assertEqual(output[-1]['unresolved'], ['invalid_event_or_stream_order'])

    def test_age_expires_with_recent_liveness_without_observer_tick(self):
        c, stream, gate, clear, output, transitions, accepted, result, core = self.blocked_run(self.consumer)
        self.clock.advance(100)
        stream.send(self.live)
        self.wait_for(lambda: len(accepted) == 2)
        self.clock.advance(401)  # Age=501, silence=401; original leases unchanged.
        self.assertTrue(clear.wait(1))
        self.assertEqual(transitions[-1][:4], ('STALE', 'observation_age_expired', None, None))
        self.assertEqual(transitions[-1][4], core.ident)
        self.assertFalse(gate.is_set())
        gate.set()
        core.join(2)
        self.assertEqual(result, [1])

    def test_output_overflow_is_bounded_and_terminal_reason_survives(self):
        c, stream, gate, clear, output, transitions, accepted, result, core = self.blocked_run(output_queue_capacity=1)
        stream.send(self.live)
        self.wait_for(lambda: len(accepted) == 2)
        stream.send(self.revoke)
        self.assertTrue(clear.wait(1))
        self.assertEqual(c._reason, 'diagnostic_output_queue_overflow')
        self.assertIsNone(c._state)
        self.assertEqual(accepted, [(1, True), (2, True), (3, True)])
        gate.set()
        core.join(2)
        self.assertEqual(result, [1])
        self.assertEqual(output[-1]['unresolved'], ['diagnostic_output_queue_overflow'])
        self.assertIs(output[-1]['diagnostics_complete'], False)
        self.assertEqual(output[-1]['diagnostics_dropped'], 2)

    def test_blocked_callback_returns_bounded_then_worker_finishes_on_release(self):
        c = DecisionConsumer(30_000_000, 2_000_000_000)
        c, stream, gate, clear, output, transitions, accepted, result, core = self.blocked_run(c, output_grace_seconds=.05)
        self.assertTrue(clear.wait(1))
        core.join(1)
        self.assertFalse(core.is_alive())
        self.assertEqual(result, [1])
        self.assertIsNone(c._state)
        self.assertFalse(gate.is_set())
        writers = [t for t in threading.enumerate() if t.name == 'decision-diagnostic-writer']
        self.assertEqual(len(writers), 1)
        self.assertTrue(writers[0].daemon)
        gate.set()
        writers[0].join(1)
        self.assertFalse(writers[0].is_alive())
        self.assertEqual(len(output), 1)  # In-flight old bytes cannot be recalled.

    def test_failure_during_normal_terminal_drain_is_not_success(self):
        for error in (BrokenPipeError('closed'), RuntimeError('callback')):
            with self.subTest(error=type(error).__name__):
                c = DecisionConsumer()
                def emit(value):
                    if value['consumer_status'] == 'CLOSED':
                        raise error
                if isinstance(error, OSError):
                    self.assertEqual(consume_events(io.StringIO(encoded(self.events)), emit, c), 1)
                else:
                    with self.assertRaises(RuntimeError):
                        consume_events(io.StringIO(encoded(self.events)), emit, c)
                self.assertEqual(c._reason, 'sample_limit')
                self.assertIsNone(c._state)
                self.assertIsNone(c._ref)

    def test_background_failure_clears_active_cache_with_stdin_open(self):
        for error in (BrokenPipeError('closed'), RuntimeError('callback')):
            with self.subTest(error=type(error).__name__):
                c, stream, gate, clear, output, transitions, accepted, result, core = self.blocked_run(emit_error=error)
                self.assertEqual(c._status, 'OBSERVING')
                gate.set()
                core.join(1)
                self.assertFalse(core.is_alive())
                self.assertIsNone(c._state)
                self.assertIsNone(c._ref)
                self.assertEqual(transitions[-1][4], core.ident)
                if isinstance(error, OSError):
                    self.assertEqual(result, [1])
                    self.assertEqual(c._reason, 'output_stream_error')
                else:
                    self.assertIs(result[0], error)

    def test_writer_exit_after_abandonment_cannot_report_success(self):
        entered, release = threading.Event(), threading.Event()
        output, dropped = [], []
        stopped = next(iter(DecisionPublisher(session_id='race').stop('sample_limit')))
        class Stream:
            def __init__(self):
                self.sent = False
            def readline(self, size):
                if self.sent:
                    return ''
                self.sent = True
                if not entered.wait(1):
                    raise OSError('test_writer_not_entered')
                return encoded([stopped])
        def emit(value):
            output.append(value)
            entered.set()
            release.wait(2)
        # Schedule a real callback completion after close has abandoned output,
        # just before its return. No state/output methods are mocked.
        source, first = inspect.getsourcelines(_DiagnosticOutput.close)
        return_line = first + next(i for i, line in enumerate(source) if line.strip().startswith('return '))
        def schedule(frame, event, arg):
            if (frame.f_code is _DiagnosticOutput.close.__code__ and event == 'line'
                    and frame.f_lineno == return_line):
                writer = frame.f_locals['self']
                dropped.append(writer._dropped)
                release.set()
                writer.thread.join(1)
            return schedule
        previous = sys.gettrace()
        c = DecisionConsumer()
        try:
            sys.settrace(schedule)
            result = consume_events(Stream(), emit, c, tick_seconds=.005, output_grace_seconds=.01)
        finally:
            sys.settrace(previous)
            release.set()
        self.assertEqual(dropped, [1])
        self.assertEqual([d['consumer_status'] for d in output], ['WAITING'])
        self.assertEqual(c._reason, 'sample_limit')
        self.assertEqual(result, 1)

    def test_raw_cli_writer_handles_partial_zero_and_memory_outputs(self):
        with patch('mtgaplayer.cli.os.write', side_effect=[2, 1000]) as write:
            _emit_consumer_diagnostic({'read_only': True})
            self.assertEqual(write.call_count, 2)
        with patch('mtgaplayer.cli.os.write', return_value=0):
            with self.assertRaises(OSError):
                _emit_consumer_diagnostic({})
        memory = io.StringIO()
        with patch('mtgaplayer.cli.sys.stdout', memory):
            _emit_consumer_diagnostic({'read_only': True})
        self.assertEqual(memory.getvalue(), '{"read_only": true}\n')

    def test_real_cli_internal_invalidation_matrix(self):
        for case in ('age', 'silence', 'new_event', 'input_overflow', 'output_overflow',
                     'cancel', 'abnormal', 'persistent'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                report = run_case(directory, case)
                self.assertTrue(report['internal_invalidated_before_resume'])
                self.assertEqual(report['input_order_errors'], 0)


if __name__ == '__main__':
    unittest.main()
