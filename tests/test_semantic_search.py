"""Producer-derived real Search episode and explicitly synthetic controls."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from mtgaplayer.semantic_samples import collect_samples, replay_samples, SampleError, _Refs
from mtgaplayer.semantic_search import (PROFILE, FIRST, project_request, project_response,
    private_context, check_request, projection)
from test_combat_frontier import baseline, save
from test_raw_log import state

FIXTURE = ROOT / 'tests' / 'fixtures' / 'semantic_search_real_v8.json'


def search_baseline():
    rows = baseline()
    gs = state(rows[2])
    gs['gameObjects'].append({'instanceId': 705, 'type': 'GameObjectType_Ability', 'zoneId': 27,
        'ownerSeatId': 1, 'controllerSeatId': 1, 'visibility': 'Visibility_Public'})
    for ident in range(801, 806):
        gs['gameObjects'].append({'instanceId': ident, 'grpId': 135792468,
            'type': 'GameObjectType_Card', 'zoneId': 32, 'ownerSeatId': 1,
            'controllerSeatId': 1, 'visibility': 'Visibility_Private', 'viewers': [1]})
    for zone in gs['zones']:
        if zone['zoneId'] == 27:
            zone['objectInstanceIds'] = [705]
        if zone['zoneId'] == 32:
            zone['objectInstanceIds'] = list(range(801, 806))
    return rows


def request(ident=990):
    return {'greToClientEvent': {'greToClientMessages': [{
        'type': 'GREMessageType_SearchReq', 'systemSeatIds': [1], 'msgId': ident, 'gameStateId': 1,
        'prompt': {'promptId': 123456789, 'parameters': [{'parameterName': 'PRIVATE_PROMPT_SENTINEL',
            'type': 'ParameterType_Number', 'numberValue': n} for n in [987654321, 1]]},
        'searchReq': {'maxFind': 1, 'zonesToSearch': [32], 'itemsToSearch': list(range(801, 806)),
            'itemsSought': list(range(801, 805)), 'sourceId': 705, 'allowFailToFind': 'AllowFailToFind_Any'},
        'allowCancel': 'AllowCancel_No'}]}}


def message(row):
    return row['greToClientEvent']['greToClientMessages'][0]


def response(ids=(801,), ident=990, version=1):
    return {'payload': {'type': 'ClientMessageType_SearchResp', 'respId': ident, 'gameStateId': version,
        'searchResp': {'itemsFound': list(ids)}}}


def annotation(kind, affected, values, source=705):
    return {'id': 600 + len(values), 'affectorId': source, 'affectedIds': [affected], 'type': [kind],
        'details': [{'key': key, 'type': 'KeyValuePairValueType_int32' if type(value) is int else
                    'KeyValuePairValueType_string', 'valueInt32' if type(value) is int else 'valueString': [value]}
                    for key, value in values.items()]}


def successor():
    return {'greToClientEvent': {'greToClientMessages': [{'type': 'GREMessageType_GameStateMessage',
        'systemSeatIds': [1], 'gameStateMessage': {'type': 'GameStateType_Diff',
            'gameStateId': 2, 'prevGameStateId': 1, 'diffDeletedInstanceIds': [801],
            'gameObjects': [{'instanceId': 901, 'grpId': 246813579, 'type': 'GameObjectType_Card',
                'zoneId': 28, 'ownerSeatId': 1, 'controllerSeatId': 1, 'visibility': 'Visibility_Public'}],
            'zones': [{'zoneId': 32, 'type': 'ZoneType_Library', 'ownerSeatId': 1,
                'visibility': 'Visibility_Hidden', 'objectInstanceIds': list(range(802, 806))},
                {'zoneId': 28, 'type': 'ZoneType_Battlefield', 'visibility': 'Visibility_Public',
                 'objectInstanceIds': [701, 702, 901]}],
            'annotations': [annotation('AnnotationType_ObjectIdChanged', 801, {'orig_id': 801, 'new_id': 901}),
                annotation('AnnotationType_ZoneTransfer', 901, {'zone_src': 32, 'zone_dest': 28, 'category': 'Put'})]}}]}}


class SemanticSearchTests(unittest.TestCase):
    def setUp(self):
        self.document = json.loads(FIXTURE.read_text(encoding='utf-8'))

    def export(self, rows, version=8):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'source.log'
            save(path, rows)
            return collect_samples(path, schema_version=version, max_samples=256)

    def test_real_episode_keeps_offers_submission_first_successor_and_facts_separate(self):
        self.assertEqual(self.document['counts'], {'matched_pairs': 1, 'exported': 1,
            'sample_limit_omissions': 0, 'unsupported_pairs': 0})
        self.assertEqual(self.document['source']['framed_records'], 732)
        sample = self.document['samples'][0]
        value = sample['request']['payload']
        self.assertEqual((value['profile'], len(value['items_sought']), value['items_to_search_count']),
                         (PROFILE, 4, 41))
        self.assertTrue(all(item['visibility'] == 'request_identifier_only' for item in value['items_sought']))
        source = next(o for o in sample['before']['objects'] if o['object_ref'] == value['source_object_ref'])
        self.assertEqual(source['zone'], 'ZoneType_Stack')
        self.assertIsNone(source['card_id'])
        report = replay_samples(self.document)['samples'][0]
        self.assertEqual(report['selected_option_positions'], [0])
        self.assertEqual(report['trace_status'], FIRST)
        self.assertEqual(len(sample['trace']['states']), 1)
        self.assertEqual([f['kind'] for f in sample['trace']['states'][0]['facts']],
            ['request_item_mapped_to_public_object', 'search_item_public_zone_transfer'])
        self.assertTrue(report['selection_submission_observed'])
        self.assertTrue(report['first_continuous_state_observed'])
        self.assertTrue(report['selected_item_public_transfer_observed'])
        for key in ('hidden_item_card_identity', 'min_find', 'fail_to_find_semantics', 'parent_activate_causal_relation'):
            self.assertIsNone(report[key])
        for key in ('rules_effect_verified', 'complete_legality_verified', 'server_acceptance_verified'):
            self.assertFalse(report[key])

    def test_hidden_faces_unfiltered_domain_prompt_and_private_context_never_export(self):
        document = self.export(search_baseline() + [request(), response(), successor()])
        report = replay_samples(document)['samples'][0]
        self.assertTrue(report['selected_item_public_transfer_observed'])
        encoded = json.dumps(document)
        for forbidden in ('135792468', 'PRIVATE_PROMPT_SENTINEL', '123456789', '"_search":',
                          'itemsToSearch', 'itemsSought', 'sourceId', '"request_scope":'):
            self.assertNotIn(forbidden, encoded)
        self.assertIn('246813579', encoded)  # Newly public identity only.
        self.assertEqual(document['samples'][0]['request']['payload']['items_to_search_count'], 5)

    def test_item_aliases_are_separate_from_public_history_and_scoped_to_request(self):
        refs, scope = _Refs(), (1, 'private-match', 1, 1)
        old_public_alias = refs.ref('object', scope, 801)
        source_alias = refs.ref('object', scope, 705)
        visible = [{'object_ref': 705, 'zone': 'ZoneType_Stack', 'owner': 1, 'controller': 1}]
        zone = {'id': 32, 'type': 'ZoneType_Library', 'owner': 1, 'visibility': 'Visibility_Hidden'}
        m = message(request()); value = project_request(m, visible, 1, refs, scope, zone)
        item = value['items_sought'][0]
        self.assertEqual(item['search_item_ref'], old_public_alias)  # Numeric collision is not a join.
        self.assertNotIn('object_ref', item)
        self.assertEqual(value['source_object_ref'], source_alias)
        self.assertIn(((*scope, 990), 801), refs.maps['search_item'])
        later = project_request(message(request(ident=991)), visible, 1, refs, scope, zone)
        self.assertNotEqual(item['search_item_ref'], later['items_sought'][0]['search_item_ref'])
        context = private_context(m, refs, scope)
        projected_request = {'kind': 'search', 'payload': value}
        with self.assertRaisesRegex(SampleError, 'known_constraints_violated'):
            project_response(response(ids=(source_alias,))['payload'], projected_request, context)

    def test_source_binding_and_zone_labels_are_checked_before_alias_allocation(self):
        refs = _Refs(); visible = [{'object_ref': 701, 'zone': 'ZoneType_Battlefield', 'owner': 1, 'controller': 1}]
        zone = {'id': 32, 'type': 'ZoneType_Library', 'owner': 1, 'visibility': 'Visibility_Hidden'}
        with patch.object(refs, 'ref', wraps=refs.ref) as allocate:
            with self.assertRaises(SampleError):
                project_request(message(request()), visible, 1, refs, (), zone)
            allocate.assert_not_called()
        for key, changed in (('owner', True), ('owner', 2), ('visibility', 'Visibility_Public'),
                             ('type', 'ZoneType_Hand'), ('id', True)):
            meta = dict(zone); meta[key] = changed
            with self.subTest(key=key, changed=changed), self.assertRaises(SampleError):
                project_request(message(request()), [{'object_ref': 705, 'zone': 'ZoneType_Stack',
                    'owner': 1, 'controller': 1}], 1, refs, (), meta)

    def test_unobserved_request_shapes_reject_whole_pair_without_private_values(self):
        mutations = [lambda m: m['searchReq'].__setitem__('itemsSought', [801, 801]),
            lambda m: m['searchReq'].__setitem__('itemsSought', [806]),
            lambda m: m['searchReq'].__setitem__('itemsToSearch', [801, 801]),
            lambda m: m['searchReq'].__setitem__('sourceId', 701),
            lambda m: m['searchReq'].__setitem__('maxFind', True),
            lambda m: m['searchReq'].__setitem__('zonesToSearch', [32, 36]),
            lambda m: m['searchReq'].__setitem__('allowFailToFind', 'AllowFailToFind_Other'),
            lambda m: m['searchReq'].__setitem__('unknown', 'PRIVATE_SENTINEL'),
            lambda m: m.__setitem__('searchReq', 'PRIVATE_SENTINEL'),
            lambda m: m['prompt']['parameters'][0].__setitem__('numberValue', True)]
        for mutate in mutations:
            row = request(); mutate(message(row))
            with self.subTest(mutate=mutate):
                document = self.export(search_baseline() + [row, response(), successor()])
                self.assertEqual(document['counts']['exported'], 0)
                self.assertEqual(document['unsupported_reasons'], [{'reason': 'request_unsupported', 'count': 1}])
                self.assertNotIn('PRIVATE_SENTINEL', json.dumps(document))

    def test_empty_selection_is_unsupported_not_proven_legal_or_violating_unknown_minimum(self):
        document = self.export(search_baseline() + [request(), response(ids=()), successor()])
        self.assertEqual(document['unsupported_reasons'], [{'reason': 'response_unsupported', 'count': 1}])
        for ids in ((806,), (801, 802), (801, 801), (True,), (801.0,)):
            document = self.export(search_baseline() + [request(), response(ids=ids), successor()])
            self.assertEqual(document['counts']['exported'], 0)
            self.assertEqual(document['unsupported_reasons'], [{'reason': 'known_constraints_violated', 'count': 1}])

    def test_existing_request_identity_and_consumption_gate_remains_authority(self):
        tails = [[request(), response(ident=991)], [request(), response(version=2)],
            [request(), request(ident=991), response()],
            [request(), request(), response(), response()]]
        for tail in tails[:3]:
            self.assertEqual(self.export(search_baseline() + tail)['counts']['matched_pairs'], 0)
        self.assertEqual(self.export(search_baseline() + tails[3])['counts']['matched_pairs'], 1)
        conflicting = request(); message(conflicting)['searchReq']['itemsSought'] = [802]
        self.assertEqual(self.export(search_baseline() + [request(), conflicting, response()])['counts']['matched_pairs'], 0)
        for seats in ([True], [1.0], [2], [1, 2]):
            row = request(); message(row)['systemSeatIds'] = seats
            self.assertEqual(self.export(search_baseline() + [row, response()])['counts']['matched_pairs'], 0)
        mixed = response(); mixed['greToClientEvent'] = {'greToClientMessages': []}
        self.assertEqual(self.export(search_baseline() + [request(), mixed])['unsupported_reasons'],
                         [{'reason': 'mixed_record_ordering', 'count': 1}])

    def test_only_first_state_is_retained_and_no_successor_still_preserves_submission(self):
        first = successor()
        later = {'type': 'GREMessageType_GameStateMessage', 'systemSeatIds': [1],
                 'gameStateMessage': {'type': 'GameStateType_Diff', 'gameStateId': 3, 'prevGameStateId': 2}}
        first['greToClientEvent']['greToClientMessages'].append(later)
        document = self.export(search_baseline() + [request(), response(), first])
        self.assertEqual(len(document['samples'][0]['trace']['states']), 1)
        document = self.export(search_baseline() + [request(), response()])
        report = replay_samples(document)['samples'][0]
        self.assertTrue(report['selection_submission_observed'])
        self.assertFalse(report['first_continuous_state_observed'])
        self.assertFalse(report['selected_item_public_transfer_observed'])

    def test_full_baseline_gap_and_next_request_do_not_become_a_successful_transfer(self):
        full = copy.deepcopy(search_baseline()[2]); state(full)['gameStateId'] = 2
        gap = successor(); state(gap).update(gameStateId=3, prevGameStateId=2)
        for tail, expected in (([full], 'full_baseline_not_continuous'),
                               ([gap], 'interrupted'), ([request(ident=991)], 'next_request_observed')):
            document = self.export(search_baseline() + [request(), response(), *tail])
            report = replay_samples(document)['samples'][0]
            self.assertEqual(report['successor_status'], expected)
            self.assertTrue(report['selection_submission_observed'])
            self.assertFalse(report['first_continuous_state_observed'])
            self.assertFalse(report['selected_item_public_transfer_observed'])

    def test_missing_competing_or_mismatched_annotations_do_not_prove_transfer(self):
        controls = []
        for index, key, value in ((0, 'affectorId', 701), (0, 'affectedIds', [802]),
                                  (1, 'affectorId', 701), (1, 'affectedIds', [902])):
            row = successor(); state(row)['annotations'][index][key] = value; controls.append(row)
        row = successor(); state(row)['annotations'] = []; controls.append(row)
        row = successor(); state(row)['annotations'].append(copy.deepcopy(state(row)['annotations'][0])); controls.append(row)
        row = successor(); state(row)['annotations'].append(annotation('AnnotationType_ObjectIdChanged', 802,
            {'orig_id': 802, 'new_id': 901}, source=702)); controls.append(row)
        row = successor(); state(row)['annotations'][1]['details'][-1]['valueString'] = ['Resolve']; controls.append(row)
        row = successor(); state(row)['annotations'][1]['details'][0]['valueInt32'] = [36]; controls.append(row)
        row = successor(); state(row)['annotations'][0]['details'].append({'key': 'unknown',
            'type': 'KeyValuePairValueType_string', 'valueString': ['PRIVATE_SENTINEL']}); controls.append(row)
        for row in controls:
            with self.subTest(row=row):
                document = self.export(search_baseline() + [request(), response(), row])
                report = replay_samples(document)['samples'][0]
                self.assertFalse(report['selected_item_public_transfer_observed'])
                self.assertEqual(report['selected_item_result'], 'insufficient_evidence')
                self.assertNotIn('PRIVATE_SENTINEL', json.dumps(document))

    def test_same_batch_foreign_conflicts_withhold_facts_in_either_position(self):
        for kind in ('AnnotationType_ZoneTransfer', 'AnnotationType_ObjectIdChanged'):
            conflict = (annotation(kind, 901, {'zone_src': 36, 'zone_dest': 28, 'category': 'Put'}, source=702)
                        if kind == 'AnnotationType_ZoneTransfer' else
                        annotation(kind, 802, {'orig_id': 802, 'new_id': 901}, source=702))
            for position in (0, 2):
                row = successor(); state(row)['annotations'].insert(position, copy.deepcopy(conflict))
                with self.subTest(kind=kind, position=position):
                    document = self.export(search_baseline() + [request(), response(), row])
                    report = replay_samples(document)['samples'][0]
                    observed = document['samples'][0]['trace']['states'][0]
                    self.assertTrue(report['selection_submission_observed'])
                    self.assertTrue(report['first_continuous_state_observed'])
                    self.assertFalse(report['selected_item_public_transfer_observed'])
                    self.assertEqual(observed['facts'], [])
                    self.assertEqual(observed['facts_status'], 'unsupported_search_annotation')
        # Loose equality is used only to find potentially related bad evidence;
        # the strict annotation ID check must then reject it, never prove an ID.
        for affected in ([901.0], [901, []]):
            row = successor()
            conflict = annotation('AnnotationType_ZoneTransfer', 901,
                {'zone_src': 36, 'zone_dest': 28, 'category': 'Put'}, source=702)
            conflict['affectedIds'] = affected
            state(row)['annotations'].append(conflict)
            document = self.export(search_baseline() + [request(), response(), row])
            self.assertFalse(replay_samples(document)['samples'][0]['selected_item_public_transfer_observed'])
            self.assertEqual(document['samples'][0]['trace']['states'][0]['facts_status'], 'unsupported_search_annotation')

    def test_original_identifier_still_public_does_not_prove_migration(self):
        row = successor(); gs = state(row)
        # The helper deletes 801 after applying gameObjects. Remove that
        # synthetic deletion so both identifiers truly survive public reduction.
        gs['diffDeletedInstanceIds'] = []
        gs['gameObjects'].append({'instanceId': 801, 'grpId': 246813580,
            'type': 'GameObjectType_Card', 'zoneId': 28, 'ownerSeatId': 1,
            'controllerSeatId': 1, 'visibility': 'Visibility_Public'})
        next(z for z in gs['zones'] if z['zoneId'] == 28)['objectInstanceIds'].append(801)
        document = self.export(search_baseline() + [request(), response(), row])
        report = replay_samples(document)['samples'][0]
        self.assertTrue(report['selection_submission_observed'])
        self.assertTrue(report['first_continuous_state_observed'])
        self.assertFalse(report['selected_item_public_mapping_observed'])
        self.assertFalse(report['selected_item_public_transfer_observed'])
        self.assertEqual(document['samples'][0]['trace']['states'][0]['facts'], [])
        self.assertEqual(document['samples'][0]['trace']['states'][0]['facts_status'], 'unsupported_search_annotation')

    def test_portable_trace_cannot_forge_namespace_bindings_destination_or_authority(self):
        changes = [lambda s: s['request']['payload']['items_sought'][0].__setitem__('object_ref', 1),
            lambda s: s['request']['payload']['items_sought'][0].__setitem__('visibility', 'visible'),
            lambda s: s['request']['payload'].__setitem__('min_find', 0),
            lambda s: s['request']['payload'].__setitem__('fail_to_find_semantics', 'legal'),
            lambda s: s['trace']['states'][0]['facts'][0].__setitem__('selected_search_item_ref', 999999),
            lambda s: s['trace']['states'][0]['facts'][1].__setitem__('source_zone_ref', 999999),
            lambda s: s['trace']['states'][0]['facts'][1].__setitem__('public_object_ref',
                float(s['trace']['states'][0]['facts'][1]['public_object_ref'])),
            lambda s: s['trace']['states'][0]['facts'][0].__setitem__('source_object_ref', True),
            lambda s: s['trace']['states'][0].__setitem__('previous_state_ref', True),
            lambda s: s.__setitem__('_search', {'hidden': 'PRIVATE_SENTINEL'})]
        for change in changes:
            document = copy.deepcopy(self.document); change(document['samples'][0])
            with self.subTest(change=change), self.assertRaises(SampleError):
                replay_samples(document)
        document = copy.deepcopy(self.document); sample = document['samples'][0]
        ref = sample['trace']['states'][0]['facts'][0]['public_object_ref']
        sample['trace']['states'][0]['snapshot']['objects'] = [o for o in sample['trace']['states'][0]['snapshot']['objects'] if o['object_ref'] != ref]
        sample['successor']['snapshot'] = copy.deepcopy(sample['trace']['states'][0]['snapshot'])
        with self.assertRaises(SampleError):
            replay_samples(document)

    def test_opt_in_pair_does_not_enter_old_sample_versions_or_change_old_kind_map(self):
        from mtgaplayer.semantic_samples import KINDS
        from mtgaplayer.response_evidence import _RESPONSE_BY_REQUEST
        for version in range(1, 8):
            self.assertEqual(self.export(search_baseline() + [request(), response(), successor()], version)['counts']['matched_pairs'], 0)
        self.assertNotIn('GREMessageType_SearchReq', KINDS)
        self.assertNotIn('GREMessageType_SearchReq', _RESPONSE_BY_REQUEST)

    def test_v8_delegates_whole_legacy_batch_to_v7(self):
        from mtgaplayer.semantic_effect_cost import replay as v7_replay
        document = json.loads((FIXTURE.parent / 'semantic_hand_real_v6.json').read_text(encoding='utf-8'))
        from mtgaplayer.semantic_effect_cost import projection as v7_projection
        document.update(schema_version='mtgaplayer.semantic-samples.v7', projection=v7_projection())
        expected = v7_replay(document)['samples']
        document.update(schema_version='mtgaplayer.semantic-samples.v8', projection=projection())
        with patch('mtgaplayer.semantic_effect_cost.replay', wraps=v7_replay) as delegated:
            self.assertEqual(replay_samples(document)['samples'], expected)
            self.assertEqual(delegated.call_count, 1)
            self.assertEqual(len(delegated.call_args.args[0]['samples']), 2)

    def test_v8_keeps_v7_payment_visibility_staging_and_exact_legacy_episode(self):
        from test_semantic_effect_cost import request as payment_request, response as payment_response
        rows = search_baseline() + [payment_request(), payment_response(), successor()]
        old, new = self.export(rows, 7), self.export(rows, 8)
        self.assertEqual(old['samples'], new['samples'])
        self.assertEqual(replay_samples(old)['samples'], replay_samples(new)['samples'])

    def test_real_fixture_cli_replay_and_synthetic_cli_export_v8(self):
        completed = subprocess.run([sys.executable, '-m', 'mtgaplayer', 'replay-semantic-samples', str(FIXTURE)],
            capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)['schema_version'], 'mtgaplayer.semantic-sample-replay.v8')
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory) / 'source.log', Path(directory) / 'new.json'
            save(source, search_baseline() + [request(), response(), successor()])
            completed = subprocess.run([sys.executable, '-m', 'mtgaplayer', 'export-semantic-samples',
                str(source), '--schema-version', '8', '--output', str(target)],
                capture_output=True, text=True, encoding='utf-8')
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            self.assertEqual(json.loads(target.read_text(encoding='utf-8'))['counts']['exported'], 1)


if __name__ == '__main__':
    unittest.main()
