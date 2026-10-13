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
