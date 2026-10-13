"""MP14: classify gaps in already-projected, request-bound action evidence.

Never reads raw GRE or SQLite. A gap report is engineering evidence, not a
legal-action set, strategic recommendation, or execution permit.
"""
from collections import Counter


_KNOWN_TYPES = (
    "ActionType_Pass", "ActionType_Play", "ActionType_Cast",
    "ActionType_Activate", "ActionType_Activate_Mana",
)
_OBSERVED_TYPES = frozenset(_KNOWN_TYPES + (
    "ActionType_FloatMana", "_unrecognized_action_type"))
_SOURCE = frozenset((
    "visible_unique", "not_in_visible_projection",
    "missing_source_instance", "ambiguous_visible_projection",
    "unverified", "not_applicable",
))
_KIND_GAPS = {
    "ActionType_Pass": ("pass_response_contract_unverified",),
    "ActionType_Play": ("play_conditions_unverified",),
    "ActionType_Cast": ("cast_payment_unverified",
                        "cast_effect_and_targets_unverified"),
    "ActionType_Activate": ("activation_cost_unverified",
                            "ability_effect_and_targets_unverified"),
    "ActionType_Activate_Mana": ("mana_effect_and_payment_unverified",),
}
_PARAMETERS = ("manaCost", "manaPaymentOptions", "manaSelections",
               "targets", "autoTapSolution")
_PAIR_STATUSES = frozenset(("unique_pair", "ambiguous_pair", "no_active_pair",
                            "missing_or_invalid_pair", "non_object"))


def _id(value):
    return type(value) is int and 0 <= value <= 2**53 - 1


def _param_shapes(described):
    raw = described.get("opaque_parameter_shapes")
    if raw is None:
        return {}, False
    if not isinstance(raw, dict):
        return None, True
    result, malformed = {}, False
    for name in _PARAMETERS:
        if name not in raw:
            continue
        item = raw[name]
        if not isinstance(item, dict):
            return None, True
        is_auto = name == "autoTapSolution"
        expected = "object" if is_auto else "array"
        count = item.get("auto_tap_actions_count" if is_auto else "element_count")
        valid = (item.get("kind") == expected and
                 (count is None and is_auto or type(count) is int and 0 <= count <= 4096))
        if not valid:
            malformed = True
        result[name] = {
            "shape": "container_size_only" if valid else "unexpected_or_unknown",
            "element_count": count if valid else None,
        }
    return result, malformed


def _relation_counts(relations, field, target=False):
    value = relations.get(field)
    if value is None:
        return {"state": "not_described", "entries_examined": 0,
                "unique_pair_rows": 0, "raw_target_groups_shaped": 0,
                "unresolved_rows": 0, "truncated": False}, False
    if (not isinstance(value, dict) or
            type(value.get("valid_array")) is not bool or
            type(value.get("truncated")) is not bool or
            type(value.get("total")) is not int and value.get("total") is not None or
            not isinstance(value.get("entries"), list)):
        return None, True
    entries = value["entries"]
    if len(entries) > 64:
        return None, True
    if value["valid_array"] is False:
        if entries:
            return None, True
        return {"state": "unexpected_container", "entries_examined": 0,
                "unique_pair_rows": 0, "raw_target_groups_shaped": 0,
                "unresolved_rows": 0, "truncated": value["truncated"]}, True
    if (type(value["total"]) is not int or value["total"] < len(entries) or
            type(value.get("examined")) is not int or
            value["examined"] != len(entries)):
        return None, True
    valid_count = 0
    for row in entries:
        if not isinstance(row, dict):
            return None, True
        if target:
            if type(row.get("valid_shape")) is not bool:
                return None, True
            valid_count += row["valid_shape"]
        else:
            if (type(row.get("status")) is not str or
                    row["status"] not in _PAIR_STATUSES):
                return None, True
            valid_count += row["status"] == "unique_pair"
    missing = len(entries) - valid_count
    return {
        "state": "raw_positions_and_counts_only",
        "entries_examined": len(entries),
        "unique_pair_rows": 0 if target else valid_count,
        "raw_target_groups_shaped": valid_count if target else 0,
        "unresolved_rows": missing,
        "truncated": value["truncated"],
    }, missing > 0 or value["truncated"]


def assess_action_gaps(decision_input):
    """No positive legal/evaluable classification exists at this milestone.

    Return None for invalid input or non-ActionsAvailable observations.
    """
    if not isinstance(decision_input, dict):
        return None
    if (decision_input.get("schema") != "mtga-readonly-decision-input-v1"
            or decision_input.get("read_only") is not True
            or decision_input.get("actionable") is not False
            or decision_input.get("input_sent") is not False
            or decision_input.get("executor_connected") is not False
            or decision_input.get("strategy_selected") is not False):
        return None
    origin = decision_input.get("source")
    request = decision_input.get("request")
    binding = decision_input.get("binding")
    if (not isinstance(origin, dict) or
            origin.get("freshness_verified") is not False or
            not isinstance(binding, dict) or
            binding.get("ownership_verified") is not True or
            not _id(binding.get("request_id")) or
            not isinstance(request, dict) or
            request.get("type") != "GREMessageType_ActionsAvailableReq"
            or request.get("shape_supported") is not False):
        return None
    inventory = request.get("engine_action_inventory")
    visible = decision_input.get("visible_objects")
    if not isinstance(inventory, dict) or not isinstance(visible, list):
        return None
    offered, described = inventory.get("offered_count"), inventory.get("described_rows")
    if (type(offered) is not int or not 0 <= offered <= 256 or
            not isinstance(described, list) or len(described) > offered or
            inventory.get("inactive_excluded") is not True or
            inventory.get("legal_actions_complete") is not False or
            inventory.get("described_count") != len(described) or
            inventory.get("undetailed_count") != offered - len(described)):
        return None
    types = inventory.get("type_counts")
    if not isinstance(types, list) or len(types) > 8:
        return None
    available = {}
    for row in visible:
        if not isinstance(row, dict) or not _id(row.get("instance_id")):
            return None
        available.setdefault(row["instance_id"], []).append(row)
    listed = {}
    for item in types:
        if not isinstance(item, dict):
            return None
        name, count = item.get("action_type"), item.get("count")
        if (type(name) is not str or name not in _OBSERVED_TYPES or
                name in listed or type(count) is not int or
                not 0 <= count <= offered):
            return None
        listed[name] = count
    if sum(listed.values()) != offered:
        return None
    positions, described_by_type, gap_counts, rows = set(), Counter(), Counter(), []
    for item in described:
        if not isinstance(item, dict):
            return None
        index, name, status = (item.get("list_position"),
                               item.get("engine_action_type"),
                               item.get("source_link_status"))
        if (type(index) is not int or not 0 <= index < offered or
                index in positions or name not in _KNOWN_TYPES or
                type(status) is not str or status not in _SOURCE or
                item.get("executable") is not False or
                item.get("legal_action_verified") is not False):
            return None
        if (name == "ActionType_Pass") != (status == "not_applicable"):
            return None
        positions.add(index)
        described_by_type[name] += 1
        card_state = "not_enriched"
        if status == "visible_unique":
            oid = item.get("visible_object_id")
            if not _id(oid) or len(available.get(oid, ())) != 1:
                return None
            card = available[oid][0].get("local_card")
            if isinstance(card, dict):
                card_state = (card.get("status") if card.get("status") in (
                    "resolved", "ambiguous", "unresolved", "missing_card_id")
                    else "unknown_catalog_status")
        elif "visible_object_id" in item:
            return None
        param, bad_shape = _param_shapes(item)
        if param is None:
            return None
        rel = item.get("raw_relations")
        if rel is not None and not isinstance(rel, dict):
            return None
        if rel is not None and any((
                rel.get("pair_equality_only") is not True,
                rel.get("payment_legal") is not False,
                rel.get("targets_legal") is not False,
                rel.get("executable") is not False,
                rel.get("read_only") is not True)):
            return None
        rel = rel or {}
        relations, bad_rel = {}, False
        for key in ("auto_tap_mana_links", "mana_selection_links", "target_slots"):
            result, incomplete = _relation_counts(rel, key, key == "target_slots")
            if result is None:
                return None
            relations[key] = result
            bad_rel = bad_rel or incomplete
        gaps = set(_KIND_GAPS[name])
        gaps.add("response_encoding_unverified")
        if name != "ActionType_Pass" and status != "visible_unique":
            gaps.add("source_visibility_unresolved")
        if bad_shape or bad_rel:
            gaps.add("raw_parameter_structure_incomplete")
        for gap in gaps:
            gap_counts[gap] += 1
        rows.append({
            "list_position": index, "engine_action_type": name,
            "source_link_status": status,
            "catalog_identity_status": card_state if status == "visible_unique" else None,
            "parameter_shapes": param,
            "request_local_relations": relations,
            "rule_gaps": sorted(gaps),
            "decision_evaluable": False,
            "legal_action_verified": False, "executable": False,
        })
    if any(count > listed.get(name, 0) for name, count in described_by_type.items()):
        return None
    undetailed = [
        {"engine_action_type": name,
         "count": count - described_by_type[name],
         "gap": "active_engine_row_not_structurally_described"}
        for name, count in sorted(listed.items())
        if count > described_by_type[name]
    ]
    return {
        "schema": "mtga-action-evidence-gaps-v1",
        "status": "engineering_gap_inventory_only",
        "scope": "authenticated_own_current_engine_action_request",
        "observed_action_rows": offered,
        "described_rows": len(rows),
        "undetailed_rows": offered - len(rows),
        "undetailed_by_type": undetailed,
        "actions": sorted(rows, key=lambda item: item["list_position"]),
        "gap_counts": [{"gap": name, "described_rows": gap_counts[name]}
                       for name in sorted(gap_counts)],
        "request_wide_gaps": [
            "complete_rules_unverified", "legal_response_contract_unverified",
            "live_freshness_unverified", "strategy_value_unverified",
            "native_mtga_input_not_connected",
        ],
        "engine_listed_not_proven_legal": True,
        "strategy_evaluation_complete": False,
        "legal_actions": None, "read_only": True, "actionable": False,
        "input_sent": False, "executor_connected": False,
    }
