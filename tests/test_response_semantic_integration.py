"""MP16 opt-in integration checks using the existing sanitized GRE source fixture."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from mtgaplayer.response_evidence import inspect_response_envelopes
from test_response_evidence import source_rows, action_request, reply, save, SCRIPT, ROOT


PASS = {'actionType': 'ActionType_Pass'}
PLAY = {'actionType': 'ActionType_Play', 'instanceId': 166, 'grpId': 96839,
        'facetId': 0, 'shouldStop': False}


class SemanticResponseIntegrationTests(unittest.TestCase):
    def inspect(self, rows):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'Player.log'
            save(path, source_rows()[:9] + rows)
            report = inspect_response_envelopes(path, semantic_choices=True)
        choices = report['action_choice_correlation']
        counts = {row['status']: row['count'] for row in choices['correlation_results']}
        self.assertEqual(set(counts), {'unique', 'multiple', 'no_match',
                                     'incomplete_or_unsupported'})
        self.assertEqual(sum(counts.values()), report['matched_actions_available_responses'])
        self.assertEqual(sum(counts.values()), choices['matched_action_responses_classified'])
        self.assertTrue(choices['counts_account_for_all_matched_action_responses'])
        self.assertTrue(report['source']['complete'])
        self.assertFalse(report['actionable'])
        self.assertFalse(report['input_sent'])
        self.assertFalse(choices['complete_response_encoding_verified'])
        self.assertFalse(choices['gameplay_effect_verified'])
        self.assertIsNone(choices['legal_actions'])
        output = json.dumps(report)
        for private in ('PRIVATE_UPSTREAM_FIELD', 'PRIVATE_UPSTREAM_VALUE',
                        '96839', '166', str(path)):
            self.assertNotIn(private, output)
        return report, counts

    def test_unparsed_same_type_source_blocks_but_uninterpreted_cast_does_not(self):
        missing = dict(PLAY)
        del missing['facetId']
        cases = [
            ([PASS, dict(PASS, PRIVATE_UPSTREAM_FIELD='PRIVATE_UPSTREAM_VALUE')], PASS,
             'incomplete_or_unsupported'),
            ([PLAY, missing], PLAY, 'incomplete_or_unsupported'),
            ([PLAY, dict(PLAY, grpId=True)], PLAY, 'incomplete_or_unsupported'),
            ([PLAY, dict(PLAY, instanceId=166.0)], PLAY, 'incomplete_or_unsupported'),
            ([PASS, {'actionType': 'ActionType_Cast',
                     'PRIVATE_UPSTREAM_FIELD': 'PRIVATE_UPSTREAM_VALUE'}], PASS, 'unique'),
        ]
        for actions, selected, status in cases:
            with self.subTest(status=status, actions=actions):
                report, counts = self.inspect([
                    action_request(actions), reply(details={'actions': [selected]})])
                self.assertEqual(counts[status], 1)
                self.assertEqual(report['matched_actions_available_responses'], 1)

    def test_wrong_or_unknown_type_consumes_request_before_valid_reply(self):
        for typ in ('ClientMessageType_SelectNResp', 'ClientMessageType_UnknownResp'):
            with self.subTest(typ=typ):
                wrong = reply(details={'actions': [PASS]})
                wrong['payload']['type'] = typ
                report, counts = self.inspect([
                    action_request([PASS]), wrong, reply(details={'actions': [PASS]})])
                self.assertEqual(sum(counts.values()), 0)
                self.assertEqual(report['unmatched_or_noncurrent_responses'], 2)

    def test_exact_current_own_gate_replacement_duplicates_and_wrong_state(self):
        newer = action_request([PASS], msg_id=38)
        prompt = next(msg for msg in newer['greToClientEvent']['greToClientMessages']
                      if msg.get('type') == 'GREMessageType_ActionsAvailableReq')
        report, counts = self.inspect([
            action_request([PASS]),
            {'greToClientEvent': {'greToClientMessages': [prompt]}},
            reply(details={'actions': [PASS]}),
            reply(38, 24, {'actions': [PASS]}),
            reply(38, 23, {'actions': [PASS]}),
            reply(38, 23, {'actions': [PASS]}),
        ])
        self.assertEqual(counts['unique'], 1)
        self.assertEqual(report['unmatched_or_noncurrent_responses'], 3)
        for recipient in ([2], [1, 2]):
            with self.subTest(recipient=recipient):
                report, counts = self.inspect([
                    action_request([PASS], recipient=recipient),
                    reply(details={'actions': [PASS]})])
                self.assertEqual(sum(counts.values()), 0)
                self.assertEqual(report['unmatched_or_noncurrent_responses'], 1)

    def test_strict_response_ids_stop_difference_duplicate_play_and_source_limits(self):
        cases = [
            ([PLAY], dict(PLAY, instanceId=True), 'incomplete_or_unsupported'),
            ([PLAY], dict(PLAY, grpId=96839.0), 'incomplete_or_unsupported'),
            ([PLAY], dict(PLAY, shouldStop=0), 'incomplete_or_unsupported'),
            ([PLAY], dict(PLAY, shouldStop=True), 'no_match'),
            ([PLAY, copy.deepcopy(PLAY)], PLAY, 'multiple'),
            ([PASS] * 257, PASS, 'incomplete_or_unsupported'),
        ]
        for actions, selected, status in cases:
            with self.subTest(status=status, selected=selected, length=len(actions)):
                _, counts = self.inspect([
                    action_request(actions), reply(details={'actions': [selected]})])
                self.assertEqual(counts[status], 1)
        inactive = action_request([])
        prompt = next(msg for msg in inactive['greToClientEvent']['greToClientMessages']
                      if msg.get('type') == 'GREMessageType_ActionsAvailableReq')
        prompt['actionsAvailableReq']['inactiveActions'] = [PASS]
        _, counts = self.inspect([inactive, reply(details={'actions': [PASS]})])
        self.assertEqual(counts['no_match'], 1)
        _, counts = self.inspect([
            action_request([PASS]), reply(details={'actions': [PASS] * 257})])
        self.assertEqual(counts['incomplete_or_unsupported'], 1)

    def test_modes_are_exclusive_and_default_and_shapes_stay_separate(self):
        rows = source_rows()[:9] + [action_request([PASS, PLAY]),
                                      reply(details={'actions': [PLAY],
                                                     'PRIVATE_UPSTREAM_FIELD':
                                                     'PRIVATE_UPSTREAM_VALUE'})]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'Player.log'
            save(path, rows)
            for shapes in (False, True):
                with self.subTest(shapes=shapes):
                    report = inspect_response_envelopes(path, action_shapes=shapes)
                    self.assertNotIn('action_choice_correlation', report)
                    self.assertEqual('action_array_structure' in report, shapes)
                    self.assertEqual(report['probe'],
                                     'mtga-client-response-action-shapes-v1' if shapes else
                                     'mtga-client-response-envelopes-v1')
            with self.assertRaises(ValueError):
                inspect_response_envelopes(path, action_shapes=True, semantic_choices=True)
            for other in ('--response-action-shapes', '--response-envelopes'):
                command = subprocess.run(
                    [sys.executable, str(SCRIPT), str(path),
                     '--response-choice-correlation', other], cwd=ROOT,
                    capture_output=True, text=True, check=False)
                self.assertEqual(command.returncode, 2)
                self.assertIn('not allowed with argument', command.stderr)

    def test_exact_authenticated_action_choice_opt_in_and_cli(self):
        request_actions = [
            {'actionType': 'ActionType_Pass'},
            {'actionType': 'ActionType_Play', 'instanceId': 166, 'grpId': 96839,
             'facetId': 0, 'shouldStop': False},
        ]
        response_action = {'actionType': 'ActionType_Play', 'instanceId': 166,
                           'grpId': 96839, 'facetId': 0, 'shouldStop': False}
        frames = source_rows()[:9] + [action_request(request_actions)] + [
            reply(details={'actions': [response_action],
                           'unknownSecretSibling': 'SECRET_NOT_EXPORTED'}),
        ]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'Player.log'
            save(path, frames)
            old = inspect_response_envelopes(path)
            report = inspect_response_envelopes(path, semantic_choices=True)
            command = subprocess.run([sys.executable, str(SCRIPT), str(path),
                                      '--response-choice-correlation'], cwd=ROOT,
                                     capture_output=True, text=True, check=False)
        self.assertNotIn('action_choice_correlation', old)
        self.assertEqual(report['probe'], 'mtga-client-response-semantic-correlation-v1')
        self.assertEqual(command.returncode, 0, command.stderr)
        self.assertEqual(json.loads(command.stdout), report)
        choices = report['action_choice_correlation']
        self.assertEqual(choices['matched_action_responses_classified'], 1)
        self.assertEqual(choices['correlation_results'][0]['count'], 1)
        self.assertTrue(choices['counts_account_for_all_matched_action_responses'])
        self.assertFalse(report['response_encoding_verified'])
        self.assertFalse(choices['complete_response_encoding_verified'])
        self.assertFalse(report['input_sent'])
        for secret in ('SECRET_NOT_EXPORTED', 'unknownSecretSibling', '96839',
                       str(path)):
            self.assertNotIn(secret, json.dumps(report))

    def test_real_sanitized_envelope_without_actions_stays_incomplete(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'Player.log'
            save(path, source_rows()[:12])
            report = inspect_response_envelopes(path, semantic_choices=True)
        self.assertEqual(report['matched_actions_available_responses'], 1)
        self.assertEqual(report['action_choice_correlation']
                         ['matched_action_responses_classified'], 1)
        self.assertEqual(report['action_choice_correlation']
                         ['correlation_results'][3]['count'], 1)
        self.assertFalse(report['response_encoding_verified'])

    def test_unmatched_response_not_correlated_and_later_valid_request_counted(self):
        actions = [{'actionType': 'ActionType_Pass'}]
        frames = source_rows()[:9] + [action_request(actions),
                                      reply(request_id=990, details={
                                          'actions': [{'actionType': 'ActionType_Pass'}]}),
                                      reply(details={
                                          'actions': [{'actionType': 'ActionType_Pass'}]})]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'Player.log'
            save(path, frames)
            report = inspect_response_envelopes(path, semantic_choices=True)
        self.assertEqual(report['unmatched_or_noncurrent_responses'], 1)
        self.assertEqual(report['action_choice_correlation']
                         ['matched_action_responses_classified'], 1)
        self.assertEqual(report['action_choice_correlation']
                         ['correlation_results'][0]['count'], 1)


if __name__ == '__main__':
    unittest.main()
