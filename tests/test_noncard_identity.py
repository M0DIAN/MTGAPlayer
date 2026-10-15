"""Real public noncard instances; catalog collisions are invented controls."""
import copy
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from mtgaplayer.cli import replay, watch_decision_events
from mtgaplayer.decision_consumer import DecisionConsumer
from mtgaplayer.observed_changes import _compare
from mtgaplayer.rule_context import assess_current_rule_context
from mtgaplayer.rules_index import build_rules_index, load_rules_index
from test_action_frontier import frames, save
from test_card_catalog_cli import create_card_db
from test_observed_changes import real_prefixes
from test_rules_index import card


class NoncardIdentityTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.path, self.index, self.db = root/'state.jsonl', root/'rules.sqlite', root/'catalog.sqlite'
        source = root/'invented-collisions.json'
        source.write_text(json.dumps([card(i, name='NONCARD_COLLISION') for i in (133532, 90694, 90698)] +
            [card(96839, name='ORDINARY_CARD_CONTROL')]), encoding='utf-8')
        build_rules_index(source, self.index, source_version='invented-collision-control')
        create_card_db(self.db)
        with closing(sqlite3.connect(self.db)) as conn, conn:
            for i in (133532, 90694, 90698):
                conn.execute('INSERT INTO Cards VALUES (?,?,?,?)', (i, i, 'SET', '1'))
                conn.execute('INSERT INTO Localizations_enUS VALUES (?,?,1)', (i, 'NONCARD_COLLISION'))

    def test_real_ability_and_tokens_never_resolve_colliding_catalog_rows_via_cli(self):
        prefixes = real_prefixes((97,163))
        for version in (1,2):
            for state, ids in ((97,(299,)), (163,(320,321))):
                save(self.path, prefixes[state])
                run = subprocess.run([sys.executable, '-m', 'mtgaplayer', 'replay', str(self.path),
                    '--format', 'player-log', '--card-db', str(self.db), '--rules-index', str(self.index),
                    '--decision-state-version', str(version)], capture_output=True, text=True, timeout=10)
                self.assertEqual(run.returncode, 0, run.stderr)
                doc = json.loads(run.stdout)
                for ident in ids:
                    raw = next(o for o in doc['current']['objects'] if o['id'] == ident)
                    obj = next(o for o in doc['decision_state']['visible_objects'] if o['instance_id'] == ident)
                    reference = next(o for o in doc['static_rule_context']['objects'] if o['instance_id'] == ident)
                    self.assertIsNone(raw['card_id'])
                    self.assertIsNone(obj['card_id'])
                    self.assertEqual(raw['local_card']['status'], 'missing_card_id')
                    self.assertEqual(reference['status'], 'missing_card_id')
                    self.assertIsNone(reference['reference'])
                    self.assertEqual(raw['zone'], 'ZoneType_Stack' if state == 97 else 'ZoneType_Battlefield')
                self.assertNotIn('NONCARD_COLLISION', run.stdout)

    def test_ordinary_card_still_resolves_and_unknown_kinds_keep_instance_only(self):
        data = frames()
        save(self.path, data)
        ordinary = replay(self.path, format='player-log', card_db_path=self.db, rules_index_path=self.index)
        obj = next(o for o in ordinary['current']['objects'] if o['id'] == 166)
        self.assertEqual(obj['card_id'], 96839)
        self.assertEqual(obj['local_card']['status'], 'resolved')
        self.assertIn('ORDINARY_CARD_CONTROL', json.dumps(ordinary['static_rule_context']))
        for kind in ('GameObjectType_Ability', 'GameObjectType_Token', 'GameObjectType_Future'):
            altered = copy.deepcopy(data)
            for frame in altered:
                for message in frame.get('greToClientEvent',{}).get('greToClientMessages',[]):
                    for row in message.get('gameStateMessage',{}).get('gameObjects',[]):
                        if row['instanceId'] == 166:
                            row['type'] = kind
            save(self.path, altered)
            doc = replay(self.path, format='player-log', decision_input=True, action_frontier=True,
                         card_db_path=self.db, rules_index_path=self.index)
            self.assertIsNone(doc['error'])
            obj = next(o for o in doc['current']['objects'] if o['id'] == 166)
            self.assertIsNone(obj['card_id'])
            template = next(o for o in doc['action_frontier']['templates'] if o['list_position'] == 1)
            self.assertEqual(template['source_link_status'], 'visible_unique')
            self.assertEqual(template['visible_object_id'], 166)
            self.assertIsNone(template['source_card_identity_agreement'])

    def test_current_prepared_rules_use_same_noncard_gate_and_stop_clears(self):
        save(self.path, real_prefixes((97,))[97])
        prepared = load_rules_index(self.index)
        c = DecisionConsumer()
        contexts = []
        for event in watch_decision_events(self.path, interval=0, samples=2, decision_state_version=2):
            self.assertTrue(c.accept_event(event))
            context = assess_current_rule_context(c, prepared)
            if context['objects']:
                contexts.append(context)
        self.assertTrue(contexts)
        for context in contexts:
            obj = next(o for o in context['objects'] if o['instance_id'] == 299)
            self.assertEqual(obj['status'], 'missing_card_id')
            self.assertNotIn('NONCARD_COLLISION', json.dumps(context))
        self.assertEqual(assess_current_rule_context(c, prepared)['objects'], [])

    def test_noncard_endpoint_fields_remain_unknown_without_card_identity(self):
        save(self.path, real_prefixes((163,))[163])
        before = replay(self.path, format='player-log', decision_state=True)['decision_state']
        after = copy.deepcopy(before)
        token = next(o for o in after['visible_objects'] if o['instance_id'] == 320)
        self.assertIsNone(token['card_id'])
        token.update(zone='ZoneType_Stack', tapped=True, controller_seat=2)
        changes, unresolved = _compare(before, after)
        self.assertFalse(any(o.get('instance_id') == 320 for o in changes))
        self.assertIn('visible_card_identity_changed_or_unknown', unresolved)
