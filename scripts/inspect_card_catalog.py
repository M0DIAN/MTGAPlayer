"""MP11 offline-only coverage probe: Player.log visible cards + local SQLite titles.

Prints aggregate counts only: no card names, IDs, paths or private GRE values.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import re
import sqlite3
from contextlib import closing

from mtgaplayer.card_catalog import CardCatalogError, lookup_local_titles, _card_id
from mtgaplayer.raw_log import RawFollower, RawReducer



# Static whitelist of fields observed in the owner's 60-column Cards schema.
_FIELDS = ("Types", "Subtypes", "Supertypes", "Colors", "ColorIdentity",
           "Power", "Toughness", "AbilityIds", "LinkedFaceGrpIds",
           "OldSchoolManaText", "IsToken", "IsPrimaryCard", "IsDigitalOnly",
           "IsRebalanced", "TypeTextId", "SubtypeTextId")
_INTEGER = re.compile(r"[+-]?[0-9]+\Z")
_DECIMAL = re.compile(r"[+-]?[0-9]+\.[0-9]+\Z")
_SYMBOL = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


def _value_shape(value):
    """Report only a storage grammar class, never its raw text or card ID."""
    if value is None:
        return "null"
    if type(value) is int:
        return "integer"
    if type(value) is float:
        return "real"
    if isinstance(value, bytes):
        return "blob"
    if not isinstance(value, str):
        return "other_storage"
    if len(value) > 4096:
        return "oversized_text"
    value = value.strip()
    if not value:
        return "empty_text"
    if value[0] in "[{":
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return "non_json_bracket_text"
        return ("json_array" if isinstance(parsed, list) else
                "json_object" if isinstance(parsed, dict) else "other_text")
    if _INTEGER.fullmatch(value):
        return "text_integer"
    if _DECIMAL.fullmatch(value):
        return "text_decimal"
    if _SYMBOL.fullmatch(value):
        return "symbol_text"
    if "," in value:
        return "comma_text"
    if "|" in value:
        return "pipe_text"
    if ";" in value:
        return "semicolon_text"
    return "other_text"


def visible_capability_shapes(card_db_path, card_ids):
    """Only GRE-verified visible card IDs are queried. Aggregate counts only."""
    ids = sorted({x for x in card_ids if _card_id(x)})
    if len(ids) > 512:
        raise CardCatalogError("visible_card_id_limit")
    path = Path(card_db_path)
    if not path.is_file():
        raise CardCatalogError("catalog_file_unavailable")
    try:
        uri = path.resolve().as_uri() + "?mode=ro&immutable=1"
        with closing(sqlite3.connect(uri, uri=True, timeout=1)) as db:
            db.execute("PRAGMA query_only=ON")
            columns = {r[1] for r in db.execute('PRAGMA table_info("Cards")')}
            if not {"GrpId", "TitleId"} <= columns:
                raise CardCatalogError("catalog_schema_unsupported")
            selected = [name for name in _FIELDS if name in columns]
            counts = {name: Counter() for name in selected}
            seen, dupes, row_count = set(), set(), 0
            for start in range(0, len(ids), 200):
                batch = ids[start:start + 200]
                if not batch:
                    continue
                query = ('SELECT "GrpId"' +
                         "".join(', "' + col + '"' for col in selected) +
                         ' FROM "Cards" WHERE "GrpId" IN (' +
                         ",".join("?" for _ in batch) + ")")
                for record in db.execute(query, batch):
                    row_count += 1
                    if row_count > 4096:
                        raise CardCatalogError("catalog_row_limit")
                    gid = record[0]
                    if not _card_id(gid) or gid not in batch:
                        continue
                    if gid in seen:
                        dupes.add(gid)
                    seen.add(gid)
                    for name, value in zip(selected, record[1:]):
                        counts[name][_value_shape(value)] += 1
            return {
                "probe": "visible-card-capability-shapes-v1",
                "scope": "accepted_own_request_visible_card_ids_only",
                "distinct_visible_ids_requested": len(ids),
                "distinct_source_ids_found": len(seen),
                "ambiguous_source_ids": len(dupes),
                "card_rows_examined": row_count,
                "fields_missing_from_schema": [x for x in _FIELDS if x not in columns],
                "field_shapes": [
                    {"field": field, "shape_counts": dict(sorted(counts[field].items()))}
                    for field in selected
                ],
                "read_only": True, "source": "explicit_local_mtga_sqlite",
                "raw_values_exported": False, "raw_ids_exported": False,
                "field_semantics_verified": False, "mana_cost_verified": False,
                "abilities_decoded": False,
                "legal_actions": None, "actionable": False, "input_sent": False,
            }
    except (sqlite3.Error, OSError, OverflowError):
        raise CardCatalogError("catalog_unavailable_or_invalid") from None


def inspect(log_path, card_db_path, max_history_bytes=64 * 1024 * 1024,
            capability_shapes=False):
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
    result = {
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
    if capability_shapes:
        result["capability_shapes"] = visible_capability_shapes(
            card_db_path, visible_card_ids)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read-only, count-only MTGA card name coverage")
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--card-db", type=Path, required=True)
    parser.add_argument("--max-history-bytes", type=int, default=64 * 1024 * 1024)
    parser.add_argument("--capability-shapes", action="store_true",
                        help="MP12: aggregate storage shapes for visible cards only")
    args = parser.parse_args(argv)
    if not 1 <= args.max_history_bytes <= 1024 * 1024 * 1024:
        parser.error("max-history-bytes must be within 1 and 1073741824")
    try:
        result = inspect(args.log, args.card_db, args.max_history_bytes,
                         capability_shapes=args.capability_shapes)
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
