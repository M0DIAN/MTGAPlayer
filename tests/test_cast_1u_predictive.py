"""MP98: public real-field 1U Cast route evidence, never real payment truth."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from mtgaplayer.cast_1u_predictive import (
    CONSISTENT, PROFILE, VERSION, assess_current_cast_1u_predictive)
from mtgaplayer.decision_consumer import EXECUTION
from mtgaplayer.rules_index import PreparedRulesIndex
from mtgaplayer.shadow_runtime import LocalShadowRuntime
from test_unified_research import Clock, bootstrap, encoded, wrap

FIXTURES = Path(__file__).parent / "fixtures"


class Cast1UPredictiveTests(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads((FIXTURES / "cast_cardflow_real.json").read_text())
        self.sample = copy.deepcopy(self.fixture["cases"][0])
        self.catalog = json.loads((FIXTURES / "cast_cardflow_reference_real.json").read_text())
        self.resource = json.loads((FIXTURES / "target_effect_real.json").read_text())
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.count = 0

    def stream(self, sample=None):
        sample = copy.deepcopy(sample if sample is not None else self.sample)
        self.count += 1
        path = Path(self.tmp.name) / f"mp98-synthetic-transport-{self.count}.jsonl"
        path.write_bytes(("\n".join(self.resource["resource_prelude"]) + "\n").encode()
                         + encoded(bootstrap(sample)))
        rules = PreparedRulesIndex(self.catalog["metadata"],
                                   {int(k): v for k, v in self.catalog["matches"].items()})
        runtime = LocalShadowRuntime(path, interval=0, clock_ns=Clock(),
                                     observation_mode="controlled_stream_replay",
                                     research_policy="cast_cardflow_research.v1",
                                     prepared_rules=rules)
        stream = runtime.frames()
        self.addCleanup(runtime.close)
        self.addCleanup(stream.close)
        history = next(stream)
        with path.open("ab") as out:
            out.write(encoded([wrap(sample["message"])]))
        current = next(stream)
        return runtime, stream, path, rules, sample, history, current

    @staticmethod
    def evaluate(runtime, rules):
        return assess_current_cast_1u_predictive(
            runtime.consumer, runtime._reducer, runtime._message, rules,
            completed_stamp=runtime._completed_stamp)

    @staticmethod
    def assert_no_authority(test, report):
        for field in ("source_readiness_verified", "actual_mana_paid_observed",
                      "payment_verified", "complete_payment_verified",
                      "legal_choice_verified", "complete_legality_verified",
                      "server_acceptance_verified", "response_encoding_verified",
                      "strategic_optimality_verified", *EXECUTION):
            test.assertIs(report[field], False, field)
        test.assertIs(report["read_only"], True)

    def test_reviewed_real_fields_match_two_predictive_blue_sources_not_payment(self):
        runtime, _, _, rules, _, history, frame = self.stream()
        self.assertEqual(self.fixture["origin"], "retained_scrubbed_real")
        self.assertFalse(self.fixture["raw_equivalent"])
        self.assertEqual(self.fixture["source_opportunity"], 20)
        self.assertNotEqual(history["time_scope"], "current_at_completed_poll")
        self.assertEqual(frame["research_decision"]["status"], "research_preference")
        report = self.evaluate(runtime, rules)
        self.assertEqual(report["schema_version"], VERSION)
        self.assertEqual(report["profile"], PROFILE)
        self.assertEqual(report["status"], CONSISTENT)
        self.assertEqual(report["literal_requirement"], {"generic": 1, "blue": 1})
        self.assertEqual(report["predictive_blue_units"], 2)
        self.assertEqual(report["distinct_predictive_sources"], 2)
        self.assertEqual(report["matched_offered_mana_actions"], 2)
        self.assertEqual(report["explicit_untapped_sources"], 0)
        self.assertEqual(report["sources_with_unknown_tapped_state"], 2)
        self.assertIs(report["predictive_amount_consistency_verified"], True)
        self.assertIs(report["predictive_source_identity_consistency_verified"], True)
        self.assertEqual(report["reviewed_cast_option_key"],
                         frame["research_decision"]["preferred_option_key"])
        self.assert_no_authority(self, report)

    def test_distinct_source_unit_and_same_request_offer_counterexamples(self):
        def offered(sample):
            return sample["message"]["actionsAvailableReq"]["actions"]

        changes = {
            "same_source": lambda s: offered(s)[0]["autoTapSolution"]["autoTapActions"][1].update(
                instanceId=offered(s)[0]["autoTapSolution"]["autoTapActions"][0]["instanceId"]),
            "duplicate_unit_id": lambda s: offered(s)[0]["autoTapSolution"]["autoTapActions"][1]
                ["manaPaymentOption"]["mana"][0].update(
                    manaId=offered(s)[0]["autoTapSolution"]["autoTapActions"][0]
                    ["manaPaymentOption"]["mana"][0]["manaId"]),
            "unit_wrong_count": lambda s: offered(s)[0]["autoTapSolution"]["autoTapActions"][0]
                ["manaPaymentOption"]["mana"][0].update(count=2),
            "mana_offer_missing": lambda s: offered(s)[8].update(abilityGrpId=10018),
            "mana_selections_conflict": lambda s: offered(s)[8]["manaSelections"][0]
                ["options"][0]["mana"][0].update(count=2),
            "wrong_unique_ability": lambda s: offered(s)[8].update(uniqueAbilityId=99999),
            "source_tapped_true": lambda s: next(
                o for o in s["initial"]["objects"] if o["instanceId"] == 1015).update(isTapped=True),
            "cast_wrong_cost": lambda s: offered(s)[0].update(
                manaCost=[{"color": ["ManaColor_Generic"], "count": 2},
                          {"color": ["ManaColor_Blue"], "count": 1}]),
        }
        for label, change in changes.items():
            with self.subTest(control=label):
                sample = copy.deepcopy(self.sample)
                change(sample)
                runtime, _, _, rules, _, _, _ = self.stream(sample)
                result = self.evaluate(runtime, rules)
                self.assertNotEqual(result["status"], CONSISTENT, label)
                self.assertIsNone(result["reviewed_cast_option_key"])
                self.assertIs(result["predictive_amount_consistency_verified"], False)
                self.assert_no_authority(self, result)

    def test_actual_response_consumption_revokes_stale_predicted_route(self):
        runtime, stream, path, rules, sample, _, frame = self.stream()
        before = self.evaluate(runtime, rules)
        self.assertEqual(before["status"], CONSISTENT)
        selected = next(a for a in sample["message"]["actionsAvailableReq"]["actions"]
                        if a.get("grpId") == 96626)
        response = {"payload": {
            "type": "ClientMessageType_PerformActionResp",
            "respId": sample["message"]["msgId"],
            "gameStateId": sample["message"]["gameStateId"],
            "performActionResp": {"actions": [selected]}}}
        with path.open("ab") as out:
            out.write(encoded([response]))
        after_frame = next(stream)
        self.assertNotEqual(after_frame["time_scope"], "current_at_completed_poll")
        after = self.evaluate(runtime, rules)
        self.assertNotEqual(after["status"], CONSISTENT)
        self.assertIsNone(after["reviewed_cast_option_key"])
        self.assert_no_authority(self, after)


if __name__ == "__main__":
    unittest.main()
