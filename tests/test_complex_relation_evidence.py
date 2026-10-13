"""MP9: deep structural relationship evidence without leaking raw game IDs."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scripts.inspect_actions import inspect_complex_relations


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "player_log_selectn.jsonl"
SCRIPT = ROOT / "scripts" / "inspect_actions.py"


class ComplexRelationshipEvidenceTests(unittest.TestCase):
    def test_existing_real_source_fixture_lacks_complex_payload(self):
        result = inspect_complex_relations(FIXTURE)
        self.assertEqual(result["request_count"], 9)
        self.assertEqual(result["payload_count"], 0)
        self.assertEqual(result["complex_active_action_count"], 0)
        self.assertTrue(result["source"]["complete"])
        self.assertEqual(sum(item["active_action_count"] for item in result["action_shapes"]), 0)
        self.assertFalse(result["source"]["input_sent"])
        self.assertIsNone(result["legal_actions"])
        self.assertFalse(result["actionable"])

    def test_synthetic_nested_shapes_and_same_request_identity_equality(self):
        data = {"greToClientEvent": {"greToClientMessages": [
            {"type": "GREMessageType_ActionsAvailableReq",
             "systemSeatIds": [1], "msgId": 349871, "gameStateId": 994433,
             "actionsAvailableReq": {"actions": [
                 {"actionType": "ActionType_Activate_Mana",
                  "instanceId": 782999, "abilityGrpId": 930087,
                  "manaPaymentOptions": [{"mana": [
                      {"color": "SECRET_MANA_COLOR", "count": 2,
                       "privateNestedKeySensitive": "SECRET_NESTED"}]}],
                  "manaSelections": [
                      {"instanceId": 782999, "abilityGrpId": 930087,
                       "options": [{"manaId": 569983, "count": 1}]}]},
                 {"actionType": "ActionType_Cast", "instanceId": 457991,
                  "manaCost": [{"color": ["SECRET_MANA_COLOR"], "count": 2}],
                  "targets": [{"targetIdx": 0, "targets": [555432]}],
                  "autoTapSolution": {"autoTapActions": [
                      {"instanceId": 782999, "abilityGrpId": 930087,
                       "manaId": 569983},
                      {"instanceId": 782999, "abilityGrpId": 444444}]}},
                 {"actionType": "ActionType_Activate",
                  "instanceId": 133771, "manaCost": [{"count": 1}],
                  "targets": [{"targetIdx": 1,
                               "targets": [{"instanceId": 234567}]}]},
                 {"actionType": "ActionType_Pass"},
             ], "inactiveActions": [
                 {"actionType": "ActionType_Activate_Mana",
                  "instanceId": 201001, "abilityGrpId": 930087,
                  "SECRET_INACTIVE": "SECRET_PRIVATE"}]}}]}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Player.log"
            path.write_text(json.dumps(data), encoding="utf-8")
            result = inspect_complex_relations(path)
            run = subprocess.run(
                [sys.executable, str(SCRIPT), str(path), "--complex-relations"],
                capture_output=True, text=True, cwd=ROOT, check=False)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(json.loads(run.stdout), result)
        self.assertEqual(result["complex_active_action_count"], 3)
        self.assertEqual([a["active_action_count"] for a in result["action_shapes"]],
                         [1, 1, 1])
        paths = " ".join(" ".join(v["field_types"])
                         for a in result["action_shapes"] for v in a["variants"])
        self.assertIn("autoTapSolution.autoTapActions[].manaId:int", paths)
        self.assertIn("manaPaymentOptions[].mana[].color:string", paths)
        self.assertIn("manaSelections[].options[].manaId:int", paths)
        self.assertIn("targets[].targets[].instanceId:int", paths)
        self.assertIn("_unrecognized_field:string", paths)
        refs = result["same_request_raw_id_pair_comparisons"]
        self.assertEqual(refs["autotap_rows"], 2)
        self.assertEqual(refs["autotap_same_request_mana_pair_match"], 1)
        self.assertEqual(refs["autotap_same_request_mana_pair_unmatched"], 1)
        self.assertEqual(refs["mana_selection_rows"], 1)
        self.assertEqual(refs["mana_selection_same_request_mana_pair_match"], 1)
        self.assertFalse(result["distinct_variant_storage_cap_reached"])
        self.assertTrue(result["source"]["complete"])
        result_text = json.dumps(result)
        for value in ("SECRET_MANA_COLOR", "SECRET_NESTED", "SECRET_INACTIVE",
                      "SECRET_PRIVATE", "privateNestedKeySensitive", "782999",
                      "930087", "569983", "457991", "555432", "234567",
                      "349871", "994433", "201001", "444444"):
            self.assertNotIn(value, result_text)
        self.assertFalse(result["source"]["input_sent"])
        self.assertIsNone(result["legal_actions"])
        self.assertFalse(result["actionable"])

    def test_unfinished_tail_is_explicit_and_no_private_values_exported(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Player.log"
            path.write_bytes(FIXTURE.read_bytes() + b'{"SECRET_VALUE":')
            result = inspect_complex_relations(path)
        self.assertTrue(result["source"]["partial_record"])
        self.assertFalse(result["source"]["complete"])
        self.assertNotIn("SECRET_VALUE", json.dumps(result))
        self.assertFalse(result["source"]["input_sent"])


if __name__ == "__main__":
    unittest.main()
