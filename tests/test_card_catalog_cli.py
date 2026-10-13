"""MP11: opt-in CLI catalog replay and source-only count summary."""
import copy
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from mtgaplayer.cli import replay
from scripts.inspect_card_catalog import inspect


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/player_log_selectn.jsonl"
SCRIPT = ROOT / "scripts/inspect_card_catalog.py"


def create_card_db(path):
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE Cards (GrpId INTEGER, TitleId INTEGER, ExpansionCode TEXT, CollectorNumber TEXT)")
        conn.execute("CREATE TABLE Localizations_enUS (LocId INTEGER, Loc TEXT, Formatted INTEGER)")
        conn.executemany("INSERT INTO Cards VALUES (?,?,?,?)", [
            (96839, 1, "SET", "11"),
            (92359, 2, "SET", "12"),
            (75557, 3, "SET", "13")])
        conn.executemany("INSERT INTO Localizations_enUS VALUES (?,?,?)", [
            (1, "Example Land", 1), (2, "Example Spell", 1),
            (3, "Example Creature", 1)])


def fixture_prefix(path):
    rows = [json.loads(line) for line in FIXTURE.read_text().splitlines()]
    entry = copy.deepcopy(rows[9])
    req = next(msg for msg in entry["greToClientEvent"]["greToClientMessages"]
               if msg.get("type") == "GREMessageType_ActionsAvailableReq")
    req["actionsAvailableReq"] = {"actions": [
        {"actionType": "ActionType_Play", "instanceId": 166,
         "grpId": 96839, "facetId": 0, "shouldStop": False},
        {"actionType": "ActionType_Cast", "instanceId": 161,
         "grpId": 92359, "manaCost": []}]}
    path.write_text("".join(json.dumps(r) + "\n" for r in rows[:9] + [entry]),
                    encoding="utf-8")


class CardCatalogCLITests(unittest.TestCase):
    def test_replay_opt_in_and_default_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log, db = root / "Player.log", root / "cards.mtga"
            fixture_prefix(log)
            create_card_db(db)
            default = replay(log, format="player-log")
            enriched = replay(log, format="player-log", card_db_path=db)
            self.assertNotIn("card_catalog", default["current"])
            self.assertEqual(enriched["current"]["card_catalog"]["counts"]["resolved"], 4)
            self.assertEqual(enriched["current"]["objects"][0]["local_card"]["status"],
                             "resolved")
            self.assertFalse(enriched["current"]["actionable"])
            self.assertIsNone(enriched["current"]["legal_actions"])
            with self.assertRaisesRegex(ValueError, "card_db_requires_player_log_format"):
                replay(log, format="normalized", card_db_path=db)

    def test_user_local_summary_is_counts_only_and_cli_exits_success(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log, db = root / "Player.log", root / "cards.mtga"
            fixture_prefix(log)
            create_card_db(db)
            doc = inspect(log, db)
            run = subprocess.run(
                [sys.executable, str(SCRIPT), "--log", str(log),
                 "--card-db", str(db)], cwd=ROOT,
                text=True, capture_output=True, check=False)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(json.loads(run.stdout), doc)
        self.assertEqual(doc["verified_requests"], 1)
        self.assertGreater(doc["unique_names_resolved"], 0)
        self.assertEqual(doc["uniquely_joined_action_rows"], 2)
        self.assertEqual(doc["joined_action_rows_with_catalog_names"], 2)
        self.assertFalse(doc["source"]["input_sent"])
        self.assertIsNone(doc["legal_actions"])
        self.assertFalse(doc["actionable"])
        out = json.dumps(doc)
        for secret in ("Example Land", "Example Spell", "Example Creature",
                       "96839", "92359", "75557", "cards.mtga", "Player.log"):
            self.assertNotIn(secret, out)

    def test_capability_shapes_are_optional_and_value_free(self):
        # Only cards appearing in the accepted own-seat visible projection
        # may influence the aggregate counts. No source scalar is exported.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log, db = root / "Player.log", root / "cards.mtga"
            fixture_prefix(log)
            create_card_db(db)
            with sqlite3.connect(db) as conn:
                for name in ("Types", "Colors", "Power", "Toughness",
                             "AbilityIds"):
                    conn.execute('ALTER TABLE Cards ADD COLUMN "' + name + '" TEXT')
                conn.execute(
                    'UPDATE Cards SET Types=?, Colors=?, Power=?, '
                    'Toughness=?, AbilityIds=? WHERE GrpId=?',
                    ('["Creature"]', 'W,U', '3', '4', '[12,31]', 96839))
                conn.execute(
                    'UPDATE Cards SET Types=?, Colors=?, Power=?, '
                    'Toughness=?, AbilityIds=? WHERE GrpId=?',
                    ('Instant', '[]', '*', '3.5', '[]', 92359))
                conn.execute(
                    'UPDATE Cards SET Types=?, Colors=?, Power=?, '
                    'Toughness=?, AbilityIds=? WHERE GrpId=?',
                    ('["Land"]', '', None, None, 'PRIVATE_RAW_SENTINEL', 75557))
                conn.execute(
                    'INSERT INTO Cards (GrpId,TitleId,Types) VALUES (?,?,?)',
                    (999998, 1, 'NEVER_VISIBLE_SENTINEL'))
            default = inspect(log, db)
            sampled = inspect(log, db, capability_shapes=True)
            run = subprocess.run(
                [sys.executable, str(SCRIPT), "--log", str(log),
                 "--card-db", str(db), "--capability-shapes"],
                cwd=ROOT, capture_output=True, text=True, check=False)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertNotIn("capability_shapes", default)
        self.assertEqual(json.loads(run.stdout), sampled)
        self.assertEqual(sampled["verified_requests"], 1)
        profile = sampled["capability_shapes"]
        self.assertEqual(profile["distinct_source_ids_found"], 3)
        self.assertEqual(profile["card_rows_examined"], 3)
        self.assertEqual(profile["ambiguous_source_ids"], 0)
        self.assertFalse(profile["field_semantics_verified"])
        self.assertFalse(profile["mana_cost_verified"])
        coverage = profile["localized_visible_stat_coverage"]
        self.assertEqual(coverage["named_visible_card_ids"], 3)
        self.assertEqual(coverage["numeric_power_literal_ids"], 1)
        self.assertEqual(coverage["numeric_toughness_literal_ids"], 1)
        self.assertEqual(coverage["both_numeric_literal_ids"], 1)
        self.assertFalse(coverage["effective_game_stats_verified"])
        self.assertIsNone(profile["legal_actions"])
        self.assertFalse(profile["actionable"])
        shapes = {row["field"]: row["shape_counts"]
                  for row in profile["field_shapes"]}
        self.assertEqual(shapes["Types"]["json_array"], 2)
        self.assertEqual(shapes["Types"]["symbol_text"], 1)
        self.assertEqual(shapes["Colors"]["comma_text"], 1)
        self.assertEqual(shapes["Colors"]["json_array"], 1)
        self.assertEqual(shapes["Colors"]["empty_text"], 1)
        self.assertEqual(shapes["Power"]["text_integer"], 1)
        self.assertEqual(shapes["Power"]["other_text"], 1)
        self.assertEqual(shapes["Toughness"]["text_decimal"], 1)
        self.assertEqual(shapes["AbilityIds"]["json_array"], 2)
        self.assertIn("OldSchoolManaText", profile["fields_missing_from_schema"])
        output = json.dumps(sampled)
        for private in ("PRIVATE_RAW_SENTINEL", "NEVER_VISIBLE_SENTINEL",
                        '["Creature"]', "W,U", "[12,31]", "999998",
                        str(db), str(log)):
            self.assertNotIn(private, output)
        self.assertFalse(sampled["source"]["input_sent"])

    def test_capability_shapes_missing_columns_remain_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log, db = root / "Player.log", root / "cards.mtga"
            fixture_prefix(log)
            create_card_db(db)
            result = inspect(log, db, capability_shapes=True)
        shapes = result["capability_shapes"]
        self.assertEqual(shapes["field_shapes"], [])
        self.assertEqual(len(shapes["fields_missing_from_schema"]), 16)
        self.assertEqual(shapes["card_rows_examined"], 3)
        self.assertEqual(shapes["localized_visible_stat_coverage"], {
            "named_visible_card_ids": 3,
            "numeric_power_literal_ids": 0,
            "numeric_toughness_literal_ids": 0,
            "both_numeric_literal_ids": 0,
            "effective_game_stats_verified": False,
        })
        self.assertFalse(shapes["field_semantics_verified"])

    def test_cli_unsupported_local_db_reports_path_free_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "Player.log"
            fixture_prefix(log)
            run = subprocess.run(
                [sys.executable, str(SCRIPT), "--log", str(log),
                 "--card-db", str(root / "unavailable.mtga")],
                cwd=ROOT, text=True, capture_output=True, check=False)
        self.assertNotEqual(run.returncode, 0)
        result = json.loads(run.stdout)
        self.assertFalse(result["actionable"])
        self.assertFalse(result["input_sent"])
        self.assertNotIn("unavailable.mtga", run.stdout)


if __name__ == "__main__":
    unittest.main()
