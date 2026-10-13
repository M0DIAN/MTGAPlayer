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

    def test_duplicate_raw_cards_row_filtered_by_localization_remains_ambiguous(self):
        # B1: JOIN output has one row, but Cards itself has two rows.
        for title_id in (999, 5):
            with self.subTest(duplicate_title_id=title_id):
                with tempfile.TemporaryDirectory() as directory:
                    db_path = Path(directory) / "cards.mtga"
                    make_db(db_path)
                    with sqlite3.connect(db_path) as db:
                        if title_id == 5:
                            db.execute(
                                "INSERT INTO Localizations_enUS "
                                "(LocId, Formatted, Loc) VALUES (?, ?, ?)",
                                (5, 0, "UNFORMATTED_ONLY"))
                        db.execute(
                            "INSERT INTO Cards "
                            "(GrpId, TitleId, ExpansionCode, CollectorNumber) "
                            "VALUES (?, ?, ?, ?)",
                            (96839, title_id, "ALT", "999"))
                    titles, ambiguous = lookup_local_titles(
                        db_path, [96839, 92359])
                    self.assertEqual(ambiguous, {96839})
                    self.assertNotIn(96839, titles)
                    self.assertEqual(titles[92359]["name"], "Sample Spell")
                    reducer = RawReducer()
                    reducer.reset(1)
                    for entry in sample_document():
                        reducer.apply(entry)
                    projection = enrich_visible_document(reducer.document(), db_path)
                    cards = {o["id"]: o["local_card"]
                             for o in projection["current"]["objects"]}
                    self.assertEqual(cards[166], {"status": "ambiguous"})
                    self.assertNotIn("Sample Land", json.dumps(cards[166]))
                    self.assertNotIn("UNFORMATTED_ONLY", json.dumps(projection))
                    self.assertFalse(projection["current"]["actionable"])

    def test_catalog_power_toughness_literals_only_on_visible_unique_cards(self):
        # Real-source GRE visibility chain, synthetic catalog scalar values.
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "cards.mtga"
            make_db(db_path)
            with sqlite3.connect(db_path) as db:
                db.execute("ALTER TABLE Cards ADD COLUMN Power TEXT")
                db.execute("ALTER TABLE Cards ADD COLUMN Toughness TEXT")
                for power, toughness, grp in (
                        ("3", "0", 96839), ("", "*", 92359),
                        ("-2", "4", 75557), ("999", "999", 999999)):
                    db.execute(
                        "UPDATE Cards SET Power=?, Toughness=? WHERE GrpId=?",
                        (power, toughness, grp))
            reducer = RawReducer()
            reducer.reset(1)
            for row in sample_document():
                reducer.apply(row)
            original = reducer.document()
            enriched = enrich_visible_document(reducer.document(), db_path)
        current = enriched["current"]
        by_id = {obj["id"]: obj for obj in current["objects"]}
        land = by_id[166]["local_card"]["catalog_stats"]
        self.assertEqual((land["power"], land["toughness"]), (3, 0))
        self.assertIsNone(by_id[161]["local_card"]["catalog_stats"]["power"])
        self.assertIsNone(by_id[161]["local_card"]["catalog_stats"]["toughness"])
        self.assertEqual(by_id[283]["local_card"]["catalog_stats"]["power"], -2)
        self.assertEqual(by_id[283]["local_card"]["catalog_stats"]["toughness"], 4)
        self.assertEqual(land["source"], "Cards.Power/Toughness")
        self.assertTrue(land["numeric_literal_only"])
        self.assertFalse(land["in_game_modifiers_accounted_for"])
        self.assertFalse(land["rules_verified"])
        self.assertFalse(current["request"]["supported"])
        self.assertEqual(current["request"]["candidates"], [])
        self.assertIsNone(current["legal_actions"])
        self.assertFalse(current["actionable"])
        self.assertNotIn("local_card", json.dumps(original))
        self.assertNotIn("catalog_stats", json.dumps(enriched["last_valid"]))
        self.assertNotIn("SECRET_HIDDEN_CARD", json.dumps(enriched))
        self.assertNotIn('"power": 999', json.dumps(enriched))

    def test_duplicate_card_with_numeric_stats_still_ambiguous(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cards.mtga"
            make_db(path)
            with sqlite3.connect(path) as db:
                db.execute("ALTER TABLE Cards ADD COLUMN Power TEXT")
                db.execute("ALTER TABLE Cards ADD COLUMN Toughness TEXT")
                db.execute("UPDATE Cards SET Power='4', Toughness='5' WHERE GrpId=96839")
                db.execute(
                    "INSERT INTO Cards (GrpId,TitleId,Power,Toughness) "
                    "VALUES (96839,999,'99','99')")
            names, ambiguous = lookup_local_titles(path, [96839, 92359])
            self.assertEqual(ambiguous, {96839})
            self.assertNotIn(96839, names)
            self.assertIn("catalog_stats", names[92359])
            reducer = RawReducer()
            reducer.reset(1)
            for row in sample_document():
                reducer.apply(row)
            doc = enrich_visible_document(reducer.document(), path)
        by_id = {o["id"]: o for o in doc["current"]["objects"]}
        self.assertEqual(by_id[166]["local_card"], {"status": "ambiguous"})
        self.assertNotIn("99", json.dumps(by_id[166]["local_card"]))
        self.assertFalse(doc["current"]["actionable"])

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
