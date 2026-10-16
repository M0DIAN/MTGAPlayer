"""Same-export Stack alias observation; curated fixture fusion is synthetic."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from mtgaplayer.semantic_samples import SampleError, load_and_replay, replay_samples

FIXTURES = Path(__file__).parent / 'fixtures'


class SharedStackObservationTests(unittest.TestCase):
    def setUp(self):
        with (FIXTURES/'semantic_effect_cost_result_real_v9.json').open(encoding='utf-8') as stream:
            self.cost = json.load(stream)
        with (FIXTURES/'semantic_search_real_v8.json').open(encoding='utf-8') as stream:
            self.search = json.load(stream)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'one-file-synthetic-composition.json'

    def combined(self):
        # Both curated episodes came from the same reported original producer;
        # this test composition DOES NOT authenticate that original raw stream.
        self.assertEqual(self.cost['source'], self.search['source'])
        result = copy.deepcopy(self.cost)
        result['source']['origin'] = 'synthetic'
        result['samples'].append(copy.deepcopy(self.search['samples'][0]))
        result['counts'] = {'matched_pairs': 2, 'exported': 2,
                            'sample_limit_omissions': 0, 'unsupported_pairs': 0}
        return result

    def replay(self, doc, *, observed=True):
        self.path.write_text(json.dumps(doc), encoding='utf-8')
        return load_and_replay(self.path, shared_stack_observation=observed)

    def test_opt_in_shared_stack_alias_keeps_causality_unknown(self):
        document = self.combined()
        result = self.replay(document)
        certificate = result['shared_stack_observation']
        self.assertEqual(certificate['schema_version'], 'mtgaplayer.shared-stack-observation.v1')
        self.assertEqual(certificate['ambiguous_pairs_withheld'], 0)
        self.assertEqual(len(certificate['links']), 1)
        link = certificate['links'][0]
        self.assertEqual((link['effect_cost_sample_index'],link['search_sample_index']), (0,1))
        self.assertEqual(link['shared_visible_stack_object_ref'], 148)
        self.assertTrue(link['sacrifice_result_observed'])
        self.assertTrue(link['search_public_transfer_observed'])
        self.assertIsNone(link['paycosts_request_source'])
        self.assertFalse(certificate['source_auth_revalidated'])
        self.assertFalse(certificate['causality_verified'])
        for name in ('parent_activate_causality_verified',
                     'paycosts_to_search_causality_verified',
                     'same_live_raw_source_reauthenticated'):
            self.assertFalse(link[name])
        self.assertFalse(certificate['complete_payment_verified'])
        self.assertFalse(certificate['complete_legality_verified'])
        self.assertFalse(certificate['server_acceptance_verified'])
        self.assertFalse(certificate['input_sent'])

    def test_default_v9_replay_byte_value_unaffected(self):
        document = self.combined()
        self.assertEqual(self.replay(document,observed=False), replay_samples(document))
        self.assertNotIn('shared_stack_observation', self.replay(self.cost,observed=False))

    def test_no_cross_artifact_join_from_one_curated_episode(self):
        for original in (self.cost,):
            self.assertEqual(self.replay(original)['shared_stack_observation']['links'], [])
        # A v8-only file is NOT silently promoted to v9.
        with self.assertRaisesRegex(SampleError,'invalid_semantic_sample'):
            self.replay(self.search)

    def test_missing_cost_result_and_search_transfer_withhold_link(self):
        cost_missing = self.combined()
        row = cost_missing['samples'][0]['trace']['states'][0]
        row.update(facts=[], facts_status='incomplete_effect_cost_result_annotations',
                   omitted_annotations=4)
        self.assertFalse(self.replay(cost_missing)['samples'][0]['selected_card_sacrifice_observed'])
        self.assertEqual(self.replay(cost_missing)['shared_stack_observation']['links'], [])
        search_missing = self.combined()
        search_missing['samples'][1]['trace']['states'][0].update(
            facts=[], facts_status='unsupported_search_annotation', omitted_annotations=6)
        self.assertFalse(self.replay(search_missing)['samples'][1]['selected_item_public_transfer_observed'])
        self.assertEqual(self.replay(search_missing)['shared_stack_observation']['links'], [])

    def test_reorder_or_other_game_withholds_link(self):
        reordered = self.combined()
        reordered['samples'].reverse()
        self.assertEqual(self.replay(reordered)['shared_stack_observation']['links'], [])
        another_game = self.combined()
        another_game['samples'][1]['identity']['game'] += 1
        self.assertEqual(self.replay(another_game)['shared_stack_observation']['links'], [])

    def test_same_raw_alias_without_visible_stack_evidence_rejected(self):
        result = self.combined()
        # A forged Stack member inside one retained public snapshot conflicts
        # with the existing v9 Search request evidence.
        source = next(o for o in result['samples'][1]['before']['objects']
                      if o['object_ref'] == 148)
        source['zone'] = 'ZoneType_Graveyard'
        with self.assertRaises(SampleError):
            self.replay(result)

    def test_ambiguous_cost_proposals_are_not_assigned_to_one_search(self):
        result = self.combined()
        cloned = copy.deepcopy(result['samples'][0])
        result['samples'].insert(1, cloned)
        result['counts'].update(matched_pairs=3, exported=3)
        finding = self.replay(result)['shared_stack_observation']
        self.assertEqual(finding['links'], [])
        self.assertEqual(finding['ambiguous_pairs_withheld'], 2)

    def test_cli_opt_in_no_raw_ids_and_legacy_cli_unchanged(self):
        self.path.write_text(json.dumps(self.combined()), encoding='utf-8')
        cmd=[sys.executable,'-m','mtgaplayer','replay-semantic-samples',str(self.path)]
        normal=subprocess.run(cmd,capture_output=True,text=True,timeout=15)
        opted=subprocess.run([*cmd,'--shared-stack-observation'],
                            capture_output=True,text=True,timeout=15)
        self.assertEqual(normal.returncode, 0, normal.stderr)
        self.assertEqual(opted.returncode, 0, opted.stderr)
        a,b=json.loads(normal.stdout),json.loads(opted.stdout)
        self.assertEqual(a,{k:v for k,v in b.items() if k!='shared_stack_observation'})
        self.assertNotIn('shared_stack_observation',a)
        self.assertNotIn('source_log_path', json.dumps(b))
        self.assertTrue(b['read_only'])
        self.assertTrue(all(v is False for v in b['execution'].values()))
