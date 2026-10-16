"""One producer-derived real episode; raw-envelope controls are synthetic."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from mtgaplayer.semantic_samples import collect_samples, replay_samples, SampleError
from mtgaplayer.semantic_effect_cost import (PROFILE, FIRST, project_request,
    check_request, check_selection, projection)
from test_combat_frontier import baseline, save

FIXTURE = Path(__file__).parent / 'fixtures' / 'semantic_effect_cost_real_v7.json'


class IdentityRefs:
    def ref(self, domain, scope, value):
        return value


def request(ids=(701,), ident=990):
    return {'greToClientEvent': {'greToClientMessages': [{
        'type': 'GREMessageType_PayCostsReq', 'systemSeatIds': [1], 'msgId': ident, 'gameStateId': 1,
        'prompt': {'promptId': 123, 'parameters': [{'parameterName': 'PRIVATE_PROMPT_SENTINEL',
            'type': 'ParameterType_Number', 'numberValue': 1}]},
        'payCostsReq': {'paymentActions': {}, 'effectCostReq': {'effectCostType': 'EffectCostType_Select',
            'costSelection': {'minSel': 1, 'maxSel': 1, 'context': 'SelectionContext_NonMana_Payment',
                'optionContext': 'OptionContext_Payment', 'listType': 'SelectionListType_Dynamic',
                'ids': list(ids), 'weights': [1] * len(ids), 'idType': 'IdType_InstanceId',
                'validationType': 'SelectionValidationType_NonRepeatable',
                'minWeight': -2147483648, 'maxWeight': 2147483647}}},
        'allowCancel': 'AllowCancel_Abort', 'allowUndo': True}]}}


def response(ids=(701,), ident=990, state=1):
    return {'payload': {'type': 'ClientMessageType_EffectCostResp', 'respId': ident, 'gameStateId': state,
        'effectCostResp': {'effectCostType': 'EffectCostType_Select', 'costSelection': {'ids': list(ids)}}}}


def message(row):
    return row['greToClientEvent']['greToClientMessages'][0]


def successor():
    return {'greToClientEvent': {'greToClientMessages': [{'type': 'GREMessageType_GameStateMessage',
        'systemSeatIds': [1], 'gameStateMessage': {'type': 'GameStateType_Diff',
            'gameStateId': 2, 'prevGameStateId': 1}}]}}


class SemanticEffectCostTests(unittest.TestCase):
    def setUp(self):
        self.document = json.loads(FIXTURE.read_text(encoding='utf-8'))

    def export(self, rows, version=7):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'source.log'
            save(path, rows)
            return collect_samples(path, schema_version=version, max_samples=256)

    def test_real_episode_preserves_only_observed_choice_and_visible_successor(self):
        self.assertEqual(self.document['counts'], {'matched_pairs': 1, 'exported': 1,
            'sample_limit_omissions': 0, 'unsupported_pairs': 0})
        self.assertEqual(self.document['source']['framed_records'], 732)
        sample = self.document['samples'][0]
        value = sample['request']['payload']
        self.assertEqual(len(value['offered_object_refs']), 16)
        self.assertEqual(value['weights'], [1] * 16)
        self.assertEqual(value['profile'], PROFILE)
        result = replay_samples(self.document)
        report = result['samples'][0]
        self.assertEqual(report['selected_option_positions'], [1])
        self.assertEqual(report['trace_status'], FIRST)
        self.assertEqual(len(sample['trace']['states']), 1)
        self.assertEqual(sample['trace']['states'][0]['facts'], [])
        self.assertIsNone(sample['trace']['states'][0]['omitted_annotations'])
        self.assertTrue(report['selection_submission_observed'])
        for key in ('payment_completed_verified', 'rules_effect_verified',
                    'complete_legality_verified', 'server_acceptance_verified'):
            self.assertFalse(report[key])
        self.assertIsNone(report['source_object_ref'])
        self.assertFalse(result['raw_source_auth_revalidated'])
        self.assertTrue(all(value is False for value in result['execution'].values()))

    def test_pure_choice_checks_quantity_membership_and_strict_references(self):
        sample = self.document['samples'][0]
        value, visible, seat = sample['request']['payload'], sample['before']['objects'], sample['identity']['self_seat']
        offered = value['offered_object_refs']
        self.assertEqual(check_selection(value, [offered[0]], visible=visible, seat=seat)[0], 'verified_known_constraints')
        for selected in ([], offered[:2], [offered[0], offered[0]], [999999], [True], [float(offered[0])], None):
            with self.subTest(selected=selected):
                self.assertEqual(check_selection(value, selected, visible=visible, seat=seat)[0], 'violated_known_constraints')
        self.assertEqual(value, self.document['samples'][0]['request']['payload'])

    def test_unknown_request_parameters_and_invisible_options_reject_whole_profile(self):
        mutations = [
            lambda m: m['payCostsReq'].__setitem__('paymentActions', {'unknown': []}),
            lambda m: m['payCostsReq']['effectCostReq'].__setitem__('effectCostType', 'EffectCostType_Other'),
            lambda m: m['payCostsReq']['effectCostReq']['costSelection'].__setitem__('unknown', True),
            lambda m: m['payCostsReq']['effectCostReq']['costSelection'].__setitem__('ids', [704]),
            lambda m: m.__setitem__('unknown', 'PRIVATE_SENTINEL'),
        ]
        for mutate in mutations:
            row = request(); mutate(message(row))
            with self.subTest(row=row):
                document = self.export(baseline() + [row, response(), successor()])
                self.assertEqual(document['counts']['exported'], 0)
                self.assertEqual(document['unsupported_reasons'], [{'reason': 'request_unsupported', 'count': 1}])
                self.assertNotIn('PRIVATE_SENTINEL', json.dumps(document))

    def test_visibility_is_checked_before_alias_allocation(self):
        row = message(request(ids=(704,)))
        refs = IdentityRefs()
        with patch.object(refs, 'ref', wraps=refs.ref) as ref:
            with self.assertRaises(SampleError):
                project_request(row, [{'object_ref': 701, 'zone': 'ZoneType_Battlefield',
                    'owner': 1, 'controller': 1}], 1, refs, ())
            ref.assert_not_called()

    def test_type_lookalikes_cannot_supply_bounds_weights_or_visible_ownership(self):
        sample = self.document['samples'][0]
        for key, changed in (('min_sel', True), ('max_sel', 1.0), ('min_weight', -2147483648.0),
                             ('weights', [True] * 16), ('allow_undo', 1)):
            value = copy.deepcopy(sample['request']['payload']); value[key] = changed
            with self.subTest(key=key), self.assertRaises(SampleError):
                check_request(value, sample['before']['objects'], sample['identity']['self_seat'])
        for key, changed in (('owner', True), ('controller', 1.0), ('zone', 'ZoneType_Hand')):
            visible = copy.deepcopy(sample['before']['objects'])
            next(o for o in visible if o['object_ref'] == sample['request']['payload']['offered_object_refs'][0])[key] = changed
            with self.subTest(key=key), self.assertRaises(SampleError):
                check_request(sample['request']['payload'], visible, sample['identity']['self_seat'])

    def test_identity_ownership_consumption_and_conflict_use_existing_gates(self):
        controls = []
        for seats in ([True], [1.0], [2], [1, 2]):
            row = request(); message(row)['systemSeatIds'] = seats
            controls.append([row, response()])
        controls.extend(([request(), response(ident=991)], [request(), response(state=2)],
            [request(), {'greToClientEvent': {'greToClientMessages': [dict(message(request(ident=991)))]}}, response()],
            [request(), request(ids=(702,)), response()]))
        for tail in controls:
            with self.subTest(tail=tail):
                self.assertEqual(self.export(baseline() + tail)['counts']['matched_pairs'], 0)
        document = self.export(baseline() + [request(), response(), response(), request(), response(), successor()])
        self.assertEqual(document['counts']['matched_pairs'], 1)
        self.assertEqual(document['counts']['exported'], 1)

    def test_portable_response_and_trace_cannot_invent_membership_or_effects(self):
        for selected in ([], [999999], [True], [1.0]):
            document = copy.deepcopy(self.document)
            document['samples'][0]['response']['payload']['selected_object_refs'] = selected
            with self.subTest(selected=selected), self.assertRaises(SampleError):
                replay_samples(document)
        for previous in (True, float(self.document['samples'][0]['before']['state_ref'])):
            document = copy.deepcopy(self.document)
            document['samples'][0]['trace']['states'][0]['previous_state_ref'] = previous
            with self.subTest(previous=previous), self.assertRaises(SampleError):
                replay_samples(document)
        self.document['samples'][0]['trace']['states'][0]['facts'] = [{'kind': 'payment_completed'}]
        with self.assertRaises(SampleError):
            replay_samples(self.document)

    def test_no_successor_still_proves_only_the_submitted_selection(self):
        sample = self.document['samples'][0]
        sample['trace'].update(status='eof', states=[])
        sample['successor'] = {'status': 'not_observed', 'snapshot': None, 'request_kind': None, 'request_ref': None}
        result = replay_samples(self.document)['samples'][0]
        self.assertTrue(result['selection_submission_observed'])
        self.assertFalse(result['payment_completed_verified'])
        self.assertEqual(result['successor_status'], 'not_observed')

    def test_new_default_pair_does_not_change_legacy_counts_or_successor_kind(self):
        offered = {'greToClientEvent': {'greToClientMessages': [{'type': 'GREMessageType_ActionsAvailableReq',
            'systemSeatIds': [1], 'msgId': 900, 'gameStateId': 1,
            'actionsAvailableReq': {'actions': [{'actionType': 'ActionType_Pass'}]}}]}}
        submitted = {'payload': {'type': 'ClientMessageType_PerformActionResp', 'respId': 900,
            'gameStateId': 1, 'performActionResp': {'actions': [{'actionType': 'ActionType_Pass'}]}}}
        rows = baseline() + [offered, submitted, request(), response(), successor()]
        for version in range(1, 7):
            document = self.export(rows, version)
            self.assertEqual(document['counts']['matched_pairs'], 1)
            if document['samples']:
                self.assertEqual(document['samples'][0]['successor']['request_kind'], 'unsupported')
        document = self.export(rows)
        self.assertEqual(document['counts']['matched_pairs'], 2)
        self.assertEqual(document['counts']['exported'], 2)
        self.assertEqual(document['samples'][0]['successor']['request_kind'], 'unsupported')

    def test_v7_delegates_all_legacy_episodes_together_to_v6(self):
        from mtgaplayer.semantic_hand import replay as v6_replay
        document = json.loads((FIXTURE.parent / 'semantic_hand_real_v6.json').read_text(encoding='utf-8'))
        expected = v6_replay(document)['samples']
        document.update(schema_version='mtgaplayer.semantic-samples.v7', projection=projection())
        with patch('mtgaplayer.semantic_hand.replay', wraps=v6_replay) as delegated:
            self.assertEqual(replay_samples(document)['samples'], expected)
            self.assertEqual(delegated.call_count, 1)
            self.assertEqual(len(delegated.call_args.args[0]['samples']), 2)


if __name__ == '__main__':
    unittest.main()
