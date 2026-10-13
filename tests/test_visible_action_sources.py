"""MP10: link only engine-described sources to the existing visible projection."""
import copy
import json
from pathlib import Path
import unittest

from mtgaplayer.raw_log import RawReducer


FIXTURE = Path(__file__).parent / "fixtures" / "player_log_selectn.jsonl"


def source_rows():
    return [json.loads(row) for row in FIXTURE.read_text(encoding="utf-8").splitlines()]


def projected(actions):
    rows = source_rows()
    frame = copy.deepcopy(rows[9])
    prompt = next(m for m in frame["greToClientEvent"]["greToClientMessages"]
                  if m.get("type") == "GREMessageType_ActionsAvailableReq")
    prompt["actionsAvailableReq"] = {"actions": actions}
    reducer = RawReducer()
    reducer.reset(1)
    for row in rows[:9] + [frame]:
        reducer.apply(row)
    return reducer


class VisibleSourceLinksTests(unittest.TestCase):
    def test_real_state_visible_own_hand_and_public_objects_only(self):
        actions = [
            {"actionType": "ActionType_Play", "instanceId": 166,
             "grpId": 96839, "facetId": 0, "shouldStop": False},
            {"actionType": "ActionType_Cast", "instanceId": 161,
             "grpId": 999999, "manaCost": []},
            {"actionType": "ActionType_Activate_Mana", "instanceId": 283,
             "abilityGrpId": 4211, "manaSelections": []},
            {"actionType": "ActionType_Cast", "instanceId": 800008,
             "manaCost": []},
            {"actionType": "ActionType_Cast", "grpId": 901,
             "manaCost": []},
            {"actionType": "ActionType_Pass"},
        ]
        reducer = projected(actions)
        doc = reducer.document()
        self.assertIsNone(doc["error"])
        current = doc["current"]
        self.assertTrue(current["valid"])
        self.assertTrue(current["request"]["binding"]["ownership_verified"])
        self.assertFalse(current["request"]["supported"])
        self.assertEqual(current["request"]["candidates"], [])
        self.assertIsNone(current["legal_actions"])
        self.assertFalse(current["actionable"])
        inv = current["request"]["action_inventory"]
        links = inv["visible_source_links"]
        self.assertEqual(links["scope"],
                         "described_active_actions_and_current_visible_objects_only")
        self.assertEqual((links["link_count"], links["unique_visible_count"]), (5, 3))
        self.assertEqual([r["list_position"] for r in links["links"]],
                         [0, 1, 2, 3, 4])
        self.assertEqual([r["status"] for r in links["links"]],
                         ["visible_unique", "visible_unique", "visible_unique",
                          "not_in_visible_projection", "missing_source_instance"])
        self.assertEqual([r["visible_object_id"] for r in links["links"][:3]],
                         [166, 161, 283])
        self.assertTrue(links["links"][0]["raw_group_equals_visible_card_id"])
        self.assertFalse(links["links"][1]["raw_group_equals_visible_card_id"])
        self.assertIsNone(links["links"][2]["raw_group_equals_visible_card_id"])
        self.assertFalse(links["all_legal_actions_known"])
        self.assertFalse(links["executable"])
        self.assertNotIn("visible_source_links", reducer.request["action_inventory"])

    def test_private_opponent_hand_never_becomes_visible_source(self):
        rows = source_rows()
        reducer = RawReducer()
        reducer.reset(1)
        for frame in rows[:9]:
            reducer.apply(frame)
        current = reducer.document()["current"]
        self.assertTrue(current["valid"])
        private_hand = next(zone for zone in reducer.zones.values()
                            if zone.get("type") == "ZoneType_Hand"
                            and zone.get("ownerSeatId") == 2)
        hidden = private_hand["objectInstanceIds"][0]
        self.assertNotIn(hidden, {obj["id"] for obj in current["objects"]})

        request_frame = copy.deepcopy(rows[9])
        request = next(m for m in request_frame["greToClientEvent"]["greToClientMessages"]
                       if m.get("type") == "GREMessageType_ActionsAvailableReq")
        request["actionsAvailableReq"] = {"actions": [
            {"actionType": "ActionType_Cast", "instanceId": hidden,
             "manaCost": [{"color": ["PRIVATE_VALUE"]}]}]}
        reducer.apply(request_frame)
        out = reducer.document()
        link = out["current"]["request"]["action_inventory"]["visible_source_links"]["links"][0]
        self.assertEqual(link["status"], "not_in_visible_projection")
        self.assertNotIn("visible_object_id", link)
        self.assertNotIn("card_id", link)
        self.assertFalse(out["current"]["actionable"])
        self.assertNotIn("PRIVATE_VALUE", json.dumps(out))


if __name__ == "__main__":
    unittest.main()
