"""MP9: scoped raw pair equality and target positions; never executable."""
import copy
import json
from pathlib import Path
import unittest
from mtgaplayer.raw_log import RawReducer

FIXTURE = Path(__file__).parent / "fixtures/player_log_selectn.jsonl"


def sample(actions, inactive=()):
    source = [json.loads(x) for x in FIXTURE.read_text().splitlines()]
    row = copy.deepcopy(source[9])
    msg = next(m for m in row["greToClientEvent"]["greToClientMessages"]
               if m.get("type") == "GREMessageType_ActionsAvailableReq")
    msg["actionsAvailableReq"] = {"actions": actions, "inactiveActions": list(inactive)}
    reducer = RawReducer()
    reducer.reset(1)
    for item in source[:9] + [row]:
        reducer.apply(item)
    return reducer.document()


class MP9LinksTests(unittest.TestCase):
    def test_one_active_mana_pair_matches_but_inactive_is_ignored(self):
        mana = {"actionType": "ActionType_Activate_Mana", "instanceId": 80,
                "abilityGrpId": 90, "manaSelections": [
                    {"instanceId": 80, "abilityGrpId": 90,
                     "options": [{"other": "LEAF_VALUE"}]}]}
        cast = {"actionType": "ActionType_Cast", "instanceId": 70,
                "autoTapSolution": {"autoTapActions": [
                    {"instanceId": 80, "abilityGrpId": 90, "manaId": 912341},
                    {"instanceId": 80, "abilityGrpId": 91}]},
                "targets": [{"targetIdx": 0, "targets": ["TARGET_LEAF"]}]}
        doc = sample([cast, mana], [{"actionType": "ActionType_Activate_Mana",
                                     "instanceId": 80, "abilityGrpId": 91}])
        request = doc["current"]["request"]
        self.assertTrue(request["binding"]["ownership_verified"])
        self.assertFalse(request["supported"])
        self.assertEqual(request["candidates"], [])
        inv = request["action_inventory"]
        self.assertEqual(inv["inactive_count"], 1)
        cast_link, mana_link = [x["raw_relations"] for x in inv["complex_raw_shapes"]]
        self.assertEqual(cast_link["auto_tap_mana_links"]["entries"], [
            {"position": 0, "status": "unique_pair", "active_mana_position": 1},
            {"position": 1, "status": "no_active_pair"}])
        self.assertEqual(mana_link["mana_selection_links"]["entries"], [
            {"position": 0, "status": "unique_pair", "active_mana_position": 1}])
        self.assertEqual(cast_link["target_slots"]["entries"][0]["target_count"], 1)
        self.assertFalse(cast_link["payment_legal"])
        self.assertFalse(cast_link["targets_legal"])
        self.assertIsNone(doc["current"]["legal_actions"])
        self.assertFalse(doc["current"]["actionable"])
        text = json.dumps(doc)
        for word in ("LEAF_VALUE", "TARGET_LEAF", "912341"):
            self.assertNotIn(word, text)

    def test_duplicates_and_invalid_inputs_have_no_unique_link(self):
        data = [{"actionType": "ActionType_Activate_Mana",
                 "instanceId": 10, "abilityGrpId": 20} for _ in range(2)]
        data.append({"actionType": "ActionType_Cast",
                     "autoTapSolution": {"autoTapActions": [
                         {"instanceId": 10, "abilityGrpId": 20},
                         {"instanceId": 10, "abilityGrpId": True},
                         {"instanceId": 10, "abilityGrpId": 30},
                         "SENTINEL"]},
                     "targets": [{"targetIdx": True, "targets": "bad"}]})
        doc = sample(data)
        relation = doc["current"]["request"]["action_inventory"]["complex_raw_shapes"][2]["raw_relations"]
        entries = relation["auto_tap_mana_links"]["entries"]
        self.assertEqual([x["status"] for x in entries],
                         ["ambiguous_pair", "missing_or_invalid_pair",
                          "no_active_pair", "non_object"])
        self.assertTrue(all("active_mana_position" not in x for x in entries))
        self.assertFalse(relation["target_slots"]["entries"][0]["valid_shape"])
        self.assertNotIn("SENTINEL", json.dumps(doc))
        self.assertFalse(doc["current"]["actionable"])


if __name__ == "__main__":
    unittest.main()
