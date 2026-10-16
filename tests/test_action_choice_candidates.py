"""MP48 Cast/Activate known-consistent rows from retained real requests."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from mtgaplayer.cli import replay
from mtgaplayer.choice_candidates import enumerate_known_candidates
from mtgaplayer.choice_validation import validate_proposed_choice
from mtgaplayer.decision_consumer import EXECUTION
from mtgaplayer.semantic_activate import PROFILE as ACTIVATE_PROFILE
from mtgaplayer.request_parameters import PROFILE as CAST_PROFILE

FIXTURE = Path(__file__).parent / 'fixtures'


class ActionRowCandidateTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / 'source.jsonl'
        self.cast_rows = [json.loads(line) for line in (
            FIXTURE / 'player_log_cast_generic_one.jsonl').read_text().splitlines()]
        self.activate_rows = [json.loads(line) for line in (
            FIXTURE / 'player_log_activate_generic_two.jsonl').read_text().splitlines()]

    def prefix(self, rows, count, version=5):
        self.path.write_text(''.join(json.dumps(row)+'\n' for row in rows[:count]))
        return replay(self.path, format='player-log',
                      decision_state_version=version)['decision_state']

    def assert_readonly_reviewed(self, state, output):
        self.assertTrue(output['read_only'])
        for key in EXECUTION:
            self.assertFalse(output[key], key)
        for key in ('full_action_domain_complete', 'global_restrictions_verified',
                    'complete_payment_verified', 'complete_legality_verified',
                    'server_acceptance_verified', 'historical_response_used'):
            self.assertFalse(output[key], key)
        for proposal in output['candidates']:
            self.assertEqual(validate_proposed_choice(state, proposal)['known_constraints'],
                             'verified_known_constraints')
            self.assertNotIn('source_snapshot_ref', proposal)

    def test_actual_generic2_activate_two_consistent_of_twenty_offered_rows(self):
        state = self.prefix(self.activate_rows, 5)
        self.assertEqual(state['legal_action_space']['request_parameters']['profile'],
                         ACTIVATE_PROFILE)
        output = enumerate_known_candidates(state)
        self.assertEqual([p['list_position'] for p in output['candidates']], [1, 3])
        self.assertEqual(output['candidate_total_for_reviewed_constraints'], 2)
        self.assertEqual(output['action_row_coverage'], {
            'engine_active_action_rows': 20,
            'verified_known_consistent_rows': 2,
            'unknown_or_unreviewed_rows': 18,
            'contradicted_known_constraint_rows': 0})
        self.assertTrue(output['exhaustive_for_reviewed_constraints'])
        self.assertFalse(output['truncated'])
        self.assert_readonly_reviewed(state, output)

    def test_actual_generic1_cast_one_consistent_of_six_offered_rows(self):
        state = self.prefix(self.cast_rows, 14)
        self.assertEqual(state['legal_action_space']['request_parameters']['profile'],
                         CAST_PROFILE)
        output = enumerate_known_candidates(state)
        self.assertEqual([p['list_position'] for p in output['candidates']], [1])
        self.assertEqual(output['action_row_coverage'], {
            'engine_active_action_rows': 6,
            'verified_known_consistent_rows': 1,
            'unknown_or_unreviewed_rows': 5,
            'contradicted_known_constraint_rows': 0})
        self.assertTrue(output['exhaustive_for_reviewed_constraints'])
        self.assert_readonly_reviewed(state, output)

    def test_bounded_enumeration_retains_total_over_supported_active_rows(self):
        state = self.prefix(self.activate_rows, 5, version=6)
        output = enumerate_known_candidates(state, limit=1)
        self.assertEqual([p['list_position'] for p in output['candidates']], [1])
        self.assertEqual(output['candidate_total_for_reviewed_constraints'], 2)
        self.assertEqual(output['action_row_coverage']['engine_active_action_rows'], 20)
        self.assertTrue(output['truncated'])
        self.assertFalse(output['exhaustive_for_reviewed_constraints'])
        self.assert_readonly_reviewed(state, output)

    def test_synthetic_activate_group_contradiction_not_admitted(self):
        rows = copy.deepcopy(self.activate_rows)
        action = rows[4]['greToClientEvent']['greToClientMessages'][0][
            'actionsAvailableReq']['actions'][3]
        objects = rows[2]['greToClientEvent']['greToClientMessages'][0][
            'gameStateMessage']['gameObjects']
        obj = next(o for o in objects if o['instanceId'] == action['instanceId'])
        pair = next(p for p in obj['uniqueAbilities'] if p['id'] == action['uniqueAbilityId'])
        pair['grpId'] += 999
        state = self.prefix(rows, 5)
        output = enumerate_known_candidates(state)
        self.assertEqual([p['list_position'] for p in output['candidates']], [1])
        self.assertEqual(output['action_row_coverage'], {
            'engine_active_action_rows': 20,
            'verified_known_consistent_rows': 1,
            'unknown_or_unreviewed_rows': 18,
            'contradicted_known_constraint_rows': 1})
        self.assert_readonly_reviewed(state, output)

    def test_target_bearing_opaque_values_do_not_enter_current_proposals(self):
        rows = copy.deepcopy(self.activate_rows)
        opaque = rows[4]['greToClientEvent']['greToClientMessages'][0][
            'actionsAvailableReq']['actions'][2]
        opaque['targets'][0]['targets'][0]['secret'] = 'PRIVATE_SENTINEL'
        state = self.prefix(rows, 5)
        output = enumerate_known_candidates(state)
        self.assertEqual([p['list_position'] for p in output['candidates']], [1, 3])
        self.assertNotIn('PRIVATE_SENTINEL', json.dumps(output))
        self.assert_readonly_reviewed(state, output)

    def test_response_consumes_request_and_revokes_candidates(self):
        state = self.prefix(self.activate_rows, 6)
        output = enumerate_known_candidates(state)
        self.assertEqual(output['status'], 'insufficient_evidence')
        self.assertEqual(output['candidates'], [])
        self.assertIsNone(output['source_snapshot_ref'])
        self.assert_readonly_reviewed(state, output)
