"""MP15 offline-only observed client response envelopes linked to own GRE requests.

Output is bounded counts and whitelisted *field kinds* only. Never outputs
response scalar values, request IDs, card IDs, raw payloads or filenames.
No message encoding or native MTGA input is implemented by this module.
"""
from collections import Counter
from pathlib import Path
import json
import re

from .raw_log import RawFollower, RawReducer


_RESP = re.compile(r"ClientMessageType_[A-Za-z_]{1,64}Resp\Z")
_RESPONSE_KINDS = {
    "ClientMessageType_PerformActionResp": "perform_action_resp",
    "ClientMessageType_SelectNResp": "select_n_resp",
    "ClientMessageType_MulliganResp": "mulligan_resp",
    "ClientMessageType_GroupResp": "group_resp",
    "ClientMessageType_SelectTargetsResp": "select_targets_resp",
    "ClientMessageType_DeclareBlockersResp": "declare_blockers_resp",
}
_FIELDS = frozenset({
    "type", "respId", "gameStateId", "performActionResp",
    "actionResp", "selectNResp", "mulliganResp", "groupResp",
    "selectTargetsResp", "declareBlockersResp", "actions",
    "action", "actionType", "instanceId", "grpId", "facetId",
    "shouldStop", "targets", "ids", "selectedIds", "selectedAction",
    "manaCost", "manaSelections", "manaPaymentOptions",
    "autoTapSolution", "payment", "selection", "result",
})
_MAX_FIELDS = 32
_MAX_NESTED = 24
_MAX_VARIANTS = 48


def _id(value):
    return type(value) is int and 0 <= value <= 2**53 - 1


def _kind(value):
    if value is None:
        return "null"
    if type(value) is bool:
        return "bool"
    if type(value) is int:
        return "integer"
    if type(value) is float:
        return "float"
    if isinstance(value, str):
        return "text"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    return "other"


def _shape(payload):
    """Only allowlisted field NAMES and scalar TYPE CLASSES, never values."""
    known, other, nested, truncated = [], 0, [], False
    if len(payload) > _MAX_FIELDS:
        truncated = True
    for key in sorted(payload, key=str)[:_MAX_FIELDS]:
        if key in _FIELDS:
            known.append((key, _kind(payload[key])))
        else:
            other += 1
        if key in _FIELDS and isinstance(payload[key], dict):
            child = payload[key]
            if len(child) > _MAX_NESTED:
                truncated = True
            child_known, child_other = [], 0
            for name in sorted(child, key=str)[:_MAX_NESTED]:
                if name in _FIELDS:
                    child_known.append((name, _kind(child[name])))
                else:
                    child_other += 1
            nested.append((key, tuple(child_known), child_other))
    return (tuple(known), other, tuple(nested), truncated)


def _current_verified_request(reducer):
    if reducer.error is not None:
        return None
    req = reducer.request
    if not isinstance(req, dict) or req.get("current") is not True:
        return None
    binding = req.get("binding")
    if (not isinstance(binding, dict) or
            binding.get("ownership_verified") is not True or
            not _id(req.get("id")) or not _id(req.get("game_state_id")) or
            req["game_state_id"] != reducer.version or
            not _id(binding.get("generation")) or
            binding["generation"] != reducer.generation or
            binding.get("match") != reducer.match or not reducer.match or
            binding.get("game") != reducer.game or
            binding.get("game_state_id") != req["game_state_id"] or
            binding.get("self_seat") != reducer.seat or
            reducer.room_seat != reducer.seat or
            reducer.seat not in (1, 2)):
        return None
    return req


def _identity(request):
    bind = request["binding"]
    return (bind["generation"], bind["match"], bind["game"],
            bind["self_seat"], request["game_state_id"], request["id"])


def _request_kind(request):
    if request["type"] == "GREMessageType_ActionsAvailableReq":
        return "actions_available"
    if request["type"] == "GREMessageType_SelectNReq":
        return "select_n"
    return "other_own_request"


def _offers(request):
    """This describes what was OFFERED, never the action the player chose."""
    if _request_kind(request) != "actions_available":
        return "not_actions_available"
    inv = request.get("action_inventory")
    if not isinstance(inv, dict) or not isinstance(inv.get("types"), list):
        return "unknown_offered_actions"
    found = {}
    for item in inv["types"]:
        if (not isinstance(item, dict) or
                type(item.get("action_type")) is not str or
                type(item.get("count")) is not int):
            return "unknown_offered_actions"
        found[item["action_type"]] = item["count"]
    if found.get("ActionType_Pass", 0) and found.get("ActionType_Play", 0):
        return "pass_and_play_offered"
    if found.get("ActionType_Pass", 0):
        return "pass_offered_play_absent"
    if found.get("ActionType_Play", 0):
        return "play_offered_pass_absent"
    return "pass_and_play_not_offered"


def _ui_bucket(total):
    if total == 0:
        return "none"
    if total == 1:
        return "one"
    return "two_or_more"


def inspect_response_envelopes(path, max_history_bytes=64 * 1024 * 1024):
    """Count exact-current-own-request response-envelope matches, offline.

    The reducer must already have accepted a current authenticated request
    BEFORE each response. Old, superseded, broadcast, invalid or unmatched
    replies are never promoted to a matched request.
    """
    follower = RawFollower(Path(path), max_history_bytes=max_history_bytes)
    _, records = follower.poll()
    reducer = RawReducer()
    reducer.reset(follower.generation)
    seen_requests = set()
    counts, by_kind, by_response, ui_bins = (
        Counter(), Counter(), Counter(), Counter())
    variants = {}
    unshown = 0
    ui_token, ui_count = None, 0
    for entry in records:
        before = _current_verified_request(reducer)
        token = _identity(before) if before is not None else None
        if token != ui_token:
            ui_token, ui_count = token, 0
        payload = entry.get("payload") if isinstance(entry, dict) else None
        typ = payload.get("type") if isinstance(payload, dict) else None
        candidate = (isinstance(typ, str) and
                     typ.startswith("ClientMessageType_") and
                     typ.endswith("Resp"))
        if before is not None and typ == "ClientMessageType_UIMessage":
            ui_count = min(ui_count + 1, 10000)
        valid_response = (
            candidate and _RESP.fullmatch(typ) is not None and
            _id(payload.get("respId")) and _id(payload.get("gameStateId")))
        reducer.apply(entry)
        after = _current_verified_request(reducer)
        if after is not None:
            next_token = _identity(after)
            if next_token not in seen_requests:
                seen_requests.add(next_token)
                counts["accepted_unique_own_requests"] += 1
                by_kind[_request_kind(after)] += 1
        if not candidate:
            continue
        counts["observed_client_response_records"] += 1
        if not valid_response:
            counts["malformed_response_envelopes"] += 1
            continue
        paired = (before is not None and
                  payload["respId"] == before["id"] and
                  payload["gameStateId"] == before["game_state_id"] and
                  reducer.error is None and
                  isinstance(reducer.submitted, dict) and
                  reducer.submitted.get("request_id") == payload["respId"] and
                  reducer.submitted.get("game_state_id") == payload["gameStateId"] and
                  reducer.submitted.get("confirmation") == "client_submission_only" and
                  (reducer.match, reducer.game) ==
                  (before["binding"]["match"], before["binding"]["game"]) and
                  (reducer.match, reducer.game, payload["respId"]) in reducer.consumed)
        if not paired:
            counts["unmatched_or_noncurrent_responses"] += 1
            continue
        counts["matched_current_own_responses"] += 1
        kind = _request_kind(before)
        if kind == "actions_available":
            counts["matched_actions_available_responses"] += 1
        response_kind = _RESPONSE_KINDS.get(typ, "other_client_response")
        by_response[(kind, response_kind)] += 1
        bucket = _ui_bucket(ui_count)
        ui_bins[bucket] += 1
        variant = (kind, _offers(before), response_kind, _shape(payload))
        if variant in variants:
            variants[variant] += 1
        elif len(variants) < _MAX_VARIANTS:
            variants[variant] = 1
        else:
            unshown += 1
        ui_token, ui_count = None, 0

    displayed = []
    for (request_kind, offered, response_kind, shape), count in sorted(
            variants.items(), key=lambda x: (-x[1], x[0])):
        fields, other, nested, truncated = shape
        displayed.append({
            "request_kind": request_kind,
            "offered_action_context_not_choice": offered,
            "response_type_class": response_kind,
            "root_field_kinds": [
                {"field": f, "kind": k} for f, k in fields],
            "other_root_field_count_examined": other,
            "nested_known_field_kinds": [
                {"parent": parent,
                 "fields": [{"field": f, "kind": k} for f, k in child_fields],
                 "other_nested_field_count_examined": other_nested}
                for parent, child_fields, other_nested in nested],
            "shape_truncated": truncated,
            "count": count,
        })
    return {
        "probe": "mtga-client-response-envelopes-v1",
        "source": {
            "mode": "offline", "format": "player-log-gre-v1",
            "framed_records": len(records),
            "complete": follower.framer.errors == 0 and not follower.framer.partial,
            "framing_errors": follower.framer.errors,
            "partial_record": follower.framer.partial,
            "tool_input_sent": False, "executor_connected": False,
        },
        "accepted_unique_own_requests": counts["accepted_unique_own_requests"],
        "accepted_request_kinds": [
            {"request_kind": name, "count": total}
            for name, total in sorted(by_kind.items())],
        "observed_historical_client_response_records":
            counts["observed_client_response_records"],
        "matched_current_own_responses": counts["matched_current_own_responses"],
        "matched_actions_available_responses":
            counts["matched_actions_available_responses"],
        "unmatched_or_noncurrent_responses":
            counts["unmatched_or_noncurrent_responses"],
        "malformed_response_envelopes":
            counts["malformed_response_envelopes"],
        "matched_response_types": [
            {"request_kind": req, "response_type_class": response,
             "count": total}
            for (req, response), total in sorted(by_response.items())],
        "ui_message_counts_between_own_request_and_response": [
            {"bucket": bucket, "count": ui_bins[bucket]}
            for bucket in ("none", "one", "two_or_more")],
        "envelope_variants": displayed,
        "envelope_variants_cap": _MAX_VARIANTS,
        "unshown_variant_occurrences": unshown,
        "historical_client_responses_not_tool_input": True,
        "selected_action_type_verified": False,
        "pass_vs_play_selection_verified": False,
        "response_encoding_verified": False,
        "request_id_equality_is_not_gameplay_legality": True,
        "gameplay_effect_verified": False, "legal_actions": None,
        "actionable": False, "input_sent": False,
        "executor_connected": False, "raw_values_included": False,
        "paths_or_identifiers_included": False,
    }
