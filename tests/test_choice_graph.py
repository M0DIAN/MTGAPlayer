"""Phase 3: real-format GRE chain with explicit synthetic composite mutations."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from mtgaplayer.cli import replay
from mtgaplayer.response_evidence import (inspect_response_envelopes,
                                          inspect_historical_choice_graphs)
from test_response_evidence import action_request, reply, save, source_rows, SCRIPT

VALIDATE = Path(__file__).resolve().parents[1] / 'scripts/validate_choice_graph_evidence.py'


def composite_rows():
    # Only action rows are synthetic; envelope, own seat and Full/Diff chain
    # come from the checked-in sanitized Player.log fixture.
    cast = {'actionType': 'ActionType_Cast', 'instanceId': 161,
            'grpId': 987654, 'facetId': 0, 'shouldStop': False,
            'manaCost': [{'private': 'PRIVATE_COST_SENTINEL'}],
            'targets': [{'targetIdx': 0, 'targets': [
                {'private': 'PRIVATE_TARGET_SENTINEL'},
                {'private': 'PRIVATE_TARGET_SENTINEL'}]}],
            'autoTapSolution': {'autoTapActions': [
                {'instanceId': 283, 'abilityGrpId': 7}]}}
    mana = {'actionType': 'ActionType_Activate_Mana', 'instanceId': 283,
            'grpId': 998877, 'facetId': 0, 'abilityGrpId': 7,
            'uniqueAbilityId': 3, 'isBatchable': True,
            'isManaAbilityWithSideEffect': False,
            'manaSelections': [{'instanceId': 283, 'abilityGrpId': 7}],
            'manaPaymentOptions': [{'private': 'PRIVATE_PAYMENT_SENTINEL'}]}
    return [{'actionType': 'ActionType_Pass'}, cast, mana], cast


def history(ending=None, selected=None):
    offered, cast = composite_rows()
    rows = source_rows()[:9] + [action_request(offered)]
    rows.append(reply(details={'actions': [selected or cast]}))
    if ending:
        rows.extend(ending)
    return rows


def valid_later_state_and_request():
    originals = source_rows()
    state = copy.deepcopy(originals[14]['greToClientEvent']['greToClientMessages'][0])
    assert state['gameStateMessage']['gameStateId'] == 24
    offered, _ = composite_rows()
    next_req = copy.deepcopy(action_request(offered)['greToClientEvent']['greToClientMessages'][-1])
    next_req['msgId'] = 39
    next_req['gameStateId'] = 24
    return [{'greToClientEvent': {'greToClientMessages': [state]}},
            {'greToClientEvent': {'greToClientMessages': [next_req]}}]


class ChoiceGraphTests(unittest.TestCase):
    def test_current_constraints_are_positional_and_do_not_assert_legality(self):
        rows = history()[:-1]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'Player.log'
            save(path, rows)
            baseline = replay(path, format='player-log', decision_input=True,
                              action_frontier=True)
            result = replay(path, format='player-log', decision_input=True,
                            action_frontier=True, choice_graph=True)
        graph = result.pop('choice_graph')
        self.assertEqual(result, baseline)
        self.assertEqual(graph['schema_version'], 'mtga-choice-graph-v1')
        self.assertEqual(graph['immediate_frontier']['completeness'], 'partial')
        self.assertEqual(graph['expanded_choices']['completeness'], 'unknown')
        self.assertIsNone(graph['expanded_choices']['legal_combinations'])
        self.assertEqual([n['action_key']['list_position'] for n in graph['action_nodes']], [1, 2])
        cast, mana = graph['action_nodes']
        self.assertEqual(cast['action_key']['request_identity'], graph['request_identity'])
        targets = next(c for c in cast['constraints'] if c['parameter_category'] == 'targets')
        self.assertEqual(targets['observed_quantity_or_domain']['groups'], [
            {'position': 0, 'target_idx_raw': 0, 'target_count': 2}])
        self.assertIn('target_domain_and_combination_legality', targets['unresolved'])
        auto = next(c for c in cast['constraints'] if c['parameter_category'] == 'autoTapSolution')
        self.assertEqual(auto['observed_quantity_or_domain']['active_mana_position_links'], [
            {'position': 0, 'status': 'unique_pair', 'active_mana_position': 2}])
        self.assertIn('same_request_raw_mana_identity_pair_equality_only',
                      auto['verified_structural_constraints'])
        self.assertIn('additional_cost_choice_unverified', cast['unresolved_parameters'])
        self.assertIn('x_value_unverified', mana['unresolved_parameters'])
        self.assertEqual(graph['observed_successors'], [])
        self.assertEqual(graph['successor_observation_status'], 'unknown')
        for field in ('legal_choice_verified', 'response_encoding_verified',
                      'execution_ready', 'input_sent'):
            self.assertIs(graph[field], False)
        output = json.dumps(graph)
        for secret in ('PRIVATE_COST_SENTINEL', 'PRIVATE_TARGET_SENTINEL',
                       'PRIVATE_PAYMENT_SENTINEL'):
            self.assertNotIn(secret, output)

    def test_malformed_ambiguous_and_truncated_do_not_create_legal_combinations(self):
        offered, cast = composite_rows()
        variants = [
            [dict(cast, targets=[{'targetIdx': -1, 'targets': []}]), offered[2]],
            [cast, copy.deepcopy(cast), offered[2]],
            [dict(cast, targets=[{'targetIdx': 0, 'targets': []}] * 65), offered[2]],
            [dict(cast, manaCost='PRIVATE_BAD_COST'), offered[2]],
        ]
        for actions in variants:
            with self.subTest(kind=str(len(actions)) + str(actions[0].get('manaCost'))[:4]):
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / 'Player.log'
                    save(path, source_rows()[:9] + [action_request(actions)])
                    graph = replay(path, format='player-log', decision_input=True,
                                   action_frontier=True, choice_graph=True)['choice_graph']
                self.assertIsNotNone(graph)
                self.assertEqual(graph['expanded_choices']['completeness'], 'unknown')
                self.assertIsNone(graph['expanded_choices']['legal_combinations'])
                self.assertFalse(graph['legal_choice_verified'])

    def test_consumed_partial_and_wrong_opt_in_cannot_reuse_current(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'Player.log'
            save(path, history())
            consumed = replay(path, format='player-log', decision_input=True,
                              action_frontier=True, choice_graph=True)
            self.assertIsNone(consumed['choice_graph'])
            save(path, history()[:-1])
            with path.open('ab') as output:
                output.write(b'{"greToClientEvent":')
            partial = replay(path, format='player-log', decision_input=True,
                             action_frontier=True, choice_graph=True)
            self.assertIsNone(partial['choice_graph'])
            with self.assertRaisesRegex(ValueError, 'choice_graph_requires_action_frontier'):
                replay(path, format='player-log', decision_input=True, choice_graph=True)

    def test_full_binding_refuses_cross_game_or_seat_request(self):
        from mtgaplayer.choice_graph import build_choice_graph
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'Player.log'
            save(path, history()[:-1])
            document = replay(path, format='player-log', decision_input=True,
                              action_frontier=True, choice_graph=True)
        self.assertIsNotNone(document['choice_graph'])
        for field, value in (('match', 'wrong-match'), ('game', 99),
                             ('self_seat', 2), ('game_state_id', 999),
                             ('generation', 999)):
            with self.subTest(field=field):
                changed = copy.deepcopy(document['current']['request'])
                changed['binding'][field] = value
                self.assertIsNone(build_choice_graph(
                    document['decision_input'], document['action_frontier'], changed))
        changed = copy.deepcopy(document['decision_input'])
        changed['request']['type'] = 'GREMessageType_SelectNReq'
        self.assertIsNone(build_choice_graph(
            changed, document['action_frontier'], document['current']['request']))

    def test_historical_temporal_successor_and_count_only_cli(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'Player.log'
            save(path, history(valid_later_state_and_request()))
            report = inspect_response_envelopes(path, choice_graph_history=True)
            cli = subprocess.run([sys.executable, str(SCRIPT), str(path),
                                  '--choice-graph-history'],
                                 capture_output=True, text=True, check=False)
        self.assertEqual(cli.returncode, 0, cli.stderr)
        self.assertEqual(json.loads(cli.stdout), report)
        relation = report['historical_choice_relations']
        self.assertEqual(relation['matched_complex_responses'], 1)
        self.assertEqual(relation['response_action_linked'], 1)
        self.assertEqual(relation['temporal_successor_observed'], 1)
        self.assertEqual(relation['discontinuity'], 0)
        self.assertTrue(relation['successor_relation_is_temporal_only'])
        self.assertFalse(relation['causal_evidence'])
        self.assertEqual(relation['parameter_container_rows']['targets'], 2)
        self.assertEqual(relation['target_group_valid_rows'], 2)
        results = report['complex_action_choice_correlation']['selected_action_identity']
        self.assertTrue(results['counts_account_for_all_matched_action_responses'])
        text = json.dumps(report)
        for forbidden in ('987654', '998877', 'PRIVATE_COST_SENTINEL',
                          'PRIVATE_TARGET_SENTINEL', 'PRIVATE_PAYMENT_SENTINEL'):
            self.assertNotIn(forbidden, text)

    def test_local_historical_graph_binds_next_selectn_evidence_to_next_request(self):
        state = valid_later_state_and_request()[0]
        next_selectn = copy.deepcopy(source_rows()[-1]['greToClientEvent']['greToClientMessages'][-1])
        self.assertEqual(next_selectn['type'], 'GREMessageType_SelectNReq')
        next_selectn['msgId'] = 39
        next_selectn['gameStateId'] = 24
        harmless = {'greToClientEvent': {'greToClientMessages': [
            {'type': 'GREMessageType_UnrelatedResp'}]}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'Player.log'
            save(path, history([harmless, state,
                                {'greToClientEvent': {'greToClientMessages': [next_selectn]}}]))
            result = inspect_historical_choice_graphs(path)
        self.assertTrue(result['source_complete'])
        self.assertEqual(result['summary']['temporal_successor_observed'], 1)
        graph = result['graphs'][0]
        self.assertEqual(graph['request_identity']['request_id'], 37)
        cast = next(n for n in graph['action_nodes'] if n['action_key']['list_position'] == 1)
        edge = cast['observed_successors'][0]
        self.assertEqual(edge['request_identity']['request_id'], 39)
        self.assertFalse(edge['causal_evidence'])
        next_choice = edge['next_request_choice_evidence']
        self.assertEqual(next_choice['max_sel_raw'], 2)
        self.assertEqual(next_choice['offered_count'], 4)
        self.assertEqual(next_choice['provenance_request_identity'], edge['request_identity'])
        self.assertIsNone(next_choice['min_sel_verified'])
        self.assertFalse(next_choice['combinations_complete'])
        self.assertEqual(graph['observed_successors'], [edge])
        self.assertEqual(graph['successor_observation_status'], 'temporal_observed')
        self.assertEqual(cast['successor_observation_status'], 'temporal_observed')
        self.assertNotIn('future_choice_request_unobserved', cast['unresolved_parameters'])
        self.assertEqual(len(cast['constraints']), 3)
        self.assertFalse(graph['legal_choice_verified'])
        self.assertFalse(graph['input_sent'])

    def test_queued_valid_state_is_a_temporal_link_not_causal_proof(self):
        later = valid_later_state_and_request()
        later[0]['greToClientEvent']['greToClientMessages'][0]['type'] = (
            'GREMessageType_QueuedGameStateMessage')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'Player.log'
            save(path, history(later))
            report = inspect_historical_choice_graphs(path)
        self.assertEqual(report['summary']['temporal_successor_observed'], 1)
        self.assertFalse(report['graphs'][0]['observed_successors'][0]['causal_evidence'])

    def test_opaque_response_wrapper_keeps_unique_identity_temporal_link(self):
        offered, cast = composite_rows()
        rows = source_rows()[:9] + [action_request(offered),
                                    reply(details={'actions': [cast],
                                                   'PRIVATE_WRAPPER': 'PRIVATE_VALUE'})]
        rows.extend(valid_later_state_and_request())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'Player.log'
            save(path, rows)
            report = inspect_historical_choice_graphs(path)
        self.assertEqual(report['summary']['responses_with_unknown_wrapper_fields'], 1)
        self.assertEqual(report['summary']['response_action_linked'], 1)
        self.assertEqual(report['summary']['temporal_successor_observed'], 1)
        self.assertFalse(report['response_encoding_verified'])
        self.assertEqual(report['graphs'][0]['action_nodes'][0]['observed_successors'][0]
                         ['request_identity']['request_id'], 39)

    def test_missing_successor_and_discontinuity_are_distinct(self):
        cases = (([], 'no_successor_observed'),
                 ([{'greToClientEvent': {'greToClientMessages': [
                     copy.deepcopy(action_request()['greToClientEvent']['greToClientMessages'][-1])
                 ]}}], 'discontinuity'),
                 ([{'greToClientEvent': {'greToClientMessages': [
                     copy.deepcopy(source_rows()[14]['greToClientEvent']['greToClientMessages'][0]),
                     copy.deepcopy(source_rows()[14]['greToClientEvent']['greToClientMessages'][1]),
                 ]}}], 'ordering_unsupported'))
        for ending, expected in cases:
            with self.subTest(expected=expected):
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / 'Player.log'
                    save(path, history(ending))
                    relation = inspect_response_envelopes(
                        path, choice_graph_history=True)['historical_choice_relations']
                    local = inspect_historical_choice_graphs(path)
                self.assertEqual(relation['response_action_linked'], 1)
                self.assertEqual(relation[expected], 1)
                self.assertEqual(relation['temporal_successor_observed'], 0)
                self.assertEqual(local['graphs'][0]['successor_observation_status'],
                                 expected)

    def test_incomplete_identity_marks_historical_graph_not_action_linked(self):
        _, cast = composite_rows()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'Player.log'
            save(path, history(selected=dict(cast, facetId=None)))
            report = inspect_historical_choice_graphs(path)
        self.assertEqual(report['summary']['response_not_action_linked'], 1)
        self.assertEqual(report['graphs'][0]['successor_observation_status'],
                         'not_action_linked')
        self.assertEqual(report['graphs'][0]['observed_successors'], [])

    def test_partial_source_withholds_pending_and_prior_edges(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'Player.log'
            save(path, history(valid_later_state_and_request()))
            with path.open('ab') as stream:
                stream.write(b'{"greToClientEvent":')
            report = inspect_historical_choice_graphs(path)
        self.assertFalse(report['source_complete'])
        self.assertEqual(report['summary']['temporal_successor_observed'], 0)
        self.assertEqual(report['summary']['source_incomplete_edges_withheld'], 1)
        self.assertEqual(report['graphs'][0]['observed_successors'], [])
        self.assertEqual(report['graphs'][0]['successor_observation_status'],
                         'discontinuity')

    def test_bounded_validation_reconciles_and_emits_no_raw_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'PRIVATE_Player.log'
            save(path, history(valid_later_state_and_request()))
            command = [sys.executable, str(VALIDATE), str(path),
                       '--expect-framed-records', '13',
                       '--expect-matched-actions', '1',
                       '--expect-unique', '1',
                       '--expect-incomplete', '0']
            result = subprocess.run(command, capture_output=True, text=True,
                                    check=False)
            mismatch = subprocess.run(command[:-1] + ['1'], capture_output=True,
                                      text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertTrue(report['source_stable'])
        self.assertEqual(report['source_before'], report['source_after'])
        self.assertEqual(mismatch.returncode, 1)
        output = result.stdout
        for forbidden in ('PRIVATE_Player.log', '987654', '998877',
                          'PRIVATE_COST_SENTINEL', 'PRIVATE_TARGET_SENTINEL'):
            self.assertNotIn(forbidden, output)


if __name__ == '__main__':
    unittest.main()
