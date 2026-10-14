"""MP7: read-only, bounded ActionsAvailableReq schema evidence.

No identifiers, scalar values, raw messages, screenshots or actions are emitted.
This is a diagnostic probe, NOT a legality oracle.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import re

from mtgaplayer.raw_log import RawFollower, RawReducer
from mtgaplayer.response_evidence import inspect_response_envelopes
from mtgaplayer.decision_input import build_decision_input
from mtgaplayer.action_gaps import assess_action_gaps


TARGET = "GREMessageType_ActionsAvailableReq"
_MAX_SHAPES = 24
_MAX_FIELDS = 48
_MAX_PATHS = 96
_MAX_LIST_EXAMPLES = 8
_MAX_DEPTH = 4
_KEY = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,47}\Z")
_ACTION = re.compile(r"ActionType_[A-Za-z_]{1,48}\Z")


def _safe_key(key):
    return key if isinstance(key, str) and _KEY.fullmatch(key) else "_other_field"



def _kind(item):
    if isinstance(item, dict):
        return "object"
    if isinstance(item, list):
        return "array"
    if item is None:
        return "null"
    if type(item) is bool:
        return "bool"
    if type(item) is int:
        return "int"
    if type(item) is float:
        return "float"
    if isinstance(item, str):
        return "string"
    return "other"


def _count_top_fields(item, counts):
    """Inventory immediate field *types* only, never their scalar values."""
    if len(item) > _MAX_FIELDS:
        shortened = True
    else:
        shortened = False
    for key in sorted(item, key=lambda x: str(x))[:_MAX_FIELDS]:
        counts[(_safe_key(key), _kind(item[key]))] += 1
    return shortened


def _top_fields(counts):
    return [{"field": key, "type": kind, "count": count}
            for (key, kind), count in sorted(counts.items(),
                                             key=lambda pair: (pair[0][0], pair[0][1]))[:_MAX_FIELDS]]


def _paths(value):
    """Bounded structural paths; no scalar values."""
    paths = set()
    truncated = False

    def visit(item, prefix, depth):
        nonlocal truncated
        if len(paths) >= _MAX_PATHS or depth > _MAX_DEPTH:
            truncated = True
            return
        if isinstance(item, dict):
            if len(item) > _MAX_FIELDS:
                truncated = True
            for key in sorted(item, key=lambda x: str(x))[:_MAX_FIELDS]:
                name = _safe_key(key)
                visit(item[key], prefix + "." + name if prefix else name, depth + 1)
        elif isinstance(item, list):
            paths.add(prefix + "[]")
            if len(item) > _MAX_LIST_EXAMPLES:
                truncated = True
            for element in item[:_MAX_LIST_EXAMPLES]:
                visit(element, prefix + "[]", depth + 1)
        else:
            if item is None:
                kind = "null"
            elif type(item) is bool:
                kind = "bool"
            elif type(item) is int:
                kind = "int"
            elif type(item) is float:
                kind = "float"
            elif isinstance(item, str):
                kind = "string"
            else:
                kind = "other"
            paths.add(prefix + ":" + kind)
    visit(value, "", 0)
    return tuple(sorted(paths)[:_MAX_PATHS]), truncated


def inspect(path, max_history_bytes=64 * 1024 * 1024):
    """Inspect the explicitly selected local file without copying it."""
    follower = RawFollower(Path(path), max_history_bytes=max_history_bytes)
    _, records = follower.poll()
    summary = Counter()
    shapes = Counter()
    shape_truncation = set()
    request_fields = Counter()
    payload_fields = Counter()
    shortened_requests = shortened_payloads = False
    for entry in records:
        if not isinstance(entry, dict):
            continue
        gre = entry.get("greToClientEvent")
        messages = gre.get("greToClientMessages") if isinstance(gre, dict) else None
        if not isinstance(messages, list):
            continue
        for message in messages:
            if not isinstance(message, dict) or message.get("type") != TARGET:
                continue
            summary["request_count"] += 1
            shortened_requests |= _count_top_fields(message, request_fields)
            payload = message.get("actionsAvailableReq")
            if not isinstance(payload, dict):
                summary["missing_payload"] += 1
                continue
            summary["payload_count"] += 1
            shortened_payloads |= _count_top_fields(payload, payload_fields)
            actions = payload.get("actions")
            if not isinstance(actions, list):
                summary["invalid_actions_list"] += 1
                continue
            summary["action_count"] += len(actions)
            for action in actions:
                if not isinstance(action, dict):
                    summary["invalid_action_rows"] += 1
                    continue
                typ = action.get("actionType")
                kind = typ if isinstance(typ, str) and _ACTION.fullmatch(typ) else "_unknown_action_type"
                field_paths, short = _paths(action)
                signature = (kind, field_paths)
                shapes[signature] += 1
                if short:
                    shape_truncation.add(signature)
    variants = sorted(shapes.items(), key=lambda item: (-item[1], item[0]))
    return {
        "probe": "actions-available-schema-v1",
        "source": {
            "format": "player-log-gre-v1",
            "mode": "offline",
            "framed_records": len(records),
            "complete": not follower.framer.partial and follower.framer.errors == 0,
            "partial_record": follower.framer.partial,
            "framing_errors": follower.framer.errors,
            "input_sent": False,
            "executor_connected": False,
        },
        "request_count": summary["request_count"],
        "payload_count": summary["payload_count"],
        "missing_payload": summary["missing_payload"],
        "invalid_actions_list": summary["invalid_actions_list"],
        "action_count": summary["action_count"],
        "invalid_action_rows": summary["invalid_action_rows"],
        "request_fields": _top_fields(request_fields),
        "payload_fields": _top_fields(payload_fields),
        "request_fields_truncated": shortened_requests or len(request_fields) > _MAX_FIELDS,
        "payload_fields_truncated": shortened_payloads or len(payload_fields) > _MAX_FIELDS,
        "variants": [
            {"action_type": kind, "count": count, "field_types": list(fields),
             "shape_truncated": (kind, fields) in shape_truncation}
            for (kind, fields), count in variants[:_MAX_SHAPES]
        ],
        "more_variants_omitted": len(variants) > _MAX_SHAPES,
        "raw_values_included": False,
        "self_seat_verified": False,
        "semantics_verified": False,
        "legal_actions": None,
        "actionable": False,
    }



# MP9: audited deep structural paths. Any unrecognized key is suppressed
# rather than echoed (free-form dictionary keys can themselves be private).
_RELATION_TYPES = ("ActionType_Cast", "ActionType_Activate", "ActionType_Activate_Mana")
_RELATION_FIELDS = frozenset({
    "actionType", "instanceId", "abilityGrpId", "uniqueAbilityId", "grpId",
    "facetId", "shouldStop", "isBatchable", "isManaAbilityWithSideEffect",
    "manaCost", "count", "color", "mana", "manaId", "costId", "sourceId",
    "targets", "targetIdx", "autoTapSolution", "autoTapActions",
    "manaPaymentOptions", "manaSelections", "options",
    "alternativeGrpId", "alternativeSourceZcid",
})
_RELATION_MAX_DEPTH = 9
_RELATION_MAX_PATHS = 80
_RELATION_MAX_LIST_EXAMPLES = 12
_RELATION_MAX_VARIANTS = 96
_RELATION_DISPLAY_VARIANTS = 4


def _deep_relation_paths(value):
    """Return structural *types*, never the contents of any scalar leaf."""
    paths = set()
    truncated = False
    unknown_keys = False

    def visit(item, prefix, depth):
        nonlocal truncated, unknown_keys
        if depth > _RELATION_MAX_DEPTH or len(paths) >= _RELATION_MAX_PATHS:
            truncated = True
            return
        if isinstance(item, dict):
            if not item:
                paths.add(prefix + ":empty_object")
            if len(item) > _MAX_FIELDS:
                truncated = True
            for key in sorted(item, key=lambda key: str(key))[:_MAX_FIELDS]:
                name = key if type(key) is str and key in _RELATION_FIELDS else "_unrecognized_field"
                if name == "_unrecognized_field":
                    unknown_keys = True
                visit(item[key], (prefix + "." if prefix else "") + name, depth + 1)
        elif isinstance(item, list):
            paths.add(prefix + "[]")
            if not item:
                paths.add(prefix + "[]:empty")
            if len(item) > _RELATION_MAX_LIST_EXAMPLES:
                truncated = True
            for element in item[:_RELATION_MAX_LIST_EXAMPLES]:
                visit(element, prefix + "[]", depth + 1)
        else:
            paths.add(prefix + ":" + _kind(item))

    visit(value, "", 0)
    return tuple(sorted(paths)[:_RELATION_MAX_PATHS]), truncated, unknown_keys


def _valid_ref(value):
    return type(value) is int and 0 <= value <= 2**53 - 1


def _pairs(actions):
    return {
        (action["instanceId"], action["abilityGrpId"])
        for action in actions
        if isinstance(action, dict)
        and action.get("actionType") == "ActionType_Activate_Mana"
        and _valid_ref(action.get("instanceId"))
        and _valid_ref(action.get("abilityGrpId"))
    }


def _reference_counts(items, mana_pairs, counts, label):
    """Compare opaque pair equality in the SAME request; no IDs are exported."""
    if not isinstance(items, list):
        return
    for item in items:
        counts[label + "_rows"] += 1
        if not isinstance(item, dict):
            counts[label + "_non_object"] += 1
            continue
        instance, ability = item.get("instanceId"), item.get("abilityGrpId")
        if not _valid_ref(instance) or not _valid_ref(ability):
            counts[label + "_without_pair"] += 1
        elif (instance, ability) in mana_pairs:
            counts[label + "_same_request_mana_pair_match"] += 1
        else:
            counts[label + "_same_request_mana_pair_unmatched"] += 1


def inspect_complex_relations(path, max_history_bytes=64 * 1024 * 1024):
    """One bounded local read. Structural evidence is NOT a legal action list."""
    follower = RawFollower(Path(path), max_history_bytes=max_history_bytes)
    _, records = follower.poll()
    request_count, payload_count, invalid_actions = 0, 0, 0
    action_counts, variants, refs = Counter(), {}, Counter()
    unknown_by_type, truncated_by_type = Counter(), Counter()
    untracked_variants = 0
    for entry in records:
        if not isinstance(entry, dict):
            continue
        gre = entry.get("greToClientEvent")
        messages = gre.get("greToClientMessages") if isinstance(gre, dict) else None
        if not isinstance(messages, list):
            continue
        for message in messages:
            if not isinstance(message, dict) or message.get("type") != TARGET:
                continue
            request_count += 1
            payload = message.get("actionsAvailableReq")
            if not isinstance(payload, dict):
                continue
            payload_count += 1
            actions = payload.get("actions")
            if not isinstance(actions, list):
                invalid_actions += 1
                continue
            mana_pairs = _pairs(actions)
            for action in actions:
                if not isinstance(action, dict):
                    invalid_actions += 1
                    continue
                kind = action.get("actionType")
                if type(kind) is not str or kind not in _RELATION_TYPES:
                    continue
                action_counts[kind] += 1
                paths, truncated, unknown = _deep_relation_paths(action)
                signature = (kind, paths)
                if signature in variants or len(variants) < _RELATION_MAX_VARIANTS:
                    variants[signature] = variants.get(signature, 0) + 1
                else:
                    untracked_variants += 1
                if truncated:
                    truncated_by_type[kind] += 1
                if unknown:
                    unknown_by_type[kind] += 1
                auto = action.get("autoTapSolution")
                if isinstance(auto, dict):
                    _reference_counts(auto.get("autoTapActions"), mana_pairs, refs, "autotap")
                if kind == "ActionType_Activate_Mana":
                    _reference_counts(action.get("manaSelections"), mana_pairs, refs,
                                      "mana_selection")
    details = []
    for kind in _RELATION_TYPES:
        candidates = sorted(
            ((signature[1], count) for signature, count in variants.items()
             if signature[0] == kind),
            key=lambda entry: (-entry[1], entry[0]))
        details.append({
            "action_type": kind, "active_action_count": action_counts[kind],
            "distinct_structural_variants": len(candidates),
            "variants": [{"count": count, "field_types": list(paths)}
                         for paths, count in candidates[:_RELATION_DISPLAY_VARIANTS]],
            "unshown_variant_count": max(0, len(candidates) - _RELATION_DISPLAY_VARIANTS),
            "truncated_action_count": truncated_by_type[kind],
            "unrecognized_field_action_count": unknown_by_type[kind],
        })
    return {
        "probe": "actions-complex-relations-v1",
        "source": {
            "format": "player-log-gre-v1", "mode": "offline",
            "framed_records": len(records),
            "complete": follower.framer.errors == 0 and not follower.framer.partial,
            "partial_record": follower.framer.partial,
            "framing_errors": follower.framer.errors,
            "input_sent": False, "executor_connected": False,
        },
        "request_count": request_count,
        "payload_count": payload_count,
        "invalid_active_action_rows_or_lists": invalid_actions,
        "complex_active_action_count": sum(action_counts.values()),
        "action_shapes": details,
        "same_request_raw_id_pair_comparisons": {
            key: refs[key] for key in (
                "autotap_rows", "autotap_non_object", "autotap_without_pair",
                "autotap_same_request_mana_pair_match",
                "autotap_same_request_mana_pair_unmatched",
                "mana_selection_rows", "mana_selection_non_object",
                "mana_selection_without_pair",
                "mana_selection_same_request_mana_pair_match",
                "mana_selection_same_request_mana_pair_unmatched"
            )},
        "reference_comparison_meaning": "numeric_pair_equality_only_not_payment_legality",
        "distinct_variant_storage_cap_reached": untracked_variants > 0,
        "untracked_variant_action_count": untracked_variants,
        "raw_values_included": False, "self_seat_verified": False,
        "legal_actions": None, "actionable": False,
    }



_VISIBLE_TYPES = ('ActionType_Play', 'ActionType_Cast',
                  'ActionType_Activate', 'ActionType_Activate_Mana')
_VISIBLE_STATUSES = ('visible_unique', 'not_in_visible_projection',
                     'missing_source_instance', 'ambiguous_visible_projection')


def inspect_visible_sources(path, max_history_bytes=64 * 1024 * 1024):
    """Only counts of accepted own-request joins, no raw identifiers or card data."""
    follower = RawFollower(Path(path), max_history_bytes=max_history_bytes)
    _, records = follower.poll()
    reducer = RawReducer()
    reducer.reset(follower.generation)
    seen = set()
    stats = Counter()
    for entry in records:
        reducer.apply(entry)
        if not isinstance(entry, dict) or reducer.error is not None:
            continue
        request = reducer.request
        if not request or request.get('type') != TARGET:
            continue
        binding = request.get('binding')
        if not isinstance(binding, dict) or binding.get('ownership_verified') is not True:
            continue
        gre = entry.get('greToClientEvent')
        messages = gre.get('greToClientMessages') if isinstance(gre, dict) else None
        if not isinstance(messages, list) or not any(
                isinstance(m, dict) and m.get('type') == TARGET
                and m.get('msgId') == request['id']
                and m.get('gameStateId') == request['game_state_id']
                and m.get('systemSeatIds') == [binding['self_seat']]
                for m in messages):
            continue
        identity = (binding['generation'], binding['match'], binding['game'],
                    binding['game_state_id'], binding['self_seat'], request['id'])
        if identity in seen:
            continue
        seen.add(identity)
        current = reducer.document()['current']
        inventory = current['request'].get('action_inventory')
        if not isinstance(inventory, dict):
            continue
        stats['verified_inventory_requests'] += 1
        data = inventory['visible_source_links']
        for row in data['links']:
            kind, status = row.get('action_type'), row.get('status')
            if kind not in _VISIBLE_TYPES or status not in _VISIBLE_STATUSES:
                continue
            stats['total_described_sources'] += 1
            stats['status.' + status] += 1
            stats['type.' + kind + '.' + status] += 1
            if status == 'visible_unique':
                equality = row.get('raw_group_equals_visible_card_id')
                label = 'equal' if equality is True else 'different' if equality is False else 'unknown'
                stats['visible_raw_group_comparison.' + label] += 1
    return {
        'probe': 'visible-action-sources-v1',
        'source': {'mode': 'offline', 'format': 'player-log-gre-v1',
                   'framed_records': len(records),
                   'complete': follower.framer.errors == 0 and not follower.framer.partial,
                   'partial_record': follower.framer.partial,
                   'framing_errors': follower.framer.errors,
                   'input_sent': False, 'executor_connected': False},
        'verified_inventory_requests': stats['verified_inventory_requests'],
        'total_described_sources': stats['total_described_sources'],
        'status_counts': {key: stats['status.' + key] for key in _VISIBLE_STATUSES},
        'type_status_counts': [
            {'type': kind, 'status': status,
             'count': stats['type.' + kind + '.' + status]}
            for kind in _VISIBLE_TYPES for status in _VISIBLE_STATUSES
            if stats['type.' + kind + '.' + status]],
        'visible_raw_group_comparisons': {
            key: stats['visible_raw_group_comparison.' + key]
            for key in ('equal', 'different', 'unknown')},
        'source_visibility_only': True, 'legal_actions': None,
        'actionable': False, 'raw_values_included': False,
    }


def inspect_gap_coverage(path, max_history_bytes=64 * 1024 * 1024):
    """Aggregates only accepted own-seat, current engine-action gap reports."""
    follower = RawFollower(Path(path), max_history_bytes)
    _, records = follower.poll()
    reducer = RawReducer()
    reducer.reset(follower.generation)
    seen = set()
    counts, types, undetailed, statuses = Counter(), Counter(), Counter(), Counter()
    gaps, shapes = Counter(), Counter()
    for entry in records:
        reducer.apply(entry)
        if not isinstance(entry, dict) or reducer.error is not None:
            continue
        request = reducer.request
        if not request or request.get("type") != TARGET:
            continue
        binding = request.get("binding")
        if not isinstance(binding, dict) or binding.get("ownership_verified") is not True:
            continue
        gre = entry.get("greToClientEvent")
        messages = gre.get("greToClientMessages") if isinstance(gre, dict) else None
        if not isinstance(messages, list) or not any(
                isinstance(m, dict) and m.get("type") == TARGET
                and m.get("msgId") == request["id"]
                and m.get("gameStateId") == request["game_state_id"]
                and m.get("systemSeatIds") == [binding["self_seat"]]
                for m in messages):
            continue
        identity = (binding["generation"], binding["match"], binding["game"],
                    binding["game_state_id"], binding["self_seat"], request["id"])
        if identity in seen:
            continue
        seen.add(identity)
        doc = reducer.document()
        doc["source"] = {
            "format": "player-log-gre-v1", "mode": "offline",
            "generation": follower.generation, "byte_offset": follower.offset,
            # Current iterated record is complete even if final stream has a tail.
            "partial_record": False,
            "input_sent": False, "executor_connected": False}
        report = assess_action_gaps(build_decision_input(doc))
        if report is None:
            counts["unassessable_verified_requests"] += 1
            continue
        counts["assessed_verified_requests"] += 1
        for source, key in (("observed_action_rows", "engine_active_rows"),
                            ("described_rows", "described_rows"),
                            ("undetailed_rows", "undetailed_rows")):
            counts[key] += report[source]
        for item in report["undetailed_by_type"]:
            undetailed[item["engine_action_type"]] += item["count"]
        for item in report["gap_counts"]:
            gaps[item["gap"]] += item["described_rows"]
        for item in report["actions"]:
            types[item["engine_action_type"]] += 1
            statuses[item["source_link_status"]] += 1
            for value in item["parameter_shapes"].values():
                shapes[value["shape"]] += 1
            relations = item["request_local_relations"]
            counts["raw_pair_unique_rows"] += sum(
                relations[name]["unique_pair_rows"] for name in
                ("auto_tap_mana_links", "mana_selection_links"))
            counts["raw_target_groups_shaped"] += (
                relations["target_slots"]["raw_target_groups_shaped"])
            counts["raw_relation_unresolved_rows"] += sum(
                relations[name]["unresolved_rows"] for name in
                ("auto_tap_mana_links", "mana_selection_links", "target_slots"))
    return {
        "probe": "mtga-action-gap-coverage-v1",
        "source": {
            "format": "player-log-gre-v1", "mode": "offline",
            "framed_records": len(records),
            "complete": follower.framer.errors == 0 and not follower.framer.partial,
            "framing_errors": follower.framer.errors,
            "partial_record": follower.framer.partial,
            "input_sent": False, "executor_connected": False,
        },
        "assessed_verified_requests": counts["assessed_verified_requests"],
        "unassessable_verified_requests": counts["unassessable_verified_requests"],
        "engine_active_rows": counts["engine_active_rows"],
        "described_rows": counts["described_rows"],
        "undetailed_rows": counts["undetailed_rows"],
        "described_by_type": [
            {"action_type": kind, "count": count}
            for kind, count in sorted(types.items())],
        "undetailed_by_type": [
            {"action_type": kind, "count": count}
            for kind, count in sorted(undetailed.items())],
        "source_status_counts": dict(sorted(statuses.items())),
        "gap_row_counts": [
            {"gap": kind, "described_rows": count}
            for kind, count in sorted(gaps.items())],
        "parameter_shape_counts": dict(sorted(shapes.items())),
        "raw_pair_unique_rows": counts["raw_pair_unique_rows"],
        "raw_target_groups_shaped": counts["raw_target_groups_shaped"],
        "raw_relation_unresolved_rows": counts["raw_relation_unresolved_rows"],
        "counts_not_rule_legality": True,
        "raw_values_included": False, "legal_actions": None,
        "actionable": False, "input_sent": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Read-only schema probe; no action IDs, card IDs or prompt values leave the file")
    parser.add_argument("input", type=Path, help="explicit local Player.log path")
    parser.add_argument("--max-history-bytes", type=int, default=64 * 1024 * 1024)
    choices = parser.add_mutually_exclusive_group()
    choices.add_argument("--complex-relations", action="store_true",
                         help="MP9: nested action field types / raw-pair equality counts")
    choices.add_argument("--visible-sources", action="store_true",
                         help="MP10: only own-request visible-source join statistics")
    choices.add_argument("--gap-coverage", action="store_true",
                         help="MP14: aggregate own-request action rule/response gaps (no raw values)")
    choices.add_argument("--response-envelopes", action="store_true",
                         help="MP15: count-only own-client response envelope/offer linkage")
    choices.add_argument("--response-action-shapes", action="store_true",
                         help="MP15: strictly value-free action-array item schema on matched own responses")
    choices.add_argument("--response-choice-correlation", action="store_true",
                         help="MP16: value-free Pass/Play same-request response candidate correlation")
    choices.add_argument("--complex-response-choice-correlation", action="store_true",
                         help="MP16 Phase 2: value-free complex same-request action identity correlation")
    choices.add_argument("--choice-graph-history", action="store_true",
                         help="MP16 Phase 3: count-only complex constraints and temporal successors")
    args = parser.parse_args(argv)
    if not 1 <= args.max_history_bytes <= 1024 * 1024 * 1024:
        parser.error("max-history-bytes must be between 1 and 1073741824")
    try:
        if args.choice_graph_history:
            result = inspect_response_envelopes(
                args.input, args.max_history_bytes, choice_graph_history=True)
        elif args.complex_response_choice_correlation:
            result = inspect_response_envelopes(
                args.input, args.max_history_bytes, complex_semantic_choices=True)
        elif args.response_choice_correlation:
            result = inspect_response_envelopes(
                args.input, args.max_history_bytes, semantic_choices=True)
        elif args.response_action_shapes:
            result = inspect_response_envelopes(
                args.input, args.max_history_bytes, action_shapes=True)
        elif args.response_envelopes:
            result = inspect_response_envelopes(args.input, args.max_history_bytes)
        elif args.gap_coverage:
            result = inspect_gap_coverage(args.input, args.max_history_bytes)
        elif args.visible_sources:
            result = inspect_visible_sources(args.input, args.max_history_bytes)
        elif args.complex_relations:
            result = inspect_complex_relations(args.input, args.max_history_bytes)
        else:
            result = inspect(args.input, args.max_history_bytes)
    except (OSError, ValueError):
        print(json.dumps({"probe": ("mtga-choice-graph-history-v1" if args.choice_graph_history
                                   else "mtga-client-response-complex-correlation-v1" if args.complex_response_choice_correlation
                                   else "mtga-client-response-semantic-correlation-v1" if args.response_choice_correlation
                                   else "mtga-client-response-action-shapes-v1" if args.response_action_shapes
                                   else "mtga-client-response-envelopes-v1" if args.response_envelopes
                                   else "mtga-action-gap-coverage-v1" if args.gap_coverage
                                   else "visible-action-sources-v1" if args.visible_sources
                                   else "actions-complex-relations-v1" if args.complex_relations
                                   else "actions-available-schema-v1"),
                          "error": "file_unavailable_or_history_limit",
                          "actionable": False, "input_sent": False}))
        return 1
    print(json.dumps(result, sort_keys=True, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
