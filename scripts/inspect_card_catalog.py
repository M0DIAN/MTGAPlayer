"""MP11 offline-only coverage probe: Player.log visible cards + local SQLite titles.

Prints aggregate counts only: no card names, IDs, paths or private GRE values.
"""
import argparse
from collections import Counter
import json
from pathlib import Path

from mtgaplayer.card_catalog import CardCatalogError, lookup_local_titles
from mtgaplayer.raw_log import RawFollower, RawReducer


def inspect(log_path, card_db_path, max_history_bytes=64 * 1024 * 1024):
    follower = RawFollower(Path(log_path), max_history_bytes=max_history_bytes)
    _, records = follower.poll()
    reducer = RawReducer()
    reducer.reset(follower.generation)
    observed = set()
    visible_card_ids = set()
    action_card_ids = []
    counts = Counter()
    for entry in records:
        reducer.apply(entry)
        if reducer.error is not None or not isinstance(entry, dict):
            continue
        request = reducer.request
        if not request or request.get("type") != "GREMessageType_ActionsAvailableReq":
            continue
        binding = request.get("binding")
        if not isinstance(binding, dict) or binding.get("ownership_verified") is not True:
            continue
        gre = entry.get("greToClientEvent")
        messages = gre.get("greToClientMessages") if isinstance(gre, dict) else None
        if not isinstance(messages, list) or not any(
                isinstance(m, dict) and m.get("type") == request["type"]
                and m.get("msgId") == request["id"]
                and m.get("gameStateId") == request["game_state_id"]
                and m.get("systemSeatIds") == [binding["self_seat"]]
                for m in messages):
            continue
        identity = (binding["generation"], binding["match"], binding["game"],
                    binding["game_state_id"], binding["self_seat"], request["id"])
        if identity in observed:
            continue
        observed.add(identity)
        current = reducer.document()["current"]
        if not current.get("valid"):
            continue
        inventory = current["request"].get("action_inventory")
        if not isinstance(inventory, dict):
            continue
        counts["verified_request_count"] += 1
        visible_objects = {obj["id"]: obj for obj in current["objects"]
                           if isinstance(obj, dict) and type(obj.get("id")) is int}
        for obj in visible_objects.values():
            grp = obj.get("card_id")
            if type(grp) is int and grp >= 0:
                visible_card_ids.add(grp)
        for link in inventory.get("visible_source_links", {}).get("links", []):
            if link.get("status") != "visible_unique":
                continue
            counts["uniquely_joined_action_rows"] += 1
            obj = visible_objects.get(link["visible_object_id"])
            grp = obj.get("card_id") if isinstance(obj, dict) else None
            if type(grp) is int and grp >= 0:
                action_card_ids.append(grp)
            else:
                counts["joined_source_without_card_id"] += 1

    names, ambiguous = lookup_local_titles(card_db_path, visible_card_ids)
    resolved = set(names)
    return {
        "probe": "local-visible-card-catalog-v1",
        "source": {
            "mode": "offline", "complete": follower.framer.errors == 0
            and not follower.framer.partial, "framed_records": len(records),
            "framing_errors": follower.framer.errors,
            "partial_record": follower.framer.partial,
            "input_sent": False, "executor_connected": False
        },
        "catalog": {
            "source": "explicit_local_mtga_sqlite",
            "language": "enUS", "read_only": True,
            "card_names_exported": False, "original_game_files_copied": False,
            "rules_verified": False,
        },
        "verified_requests": counts["verified_request_count"],
        "unique_visible_card_ids": len(visible_card_ids),
        "unique_names_resolved": len(resolved),
        "unique_card_ids_ambiguous": len(ambiguous),
        "unique_card_ids_unresolved": len(visible_card_ids - resolved - ambiguous),
        "uniquely_joined_action_rows": counts["uniquely_joined_action_rows"],
        "joined_action_rows_with_catalog_names": sum(
            grp in resolved for grp in action_card_ids),
        "joined_action_rows_without_catalog_names": (
            counts["uniquely_joined_action_rows"] -
            sum(grp in resolved for grp in action_card_ids)),
        "raw_values_included": False, "legal_actions": None, "actionable": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read-only, count-only MTGA card name coverage")
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--card-db", type=Path, required=True)
    parser.add_argument("--max-history-bytes", type=int, default=64 * 1024 * 1024)
    args = parser.parse_args(argv)
    if not 1 <= args.max_history_bytes <= 1024 * 1024 * 1024:
        parser.error("max-history-bytes must be within 1 and 1073741824")
    try:
        result = inspect(args.log, args.card_db, args.max_history_bytes)
    except (OSError, ValueError, CardCatalogError):
        print(json.dumps({
            "probe": "local-visible-card-catalog-v1",
            "error": "catalog_or_log_unavailable_or_unsupported",
            "actionable": False, "input_sent": False
        }))
        return 1
    print(json.dumps(result, sort_keys=True, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
