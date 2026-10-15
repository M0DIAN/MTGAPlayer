"""Invented reference cards in the documented Scryfall shape; no game assets."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from mtgaplayer.rules_index import build_rules_index, lookup_rules, RulesIndexError


def card(arena=10, **changes):
    return {'object': 'card', 'arena_id': arena,
        'id': '00000000-0000-0000-0000-000000000001',
        'oracle_id': '00000000-0000-0000-0000-000000000002',
        'name': 'Invented reference', 'lang': 'en', 'layout': 'normal', 'digital': False,
        'oracle_text': 'Invented text\nwith a second line.', 'type_line': 'Invented type',
        'mana_cost': '{2}{U}', 'keywords': ['Invented keyword'], 'power': '*', 'toughness': '2',
        'colors': ['U'], **changes}


class RulesIndexTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name) / 'cards.json'
        self.output = Path(self.temp.name) / 'rules.sqlite'

    def build(self, cards):
        self.source.write_text(json.dumps(cards, ensure_ascii=False), encoding='utf-8')
        return build_rules_index(self.source, self.output, source_version='synthetic.v1')

    def test_exact_id_metadata_unknowns_and_reopen_read_only(self):
        report = self.build([card(), card(None), card(11, name='Same name', digital=True),
                             card(12, name='Same name')])
        self.assertEqual(report['source_sha256'], hashlib.sha256(self.source.read_bytes()).hexdigest())
        self.assertEqual((report['card_records'], report['records_without_arena_id'], report['unique_arena_ids']), (4, 1, 3))
        before = self.output.read_bytes()
        metadata, found = lookup_rules(self.output, [10, 11, 12, 999])
        self.assertEqual(metadata['source_version'], 'synthetic.v1')
        self.assertEqual(found[10]['card']['power'], '*')  # no numeric/effective-stat inference
        self.assertEqual(found[10]['card']['card_faces'], [])
        self.assertTrue(found[11]['card']['digital'])
        self.assertEqual(found[999], {'status': 'unresolved', 'card': None})
        self.assertEqual(self.output.read_bytes(), before)
        self.output.rename(self.output.with_suffix('.renamed'))  # open handles would fail on Windows

    def test_duplicate_id_is_ambiguous_even_identical_or_later_valid(self):
        report = self.build([card(), card(), card(11), card(11, name='Different digital identity', digital=True), card()])
        self.assertEqual(report['ambiguous_arena_ids'], 2)
        self.assertEqual(report['unique_arena_ids'], 0)
        self.assertEqual([v['status'] for v in lookup_rules(self.output, [10, 11])[1].values()], ['ambiguous', 'ambiguous'])
        self.assertTrue(all(v['card'] is None for v in lookup_rules(self.output, [10, 11])[1].values()))

    def test_faces_remain_separate_and_uninterpreted(self):
        faces = [{'name': 'Invented front', 'oracle_text': 'Front only', 'mana_cost': '{R}'},
                 {'name': 'Invented back', 'oracle_text': 'Back only', 'power': '*'}]
        self.build([card(layout='transform', card_faces=faces, oracle_text=None, mana_cost=None)])
        result = lookup_rules(self.output, [10])[1][10]['card']
        self.assertIsNone(result['oracle_text'])
        self.assertIsNone(result['mana_cost'])
        self.assertEqual([f['oracle_text'] for f in result['card_faces']], ['Front only', 'Back only'])
        self.assertEqual(result['card_faces'][1]['power'], '*')

    def test_stream_chunk_boundaries_unicode_and_empty_array(self):
        with patch('mtgaplayer.rules_index._CHUNK', 7):
            self.build([card(name='合成テスト😀'), card(11)])
        self.assertEqual(lookup_rules(self.output, [10])[1][10]['card']['name'], '合成テスト😀')
        self.output.unlink()
        report = self.build([])
        self.assertEqual(report['card_records'], 0)
        self.assertEqual(lookup_rules(self.output, [10])[1][10]['status'], 'unresolved')

    def test_invalid_or_partial_import_never_publishes_and_recovers(self):
        valid = json.dumps([card()])
        for raw in (valid[:-2], valid + 'garbage', valid[:-1] + ',]', '{}',
                    json.dumps([card(True)]), json.dumps([card(oracle_id='bad')]),
                    json.dumps([card(card_faces=[{}])]), '[{"object":"card","arena_id":null,"arena_id":10}]',
                    '[NaN]'):
            with self.subTest(raw=raw[:30]):
                self.source.write_text(raw, encoding='utf-8')
                with self.assertRaises(RulesIndexError):
                    build_rules_index(self.source, self.output, source_version='test')
                self.assertFalse(self.output.exists())
                self.assertEqual(list(Path(self.temp.name).glob('.rules-*')), [])
        self.build([card()])
        before = self.output.read_bytes()
        with self.assertRaisesRegex(RulesIndexError, 'rules_index_exists'):
            build_rules_index(self.source, self.output, source_version='replacement')
        self.assertEqual(self.output.read_bytes(), before)

    def test_corrupt_index_missing_path_and_strict_lookup_ids(self):
        with self.assertRaises(RulesIndexError):
            lookup_rules(self.output, [10])
        self.build([card()])
        for ids in ([10, True], [10.0], [-1], list(range(513))):
            with self.assertRaises(RulesIndexError):
                lookup_rules(self.output, ids)
        with closing(sqlite3.connect(self.output)) as db, db:
            db.execute('UPDATE cards SET card_json=?', (json.dumps(card(11)),))
        with self.assertRaises(RulesIndexError):
            lookup_rules(self.output, [10])

    def test_actual_import_cli_counts_only_and_refuses_overwrite(self):
        self.source.write_text(json.dumps([card()]), encoding='utf-8')
        command = [sys.executable, '-m', 'mtgaplayer', 'import-rules', str(self.source),
                   '--output', str(self.output), '--source-version', 'synthetic.v1']
        good = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(good.returncode, 0, good.stderr)
        self.assertEqual(json.loads(good.stdout)['unique_arena_ids'], 1)
        self.assertNotIn('Invented reference', good.stdout)
        self.assertNotIn(str(self.temp.name), good.stdout)
        failed = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(failed.returncode, 1)
        self.assertEqual(json.loads(failed.stdout)['error'], 'rules_index_exists')
