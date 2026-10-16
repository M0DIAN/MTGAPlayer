"""Producer-derived real v9 episode; raw mutations below are synthetic controls."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from mtgaplayer.choice_validation import validate_proposed_choice
from mtgaplayer.semantic_samples import collect_samples, replay_samples, SampleError
from mtgaplayer.semantic_effect_cost_result import REVIEWED, MISSING, UNSUPPORTED
from test_semantic_effect_cost import baseline, save, request, response, message
from test_raw_log import state

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT/'tests/fixtures/semantic_effect_cost_result_real_v9.json'


def control_rows():
    """Invented finite producer control, never labeled real source evidence."""
    rows = baseline()
    full = state(rows[-1])
    full['gameObjects'].append({'instanceId': 705, 'grpId': 1234, 'type': 'GameObjectType_Ability',
        'zoneId': 27, 'ownerSeatId': 1, 'controllerSeatId': 1, 'visibility': 'Visibility_Public'})
    next(z for z in full['zones'] if z['zoneId'] == 27)['objectInstanceIds'] = [705]
    def detail(key, value):
        typ, field = ('string', 'valueString') if type(value) is str else ('int32', 'valueInt32')
        return {'key': key, 'type': 'KeyValuePairValueType_' + typ, field: [value]}
    after = {'type': 'GameStateType_Diff', 'gameStateId': 2, 'prevGameStateId': 1,
        'zones': [
            {'zoneId': 28, 'type': 'ZoneType_Battlefield', 'visibility': 'Visibility_Public', 'objectInstanceIds': [702]},
            {'zoneId': 33, 'type': 'ZoneType_Graveyard', 'visibility': 'Visibility_Public',
             'ownerSeatId': 1, 'objectInstanceIds': [706]}],
        'gameObjects': [{'instanceId': 706, 'grpId': 987654321, 'type': 'GameObjectType_Card',
            'zoneId': 33, 'ownerSeatId': 1, 'controllerSeatId': 1, 'visibility': 'Visibility_Public'}],
        'annotations': [
            {'id': 801, 'affectorId': 705, 'affectedIds': [701], 'type': ['AnnotationType_ObjectIdChanged'],
             'details': [detail('orig_id', 701), detail('new_id', 706)]},
            {'id': 802, 'affectorId': 705, 'affectedIds': [706], 'type': ['AnnotationType_ZoneTransfer'],
             'details': [detail('zone_src', 28), detail('zone_dest', 33), detail('category', 'Sacrifice')]}]}
    return rows + [request(), response(), {'greToClientEvent': {'greToClientMessages': [{
        'type': 'GREMessageType_GameStateMessage', 'systemSeatIds': [1], 'gameStateMessage': after}]}}]


class EffectCostResultTests(unittest.TestCase):
    def setUp(self):
        self.document = json.loads(FIXTURE.read_text(encoding='utf-8'))
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root/'controls.jsonl'

    def export(self, rows, version=9):
        save(self.path, rows)
        return collect_samples(self.path, schema_version=version, max_samples=256, origin='synthetic')

    def report(self, document):
        return replay_samples(document)['samples'][0]

    def test_real_selected_card_sacrifice_is_distinct_from_complete_payment(self):
        sample = self.document['samples'][0]
        report = self.report(self.document)
        self.assertEqual(report['selected_option_positions'], [1])
        self.assertTrue(report['selected_card_sacrifice_observed'])
        self.assertEqual(report['selected_card_result'], 'observed_explicit_annotation_chain')
        self.assertEqual(sample['trace']['states'][0]['facts_status'], REVIEWED)
        self.assertEqual(sample['trace']['states'][0]['omitted_annotations'], 2)
        self.assertEqual(len(sample['trace']['states']), 1)
        self.assertIsNone(report['source_object_ref'])
        self.assertIsNone(report['parent_activate_causal_relation'])
        for key in ('payment_completed_verified', 'rules_effect_verified', 'complete_legality_verified', 'server_acceptance_verified'):
            self.assertFalse(report[key])
        self.assertFalse(replay_samples(self.document)['raw_source_auth_revalidated'])
        self.assertTrue(all(v is False for v in replay_samples(self.document)['execution'].values()))
        # This version adds facts; it must not rewrite the previously retained real episode.
        old = json.loads((ROOT/'tests/fixtures/semantic_effect_cost_real_v7.json').read_text())['samples'][0]
        normalized = copy.deepcopy(sample)
        normalized['trace']['states'][0].update(facts=[], facts_status='visible_snapshot_only', omitted_annotations=None)
        self.assertEqual(normalized, old)

    def test_actual_cli_roundtrip_and_private_context_omission(self):
        self.export(control_rows())
        output = self.root/'portable.json'
        run = subprocess.run([sys.executable, '-m', 'mtgaplayer', 'export-semantic-samples', str(self.path),
            '--schema-version', '9', '--origin', 'synthetic', '--output', str(output)], capture_output=True, text=True, timeout=10)
        self.assertEqual(run.returncode, 0, run.stderr)
        run = subprocess.run([sys.executable, '-m', 'mtgaplayer', 'replay-semantic-samples', str(output)],
                             capture_output=True, text=True, timeout=10)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertTrue(json.loads(run.stdout)['samples'][0]['selected_card_sacrifice_observed'])
        text = output.read_text()
        for private in ('_cost_selected_raw', 'PRIVATE_PROMPT_SENTINEL', 'fixture-local', 'fixture-match',
                        'payCostsReq', 'effectCostResp', 'gameObjects'):
            self.assertNotIn(private, text)

    def test_producer_same_state_annotation_order_does_not_change_evidence(self):
        forward = self.export(control_rows())
        rows = control_rows(); state(rows[-1])['annotations'].reverse()
        self.assertEqual(self.export(rows), forward)
        self.assertTrue(self.report(forward)['selected_card_sacrifice_observed'])

    def test_missing_or_conflicting_annotation_never_becomes_a_result(self):
        for mode in ('no_mapping', 'no_transfer', 'wrong_category', 'foreign_affector', 'duplicate_mapping',
                     'duplicate_transfer', 'mixed_type', 'float_id', 'extra_private_field'):
            rows = control_rows(); annotations = state(rows[-1])['annotations']
            if mode == 'no_mapping': annotations.pop(0)
            elif mode == 'no_transfer': annotations.pop()
            elif mode == 'wrong_category': annotations[1]['details'][-1]['valueString'] = ['Destroy']
            elif mode == 'foreign_affector': annotations[1]['affectorId'] = 702
            elif mode.startswith('duplicate'): annotations.insert(0, copy.deepcopy(annotations[0 if mode.endswith('mapping') else 1]))
            elif mode == 'mixed_type': annotations[0]['type'].append('Unknown')
            elif mode == 'float_id': annotations[0]['details'][1]['valueInt32'] = [706.0]
            else: annotations[0]['PRIVATE_UNKNOWN'] = 'PRIVATE_VALUE'
            with self.subTest(mode=mode):
                doc = self.export(rows); result = self.report(doc)
                self.assertTrue(result['selection_submission_observed'])
                self.assertFalse(result['selected_card_sacrifice_observed'])
                self.assertEqual(doc['samples'][0]['trace']['states'][0]['facts'], [])
                self.assertNotIn('PRIVATE_VALUE', json.dumps(doc))

    def test_public_endpoint_identity_and_membership_must_correspond(self):
        for mode in ('old_still_visible', 'target_already_visible', 'new_hidden', 'different_card', 'wrong_owner', 'affector_not_stack'):
            rows = control_rows(); before = state(rows[2]); after = state(rows[-1])
            if mode == 'old_still_visible': after['zones'][0]['objectInstanceIds'].append(701)
            elif mode == 'target_already_visible':
                obj = copy.deepcopy(after['gameObjects'][0]); before['gameObjects'].append(obj)
                next(z for z in before['zones'] if z['zoneId'] == 33)['objectInstanceIds'] = [706]
            elif mode == 'new_hidden': after['gameObjects'][0]['visibility'] = 'Visibility_Hidden'
            elif mode == 'different_card': after['gameObjects'][0]['grpId'] += 1
            elif mode == 'wrong_owner': after['gameObjects'][0]['ownerSeatId'] = 2
            else:
                source = before['gameObjects'][-1]; source['zoneId'] = 28
                next(z for z in before['zones'] if z['zoneId'] == 27)['objectInstanceIds'] = []
                next(z for z in before['zones'] if z['zoneId'] == 28)['objectInstanceIds'].append(705)
            with self.subTest(mode=mode):
                self.assertFalse(self.report(self.export(rows))['selected_card_sacrifice_observed'])

    def test_wrong_response_gap_eof_and_first_successor_are_not_repaired_by_future(self):
        rows = control_rows(); rows[4]['payload']['respId'] += 1
        self.assertEqual(self.export(rows)['counts']['exported'], 0)
        rows = control_rows(); state(rows[-1])['prevGameStateId'] = 999
        self.assertFalse(self.report(self.export(rows))['selected_card_sacrifice_observed'])
        self.assertFalse(self.report(self.export(control_rows()[:-1]))['selected_card_sacrifice_observed'])
        rows = control_rows(); later = copy.deepcopy(rows[-1]); gs = state(later)
        gs['gameStateId'] = 3; gs['prevGameStateId'] = 2
        rows[-1] = {'greToClientEvent': {'greToClientMessages': [{'type': 'GREMessageType_GameStateMessage',
            'systemSeatIds': [1], 'gameStateMessage': {'type': 'GameStateType_Diff', 'gameStateId': 2, 'prevGameStateId': 1}}]}}
        rows.append(later)
        self.assertFalse(self.report(self.export(rows))['selected_card_sacrifice_observed'])

    def test_portable_result_cannot_lend_actual_outcome_to_another_choice(self):
        for mode in ('choice', 'affector', 'target', 'incomplete_facts', 'unknown_with_facts', 'malformed_sample'):
            doc = copy.deepcopy(self.document); sample = doc['samples'][0]
            facts = sample['trace']['states'][0]['facts']
            if mode == 'choice': sample['response']['payload']['selected_object_refs'] = sample['request']['payload']['offered_object_refs'][:1]
            elif mode == 'affector': facts[1]['observed_affector_ref'] += 1000
            elif mode == 'target': facts[0]['new_object_ref'] = float(facts[0]['new_object_ref'])
            elif mode == 'incomplete_facts': facts.pop()
            elif mode == 'unknown_with_facts': sample['trace']['states'][0]['facts_status'] = UNSUPPORTED
            else: doc['samples'] = [None]
            with self.subTest(mode=mode), self.assertRaises(SampleError):
                replay_samples(doc)

    def test_state6_choices_and_legacy_cost_versions_still_have_no_future_result(self):
        current = json.loads((ROOT/'tests/fixtures/decision_state_effect_cost_real_v6.json').read_text())
        offered = current['legal_action_space']['request_parameters']['cost_selection']['offered_object_refs']
        for ref in offered:
            result = validate_proposed_choice(current, {'request_identity': current['binding'],
                       'proposed_cost_selection': {'selected_object_refs': [ref]}})
            self.assertEqual(result['known_constraints'], 'verified_known_constraints')
            self.assertFalse(result['payment_completed_verified'])
            self.assertNotIn('selected_card_sacrifice_observed', result)
        for version in (7, 8):
            doc = self.export(control_rows(), version)
            self.assertEqual(doc['samples'][0]['trace']['states'][0]['facts'], [])
            self.assertNotIn('selected_card_sacrifice_observed', self.report(doc))


if __name__ == '__main__':
    unittest.main()
