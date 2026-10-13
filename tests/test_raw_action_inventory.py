"""MP7: typed, read-only ActionsAvailableReq observations derived from local schema."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from mtgaplayer.cli import watch
from mtgaplayer.raw_log import RawReducer


FIXTURE = Path(__file__).parent / "fixtures" / "player_log_selectn.jsonl"


def fixture_rows():
    return [json.loads(row) for row in FIXTURE.read_text(encoding="utf-8").splitlines()]


def actions_request(row):
    return next(m for m in row["greToClientEvent"]["greToClientMessages"]
                if m.get("type") == "GREMessageType_ActionsAvailableReq")


def reduced(rows):
    reducer = RawReducer()
    reducer.reset(1)
    for row in rows:
        reducer.apply(row)
    return reducer.document()


class RawActionInventoryTests(unittest.TestCase):
    def test_actual_fixture_header_is_unsupported_without_payload(self):
        source = fixture_rows()
        doc = reduced(source[:10])
        self.assertTrue(doc["current"]["valid"])
        req = doc["current"]["request"]
        self.assertEqual((req["id"], req["game_state_id"]), (37, 23))
        self.assertFalse(req["supported"])
        self.assertEqual(req["unsupported_reason"], "missing_actions_available_payload")
        self.assertIsNone(req["action_inventory"])
        self.assertEqual(req["candidates"], [])
        self.assertIsNone(doc["current"]["legal_actions"])
        self.assertFalse(doc["current"]["actionable"])

    def test_own_seat_active_inventory_excludes_inactive_and_unknown_details(self):
        source = fixture_rows()
        injected = copy.deepcopy(source[9])
        actions_request(injected)["actionsAvailableReq"] = {
            "actions": [
                {"actionType": "ActionType_Pass"},
                {"actionType": "ActionType_Play", "instanceId": 161,
                 "grpId": 96839, "facetId": 0, "shouldStop": False},
                {"actionType": "ActionType_Cast", "instanceId": 161,
                 "manaCost": [{"count": 1, "color": ["ManaColor_Red"]}],
                 "targets": [{"targetIdx": 0, "targets": [212]}]},
                {"actionType": "ActionType_Activate_Mana",
                 "manaSelections": [{"instanceId": 999, "options": ["hidden-value"]}]},
            ],
            "inactiveActions": [{"actionType": "ActionType_Private",
                                 "secret": "HIDDEN_SENTINEL"}],
        }
        doc = reduced(source[:9] + [injected])
        self.assertIsNone(doc["error"])
        self.assertTrue(doc["current"]["valid"])
        req = doc["current"]["request"]
        self.assertTrue(req["binding"]["ownership_verified"])
        self.assertEqual((req["id"], req["game_state_id"]), (37, 23))
        self.assertFalse(req["supported"])
        self.assertEqual(req["unsupported_reason"], "action_details_unverified")
        inv = req["action_inventory"]
        self.assertEqual(inv["offered_count"], 4)
        self.assertEqual(inv["inactive_count"], 1)
        self.assertTrue(inv["inactive_excluded"])
        self.assertEqual(inv["types"], [
            {"action_type": "ActionType_Activate_Mana", "count": 1},
            {"action_type": "ActionType_Cast", "count": 1},
            {"action_type": "ActionType_Pass", "count": 1},
            {"action_type": "ActionType_Play", "count": 1},
        ])
        self.assertEqual(inv["simple_shapes"], [
            {"list_position": 0, "action_type": "ActionType_Pass"},
            {"list_position": 1, "action_type": "ActionType_Play",
             "instance_id": 161, "grp_id": 96839,
             "facet_id": 0, "should_stop_raw": False},
        ])
        self.assertEqual(inv["remaining_action_details_unverified"], 2)
        self.assertFalse(inv["semantics_complete"])
        self.assertFalse(inv["legal_actions_complete"])
        self.assertFalse(inv["executable"])
        self.assertEqual(req["candidates"], [])
        self.assertIsNone(req["selection"])
        self.assertIsNone(doc["current"]["legal_actions"])
        self.assertFalse(doc["current"]["actionable"])
        output = json.dumps(doc)
        for private in ("HIDDEN_SENTINEL", "hidden-value", "ActionType_Private",
                        "ManaColor_Red"):
            self.assertNotIn(private, output)

    def test_invalid_shapes_and_other_seats_never_expose_actions(self):
        source = fixture_rows()
        for invalid in ({"actions": [{"actionType": {"unexpected": "raw"}}]},
                        {"actions": "not-an-array"},
                        {"actions": [{"actionType": "ActionType_Pass"}],
                         "inactiveActions": "not-an-array"}):
            with self.subTest(invalid=invalid):
                row = copy.deepcopy(source[9])
                actions_request(row)["actionsAvailableReq"] = invalid
                doc = reduced(source[:9] + [row])
                self.assertTrue(doc["current"]["valid"])
                request = doc["current"]["request"]
                self.assertFalse(request["supported"])
                self.assertEqual(request["candidates"], [])
                self.assertIsNone(request["selection"])
                self.assertFalse(doc["current"]["actionable"])
                self.assertNotIn("unexpected", json.dumps(doc))
        for seats in ([2], [1, 2]):
            with self.subTest(seats=seats):
                row = copy.deepcopy(source[9])
                req = actions_request(row)
                req["systemSeatIds"] = seats
                req["actionsAvailableReq"] = {
                    "actions": [{"actionType": "ActionType_Play", "instanceId": 421337,
                                 "grpId": 999, "facetId": 0, "shouldStop": False}]}
                doc = reduced(source[:9] + [row])
                self.assertTrue(doc["current"]["valid"])
                self.assertIsNone(doc["current"]["request"])
                self.assertNotIn("421337", json.dumps(doc))

    def test_watch_append_inventory_does_not_become_actionable_or_candidate_event(self):
        source = fixture_rows()
        final = copy.deepcopy(source[9])
        actions_request(final)["actionsAvailableReq"] = {
            "actions": [{"actionType": "ActionType_Pass"}]}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Player.log"
            path.write_text("".join(json.dumps(r) + "\n" for r in source[:9]),
                            encoding="utf-8")
            samples = watch(path, interval=0, samples=2)
            history = next(samples)
            self.assertEqual(history["source"]["phase"], "history")
            with path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(final) + "\n")
            appended = next(samples)
            self.assertEqual(appended["source"]["phase"], "append")
            self.assertTrue(appended["current"]["valid"])
            self.assertEqual(appended["current"]["request"]["action_inventory"]
                             ["types"][0]["action_type"], "ActionType_Pass")
            self.assertIsNone(appended["source"]["candidate_event"])
            self.assertFalse(appended["current"]["actionable"])
            self.assertFalse(appended["source"]["input_sent"])
            self.assertFalse(appended["source"]["executor_connected"])


if __name__ == "__main__":
    unittest.main()
