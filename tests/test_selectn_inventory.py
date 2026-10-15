"""SelectN current-domain integrity and request-only option evidence."""
import copy
import json
import subprocess
import sys
import unittest

from mtgaplayer.cli import watch_decision_events
from mtgaplayer.decision_advisor import assess_current_decision, assess_decision_state
from mtgaplayer.decision_consumer import DecisionConsumer
import test_decision_advisor as advisor_helpers
from test_decision_input import rows
from test_decision_publisher import ManualClock, append, poll_events
from test_action_frontier import save
from test_decision_consumer import encoded


class SelectNInventoryTests(unittest.TestCase):
    setUp = advisor_helpers.DecisionAdvisorTests.setUp
    current = advisor_helpers.DecisionAdvisorTests.current
    accept_poll = advisor_helpers.DecisionAdvisorTests.accept_poll

    def test_real_current_options_preserve_order_identity_without_card_enrichment(self):
        consumer = self.current(rows=rows())
        advice = assess_current_decision(consumer)
        options = advice['candidate_assessments']
        self.assertEqual([o['offered_instance_id'] for o in options], [175, 176, 178, 179])
        self.assertEqual(advice['candidate_coverage']['assessed_count'], 4)
        self.assertTrue(advice['candidate_coverage']['inventory_integrity_verified'])
        for position, option in enumerate(options):
            self.assertEqual(option['option_key'], {'request_identity': advice['request_identity'], 'option_position': position})
            self.assertEqual(option['highest_evidence_level'], 'LA1')
            self.assertEqual(option['identity_scope'], 'request_reference_only')
            self.assertIsNone(option['strategic_utility'])
            self.assertNotIn('action_key', option)
            self.assertNotIn('list_position', option)
            self.assertNotIn('card_id', option)
            self.assertTrue(all(v is False for v in option['execution'].values()))
        self.assertIsNone(advice['preferred_candidate'])
        self.assertEqual(advice['abstention_reason'], 'select_n_strategy_unsupported')
        options[0]['option_key']['request_identity']['request_id'] = 999
        self.assertEqual(assess_current_decision(consumer)['request_identity']['request_id'], 311)

    def test_malformed_domain_never_claims_inventory_integrity(self):
        self.current(rows=rows())
        cases = [([175, 175, 178, 179], 2), ([175, True], 1), ([175, 176.0], 1),
                 ([175, -1], 1), ([], 2), ([175, 176], -1), ([175, 176], 0),
                 ([175, 176], 3), ([175, 176], None)]
        for ids, maximum in cases:
            with self.subTest(ids=ids, maximum=maximum):
                event = copy.deepcopy(self.snapshot)
                event['sequence'] = event['snapshot_ref']['sequence'] = 1
                projection = event['decision_state']['legal_action_space']['immediate_frontier']['projection']
                projection.update(offered_instance_ids=ids, max_sel_raw=maximum)
                consumer = DecisionConsumer(clock_ns=self.clock)
                self.assertFalse(consumer.accept_event(event))
                view = consumer.current_view()
                self.assertEqual(view['consumer_status'], 'PROTOCOL_ERROR')
                self.assertIsNone(view['decision_state'])
                pure = assess_decision_state(event['decision_state'])
                self.assertFalse(pure['candidate_coverage']['inventory_integrity_verified'])
                self.assertEqual(pure['candidate_assessments'], [])

    def test_actual_replay_and_append_event_cli_publish_options_then_clear(self):
        data = rows()
        save(self.path, data)
        result = subprocess.run([sys.executable, '-m', 'mtgaplayer', 'replay', str(self.path),
            '--format', 'player-log', '--advice'], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(json.loads(result.stdout)['decision_advice']['candidate_assessments']), 4)
        save(self.path, data[:-1])
        stream = watch_decision_events(self.path, interval=0, samples=3, clock_ns=ManualClock(), session_id='selectn-options')
        self.addCleanup(stream.close)
        events = poll_events(stream)
        append(self.path, data[-1:])
        events += poll_events(stream) + list(stream)
        cli = subprocess.run([sys.executable, '-m', 'mtgaplayer', 'consume-events', '--advice'],
            input=encoded(events), capture_output=True, text=True, timeout=10)
        self.assertEqual(cli.returncode, 0, cli.stderr)
        diagnostics = [json.loads(line) for line in cli.stdout.splitlines()]
        observed = [d['decision_advice'] for d in diagnostics if d['decision_advice']['candidate_assessments']]
        self.assertTrue(observed)
        self.assertTrue(all(a['candidate_coverage']['assessed_count'] == 4 for a in observed))
        self.assertEqual(diagnostics[-1]['consumer_status'], 'CLOSED')
        self.assertEqual(diagnostics[-1]['decision_advice']['candidate_assessments'], [])

    def test_local_expiry_clears_all_options_without_using_retained_advice(self):
        self.current(rows=rows())
        self.assertEqual(len(assess_current_decision(self.consumer)['candidate_assessments']), 4)
        self.clock.advance(10_001)
        advice = assess_current_decision(self.consumer)
        self.assertEqual(advice['candidate_assessments'], [])
        self.assertIsNone(advice['source_snapshot_ref'])
