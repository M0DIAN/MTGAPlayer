"""MP7: read-only, bounded ActionsAvailableReq schema evidence.

No identifiers, scalar values, raw messages, screenshots or actions are emitted.
This is a diagnostic probe, NOT a legality oracle.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import re

from mtgaplayer.raw_log import RawFollower


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


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Read-only schema probe; no action IDs, card IDs or prompt values leave the file")
    parser.add_argument("input", type=Path, help="explicit local Player.log path")
    parser.add_argument("--max-history-bytes", type=int, default=64 * 1024 * 1024)
    args = parser.parse_args(argv)
    if not 1 <= args.max_history_bytes <= 1024 * 1024 * 1024:
        parser.error("max-history-bytes must be between 1 and 1073741824")
    try:
        result = inspect(args.input, args.max_history_bytes)
    except (OSError, ValueError):
        print(json.dumps({"probe": "actions-available-schema-v1",
                          "error": "file_unavailable_or_history_limit",
                          "actionable": False, "input_sent": False}))
        return 1
    print(json.dumps(result, sort_keys=True, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
