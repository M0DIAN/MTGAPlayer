"""MP13 read-only observation for future local decision research.

Accepts ONLY a projected raw GRE CLI document, never RawReducer's private
working maps. This is not a legal-action API or a native execution contract.
"""
import copy


def _id(value):
    return type(value) is int and 0 <= value <= 2**53 - 1


def _catalog(card):
    if not isinstance(card, dict):
        return None
    status = card.get("status")
    if status not in ("resolved", "unresolved", "ambiguous", "missing_card_id"):
        return None
    result = {"status": status}
    if status == "resolved" and isinstance(card.get("name"), str):
        result["name"] = card["name"]
        result["set_code"] = card.get("set_code")
        result["collector_number"] = card.get("collector_number")
        stats = card.get("catalog_stats")
        if isinstance(stats, dict):
            result["static_catalog_stats"] = {
                "power": stats.get("power") if type(stats.get("power")) is int else None,
                "toughness": (stats.get("toughness")
                              if type(stats.get("toughness")) is int else None),
                "source": "Cards.Power/Toughness",
                "effective_in_game": False, "rules_verified": False,
            }
    return result


def _observed_actions(inventory, visible_counts):
    """Only existing typed active descriptions, never synthesize other rows."""
    if not isinstance(inventory, dict) or type(inventory.get("offered_count")) is not int:
        return None
    offered = inventory["offered_count"]
    if not 0 <= offered <= 256:
        return None
    simple = inventory.get("simple_shapes")
    complex_rows = inventory.get("complex_raw_shapes")
    source_links = inventory.get("visible_source_links")
    if (not isinstance(simple, list) or not isinstance(complex_rows, list) or
            not isinstance(source_links, dict) or
            not isinstance(source_links.get("links"), list)):
        return None
    records, links = simple + complex_rows, source_links["links"]
    if len(records) > offered or len(links) > offered:
        return None
    by_position = {}
    for link in links:
        if not isinstance(link, dict):
            return None
        position = link.get("list_position")
        if (type(position) is not int or not 0 <= position < offered or
                position in by_position):
            return None
        by_position[position] = link
    described, positions = [], set()
    for shape in records:
        if not isinstance(shape, dict):
            return None
        position = shape.get("list_position")
        action_type = shape.get("action_type")
        if (type(position) is not int or position < 0 or position >= offered or
                position in positions or not isinstance(action_type, str)):
            return None
        positions.add(position)
        link = by_position.get(position)
        source_status = "not_applicable" if action_type == "ActionType_Pass" else (
            link.get("status", "unverified") if isinstance(link, dict) else "unverified")
        row = {
            "list_position": position, "engine_action_type": action_type,
            "source_link_status": source_status,
            "raw_action_details_complete": False,
            "legal_action_verified": False, "executable": False,
        }
        if (source_status == "visible_unique" and isinstance(link, dict) and
                _id(link.get("visible_object_id")) and
                visible_counts.get(link["visible_object_id"]) == 1):
            row["visible_object_id"] = link["visible_object_id"]
        if "opaque_parameter_shapes" in shape:
            row["opaque_parameter_shapes"] = copy.deepcopy(
                shape["opaque_parameter_shapes"])
            row["raw_relations"] = copy.deepcopy(shape.get("raw_relations"))
        described.append(row)
    described.sort(key=lambda row: row["list_position"])
    return {
        "offered_count": offered,
        "described_count": len(described),
        "undetailed_count": offered - len(described),
        "type_counts": copy.deepcopy(inventory.get("types", [])),
        "inactive_count": inventory.get("inactive_count"),
        "inactive_excluded": True,
        "legal_actions_complete": False,
        "described_rows": described,
    }


def build_decision_input(document):
    """Return a request-bound observation or None; never use last_valid.

    Expected input is the final projected output of raw replay/watch AFTER
    optional visible catalog enrichment and source metadata have been added.
    Historical/offline and watch data are always non-actionable.
    """
    if not isinstance(document, dict):
        return None
    current, source = document.get("current"), document.get("source")
    if (not isinstance(current, dict) or not isinstance(source, dict) or
            current.get("valid") is not True or current.get("actionable") is not False or
            current.get("legal_actions") is not None or
            source.get("format") != "player-log-gre-v1" or
            source.get("mode") not in ("offline", "watch") or
            source.get("partial_record") is not False or
            source.get("input_sent") is not False or
            source.get("executor_connected") is not False):
        return None
    request = current.get("request")
    if not isinstance(request, dict) or request.get("current") is not True:
        return None
    binding = request.get("binding")
    if (not isinstance(binding, dict) or
            binding.get("ownership_verified") is not True or
            not _id(binding.get("generation")) or
            not _id(source.get("generation")) or
            not isinstance(binding.get("match"), str) or
            not _id(binding.get("game")) or binding.get("game") < 1 or
            type(binding.get("self_seat")) is not int or
            binding.get("self_seat") not in (1, 2) or
            not _id(request.get("id")) or
            not _id(current.get("game_state_id")) or
            request.get("game_state_id") != current.get("game_state_id") or
            binding.get("generation") != source.get("generation") or
            any(binding.get(k) != current.get(k) for k in
                ("match", "game", "game_state_id", "self_seat"))):
        return None
    objects = current.get("objects")
    if not isinstance(objects, list) or len(objects) > 512:
        return None
    visible, visible_counts = [], {}
    for obj in objects:
        if not isinstance(obj, dict) or not _id(obj.get("id")):
            return None
        instance = obj["id"]
        visible_counts[instance] = visible_counts.get(instance, 0) + 1
        row = {
            "instance_id": instance,
            "card_id": obj.get("card_id") if _id(obj.get("card_id")) else None,
            "zone": obj.get("zone"), "owner_seat": obj.get("owner"),
            "controller_seat": obj.get("controller"), "tapped": obj.get("tapped"),
        }
        if "local_card" in obj:
            catalog = _catalog(obj["local_card"])
            if catalog is not None:
                row["local_card"] = catalog
        visible.append(row)
    inventory = request.get("action_inventory")
    actions = _observed_actions(inventory, visible_counts) if inventory is not None else None
    if inventory is not None and actions is None:
        return None
    selectn = request.get("selection")
    selection = None
    if (request.get("type") == "GREMessageType_SelectNReq" and
            request.get("supported") is True and isinstance(selectn, dict)):
        candidates = request.get("candidates")
        if (not isinstance(candidates, list) or len(candidates) > 256 or
                not all(isinstance(x, dict) and _id(x.get("instance_id"))
                        for x in candidates)):
            return None
        selection = {
            "offered_instance_ids": [x["instance_id"] for x in candidates],
            "max_sel_raw": selectn.get("max_sel"),
            "min_sel_verified": None,
            "combinations_complete": False,
            "source_ids_not_visibility_joined": True,
        }
    return {
        "schema": "mtga-readonly-decision-input-v1",
        "status": "request_observed_only",
        "binding": {
            "generation": binding["generation"],
            "match": binding["match"], "game": binding["game"],
            "game_state_id": binding["game_state_id"],
            "self_seat": binding["self_seat"], "request_id": request["id"],
            "ownership_verified": True,
            "source_byte_offset": source.get("byte_offset"),
        },
        "game": {
            "room_state": current.get("room_state"),
            "game_stage": current.get("game_stage"),
            "source_state_timestamp": current.get("source_state_timestamp"),
            "turn": copy.deepcopy(current.get("turn")),
            "players": copy.deepcopy(current.get("players")),
            "mana": None, "effective_combat_stats": None, "rules": None,
        },
        "visible_objects": visible,
        "request": {
            "type": request.get("type"),
            "shape_supported": request.get("supported") is True,
            "unsupported_reason": request.get("unsupported_reason"),
            "select_n": selection,
            "engine_action_inventory": actions,
        },
        "source": {
            "mode": source["mode"],
            "phase": source.get("phase"), "stopped": source.get("stopped", False),
            "freshness_verified": False,
        },
        "unknown": {
            "legal_actions": None, "mana_payment_legality": None,
            "target_legality": None, "effective_combat_stats": None,
            "screen_coordinates": None, "complete_rules": None,
        },
        "read_only": True, "actionable": False,
        "input_sent": False, "executor_connected": False,
        "strategy_selected": False,
    }
