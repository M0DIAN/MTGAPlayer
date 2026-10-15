"""Bounded real-CLI backpressure counterexamples; synthetic source only.

Internal stderr samples are test observations, never product notifications.
All comparisons and deadlines use controller perf_counter_ns. Child clocks
only identify an emit that has not returned, not cross-process latency.
"""
import argparse
import json
from pathlib import Path
import tempfile
import time
import platform
import sys

from qualify_delivery import Session, QualificationError, encoded, request, version


def blocked(row):
    since = row.get('emit_active_since_ns')
    return since is not None and row['child_ns'] - since >= 30_000_000


def run_case(directory, case, baseline=False):
    directory = Path(directory)
    gate = directory / 'producer.gate'
    gate.touch()
    options = {'output_queue_capacity': 512}
    if case in ('output_overflow', 'persistent'):
        options['output_queue_capacity'] = 64
    if case == 'input_overflow':
        options['queue_capacity'] = 64
    # Fill larger OS stdout pipes before the unchanged 500ms age lease expires.
    # Still require an actual emit blocked >=30ms; never infer backpressure
    # merely from paused controller reads or relax the invalidation assertions.
    interval = .001 if case in ('age', 'new_event', 'output_overflow', 'persistent', 'input_overflow') else .003
    session = Session(directory, interval, 1000, silence_ms=150 if case == 'silence' else 3000,
        age_ms=500 if case in ('age', 'new_event') else 30000, pause_file=gate,
        event_probes=False, consumer_role='consumer_internal', consumer_options=options)
    try:
        session.startup()
        session.gate.clear()
        session.wait(session.paused.is_set)
        paused = time.perf_counter_ns()
        first_blocked = session.wait(lambda: next((r for r in session.internal if blocked(r)), None))
        blocked_at = first_blocked['observed_ns']
        initial_sequence = first_blocked['last_sequence']
        if case == 'silence':
            gate.unlink()  # Producer remains alive, pipe stays open.
            session.wait(lambda: session.producer_gated)
        elif case == 'new_event':
            session.write(encoded([request(41, 1)]))
        elif case == 'abnormal':
            session.producer.kill()
        elif case in ('input_overflow', 'cancel'):
            # Probe files are sent through the child environment before launch.
            (directory / (case + '.trigger')).touch()
        hold = 1.25 if case == 'persistent' else .7
        deadline = time.perf_counter() + hold
        while time.perf_counter() < deadline:
            session.pump(.01)
        # Capture before permitting even one more stdout read.
        before_resume = time.perf_counter_ns()
        during = [r for r in session.internal if blocked_at <= r['observed_ns'] <= before_resume]
        invalid = next((r for r in during if r['kind'] == 'clear' and not r['has_state'] and
                        not r['has_reference'] and r['status'] in ('CLOSED', 'STALE', 'PROTOCOL_ERROR')), None)
        session.gate.set()
        if not gate.exists():
            gate.touch()
        session.consumer.wait(timeout=3)
        if session.producer.poll() is None:
            session.producer.wait(timeout=3)
        for thread in session.threads:
            thread.join(1)
        while not session.inbox.empty():
            session.pump(0)
        if session.failure:
            raise QualificationError(session.failure)
        terminal = next((d for d in reversed(session.diagnostics) if d['consumer_status'] in
                         ('STALE', 'PROTOCOL_ERROR', 'CLOSED')), None)
        expected = {'age': 'observation_age_expired', 'new_event': 'observation_age_expired',
            'silence': 'event_silence_expired', 'output_overflow': 'diagnostic_output_queue_overflow',
            'persistent': 'diagnostic_output_queue_overflow', 'abnormal': 'unexpected_eof',
            'input_overflow': 'input_queue_overflow', 'cancel': 'cancelled'}[case]
        returned = next((r for r in reversed(session.internal) if r['kind'] == 'returned'), None)
        result = {'case': case, 'outcome': 'baseline_reproduced' if baseline else 'verified',
            'producer_interval_seconds': interval,
            'stdout_read_pause_ms': (before_resume - paused) / 1e6,
            'confirmed_emit_block_ms': (before_resume - blocked_at) / 1e6,
            'internal_invalidated_before_resume': invalid is not None,
            'internal_invalidation_observed_ms': None if invalid is None else (invalid['observed_ns'] - blocked_at) / 1e6,
            'internal_reason': None if invalid is None else invalid['reason'],
            'accepted_sequence_at_block': initial_sequence,
            'max_accepted_sequence_while_blocked': max(r['last_sequence'] or 0 for r in during),
            'ticks_at_block': first_blocked['ticks'], 'ticks_before_resume': during[-1]['ticks'],
            'input_queue_peak': max(r['input_peak'] for r in session.internal),
            'input_overflows': max(r['input_overflows'] for r in session.internal),
            'input_order_errors': max(r['order_errors'] for r in session.internal),
            'output_metrics': None if returned is None else returned['output'],
            'terminal_diagnostic': terminal, 'consumer_exit': session.consumer.returncode,
            'producer_exit': session.producer.returncode, 'returned_internal': returned,
            'external_notification_during_block_claimed': False,
            'internal_observations': session.internal,
            'input_tail': 'fail-closed stops subscription; unread tail is not claimed delivered'}
        if not baseline:
            if invalid is None or invalid['reason'] != expected or result['input_order_errors']:
                raise QualificationError('internal_invalidation_or_order_failed: ' + json.dumps(result))
            if case != 'persistent' and (terminal is None or terminal['unresolved'] != [expected]):
                raise QualificationError('terminal_reason_not_delivered: ' + json.dumps(result))
            if returned is None or returned['has_state'] or returned['has_reference'] or session.consumer.returncode != 1:
                raise QualificationError('uncleared_or_unbounded_exit')
            if case == 'new_event' and not any(r['kind'] == 'clear' and r['status'] == 'INVALIDATED'
                    and r['reason'] == 'request_replaced' for r in during):
                raise QualificationError('new_event_not_processed_while_blocked')
        elif invalid is not None:
            raise QualificationError('baseline_no_longer_reproduces_stalled_core')
        return result
    finally:
        session.cleanup()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    cases = ('age',) if args.baseline else ('age', 'silence', 'new_event', 'input_overflow',
               'output_overflow', 'cancel', 'abnormal', 'persistent')
    report = {'code': version(), 'baseline': args.baseline, 'cases': [], 'qualified': False,
              'environment': {'python': sys.version, 'executable': sys.executable, 'platform': platform.platform()}}
    try:
        for case in cases:
            record = {'case': case, 'outcome': 'pending'}
            report['cases'].append(record)  # Failed attempts remain in the denominator.
            try:
                with tempfile.TemporaryDirectory(prefix='backpressure-') as directory:
                    record.update(run_case(directory, case, args.baseline))
            except (QualificationError, OSError, TimeoutError) as exc:
                record.update(outcome='failed', error=str(exc))
                raise
        report['qualified'] = True
    finally:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'qualified': True, 'cases': len(report['cases'])}))


if __name__ == '__main__':
    main()
