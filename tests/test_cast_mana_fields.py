"""MP99 real aliased field evidence; all mutations below are synthetic negatives."""
import copy
import hashlib
import json
from pathlib import Path
import unittest

from mtgaplayer.cast_1u_predictive import (
    verify_observed_cast_1u_mana_fields, reconcile_observed_cast_1u_sources)
from mtgaplayer.decision_consumer import EXECUTION

FIXTURES = Path(__file__).parent / "fixtures"


class CastManaFieldsTests(unittest.TestCase):
    def setUp(self):
        self.document = json.loads((FIXTURES / "cast_1u_payment_real.json").read_text())["document"]
        self.fixture = json.loads((FIXTURES / "cast_1u_mana_fields_real.json").read_text())
        self.evidence = copy.deepcopy(self.fixture["evidence"])

    def check(self):
        return verify_observed_cast_1u_mana_fields(self.document, self.evidence)

    def assert_no_authority(self, report):
        for k in ("raw_source_auth_revalidated", "source_build_reauthenticated", "current_available",
                  "actual_paid_color_verified", "payment_verified", "complete_payment_verified",
                  "source_readiness_verified", "complete_legality_verified",
                  "strategic_optimality_verified", "response_encoding_verified",
                  "server_acceptance_verified", *EXECUTION):
            self.assertIs(report[k], False, k)
        self.assertIsNone(report["actual_mana_units"])
        self.assertIsNone(report["request_binding"])
        self.assertIsNone(report["source_snapshot_ref"])
        self.assertEqual(report["time_scope"], "historical_only")

    def test_real_two_blue_detail_encodings_are_not_actual_two_units(self):
        self.assertEqual(self.fixture["origin"], "retained_scrubbed_real")
        self.assertFalse(self.fixture["raw_equivalent"])
        self.assertEqual(self.fixture["source_opportunity"], 20)
        result = self.check()
        self.assertEqual(result["status"], "verified_scope")
        self.assertIs(result["annotation_color_encoding_verified"], True)
        self.assertEqual(result["observed"], {"annotation_rows": 2,
            "distinct_actual_mana_refs": 2, "Blue_encoded_color_rows": 2})
        self.assertIn("client_pool_lookup_branch", result["unknown"])
        self.assertIn("effective_client_event_color", result["unknown"])
        self.assert_no_authority(result)

    def test_version_proof_each_component_and_extra_claims_fail_closed(self):
        for key in self.evidence["version_evidence"]:
            with self.subTest(component=key):
                original = self.evidence["version_evidence"][key]
                self.evidence["version_evidence"][key] = "unreviewed"
                result = self.check()
                self.assertEqual(result["reason"], "payment_field_build_not_reviewed")
                self.assertEqual(result["verified_scope"], [])
                self.assert_no_authority(result)
                self.evidence["version_evidence"][key] = original
        self.evidence["version_evidence"]["complete_payment_verified"] = True
        self.assertEqual(self.check()["status"], "unknown")

    def test_wrong_document_identity_state_source_spell_and_typed_fact(self):
        mutations = {
            "other_document_digest": lambda e: e.update(document_sha256="0" * 64),
            "different_seat": lambda e: e["identity"].update(self_seat=1),
            "different_request": lambda e: e["identity"].update(request_ref=999),
            "other_state": lambda e: e["events"][0].update(state_ref=999),
            "bool_state": lambda e: e["events"][0].update(state_ref=True),
            "other_source": lambda e: e["events"][0].update(source_object_ref=999),
            "other_spell": lambda e: e["events"][0].update(spell_object_ref=999),
            "other_fact": lambda e: e["events"][0].update(fact_index=0),
            "bool_fact": lambda e: e["events"][0].update(fact_index=True),
            "namespace": lambda e: e.update(mana_id_namespace="request_predictive_ids"),
        }
        for label, mutate in mutations.items():
            with self.subTest(synthetic=label):
                self.evidence = copy.deepcopy(self.fixture["evidence"])
                mutate(self.evidence)
                result = self.check()
                self.assertEqual(result["status"], "unknown")
                self.assertIs(result["annotation_color_encoding_verified"], False)
                self.assert_no_authority(result)

    def test_duplicate_ids_rows_keys_and_invented_amount_do_not_verify(self):
        def row(e): return e["events"][0]
        def detail(e, key): return next(d for d in row(e)["details"] if d["key"] == key)
        mutations = {
            "duplicate_actual_mana": lambda e: next(d for d in e["events"][1]["details"]
                if d["key"] == "id").update(valueInt32=detail(e, "id")["valueInt32"]),
            "duplicate_annotation": lambda e: e["events"][1].update(annotation_ref=row(e)["annotation_ref"]),
            "duplicate_fact": lambda e: e["events"][1].update(fact_index=row(e)["fact_index"]),
            "duplicate_key": lambda e: row(e)["details"].append(copy.deepcopy(detail(e, "color"))),
            "multiple_values": lambda e: detail(e, "color").update(valueInt32=[2, 2]),
            "bool_id": lambda e: detail(e, "id").update(valueInt32=[True]),
            "bool_color": lambda e: detail(e, "color").update(valueInt32=[True]),
            "string_color": lambda e: detail(e, "color").update(valueInt32=["2"]),
            "string_type": lambda e: detail(e, "color").update(type="KeyValuePairValueType_string"),
            "missing_row": lambda e: e["events"].pop(),
            "extra_row": lambda e: e["events"].append(copy.deepcopy(row(e))),
            "invented_amount": lambda e: row(e).update(count=2),
        }
        for label, mutate in mutations.items():
            with self.subTest(synthetic=label):
                self.evidence = copy.deepcopy(self.fixture["evidence"])
                mutate(self.evidence)
                result = self.check()
                self.assertEqual(result["status"], "unknown")
                self.assertEqual(result["verified_scope"], [])
                self.assert_no_authority(result)

    def test_color_profile_contradiction_does_not_mean_payment_failed(self):
        color = next(d for d in self.evidence["events"][0]["details"] if d["key"] == "color")
        color["valueInt32"] = [5]  # exact-build Green; synthetic mismatch, not database Colors
        result = self.check()
        self.assertEqual(result["status"], "contradicted")
        self.assertEqual(result["contradicted_scope"], "reviewed_annotation_encoding_profile_only")
        self.assertEqual(result["observed"]["Blue_encoded_color_rows"], 1)
        self.assert_no_authority(result)
        color["valueInt32"] = [99]
        self.assertEqual(self.check()["reason"], "payment_color_encoding_not_reviewed")

    def test_field_check_preserves_inputs_legacy_result_and_canonical_key_order(self):
        original = copy.deepcopy((self.document, self.evidence))
        before = reconcile_observed_cast_1u_sources(self.document)
        result = self.check()
        self.assertEqual((self.document, self.evidence), original)
        self.assertEqual(reconcile_observed_cast_1u_sources(self.document), before)
        self.document = dict(reversed(list(self.document.items())))
        self.assertEqual(self.check(), result)
        self.document["samples"][0]["identity"]["self_seat"] = 1
        self.assertEqual(self.check()["reason"], "payment_document_digest_mismatch")


if __name__ == "__main__":
    unittest.main()
