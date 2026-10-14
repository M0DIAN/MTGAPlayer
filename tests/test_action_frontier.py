"""MP15 first action frontier on sanitized GRE plus explicit synthetic mutations."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from mtgaplayer.action_frontier import build_action_frontier
from mtgaplayer.cli import replay, watch
from mtgaplayer.raw_log import RawReducer


FIXTURE = Path(__file__).resolve().parents[1] / 'tests/fixtures/player_log_selectn.jsonl'


def source_rows():
    return [json.loads(line) for line in FIXTURE.read_text(encoding='utf-8').splitlines()]


def frames():
    original = source_rows()
    frame = copy.deepcopy(original[9])
    reducer = RawReducer()
    reducer.reset(1)
    for entry in original[:9]:
        reducer.apply(entry)
    hidden = next(zone['objectInstanceIds'][0] for zone in reducer.zones.values()
                  if zone.get('type') == 'ZoneType_Hand' and
                  zone.get('ownerSeatId') == 2)
    request = next(message for message in frame['greToClientEvent']['greToClientMessages']
                   if message.get('type') == 'GREMessageType_ActionsAvailableReq')
    request['actionsAvailableReq'] = {'actions': [
        {'actionType': 'ActionType_Pass'},
        {'actionType': 'ActionType_Play', 'instanceId': 166,
         'grpId': 96839, 'facetId': 0, 'shouldStop': False},
        {'actionType': 'ActionType_Cast', 'instanceId': 161,
         'manaCost': [{'private': 'PRIVATE_COST_SENTINEL'}],
         'targets': [{'targetIdx': 0,
                      'targets': [{'private': 'PRIVATE_TARGET_SENTINEL'}]}],
         'autoTapSolution': {'autoTapActions': [
             {'instanceId': 283, 'abilityGrpId': 7}]}},
        {'actionType': 'ActionType_Activate_Mana', 'instanceId': 283,
         'abilityGrpId': 7, 'manaSelections': []},
        {'actionType': 'ActionType_Activate', 'instanceId': hidden,
         'targets': [{'targetIdx': -3, 'targets': []}],
         'manaCost': 'UNEXPECTED_PRIVATE_VALUE'},
        {'actionType': 'ActionType_FloatMana'},
        {'actionType': 'ActionType_FutureVariant', 'other': 'PRIVATE_UNKNOWN'},
    ]}
    return original[:9] + [frame]


def save(path, rows):
    path.write_text(''.join(json.dumps(row) + '\n' for row in rows),
                    encoding='utf-8')


def _request(rows):
    return next(message for message in rows[-1]['greToClientEvent']['greToClientMessages']
                if message.get('type') == 'GREMessageType_ActionsAvailableReq')


class ActionFrontierTests(unittest.TestCase):
    def test_every_active_position_and_safe_source_boundaries(self):
        rows = frames()
        _request(rows)['actionsAvailableReq']['inactiveActions'] = [
            {'actionType': 'ActionType_Pass'}]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'Player.log'
            save(path, rows)
            plain = replay(path, format='player-log', decision_input=True,
                           action_gaps=True)
            result = replay(path, format='player-log', decision_input=True,
                            action_gaps=True, action_frontier=True)
        self.assertNotIn('action_frontier', plain)
        self.assertNotIn('_frontier_rows', json.dumps(plain))
        report = result.pop('action_frontier')
        self.assertEqual(result, plain)
        self.assertEqual((report['engine_active_action_count'],
                          report['interpreted_action_count'],
                          report['unsupported_action_count']), (7, 4, 3))
        self.assertEqual([x['list_position'] for x in report['templates']],
                         list(range(7)))
        self.assertEqual([x['structurally_interpreted']
                          for x in report['templates']],
                         [True, True, True, True, False, False, False])
        self.assertEqual(report['immediate_completeness'], 'partial')
        self.assertEqual(report['expanded_choice_completeness'], 'unknown')
        self.assertEqual(report['templates'][1]['visible_object_id'], 166)
        self.assertEqual(report['templates'][4]['source_link_status'],
                         'not_in_visible_projection')
        self.assertIsNone(report['templates'][4]['visible_object_id'])
        self.assertEqual(report['templates'][2]['observed_parameter_shapes']
                         ['manaCost']['element_count'], 1)
        self.assertFalse(report['actionable'])
        self.assertIsNone(report['legal_actions'])
        for row in report['templates']:
            self.assertEqual(row['request_identity'], report['request_identity'])
            self.assertEqual(row['action_key'], {
                'request_identity': report['request_identity'],
                'list_position': row['list_position']})
            self.assertIsNone(row['next_choice_request'])
            for key in ('legal_choice_verified', 'execution_ready',
                        'response_encoding_verified', 'actionable', 'input_sent'):
                self.assertFalse(row[key])
        text = json.dumps(report)
        for secret in ('PRIVATE_COST_SENTINEL', 'PRIVATE_TARGET_SENTINEL',
                       'UNEXPECTED_PRIVATE_VALUE', 'PRIVATE_UNKNOWN',
                       'ActionType_FutureVariant', '96839', '_frontier_rows'):
            self.assertNotIn(secret, text)
        self.assertNotIn('_frontier_rows', json.dumps(result))

    def test_duplicate_and_malformed_rows_keep_original_positions(self):
        rows = frames()
        actions = _request(rows)['actionsAvailableReq']['actions']
        actions.extend([
            copy.deepcopy(actions[1]),
            {'actionType': 'ActionType_Pass', 'privateField': 'PRIVATE_FIELD'},
            {'actionType': 'ActionType_Future', 'manaCost': [
                {'private': 'PRIVATE_VALUE'}], 'secretKey': 'PRIVATE_KEY'},
        ])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'Player.log'
            save(path, rows)
            report = replay(path, format='player-log', decision_input=True,
                            action_frontier=True)['action_frontier']
        self.assertEqual(report['engine_active_action_count'], 10)
        self.assertEqual(report['interpreted_action_count'], 5)
        self.assertEqual(report['unsupported_action_count'], 5)
        self.assertEqual([r['list_position'] for r in report['templates']],
                         list(range(10)))
        self.assertTrue(report['templates'][7]['structurally_interpreted'])
        self.assertFalse(report['templates'][8]['structurally_interpreted'])
        self.assertEqual(report['templates'][9]['engine_action_type'],
                         '_unrecognized_action_type')
        self.assertTrue(report['templates'][9]['unknown_parameter_fields_present'])
        self.assertEqual(report['templates'][9]['observed_parameter_shapes']
                         ['manaCost']['element_count'], 1)
        for secret in ('PRIVATE_FIELD', 'PRIVATE_VALUE', 'PRIVATE_KEY',
                       'privateField', 'secretKey', 'ActionType_Future'):
            self.assertNotIn(secret, json.dumps(report))

    def test_complex_bad_known_parameter_without_targets_is_unsupported(self):
        rows = frames()
        actions = _request(rows)['actionsAvailableReq']['actions']
        actions.append({'actionType': 'ActionType_Cast', 'instanceId': 161,
                        'manaCost': 'PRIVATE_BAD_COST'})
        actions.append({'actionType': 'ActionType_Cast', 'instanceId': 161,
                        'autoTapSolution': {}})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'Player.log'
            save(path, rows)
            report = replay(path, format='player-log', decision_input=True,
                            action_frontier=True)['action_frontier']
        self.assertEqual(report['engine_active_action_count'], 9)
        self.assertFalse(report['templates'][7]['structurally_interpreted'])
        self.assertFalse(report['templates'][8]['structurally_interpreted'])
        self.assertEqual(report['templates'][7]['observed_parameter_shapes']
                         ['manaCost']['kind'], 'unexpected')
        self.assertNotIn('PRIVATE_BAD_COST', json.dumps(report))

    def test_no_payload_no_current_or_mismatched_binding_cannot_fill_totals(self):
        rows = frames()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'Player.log'
            save(path, rows)
            current = replay(path, format='player-log', decision_input=True,
                             action_frontier=True)
            frontier = current['action_frontier']
            self.assertEqual(frontier['engine_active_action_count'], 7)
            newer = frames()
            _request(newer)['msgId'] = 38
            save(path, newer)
            changed_request = replay(path, format='player-log',
                                     decision_input=True,
                                     action_frontier=True)['action_frontier']
            self.assertNotEqual(frontier['templates'][0]['action_key'],
                                changed_request['templates'][0]['action_key'])
            evidence = current['current']['request']['action_inventory']
            # The opt-in private evidence has been consumed from public output.
            self.assertNotIn('_frontier_rows', evidence)
            self.assertEqual(build_action_frontier(
                current['decision_input'], {'request_identity': {
                    **frontier['request_identity'], 'request_id': 999},
                    'rows': [None] * 7})['immediate_completeness'], 'unknown')
            _request(rows).pop('actionsAvailableReq')
            save(path, rows)
            missing = replay(path, format='player-log', decision_input=True,
                             action_frontier=True)['action_frontier']
            self.assertEqual(missing['immediate_completeness'], 'unknown')
            self.assertIsNone(missing['engine_active_action_count'])
            self.assertIsNone(missing['templates'])
            save(path, source_rows())
            selectn = replay(path, format='player-log', decision_input=True,
                             action_frontier=True)['action_frontier']
            self.assertEqual(selectn['immediate_completeness'], 'unknown')
            self.assertIsNone(selectn['engine_active_action_count'])
            save(path, rows[:9] + [frames()[9]])
            with path.open('ab') as stream:
                stream.write(b'{"greToClientEvent":')
            partial = replay(path, format='player-log', decision_input=True,
                             action_frontier=True)
            self.assertIsNone(partial['action_frontier'])

    def test_real_response_state_progress_and_watch_stopped_are_read_only(self):
        rows = frames()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'Player.log'
            save(path, rows)
            initial = replay(path, format='player-log', decision_input=True,
                             action_frontier=True)
            self.assertEqual(initial['action_frontier']['engine_active_action_count'], 7)
            original = source_rows()
            save(path, rows + original[10:12])
            consumed = replay(path, format='player-log', decision_input=True,
                              action_frontier=True)
            self.assertIsNone(consumed['action_frontier'])
            save(path, rows + original[10:13])
            progressed = replay(path, format='player-log', decision_input=True,
                                action_frontier=True)
            self.assertIsNone(progressed['action_frontier'])
            save(path, rows)
            final = next(watch(path, interval=0, samples=1,
                               decision_input=True, action_frontier=True))
        self.assertTrue(final['source']['stopped'])
        self.assertIsNotNone(final['action_frontier'])
        self.assertFalse(final['action_frontier']['actionable'])
        self.assertFalse(final['action_frontier']['input_sent'])

    def test_cli_opt_in_and_default_compatibility(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'Player.log'
            save(path, frames())
            executable = Path(sys.prefix) / ('Scripts/mtgaplayer.exe'
                                             if os.name == 'nt' else 'bin/mtgaplayer')
            self.assertTrue(executable.is_file())
            def run(*options):
                return subprocess.run([str(executable), 'replay', *options,
                                       str(path)], capture_output=True,
                                      text=True, check=False)
            default = run('--format', 'player-log')
            enabled = run('--format', 'player-log', '--decision-input',
                          '--action-frontier')
            missing = run('--format', 'player-log', '--action-frontier')
            synthetic = run('--decision-input', '--action-frontier')
            watch_default = subprocess.run(
                [str(executable), 'watch', '--samples', '1', str(path)],
                capture_output=True, text=True, check=False)
            watch_enabled = subprocess.run(
                [str(executable), 'watch', '--samples', '1',
                 '--decision-input', '--action-frontier', str(path)],
                capture_output=True, text=True, check=False)
        self.assertEqual(default.returncode, 0, default.stderr)
        self.assertNotIn('action_frontier', json.loads(default.stdout))
        self.assertEqual(enabled.returncode, 0, enabled.stderr)
        self.assertEqual(json.loads(enabled.stdout)['action_frontier']
                         ['engine_active_action_count'], 7)
        self.assertEqual(missing.returncode, 1)
        self.assertEqual(json.loads(missing.stdout)['error'],
                         'action_frontier_requires_decision_input')
        self.assertEqual(synthetic.returncode, 1)
        self.assertEqual(json.loads(synthetic.stdout)['error'],
                         'decision_input_requires_player_log_format')
        self.assertEqual(watch_default.returncode, 0, watch_default.stderr)
        self.assertNotIn('action_frontier', json.loads(watch_default.stdout))
        self.assertEqual(watch_enabled.returncode, 0, watch_enabled.stderr)
        watched = json.loads(watch_enabled.stdout)
        self.assertEqual(watched['action_frontier']['engine_active_action_count'], 7)
        self.assertTrue(watched['source']['stopped'])
        self.assertFalse(watched['action_frontier']['actionable'])


if __name__ == '__main__':
    unittest.main()
