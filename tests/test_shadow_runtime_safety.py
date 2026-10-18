"""Public fixtures and invented controls only; no private logs or game input."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from mtgaplayer import cli
from mtgaplayer.decision_consumer import EXECUTION
from mtgaplayer.raw_log import RawFollower
from mtgaplayer.shadow_runtime import LocalShadowRuntime, _unknown, safe_summary
from test_combat_frontier import baseline, save
from test_decision_publisher import append, own_request


class StepClock:
    def __init__(self):
        self.now = 1_000_000

    def __call__(self):
        self.now += 1000
        return self.now


class ShadowRuntimeSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / 'synthetic-public.log'
        save(self.path, baseline())

    def runtime(self, **kwargs):
        result = LocalShadowRuntime(self.path, interval=0, clock_ns=StepClock(), **kwargs)
        self.addCleanup(result.close)
        return result

    def readonly(self, report):
        self.assertIs(report['read_only'], True)
        for key in EXECUTION:
            self.assertIs(report[key], False, key)

    def test_safe_summary_does_not_forward_owner_data_or_unknown_strings(self):
        secret = 'PRIVATE_OWNER_ACCOUNT_CARD_PATH_SENTINEL'
        frame = _unknown(secret)
        frame.update(request_type='GREMessageType_' + secret + 'Req',
            request_binding={'match': secret, 'request_id': 987654321},
            source_snapshot_ref={'session_id': secret},
            shadow_preference={'option_key': secret},
            observation_mode=secret, state_status=secret, time_scope=secret,
            shadow_policy_status=secret, hidden_card=secret, raw_payload=secret,
            input_path='C:/private/' + secret,
            current_options={'coverage': {'engine_offered_count': secret,
                'engine_offered_unit': secret, 'returned_options': True,
                'omitted_constructed_options': -1, 'truncated': secret},
                'options': [{'card_id': 987654321, 'face': secret}]},
            local_evidence={secret: {'status': secret}},
            timings_ns={secret: 123, 'current_options': 200, 'shadow_policy': -1})
        frame.update({key: True for key in EXECUTION})
        before = copy.deepcopy(frame)
        report = safe_summary(frame)
        self.assertEqual(frame, before)
        encoded = json.dumps(report)
        for value in (secret, '987654321', 'C:/private/', 'request_binding',
                      'source_snapshot_ref', 'shadow_preference', 'raw_payload', 'card_id'):
            self.assertNotIn(value, encoded)
        self.assertEqual(report['request_type'], 'unsupported_request')
        self.assertEqual(report['abstention_reason'], 'unreviewed_reason')
        self.assertEqual(report['revocation_reason'], 'unreviewed_reason')
        self.assertIsNone(report['engine_offered_count'])
        self.assertIsNone(report['returned_options'])
        self.assertEqual(report['timings_ns'], {'current_options': 200})
        self.readonly(report)

    def test_safe_summary_keeps_source_domains_separate_and_omits_item_ids(self):
        secret = 'PRIVATE_SOURCE_ITEM_CARD'
        frame = _unknown('request_strategy_unsupported')
        frame.update(time_scope='current_at_completed_poll',
            request_type='GREMessageType_GroupReq', shadow_policy_status='unsupported',
            local_evidence={
                'current_group_evidence': {'status': 'observed', 'observed_item_count': 2,
                    'reviewed_member_count': 0, 'unresolved_item_count': 2,
                    'returned_members': 2, 'truncated': False,
                    'unresolved_item_references': [{'group_item_ref': 987654321, 'face': secret}]},
                'current_search_evidence': {'status': 'observed', 'offered_item_count': 8,
                    'returned_members': 3, 'items_to_search_count': 47, 'truncated': True,
                    'offered_search_item_refs': [{'search_item_ref': 987654321, 'face': secret}]}})
        report = safe_summary(frame)
        self.assertEqual(report['local_evidence']['current_search_evidence']['counts'],
            {'offered_item_count': 8, 'returned_members': 3, 'items_to_search_count': 47})
        self.assertEqual(report['local_evidence']['current_group_evidence']['counts'],
            {'observed_item_count': 2, 'reviewed_member_count': 0,
             'unresolved_item_count': 2, 'returned_members': 2})
        self.assertTrue(report['local_evidence']['current_search_evidence']['truncated'])
        self.assertFalse(report['local_evidence']['current_group_evidence']['truncated'])
        self.assertNotIn(secret, json.dumps(report))
        self.assertNotIn('987654321', json.dumps(report))
        self.assertIsNone(report['complete_legal_choices'])

    def test_unknown_cost_domain_is_null_instead_of_zero_observed_choices(self):
        from mtgaplayer.current_cost_stage import unknown
        frame = _unknown('request_strategy_unsupported')
        frame['local_evidence'] = {'current_cost_stage': unknown('unreviewed_cost_shape')}
        cost = safe_summary(frame)['local_evidence']['current_cost_stage']
        self.assertEqual(cost['status'], 'unknown')
        for key in ('mana_requirements', 'payment_action_rows', 'predictive_solutions'):
            self.assertIsNone(cost[key], key)

    def test_safe_source_coverage_and_evidence_levels_are_whitelisted(self):
        secret = 'PRIVATE_SOURCE_SCOPE_ID'
        frame = _unknown('request_strategy_unsupported')
        frame['current_options'] = {'coverage': {'sources': [
            {'source': 'known_candidates_v6.cast_members', 'scope': secret,
             'constructed_options': 2, 'returned_options': 1,
             'omitted_constructed_options': 1, 'truncated': True,
             'coverage': {'candidate_total_for_reviewed_constraints': None,
                'member_probes': {'verified': 1, 'unknown': 2, secret: 987654321}}},
            {'source': secret, 'observed': 987654321}]},
            'options': [{'evidence_level': 'known_constraints_verified', 'card_id': 987654321},
                        {'evidence_level': secret}]}
        report = safe_summary(frame)
        self.assertEqual(len(report['sources']), 1)
        source = report['sources'][0]
        self.assertEqual(source['source'], 'known_candidates_v6.cast_members')
        self.assertEqual(source['returned_options'], 1)
        self.assertEqual(source['omitted_constructed_options'], 1)
        self.assertTrue(source['truncated'])
        self.assertEqual(source['coverage']['member_probes'], {'verified': 1, 'unknown': 2})
        self.assertIsNone(source['coverage']['candidate_total_for_reviewed_constraints'])
        self.assertEqual(report['evidence_levels'], {'known_constraints_verified': 1})
        self.assertNotIn(secret, json.dumps(report))
        self.assertNotIn('987654321', json.dumps(report))

    def test_finite_watch_counts_empty_polls_and_closes_preference(self):
        runtime = self.runtime(samples=3)
        frames = list(runtime.frames())
        self.assertEqual(len(frames), 4)
        self.assertEqual(frames[0]['time_scope'], 'observed_in_history')
        self.assertEqual(frames[-1]['reason'], 'sample_limit')
        self.assertIsNone(runtime.current_frame()['shadow_preference'])
        self.assertTrue(runtime._closed)
        report = runtime.performance_report()
        self.assertEqual(report['counts']['polls'], 3)
        self.assertEqual(report['counts']['terminal_revocations'], 1)
        self.assertEqual(report['phases']['all_polls']['poll_count'], 3)
        self.assertEqual(report['phases']['empty_poll']['poll_count'], 2)
        for frame in frames:
            self.readonly(frame)
        timing = report['phases']['all_polls']['timings_ms']['poll_to_frame_ready']
        self.assertEqual(timing['sample_count'], 3)
        self.assertEqual(timing['attempted_samples'], 3)
        self.assertEqual(timing['omitted_by_cap'], 0)
        self.assertGreaterEqual(timing['max_ms'], timing['p50_ms'])

    def test_continuous_generator_close_revokes_current_frame(self):
        runtime = self.runtime()
        stream = runtime.frames()
        self.addCleanup(stream.close)
        self.assertEqual(next(stream)['time_scope'], 'observed_in_history')
        append(self.path, [own_request()])
        current = next(stream)
        self.assertEqual(current['time_scope'], 'current_at_completed_poll')
        self.assertIsNotNone(current['request_binding'])
        stream.close()
        self.assertTrue(runtime._closed)
        denied = runtime.current_frame()
        self.assertEqual(denied['time_scope'], 'expired_or_revoked')
        self.assertIsNone(denied['request_binding'])
        self.assertIsNone(denied['current_options'])
        self.assertIsNone(denied['shadow_preference'])
        self.assertEqual(runtime.performance_report()['counts']['terminal_revocations'], 1)

    def test_source_error_preserves_failed_attempt_and_sanitizes_private_path(self):
        runtime = self.runtime(samples=4)
        original = RawFollower.poll
        calls = 0
        def failing(follower):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError('C:/PRIVATE_ACCOUNT/Player.log PRIVATE_PAYLOAD')
            return original(follower)
        with patch.object(RawFollower, 'poll', failing):
            frames = list(runtime.frames())
        self.assertEqual(frames[-1]['reason'], 'source_io_error')
        report = runtime.performance_report()
        self.assertEqual(report['counts']['polls'], 2)
        self.assertEqual(report['counts']['failed_polls'], 1)
        self.assertEqual(report['phases']['failed_poll']['poll_count'], 1)
        failed = report['phases']['failed_poll']['timings_ms']
        self.assertEqual(failed['poll_to_frame_ready']['sample_count'], 1)
        self.assertEqual(failed['poll_read_framing']['sample_count'], 0)
        self.assertEqual(report['phases']['all_polls']['timings_ms']['poll_to_frame_ready']['sample_count'], 2)
        text = json.dumps({'frames': [safe_summary(frame) for frame in frames], 'performance': report})
        self.assertNotIn('PRIVATE_ACCOUNT', text)
        self.assertNotIn('PRIVATE_PAYLOAD', text)
        self.assertNotIn(str(self.path), text)
        self.readonly(report)

    def test_invalid_complete_record_is_counted_without_losing_latency(self):
        runtime = self.runtime(samples=4)
        stream = runtime.frames()
        self.addCleanup(stream.close)
        next(stream)
        with self.path.open('ab') as output:
            output.write(b'{not valid JSON}\n')
        frame = next(stream)
        self.assertEqual(frame['time_scope'], 'expired_or_revoked')
        self.assertIsNone(frame['shadow_preference'])
        report = runtime.performance_report()
        self.assertEqual(report['counts']['polls'], 2)
        self.assertEqual(report['phases']['invalid_or_revoked']['poll_count'], 1)
        self.assertEqual(report['phases']['invalid_or_revoked']['timings_ms']['poll_to_frame_ready']['sample_count'], 1)

    def test_cli_source_error_only_emits_safe_summary_and_failed_timing(self):
        output = []
        with patch.object(RawFollower, 'poll', side_effect=OSError('C:/PRIVATE_PATH/SECRET_PAYLOAD')), \
             patch.object(cli, '_emit_consumer_diagnostic', side_effect=output.append):
            code = cli.main(['watch-shadow', str(self.path), '--samples', '2', '--interval', '0'])
        self.assertEqual(code, 1)
        self.assertEqual(len(output), 1)
        self.assertEqual(output[0]['revocation_reason'], 'source_io_error')
        self.assertEqual(output[0]['performance']['counts']['failed_polls'], 1)
        self.assertNotIn('PRIVATE_PATH', json.dumps(output))
        self.assertNotIn('SECRET_PAYLOAD', json.dumps(output))
        self.assertNotIn(str(self.path), json.dumps(output))
        self.readonly(output[0])

    def test_cli_default_continuous_interrupt_is_explicit_and_bounded(self):
        output = []
        def interrupted(_seconds):
            raise KeyboardInterrupt
        with patch.object(cli.time, 'sleep', side_effect=interrupted), \
             patch.object(cli, '_emit_consumer_diagnostic', side_effect=output.append):
            code = cli.main(['watch-shadow', str(self.path), '--interval', '0'])
        self.assertEqual(code, 0)
        self.assertEqual(len(output), 2)
        self.assertEqual(output[-1]['revocation_reason'], 'user_interrupt')
        self.assertEqual(output[-1]['performance']['counts']['polls'], 1)
        self.assertEqual(output[-1]['performance']['counts']['terminal_revocations'], 1)

    def test_constructor_rejects_bool_or_invalid_bounds(self):
        for kwargs in ({'samples': True}, {'samples': 0}, {'samples': 1001},
                       {'interval': True}, {'interval': float('nan')},
                       {'max_history_bytes': True}, {'max_observation_age_ns': 0},
                       {'observation_mode': 'PRIVATE_PATH'}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                LocalShadowRuntime(self.path, **kwargs)


if __name__ == '__main__':
    unittest.main()
