"""MP15: exact-own-response correlation without decoding selected actions."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from mtgaplayer.response_evidence import inspect_response_envelopes


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/player_log_selectn.jsonl"
SCRIPT = ROOT / "scripts/inspect_actions.py"


def source_rows():
    return [json.loads(line) for line in FIXTURE.read_text(encoding="utf-8").splitlines()]


def action_request(actions=None, recipient=None, msg_id=37):
    frame = copy.deepcopy(source_rows()[9])
    req = next(msg for msg in frame["greToClientEvent"]["greToClientMessages"]
               if msg.get("type") == "GREMessageType_ActionsAvailableReq")
    req["msgId"] = msg_id
    if actions is not None:
        req["actionsAvailableReq"] = {"actions": actions}
    if recipient is not None:
        req["systemSeatIds"] = recipient
    return frame


def reply(request_id=37, state_id=23, details=None):
    data = {"type": "ClientMessageType_PerformActionResp",
            "respId": request_id, "gameStateId": state_id}
    if details is not None:
        data["performActionResp"] = details
    return {"payload": data}


def save(path, rows):
    path.write_text("".join(json.dumps(x) + "\n" for x in rows), encoding="utf-8")


class ResponseEvidenceTests(unittest.TestCase):
    def test_real_source_prefix_has_matching_perform_action_response_envelope(self):
        # Use actual sanitized source GRE + original client response fixture,
        # not an invented action response schema.
        original = source_rows()
        self.assertEqual(original[11]["payload"]["type"],
                         "ClientMessageType_PerformActionResp")
        self.assertEqual(set(original[11]["payload"]),
                         {"type", "respId", "gameStateId"})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Player.log"
            save(path, original[:12])
            report = inspect_response_envelopes(path)
        self.assertTrue(report["source"]["complete"])
        self.assertGreaterEqual(report["matched_current_own_responses"], 1)
        self.assertEqual(report["matched_actions_available_responses"], 1)
        self.assertIn({"request_kind": "actions_available",
                       "response_type_class": "perform_action_resp", "count": 1},
                      report["matched_response_types"])
        self.assertFalse(report["response_encoding_verified"])
        self.assertFalse(report["selected_action_type_verified"])
        self.assertFalse(report["pass_vs_play_selection_verified"])
        self.assertFalse(report["gameplay_effect_verified"])
        self.assertIsNone(report["legal_actions"])
        self.assertFalse(report["actionable"])
        self.assertFalse(report["input_sent"])

    def test_pass_play_are_only_offered_not_selected_and_private_values_omitted(self):
        actions = [
            {"actionType": "ActionType_Pass"},
            {"actionType": "ActionType_Play", "instanceId": 166,
             "grpId": 96839, "facetId": 0, "shouldStop": False},
        ]
        nested = {
            "actionType": "PRIVATE_SELECTED_ACTION_SENTINEL",
            "instanceId": 12345678,
            "otherUnknownField": "PRIVATE_NESTED_SENTINEL",
            "targets": [{"cardId": "PRIVATE_TARGET_SENTINEL"}],
        }
        response = reply(details=nested)
        response["payload"]["privateTopField"] = "PRIVATE_TOP_SENTINEL"
        frames = source_rows()[:9] + [action_request(actions)] + [
            {"payload": {"type": "ClientMessageType_UIMessage"}},
            response,
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Player.log"
            save(path, frames)
            report = inspect_response_envelopes(path)
        # The real GRE prefix ALSO has an authenticated Mulligan response.
        # Retain it as history; count the new action response separately.
        self.assertEqual(report["matched_current_own_responses"], 2)
        self.assertEqual(report["matched_actions_available_responses"], 1)
        self.assertEqual(report["unmatched_or_noncurrent_responses"], 0)
        self.assertEqual(report["observed_historical_client_response_records"], 2)
        self.assertIn(
            {"request_kind": "actions_available",
             "response_type_class": "perform_action_resp", "count": 1},
            report["matched_response_types"])
        variant = next(v for v in report["envelope_variants"]
                       if v["request_kind"] == "actions_available")
        self.assertEqual(variant["offered_action_context_not_choice"],
                         "pass_and_play_offered")
        self.assertEqual(variant["response_type_class"], "perform_action_resp")
        self.assertEqual(variant["other_root_field_count_examined"], 1)
        self.assertIn({"field": "respId", "kind": "integer"},
                      variant["root_field_kinds"])
        self.assertIn({"field": "performActionResp", "kind": "object"},
                      variant["root_field_kinds"])
        self.assertEqual(variant["nested_known_field_kinds"][0]
                         ["other_nested_field_count_examined"], 1)
        self.assertIn({"bucket": "one", "count": 1},
                      report["ui_message_counts_between_own_request_and_response"])
        self.assertFalse(report["pass_vs_play_selection_verified"])
        self.assertFalse(report["response_encoding_verified"])
        output = json.dumps(report)
        for sensitive in (
                "PRIVATE_SELECTED_ACTION_SENTINEL", "PRIVATE_NESTED_SENTINEL",
                "PRIVATE_TOP_SENTINEL", "PRIVATE_TARGET_SENTINEL",
                "12345678", "96839", str(path), "otherUnknownField",
                "privateTopField"):
            self.assertNotIn(sensitive, output)

    def test_superseded_and_mismatched_reply_never_matches_current_request(self):
        newer = action_request(msg_id=38)
        new_prompt = next(
            message for message in newer["greToClientEvent"]["greToClientMessages"]
            if message.get("type") == "GREMessageType_ActionsAvailableReq")
        frames = source_rows()[:9] + [
            action_request(msg_id=37),
            {"greToClientEvent": {"greToClientMessages": [new_prompt]}},
            reply(37, 23),
            reply(38, 24),   # wrong gameStateId, not current reply
            reply(38, 23),   # exact new current request
            reply(38, 23),   # duplicate after consumption
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Player.log"
            save(path, frames)
            report = inspect_response_envelopes(path)
        self.assertEqual(report["observed_historical_client_response_records"], 5)
        self.assertEqual(report["matched_current_own_responses"], 2)
        self.assertEqual(report["matched_actions_available_responses"], 1)
        self.assertEqual(report["unmatched_or_noncurrent_responses"], 3)
        self.assertEqual(report["malformed_response_envelopes"], 0)
        self.assertFalse(report["response_encoding_verified"])

    def test_opponent_or_broadcast_request_never_yields_matched_own_reply(self):
        for recipient in ([2], [1, 2]):
            with self.subTest(recipient=recipient):
                frames = source_rows()[:9] + [
                    action_request(recipient=recipient), reply()]
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / "Player.log"
                    save(path, frames)
                    report = inspect_response_envelopes(path)
                self.assertEqual(report["matched_current_own_responses"], 1)
                self.assertEqual(report["matched_actions_available_responses"], 0)
                self.assertEqual(report["unmatched_or_noncurrent_responses"], 1)

    def test_wrong_or_unknown_response_type_cannot_match_or_reopen_request(self):
        cases = (
            ("GREMessageType_ActionsAvailableReq", "ClientMessageType_SelectNResp"),
            ("GREMessageType_SelectNReq", "ClientMessageType_PerformActionResp"),
            ("GREMessageType_ActionsAvailableReq", "ClientMessageType_UnknownResp"),
            ("GREMessageType_UnknownReq", "ClientMessageType_UnknownResp"),
        )
        for request_type, response_type in cases:
            with self.subTest(request_type=request_type, response_type=response_type):
                frame = action_request([{"actionType": "ActionType_Pass"}])
                request = next(
                    message for message in frame["greToClientEvent"]["greToClientMessages"]
                    if message.get("type") == "GREMessageType_ActionsAvailableReq")
                request["type"] = request_type
                wrong = reply(details={"actions": [{"actionType": "PRIVATE_WRONG_TYPE"}]})
                wrong["payload"]["type"] = response_type
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / "Player.log"
                    save(path, source_rows()[:9] + [frame, wrong, reply()])
                    report = inspect_response_envelopes(path, action_shapes=True)
                # RawReducer records a client submission by ID/state alone. The
                # evidence layer must reject the wrong type; consumption then
                # prevents a later reply from reviving this request.
                self.assertEqual(report["matched_current_own_responses"], 1)
                self.assertEqual(report["matched_actions_available_responses"], 0)
                self.assertEqual(report["unmatched_or_noncurrent_responses"], 2)
                self.assertEqual(report["action_array_structure"]
                                 ["matched_action_responses_examined"], 0)
                self.assertNotIn("PRIVATE_WRONG_TYPE", json.dumps(report))

    def test_known_request_response_pairs_and_real_mulligan_selectn_survive(self):
        pairs = (
            ("GREMessageType_ActionsAvailableReq",
             "ClientMessageType_PerformActionResp"),
            ("GREMessageType_SelectNReq", "ClientMessageType_SelectNResp"),
            ("GREMessageType_MulliganReq", "ClientMessageType_MulliganResp"),
            ("GREMessageType_GroupReq", "ClientMessageType_GroupResp"),
            ("GREMessageType_SelectTargetsReq",
             "ClientMessageType_SelectTargetsResp"),
            ("GREMessageType_DeclareBlockersReq",
             "ClientMessageType_DeclareBlockersResp"),
        )
        for request_type, response_type in pairs:
            with self.subTest(request_type=request_type):
                frame = action_request([{"actionType": "ActionType_Pass"}])
                request = next(
                    message for message in frame["greToClientEvent"]["greToClientMessages"]
                    if message.get("type") == "GREMessageType_ActionsAvailableReq")
                request["type"] = request_type
                response = reply()
                response["payload"]["type"] = response_type
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / "Player.log"
                    save(path, source_rows()[:9] + [frame, response])
                    report = inspect_response_envelopes(path)
                self.assertEqual(report["matched_current_own_responses"], 2)
                self.assertEqual(report["unmatched_or_noncurrent_responses"], 0)
                self.assertEqual(report["matched_actions_available_responses"],
                                 int(request_type == "GREMessageType_ActionsAvailableReq"))

        original = source_rows()
        selectn_response = json.loads(
            (FIXTURE.parent / "player_log_selectn_response.jsonl").read_text(
                encoding="utf-8"))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Player.log"
            save(path, original + [selectn_response])
            report = inspect_response_envelopes(path)
        self.assertIn(
            {"request_kind": "other_own_request",
             "response_type_class": "mulligan_resp", "count": 1},
            report["matched_response_types"])
        self.assertIn(
            {"request_kind": "select_n",
             "response_type_class": "select_n_resp", "count": 1},
            report["matched_response_types"])

    def test_action_array_items_are_type_only_and_old_probe_unchanged(self):
        offered = [
            {"actionType": "ActionType_Pass"},
            {"actionType": "ActionType_Play", "instanceId": 166,
             "grpId": 96839, "facetId": 0, "shouldStop": False},
        ]
        nested = {
            "actions": [
                {"actionType": "SECRET_SELECTED_ACTION_VALUE",
                 "instanceId": 12345678,
                 "action": {"actionType": "SECRET_NESTED_ACTION_VALUE",
                            "grpId": 98765432, "secretChild": "HIDDEN_INNER"},
                 "privateSelectedValue": "HIDDEN_ACTION_FIELD"},
                {"targets": [{"secret": "HIDDEN_TARGET_VALUE"}],
                 "privateFieldTwo": {"secret": "HIDDEN_DATA"}},
            ],
            "privateSiblingKey": {"user": "HIDDEN_SIBLING_CONTENT"},
        }
        rows = source_rows()[:9] + [action_request(offered)] + [
            reply(details=nested),
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Player.log"
            save(path, rows)
            old = inspect_response_envelopes(path)
            detailed = inspect_response_envelopes(path, action_shapes=True)
            cli = subprocess.run(
                [sys.executable, str(SCRIPT), str(path),
                 "--response-action-shapes"],
                cwd=ROOT, text=True, capture_output=True, check=False)
        self.assertNotIn("action_array_structure", old)
        self.assertEqual(old["probe"], "mtga-client-response-envelopes-v1")
        self.assertEqual(cli.returncode, 0, cli.stderr)
        self.assertEqual(detailed, json.loads(cli.stdout))
        self.assertEqual(detailed["probe"], "mtga-client-response-action-shapes-v1")
        sample = detailed["action_array_structure"]
        self.assertEqual(sample["matched_action_responses_examined"], 1)
        self.assertEqual(sample["container_status_counts"], [
            {"status": "actions_array", "response_count": 1}])
        self.assertEqual(sample["array_length_buckets_by_offered_context"], [
            {"offered_context_not_selected_action": "pass_and_play_offered",
             "length_bucket": "two", "response_count": 1}])
        self.assertEqual(sample["suppressed_sibling_field_storage_types"], [
            {"kind": "object", "field_occurrences": 1}])
        self.assertEqual(sample["array_item_storage_kinds"], [
            {"kind": "object", "item_count": 2}])
        self.assertEqual(sample["array_items_examined"], 2)
        self.assertEqual(sample["array_items_unexamined_due_to_cap"], 0)
        variants = sample["array_element_shape_variants"]
        self.assertEqual(sum(v["count"] for v in variants), 2)
        known = [entry for v in variants for entry in v["known_field_kinds"]]
        self.assertIn({"field": "actionType", "kind": "text"}, known)
        self.assertIn({"field": "instanceId", "kind": "integer"}, known)
        self.assertIn({"field": "targets", "kind": "array"}, known)
        nested_fields = [f for v in variants
                         for n in v["nested_known_object_fields"]
                         for f in n["known_field_kinds"]]
        self.assertIn({"field": "grpId", "kind": "integer"}, nested_fields)
        self.assertFalse(sample["selected_action_type_verified"])
        self.assertFalse(sample["pass_vs_play_selection_verified"])
        self.assertFalse(sample["complete_response_encoding_verified"])
        self.assertIsNone(sample["legal_actions"])
        self.assertFalse(sample["input_sent"])
        output = json.dumps(detailed)
        for private in ("SECRET_SELECTED_ACTION_VALUE",
                        "SECRET_NESTED_ACTION_VALUE",
                        "HIDDEN_INNER", "HIDDEN_ACTION_FIELD",
                        "HIDDEN_TARGET_VALUE", "HIDDEN_DATA",
                        "HIDDEN_SIBLING_CONTENT", "privateSiblingKey",
                        "privateSelectedValue", "privateFieldTwo",
                        "secretChild", "12345678", "98765432", str(path)):
            self.assertNotIn(private, output)

    def test_action_item_limit_and_wrong_container_are_marked_unknown(self):
        offered = [{"actionType": "ActionType_Pass"}]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Player.log"
            save(path, source_rows()[:9] + [action_request(offered)] + [
                reply(details={"actions": [
                    {"actionType": "SECRET_PASS_OR_PLAY"}
                    for _ in range(67)]})])
            large = inspect_response_envelopes(path, action_shapes=True)
            save(path, source_rows()[:9] + [action_request(offered)] + [
                reply(details={"actions": "DO_NOT_EXPORT_NON_ARRAY"})])
            wrong = inspect_response_envelopes(path, action_shapes=True)
        first = large["action_array_structure"]
        self.assertEqual(first["array_items_examined"], 64)
        self.assertEqual(first["array_items_unexamined_due_to_cap"], 3)
        self.assertEqual(first["array_length_buckets_by_offered_context"][0]
                         ["length_bucket"], "over_64_truncated")
        self.assertEqual(first["array_element_shape_variants"][0]["count"], 64)
        second = wrong["action_array_structure"]
        self.assertEqual(second["matched_action_responses_examined"], 1)
        self.assertEqual(second["container_status_counts"], [
            {"status": "unexpected_actions_container", "response_count": 1}])
        self.assertEqual(second["array_items_examined"], 0)
        self.assertNotIn("DO_NOT_EXPORT_NON_ARRAY", json.dumps(wrong))
        self.assertNotIn("SECRET_PASS_OR_PLAY", json.dumps(large))

    def test_only_exact_current_own_action_replies_are_drilled_down(self):
        offered = [{"actionType": "ActionType_Pass"}]
        unmatched = reply(9999, 23, {"actions": [
            {"privateField": "SECRET_UNMATCHED_VALUE"}]})
        matched = reply(37, 23, {"actions": [
            {"actionType": "PRIVATE_SELECTED_VALUE"}]})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Player.log"
            save(path, source_rows()[:9] + [action_request(offered),
                                            unmatched, matched])
            result = inspect_response_envelopes(path, action_shapes=True)
        self.assertEqual(result["matched_actions_available_responses"], 1)
        self.assertEqual(result["unmatched_or_noncurrent_responses"], 1)
        self.assertEqual(result["action_array_structure"]
                         ["matched_action_responses_examined"], 1)
        self.assertEqual(result["action_array_structure"]
                         ["array_items_examined"], 1)
        self.assertNotIn("SECRET_UNMATCHED_VALUE", json.dumps(result))
        self.assertNotIn("PRIVATE_SELECTED_VALUE", json.dumps(result))
        self.assertFalse(result["response_encoding_verified"])

    def test_count_only_cli_and_partial_tail_never_claim_verified_encoding(self):
        original = source_rows()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Player.log"
            save(path, original[:12])
            with path.open("ab") as stream:
                stream.write(b'{"payload":{"type":"ClientMessageType_PerformAct')
            expected = inspect_response_envelopes(path)
            result = subprocess.run(
                [sys.executable, str(SCRIPT), str(path), "--response-envelopes"],
                cwd=ROOT, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), expected)
        self.assertFalse(expected["source"]["complete"])
        self.assertTrue(expected["source"]["partial_record"])
        self.assertFalse(expected["response_encoding_verified"])
        self.assertFalse(expected["actionable"])
        self.assertNotIn(str(path), result.stdout)
        self.assertNotIn('"respId": 37', result.stdout)


if __name__ == "__main__":
    unittest.main()
