"""MP13: request-bound, read-only decision observation from actual GRE projection."""
import copy
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from mtgaplayer.cli import replay, watch
from mtgaplayer.decision_input import build_decision_input
from mtgaplayer.raw_log import RawReducer


FIXTURE = Path(__file__).parent / "fixtures" / "player_log_selectn.jsonl"


def rows():
    return [json.loads(x) for x in FIXTURE.read_text(encoding="utf-8").splitlines()]


def action_frames():
    original = rows()
    frame = copy.deepcopy(original[9])
    message = next(m for m in frame["greToClientEvent"]["greToClientMessages"]
                   if m.get("type") == "GREMessageType_ActionsAvailableReq")
    # Explicit synthetic actions injected into the real-source Full/Diff chain.
    # Use an actual opponent-private hand instance from the sanitized state
    # as one action source: it must NEVER become a visible source reference.
    base = RawReducer()
    base.reset(1)
    for entry in original[:9]:
        base.apply(entry)
    opponent_hand = next(z for z in base.zones.values()
                         if z.get("type") == "ZoneType_Hand"
                         and z.get("ownerSeatId") == 2)
    hidden_instance = opponent_hand["objectInstanceIds"][0]
    message["actionsAvailableReq"] = {"actions": [
        {"actionType": "ActionType_Play", "instanceId": 166, "grpId": 96839,
         "facetId": 0, "shouldStop": False},
        {"actionType": "ActionType_Cast", "instanceId": 161, "grpId": 92359,
         "manaCost": [], "targets": [{"targetIdx": 0,
                                     "targets": [{"secret": "HIDDEN_TARGET_SENTINEL"}]}],
         "autoTapSolution": {"autoTapActions": [
             {"instanceId": 283, "abilityGrpId": 7}]}},
        {"actionType": "ActionType_Activate_Mana", "instanceId": 283,
         "abilityGrpId": 7, "manaSelections": []},
        {"actionType": "ActionType_Cast", "instanceId": hidden_instance,
         "manaCost": [{"secret": "SECRET_PAYMENT_SENTINEL"}]},
        {"actionType": "ActionType_Pass"},
        {"actionType": "ActionType_FloatMana"},
    ]}
    return original[:9] + [frame]


def log_file(path, frames):
    path.write_text("".join(json.dumps(frame) + "\n" for frame in frames),
                    encoding="utf-8")


def catalog_file(path):
    with closing(sqlite3.connect(path)) as db, db:
        db.execute(
            "CREATE TABLE Cards (GrpId INTEGER, TitleId INTEGER, Power TEXT, "
            "Toughness TEXT, ExpansionCode TEXT, CollectorNumber TEXT)")
        db.execute("CREATE TABLE Localizations_enUS "
                   "(LocId INTEGER, Formatted INTEGER, Loc TEXT)")
        db.executemany("INSERT INTO Cards VALUES (?,?,?,?,?,?)", [
            (96839, 1, "3", "4", "SET", "001"),
            (92359, 2, "", "*", "SET", "002"),
            (75557, 3, "-1", "0", "SET", "003"),
            (999999, 4, "88", "88", "SET", "004")])
        db.executemany("INSERT INTO Localizations_enUS VALUES (?,?,?)", [
            (1, 1, "Land Example"), (2, 1, "Spell Example"),
            (3, 1, "Permanent Example"),
            (4, 1, "OPPONENT_PRIVATE_CATALOG_SENTINEL")])


class DecisionInputTests(unittest.TestCase):
    def test_action_positions_visible_sources_and_raw_constraints_only(self):
        frames = action_frames()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Player.log"
            log_file(path, frames)
            default = replay(path, format="player-log")
            result = replay(path, format="player-log", decision_input=True)
        self.assertNotIn("decision_input", default)
        observation = result["decision_input"]
        self.assertIsNotNone(observation)
        self.assertEqual(observation["schema"], "mtga-readonly-decision-input-v1")
        self.assertEqual(observation["status"], "request_observed_only")
        self.assertEqual(observation["binding"]["request_id"],
                         result["current"]["request"]["id"])
        self.assertEqual(observation["binding"]["game_state_id"],
                         result["current"]["game_state_id"])
        self.assertTrue(observation["binding"]["ownership_verified"])
        self.assertEqual(observation["binding"]["generation"],
                         result["source"]["generation"])
        self.assertFalse(observation["actionable"])
        self.assertFalse(observation["input_sent"])
        self.assertFalse(observation["executor_connected"])
        self.assertFalse(observation["strategy_selected"])
        self.assertFalse(observation["source"]["freshness_verified"])
        self.assertIsNone(observation["unknown"]["legal_actions"])
        self.assertIsNone(observation["unknown"]["target_legality"])
        self.assertIsNone(observation["unknown"]["mana_payment_legality"])
        self.assertIsNone(observation["game"]["effective_combat_stats"])
        self.assertIsNone(observation["request"]["select_n"])

        inventory = observation["request"]["engine_action_inventory"]
        self.assertEqual(inventory["offered_count"], 6)
        self.assertEqual(inventory["described_count"], 5)
        self.assertEqual(inventory["undetailed_count"], 1)
        self.assertTrue(inventory["inactive_excluded"])
        self.assertFalse(inventory["legal_actions_complete"])
        described = inventory["described_rows"]
        self.assertEqual([x["list_position"] for x in described], [0, 1, 2, 3, 4])
        self.assertEqual([x.get("visible_object_id") for x in described],
                         [166, 161, 283, None, None])
        self.assertEqual(described[3]["source_link_status"],
                         "not_in_visible_projection")
        self.assertEqual(described[4]["source_link_status"], "not_applicable")
        self.assertNotIn("visible_object_id", described[3])
        self.assertEqual(
            described[1]["raw_relations"]["auto_tap_mana_links"]["entries"][0]
            ["active_mana_position"], 2)
        self.assertFalse(described[1]["raw_relations"]["payment_legal"])
        self.assertFalse(described[1]["raw_relations"]["targets_legal"])
        self.assertEqual(
            described[1]["raw_relations"]["target_slots"]["entries"][0]["target_count"], 1)
        self.assertNotIn("raw_identifiers", described[1])
        payload = json.dumps(observation)
        self.assertNotIn("HIDDEN_TARGET_SENTINEL", payload)
        self.assertNotIn("SECRET_PAYMENT_SENTINEL", payload)
        self.assertNotIn("OPPONENT_PRIVATE_CATALOG_SENTINEL", payload)
        self.assertFalse(result["current"]["actionable"])
        self.assertIsNone(result["current"]["legal_actions"])
        broken = copy.deepcopy(result)
        links = broken["current"]["request"]["action_inventory"][
            "visible_source_links"]["links"]
        links.append(copy.deepcopy(links[0]))  # Conflicting source position.
        self.assertIsNone(build_decision_input(broken))

    def test_catalog_opt_in_is_provenance_labeled_no_private_card_leak(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path, db = root / "Player.log", root / "card.db"
            log_file(path, action_frames())
            catalog_file(db)
            result = replay(path, format="player-log", card_db_path=db,
                            decision_input=True)
        self.assertIsNotNone(result["decision_input"])
        obs = result["decision_input"]
        visible = {item["instance_id"]: item for item in obs["visible_objects"]}
        self.assertEqual(visible[166]["local_card"]["name"], "Land Example")
        self.assertEqual(visible[166]["local_card"]["static_catalog_stats"]["power"], 3)
        self.assertEqual(visible[166]["local_card"]["static_catalog_stats"]["toughness"], 4)
        self.assertFalse(
            visible[166]["local_card"]["static_catalog_stats"]["effective_in_game"])
        self.assertIsNone(visible[161]["local_card"]["static_catalog_stats"]["power"])
        self.assertIsNone(visible[161]["local_card"]["static_catalog_stats"]["toughness"])
        self.assertNotIn("OPPONENT_PRIVATE_CATALOG_SENTINEL", json.dumps(obs))
        self.assertNotIn("decision_input", json.dumps(result["last_valid"]))
        self.assertNotIn("local_card", json.dumps(result["last_valid"]))
        self.assertFalse(obs["read_only"] is False)
        self.assertFalse(obs["request"]["shape_supported"])
        self.assertIsNone(obs["unknown"]["complete_rules"])

    def test_selectn_and_binding_freshness_are_not_action_permission(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Player.log"
            log_file(path, rows())
            result = replay(path, format="player-log", decision_input=True)
        obs = result["decision_input"]
        self.assertIsNotNone(obs)
        self.assertEqual(obs["request"]["type"], "GREMessageType_SelectNReq")
        self.assertTrue(obs["request"]["shape_supported"])
        self.assertEqual(obs["request"]["select_n"]["offered_instance_ids"],
                         [175, 176, 178, 179])
        self.assertEqual(obs["request"]["select_n"]["max_sel_raw"], 2)
        self.assertIsNone(obs["request"]["select_n"]["min_sel_verified"])
        self.assertFalse(obs["request"]["select_n"]["combinations_complete"])
        self.assertTrue(obs["request"]["select_n"]["source_ids_not_visibility_joined"])
        self.assertIsNone(obs["request"]["engine_action_inventory"])
        self.assertFalse(obs["actionable"])
        self.assertFalse(obs["source"]["freshness_verified"])
        for replacement in (
                lambda r: r["current"]["request"]["binding"].update(game_state_id=999),
                lambda r: r["source"].update(generation=999),
                lambda r: r["source"].update(partial_record=True),
                lambda r: r["current"].update(valid=False),
                lambda r: r["current"].update(request=None),
                lambda r: r["current"].update(actionable=True),
                lambda r: r["source"].update(input_sent=True),
                lambda r: r["current"]["request"].update(current=False)):
            mutated = copy.deepcopy(result)
            replacement(mutated)
            self.assertIsNone(build_decision_input(mutated))
        invalid = copy.deepcopy(result)
        invalid["current"] = {"valid": False, "actionable": False}
        self.assertIsNotNone(invalid["last_valid"])
        self.assertIsNone(build_decision_input(invalid))

    def test_installed_cli_opt_in_and_normalized_guard(self):
        executable = Path(sys.prefix) / (
            "Scripts/mtgaplayer.exe" if os.name == "nt" else "bin/mtgaplayer")
        self.assertTrue(executable.is_file())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Player.log"
            log_file(path, action_frames())
            with_input = subprocess.run(
                [str(executable), "replay", "--format", "player-log",
                 "--decision-input", str(path)],
                capture_output=True, text=True, check=False)
            default = subprocess.run(
                [str(executable), "replay", "--format", "player-log", str(path)],
                capture_output=True, text=True, check=False)
            wrong_format = subprocess.run(
                [str(executable), "replay", "--decision-input", str(path)],
                capture_output=True, text=True, check=False)
        self.assertEqual(with_input.returncode, 0, with_input.stderr)
        self.assertEqual(default.returncode, 0, default.stderr)
        self.assertEqual(json.loads(with_input.stdout)["decision_input"]
                         ["binding"]["game_state_id"],
                         json.loads(with_input.stdout)["current"]["game_state_id"])
        self.assertNotIn("decision_input", json.loads(default.stdout))
        self.assertEqual(wrong_format.returncode, 1)
        self.assertEqual(json.loads(wrong_format.stdout)["error"],
                         "decision_input_requires_player_log_format")

    def test_watch_observation_no_event_promotion_and_partial_wait(self):
        records = action_frames()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Player.log"
            log_file(path, records[:9])
            generator = watch(path, interval=0, samples=3, decision_input=True)
            first = next(generator)
            self.assertIsNone(first["decision_input"])
            raw = (json.dumps(records[9]) + "\n").encode("utf-8")
            with path.open("ab") as f:
                f.write(raw[:21])
            partial = next(generator)
            self.assertTrue(partial["source"]["partial_record"])
            self.assertIsNone(partial["decision_input"])
            self.assertIsNone(partial["source"]["candidate_event"])
            with path.open("ab") as f:
                f.write(raw[21:])
            last = next(generator)
        self.assertEqual(last["source"]["phase"], "append")
        self.assertTrue(last["source"]["stopped"])
        self.assertIsNone(last["source"]["candidate_event"])
        self.assertIsNotNone(last["decision_input"])
        self.assertEqual(last["decision_input"]["source"]["mode"], "watch")
        self.assertTrue(last["decision_input"]["source"]["stopped"])
        self.assertFalse(last["decision_input"]["actionable"])
        self.assertFalse(last["decision_input"]["executor_connected"])


if __name__ == "__main__":
    unittest.main()
