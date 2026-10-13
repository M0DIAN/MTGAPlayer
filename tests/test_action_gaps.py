"""MP14 gap classifier tests: real-source GRE state + synthetic action body."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from mtgaplayer.action_gaps import assess_action_gaps
from mtgaplayer.cli import replay, watch
from mtgaplayer.raw_log import RawReducer
from scripts.inspect_actions import inspect_gap_coverage


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/player_log_selectn.jsonl"


def frames():
    original = [json.loads(x) for x in FIXTURE.read_text(encoding="utf-8").splitlines()]
    frame = copy.deepcopy(original[9])
    request = next(m for m in frame["greToClientEvent"]["greToClientMessages"]
                   if m.get("type") == "GREMessageType_ActionsAvailableReq")
    reducer = RawReducer()
    reducer.reset(1)
    for entry in original[:9]:
        reducer.apply(entry)
    hidden = next(z["objectInstanceIds"][0] for z in reducer.zones.values()
                  if z.get("type") == "ZoneType_Hand" and z.get("ownerSeatId") == 2)
    request["actionsAvailableReq"] = {"actions": [
        {"actionType": "ActionType_Pass"},
        {"actionType": "ActionType_Play", "instanceId": 166,
         "grpId": 96839, "facetId": 0, "shouldStop": False},
        {"actionType": "ActionType_Cast", "instanceId": 161,
         "manaCost": [{"private": "PRIVATE_COST_SENTINEL"}],
         "targets": [{"targetIdx": 0,
                      "targets": [{"private": "PRIVATE_TARGET_SENTINEL"}]}],
         "autoTapSolution": {"autoTapActions": [
             {"instanceId": 283, "abilityGrpId": 7}]}},
        {"actionType": "ActionType_Activate_Mana", "instanceId": 283,
         "abilityGrpId": 7, "manaSelections": []},
        {"actionType": "ActionType_Activate", "instanceId": hidden,
         "targets": [{"targetIdx": -3, "targets": []}],
         "manaCost": "UNEXPECTED_PRIVATE_VALUE"},
        {"actionType": "ActionType_FloatMana"},
        {"actionType": "ActionType_FutureVariant", "other": "PRIVATE_UNKNOWN"},
    ]}
    return original[:9] + [frame]


def save(path, data):
    path.write_text("".join(json.dumps(x) + "\n" for x in data),
                    encoding="utf-8")


class ActionGapTests(unittest.TestCase):
    def test_inventory_counts_and_position_only_no_legality_upgrade(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "Player.log"
            save(log, frames())
            default = replay(log, format="player-log", decision_input=True)
            out = replay(log, format="player-log",
                         decision_input=True, action_gaps=True)
        self.assertNotIn("action_gap_report", default)
        report = out["action_gap_report"]
        self.assertIsNotNone(report)
        self.assertEqual(report["schema"], "mtga-action-evidence-gaps-v1")
        self.assertEqual(report["observed_action_rows"], 7)
        self.assertEqual(report["described_rows"], 5)
        self.assertEqual(report["undetailed_rows"], 2)
        self.assertEqual(report["undetailed_by_type"], [
            {"engine_action_type": "ActionType_FloatMana", "count": 1,
             "gap": "active_engine_row_not_structurally_described"},
            {"engine_action_type": "_unrecognized_action_type", "count": 1,
             "gap": "active_engine_row_not_structurally_described"}])
        actions = report["actions"]
        self.assertEqual([r["list_position"] for r in actions], [0, 1, 2, 3, 4])
        self.assertEqual([r["engine_action_type"] for r in actions],
                         ["ActionType_Pass", "ActionType_Play",
                          "ActionType_Cast", "ActionType_Activate_Mana",
                          "ActionType_Activate"])
        self.assertEqual([r["source_link_status"] for r in actions],
                         ["not_applicable", "visible_unique", "visible_unique",
                          "visible_unique", "not_in_visible_projection"])
        self.assertEqual(actions[2]["parameter_shapes"]["manaCost"],
                         {"shape": "container_size_only", "element_count": 1})
        self.assertEqual(actions[2]["request_local_relations"]
                         ["auto_tap_mana_links"]["unique_pair_rows"], 1)
        self.assertEqual(actions[2]["request_local_relations"]
                         ["target_slots"]["raw_target_groups_shaped"], 1)
        self.assertIn("raw_parameter_structure_incomplete", actions[4]["rule_gaps"])
        self.assertIn("source_visibility_unresolved", actions[4]["rule_gaps"])
        self.assertFalse(report["strategy_evaluation_complete"])
        self.assertTrue(report["engine_listed_not_proven_legal"])
        self.assertIsNone(report["legal_actions"])
        self.assertFalse(report["actionable"])
        self.assertFalse(report["input_sent"])
        self.assertFalse(report["executor_connected"])
        for row in actions:
            self.assertFalse(row["decision_evaluable"])
            self.assertFalse(row["legal_action_verified"])
            self.assertFalse(row["executable"])
        text = json.dumps(report)
        for private in ("PRIVATE_COST_SENTINEL", "PRIVATE_TARGET_SENTINEL",
                        "UNEXPECTED_PRIVATE_VALUE", "PRIVATE_UNKNOWN",
                        '"visible_object_id"', '"instance_id"', '"card_id"',
                        "96839", "92359", "75557"):
            self.assertNotIn(private, text)

    def test_uncertain_source_and_tampered_observation_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "Player.log"
            save(log, frames())
            result = replay(log, format="player-log", decision_input=True)
        obs = result["decision_input"]
        self.assertIsNotNone(assess_action_gaps(obs))
        for change in (
                lambda c: c.update(actionable=True),
                lambda c: c.update(input_sent=True),
                lambda c: c.update(executor_connected=True),
                lambda c: c.update(strategy_selected=True),
                lambda c: c["source"].update(freshness_verified=True),
                lambda c: c["request"].update(type="GREMessageType_SelectNReq"),
                lambda c: c["request"]["engine_action_inventory"].update(
                    offered_count=3),
                lambda c: c["request"]["engine_action_inventory"]["described_rows"][1]
                          .update(visible_object_id=12345678)):
            altered = copy.deepcopy(obs)
            change(altered)
            self.assertIsNone(assess_action_gaps(altered))

    def test_cli_requires_two_opt_ins_and_rejects_synthetic_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "Player.log"
            save(log, frames())
            path = Path(sys.prefix) / ("Scripts/mtgaplayer.exe"
                                       if sys.platform == "win32" else "bin/mtgaplayer")
            self.assertTrue(path.is_file())
            ok = subprocess.run(
                [str(path), "replay", "--format", "player-log",
                 "--decision-input", "--action-gaps", str(log)],
                capture_output=True, text=True, check=False)
            disabled = subprocess.run(
                [str(path), "replay", "--format", "player-log",
                 "--action-gaps", str(log)],
                capture_output=True, text=True, check=False)
            synthetic = subprocess.run(
                [str(path), "replay", "--decision-input", "--action-gaps",
                 str(log)], capture_output=True, text=True, check=False)
        self.assertEqual(ok.returncode, 0, ok.stderr)
        self.assertEqual(json.loads(ok.stdout)["action_gap_report"]
                         ["observed_action_rows"], 7)
        self.assertEqual(disabled.returncode, 1)
        self.assertEqual(json.loads(disabled.stdout)["error"],
                         "action_gaps_requires_decision_input")
        self.assertEqual(synthetic.returncode, 1)
        self.assertEqual(json.loads(synthetic.stdout)["error"],
                         "decision_input_requires_player_log_format")

    def test_original_source_prefix_count_only_gap_coverage_cli(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "Player.log"
            save(log, frames())
            result = inspect_gap_coverage(log)
            command = subprocess.run(
                [sys.executable, str(ROOT / "scripts/inspect_actions.py"),
                 str(log), "--gap-coverage"],
                cwd=ROOT, capture_output=True, text=True, check=False)
        self.assertEqual(command.returncode, 0, command.stderr)
        self.assertEqual(json.loads(command.stdout), result)
        self.assertTrue(result["source"]["complete"])
        self.assertEqual(result["assessed_verified_requests"], 1)
        self.assertEqual(result["engine_active_rows"], 7)
        self.assertEqual(result["described_rows"], 5)
        self.assertEqual(result["undetailed_rows"], 2)
        self.assertEqual(result["source_status_counts"]["visible_unique"], 3)
        self.assertEqual(result["source_status_counts"]["not_applicable"], 1)
        self.assertEqual(result["source_status_counts"]["not_in_visible_projection"], 1)
        self.assertEqual(result["raw_pair_unique_rows"], 1)
        self.assertEqual(result["raw_target_groups_shaped"], 1)
        self.assertTrue(result["counts_not_rule_legality"])
        self.assertIsNone(result["legal_actions"])
        self.assertFalse(result["actionable"])
        self.assertFalse(result["source"]["input_sent"])
        output = json.dumps(result)
        for private in ("PRIVATE_COST_SENTINEL", "PRIVATE_TARGET_SENTINEL",
                        "UNEXPECTED_PRIVATE_VALUE", "PRIVATE_UNKNOWN",
                        "96839", "92359", "75557", str(log)):
            self.assertNotIn(private, output)

    def test_partial_and_selectn_are_not_action_inventory_reports(self):
        source = [json.loads(x) for x in FIXTURE.read_text().splitlines()]
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "Player.log"
            save(log, source)
            selection = replay(log, format="player-log",
                               decision_input=True, action_gaps=True)
            self.assertIsNone(selection["action_gap_report"])
            self.assertTrue(selection["decision_input"]["request"]
                            ["shape_supported"])
            save(log, frames()[:9])
            observations = watch(log, interval=0, samples=3,
                                 decision_input=True, action_gaps=True)
            baseline = next(observations)
            self.assertIsNone(baseline["action_gap_report"])
            tail = (json.dumps(frames()[9]) + "\n").encode("utf-8")
            with log.open("ab") as stream:
                stream.write(tail[:19])
            partial = next(observations)
            self.assertIsNone(partial["decision_input"])
            self.assertIsNone(partial["action_gap_report"])
            with log.open("ab") as stream:
                stream.write(tail[19:])
            final = next(observations)
        self.assertTrue(final["source"]["stopped"])
        self.assertIsNone(final["source"]["candidate_event"])
        self.assertIsNotNone(final["action_gap_report"])
        self.assertFalse(final["action_gap_report"]["actionable"])


if __name__ == "__main__":
    unittest.main()
