"""MP98: public real-field 1U Cast route evidence, never real payment truth."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from mtgaplayer.cast_1u_predictive import (
    CONSISTENT, PROFILE, VERSION, assess_current_cast_1u_predictive,
    reconcile_observed_cast_1u_sources)
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

    def test_synthetic_conflicting_unique_ability_id_is_not_an_identity_proof(self):
        sample = copy.deepcopy(self.sample)
        mana = sample["message"]["actionsAvailableReq"]["actions"][8]
        source = next(o for o in sample["initial"]["objects"]
                      if o["instanceId"] == mana["instanceId"])
        source["uniqueAbilities"].append({"id": mana["uniqueAbilityId"],
                                          "grpId": mana["abilityGrpId"] + 1})
        runtime, _, _, rules, _, _, frame = self.stream(sample)
        self.assertEqual(frame["research_decision"]["status"], "research_preference")
        report = self.evaluate(runtime, rules)
        self.assertEqual(report["reason"], "public_source_or_ability_identity_unverified")
        self.assertIs(report["predictive_source_identity_consistency_verified"], False)
        self.assert_no_authority(self, report)

    def test_synthetic_private_source_zone_is_not_public_payment_evidence(self):
        sample = copy.deepcopy(self.sample)
        mana = sample["message"]["actionsAvailableReq"]["actions"][8]
        source = next(o for o in sample["initial"]["objects"]
                      if o["instanceId"] == mana["instanceId"])
        zone = next(z for z in sample["initial"]["zones"]
                    if z["zoneId"] == source["zoneId"])
        zone["visibility"] = "Visibility_Private"
        runtime, _, _, rules, _, _, frame = self.stream(sample)
        self.assertEqual(frame["research_decision"]["status"], "research_preference")
        report = self.evaluate(runtime, rules)
        self.assertEqual(report["reason"], "public_source_or_ability_identity_unverified")
        self.assertIs(report["predictive_source_identity_consistency_verified"], False)
        self.assert_no_authority(self, report)


class Historical1UPaymentTests(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads((FIXTURES / "cast_1u_payment_real.json").read_text())
        self.document = copy.deepcopy(self.fixture["document"])

    def result(self):
        return reconcile_observed_cast_1u_sources(self.document)["samples"][0]

    def test_real_selected_cast_sources_match_mana_paid_links_not_full_payment(self):
        from mtgaplayer.semantic_samples import replay_samples
        self.assertEqual(self.fixture["origin"], "retained_scrubbed_real")
        self.assertIs(self.fixture["raw_equivalent"], False)
        self.assertEqual(self.fixture["source_opportunity"], 20)
        sample = self.document["samples"][0]
        self.assertEqual(len(sample["request"]["payload"]["actions"]), 11)
        self.assertEqual(len(sample["trace"]["states"]), 38)
        self.assertEqual(replay_samples(self.document)["samples"][0]["cast_evidence"]
                         ["known_cost_and_predictive_payment"], "insufficient_evidence")
        report = self.result()
        self.assertEqual(report["status"], "historical_source_links_consistent")
        self.assertEqual(report["observed_mana_paid_source_links"], 2)
        self.assertEqual(report["observed_sources_tapped"], 2)
        self.assertIs(report["actual_mana_paid_observed"], True)
        self.assertEqual(report["time_scope"], "historical_only")
        self.assertIsNone(report["request_binding"])
        for k in ("current_available", "raw_source_auth_revalidated", "actual_color_count_verified",
                  "payment_verified", "complete_payment_verified", "source_readiness_verified",
                  "complete_legality_verified", "strategic_optimality_verified", *EXECUTION):
            self.assertIs(report[k], False, k)

    def test_synthetic_wrong_missing_duplicate_or_extra_actual_links_refuse(self):
        original = copy.deepcopy(self.document)
        for label in ("wrong_source", "wrong_spell", "missing", "duplicate", "extra"):
            with self.subTest(control=label):
                self.document = copy.deepcopy(original)
                sample = self.document["samples"][0]
                facts = sample["trace"]["states"][0]["facts"]
                links = [f for f in facts if f["kind"] == "mana_paid"]
                if label == "wrong_source":
                    links[0]["source_object_ref"] = sample["response"]["payload"]["action"]["identifier_refs"]["instanceId"]
                elif label == "wrong_spell":
                    links[0]["spell_object_ref"] = links[0]["source_object_ref"]
                elif label == "missing": facts.remove(links[0])
                elif label == "duplicate": links[1].update(links[0])
                else: facts.append(copy.deepcopy(links[0]))
                report = self.result()
                self.assertIs(report["historical_source_links_consistent"], False)
                self.assertIs(report["actual_mana_paid_observed"], False)

    def test_synthetic_selection_identity_continuity_and_termination_refuse(self):
        original = copy.deepcopy(self.document)
        for label in ("response_parameters", "source_identity", "seat", "interrupted", "predictive_color"):
            with self.subTest(control=label):
                self.document = copy.deepcopy(original)
                sample = self.document["samples"][0]
                chosen = sample["response"]["payload"]["action"]
                if label == "response_parameters":
                    chosen["flags"]["shouldStop"] = not chosen["flags"]["shouldStop"]
                elif label == "source_identity":
                    sid = chosen["parameters"]["autoTapSolution"]["autoTapActions"][0]["instanceId"]
                    obj = next(o for o in sample["trace"]["states"][1]["snapshot"]["objects"] if o["object_ref"] == sid)
                    obj["card_id"] += 1
                elif label == "seat": sample["identity"]["self_seat"] = 3 - sample["identity"]["self_seat"]
                elif label == "interrupted":
                    sample["trace"].update(status="interrupted", next_request_ref=None)
                else:
                    offered = sample["request"]["payload"]["actions"][0]
                    for row in (chosen, offered):
                        row["parameters"]["autoTapSolution"]["autoTapActions"][0]["manaPaymentOption"]["mana"][0]["color"] = "ManaColor_Red"
                self.assertIs(self.result()["historical_source_links_consistent"], False)

    def test_synthetic_conflicting_cast_migration_identity_refuses(self):
        original = copy.deepcopy(self.document)
        for label in ("two_sources_one_spell", "old_source_still_visible", "spell_preexists", "payment_source_replaced"):
            with self.subTest(control=label):
                self.document = copy.deepcopy(original)
                sample = self.document["samples"][0]
                first = sample["trace"]["states"][0]
                change = next(f for f in first["facts"] if f["kind"] == "object_id_changed")
                if label == "two_sources_one_spell":
                    sid = next(f["source_object_ref"] for f in first["facts"] if f["kind"] == "mana_paid")
                    first["facts"].append({**change, "original_object_ref":sid})
                elif label == "payment_source_replaced":
                    unchosen = next(o["object_ref"] for o in sample["before"]["objects"]
                        if o["zone"] == "ZoneType_Hand" and o["object_ref"] != change["original_object_ref"])
                    sid = next(f["source_object_ref"] for f in first["facts"] if f["kind"] == "mana_paid")
                    first["facts"].append({"kind":"object_id_changed", "original_object_ref":unchosen, "new_object_ref":sid})
                elif label == "old_source_still_visible":
                    first["snapshot"]["objects"].append(copy.deepcopy(next(o for o in sample["before"]["objects"]
                        if o["object_ref"] == change["original_object_ref"])))
                else:
                    sample["before"]["objects"].append(copy.deepcopy(next(o for o in first["snapshot"]["objects"]
                        if o["object_ref"] == change["new_object_ref"])))
                sample["successor"]["snapshot"] = copy.deepcopy(first["snapshot"])
                self.assertIs(self.result()["historical_source_links_consistent"], False)


if __name__ == "__main__":
    unittest.main()
