"""MP8: non-executable request-scoped Cast/Activate/mana raw shapes."""
import copy
import json
from pathlib import Path
import unittest

from mtgaplayer.raw_log import RawReducer


SOURCE = Path(__file__).parent / "fixtures" / "player_log_selectn.jsonl"


def _base_with_request():
    rows = [json.loads(line) for line in SOURCE.read_text(encoding="utf-8").splitlines()]
    candidate = copy.deepcopy(rows[9])
    request = next(m for m in candidate["greToClientEvent"]["greToClientMessages"]
                   if m.get("type") == "GREMessageType_ActionsAvailableReq")
    return rows[:9], candidate, request


def _run(rows):
    reducer = RawReducer()
    reducer.reset(1)
    for row in rows:
        reducer.apply(row)
    return reducer.document()


class ComplexActionRawShapesTests(unittest.TestCase):
    def test_known_complex_types_preserve_only_flat_raw_fields_and_opaque_counts(self):
        baseline, record, request = _base_with_request()
        request["actionsAvailableReq"] = {
            "actions": [
                {"actionType": "ActionType_Pass"},
                {"actionType": "ActionType_Cast", "instanceId": 161, "grpId": 900,
                 "facetId": 0, "shouldStop": False,
                 "manaCost": [{"count": 1, "color": ["ManaColor_Blue"]}],
                 "targets": [{"targetIdx": 0, "targets": ["SECRET_TARGET"]}],
                 "autoTapSolution": {"autoTapActions": [
                     {"instanceId": 80000, "abilityGrpId": 90000, "secret": "SECRET_TAP"}]}},
                {"actionType": "ActionType_Activate", "instanceId": 170,
                 "abilityGrpId": 300, "uniqueAbilityId": 901,
                 "manaCost": [{"abilityGrpId": 100000, "count": 2}],
                 "targets": [{"targetIdx": 1, "targets": [98765]}],
                 "unknownPayload": {"private": "SECRET_EXTRA"}},
                {"actionType": "ActionType_Activate_Mana",
                 "instanceId": 174, "abilityGrpId": 301, "uniqueAbilityId": 902,
                 "isBatchable": True, "isManaAbilityWithSideEffect": False,
                 "manaPaymentOptions": [{"mana": [{"id": "SECRET_MANA"}]}],
                 "manaSelections": [{"options": [1, 2, 3]}]},
                {"actionType": "ActionType_FloatMana"},
            ],
            "inactiveActions": [{
                "actionType": "ActionType_Cast", "instanceId": 1357911,
                "targets": [{"private": "SECRET_INACTIVE"}]}],
        }
        result = _run(baseline + [record])
        self.assertIsNone(result["error"])
        self.assertTrue(result["current"]["valid"])
        current = result["current"]
        req = current["request"]
        self.assertTrue(req["binding"]["ownership_verified"])
        self.assertFalse(req["supported"])
        self.assertEqual(req["unsupported_reason"], "action_details_unverified")
        self.assertEqual(req["candidates"], [])
        inv = req["action_inventory"]
        self.assertEqual(inv["offered_count"], 5)
        self.assertEqual(inv["inactive_count"], 1)
        self.assertEqual(inv["simple_shapes_count"], 1)
        self.assertEqual(inv["complex_raw_shapes_count"], 3)
        self.assertEqual(inv["remaining_action_details_unverified"], 4)
        self.assertEqual([r["list_position"] for r in inv["complex_raw_shapes"]], [1, 2, 3])
        cast, activate, mana = inv["complex_raw_shapes"]
        self.assertEqual(cast["action_type"], "ActionType_Cast")
        self.assertEqual(cast["raw_identifiers"],
                         {"instance_id": 161, "grp_id": 900, "facet_id": 0})
        self.assertEqual(cast["raw_flags"], {"should_stop": False})
        self.assertEqual(cast["opaque_parameter_shapes"], {
            "manaCost": {"kind": "array", "element_count": 1},
            "targets": {"kind": "array", "element_count": 1},
            "autoTapSolution": {"kind": "object", "auto_tap_actions_count": 1},
        })
        self.assertEqual(activate["raw_identifiers"],
                         {"instance_id": 170, "ability_grp_id": 300,
                          "unique_ability_id": 901})
        self.assertTrue(activate["other_top_level_fields_present"])
        self.assertEqual(mana["raw_flags"], {
            "is_batchable": True, "is_mana_ability_with_side_effect": False})
        self.assertEqual(mana["opaque_parameter_shapes"]["manaSelections"]["element_count"], 1)
        self.assertEqual(mana["opaque_parameter_shapes"]["manaPaymentOptions"]["element_count"], 1)
        for shape in inv["complex_raw_shapes"]:
            self.assertFalse(shape["semantics_complete"])
            self.assertFalse(shape["legal_action_verified"])
            self.assertFalse(shape["executable"])
            self.assertTrue(shape["read_only"])
        self.assertIsNone(current["legal_actions"])
        self.assertFalse(current["actionable"])
        output = json.dumps(result)
        for raw_private in ("ManaColor_Blue", "SECRET_TARGET", "SECRET_TAP",
                            "SECRET_EXTRA", "SECRET_MANA", "SECRET_INACTIVE",
                            "1357911", "80000", "90000", "98765", "100000"):
            self.assertNotIn(raw_private, output)

    def test_malformed_known_scalar_or_nested_container_is_not_treated_as_semantics(self):
        baseline, record, request = _base_with_request()
        request["actionsAvailableReq"] = {
            "actions": [{"actionType": "ActionType_Cast",
                         "instanceId": "PRIVATE_BAD_ID", "grpId": True,
                         "shouldStop": "PRIVATE_BAD_FLAG",
                         "manaCost": {"secret": "PRIVATE_COST"},
                         "autoTapSolution": {"autoTapActions": "PRIVATE_TAP"},
                         "targets": [{"targetIdx": "PRIVATE_TARGET"}]}]}
        result = _run(baseline + [record])
        self.assertTrue(result["current"]["valid"])
        req = result["current"]["request"]
        self.assertFalse(req["supported"])
        shape = req["action_inventory"]["complex_raw_shapes"][0]
        self.assertEqual(shape["raw_identifiers"], {})
        self.assertEqual(shape["raw_flags"], {})
        self.assertEqual(set(shape["invalid_known_field_types"]),
                         {"instanceId", "grpId", "shouldStop",
                          "manaCost", "autoTapSolution"})
        self.assertEqual(shape["opaque_parameter_shapes"]["manaCost"],
                         {"kind": "unexpected", "element_count": None})
        self.assertEqual(shape["opaque_parameter_shapes"]["autoTapSolution"],
                         {"kind": "object", "auto_tap_actions_count": None})
        self.assertEqual(shape["opaque_parameter_shapes"]["targets"]["element_count"], 1)
        self.assertFalse(shape["legal_action_verified"])
        self.assertFalse(shape["executable"])
        self.assertIsNone(result["current"]["legal_actions"])
        self.assertFalse(result["current"]["actionable"])
        output = json.dumps(result)
        for secret in ("PRIVATE_BAD_ID", "PRIVATE_BAD_FLAG", "PRIVATE_COST",
                       "PRIVATE_TAP", "PRIVATE_TARGET"):
            self.assertNotIn(secret, output)


if __name__ == "__main__":
    unittest.main()
