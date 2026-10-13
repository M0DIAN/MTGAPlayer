"""Opt-in, read-only card title lookup from an explicit local MTGA SQLite file.

This never reads private GRE objects: the caller passes only already-visible
card_id values. Titles are source metadata, not Magic rules or legal actions.
"""
from contextlib import closing
from pathlib import Path
import re
import sqlite3


_MAX_IDS = 512
_MAX_ROWS = 4096
_MAX_CARD_ID = 2**53 - 1
_SET = re.compile(r"[A-Za-z0-9_]{1,12}\Z")


class CardCatalogError(ValueError):
    """Safe, path-free local catalog error."""


def _card_id(value):
    return type(value) is int and 0 <= value <= _MAX_CARD_ID


def _label(value, limit):
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if (not 1 <= len(cleaned) <= limit or "<" in cleaned or ">" in cleaned or
            any(ord(char) < 32 or ord(char) == 127 for char in cleaned)):
        return None
    return cleaned


def _columns(connection, table):
    # Fixed, trusted names from this function; never SQL-interpolate user input.
    return {row[1] for row in connection.execute("PRAGMA table_info(" + table + ")")}


def lookup_local_titles(card_db_path, visible_card_ids):
    """Return (unique titles, ambiguous ids) without ever reading log objects.

    The MTGA local DB schema is checked before a parameterized lookup. A missing
    or duplicate title stays unresolved; no guessing by expansion, spelling,
    alternate face or card rules is performed.
    """
    ids = {i for i in visible_card_ids if _card_id(i)}
    if len(ids) > _MAX_IDS:
        raise CardCatalogError("visible_card_id_limit")
    if not ids:
        return {}, set()
    try:
        path = Path(card_db_path)
        if not path.is_file():
            raise CardCatalogError("catalog_file_unavailable")
        # Immutable read-only SQLite URI avoids journal/SHM writes to game files.
        uri = path.resolve().as_uri() + "?mode=ro&immutable=1"
        with closing(sqlite3.connect(uri, uri=True, timeout=1)) as connection:
            connection.execute("PRAGMA query_only=ON")
            tables = {row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            if "Cards" not in tables:
                raise CardCatalogError("catalog_schema_unsupported")
            cols = _columns(connection, "Cards")
            if not {"GrpId", "TitleId"} <= cols:
                raise CardCatalogError("catalog_schema_unsupported")
            if "Localizations_enUS" in tables and {
                    "LocId", "Loc"} <= _columns(connection, "Localizations_enUS"):
                table, name = "Localizations_enUS", "Loc"
            elif "Localizations" in tables and {
                    "LocId", "enUS"} <= _columns(connection, "Localizations"):
                table, name = "Localizations", "enUS"
            else:
                raise CardCatalogError("catalog_schema_unsupported")
            loc_cols = _columns(connection, table)
            formatted = " AND l.Formatted = 1" if "Formatted" in loc_cols else ""
            expansion = "c.ExpansionCode" if "ExpansionCode" in cols else "NULL"
            collector = "c.CollectorNumber" if "CollectorNumber" in cols else "NULL"
            sql = (
                "SELECT c.GrpId, l." + name + ", " + expansion + ", " + collector +
                " FROM Cards AS c JOIN " + table +
                " AS l ON c.TitleId = l.LocId WHERE c.GrpId IN ({})" + formatted)
            found, duplicates, seen = {}, set(), set()
            inspected = 0
            values = sorted(ids)
            for start in range(0, len(values), 200):
                group = values[start:start + 200]
                for grp, title, set_code, collector_no in connection.execute(
                        sql.format(",".join("?" for _ in group)), group):
                    inspected += 1
                    if inspected > _MAX_ROWS:
                        raise CardCatalogError("catalog_row_limit")
                    if not _card_id(grp) or grp not in ids:
                        continue
                    if grp in seen:
                        duplicates.add(grp)
                        found.pop(grp, None)
                        continue
                    seen.add(grp)
                    clean_name = _label(title, 180)
                    if clean_name is None:
                        continue
                    clean_set = (_label(set_code, 12)
                                 if isinstance(set_code, str) and _SET.fullmatch(set_code)
                                 else None)
                    clean_number = (_label(str(collector_no), 32)
                                    if type(collector_no) in (int, str) else None)
                    found[grp] = {
                        "name": clean_name, "set_code": clean_set,
                        "collector_number": clean_number,
                        "provenance": "explicit_local_mtga_sqlite",
                        "rules_verified": False,
                    }
            return found, duplicates
    except (sqlite3.Error, OSError, OverflowError) as exc:
        raise CardCatalogError("catalog_unavailable_or_invalid") from None


def enrich_visible_document(document, card_db_path):
    """Enrich only current already-visible objects, not stale/hidden history.

    Mutates only the passed output document, never RawReducer's source state.
    """
    current = document.get("current")
    if not isinstance(current, dict) or current.get("valid") is not True:
        return document
    objects = current.get("objects")
    if not isinstance(objects, list) or len(objects) > _MAX_IDS:
        raise CardCatalogError("visible_object_limit")
    titles, duplicates = lookup_local_titles(
        card_db_path, (o.get("card_id") for o in objects if isinstance(o, dict)))
    counts = {"resolved": 0, "unresolved": 0, "ambiguous": 0,
              "missing_card_id": 0}
    for obj in objects:
        if not isinstance(obj, dict):
            raise CardCatalogError("visible_object_invalid")
        grp = obj.get("card_id")
        if not _card_id(grp):
            status = "missing_card_id"
        elif grp in duplicates:
            status = "ambiguous"
        elif grp in titles:
            status = "resolved"
        else:
            status = "unresolved"
        counts[status] += 1
        card = {"status": status}
        if status == "resolved":
            card.update(titles[grp])
        obj["local_card"] = card
    current["card_catalog"] = {
        "source": "explicit_local_mtga_sqlite",
        "language": "enUS", "scope": "current_visible_objects_only",
        "visible_object_count": len(objects),
        "counts": counts,
        "card_names_are_metadata_only": True,
        "full_rules_verified": False, "legal_actions": None,
        "actionable": False, "input_sent": False,
    }
    return document
