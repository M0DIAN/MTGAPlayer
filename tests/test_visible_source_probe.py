"""MP10 CLI: bounded offline summary without printing source IDs."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scripts.inspect_actions import inspect_visible_sources


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "player_log_selectn.jsonl"
SCRIPT = ROOT / "scripts" / "inspect_actions.py"


class VisibleSourceProbeTests(unittest.TestCase):
    def test_repository_header_only_fixture_has_no_join(self):
        result = inspect_visible_sources(FIXTURE)
        self.assertEqual(result["verified_inventory_requests"], 0)
        self.assertEqual(result["total_described_sources"], 0)
        self.assertTrue(result["source"]["complete"])
        self.assertFalse(result["actionable"])

    def test_cli_counts_only_verified_current_visible_sources(self):
        source = [json.loads(x) for x in FIXTURE.read_text().splitlines()]
        frame = copy.deepcopy(source[9])
        message = next(x for x in frame["greToClientEvent"]["greToClientMessages"]
                       if x.get("type") == "GREMessageType_ActionsAvailableReq")
        message["actionsAvailableReq"] = {"actions": [
            {"actionType": "ActionType_Play", "instanceId": 166,
             "grpId": 96839, "facetId": 0, "shouldStop": False},
            {"actionType": "ActionType_Cast", "instanceId": 161,
             "grpId": 999999},
            {"actionType": "ActionType_Cast", "instanceId": 912345},
            {"actionType": "ActionType_Pass"}]}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Player.log"
            path.write_text("".join(json.dumps(x) + "\n" for x in source[:9] + [frame]),
                            encoding="utf-8")
            direct = inspect_visible_sources(path)
            cli = subprocess.run(
                [sys.executable, str(SCRIPT), str(path), "--visible-sources"],
                cwd=ROOT, text=True, capture_output=True, check=False)
        self.assertEqual(cli.returncode, 0, cli.stderr)
        self.assertEqual(json.loads(cli.stdout), direct)
        self.assertEqual(direct["verified_inventory_requests"], 1)
        self.assertEqual(direct["total_described_sources"], 3)
        self.assertEqual(direct["status_counts"]["visible_unique"], 2)
        self.assertEqual(direct["status_counts"]["not_in_visible_projection"], 1)
        self.assertEqual(direct["visible_raw_group_comparisons"],
                         {"equal": 1, "different": 1, "unknown": 0})
        self.assertEqual(len(direct["type_status_counts"]), 3)
        self.assertFalse(direct["source"]["input_sent"])
        self.assertIsNone(direct["legal_actions"])
        self.assertFalse(direct["actionable"])
        out = json.dumps(direct)
        for private in ("166", "96839", "161", "999999", "912345"):
            self.assertNotIn(private, out)


if __name__ == "__main__":
    unittest.main()
