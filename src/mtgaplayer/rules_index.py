"""Offline Scryfall reference data. No game rules, downloads or name fallback."""
import codecs
from contextlib import closing
import copy
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
DEFAULT_MAX_CARDS = 100_000
DEFAULT_MAX_JSON_BYTES = 64 * 1024 * 1024


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


def _lookup_ids(arena_ids):
    values = list(arena_ids)
    _require(len(values) <= 512 and all(_id(value) for value in values))
    return set(values)


def _read_metadata(db):
    metadata = {}
    for key, raw in db.execute('SELECT key,value FROM metadata'):
        _require(len(metadata) < 9 and type(key) is str and key not in metadata and
                 type(raw) is str and len(raw) <= 4096)
        metadata[key] = json.loads(raw, object_pairs_hook=_pairs, parse_constant=_constant)
    _require(set(metadata) == {'schema_version', 'source_format', 'source_version',
        'source_sha256', 'source_version_is_user_supplied', 'card_records',
        'records_without_arena_id', 'unique_arena_ids', 'ambiguous_arena_ids'})
    _require(metadata['schema_version'] == VERSION and
             metadata['source_format'] == 'scryfall_card_json_array' and
             metadata['source_version_is_user_supplied'] is True and
             type(metadata['source_version']) is str and 1 <= len(metadata['source_version']) <= 128 and
             all(ord(c) >= 32 for c in metadata['source_version']) and
             type(metadata['source_sha256']) is str and
             re.fullmatch('[0-9a-f]{64}', metadata['source_sha256']) is not None)
    _require(all(type(metadata[k]) is int and 0 <= metadata[k] <= 1_000_000 for k in
                 ('card_records', 'records_without_arena_id', 'unique_arena_ids', 'ambiguous_arena_ids')))
    return metadata


def _read_card(arena, count, raw):
    _require(_id(arena) and type(count) is int and 1 <= count <= 1_000_000)
    if count > 1:
        _require(raw is None)
        return {'status': 'ambiguous', 'card': None}
    _require(type(raw) is str and len(raw) <= _MAX_RECORD)
    card = _card(json.loads(raw, object_pairs_hook=_pairs, parse_constant=_constant))
    _require(card['arena_id'] == arena)
    return {'status': 'resolved', 'card': card}


class PreparedRulesIndex:
    """A source-fixed reference snapshot, created only by load_rules_index.

    Queries perform no filesystem/SQLite operations and return detached data.
    The encoded-payload budget is not a Python heap/RSS bound.
    """
    __slots__ = ('_metadata', '_cards')

    def __init__(self, metadata, cards):
        self._metadata, self._cards = metadata, cards

    def lookup(self, arena_ids):
        ids = _lookup_ids(arena_ids)
        return copy.deepcopy((self._metadata, {arena: self._cards.get(arena,
            {'status': 'unresolved', 'card': None}) for arena in ids}))


def load_rules_index(index_path, *, max_cards=DEFAULT_MAX_CARDS,
                     max_json_bytes=DEFAULT_MAX_JSON_BYTES):
    """Prepare once before starting a subscription; never reload implicitly.

    Bound indexed IDs and encoded JSON bytes before loading card payloads.
    Validate the complete index; an invalid late row cannot publish a prefix.
    """
    _require(type(max_cards) is int and 1 <= max_cards <= 1_000_000 and
             type(max_json_bytes) is int and 1 <= max_json_bytes <= 1024 * 1024 * 1024)
    try:
        path = Path(index_path)
        _require(path.is_file())
        with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro&immutable=1', uri=True)) as db:
            rows, card_bytes = db.execute('SELECT COUNT(*), '
                'COALESCE(SUM(length(CAST(card_json AS BLOB))),0) FROM cards').fetchone()
            meta_bytes = db.execute('SELECT COALESCE(SUM(length(CAST(value AS BLOB))),0) FROM metadata').fetchone()[0]
            if rows > max_cards or card_bytes + meta_bytes > max_json_bytes:
                raise RulesIndexError('rules_index_limits_exceeded')
            metadata = _read_metadata(db)
            cards, occurrences, ambiguous = {}, 0, 0
            for arena, count, raw in db.execute('SELECT arena_id,occurrences,card_json FROM cards'):
                _require(arena not in cards)
                cards[arena] = _read_card(arena, count, raw)
                occurrences += count
                ambiguous += count > 1
            _require(len(cards) == rows and metadata['unique_arena_ids'] == rows - ambiguous and
                     metadata['ambiguous_arena_ids'] == ambiguous and
                     metadata['card_records'] == occurrences + metadata['records_without_arena_id'])
        return PreparedRulesIndex(metadata, cards)
    except (OSError, sqlite3.Error, ValueError, TypeError, RecursionError) as exc:
        if isinstance(exc, RulesIndexError) and str(exc) == 'rules_index_limits_exceeded':
            raise
        raise RulesIndexError('rules_index_unavailable_or_invalid') from None


def lookup_rules(index_path, arena_ids):
    """Read exact IDs only. Duplicate IDs never resolve, even identical rows."""
    ids = _lookup_ids(arena_ids)
    try:
        path = Path(index_path)
        if not path.is_file():
            raise RulesIndexError('rules_index_unavailable_or_invalid')
        with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro&immutable=1', uri=True)) as db:
            metadata = _read_metadata(db)
            result = {value: {'status': 'unresolved', 'card': None} for value in ids}
            values = sorted(ids)
            for start in range(0, len(values), 200):
                group = values[start:start + 200]
                for arena, count, raw in db.execute('SELECT arena_id,occurrences,card_json FROM cards '
                        'WHERE arena_id IN (' + ','.join('?' for _ in group) + ')', group):
                    _require(arena in ids)
                    result[arena] = _read_card(arena, count, raw)
            return metadata, result
    except (OSError, sqlite3.Error, ValueError, TypeError, RecursionError):
        raise RulesIndexError('rules_index_unavailable_or_invalid') from None
