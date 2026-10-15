"""Advisor research over scrubbed fixtures and labeled synthetic action bodies."""
import copy
import json
import subprocess
import sys
from pathlib import Path
import tempfile
import unittest

from mtgaplayer.cli import replay, watch, watch_decision_events
from mtgaplayer.decision_consumer import DecisionConsumer, EXECUTION
from mtgaplayer.decision_advisor import (assess_current_decision, assess_decision_state,
    EVIDENCE_POLICY, SIMPLE_TYPE_POLICY)
from test_action_frontier import frames, save
from test_decision_state import action_message, walk
from test_decision_publisher import append, poll_events, ManualClock
from test_decision_input import rows as selectn_rows
from test_combat_frontier import baseline, request, ATTACK, BLOCK

PASS = {'actionType': 'ActionType_Pass'}
PLAY = {'actionType': 'ActionType_Play', 'instanceId': 166, 'grpId': 96839,
        'facetId': 0, 'shouldStop': False}


class DecisionAdvisorTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / 'scrubbed-synthetic.jsonl'
        self.clock = ManualClock(100)
        self.producer_clock = ManualClock(1_000_000)
        self.snapshot = None

    def current(self, actions=None, history=False, rows=None):
        data = frames() if rows is None else copy.deepcopy(rows)
        if actions is not None:
            action_message(data[-1])['actionsAvailableReq'] = {'actions': copy.deepcopy(actions),
                'inactiveActions': [{'actionType': 'ActionType_Cast', 'instanceId': 161}]}
        save(self.path, data if history else data[:-1])
        self.stream = watch_decision_events(self.path, interval=0, samples=100,
            clock_ns=self.producer_clock, session_id='advisor-session')
        self.addCleanup(self.stream.close)
        self.consumer = DecisionConsumer(10_000, 10_000, self.clock)
        self.accept_poll()
        if not history:
            append(self.path, [data[-1]])
            self.accept_poll()
        return self.consumer

    def accept_poll(self):
        events = poll_events(self.stream)
        for event in events:
            self.assertTrue(self.consumer.accept_event(event), event['event_type'])
            if event['event_type'] == 'snapshot':
                self.snapshot = copy.deepcopy(event)
        return events

    def advice(self, consumer=None, policy=SIMPLE_TYPE_POLICY):
        return assess_current_decision(consumer or self.consumer, policy_version=policy)

    def from_mutated_projection(self, change):
        """Advisor-specific integrity gaps can pass existing event validation."""
        event = copy.deepcopy(self.snapshot)
        event['sequence'] = event['snapshot_ref']['sequence'] = 1
        change(event['decision_state'])
        c = DecisionConsumer(clock_ns=self.clock)
        self.assertTrue(c.accept_event(event))
        return c

    def assert_abstain(self, advice, reason=None, empty=False):
        self.assertEqual(advice['assessment_status'], 'abstain')
        self.assertIsNone(advice['preferred_candidate'])
        self.assertIsNone(advice['preference_basis'])
        self.assertIsNotNone(advice['abstention_reason'])
        if reason:
            self.assertEqual(advice['abstention_reason'], reason)
        if empty:
            self.assertEqual(advice['candidate_assessments'], [])

    def test_actual_chain_unique_play_is_opt_in_research_only(self):
        c = self.current([PASS, PLAY])
        before = c.current_view()
        default = assess_current_decision(c)
        self.assert_abstain(default, 'evidence_only_policy')
        result = self.advice()
        self.assertEqual(result['assessment_status'], 'research_preference')
        self.assertEqual(result['preferred_candidate']['list_position'], 1)
        self.assertEqual(result['preference_basis'], 'unverified_simple_type_heuristic')
        self.assertEqual(result['policy_basis'], result['preference_basis'])
        self.assertEqual(result['source_snapshot_ref'], before['current_snapshot_ref'])
        self.assertEqual(result['request_identity'], before['decision_state']['binding'])
        self.assertEqual(result['preferred_candidate']['request_identity'], result['request_identity'])
        self.assertEqual(len(result['candidate_assessments']), 2)  # inactive Cast excluded.
        self.assertEqual(before, c.current_view())
        self.assertFalse(result['new_live_opportunity'])

    def test_history_and_detached_views_cannot_be_current_advice(self):
        c = self.current([PASS, PLAY], history=True)
        view = c.current_view()
        self.assert_abstain(self.advice(), 'new_request_not_observed', empty=True)
        self.assert_abstain(assess_current_decision(view), 'requires_current_consumer', empty=True)
        offline = assess_decision_state(view['decision_state'], policy_version=SIMPLE_TYPE_POLICY)
        self.assertTrue(offline['historical_research_only'])
        self.assertEqual(offline['assessment_scope'], 'historical_research_only')
        self.assertEqual(len(offline['candidate_assessments']), 2)
        self.assert_abstain(offline, 'historical_research_only')

    def test_pass_only_and_confirmed_empty_never_invent_preference(self):
        for actions in ([PASS], []):
            with self.subTest(actions=actions):
                self.current(actions)
                result = self.advice()
                self.assert_abstain(result)
                self.assertEqual(result['candidate_coverage']['offered_count'], len(actions))
                self.assertEqual(result['candidate_coverage']['inventory_status'], 'observed' if actions else 'confirmed_empty')
                self.assertIsNone(result['candidate_coverage']['legal_combinations'])

    def test_duplicate_types_preserve_original_positions_and_abstain(self):
        self.current([PASS, PLAY, PLAY, PASS])
        result = self.advice()
        self.assert_abstain(result, 'unique_play_not_observed')
        self.assertEqual([c['list_position'] for c in result['candidate_assessments']], [0, 1, 2, 3])
        self.assertNotEqual(result['candidate_assessments'][1]['action_key'], result['candidate_assessments'][2]['action_key'])

    def test_complex_floatmana_unknown_remain_visible_without_strategy_scores(self):
        self.current()
        result = self.advice()
        self.assert_abstain(result, 'complex_or_unsupported_candidates')
        candidates = result['candidate_assessments']
        self.assertEqual(len(candidates), 7)
        self.assertEqual(candidates[5]['engine_action_type'], 'ActionType_FloatMana')
        self.assertIn('UNSUPPORTED_STRUCTURE', candidates[5]['evidence_quality'])
        self.assertEqual(candidates[6]['engine_action_type'], '_unrecognized_action_type')
        self.assertIn('PARAMETERS_PARTIAL', candidates[2]['evidence_quality'])
        self.assertTrue(all(c['strategic_utility'] is None for c in candidates))
        self.assertNotIn('PRIVATE_', json.dumps(result))
        actions = [PASS, {'actionType': 'ActionType_Activate', 'instanceId': 166, 'abilityGrpId': 7, 'targets': []}]
        self.current(actions)
        self.assert_abstain(self.advice(), 'complex_or_unsupported_candidates')

    def test_inconsistent_counts_positions_scope_and_metadata_are_not_ranked(self):
        self.current([PASS, PLAY])
        changes = [
            lambda p: p.update(engine_active_action_count=3),
            lambda p: p['templates'].pop(),
            lambda p: (p['templates'][1].update(list_position=0), p['templates'][1]['action_key'].update(list_position=0)),
            lambda p: (p['templates'][1].update(list_position=5), p['templates'][1]['action_key'].update(list_position=5)),
            lambda p: p.update(scope='inactiveActions'),
            lambda p: p.update(interpreted_action_count=1),
            lambda p: p['templates'][1].pop('structurally_interpreted'),
            lambda p: p['templates'][1].update(visible_object_id=999999),
        ]
        for change in changes:
            with self.subTest(change=changes.index(change)):
                c = self.from_mutated_projection(lambda s: change(s['legal_action_space']['immediate_frontier']['projection']))
                result = self.advice(c)
                self.assert_abstain(result, 'candidate_inventory_invalid', empty=True)
                self.assertFalse(result['candidate_coverage']['inventory_integrity_verified'])
                self.assertIsNone(result['candidate_coverage']['offered_count'])

    def test_full_identity_and_nested_action_key_mismatches_are_rejected_offline(self):
        self.current([PASS, PLAY])
        state = self.consumer.current_view()['decision_state']
        for field in state['binding']:
            with self.subTest(field=field):
                bad = copy.deepcopy(state)
                value = bad['binding'][field]
                bad['binding'][field] = value + 1 if type(value) is int else value + '-different'
                self.assert_abstain(assess_decision_state(bad), 'invalid_decision_state', empty=True)
        for path in ('request_identity', 'action_key'):
            bad = copy.deepcopy(state)
            row = bad['legal_action_space']['immediate_frontier']['projection']['templates'][1]
            identity = row[path] if path == 'request_identity' else row[path]['request_identity']
            identity['request_id'] += 1
            self.assert_abstain(assess_decision_state(bad), 'invalid_decision_state', empty=True)

    def test_choice_graph_cannot_add_or_repair_actions(self):
        self.current()
        complex_node = copy.deepcopy(self.consumer.current_view()['decision_state']['legal_action_space']['choice_graph']['action_nodes'][0])
        self.current([PASS, PLAY])
        c = self.from_mutated_projection(lambda s: s['legal_action_space']['choice_graph']['action_nodes'].append(complex_node))
        result = self.advice(c)
        self.assert_abstain(result, 'choice_graph_candidate_conflict')
        self.assertEqual(len(result['candidate_assessments']), 2)
        c = self.from_mutated_projection(lambda s: s['legal_action_space']['immediate_frontier']['projection'].update(templates=None))
        self.assert_abstain(self.advice(c), 'candidate_inventory_invalid', empty=True)

    def test_select_n_reports_only_existing_count_and_unknown_minimum(self):
        self.current(rows=selectn_rows())
        result = self.advice()
        self.assert_abstain(result, 'select_n_strategy_unsupported')
        self.assertEqual(result['request_summary'], {'observed_candidate_count': 4, 'max_sel_raw': 2,
            'min_sel': None, 'combination_legality': None})
        self.assertEqual(result['candidate_assessments'], [])

    def test_combat_reports_only_existing_candidates_and_explicit_relations(self):
        for typ in (ATTACK, BLOCK):
            with self.subTest(typ=typ):
                self.current(rows=baseline() + [request(typ)])
                result = self.advice()
                self.assert_abstain(result, 'combat_strategy_unsupported')
                row = result['candidate_assessments'][0]
                self.assertEqual(row['candidate_instance_id'], 701)
                if typ == BLOCK:
                    self.assertEqual(row['engine_listed_attacker_references'][0]['attacker_instance_id'], 702)
                self.assertIsNone(result['candidate_coverage']['legal_combinations'])
                self.assertNotIn('PRIVATE_', json.dumps(result))

    def test_combat_reference_grafts_do_not_export_hidden_or_wrong_side_ids(self):
        self.current(rows=baseline() + [request(BLOCK)])
        changes = [
            lambda row: row.update(candidate_instance_id=703),  # Own private hand, not battlefield.
            lambda row: row['engine_listed_attacker_references'][0].update(attacker_instance_id=704),
            lambda row: row['engine_listed_attacker_references'][0].update(attacker_instance_id=701),
        ]
        for change in changes:
            with self.subTest(change=changes.index(change)):
                c = self.from_mutated_projection(lambda s: change(
                    s['legal_action_space']['immediate_frontier']['projection']['engine_offered_candidates'][0]))
                result = self.advice(c)
                self.assert_abstain(result, 'candidate_inventory_invalid', empty=True)
                self.assertNotIn('703', json.dumps(result))
                self.assertNotIn('704', json.dumps(result))

    def test_incomplete_blocker_edge_abstains_in_both_research_entries(self):
        self.current(rows=baseline() + [request(BLOCK)])
        def incomplete(state):
            edge = state['legal_action_space']['immediate_frontier']['projection']['engine_offered_candidates'][0]['engine_listed_attacker_references'][0]
            edge.pop('attacker_instance_id')
            edge['public_reference_verified'] = False
        c = self.from_mutated_projection(incomplete)
        self.assert_abstain(assess_decision_state(c.current_view()['decision_state']),
                            'candidate_inventory_invalid', empty=True)
        self.assert_abstain(self.advice(c), 'candidate_inventory_invalid', empty=True)

    def test_actual_replacement_invalidation_and_consumption_revoke_advice(self):
        self.current([PASS, PLAY])
        old = self.advice()
        frame = copy.deepcopy(action_message(frames()[-1]))
        frame.update(msgId=38, gameStateId=23)
        frame['actionsAvailableReq'] = {'actions': [PASS, PLAY]}
        append(self.path, [{'greToClientEvent': {'greToClientMessages': [frame]}}])
        events = poll_events(self.stream)
        self.assertEqual(events[0]['event_type'], 'invalidate')
        self.assertTrue(self.consumer.accept_event(events[0]))
        self.assert_abstain(self.advice(), 'consumer_invalidated', empty=True)
        for event in events[1:]:
            self.assertTrue(self.consumer.accept_event(event))
        new = self.advice()
        self.assertNotEqual(new['source_snapshot_ref'], old['source_snapshot_ref'])
        self.assertEqual(new['request_identity']['request_id'], 38)
        append(self.path, [{'payload': {'type': 'ClientMessageType_PerformActionResp', 'respId': 38, 'gameStateId': 23}}])
        self.accept_poll()
        self.assert_abstain(self.advice(), empty=True)

    def test_all_nonobserving_states_and_expired_retained_view_abstain(self):
        self.assert_abstain(assess_current_decision(DecisionConsumer(clock_ns=self.clock)), 'consumer_waiting', empty=True)
        self.current([PASS, PLAY])
        retained = self.consumer.current_view()
        self.clock.advance(10_001)
        self.assert_abstain(self.advice(), 'consumer_stale', empty=True)
        self.assert_abstain(assess_current_decision(retained), 'requires_current_consumer', empty=True)
        self.clock.now = 100
        self.current([PASS, PLAY])
        self.consumer.close('eof')
        self.assert_abstain(self.advice(), 'consumer_closed', empty=True)
        self.current([PASS, PLAY])
        self.assertFalse(self.consumer.accept_event({}))
        self.assert_abstain(self.advice(), 'consumer_protocol_error', empty=True)

    def test_deterministic_reassessment_and_detached_outputs_do_not_create_opportunity(self):
        self.current([PASS, PLAY])
        first = self.advice()
        self.clock.advance(100)
        self.accept_poll()  # Liveness changes sequence/age, not snapshot advice.
        self.assertEqual(first, self.advice())
        expected = copy.deepcopy(first)
        first['candidate_assessments'][1]['request_identity']['request_id'] = -1
        self.assertEqual(expected, self.advice())
        for node in walk(expected):
            self.assertTrue(all(node[k] is False for k in EXECUTION if k in node))
        for value in ('Plan', 'mouse_events', 'coordinates', 'response_payload', 'complete_verified'):
            self.assertNotIn(value, json.dumps(expected))

    def test_nested_authority_and_unsupported_policy_abstain(self):
        self.current([PASS, PLAY])
        state = self.consumer.current_view()['decision_state']
        state['legal_action_space']['immediate_frontier']['projection']['templates'][0]['execution_ready'] = True
        self.assert_abstain(assess_decision_state(state), 'invalid_decision_state', empty=True)
        self.assert_abstain(self.advice(policy='unknown'), 'unsupported_policy_version', empty=True)

    def test_simple_unknown_parameters_and_graph_structure_block_preference(self):
        self.current([PASS, PLAY])
        c = self.from_mutated_projection(lambda s: s['legal_action_space']['immediate_frontier']['projection']['templates'][1].update(
            unknown_parameter_fields_present=True))
        self.assert_abstain(self.advice(c), 'simple_candidate_structure_incomplete')
        c = self.from_mutated_projection(lambda s: s['legal_action_space']['immediate_frontier']['projection']['templates'][1].update(
            observed_parameter_shapes={'targets': {'kind': 'array', 'element_count': 0}}))
        self.assert_abstain(self.advice(c), 'simple_candidate_structure_incomplete')

    def test_missing_combat_body_and_unsupported_requests_never_imply_empty_domain(self):
        frame = request(ATTACK)
        frame['greToClientEvent']['greToClientMessages'][0].pop('declareAttackersReq')
        self.current(rows=baseline() + [frame])
        result = self.advice()
        self.assert_abstain(result, 'candidate_inventory_invalid', empty=True)
        self.assertIsNone(result['candidate_coverage']['offered_count'])
        self.current([PASS, PLAY])
        state = self.consumer.current_view()['decision_state']
        state['binding']['request_type'] = 'GREMessageType_UnknownReq'
        space = state['legal_action_space']
        space.update(request_type='GREMessageType_UnknownReq', choice_graph=None,
            immediate_frontier={'kind': None, 'availability': 'unsupported', 'completeness': 'unknown', 'projection': None})
        self.assert_abstain(assess_decision_state(state), 'unsupported_request_type', empty=True)

    def test_state_advance_and_generation_reset_do_not_restore_old_advice(self):
        self.current([PASS, PLAY])
        old = self.advice()
        append(self.path, [{'greToClientEvent': {'greToClientMessages': [{
            'type': 'GREMessageType_GameStateMessage', 'systemSeatIds': [1],
            'gameStateMessage': {'type': 'GameStateType_Diff', 'gameStateId': 24,
                'prevGameStateId': 23, 'turnInfo': {'decisionPlayer': 1, 'turnNumber': 24}}}]}}])
        self.accept_poll()
        self.assert_abstain(self.advice(), empty=True)
        replacement = self.path.with_name('replacement.jsonl')
        save(replacement, frames())
        replacement.replace(self.path)
        self.accept_poll()
        self.assert_abstain(self.advice(), 'new_request_not_observed', empty=True)
        self.assertNotEqual(old['source_snapshot_ref'], self.consumer.current_view()['current_snapshot_ref'])

    def test_actual_measurement_script_keeps_durations_outside_advice(self):
        output = self.path.with_name('measurement.json')
        run = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1] / 'scripts/measure_decision_advisor.py'),
            '--samples', '2', '--output', str(output)], capture_output=True, timeout=10)
        self.assertEqual(run.returncode, 0, run.stderr)
        report = json.loads(output.read_text(encoding='utf-8'))
        self.assertTrue(report['qualified'])
        self.assertFalse(report['live_qualification'])
        self.assertEqual(len(report['cases']), 3)
        for case in report['cases']:
            self.assertEqual((case['attempted'], case['verified']), (2, 2))
            self.assertEqual(set(case['stages_ms']), {'candidate_extraction', 'evidence_classification',
                'heuristic_preference', 'total_assessment'})
            self.assertTrue(all(stage['sample_count'] == 2 for stage in case['stages_ms'].values()))
        self.assertNotIn('request_identity', json.dumps(report))

    def test_old_harness_and_default_projection_remain_separate(self):
        self.current([PASS, PLAY])
        plain = replay(self.path, format='player-log')
        self.assertNotIn('decision_advice', plain)
        self.assertNotIn('decision_state', plain)
        document = next(watch(self.path, interval=0, samples=1))
        self.assertNotIn('decision_advice', document)
        self.assertNotIn('decision_state', document)
        synthetic = replay(Path(__file__).resolve().parents[1] / 'examples/synthetic.jsonl', True)
        self.assertTrue(synthetic['current']['valid'])


if __name__ == '__main__':
    unittest.main()
