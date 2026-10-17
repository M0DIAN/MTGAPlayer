import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from mtgaplayer.raw_log import RawFollower
from mtgaplayer.semantic_samples import collect_samples, replay_samples, SampleError
from mtgaplayer.semantic_activate_targets import collect_records, VERSION


FIXTURES = Path(__file__).parent / 'fixtures'


class ActivateTargetTests(unittest.TestCase):
    def setUp(self):
        self.document = json.loads((FIXTURES / 'semantic_activate_targets_real_v10.json').read_text())

    def sample(self, document=None):
        return (document or self.document)['samples'][0]

    def report(self, document=None):
        return replay_samples(document or self.document)['samples'][0]

    def test_real_equip_chain_and_explicit_limits(self):
        self.assertEqual(self.document['schema_version'], VERSION)
        self.assertEqual(self.document['counts'], dict(matched_pairs=1, exported=1,
            sample_limit_omissions=0, unsupported_pairs=0))
        report = self.report()
        self.assertEqual(report['selected_action_position'], 6)
        self.assertEqual(report['validation_level'], 'verified_known_constraints')
        for key in ('actual_activate_submission_observed', 'public_parent_group_creation_observed',
                    'target_request_linked_to_created_ability', 'actual_target_selection_and_final_submit_observed',
                    'actual_selected_set_satisfies_explicit_request_bounds', 'public_targets_submitted_observed',
                    'same_ability_resolution_and_deletion_observed', 'public_attachment_endpoints_observed'):
            self.assertIs(report[key], True, key)
        self.assertFalse(report['continuation_unique_ability_identity_verified'])
        self.assertFalse(report['effect_causation_verified'])
        replay = replay_samples(self.document)
        self.assertFalse(replay['raw_source_auth_revalidated'])
        self.assertFalse(any(replay['execution'].values()))
        self.assertEqual(self.sample()['targets'][0]['request']['selected_count'], None)
        self.assertEqual(self.sample()['targets'][1]['request']['selected_count'], 1)
        self.assertTrue(self.sample()['priority_requests'])
        self.assertEqual(self.sample()['trace']['status'], 'explicit_ability_deleted')

    def test_fixture_has_only_public_endpoints_and_no_catalog_or_highlight_values(self):
        sample = self.sample()
        snapshots = [sample['before'], *[row['snapshot'] for row in sample['trace']['states']]]
        for snapshot in snapshots:
            for obj in snapshot['objects']:
                self.assertIsNone(obj['card_id'])
                self.assertIn(obj['zone'], ('ZoneType_Battlefield', 'ZoneType_Stack'))
        for row in sample['request']['payload']['rows']:
            self.assertFalse(row['structurally_interpreted'])
        actual = [row for row in sample['request']['payload']['rows'] if row['selected_literal'] is not None]
        self.assertEqual(len(actual), 1)
        self.assertNotIn('highlight', actual[0]['selected_literal']['parameters']['targets'][0]['targets'][0])

    def test_counterfactual_response_or_unchosen_position_cannot_borrow_result(self):
        for change in ('position', 'response', 'pair', 'duplicate_literal'):
            with self.subTest(change=change):
                document = copy.deepcopy(self.document); sample = self.sample(document)
                if change == 'position': sample['request']['payload']['selected_position'] = 0
                elif change == 'response': sample['response']['payload']['action']['identifier_refs']['uniqueAbilityId'] += 100
                elif change == 'pair': sample['source_observation']['ability_grp_ref'] += 100
                else: sample['request']['payload']['rows'][0]['selected_literal'] = copy.deepcopy(sample['response']['payload']['action'])
                with self.assertRaises(SampleError): replay_samples(document)

    def test_wrong_generation_game_match_seat_state_and_boolean_bindings(self):
        for field in ('generation_ref', 'match_ref', 'game', 'self_seat', 'state_ref', 'request_ref'):
            with self.subTest(field=field):
                document = copy.deepcopy(self.document)
                binding = self.sample(document)['targets'][0]['binding']
                binding[field] = True if field == 'request_ref' else binding[field] + 100
                with self.assertRaises(SampleError): replay_samples(document)

    def test_changed_slot_duplicate_target_and_final_set_mismatch(self):
        for change in ('slot', 'duplicate', 'selected_set', 'count', 'bounds'):
            with self.subTest(change=change):
                document = copy.deepcopy(self.document); steps = self.sample(document)['targets']
                if change == 'slot': steps[0]['response']['target_idx'] += 1
                elif change == 'duplicate': steps[0]['request']['entries'] *= 2
                elif change == 'selected_set': steps[1]['request']['entries'][0]['object_ref'] += 1000
                elif change == 'count': steps[1]['request']['selected_count'] = 0
                else: steps[1]['request']['min_targets'] = steps[1]['request']['max_targets'] = 2
                with self.assertRaises(SampleError): replay_samples(document)

    def test_parent_group_or_parent_action_slot_mismatch_is_unknown(self):
        for field in ('ability_grp_ref', 'target_idx'):
            document = copy.deepcopy(self.document); sample = self.sample(document)
            for step in sample['targets']: step['request'][field] += 100
            if field == 'target_idx': sample['targets'][0]['response']['target_idx'] += 100
            report = self.report(document)
            self.assertEqual(report['validation_level'], 'insufficient_evidence')
            self.assertFalse(report['target_request_linked_to_created_ability'])
            self.assertFalse(report['public_attachment_endpoints_observed'])

    def test_missing_bounds_are_unknown_not_inferred_from_parent_menu(self):
        document = copy.deepcopy(self.document)
        for step in self.sample(document)['targets']: step['request']['min_targets'] = None
        report = self.report(document)
        self.assertEqual(report['validation_level'], 'insufficient_evidence')
        self.assertFalse(report['actual_selected_set_satisfies_explicit_request_bounds'])

    def test_additional_unanswered_choice_prevents_complete_chain(self):
        document = copy.deepcopy(self.document); sample = self.sample(document)
        extra = copy.deepcopy(sample['targets'][-1])
        extra['location'] = {'record': 1427, 'message': 2}
        extra['binding']['request_ref'] += 1000
        extra['binding']['state_ref'] = sample['trace']['states'][3]['snapshot']['state_ref']
        extra['response'] = extra['response_location'] = None
        sample['targets'].append(extra)
        self.assertEqual(self.report(document)['validation_level'], 'insufficient_evidence')

    def test_missing_result_or_interrupted_trace_cannot_borrow_suffix(self):
        for status in ('eof', 'interrupted', 'full_baseline_not_continuous', 'limit_reached'):
            with self.subTest(status=status):
                document = copy.deepcopy(self.document); sample = self.sample(document)
                sample['trace']['states'].pop()
                sample['trace']['status'] = status
                sample['priority_requests'] = []
                report = self.report(document)
                self.assertEqual(report['validation_level'], 'insufficient_evidence')
                self.assertFalse(report['same_ability_resolution_and_deletion_observed'])
                self.assertFalse(report['public_attachment_endpoints_observed'])
        document = copy.deepcopy(self.document)
        self.sample(document)['trace']['states'][-1]['attachments'] = []
        report = self.report(document)
        self.assertEqual(report['validation_level'], 'insufficient_evidence')
        self.assertTrue(report['same_ability_resolution_and_deletion_observed'])
        self.assertFalse(report['public_attachment_endpoints_observed'])
        document = copy.deepcopy(self.document); states = self.sample(document)['trace']['states']
        states[3]['attachments'] = states[-1]['attachments']; states[-1]['attachments'] = []
        report = self.report(document)
        self.assertEqual(report['validation_level'], 'insufficient_evidence')
        self.assertFalse(report['attachment_and_ability_resolution_same_message_observed'])

    def test_wrong_attachment_endpoints_hidden_target_and_ambiguous_creation_rejected(self):
        for change in ('source', 'target', 'hidden', 'duplicate_creation'):
            with self.subTest(change=change):
                document = copy.deepcopy(self.document); sample = self.sample(document)
                final = sample['trace']['states'][-1]
                if change in ('source', 'target'): final['attachments'][0][change + '_object_ref'] += 1000
                elif change == 'hidden':
                    target = final['attachments'][0]['target_object_ref']
                    next(obj for obj in final['snapshot']['objects'] if obj['object_ref'] == target)['zone'] = 'ZoneType_Hand'
                else: sample['trace']['states'][0]['facts'] *= 2
                with self.assertRaises(SampleError): replay_samples(document)

    def test_request_supersession_between_selection_and_response_rejected(self):
        document = copy.deepcopy(self.document); sample = self.sample(document)
        checkpoint = copy.deepcopy(sample['priority_requests'][0])
        checkpoint['location'] = {'record': 1423, 'message': 0}
        checkpoint['binding']['state_ref'] = sample['targets'][0]['binding']['state_ref']
        sample['priority_requests'] = [checkpoint]
        with self.assertRaises(SampleError): replay_samples(document)

    def test_accepted_state_revokes_request_and_payload_cannot_share_gre_record(self):
        for message in (None, 0):
            document = copy.deepcopy(self.document)
            self.sample(document)['targets'][0]['response_location'] = {'record': 1425, 'message': message}
            with self.assertRaises(SampleError): replay_samples(document)
        document = copy.deepcopy(self.document)
        self.sample(document)['targets'][0]['response_location']['message'] = 1
        with self.assertRaises(SampleError): replay_samples(document)

    def test_lifecycle_cannot_precede_submit_reverse_or_repeat(self):
        for change in ('early_start', 'early_start_complete', 'reversed', 'duplicate', 'late_public_submission'):
            with self.subTest(change=change):
                document = copy.deepcopy(self.document); states = self.sample(document)['trace']['states']
                if change.startswith('early'):
                    kinds = {'resolution_start', 'resolution_complete'} if change == 'early_start_complete' else {'resolution_start'}
                    moved = [fact for fact in states[-1]['facts'] if fact['kind'] in kinds]
                    states[-1]['facts'] = [fact for fact in states[-1]['facts'] if fact['kind'] not in kinds]
                    states[1]['facts'].extend(moved)
                elif change == 'reversed': states[-1]['facts'][0:2] = list(reversed(states[-1]['facts'][0:2]))
                elif change == 'duplicate': states[-1]['facts'].append(copy.deepcopy(states[-1]['facts'][0]))
                else:
                    states[-1]['target_submissions'] = states[2]['target_submissions']
                    states[2]['target_submissions'] = []
                with self.assertRaises(SampleError): replay_samples(document)

    def test_unsupported_annotations_and_impossible_source_positions_do_not_certify(self):
        document = copy.deepcopy(self.document)
        self.sample(document)['trace']['states'][-1]['facts_status'] = 'unsupported_relevant_annotation'
        report = self.report(document)
        self.assertEqual(report['validation_level'], 'insufficient_evidence')
        self.assertFalse(report['relevant_annotation_profile_supported'])
        for change in ('out_of_source', 'after_episode', 'target_state_collision', 'priority_state_collision', 'request_message_none'):
            with self.subTest(change=change):
                document = copy.deepcopy(self.document); sample = self.sample(document)
                if change == 'out_of_source': sample['priority_requests'][0]['location']['record'] = 999999
                elif change == 'after_episode': sample['priority_requests'][0]['location']['record'] += 1
                elif change == 'target_state_collision': sample['targets'][0]['location'] = copy.deepcopy(sample['trace']['states'][0]['location'])
                elif change == 'priority_state_collision': sample['priority_requests'][0]['location'] = copy.deepcopy(sample['trace']['states'][-1]['location'])
                else: sample['priority_requests'][0]['location']['message'] = None
                with self.assertRaises(SampleError): replay_samples(document)

    def negative_records(self):
        """Synthetic NEGATIVES derived from the old offered-only real prefix.

        The fabricated response is used only with a deliberately broken binding;
        it is never retained or asserted as a real targeted positive.
        """
        follower = RawFollower(FIXTURES / 'player_log_activate_generic_two.jsonl')
        _, rows = follower.poll()
        prefix = copy.deepcopy(rows[:5])
        message = next(message for record in prefix for message in
            record.get('greToClientEvent', {}).get('greToClientMessages', [])
            if message['type'] == 'GREMessageType_ActionsAvailableReq')
        response = copy.deepcopy(rows[5])
        response['payload']['performActionResp']['actions'] = [copy.deepcopy(message['actionsAvailableReq']['actions'][2])]
        return prefix, message, response

    def test_raw_current_gate_rejects_wrong_recipient_digest_supersession_and_gap(self):
        for change in ('recipient', 'digest', 'supersession', 'gap', 'response_id'):
            with self.subTest(change=change):
                prefix, request, response = self.negative_records()
                if change == 'recipient': request['systemSeatIds'] = [2 if request['systemSeatIds'] == [1] else 1]
                elif change in ('digest', 'supersession'):
                    next_request = copy.deepcopy(request)
                    if change == 'digest': next_request['actionsAvailableReq']['actions'][2]['shouldStop'] = not next_request['actionsAvailableReq']['actions'][2]['shouldStop']
                    else: next_request['msgId'] += 1
                    prefix.append({'greToClientEvent': {'greToClientMessages': [next_request]}})
                elif change == 'gap':
                    prefix.append({'greToClientEvent': {'greToClientMessages': [{
                        'type': 'GREMessageType_GameStateMessage', 'systemSeatIds': request['systemSeatIds'],
                        'gameStateMessage': {'type': 'GameStateType_Diff',
                            'gameStateId': request['gameStateId'] + 3, 'prevGameStateId': request['gameStateId'] + 2}}]}})
                else: response['payload']['respId'] += 100
                document = collect_records([*prefix, response], 1, 'synthetic', 16)
                self.assertEqual(document['counts']['exported'], 0)

    def test_real_old_no_target_activate_is_not_relabelled_and_default_stays_v1(self):
        path = FIXTURES / 'player_log_activate_generic_two.jsonl'
        self.assertEqual(collect_samples(path)['schema_version'], 'mtgaplayer.semantic-samples.v1')
        document = collect_samples(path, schema_version=10)
        self.assertEqual(document['counts']['matched_pairs'], 0)

    def test_raw_source_pair_ambiguity_boolean_identity_and_unknown_highlight_are_withheld(self):
        for change in ('pair', 'duplicate_identity', 'boolean_identity', 'unknown_highlight'):
            with self.subTest(change=change):
                prefix, request, response = self.negative_records()
                selected = response['payload']['performActionResp']['actions'][0]
                if change == 'pair':
                    changed = False
                    for record in prefix:
                        for message in record.get('greToClientEvent', {}).get('greToClientMessages', []):
                            for obj in message.get('gameStateMessage', {}).get('gameObjects', []):
                                if obj.get('instanceId') == selected['instanceId']:
                                    for pair in obj.get('uniqueAbilities', []):
                                        if pair['id'] == selected['uniqueAbilityId']:
                                            pair['grpId'] += 100; changed = True
                    self.assertTrue(changed)
                elif change == 'duplicate_identity':
                    duplicate = copy.deepcopy(selected)
                    duplicate['targets'][0]['targets'][0]['highlight'] = 'PRIVATE_SENTINEL'
                    request['actionsAvailableReq']['actions'].append(duplicate)
                elif change == 'boolean_identity': selected['uniqueAbilityId'] = True
                else:
                    for row in (selected, request['actionsAvailableReq']['actions'][2]):
                        row['targets'][0]['targets'][0]['highlight'] = {'private': 'PRIVATE_SENTINEL'}
                document = collect_records([*prefix, response], 1, 'synthetic', 16)
                self.assertEqual(document['counts']['exported'], 0)
                self.assertEqual(document['counts']['unsupported_pairs'], 1)
                self.assertNotIn('PRIVATE_SENTINEL', json.dumps(document))

    def test_explicit_cli_portable_replay_and_duplicate_key_failure_are_read_only(self):
        path = FIXTURES / 'semantic_activate_targets_real_v10.json'
        run = subprocess.run([sys.executable, '-m', 'mtgaplayer', 'replay-semantic-samples', str(path)],
                             capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(json.loads(run.stdout)['schema_version'], 'mtgaplayer.semantic-sample-replay.v10')
        with tempfile.TemporaryDirectory() as directory:
            duplicate = Path(directory) / 'duplicate.json'
            duplicate.write_text('{"schema_version":1,"schema_version":2}')
            run = subprocess.run([sys.executable, '-m', 'mtgaplayer', 'replay-semantic-samples', str(duplicate)],
                                 capture_output=True, text=True)
            self.assertNotEqual(run.returncode, 0)
            self.assertFalse(json.loads(run.stdout)['input_sent'])


if __name__ == '__main__':
    unittest.main()
