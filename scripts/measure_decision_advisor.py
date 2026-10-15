"""Bounded synthetic advisor timings, not live game/three-second qualification.

Stage samples are independent calls, not an additive decomposition of total.
The full API total includes latest Consumer view copy, validation and output.
No identity, candidate content or mutable timings enter deterministic advice.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time

from mtgaplayer.cli import watch_decision_events
from mtgaplayer.decision_consumer import DecisionConsumer
from mtgaplayer.decision_advisor import (assess_current_decision, _extract_actions,
    _classify_actions, _preference, _graph_issue, SIMPLE_TYPE_POLICY)
from mtgaplayer.live_performance import quantiles

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'tests/fixtures/player_log_selectn.jsonl'


def _poll(stream):
    result = []
    for event in stream:
        result.append(event)
        if event['event_type'] == 'liveness':
            return result
    raise ValueError('fixture_stream_ended')


def _version():
    def git(*args):
        return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()
    paths = ('src/mtgaplayer/decision_advisor.py', 'src/mtgaplayer/decision_consumer.py',
             'src/mtgaplayer/policy.py', 'tests/test_decision_advisor.py', 'scripts/measure_decision_advisor.py')
    return {'head': git('rev-parse', 'HEAD'), 'tree': git('rev-parse', 'HEAD^{tree}'),
        'tracked_dirty': bool(git('status', '--porcelain', '--untracked-files=no')),
        'source_sha256': {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in paths}}


def measure(count, *, report=None):
    original = [json.loads(line) for line in FIXTURE.read_text(encoding='utf-8').splitlines()]
    cases = {'pass_only': [{'actionType': 'ActionType_Pass'}],
        'pass_unique_play': [{'actionType': 'ActionType_Pass'}, {'actionType': 'ActionType_Play',
            'instanceId': 166, 'grpId': 96839, 'facetId': 0, 'shouldStop': False}],
        'complex_and_unknown': [{'actionType': 'ActionType_Pass'}, {'actionType': 'ActionType_Cast',
            'instanceId': 161, 'targets': [], 'manaCost': []}, {'actionType': 'ActionType_FloatMana'}]}
    content = {'code': _version(), 'environment': {'python': sys.version, 'executable': sys.executable,
        'platform': platform.platform()}, 'samples_per_case': count,
        'clock': 'perf_counter_ns; local durations only', 'policy_version': SIMPLE_TYPE_POLICY,
        'inputs': 'existing scrubbed Full/Diff chain plus explicitly synthetic action arrays',
        'stage_note': 'Independent stage calls are not additive; total is the complete current advisor API.',
        'live_qualification': False, 'cases': [], 'qualified': False}
    report = {} if report is None else report
    report.update(content)
    for name, actions in cases.items():
        record = {'case': name, 'requested': count, 'attempted': 0, 'verified': 0,
                  'unattempted': count, 'failures': [], 'stages_ms': {}}
        report['cases'].append(record)
        times = {key: [] for key in ('candidate_extraction', 'evidence_classification', 'heuristic_preference', 'total_assessment')}
        record['raw_durations_ns'] = times
        with tempfile.TemporaryDirectory(prefix='advisor-bench-') as directory:
            path = Path(directory) / 'synthetic.jsonl'
            path.write_text(''.join(json.dumps(row) + '\n' for row in original[:9]), encoding='utf-8')
            stream = watch_decision_events(path, interval=0, samples=3, session_id='advisor-measurement')
            consumer = DecisionConsumer()
            try:
                for event in _poll(stream):
                    if not consumer.accept_event(event):
                        raise ValueError('history_consumer_rejected')
                frame = copy.deepcopy(original[9])
                request = next(m for m in frame['greToClientEvent']['greToClientMessages']
                               if m.get('type') == 'GREMessageType_ActionsAvailableReq')
                request['actionsAvailableReq'] = {'actions': actions}
                with path.open('a', encoding='utf-8') as handle:
                    handle.write(json.dumps(frame) + '\n')
                for event in _poll(stream):
                    if not consumer.accept_event(event):
                        raise ValueError('append_consumer_rejected')
                state = consumer.current_view()['decision_state']
                rows = _extract_actions(state)
                issue = _graph_issue(state, rows)
                expected = assess_current_decision(consumer, policy_version=SIMPLE_TYPE_POLICY)
                for _ in range(count):
                    record['attempted'] += 1
                    record['unattempted'] -= 1
                    samples = {}
                    for key, call in (
                        ('candidate_extraction', lambda: _extract_actions(state)),
                        ('evidence_classification', lambda: _classify_actions(rows, state['binding'])),
                        ('heuristic_preference', lambda: _preference(rows, SIMPLE_TYPE_POLICY, True, issue,
                            state['legal_action_space']['immediate_frontier']['projection'].get('unknown_request_fields_present'))),
                        ('total_assessment', lambda: assess_current_decision(consumer, policy_version=SIMPLE_TYPE_POLICY))):
                        started = time.perf_counter_ns()
                        value = call()
                        samples[key] = time.perf_counter_ns() - started
                    if value != expected or not value['candidate_coverage']['inventory_integrity_verified']:
                        record['failures'].append('assessment_changed_or_expired')
                        continue
                    record['verified'] += 1
                    for key, duration in samples.items():
                        times[key].append(duration)
            finally:
                stream.close()
                consumer.close('measurement_ended')
        record['stages_ms'] = {key: quantiles([value / 1_000_000 for value in values]) for key, values in times.items()}
        record['raw_durations_ns'] = times
    report['qualified'] = all(r['verified'] == count and not r['failures'] for r in report['cases'])
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--samples', type=int, default=200)
    parser.add_argument('--output', type=Path, default=ROOT / 'artifacts/local-mp19-phase1/performance.json')
    args = parser.parse_args()
    if not 1 <= args.samples <= 1000:
        parser.error('samples must be 1..1000')
    report = {'qualified': False, 'cases': []}
    try:
        measure(args.samples, report=report)
    except (ValueError, KeyError, TypeError, OSError, StopIteration):
        report['qualified'] = False
        report['error'] = 'fixture_or_assessment_error'
        if report['cases']:
            report['cases'][-1]['failures'].append('measurement_aborted')
    for record in report['cases']:
        record['stages_ms'] = {key: quantiles([value / 1_000_000 for value in values])
                              for key, values in record['raw_durations_ns'].items()}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'qualified': report['qualified'], 'cases': len(report['cases'])}))
    return 0 if report['qualified'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
