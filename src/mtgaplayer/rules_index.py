"""Offline Scryfall reference data. No game rules, downloads or name fallback."""
import codecs
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
from uuid import UUID

VERSION = 'mtgaplayer.static-rules-index.v1'
MAX_CARD_ID = 9_007_199_254_740_991
_CHUNK = 65536
_MAX_RECORD = 1024 * 1024
_TEXT = ('oracle_text', 'type_line', 'mana_cost', 'power', 'toughness')


class RulesIndexError(ValueError):
    """Fixed, path-free failure; an incomplete import is never published."""


def _require(condition):
    if not condition:
        raise RulesIndexError('rules_data_invalid')


def _id(value):
    return type(value) is int and 0 <= value <= MAX_CARD_ID


def _text(value, limit=16384, nullable=True):
    _require(nullable and value is None or type(value) is str and len(value) <= limit)
    return value


def _uuid(value, nullable=False):
    if value is None and nullable:
        return None
    _require(type(value) is str and str(UUID(value)) == value)
    return value


def _strings(value):
    if value is None:
        return None
    _require(type(value) is list and len(value) <= 128)
    return [_text(item, 256, False) for item in value]


def _card(raw):
    _require(type(raw) is dict and raw.get('object') == 'card' and _id(raw.get('arena_id')))
    card = {key: _text(raw.get(key), 256, False) for key in ('name', 'lang', 'layout')}
    _require(all(card.values()) and type(raw.get('digital')) is bool)
    card.update(object='card', arena_id=raw['arena_id'], id=_uuid(raw.get('id')),
                oracle_id=_uuid(raw.get('oracle_id'), True), digital=raw['digital'])
    card.update({key: _text(raw.get(key)) for key in _TEXT})
    card.update({key: _strings(raw.get(key)) for key in ('colors', 'keywords')})
    faces = raw.get('card_faces', [])
    _require(type(faces) is list and len(faces) <= 8)
    card['card_faces'] = []
    for face in faces:
        _require(type(face) is dict)
        entry = {'name': _text(face.get('name'), 256, False),
                 'oracle_id': _uuid(face.get('oracle_id'), True)}
        _require(bool(entry['name']))
        entry.update({key: _text(face.get(key)) for key in _TEXT})
        entry['colors'] = _strings(face.get('colors'))
        card['card_faces'].append(entry)
    return card


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result)
        result[key] = value
    return result


def _constant(value):
    raise RulesIndexError('rules_data_invalid')


def _records(stream, digest):
    """Stream the documented JSON array without loading the bulk file at once."""
    decoder = json.JSONDecoder(object_pairs_hook=_pairs, parse_constant=_constant)
    utf8 = codecs.getincrementaldecoder('utf-8')()
    buffer, eof, total = '', False, 0

    def fill():
        nonlocal buffer, eof, total
        raw = stream.read(_CHUNK)
        total += len(raw)
        _require(total <= 2 * 1024 * 1024 * 1024)
        digest.update(raw)
        eof = not raw
        buffer += utf8.decode(raw, final=eof)

    def space():
        nonlocal buffer
        buffer = buffer.lstrip(' \t\r\n')
        while not buffer and not eof:
            fill()
            buffer = buffer.lstrip(' \t\r\n')

    space()
    _require(buffer.startswith('['))
    buffer = buffer[1:]
    space()
    first = True
    while not buffer.startswith(']') or not first:
        while True:
            _require(len(buffer) <= _MAX_RECORD)
            try:
                value, end = decoder.raw_decode(buffer)
                break
            except json.JSONDecodeError:
                _require(not eof)
                fill()
        _require(end <= _MAX_RECORD)
        yield value
        buffer = buffer[end:]
        space()
        _require(bool(buffer))
        if buffer[0] == ']':
            break
        _require(buffer[0] == ',')
        buffer = buffer[1:]
        space()
        first = False  # A closing bracket here would be a trailing comma.
    _require(buffer.startswith(']'))
    buffer = buffer[1:]
    space()
    _require(eof and not buffer)


def build_rules_index(source_path, output_path, *, source_version):
    """Create a NEW index. Use a new versioned path for each update."""
    _require(type(source_version) is str and 1 <= len(source_version) <= 128 and
             all(ord(c) >= 32 for c in source_version))
    output = Path(output_path)
    temporary = None
    if output.exists():
        raise RulesIndexError('rules_index_exists')
    try:
        descriptor, name = tempfile.mkstemp(prefix='.rules-', suffix='.sqlite', dir=output.parent)
        os.close(descriptor)
        temporary = Path(name)
        digest = hashlib.sha256()
        total, no_arena = 0, 0
        with closing(sqlite3.connect(temporary)) as db, db:
            db.execute('CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
            db.execute('CREATE TABLE cards (arena_id INTEGER PRIMARY KEY, occurrences INTEGER NOT NULL, card_json TEXT)')
            with open(source_path, 'rb') as stream:
                for raw in _records(stream, digest):
                    total += 1
                    _require(total <= 1_000_000 and type(raw) is dict and raw.get('object') == 'card')
                    if raw.get('arena_id') is None:
                        no_arena += 1
                        continue
                    card = _card(raw)
                    db.execute('INSERT INTO cards VALUES (?,1,?) ON CONFLICT(arena_id) DO UPDATE '
                               'SET occurrences=occurrences+1, card_json=NULL',
                               (card['arena_id'], json.dumps(card, ensure_ascii=False, sort_keys=True)))
            unique, ambiguous = db.execute('SELECT COALESCE(SUM(occurrences=1),0), '
                                          'COALESCE(SUM(occurrences>1),0) FROM cards').fetchone()
            metadata = {'schema_version': VERSION, 'source_format': 'scryfall_card_json_array',
                'source_version': source_version, 'source_sha256': digest.hexdigest(),
                'source_version_is_user_supplied': True, 'card_records': total,
                'records_without_arena_id': no_arena, 'unique_arena_ids': unique,
                'ambiguous_arena_ids': ambiguous}
            db.executemany('INSERT INTO metadata VALUES (?,?)',
                           ((k, json.dumps(v)) for k, v in metadata.items()))
        # Atomic create-if-absent: never overwrite an existing good index,
        # including a file created by another process during the import.
        os.link(temporary, output)
        return {**metadata, 'read_only': True, 'input_sent': False}
    except FileExistsError:
        raise RulesIndexError('rules_index_exists') from None
    except (OSError, sqlite3.Error, ValueError, TypeError, RecursionError) as exc:
        if isinstance(exc, RulesIndexError):
            raise
        raise RulesIndexError('rules_import_unavailable_or_invalid') from None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def lookup_rules(index_path, arena_ids):
    """Read exact IDs only. Duplicate IDs never resolve, even identical rows."""
    values = list(arena_ids)
    _require(len(values) <= 512 and all(_id(value) for value in values))
    ids = set(values)
    try:
        path = Path(index_path)
        if not path.is_file():
            raise RulesIndexError('rules_index_unavailable_or_invalid')
        with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro&immutable=1', uri=True)) as db:
            metadata = {key: json.loads(value) for key, value in db.execute('SELECT key,value FROM metadata')}
            _require(metadata.get('schema_version') == VERSION and
                     metadata.get('source_format') == 'scryfall_card_json_array' and
                     metadata.get('source_version_is_user_supplied') is True and
                     type(metadata.get('source_version')) is str and
                     type(metadata.get('source_sha256')) is str and
                     re.fullmatch('[0-9a-f]{64}', metadata['source_sha256']) is not None)
            result = {value: {'status': 'unresolved', 'card': None} for value in ids}
            values = sorted(ids)
            for start in range(0, len(values), 200):
                group = values[start:start + 200]
                for arena, count, raw in db.execute('SELECT arena_id,occurrences,card_json FROM cards '
                        'WHERE arena_id IN (' + ','.join('?' for _ in group) + ')', group):
                    _require(_id(arena) and arena in ids and type(count) is int and count >= 1)
                    if count > 1:
                        _require(raw is None)
                        result[arena] = {'status': 'ambiguous', 'card': None}
                    else:
                        _require(type(raw) is str and len(raw) <= _MAX_RECORD)
                        card = _card(json.loads(raw, object_pairs_hook=_pairs, parse_constant=_constant))
                        _require(card['arena_id'] == arena)
                        result[arena] = {'status': 'resolved', 'card': card}
            return metadata, result
    except (OSError, sqlite3.Error, ValueError, TypeError, RecursionError):
        raise RulesIndexError('rules_index_unavailable_or_invalid') from None
