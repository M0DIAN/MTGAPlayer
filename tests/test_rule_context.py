"""Static references joined only to the existing visible-state projection."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from mtgaplayer.cli import replay
from mtgaplayer.rule_context import build_static_rule_context
from mtgaplayer.rules_index import build_rules_index, lookup_rules
from test_rules_index import card

FIXTURE = Path(__file__).parent / 'fixtures/player_log_selectn.jsonl'


class StaticRuleContextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name) / 'cards.json'
        self.index = Path(self.temp.name) / 'rules.sqlite'
        self.state = replay(FIXTURE, format='player-log', decision_state=True)['decision_state']
        self.known = self.state['visible_objects'][0]['card_id']
        self.other = next(o['card_id'] for o in self.state['visible_objects'] if o['card_id'] != self.known)

    def build(self, cards):
        self.source.write_text(json.dumps(cards), encoding='utf-8')
        build_rules_index(self.source, self.index, source_version='invented-reference-v1')

    def test_visible_only_full_binding_provenance_and_pure_association(self):
        self.build([card(self.known), card(99999999, name='PRIVATE_SENTINEL')])
        original = copy.deepcopy(self.state)
        with patch('mtgaplayer.rule_context.lookup_rules', wraps=lookup_rules) as lookup:
            context = build_static_rule_context(self.state, self.index)
        self.assertEqual(lookup.call_args.args[1], {o['card_id'] for o in self.state['visible_objects'] if o['card_id'] is not None})
        self.assertEqual(context['binding'], self.state['binding'])
        self.assertEqual(context['rules_source']['source_sha256'], hashlib.sha256(self.source.read_bytes()).hexdigest())
        self.assertEqual(context['rules_source']['source_version'], 'invented-reference-v1')
        self.assertEqual(len(context['objects']), len(self.state['visible_objects']))
        self.assertEqual(sum(context['counts'].values()), len(context['objects']))
        self.assertNotIn('PRIVATE_SENTINEL', json.dumps(context))
        self.assertEqual(original, self.state)
        self.assertIsNone(context['effect_claims'])
        self.assertIsNone(context['legal_actions'])
        self.assertTrue(all(v is False for v in context['execution'].values()))
        context['binding']['request_id'] += 1
        context['objects'][0]['reference']['name'] = 'changed detached result'
        self.assertEqual(original, self.state)

    def test_missing_ambiguous_ids_faces_and_stats_never_gain_semantics(self):
        faces = [{'name': 'Front', 'oracle_text': 'Front'}, {'name': 'Back', 'oracle_text': 'Back'}]
        self.build([card(self.known, card_faces=faces, layout='transform'),
                    card(self.other), card(self.other, digital=True)])
        context = build_static_rule_context(self.state, self.index)
        for row in context['objects']:
            self.assertIsNone(row['current_face'])
            self.assertFalse(row['effective_in_game'])
            self.assertFalse(row['rules_verified'])
            if row['card_id'] == self.known:
                self.assertEqual(row['status'], 'resolved_static_reference')
                self.assertEqual([f['name'] for f in row['reference']['card_faces']], ['Front', 'Back'])
                self.assertEqual(row['reference']['power'], '*')
            elif row['card_id'] == self.other:
                self.assertEqual(row['status'], 'ambiguous_catalog_id')
                self.assertIsNone(row['reference'])
            else:
                self.assertIn(row['status'], ('not_in_index', 'missing_card_id'))

    def test_unpublished_selectn_instance_ids_cannot_drive_catalog_lookup(self):
        state = copy.deepcopy(self.state)
        domain = state['legal_action_space']['immediate_frontier']['projection']['offered_instance_ids']
        domain.append(99999999)  # invented request reference, not a visible object/card ID
        self.build([card(99999999, name='REQUEST_REFERENCE_MUST_NOT_ENRICH')])
        context = build_static_rule_context(state, self.index)
        self.assertNotIn('REQUEST_REFERENCE_MUST_NOT_ENRICH', json.dumps(context))
        self.assertEqual(context['counts']['resolved_static_reference'], 0)

    def test_invalid_state_and_missing_index_have_no_reference_content(self):
        self.build([card(self.known)])
        invalid = copy.deepcopy(self.state)
        invalid['execution']['actionable'] = True
        for state in (None, {}, invalid):
            with patch('mtgaplayer.rule_context.lookup_rules', side_effect=AssertionError('must not query')):
                context = build_static_rule_context(state, self.index)
            self.assertEqual(context['status'], 'unavailable')
            self.assertIsNone(context['binding'])
            self.assertEqual(context['objects'], [])
        self.index.unlink()
        context = build_static_rule_context(self.state, self.index)
        self.assertEqual(context['unresolved'], ['rules_index_unavailable_or_invalid'])
        self.assertEqual(context['binding'], self.state['binding'])
        self.assertEqual(context['objects'], [])

    def test_duplicate_visible_instance_is_not_resolved_by_other_rows(self):
        self.build([card(self.known)])
        state = copy.deepcopy(self.state)
        state['visible_objects'].append(copy.deepcopy(state['visible_objects'][0]))
        state['visible_objects'][1]['card_id'] = None
        context = build_static_rule_context(state, self.index)
        duplicated = [o for o in context['objects'] if o['instance_id'] == state['visible_objects'][0]['instance_id']]
        self.assertEqual(len(duplicated), 2)
        self.assertTrue(all(o['status'] == 'ambiguous_visible_identity' and o['reference'] is None for o in duplicated))
        # The real fixture can already contain visible noncard instances.
        missing_before = sum(obj['card_id'] is None for obj in self.state['visible_objects'])
        self.assertEqual(context['counts']['missing_card_id'], missing_before + 1)

    def test_actual_replay_cli_is_opt_in_and_legacy_outputs_unchanged(self):
        self.build([card(self.known)])
        base = replay(FIXTURE, format='player-log')
        opted = replay(FIXTURE, format='player-log', rules_index_path=self.index)
        self.assertEqual({k:v for k,v in opted.items() if k not in ('decision_state', 'static_rule_context')}, base)
        self.assertEqual(opted['decision_state'], self.state)
        self.assertNotIn('static_rule_context', base)
        result = subprocess.run([sys.executable, '-m', 'mtgaplayer', 'replay', '--format', 'player-log',
            '--rules-index', str(self.index), str(FIXTURE)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['static_rule_context'], opted['static_rule_context'])
        with self.assertRaisesRegex(ValueError, 'rules_index_requires_player_log_format'):
            replay(FIXTURE, rules_index_path=self.index)
