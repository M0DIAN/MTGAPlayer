"""MP15 offline-only observed client response envelopes linked to own GRE requests.

Output is bounded counts and whitelisted *field kinds* only. Never outputs
response scalar values, request IDs, card IDs, raw payloads or filenames.
No message encoding or native MTGA input is implemented by this module.
"""
from collections import Counter
from pathlib import Path
import json
import re

from .raw_log import RawFollower, RawReducer, _request_digest
from .semantic_evidence import SemanticChoiceCounter, ComplexSemanticChoiceCounter
from .choice_graph import (CHOICE_VALIDATION_LEVELS, _selectn_known_constraints,
                           _build_selectn_constraint_graph)


_RESP = re.compile(r"ClientMessageType_[A-Za-z_]{1,64}Resp\Z")
_RESPONSE_KINDS = {
    "ClientMessageType_PerformActionResp": "perform_action_resp",
    "ClientMessageType_SelectNResp": "select_n_resp",
    "ClientMessageType_MulliganResp": "mulligan_resp",
    "ClientMessageType_GroupResp": "group_resp",
    "ClientMessageType_SelectTargetsResp": "select_targets_resp",
    "ClientMessageType_DeclareBlockersResp": "declare_blockers_resp",
}
# Only these observed GRE request/client response type pairs may be counted
# as matched evidence. RawReducer still owns request consumption by ID/state.
_RESPONSE_BY_REQUEST = {
    "GREMessageType_ActionsAvailableReq": "ClientMessageType_PerformActionResp",
    "GREMessageType_SelectNReq": "ClientMessageType_SelectNResp",
    "GREMessageType_MulliganReq": "ClientMessageType_MulliganResp",
    "GREMessageType_GroupReq": "ClientMessageType_GroupResp",
    "GREMessageType_SelectTargetsReq": "ClientMessageType_SelectTargetsResp",
    "GREMessageType_DeclareBlockersReq": "ClientMessageType_DeclareBlockersResp",
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


def _current_verified_raw_request(reducer, message):
    """Bind accepted-event content to the single reducer's current digest ledger.

    Adapted from the local Phase 5B helper; strict recipient types are required.
    Neither matching headers nor an old accepted message establish this binding.
    """
    req = _current_verified_request(reducer)
    recipients = message.get('systemSeatIds') if isinstance(message, dict) else None
    if (req is None or reducer.conflict or not isinstance(message, dict) or
            not _id(message.get('msgId')) or not _id(message.get('gameStateId')) or
            not isinstance(recipients, list) or len(recipients) != 1 or
            type(recipients[0]) is not int or recipients[0] != reducer.room_seat or
            message.get('msgId') != req['id'] or
            message.get('gameStateId') != req['game_state_id'] or
            message.get('type') != req['type'] or
            (reducer.match, reducer.game, req['id']) in reducer.consumed or
            req['id'] in reducer.superseded or
            reducer.request_ids.get(req['id']) !=
            (req['game_state_id'], req['type'], _request_digest(message))):
        return None
    return req


def _paired_response(reducer, before, payload, expected_type=None):
    """Existing MP15 post-consumption gate, client submission only.

    A bounded diagnostic can supply a fixed protocol pair without changing the
    default response map. Callers must authenticate request content separately.
    """
    if not isinstance(payload, dict) or before is None:
        return False
    typ = payload.get('type')
    expected = expected_type or _RESPONSE_BY_REQUEST.get(before.get('type'))
    return (isinstance(typ, str) and _RESP.fullmatch(typ) is not None and
            _id(payload.get('respId')) and _id(payload.get('gameStateId')) and
            typ == expected and payload['respId'] == before['id'] and
            payload['gameStateId'] == before['game_state_id'] and
            reducer.error is None and isinstance(reducer.submitted, dict) and
            reducer.submitted.get('request_id') == payload['respId'] and
            reducer.submitted.get('game_state_id') == payload['gameStateId'] and
            reducer.submitted.get('confirmation') == 'client_submission_only' and
            (reducer.match, reducer.game) ==
            (before['binding']['match'], before['binding']['game']) and
            (reducer.match, reducer.game, payload['respId']) in reducer.consumed)


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



# MP15 value-free drill-down, only when explicitly requested.
_ACTION_ITEMS_LIMIT = 64
_ACTION_FIELDS_LIMIT = 24
_ACTION_NESTED_FIELDS_LIMIT = 16
_ACTION_VARIANT_LIMIT = 48


def _array_length_bucket(size):
    """Fixed labels, not per-response cardinalities or selected action IDs."""
    if size == 0:
        return "zero"
    if size == 1:
        return "one"
    if size == 2:
        return "two"
    if size <= _ACTION_ITEMS_LIMIT:
        return "three_to_64"
    return "over_64_truncated"


def _known_fields_signature(item, limit):
    """Names are emitted ONLY from our static, previously reviewed allowlist."""
    found, hidden_kinds = [], Counter()
    for name in sorted(item, key=str)[:limit]:
        kind = _kind(item[name])
        if isinstance(name, str) and name in _FIELDS:
            found.append((name, kind))
        else:
            hidden_kinds[kind] += 1
    return tuple(found), tuple(sorted(hidden_kinds.items())), len(item) > limit


def _action_item_shape(item):
    """At most two levels of fixed field names; no scalar or array elements."""
    if not isinstance(item, dict):
        return (_kind(item), (), (), (), False)
    known, other_kinds, truncated = _known_fields_signature(
        item, _ACTION_FIELDS_LIMIT)
    nested = []
    for name, kind in known:
        value = item[name]
        if kind == "object":
            child_fields, child_others, cut = _known_fields_signature(
                value, _ACTION_NESTED_FIELDS_LIMIT)
            nested.append((name, child_fields, child_others))
            truncated |= cut
    return ("object", known, other_kinds, tuple(nested), truncated)


class _ActionShapeCounts:
    """Aggregate matched PerformActionResp.actions only, strictly no values."""

    def __init__(self):
        self.responses = 0
        self.container = Counter()
        self.lengths = Counter()
        self.sibling_kinds = Counter()
        self.item_kinds = Counter()
        self.variants = {}
        self.unshown_variants = 0
        self.items_examined = 0
        self.items_unexamined = 0
        self.fields_truncated = 0

    def add(self, payload, offered):
        self.responses += 1
        response = payload.get("performActionResp")
        if response is None:
            self.container["missing_or_null_perform_action_resp"] += 1
            return
        if not isinstance(response, dict):
            self.container["unexpected_perform_action_resp_container"] += 1
            return
        for field, value in response.items():
            if field != "actions":
                # Suppress arbitrary field names, types only.
                self.sibling_kinds[_kind(value)] += 1
        if "actions" not in response:
            self.container["missing_actions"] += 1
            return
        actions = response["actions"]
        if not isinstance(actions, list):
            self.container["unexpected_actions_container"] += 1
            return
        self.container["actions_array"] += 1
        self.lengths[(offered, _array_length_bucket(len(actions)))] += 1
        self.items_unexamined += max(0, len(actions) - _ACTION_ITEMS_LIMIT)
        for item in actions[:_ACTION_ITEMS_LIMIT]:
            self.items_examined += 1
            signature = _action_item_shape(item)
            self.item_kinds[signature[0]] += 1
            if signature[4]:
                self.fields_truncated += 1
            if signature in self.variants:
                self.variants[signature] += 1
            elif len(self.variants) < _ACTION_VARIANT_LIMIT:
                self.variants[signature] = 1
            else:
                self.unshown_variants += 1

    def report(self):
        variants = []
        for signature, count in sorted(
                self.variants.items(), key=lambda x: (-x[1], x[0])):
            kind, fields, other, nested, truncated = signature
            variants.append({
                "item_kind": kind,
                "known_field_kinds": [
                    {"field": key, "kind": value} for key, value in fields],
                "suppressed_unknown_field_kinds": [
                    {"kind": category, "count": total}
                    for category, total in other],
                "nested_known_object_fields": [
                    {"parent": parent,
                     "known_field_kinds": [
                         {"field": key, "kind": value}
                         for key, value in child_fields],
                     "suppressed_unknown_field_kinds": [
                         {"kind": category, "count": total}
                         for category, total in child_other]}
                    for parent, child_fields, child_other in nested],
                "fields_truncated": truncated,
                "count": count,
            })
        return {
            "scope": "matched_own_actions_available_perform_action_resp_only",
            "matched_action_responses_examined": self.responses,
            "container_status_counts": [
                {"status": kind, "response_count": total}
                for kind, total in sorted(self.container.items())],
            "array_length_buckets_by_offered_context": [
                {"offered_context_not_selected_action": offered,
                 "length_bucket": length_bucket, "response_count": total}
                for (offered, length_bucket), total in sorted(self.lengths.items())],
            "suppressed_sibling_field_storage_types": [
                {"kind": kind, "field_occurrences": count}
                for kind, count in sorted(self.sibling_kinds.items())],
            "array_item_storage_kinds": [
                {"kind": kind, "item_count": count}
                for kind, count in sorted(self.item_kinds.items())],
            "array_items_examined": self.items_examined,
            "array_items_unexamined_due_to_cap": self.items_unexamined,
            "items_with_truncated_fields": self.fields_truncated,
            "array_element_shape_variants": variants,
            "shape_variant_limit": _ACTION_VARIANT_LIMIT,
            "unshown_variant_item_occurrences": self.unshown_variants,
            "raw_values_or_unknown_field_names_exported": False,
            "selected_action_type_verified": False,
            "pass_vs_play_selection_verified": False,
            "complete_response_encoding_verified": False,
            "legal_actions": None,
            "read_only": True, "actionable": False, "input_sent": False,
        }


class _ChoiceConstraintCounts:
    """Every observed response stays in the denominator, including early rejects."""

    def __init__(self, complete, graphs=None):
        self.complete, self.graphs = complete, graphs
        self.all_counts, self.selectn_counts = Counter(), Counter()

    def add(self, request, payload, paired):
        selectn = payload['type'] == 'ClientMessageType_SelectNResp'
        if not selectn:
            validation = {'validation_level': 'unsupported_protocol'}
        elif not self.complete or not paired:
            validation = {'validation_level': 'insufficient_evidence'}
        else:
            validation = _selectn_known_constraints(request, payload)
            if self.graphs is not None:
                graph = _build_selectn_constraint_graph(request, validation)
                if graph is not None:
                    self.graphs.append(graph)
        level = validation['validation_level']
        self.all_counts[level] += 1
        if selectn:
            self.selectn_counts[level] += 1

    def report(self, source):
        def counts(counter):
            return {'total': sum(counter.values()),
                    'counts': {name: counter[name] for name in CHOICE_VALIDATION_LEVELS}}
        return {'probe': 'mtga-verified-choice-constraints-v1',
                'all_observed_client_responses': counts(self.all_counts),
                'select_n_responses': counts(self.selectn_counts),
                'source': source, 'raw_values_included': False,
                'paths_or_identifiers_included': False,
                'complete_legality_verified': False, 'legal_choice_verified': False,
                'response_encoding_verified': False, 'server_acceptance_verified': False,
                'execution_ready': False, 'input_sent': False, 'read_only': True}


def inspect_response_envelopes(path, max_history_bytes=64 * 1024 * 1024,
                               action_shapes=False, semantic_choices=False,
                               complex_semantic_choices=False,
                               choice_graph_history=False,
                               _history_collector=None,
                               verified_choice_constraints=False,
                               _constraint_graphs=None):
    """Count exact-current-own-request response-envelope matches, offline.

    The reducer must already have accepted a current authenticated request
    BEFORE each response. Old, superseded, broadcast, invalid or unmatched
    replies are never promoted to a matched request.
    """
    if sum(bool(mode) for mode in (action_shapes, semantic_choices,
                                  complex_semantic_choices, choice_graph_history,
                                  verified_choice_constraints)) > 1:
        raise ValueError('MP15 shape and MP16 semantic modes are mutually exclusive')
    follower = RawFollower(Path(path), max_history_bytes=max_history_bytes)
    _, records = follower.poll()
    source = {'mode': 'offline', 'format': 'player-log-gre-v1',
              'framed_records': len(records),
              'complete': follower.framer.errors == 0 and not follower.framer.partial,
              'framing_errors': follower.framer.errors,
              'partial_record': follower.framer.partial,
              'tool_input_sent': False, 'executor_connected': False}
    constraint_counts = (_ChoiceConstraintCounts(source['complete'], _constraint_graphs)
                         if verified_choice_constraints else None)
    reducer = RawReducer()
    reducer.reset(follower.generation)
    seen_requests = set()
    counts, by_kind, by_response, ui_bins = (
        Counter(), Counter(), Counter(), Counter())
    variants = {}
    unshown = 0
    action_shape_counts = _ActionShapeCounts() if action_shapes else None
    semantic_counter = SemanticChoiceCounter() if semantic_choices else None
    complex_counter = ComplexSemanticChoiceCounter() if (
        complex_semantic_choices or choice_graph_history) else None
    if choice_graph_history:
        from .choice_history import ChoiceHistoryCounter
        choice_history = (_history_collector if _history_collector is not None
                          else ChoiceHistoryCounter())
    else:
        choice_history = None
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
        if choice_history is not None:
            choice_history.observe_entry(entry, reducer)
        after = _current_verified_request(reducer)
        if after is not None:
            next_token = _identity(after)
            if next_token not in seen_requests:
                seen_requests.add(next_token)
                counts["accepted_unique_own_requests"] += 1
                by_kind[_request_kind(after)] += 1
                if choice_history is not None:
                    choice_history.observe_request(after)
        if not candidate:
            continue
        counts["observed_client_response_records"] += 1
        paired = _paired_response(reducer, before, payload)
        if constraint_counts is not None:
            constraint_counts.add(before, payload, paired)
        if not valid_response:
            counts["malformed_response_envelopes"] += 1
            continue
        if not paired:
            counts["unmatched_or_noncurrent_responses"] += 1
            continue
        counts["matched_current_own_responses"] += 1
        kind = _request_kind(before)
        if kind == "actions_available":
            counts["matched_actions_available_responses"] += 1
            if action_shape_counts is not None and typ == "ClientMessageType_PerformActionResp":
                action_shape_counts.add(payload, _offers(before))
            if semantic_counter is not None and typ == "ClientMessageType_PerformActionResp":
                # Only after the existing exact authenticated request/response gate.
                semantic_counter.add(before, payload)
            if complex_counter is not None and typ == "ClientMessageType_PerformActionResp":
                complex_counter.add(before, payload)
            if choice_history is not None and typ == "ClientMessageType_PerformActionResp":
                choice_history.matched_response(before, payload, reducer)
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

    if constraint_counts is not None:
        return constraint_counts.report(source)
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
    report = {
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
    if action_shape_counts is not None:
        report["probe"] = "mtga-client-response-action-shapes-v1"
        report["action_array_structure"] = action_shape_counts.report()
    if semantic_counter is not None:
        report["probe"] = "mtga-client-response-semantic-correlation-v1"
        report["action_choice_correlation"] = semantic_counter.report()
    if complex_counter is not None:
        report["probe"] = "mtga-client-response-complex-correlation-v1"
        report["complex_action_choice_correlation"] = complex_counter.report()
    if choice_history is not None:
        choice_history.finish(report['source']['complete'])
        report["probe"] = "mtga-choice-graph-history-v1"
        report["historical_choice_relations"] = choice_history.report()
    return report


def inspect_historical_choice_graphs(path, max_history_bytes=64 * 1024 * 1024):
    """Explicit offline local API for bound source graphs and temporal edges.

    Unlike the count-only CLI, this returns request/action identities from the
    caller's chosen log. It never returns raw response payloads or target IDs.
    """
    from .choice_history import ChoiceHistoryCounter
    collector = ChoiceHistoryCounter()
    report = inspect_response_envelopes(
        path, max_history_bytes=max_history_bytes, choice_graph_history=True,
        _history_collector=collector)
    return {'schema_version': 'mtga-historical-choice-graphs-v1',
            'source_complete': report['source']['complete'],
            'graphs': collector.graphs,
            'summary': report['historical_choice_relations'],
            'read_only': True, 'legal_choice_verified': False,
            'response_encoding_verified': False, 'execution_ready': False,
            'input_sent': False}


def inspect_verified_choice_constraints(path, max_history_bytes=64 * 1024 * 1024):
    """Explicit local opt-in for identity-bearing historical SelectN graphs.

    Never used by the count-only CLI or default replay/watch. Graphs refer to
    authenticated request snapshots at response time, not current candidates.
    """
    graphs = []
    summary = inspect_response_envelopes(
        path, max_history_bytes=max_history_bytes, verified_choice_constraints=True,
        _constraint_graphs=graphs)
    return {'schema_version': 'mtga-historical-selectn-constraints-v1',
            'source_complete': summary['source']['complete'],
            'graphs': graphs, 'summary': summary,
            'legal_choice_verified': False, 'complete_legality_verified': False,
            'response_encoding_verified': False, 'server_acceptance_verified': False,
            'execution_ready': False, 'input_sent': False, 'read_only': True}
