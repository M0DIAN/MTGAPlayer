"""Performance baseline tests use sanitized fixtures and synthetic mutations only."""
import copy
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from mtgaplayer.cli import main, replay, watch
from mtgaplayer.decision_input import build_decision_input
from mtgaplayer.live_performance import (PHASES, STAGES, PerformanceBaseline,
                                         quantiles, run, serialize_report)
from mtgaplayer.raw_log import RawReducer
from test_raw_log import entries, state
from test_response_evidence import action_request, reply, save, source_rows


def append(path, rows):
    with path.open('ab') as stream:
        stream.write(''.join(json.dumps(row) + '\n' for row in rows).encode('utf-8'))


def message_only(frame):
    request = frame['greToClientEvent']['greToClientMessages'][-1]
    return {'greToClientEvent': {'greToClientMessages': [copy.deepcopy(request)]}}


class FakeClock:
    def __init__(self, tick_ns=100_000):
        self.now = 0
        self.tick_ns = tick_ns
        self.sleeps = []

    def __call__(self):
        value = self.now
        self.now += self.tick_ns
        return value

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += round(seconds * 1_000_000_000)


class LivePerformanceTests(unittest.TestCase):
    def test_nearest_rank_and_empty_quantiles(self):
        result = quantiles(range(1, 101))
        self.assertEqual(result, {'sample_count': 100, 'p50_ms': 50,
                                  'p95_ms': 95, 'p99_ms': 99, 'max_ms': 100})
        self.assertEqual(quantiles([7])['p99_ms'], 7)
        self.assertEqual(quantiles([]), {'sample_count': 0, 'p50_ms': None,
                                        'p95_ms': None, 'p99_ms': None, 'max_ms': None})

    def assert_group_reconciliation(self, report):
        groups = report['groups'] if 'groups' in report else report
        total = groups['all_polls']
        for key, value in total['counts'].items():
            self.assertEqual(value, sum(groups[name]['counts'][key] for name in PHASES), key)
        for kind, counters in total['requests'].items():
            for key, value in counters.items():
                self.assertEqual(value, sum(groups[name]['requests'][kind][key]
                                            for name in PHASES), (kind, key))
        for name in ('all_polls',) + PHASES:
            group = groups[name]
            for stage in STAGES:
                self.assertEqual(group['timings_ms'][stage]['sample_count'], group['counts']['polls'])
            self.assertEqual(group['counts']['valid_snapshots'] + group['counts']['invalid_snapshots'],
                             group['counts']['polls'])

    def test_production_follower_append_partial_corruption_reset_and_full_recovery(self):
        rows = entries()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'synthetic.log'
            save(path, rows[:3])
            monitor = PerformanceBaseline(path)
            self.assertEqual(monitor.poll(), 'startup_history')
            self.assertEqual(monitor.poll(), 'empty_poll')
            encoded = (json.dumps(rows[3]) + '\n').encode()
            with path.open('ab') as stream:
                stream.write(encoded[:19])
            captured = []
            def decision(document):
                captured.append(copy.deepcopy(document))
                return build_decision_input(document)
            with patch('mtgaplayer.live_performance.build_decision_input', side_effect=decision):
                self.assertEqual(monitor.poll(), 'partial_append')
                self.assertEqual(monitor.poll(), 'empty_poll')
            for document in captured:
                self.assertFalse(document['current']['valid'])
                self.assertNotIn('objects', document['current'])
                self.assertTrue(document['last_valid']['valid'])
                self.assertIsNone(build_decision_input(document))
            with path.open('ab') as stream:
                stream.write(encoded[19:])
            self.assertEqual(monitor.poll(), 'incremental')
            with path.open('ab') as stream:
                stream.write(b'{"greToClientEvent":}\n')
            self.assertEqual(monitor.poll(), 'incremental')
            self.assertEqual(monitor.reducer.error, 'malformed_raw_record')
            restored = copy.deepcopy(rows[2])
            state(restored)['gameStateId'] = 3
            append(path, [restored])
            self.assertEqual(monitor.poll(), 'baseline_recovery')
            gap = copy.deepcopy(rows[3])
            state(gap).update(gameStateId=4, prevGameStateId=999)
            append(path, [gap])
            self.assertEqual(monitor.poll(), 'incremental')
            self.assertEqual(monitor.reducer.error, 'state_gap_or_missing_full')
            append(path, [restored])  # identical Full retransmission repairs continuity
            self.assertEqual(monitor.poll(), 'baseline_recovery')
            self.assertIsNone(monitor.reducer.error)
            save(path, rows[:3])
            self.assertEqual(monitor.poll(), 'file_reset')
            summary = monitor.summary()
        self.assert_group_reconciliation(summary)
        counts = summary['all_polls']['counts']
        self.assertEqual(counts['polls'], 10)
        self.assertEqual(counts['json_records'], 11)
        self.assertEqual(counts['gre_messages'], 6)
        self.assertEqual(counts['partial_polls'], 2)
        self.assertEqual(counts['continuity_error_events'], 2)
        self.assertEqual(counts['file_resets'], 1)
        self.assertEqual(counts['full_baseline_acquisitions'], 2)
        self.assertEqual(counts['full_baseline_recoveries'], 2)
        self.assertEqual(summary['incremental']['counts']['polls'], 3)
        self.assertEqual(summary['baseline_recovery']['counts']['polls'], 2)
        self.assertEqual(counts['unknown_or_unsupported_requests'], 0)
        self.assertEqual(counts['choice_graph_no_request_polls'], 10)

    def test_same_poll_request_then_response_is_observed_without_snapshot_coverage(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'synthetic.log'
            save(path, source_rows()[:9])
            monitor = PerformanceBaseline(path)
            monitor.poll()
            offered = action_request([{'actionType': 'ActionType_Pass'}])
            append(path, [offered, reply()])
            self.assertEqual(monitor.poll(), 'incremental')
            append(path, [message_only(offered)])  # consumed request cannot revive
            monitor.poll()
            summary = monitor.summary()
        self.assert_group_reconciliation(summary)
        counts = summary['incremental']['requests']['actions_available']
        self.assertEqual(counts['observed_unique'], 1)
        # Production ActionsAvailable semantics remain unverified even for Pass.
        self.assertEqual(counts['supported_unique'], 0)
        self.assertEqual(counts['unsupported_unique'], 1)
        self.assertEqual(counts['consumed_unique'], 1)
        self.assertEqual(counts['not_in_final_poll_snapshot_unique'], 1)
        self.assertEqual(counts['snapshot_polls'], 0)
        self.assertEqual(counts['frontier_unique_request_coverage'], 0)
        self.assertEqual(summary['incremental']['counts']['polls_observed_request_but_no_final_request'], 1)

    def test_same_gre_record_request_superseded_by_unsupported_request(self):
        offered = action_request([{'actionType': 'ActionType_Pass'}])
        messages = offered['greToClientEvent']['greToClientMessages']
        unsupported = copy.deepcopy(messages[-1])
        unsupported['msgId'] = 38
        unsupported['actionsAvailableReq'] = {'actions': 'PRIVATE_INVALID_SHAPE_SENTINEL'}
        messages.append(unsupported)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'synthetic.log'
            save(path, source_rows()[:9])
            monitor = PerformanceBaseline(path)
            monitor.poll()
            append(path, [offered])
            self.assertEqual(monitor.poll(), 'incremental')
            summary = monitor.summary()
        self.assert_group_reconciliation(summary)
        counts = summary['incremental']['requests']['actions_available']
        self.assertEqual(counts['observed_unique'], 2)
        self.assertEqual((counts['supported_unique'], counts['unsupported_unique']), (0, 2))
        self.assertEqual(counts['superseded_unique'], 1)
        self.assertEqual(counts['not_in_final_poll_snapshot_unique'], 1)
        self.assertEqual(counts['snapshot_unsupported_polls'], 1)
        self.assertEqual(counts['choice_graph_unsupported_snapshot_polls'], 1)
        self.assertEqual(summary['incremental']['counts']['polls_observed_request_not_in_final_snapshot'], 1)
        self.assertEqual(summary['incremental']['counts']['polls_observed_request_but_no_final_request'], 0)

    def test_projections_build_and_idle_never_inflates_unique_coverage(self):
        offered = action_request([{'actionType': 'ActionType_Pass'}, {
            'actionType': 'ActionType_Cast', 'instanceId': 161,
            'grpId': 987654, 'facetId': 0, 'shouldStop': False,
            'targets': [{'targetIdx': 0, 'targets': [{'private': 'PRIVATE_TARGET_SENTINEL'}]}],
            'manaCost': [{'private': 'PRIVATE_COST_SENTINEL'}],
        }])
        decisions = []
        def decision(document):
            value = build_decision_input(document)
            decisions.append(value)
            return value
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'PRIVATE_PATH_SENTINEL.log'
            save(path, source_rows()[:9] + [offered])
            monitor = PerformanceBaseline(path)
            with patch('mtgaplayer.live_performance.build_decision_input', side_effect=decision), \
                    patch.object(monitor.reducer, 'document', wraps=monitor.reducer.document) as project:
                monitor.poll()
                monitor.poll()
                self.assertEqual(project.call_count, 2)
            summary = monitor.summary()
        self.assertTrue(all(isinstance(value, dict) for value in decisions))
        counts = summary['all_polls']['requests']['actions_available']
        self.assertEqual(counts['observed_unique'], 1)
        self.assertEqual(counts['snapshot_polls'], 2)
        self.assertEqual(counts['frontier_success_snapshot_polls'], 2)
        self.assertEqual(counts['choice_graph_success_snapshot_polls'], 2)
        self.assertEqual(counts['frontier_unique_request_coverage'], 1)
        self.assertEqual(counts['choice_graph_unique_request_coverage'], 1)
        self.assertEqual(summary['empty_poll']['requests']['actions_available']['observed_unique'], 0)
        text = serialize_report({'groups': summary})
        self.assertNotIn('PRIVATE_', text)
        for forbidden in ('instance_id', 'request_identity', 'game_state_id', 'last_valid',
                          'visible_objects', 'grp_id', 'hand', '987654'):
            self.assertNotIn(forbidden, text)

    def test_real_selectn_has_explicit_not_applicable_graph(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'synthetic.log'
            save(path, source_rows())
            monitor = PerformanceBaseline(path)
            monitor.poll()
            summary = monitor.summary()
        counts = summary['startup_history']['requests']['select_n']
        self.assertEqual(counts['observed_unique'], 1)
        self.assertEqual(counts['supported_unique'], 1)
        self.assertEqual(counts['snapshot_supported_polls'], 1)
        self.assertEqual(counts['choice_graph_not_applicable_snapshot_polls'], 1)
        self.assertEqual(counts['choice_graph_success_snapshot_polls'], 0)
        self.assertEqual(counts['frontier_unsupported_snapshot_polls'], 1)

    def test_request_before_corruption_retained_and_unknown_labels_stay_private(self):
        offered = action_request([{'actionType': 'ActionType_Pass'}])
        unknown = message_only(offered)
        request = unknown['greToClientEvent']['greToClientMessages'][0]
        request.update(type='GREMessageType_PRIVATE_UNKNOWN_SENTINELReq', msgId=38)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'synthetic.log'
            save(path, source_rows()[:9])
            monitor = PerformanceBaseline(path)
            monitor.poll()
            append(path, [offered, unknown])
            with path.open('ab') as stream:
                stream.write(b'{"greToClientEvent":}\n')
            monitor.poll()
            summary = monitor.summary()
        self.assertEqual(summary['incremental']['requests']['actions_available']['observed_unique'], 1)
        self.assertEqual(summary['incremental']['requests']['other']['observed_unique'], 1)
        self.assertEqual(summary['incremental']['counts']['invalid_snapshots'], 1)
        self.assertEqual(summary['incremental']['counts']['polls_observed_request_but_no_final_request'], 1)
        self.assertNotIn('PRIVATE_UNKNOWN_SENTINEL', serialize_report({'groups': summary}))

    def test_legal_cross_game_and_match_full_resets_do_not_count_as_gaps(self):
        rows = entries()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'synthetic.log'
            save(path, rows[:4])
            monitor = PerformanceBaseline(path)
            monitor.poll()
            next_game = copy.deepcopy(rows[2])
            state(next_game)['gameInfo']['gameNumber'] = 2
            append(path, [next_game])
            self.assertEqual(monitor.poll(), 'baseline_recovery')
            self.assertEqual(monitor.reducer.version, 1)
            new_room = copy.deepcopy(rows[1])
            new_room['matchGameRoomStateChangedEvent']['gameRoomInfo']['gameRoomConfig']['matchId'] = 'next-fixture-match'
            new_match = copy.deepcopy(rows[2])
            state(new_match)['gameInfo']['matchID'] = 'next-fixture-match'
            append(path, [new_room, new_match])
            self.assertEqual(monitor.poll(), 'baseline_recovery')
            summary = monitor.summary()
        self.assertEqual(summary['all_polls']['counts']['full_baseline_acquisitions'], 3)
        self.assertEqual(summary['all_polls']['counts']['continuity_error_events'], 0)
        self.assertEqual(summary['baseline_recovery']['counts']['valid_snapshots'], 2)
        self.assertEqual(summary['incremental']['counts']['polls'], 0)
        self.assert_group_reconciliation(summary)

    def test_monotonic_600s_schedule_exceeds_watch_limit_and_excludes_sleep(self):
        clock = FakeClock()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'synthetic.log'
            save(path, entries()[:3])
            report = run(path, duration=600, interval=.25, clock_ns=clock, sleep=clock.sleep)
        self.assertIsNone(report['failure_category'])
        self.assertEqual(report['stop_reason'], 'duration_elapsed')
        self.assertEqual(report['groups']['all_polls']['counts']['polls'], 2400)
        self.assertGreaterEqual(report['elapsed_seconds'], 600)
        self.assertLess(report['elapsed_seconds'], 600.01)
        self.assertGreater(sum(clock.sleeps), 590)
        self.assertLess(report['groups']['all_polls']['timings_ms']['internal_pipeline_ms']['max_ms'], 10)
        self.assertEqual(report['groups']['all_polls']['counts']['missed_deadlines'], 0)
        self.assertEqual(report['trailing_missed_deadlines'], 0)
        self.assertEqual(report['groups']['all_polls']['scheduler_ms']['actual_poll_interval']['sample_count'], 2399)
        self.assert_group_reconciliation(report)

    def test_slow_pipeline_skips_deadlines_and_reports_lateness_and_jitter(self):
        clock = FakeClock(tick_ns=2_000_000)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'synthetic.log'
            save(path, entries()[:3])
            report = run(path, duration=.12, interval=.01, clock_ns=clock, sleep=clock.sleep)
        total = report['groups']['all_polls']
        self.assertGreater(total['counts']['missed_deadlines'] + report['trailing_missed_deadlines'], 0)
        self.assertGreater(total['scheduler_ms']['start_lateness']['max_ms'], 0)
        self.assertGreater(total['scheduler_ms']['interval_jitter']['max_ms'], 0)
        self.assertLess(total['counts']['polls'], 12)
        self.assert_group_reconciliation(report)

    def test_deadline_oversleep_preserves_all_unexecuted_schedule_slots(self):
        for extras, duration, expected in (
                ([0, 0, .26], 1, (3, 0, 1)),
                ([.26, .26], 1, (2, 0, 2)),
                ([.26, 0, .26], 1.25, (3, 1, 1))):
            with self.subTest(extras=extras):
                clock = FakeClock(tick_ns=0)
                oversleeps = iter(extras)

                def sleep(seconds):
                    clock.sleep(seconds)
                    clock.now += round(next(oversleeps, 0) * 1_000_000_000)

                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / 'synthetic.log'
                    save(path, entries()[:3])
                    report = run(path, duration=duration, interval=.25,
                                 clock_ns=clock, sleep=sleep)
                counts = report['groups']['all_polls']['counts']
                actual = (counts['polls'], counts['missed_deadlines'],
                          report['trailing_missed_deadlines'])
                self.assertEqual(actual, expected)
                self.assertEqual(sum(actual), round(duration / .25))
                self.assertEqual(report['stop_reason'], 'duration_elapsed')
                self.assert_group_reconciliation(report)

    def test_safe_error_interrupt_and_serialization_are_separate(self):
        clock = FakeClock()
        private_path = 'PRIVATE_ACCOUNT_PATH_SENTINEL.log'
        report = run(private_path, duration=.01, clock_ns=clock, sleep=clock.sleep)
        self.assertEqual(report['failure_category'], 'source_io_error')
        self.assertEqual(report['incomplete_poll_attempts'], 1)
        self.assertNotIn(private_path, serialize_report(report))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'synthetic.log'
            save(path, entries()[:3])
            with patch('mtgaplayer.live_performance.PerformanceBaseline.poll',
                       side_effect=ValueError('PRIVATE_RAW_EXCEPTION_SENTINEL')):
                report = run(path, duration=.01, clock_ns=clock, sleep=clock.sleep)
            self.assertEqual(report['failure_category'], 'other')
            self.assertNotIn('PRIVATE_RAW_EXCEPTION_SENTINEL', serialize_report(report))
            def interrupt(seconds):
                raise KeyboardInterrupt
            report = run(path, duration=.01, interval=.005, clock_ns=clock, sleep=interrupt)
        self.assertEqual(report['stop_reason'], 'keyboard_interrupt')
        self.assertIsNone(report['true_end_to_end_ms'])
        self.assertIsNone(report['game_event_to_log_write_ms'])
        for key in ('input_sent', 'executor_connected', 'execution_ready', 'legal_choice_verified'):
            self.assertFalse(report[key])
        self.assertNotIn('summary_serialization_ms', report)
        encoded = serialize_report(report, clock_ns=clock)
        decoded = json.loads(encoded)
        self.assertAlmostEqual(decoded.pop('summary_serialization_ms'), .1)
        self.assertEqual(decoded, report)

    def test_default_replay_watch_and_cli_bounds_unchanged(self):
        rows = entries()
        observed = []
        normal, instrumented = RawReducer(), RawReducer(lambda kind, details: observed.append(kind))
        normal.reset(1)
        instrumented.reset(1)
        for row in rows:
            normal.apply(row)
            instrumented.apply(row)
        self.assertEqual(normal.document(), instrumented.document())
        self.assertIn('request_accepted', observed)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'synthetic.log'
            save(path, rows[:4])
            replayed = replay(path, format='player-log')
            watched = list(watch(path, interval=0, samples=2))
        for document in [replayed] + watched:
            self.assertNotIn('groups', document)
            self.assertNotIn('decision_input', document)
            self.assertNotIn('action_frontier', document)
            self.assertNotIn('choice_graph', document)
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            main(['watch', 'unused.log', '--samples', '1001'])
        self.assertEqual(error.exception.code, 2)
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            main(['performance-baseline', 'unused.log', '--duration', '.1'])
        with self.assertRaisesRegex(ValueError, 'invalid_performance_bounds'):
            run('unused.log', interval=1e-12)
        expected = {'failure_category': None, 'input_sent': False}
        stdout = io.StringIO()
        with patch('mtgaplayer.live_performance.run', return_value=expected) as called, redirect_stdout(stdout):
            self.assertEqual(main(['performance-baseline', 'unused.log']), 0)
        self.assertEqual(called.call_args.args[1:3], (600, .25))
        self.assertFalse(json.loads(stdout.getvalue())['input_sent'])


if __name__ == '__main__':
    unittest.main()
