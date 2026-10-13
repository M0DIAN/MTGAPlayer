"""MP7: real-source header evidence and synthetic private-value suppression."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scripts.inspect_actions import inspect


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "inspect_actions.py"
FIXTURE = ROOT / "tests" / "fixtures" / "player_log_selectn.jsonl"


class ActionEvidenceTests(unittest.TestCase):
    def test_real_source_fixture_has_only_actions_request_headers(self):
        result = inspect(FIXTURE)
        self.assertEqual(result["request_count"], 9)
        self.assertEqual(result["payload_count"], 0)
        self.assertEqual(result["missing_payload"], 9)
        self.assertEqual(result["action_count"], 0)
        self.assertEqual(result["variants"], [])
        self.assertIn({"field": "type", "type": "string", "count": 9},
                      result["request_fields"])
        self.assertIn({"field": "gameStateId", "type": "int", "count": 9},
                      result["request_fields"])
        self.assertEqual(result["payload_fields"], [])
        self.assertTrue(result["source"]["complete"])
        self.assertIsNone(result["legal_actions"])
        self.assertFalse(result["self_seat_verified"])
        self.assertFalse(result["semantics_verified"])
        self.assertFalse(result["actionable"])
        self.assertFalse(result["source"]["input_sent"])

    def test_synthetic_schema_values_are_not_exported(self):
        synthetic = {"greToClientEvent": {"greToClientMessages": [
            {"type": "GREMessageType_ActionsAvailableReq",
             "systemSeatIds": [2], "msgId": 222, "gameStateId": 99,
             "prompt": {"secret": "SECRET_PROMPT_abc"},
             "unexpectedEnvelope": {"account": "PRIVATE_NAME"},
             "actionsAvailableReq": {"optionalConstraint": True,
                                      "actions": [
                 {"actionType": "ActionType_Play", "grpId": 873456,
                  "instanceId": 421337, "grouping": "Grouping_Single"},
                 {"actionType": "ActionType_Pass", "grouping": "Grouping_Single"},
                 {"actionType": "ActionType_Cast", "instanceId": 421337,
                  "manaCost": [{"color": ["ManaColor_Red"], "count": 1, "costId": 998877}],
                  "autoTapActions": [{"abilityGrpId": 999999}]},
             ]}}]}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Player.log"
            path.write_text(json.dumps(synthetic), encoding="utf-8")
            doc = inspect(path)
        self.assertEqual((doc["request_count"], doc["payload_count"], doc["action_count"]), (1, 1, 3))
        self.assertEqual({v["action_type"] for v in doc["variants"]},
                         {"ActionType_Play", "ActionType_Pass", "ActionType_Cast"})
        fields = " ".join(" ".join(v["field_types"]) for v in doc["variants"])
        self.assertIn("manaCost[]", fields)
        self.assertIn({"field": "unexpectedEnvelope", "type": "object", "count": 1},
                      doc["request_fields"])
        self.assertIn({"field": "actionsAvailableReq", "type": "object", "count": 1},
                      doc["request_fields"])
        self.assertIn({"field": "optionalConstraint", "type": "bool", "count": 1},
                      doc["payload_fields"])
        self.assertIn({"field": "actions", "type": "array", "count": 1},
                      doc["payload_fields"])
        output = json.dumps(doc)
        for private in ("SECRET_PROMPT_abc", "PRIVATE_NAME", "421337", "873456", "998877",
                        "999999", "ManaColor_Red", "Grouping_Single"):
            self.assertNotIn(private, output)
        self.assertFalse(doc["source"]["input_sent"])
        self.assertIsNone(doc["legal_actions"])
        self.assertFalse(doc["actionable"])

    def test_actual_script_entry_and_partial_record(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Player.log"
            path.write_bytes(FIXTURE.read_bytes() + b'{"incomplete":')
            run = subprocess.run([sys.executable, str(SCRIPT), str(path)],
                                 capture_output=True, text=True, encoding="utf-8",
                                 cwd=ROOT, check=False)
            self.assertEqual(run.returncode, 0, run.stderr)
            result = json.loads(run.stdout)
            self.assertTrue(result["source"]["partial_record"])
            self.assertFalse(result["source"]["complete"])
            self.assertEqual(result["request_count"], 9)
            self.assertFalse(result["source"]["input_sent"])
            self.assertFalse(result["actionable"])


if __name__ == "__main__":
    unittest.main()
