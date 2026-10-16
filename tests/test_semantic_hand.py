"""Two curated real episodes; all mutations below are synthetic controls."""
import copy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from mtgaplayer.semantic_samples import collect_samples, replay_samples, SampleError
from mtgaplayer.semantic_hand import (FIRST, UNKNOWN, facts,
    project_request, project_response)
from test_response_evidence import source_rows, action_request

FIXTURES = Path(__file__).parent / 'fixtures'
FIXTURE = FIXTURES / 'semantic_hand_real_v6.json'


class IdentityRefs:
    def ref(self, domain, scope, value):
        return value


class SemanticHandTests(unittest.TestCase):
    def setUp(self):
        self.document = json.loads(FIXTURE.read_text(encoding='utf-8'))

    def evidence(self, index=1):
        return replay_samples(self.document)['samples'][index]

    def after(self, index=1):
        return self.document['samples'][index]['trace']['states'][0]['snapshot']

    def synchronize_successor(self, index=1):
        sample = self.document['samples'][index]
        sample['successor']['snapshot'] = copy.deepcopy(sample['trace']['states'][0]['snapshot'])

    def test_curated_real_values_and_unknowns_are_not_complete_legality(self):
        self.assertEqual(self.document['counts'], {'matched_pairs': 2, 'exported': 2,
            'sample_limit_omissions': 0, 'unsupported_pairs': 0})
        self.assertEqual(self.document['source']['framed_records'], 278)
        result = replay_samples(self.document)
        keep, discard = result['samples']
        self.assertTrue(keep['mulligan_evidence']['accept_hand_submission_observed'])
        self.assertTrue(keep['mulligan_evidence']['first_visible_hand_refs_preserved'])
        self.assertEqual((keep['visible_own_hand_count_before'], keep['visible_own_hand_count_after']), (7,7))
        self.assertEqual(discard['selected_option_positions'], [4])
        self.assertEqual((discard['visible_own_hand_count_before'], discard['visible_own_hand_count_after']), (8,7))
        self.assertTrue(discard['discard_evidence']['selected_card_discard_observed'])
        for sample in self.document['samples']:
            self.assertEqual(sample['trace']['status'], FIRST)
            self.assertEqual(len(sample['trace']['states']), 1)
            self.assertFalse(sample['provenance']['private_auth_revalidated_by_replay'])
        self.assertTrue(all(self.document['samples'][1]['request']['payload'][key] is None for key in UNKNOWN))
        self.assertFalse(result['raw_source_auth_revalidated'])
        self.assertFalse(result['complete_legality_verified'])
        self.assertFalse(result['server_acceptance_verified'])
        self.assertTrue(all(value is False for value in result['execution'].values()))

    def test_previous_state_and_transfer_references_require_strict_integers(self):
        baseline = copy.deepcopy(self.document)
        for value in (True, 1.0):
            with self.subTest(previous=value):
                self.document = copy.deepcopy(baseline)
                self.document['samples'][0]['trace']['states'][0]['previous_state_ref'] = value
                with self.assertRaises(SampleError):
                    replay_samples(self.document)
        target = baseline['samples'][1]['trace']['states'][0]['facts'][1]['object_ref']
        for value in (True, float(target)):
            with self.subTest(transfer=value):
                self.document = copy.deepcopy(baseline)
                self.document['samples'][1]['trace']['states'][0]['facts'][1]['object_ref'] = value
                with self.assertRaises(SampleError):
                    replay_samples(self.document)

    def test_missing_or_changed_card_identity_cannot_prove_discard(self):
        baseline = copy.deepcopy(self.document)
        for mode in ('both_unknown', 'after_unknown', 'changed'):
            with self.subTest(mode=mode):
                self.document = copy.deepcopy(baseline)
                sample = self.document['samples'][1]
                selected = sample['response']['payload']['selected_object_refs'][0]
                migrated = sample['trace']['states'][0]['facts'][0]['new_object_ref']
                old = next(o for o in sample['before']['objects'] if o['object_ref'] == selected)
                new = next(o for o in self.after()['objects'] if o['object_ref'] == migrated)
                if mode == 'both_unknown':
                    old['card_id'] = new['card_id'] = None
                elif mode == 'after_unknown':
                    new['card_id'] = None
                else:
                    new['card_id'] = 987654
                self.synchronize_successor()
                evidence = self.evidence()['discard_evidence']
                self.assertFalse(evidence['selected_card_discard_observed'])
                self.assertEqual(evidence['selected_card_result'], 'insufficient_evidence')

    def test_original_still_visible_is_not_a_selected_id_migration(self):
        sample = self.document['samples'][1]
        selected = sample['response']['payload']['selected_object_refs'][0]
        old = next(o for o in sample['before']['objects'] if o['object_ref'] == selected)
        self.after()['objects'].append(copy.deepcopy(old))
        self.synchronize_successor()
        with self.assertRaises(SampleError):
            replay_samples(self.document)

    def test_independent_hand_change_does_not_erase_explicit_selected_discard(self):
        extra = copy.deepcopy(next(o for o in self.after()['objects'] if o['zone'] == 'ZoneType_Hand'))
        extra['object_ref'] = max(o['object_ref'] for o in self.after()['objects']) + 100
        self.after()['objects'].append(extra)
        self.synchronize_successor()
        result = self.evidence()
        self.assertEqual(result['visible_own_hand_count_after'], 8)
        self.assertTrue(result['discard_evidence']['selected_card_discard_observed'])

    def test_endpoint_count_or_migration_without_discard_fact_is_insufficient(self):
        sample = self.document['samples'][1]
        sample['trace']['states'][0]['facts'] = sample['trace']['states'][0]['facts'][:1]
        self.assertFalse(self.evidence()['discard_evidence']['selected_card_discard_observed'])
        sample['trace']['states'][0]['facts'] = []
        self.assertFalse(self.evidence()['discard_evidence']['selected_card_discard_observed'])

    def test_duplicate_source_annotations_remain_bounded_and_insufficient(self):
        sample = self.document['samples'][1]
        previous = sample['before']
        following = self.after()
        original = sample['response']['payload']['selected_object_refs'][0]
        target = sample['trace']['states'][0]['facts'][0]['new_object_ref']
        def annotation(kind, affected, values):
            return {'id': 1, 'type': [kind], 'affectedIds': [affected], 'details': [
                {'key': key, 'type': 'KeyValuePairValueType_string' if type(value) is str else 'KeyValuePairValueType_int32',
                 'valueString' if type(value) is str else 'valueInt32': [value]}
                for key, value in values.items()]}
        migration = annotation('AnnotationType_ObjectIdChanged', original, {'orig_id': original, 'new_id': target})
        transfer = annotation('AnnotationType_ZoneTransfer', target, {'zone_src': 1, 'zone_dest': 2, 'category': 'Discard'})
        reducer = SimpleNamespace(zones={1: {'type': 'ZoneType_Hand'}, 2: {'type': 'ZoneType_Graveyard'}})
        for rows in ([migration, migration, transfer], [migration, transfer, transfer]):
            projected, status, omitted = facts({'annotations': rows}, reducer, IdentityRefs(), (),
                previous, following, sample['request'], sample['response'], sample['identity']['self_seat'])
            self.assertEqual(len(projected), 2)
            self.assertEqual(status, 'unsupported_hand_annotation')
            self.assertEqual(omitted, 1)
            sample['trace']['states'][0].update(facts=projected, facts_status=status, omitted_annotations=omitted)
            self.assertFalse(self.evidence()['discard_evidence']['selected_card_discard_observed'])

    def test_missing_constraints_cannot_be_filled_with_resolution_defaults(self):
        baseline = copy.deepcopy(self.document)
        for key, value in (('allow_cancel', False), ('source_object_ref', 0),
                           ('min_weight', -2147483648), ('unfiltered_domain', [])):
            with self.subTest(key=key):
                self.document = copy.deepcopy(baseline)
                self.document['samples'][1]['request']['payload'][key] = value
                with self.assertRaises(SampleError):
                    replay_samples(self.document)

    def test_selected_count_membership_and_current_visible_hand_are_checked(self):
        baseline = copy.deepcopy(self.document)
        for mode in ('duplicate', 'outside', 'non_hand_candidate', 'unknown_min'):
            with self.subTest(mode=mode):
                self.document = copy.deepcopy(baseline)
                sample = self.document['samples'][1]
                if mode == 'duplicate':
                    sample['response']['payload']['selected_object_refs'] *= 2
                elif mode == 'outside':
                    sample['response']['payload']['selected_object_refs'] = [999999]
                elif mode == 'unknown_min':
                    sample['request']['payload']['min_sel'] = None
                else:
                    obj = next(o for o in sample['before']['objects'] if o['zone'] == 'ZoneType_Battlefield')
                    sample['request']['payload']['offered_object_refs'][0] = obj['object_ref']
                with self.assertRaises(SampleError):
                    replay_samples(self.document)

    def test_only_first_successor_and_mulligan_ref_set_scope(self):
        sample = self.document['samples'][0]
        # Card catalog identity is outside this specifically named ref-set fact.
        self.after(0)['objects'][0]['card_id'] = None
        self.synchronize_successor(0)
        self.assertTrue(self.evidence(0)['mulligan_evidence']['first_visible_hand_refs_preserved'])
        sample['trace']['states'].append(copy.deepcopy(sample['trace']['states'][0]))
        with self.assertRaises(SampleError):
            replay_samples(self.document)

    def test_raw_hand_projectors_keep_prompt_literal_and_reject_extra_constraints(self):
        before = self.document['samples'][1]['before']
        seat = self.document['samples'][1]['identity']['self_seat']
        scope = (1, 'synthetic-match', 1, seat)
        ids = self.document['samples'][1]['request']['payload']['offered_object_refs']
        message = {'type': 'GREMessageType_SelectNReq', 'systemSeatIds': [seat], 'msgId': 37,
            'gameStateId': 23, 'prompt': {'promptId': 123, 'parameters': [
                {'parameterName': 'PRIVATE_PROMPT_SENTINEL', 'type': 'ParameterType_Number', 'numberValue': 1}]},
            'selectNReq': {'minSel': 1, 'maxSel': 1, 'ids': ids, 'context': 'SelectionContext_Discard',
                'optionContext': 'OptionContext_TurnBased', 'listType': 'SelectionListType_Dynamic',
                'idType': 'IdType_InstanceId', 'validationType': 'SelectionValidationType_NonRepeatable'}}
        projected = project_request(message, IdentityRefs(), scope, before)
        self.assertEqual(projected['payload']['prompt_numbers'], [1])
        self.assertNotIn('PRIVATE_PROMPT_SENTINEL', json.dumps(projected))
        response = {'type': 'ClientMessageType_SelectNResp', 'respId': 37, 'gameStateId': 23,
                    'selectNResp': {'ids': [ids[4]]}}
        self.assertEqual(project_response(response, projected, IdentityRefs(), scope)['payload']['selected_object_refs'], [ids[4]])
        message['selectNReq']['allowCancel'] = False
        with self.assertRaisesRegex(SampleError, 'request_unsupported'):
            project_request(message, IdentityRefs(), scope, before)

    def test_existing_source_gate_consumption_still_controls_new_mulligan_export(self):
        rows = [row for row in source_rows()[:9] if 'payload' not in row]
        request = action_request([{'actionType': 'ActionType_Pass'}])
        header = request['greToClientEvent']['greToClientMessages'][-1]
        request['greToClientEvent']['greToClientMessages'][-1] = {
            **{key: header[key] for key in ('systemSeatIds', 'msgId', 'gameStateId')},
            'type': 'GREMessageType_MulliganReq', 'mulliganReq': {'mulliganType': 'MulliganType_London'},
            'prompt': {'promptId': 123, 'parameters': [{'parameterName': 'count',
                'type': 'ParameterType_Number', 'numberValue': 7}]}}
        response = {'payload': {'type': 'ClientMessageType_MulliganResp', 'respId': header['msgId'],
            'gameStateId': header['gameStateId'], 'mulliganResp': {'decision': 'MulliganOption_AcceptHand'}}}
        diff = {'greToClientEvent': {'greToClientMessages': [{'type': 'GREMessageType_GameStateMessage',
            'systemSeatIds': header['systemSeatIds'], 'gameStateMessage': {'type': 'GameStateType_Diff',
                'gameStateId': 24, 'prevGameStateId': 23}}]}}
        (ROOT / '.tmp').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / '.tmp') as temporary:
            path = Path(temporary) / 'synthetic.log'
            def collect(entries):
                path.write_text(''.join(json.dumps(row) + '\n' for row in entries), encoding='utf-8')
                return collect_samples(path, schema_version=6, origin='synthetic')
            self.assertEqual(collect([*rows, request, response, diff])['counts']['exported'], 1)
            bad = copy.deepcopy(response)
            bad['payload']['respId'] += 1000
            self.assertEqual(collect([*rows, request, bad, diff])['counts']['matched_pairs'], 0)
            bad = copy.deepcopy(response)
            bad['payload']['mulliganResp']['decision'] = 'MulliganOption_Mulligan'
            self.assertEqual(collect([*rows, request, bad, diff])['unsupported_reasons'],
                             [{'reason': 'response_unsupported', 'count': 1}])

    def test_v6_keeps_v4_target_cross_episode_links_and_cast_combat_evidence(self):
        for name in ('player_log_single_target.jsonl', 'player_log_cast_generic_one.jsonl',
                     'player_log_combat_blockers.jsonl'):
            with self.subTest(fixture=name):
                old = replay_samples(collect_samples(FIXTURES / name, schema_version=4, max_samples=256))
                new = replay_samples(collect_samples(FIXTURES / name, schema_version=6, max_samples=256))
                for field in ('target_evidence', 'cast_evidence', 'combat_evidence'):
                    a = [row[field] for row in old['samples'] if field in row]
                    b = [row[field] for row in new['samples'] if field in row]
                    self.assertEqual(a, b)


if __name__ == '__main__':
    unittest.main()
