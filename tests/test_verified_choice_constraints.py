"""SelectN necessary constraints via actual raw replay; mutations are synthetic.

The positive prefix and response are existing authorized sanitized fixtures.
No private Player.log, response encoding, server acceptance or input is used.
"""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from mtgaplayer.choice_graph import CHOICE_VALIDATION_LEVELS
from mtgaplayer.raw_log import RawReducer
from mtgaplayer.response_evidence import (inspect_response_envelopes,
                                         inspect_verified_choice_constraints)
from test_response_evidence import FIXTURE, ROOT, SCRIPT, save, source_rows


def response():
    return json.loads((FIXTURE.parent / 'player_log_selectn_response.jsonl').read_text(encoding='utf-8'))


def prompt(rows):
    return next(m for m in rows[-1]['greToClientEvent']['greToClientMessages']
                if m['type'] == 'GREMessageType_SelectNReq')


def state_change(previous=231):
    return {'greToClientEvent': {'greToClientMessages': [{
        'type': 'GREMessageType_GameStateMessage', 'systemSeatIds': [1],
        'gameStateMessage': {'type': 'GameStateType_Diff', 'gameStateId': 232,
                             'prevGameStateId': previous}}]}}


class VerifiedChoiceConstraintTests(unittest.TestCase):
    def inspect(self, rows, tail=b''):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'authorized-fixture.jsonl'
            save(path, rows)
            if tail:
                with path.open('ab') as stream:
                    stream.write(tail)
            return inspect_verified_choice_constraints(path)

    def assert_counts(self, result, selectn, other=14):
        summary = result['summary']
        expected = dict(zip(CHOICE_VALIDATION_LEVELS, selectn))
        subset = summary['select_n_responses']
        self.assertEqual(subset['counts'], expected)
        self.assertEqual(subset['total'], sum(selectn))
        expected['unsupported_protocol'] += other
        total = summary['all_observed_client_responses']
        self.assertEqual(total['counts'], expected)
        self.assertEqual(total['total'], sum(expected.values()))
        for key in ('legal_choice_verified', 'complete_legality_verified',
                    'response_encoding_verified', 'server_acceptance_verified',
                    'execution_ready', 'input_sent'):
            self.assertIs(result[key], False)
            self.assertIs(summary[key], False)

    def test_real_prefix_response_and_actual_count_only_cli(self):
        rows = source_rows()
        reducer = RawReducer()
        reducer.reset(1)
        for row in rows:
            reducer.apply(row)
        before = copy.deepcopy(reducer.request)
        self.assertEqual((before['id'], before['game_state_id']), (311, 231))
        self.assertEqual([c['instance_id'] for c in before['candidates']], [175, 176, 178, 179])
        reducer.apply(response())
        self.assertIsNone(reducer.request)
        self.assertIn((reducer.match, reducer.game, 311), reducer.consumed)
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'authorized-fixture.jsonl'
            save(path, rows + [response()])
            result = inspect_verified_choice_constraints(path)
            cli = subprocess.run([sys.executable, str(SCRIPT), str(path),
                                  '--verified-choice-constraints'], cwd=ROOT,
                                 text=True, capture_output=True, check=False)
            old = inspect_response_envelopes(path)
        self.assertEqual(cli.returncode, 0, cli.stderr)
        self.assertEqual(json.loads(cli.stdout), result['summary'])
        self.assert_counts(result, (1, 0, 0, 0))
        self.assertEqual(result['summary']['source']['framed_records'], 131)
        graph, = result['graphs']
        expected_identity = {**{k: before['binding'][k] for k in
                                ('generation', 'match', 'game', 'game_state_id', 'self_seat')},
                             'request_id': 311, 'request_type': 'GREMessageType_SelectNReq'}
        self.assertEqual(graph['request_identity'], expected_identity)
        self.assertFalse(graph['current_request'])
        self.assertTrue(graph['engine_offered'])
        self.assertTrue(graph['known_constraint_satisfied'])
        self.assertEqual(graph['completeness'], 'partial')
        constraint, = graph['constraints']
        self.assertEqual(constraint['action_key'], {'request_identity': expected_identity})
        self.assertEqual(constraint['observed_quantity_or_domain'],
                         {'candidate_instance_ids': [175, 176, 178, 179], 'max_sel': 2, 'min_sel': None})
        self.assertEqual(len(constraint['verified_structural_constraints']), 5)
        self.assertEqual(graph['historical_validation']['selected_count'], 2)
        self.assertTrue(all(c['satisfied'] for c in graph['historical_validation']['checks']))
        self.assertIn('min_sel_unknown', graph['unresolved'])
        self.assertEqual(graph['observed_successors'], [])
        for key in ('legal_choice_verified', 'complete_legality_verified',
                    'response_encoding_verified', 'server_acceptance_verified',
                    'execution_ready', 'input_sent'):
            self.assertIs(graph[key], False)
        self.assertNotIn('all_observed_client_responses', old)
        self.assertEqual(old['observed_historical_client_response_records'], 15)
        self.assertNotIn('graphs', cli.stdout)
        for private in (str(path), before['binding']['match'], '175', '179', '231', '311',
                        'request_identity', 'candidate_instance_ids'):
            self.assertNotIn(private, cli.stdout)

    def test_membership_maximum_and_nonrepeatable_violate_without_sanitizing(self):
        # 174 is in real unfilteredIds but NOT the allowed selectNReq.ids.
        self.assertIn(174, prompt(source_rows())['selectNReq']['unfilteredIds'])
        for selected in ([174], [175, 175], [175, 176, 178], [True], [175.0],
                         ['175'], [-1], [2**53], None, 'not-an-array'):
            with self.subTest(selected=selected):
                reply = response()
                reply['payload']['selectNResp']['ids'] = selected
                result = self.inspect(source_rows() + [reply])
                self.assert_counts(result, (0, 1, 0, 0))
                graph, = result['graphs']
                self.assertFalse(graph['known_constraint_satisfied'])
                self.assertEqual(graph['constraints'][0]['observed_quantity_or_domain']
                                 ['candidate_instance_ids'], [175, 176, 178, 179])

    def test_missing_evidence_and_extended_protocol_never_default_to_empty(self):
        for mutation, expected in (
                (lambda p: p.pop('selectNResp'), (0, 0, 1, 0)),
                (lambda p: p.update(selectNResp={}), (0, 0, 1, 0)),
                (lambda p: p.update(selectNResp={'selectedIds': [175]}), (0, 0, 0, 1)),
                (lambda p: p['selectNResp'].update(extraLimit='PRIVATE_SENTINEL'), (0, 0, 0, 1)),
                (lambda p: p.update(privateExtra='PRIVATE_SENTINEL'), (0, 0, 0, 1)),
                (lambda p: p.update(selectNResp=True), (0, 1, 0, 0))):
            with self.subTest(expected=expected, mutation=mutation):
                reply = response()
                mutation(reply['payload'])
                result = self.inspect(source_rows() + [reply])
                self.assert_counts(result, expected)
                self.assertNotIn('PRIVATE_SENTINEL', json.dumps(result))

    def test_exact_gate_rejects_bad_envelope_ids_state_or_no_own_request(self):
        for field, value in (('respId', None), ('respId', True), ('respId', 311.0),
                             ('respId', 312), ('gameStateId', None),
                             ('gameStateId', True), ('gameStateId', 231.0), ('gameStateId', 232)):
            with self.subTest(field=field, value=value):
                reply = response()
                if value is None:
                    reply['payload'].pop(field)
                else:
                    reply['payload'][field] = value
                result = self.inspect(source_rows() + [reply])
                self.assert_counts(result, (0, 0, 1, 0))
                self.assertEqual(result['graphs'], [])
        for seats in ([2], [1, 2]):
            rows = source_rows()
            prompt(rows)['systemSeatIds'] = seats
            self.assert_counts(self.inspect(rows + [response()]), (0, 0, 1, 0))
        self.assert_counts(self.inspect([response()]), (0, 0, 1, 0), other=0)

    def test_consumed_superseded_state_advance_and_gap_never_reopen(self):
        result = self.inspect(source_rows() + [response(), response()])
        self.assert_counts(result, (1, 0, 1, 0))
        self.assertEqual(len(result['graphs']), 1)
        newer = copy.deepcopy(prompt(source_rows()))
        newer['msgId'] = 312
        supersede = {'greToClientEvent': {'greToClientMessages': [newer]}}
        for intervening in (supersede, state_change(), state_change(previous=999)):
            with self.subTest(intervening=intervening):
                result = self.inspect(source_rows() + [intervening, response()])
                self.assert_counts(result, (0, 0, 1, 0))
                self.assertEqual(result['graphs'], [])

    def test_empty_array_only_satisfies_known_constraints_and_unknown_request_is_unsupported(self):
        reply = response()
        reply['payload']['selectNResp']['ids'] = []
        result = self.inspect(source_rows() + [reply])
        self.assert_counts(result, (1, 0, 0, 0))
        graph, = result['graphs']
        self.assertTrue(graph['known_constraint_satisfied'])
        self.assertIsNone(graph['constraints'][0]['observed_quantity_or_domain']['min_sel'])
        self.assertIn('min_sel_unknown', graph['unresolved'])
        for field, value in (('validationType', 'SelectionValidationType_Unknown'),
                             ('minSel', 1), ('allowCancel', 'AllowCancel_Yes'),
                             ('minWeight', -2147483648.0), ('maxWeight', 2147483647.0)):
            with self.subTest(field=field):
                rows = source_rows()
                req = prompt(rows)
                if field == 'allowCancel':
                    req[field] = value
                else:
                    req['selectNReq'][field] = value
                result = self.inspect(rows + [response()])
                self.assert_counts(result, (0, 0, 0, 1))
                self.assertEqual(result['graphs'], [])

    def test_partial_or_framing_error_preserves_denominator_but_no_verified_graph(self):
        for tail in (b'{"payload":', b'{bad}\n'):
            with self.subTest(tail=tail):
                result = self.inspect(source_rows() + [response()], tail=tail)
                self.assert_counts(result, (0, 0, 1, 0))
                self.assertFalse(result['source_complete'])
                self.assertEqual(result['graphs'], [])
                source = result['summary']['source']
                self.assertTrue(source['partial_record'] or source['framing_errors'])

    def test_all_observed_denominator_keeps_unknown_and_malformed_responses(self):
        unknown = {'payload': {'type': 'ClientMessageType_PRIVATE_UNKNOWNResp',
                               'respId': 900, 'gameStateId': 231}}
        malformed_other = {'payload': {'type': 'ClientMessageType_PerformActionResp',
                                       'respId': True, 'gameStateId': 231}}
        malformed_selectn = response()
        malformed_selectn['payload'].pop('respId')
        result = self.inspect(source_rows() + [response(), unknown, malformed_other, malformed_selectn])
        self.assert_counts(result, (1, 0, 1, 0), other=16)
        self.assertEqual(result['summary']['all_observed_client_responses']['total'], 18)
        self.assertNotIn('PRIVATE_UNKNOWN', json.dumps(result))

    def test_new_mode_is_opt_in_mutually_exclusive_and_missing_file_count_only(self):
        with self.assertRaises(ValueError):
            inspect_response_envelopes(FIXTURE, verified_choice_constraints=True, choice_graph_history=True)
        with tempfile.TemporaryDirectory() as d:
            missing = Path(d) / 'absent-private-path.log'
            cli = subprocess.run([sys.executable, str(SCRIPT), str(missing),
                                  '--verified-choice-constraints'], cwd=ROOT,
                                 text=True, capture_output=True, check=False)
        self.assertEqual(cli.returncode, 1)
        output = json.loads(cli.stdout)
        self.assertEqual(output['probe'], 'mtga-verified-choice-constraints-v1')
        self.assertNotIn(str(missing), cli.stdout)
        self.assertFalse(output['input_sent'])


if __name__ == '__main__':
    unittest.main()
