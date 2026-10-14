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
        self.assertEqual(report["matched_current_own_responses"], 1)
        self.assertEqual(report["unmatched_or_noncurrent_responses"], 0)
        self.assertEqual(report["observed_historical_client_response_records"], 1)
        self.assertEqual(report["matched_response_types"], [
            {"request_kind": "actions_available",
             "response_type_class": "perform_action_resp", "count": 1}])
        variant = report["envelope_variants"][0]
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
        self.assertEqual(report["observed_historical_client_response_records"], 4)
        self.assertEqual(report["matched_current_own_responses"], 1)
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
                self.assertEqual(report["matched_current_own_responses"], 0)
                self.assertEqual(report["unmatched_or_noncurrent_responses"], 1)

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
