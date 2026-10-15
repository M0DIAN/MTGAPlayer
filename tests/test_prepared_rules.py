"""Bounded startup reference preparation; invented records, no game resources."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from mtgaplayer.rules_index import build_rules_index, load_rules_index, lookup_rules, RulesIndexError
from test_rules_index import card


class PreparedRulesTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.source = Path(temp.name) / 'cards.json'
        self.index = Path(temp.name) / 'rules.sqlite'

    def build(self, cards, version='invented.v1'):
        self.source.write_text(json.dumps(cards, ensure_ascii=False), encoding='utf-8')
        build_rules_index(self.source, self.index, source_version=version)

    def test_file_equivalence_exact_ids_duplicates_faces_and_empty(self):
        self.build([card(), card(11, digital=True, name='合成😀'), card(12), card(12),
            card(13, layout='transform', card_faces=[{'name': 'Front'}, {'name': 'Back'}]), card(None)])
        prepared = load_rules_index(self.index)
        self.assertEqual(prepared.lookup([10, 11, 12, 13, 99, 10]),
                         lookup_rules(self.index, [10, 11, 12, 13, 99, 10]))
        self.index.unlink()
        self.build([])
        self.assertEqual(load_rules_index(self.index).lookup([99]), lookup_rules(self.index, [99]))

    def test_source_removal_and_replacement_cannot_change_prepared_version(self):
        self.build([card()])
        prepared = load_rules_index(self.index)
        expected = prepared.lookup([10])
        self.index.unlink()  # also proves no retained SQLite handle on Windows
        self.source.unlink()
        self.assertEqual(prepared.lookup([10]), expected)
        self.build([card(name='Replacement')], 'invented.v2')
        self.assertNotEqual(lookup_rules(self.index, [10]), expected)
        self.assertEqual(prepared.lookup([10]), expected)

    def test_returned_data_is_detached_and_lookup_has_no_io(self):
        self.build([card(card_faces=[{'name': 'Front'}])])
        prepared = load_rules_index(self.index)
        expected = prepared.lookup([10, 99])
        metadata, found = prepared.lookup([10, 99])
        metadata['source_sha256'] = 'changed'
        found[10]['card']['card_faces'][0]['name'] = 'changed'
        found[99]['status'] = 'changed'
        with patch('mtgaplayer.rules_index.sqlite3.connect', side_effect=AssertionError('SQLite lookup')), \
             patch('builtins.open', side_effect=AssertionError('file lookup')), \
             patch.object(Path, 'is_file', side_effect=AssertionError('path lookup')):
            self.assertEqual(prepared.lookup([10, 99]), expected)
        for ids in ([True, 10], [10.0], [-1], list(range(513))):
            with self.assertRaises(RulesIndexError):
                prepared.lookup(ids)

    def test_bounds_reject_before_payload_decode_and_release_file(self):
        self.build([card(), card(11, name='合成😀')])
        with closing(sqlite3.connect(self.index)) as db:
            size = sum(db.execute('SELECT COALESCE(SUM(length(CAST(card_json AS BLOB))),0) FROM cards').fetchone())
            size += sum(db.execute('SELECT SUM(length(CAST(value AS BLOB))) FROM metadata').fetchone())
        for limits in ({'max_cards': 1}, {'max_json_bytes': size - 1}):
            with self.subTest(limits=limits), patch('mtgaplayer.rules_index._read_card',
                    side_effect=AssertionError('must fail before decode')):
                with self.assertRaisesRegex(RulesIndexError, '^rules_index_limits_exceeded$'):
                    load_rules_index(self.index, **limits)
        self.assertEqual(load_rules_index(self.index, max_cards=2, max_json_bytes=size).lookup([10]),
                         lookup_rules(self.index, [10]))
        self.index.rename(self.index.with_suffix('.released'))

    def test_corrupt_late_row_or_metadata_cannot_publish_partial_snapshot(self):
        with self.assertRaisesRegex(RulesIndexError, '^rules_index_unavailable_or_invalid$'):
            load_rules_index(self.index)
        self.build([card(), card(11)])
        with closing(sqlite3.connect(self.index)) as db, db:
            db.execute('UPDATE cards SET card_json=? WHERE arena_id=11', (json.dumps(card(12)),))
        with self.assertRaisesRegex(RulesIndexError, '^rules_index_unavailable_or_invalid$'):
            load_rules_index(self.index)
        self.index.unlink()
        self.build([card()])
        with closing(sqlite3.connect(self.index)) as db, db:
            db.execute("UPDATE metadata SET value='2' WHERE key='unique_arena_ids'")
        with self.assertRaisesRegex(RulesIndexError, '^rules_index_unavailable_or_invalid$'):
            load_rules_index(self.index)
        self.index.unlink()
