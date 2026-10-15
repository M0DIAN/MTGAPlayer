"""MP12 schema inventory tests: database metadata only, no card values."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from scripts.inspect_card_capability_schema import inspect


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/inspect_card_capability_schema.py"


def make_db(path):
    with closing(sqlite3.connect(path)) as db, db:
        db.execute(
            'CREATE TABLE Cards (GrpId INTEGER, TitleId INTEGER NOT NULL, '
            'ManaCost TEXT, CardType INTEGER, Abilities BLOB, '
            '"unsafe/data" TEXT)')
        db.execute('CREATE TABLE CardAbilities (CardId INTEGER, AbilityId INTEGER)')
        db.execute('CREATE TABLE ManaCostData (CostId INTEGER)')
        db.execute('CREATE TABLE Localizations_enUS (LocId INTEGER, Loc TEXT)')
        db.execute('CREATE TABLE AccountSecret (Value TEXT)')
        db.execute(
            'INSERT INTO Cards (GrpId, TitleId, ManaCost, "unsafe/data") '
            'VALUES (?, ?, ?, ?)',
            (98765432, 42, "DO_NOT_EXPORT_PRIVATE_COST", "PRIVATE_CARD_ROW"))
        db.execute('INSERT INTO AccountSecret VALUES (?)',
                   ("DO_NOT_EXPORT_PRIVATE_ACCOUNT",))


class CapabilitySchemaEvidenceTests(unittest.TestCase):
    def test_schema_names_and_storage_affinity_not_card_row_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "private_game_database.mtga"
            make_db(path)
            before = hashlib.sha256(path.read_bytes()).digest()
            report = inspect(path)
            after = hashlib.sha256(path.read_bytes()).digest()
        self.assertEqual(before, after)
        self.assertEqual(report["probe"], "mtga-card-capability-schema-v1")
        self.assertTrue(report["catalog"]["sqlite_query_only"])
        self.assertFalse(report["catalog"]["row_values_read"])
        self.assertFalse(report["catalog"]["card_names_exported"])
        self.assertEqual(report["schema"]["all_user_table_count"], 5)
        self.assertEqual(report["schema"]["related_table_names"],
                         ["CardAbilities", "Cards", "Localizations_enUS",
                          "ManaCostData"])
        columns = {item["name"]: item for item in report["schema"]["cards_columns"]}
        self.assertIn("GrpId", columns)
        self.assertEqual(columns["ManaCost"]["sqlite_affinity"], "text")
        self.assertEqual(columns["CardType"]["sqlite_affinity"], "integer")
        self.assertEqual(columns["Abilities"]["sqlite_affinity"], "blob")
        self.assertTrue(columns["TitleId"]["declared_not_null"])
        self.assertEqual(report["schema"]["cards_column_names_suppressed"], 1)
        self.assertFalse(report["schema"]["field_semantics_verified"])
        self.assertFalse(report["schema"]["abilities_decoded"])
        self.assertIsNone(report["legal_actions"])
        self.assertFalse(report["actionable"])
        self.assertFalse(report["input_sent"])
        output = json.dumps(report)
        for private in ("private_game_database.mtga", "DO_NOT_EXPORT_PRIVATE_COST",
                        "DO_NOT_EXPORT_PRIVATE_ACCOUNT", "PRIVATE_CARD_ROW",
                        "AccountSecret", "98765432", "unsafe/data"):
            self.assertNotIn(private, output)

    def test_cli_uses_explicit_db_and_prints_only_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.mtga"
            make_db(path)
            run = subprocess.run(
                [sys.executable, str(SCRIPT), "--card-db", str(path)],
                cwd=ROOT, capture_output=True, text=True, check=False)
            direct = inspect(path)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(json.loads(run.stdout), direct)
        self.assertNotIn(str(path), run.stdout)
        self.assertFalse(json.loads(run.stdout)["rules_verified"])

    def test_missing_or_unsupported_schema_fails_without_path_leak(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "PRIVATE_DB_LOCATION.mtga"
            with closing(sqlite3.connect(path)) as db, db:
                db.execute("CREATE TABLE MissingCards (GrpId INTEGER)")
            run = subprocess.run(
                [sys.executable, str(SCRIPT), "--card-db", str(path)],
                cwd=ROOT, capture_output=True, text=True, check=False)
        self.assertNotEqual(run.returncode, 0)
        report = json.loads(run.stdout)
        self.assertEqual(report["error"], "catalog_unavailable_or_unsupported")
        self.assertNotIn("PRIVATE_DB_LOCATION", run.stdout)
        self.assertFalse(report["input_sent"])


if __name__ == "__main__":
    unittest.main()
