"""MP11: opt-in, local-only card titles for visible GRE card IDs."""
import copy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from mtgaplayer.card_catalog import CardCatalogError, lookup_local_titles, enrich_visible_document
from mtgaplayer.cli import replay
from mtgaplayer.raw_log import RawReducer


FIXTURE = Path(__file__).parent / "fixtures/player_log_selectn.jsonl"


def make_db(path, classic=False, duplicate=False):
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE Cards (GrpId INTEGER, TitleId INTEGER, ExpansionCode TEXT, CollectorNumber TEXT)")
        if classic:
            db.execute("CREATE TABLE Localizations (LocId INTEGER, Formatted INTEGER, enUS TEXT)")
            loc = "Localizations"
            lang = "enUS"
        else:
            db.execute("CREATE TABLE Localizations_enUS (LocId INTEGER, Formatted INTEGER, Loc TEXT)")
            loc = "Localizations_enUS"
            lang = "Loc"
        rows = [(96839, 1, "SET", "001"), (92359, 2, "SET", "002"),
                (75557, 3, "SET", "003"), (999999, 4, "SET", "004")]
        db.executemany("INSERT INTO Cards VALUES (?, ?, ?, ?)", rows)
        db.executemany("INSERT INTO " + loc + " (LocId, Formatted, " + lang +
                       ") VALUES (?, ?, ?)",
                       [(1, 1, "Sample Land"), (2, 1, "Sample Spell"),
                        (3, 1, "Sample Permanent"), (4, 1, "SECRET_HIDDEN_CARD")])
        if duplicate:
            db.execute("INSERT INTO Cards VALUES (96839, 1, 'ALT', '999')")


def sample_document():
    rows = [json.loads(s) for s in FIXTURE.read_text().splitlines()]
    frame = copy.deepcopy(rows[9])
    request = next(m for m in frame["greToClientEvent"]["greToClientMessages"]
                   if m.get("type") == "GREMessageType_ActionsAvailableReq")
    request["actionsAvailableReq"] = {"actions": [
        {"actionType": "ActionType_Play", "instanceId": 166,
         "grpId": 96839, "facetId": 0, "shouldStop": False},
        {"actionType": "ActionType_Cast", "instanceId": 161,
         "grpId": 92359, "manaCost": []}]}
    return rows[:9] + [frame]


class LocalCardTitlesTests(unittest.TestCase):
    def test_only_current_visible_ids_enriched_with_real_source_state(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "cards.mtga"
            make_db(db_path)
            reducer = RawReducer()
            reducer.reset(1)
            for frame in sample_document():
                reducer.apply(frame)
            original = reducer.document()
            enriched = enrich_visible_document(reducer.document(), db_path)
        self.assertTrue(enriched["current"]["valid"])
        current = enriched["current"]
        self.assertEqual(current["card_catalog"]["source"], "explicit_local_mtga_sqlite")
        self.assertEqual(current["card_catalog"]["language"], "enUS")
        by_id = {x["id"]: x for x in current["objects"]}
        self.assertEqual(by_id[166]["local_card"]["name"], "Sample Land")
        self.assertEqual(by_id[161]["local_card"]["name"], "Sample Spell")
        self.assertEqual(by_id[283]["local_card"]["name"], "Sample Permanent")
        self.assertEqual(by_id[166]["local_card"]["set_code"], "SET")
        self.assertFalse(by_id[166]["local_card"]["rules_verified"])
        link = current["request"]["action_inventory"]["visible_source_links"]["links"][0]
        self.assertEqual(link["visible_object_id"], 166)
        self.assertFalse(link["executable"] if "executable" in link else
                         current["request"]["supported"])
        self.assertEqual(current["request"]["candidates"], [])
        self.assertIsNone(current["legal_actions"])
        self.assertFalse(current["actionable"])
        self.assertNotIn("SECRET_HIDDEN_CARD", json.dumps(enriched))
        self.assertNotIn("local_card", json.dumps(original))
        self.assertNotIn("local_card", json.dumps(reducer.document()))
        self.assertNotIn("card_catalog", json.dumps(enriched["last_valid"]))

    def test_ambiguous_rows_and_alternative_localization_stay_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "cards.mtga"
            make_db(db_path, classic=True, duplicate=True)
            titles, duplicates = lookup_local_titles(db_path, [96839, 92359, 999999])
            self.assertIn(96839, duplicates)
            self.assertNotIn(96839, titles)
            self.assertEqual(titles[92359]["name"], "Sample Spell")
            self.assertEqual(titles[999999]["name"], "SECRET_HIDDEN_CARD")
            reducer = RawReducer()
            reducer.reset(1)
            for row in sample_document():
                reducer.apply(row)
            snapshot = enrich_visible_document(reducer.document(), db_path)
        by_id = {x["id"]: x for x in snapshot["current"]["objects"]}
        self.assertEqual(by_id[166]["local_card"]["status"], "ambiguous")
        self.assertNotIn("name", by_id[166]["local_card"])
        self.assertEqual(by_id[161]["local_card"]["name"], "Sample Spell")
        self.assertNotIn("SECRET_HIDDEN_CARD", json.dumps(snapshot))
        self.assertFalse(snapshot["current"]["actionable"])

    def test_invalid_and_missing_database_blocks_without_synthesized_titles(self):
        with tempfile.TemporaryDirectory() as directory:
            fake = Path(directory) / "missing.mtga"
            with self.assertRaises(CardCatalogError):
                lookup_local_titles(fake, [96839])
            with sqlite3.connect(fake) as db:
                db.execute("CREATE TABLE Wrong (ID INTEGER)")
            with self.assertRaisesRegex(CardCatalogError, "catalog_schema_unsupported"):
                lookup_local_titles(fake, [96839])
            with self.assertRaises(CardCatalogError):
                lookup_local_titles(fake, range(1000))
            invalid_document = {"current": {"valid": False, "objects": [
                {"id": 1, "card_id": 999999}]}, "last_valid": {"objects": []}}
            self.assertEqual(enrich_visible_document(invalid_document, fake),
                             invalid_document)
            self.assertNotIn("card_catalog", invalid_document["current"])


if __name__ == "__main__":
    unittest.main()
