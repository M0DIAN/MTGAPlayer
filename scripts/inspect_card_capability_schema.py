"""MP12 read-only capability SCHEMA evidence from an explicit local card catalog.

No card rows, rules text, identifiers, prices, names, file paths or GRE
records are read or printed. Schema column names are NOT card semantics.
"""
import argparse
from contextlib import closing
import json
from pathlib import Path
import re
import sqlite3

from mtgaplayer.card_catalog import CardCatalogError


_SAFE_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}\Z")
_RELATED_NAME = re.compile(
    r"Card|Ability|Mana|Cost|Spell|Effect|Type|Keyword|Target|Rule|Text|Localiz",
    re.IGNORECASE)
_MAX_TABLES = 4096
_MAX_OUTPUT_TABLES = 64
_MAX_COLUMNS = 160


def _affinity(declared):
    """SQLite storage affinity only, not the meaning of any game field."""
    if not isinstance(declared, str):
        return "unknown"
    label = declared.upper()
    if "INT" in label:
        return "integer"
    if any(token in label for token in ("CHAR", "CLOB", "TEXT")):
        return "text"
    if "BLOB" in label or not label:
        return "blob"
    if any(token in label for token in ("REAL", "FLOA", "DOUB")):
        return "real"
    return "numeric"


def inspect(card_db_path):
    """Return bounded schema metadata from Cards and related table NAMES."""
    path = Path(card_db_path)
    if not path.is_file():
        raise CardCatalogError("catalog_file_unavailable")
    try:
        uri = path.resolve().as_uri() + "?mode=ro&immutable=1"
        with closing(sqlite3.connect(uri, uri=True, timeout=1)) as db:
            db.execute("PRAGMA query_only=ON")
            names = [row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")]
            if len(names) > _MAX_TABLES:
                raise CardCatalogError("catalog_table_limit")
            if "Cards" not in names:
                raise CardCatalogError("catalog_schema_unsupported")
            columns = list(db.execute('PRAGMA table_info("Cards")'))
            if not {"GrpId", "TitleId"} <= {row[1] for row in columns}:
                raise CardCatalogError("catalog_schema_unsupported")

            displayed = []
            suppressed = 0
            for row in columns:
                name = row[1]
                if not isinstance(name, str) or not _SAFE_NAME.fullmatch(name):
                    suppressed += 1
                    continue
                if len(displayed) < _MAX_COLUMNS:
                    displayed.append({
                        "name": name,
                        "sqlite_affinity": _affinity(row[2]),
                        "declared_not_null": bool(row[3]),
                        "primary_key_member": bool(row[5]),
                    })

            table_names = [name for name in names
                           if isinstance(name, str)
                           and not name.lower().startswith("sqlite_")]
            related = sorted(
                name for name in table_names
                if _SAFE_NAME.fullmatch(name) and _RELATED_NAME.search(name))
            return {
                "probe": "mtga-card-capability-schema-v1",
                "catalog": {
                    "mode": "offline", "source": "explicit_local_mtga_sqlite",
                    "sqlite_query_only": True, "database_modified": False,
                    "game_data_copied": False, "row_values_read": False,
                    "identifiers_exported": False,
                    "card_names_exported": False,
                },
                "schema": {
                    "all_user_table_count": len(table_names),
                    "related_table_count": len(related),
                    "related_table_names": related[:_MAX_OUTPUT_TABLES],
                    "related_table_names_truncated": len(related) > _MAX_OUTPUT_TABLES,
                    "cards_column_count": len(columns),
                    "cards_columns": displayed,
                    "cards_columns_truncated": (len(columns) - suppressed >
                                                _MAX_COLUMNS),
                    "cards_column_names_suppressed": suppressed,
                    "field_semantics_verified": False,
                    "abilities_decoded": False,
                },
                "rules_verified": False, "legal_actions": None,
                "actionable": False, "input_sent": False,
                "executor_connected": False,
            }
    except (sqlite3.Error, OSError, OverflowError):
        raise CardCatalogError("catalog_unavailable_or_invalid") from None


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Read-only MTGA card schema inventory (never card values)")
    parser.add_argument("--card-db", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = inspect(args.card_db)
    except (CardCatalogError, OSError, ValueError):
        print(json.dumps({
            "probe": "mtga-card-capability-schema-v1",
            "error": "catalog_unavailable_or_unsupported",
            "rules_verified": False,
            "actionable": False, "input_sent": False,
        }, sort_keys=True))
        return 1
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
