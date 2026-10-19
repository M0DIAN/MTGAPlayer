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
    __slots__ = ('_metadata', '_cards', '_reference_bytes')

    def __init__(self, metadata, cards):
        self._metadata, self._cards = metadata, cards
        self._reference_bytes = {arena: len(json.dumps(match['card'], ensure_ascii=False).encode('utf-8'))
                                 if match['card'] is not None else 0 for arena, match in cards.items()}

    def lookup(self, arena_ids, *, max_reference_bytes=None):
        values = list(arena_ids)
        ids = _lookup_ids(values)
        if max_reference_bytes is not None:
            _require(type(max_reference_bytes) is int and 0 <= max_reference_bytes <= DEFAULT_MAX_JSON_BYTES)
            # Repeated IDs represent repeated visible instances in a sidecar.
            # Reject before deepcopy, rather than constructing an oversized result.
            if sum(self._reference_bytes.get(arena, 0) for arena in values) > max_reference_bytes:
                raise RulesIndexError('rules_context_limits_exceeded')
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


# This is a second explicit *source format* for the same prepared reference
# container, not a Scryfall conversion. No printing/Oracle IDs are invented.
MTGA_LAND_VERSION = 'mtgaplayer.mtga-land-reference.v1'
MTGA_LAND_FORMAT = 'mtga_official_sqlite_card_metadata'
MTGA_PROFILE_FIELDS = ('Types', 'Supertypes', 'Subtypes', 'TypeTextId', 'SubtypeTextId',
    'OldSchoolManaText', 'LinkedFaceType', 'LinkedFaceGrpIds', 'LinkedAbilityTemplateCardGrpIds',
    'IsToken', 'IsPrimaryCard', 'IsDigitalOnly', 'IsRebalanced', 'RebalancedCardGrpId',
    'DefunctRebalancedCardGrpId', 'RawFrameDetail', 'AdditionalFrameDetails', 'ExtraFrameDetails',
    'TextChangeData', 'AbilityIds', 'HiddenAbilityIds')


def _file_sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(_CHUNK), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _catalog_numbers(value):
    _require(type(value) is str and len(value) <= 16384)
    if not value:
        return []
    _require(re.fullmatch(r'[0-9]+(?:,[0-9]+)*', value) is not None)
    values = [int(item) for item in value.split(',')]
    _require(len(values) <= 512 and all(_id(item) for item in values) and
             len(set(values)) == len(values))
    return values


def prepare_mtga_land_reference(db_path, arena_ids, *, expected_sha256, expected_source_version):
    """Prepare a bounded, exact-ID official catalog metadata subset, offline.

    The explicit hash and literal Data/GRP versions pin the owner's reviewed
    source. Queries close before publication; subsequent lookups do no I/O.
    This metadata does not establish current card characteristics or legality.
    """
    ids = _lookup_ids(arena_ids)
    _require(type(expected_sha256) is str and re.fullmatch('[0-9a-f]{64}', expected_sha256) is not None)
    _require(type(expected_source_version) is dict and set(expected_source_version) == {'Data', 'GRP'} and
             all(type(value) is str and re.fullmatch(r'[0-9.]{1,80}', value) is not None
                 for value in expected_source_version.values()))
    try:
        path = Path(db_path).resolve()
        before = path.stat()
        _require(path.is_file() and 0 < before.st_size <= 512 * 1024 * 1024)
        _require(_file_sha256(path) == expected_sha256)
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro&immutable=1', uri=True)) as db:
            db.execute('PRAGMA query_only=ON')
            db.row_factory = sqlite3.Row
            required = {'Cards': {'GrpId', *MTGA_PROFILE_FIELDS},
                'Enums': {'Type', 'Value', 'LocId'}, 'Localizations_enUS': {'LocId', 'Formatted', 'Loc'},
                'Versions': {'Type', 'Version'}}
            for table, columns in required.items():
                actual = {row[1]: row[2].upper() for row in db.execute('PRAGMA table_info(' + table + ')')}
                _require(columns <= actual.keys())
                integer = {'GrpId', 'TypeTextId', 'SubtypeTextId', 'LinkedFaceType', 'IsToken',
                    'IsPrimaryCard', 'IsDigitalOnly', 'IsRebalanced', 'RebalancedCardGrpId',
                    'DefunctRebalancedCardGrpId', 'Value', 'LocId', 'Formatted'}
                flags = {'IsToken', 'IsPrimaryCard', 'IsDigitalOnly', 'IsRebalanced'}
                _require(all(actual[key] in (('INT', 'INTEGER', 'BOOLEAN') if key in flags else
                    ('INT', 'INTEGER') if key in integer else ('TEXT',)) for key in columns))
            versions = db.execute('SELECT Type,Version FROM Versions LIMIT 33').fetchall()
            _require(len(versions) == 2 and all(type(row['Type']) is str and type(row['Version']) is str for row in versions))
            source_versions = {row['Type']: row['Version'] for row in versions}
            _require(len(source_versions) == 2 and source_versions == expected_source_version)
            total = db.execute('SELECT COUNT(*) FROM Cards').fetchone()[0]
            _require(type(total) is int and 0 <= total <= DEFAULT_MAX_CARDS)

            def localized(loc_id):
                _require(_id(loc_id))
                rows = db.execute('SELECT LocId,Formatted,Loc FROM Localizations_enUS WHERE LocId=? LIMIT 3', (loc_id,)).fetchall()
                _require(len(rows) == 1 and type(rows[0]['LocId']) is int and rows[0]['LocId'] == loc_id and
                         type(rows[0]['Formatted']) is int and rows[0]['Formatted'] == 1)
                return _text(rows[0]['Loc'], 256, False)

            def terms(kind, raw):
                result = []
                for value in _catalog_numbers(raw):
                    rows = db.execute('SELECT Type,Value,LocId FROM Enums WHERE Type=? AND Value=? LIMIT 3', (kind, value)).fetchall()
                    _require(len(rows) == 1 and rows[0]['Type'] == kind and type(rows[0]['Value']) is int and rows[0]['Value'] == value)
                    result.append({'value': value, 'loc_id': rows[0]['LocId'], 'label': localized(rows[0]['LocId'])})
                return result

            cards = {}; selected_rows = 0; ambiguous = 0
            for arena in sorted(ids):
                rows = db.execute('SELECT GrpId,' + ','.join(MTGA_PROFILE_FIELDS) + ' FROM Cards WHERE GrpId=? LIMIT 4097', (arena,)).fetchall()
                _require(len(rows) <= 4096)
                selected_rows += len(rows)
                if len(rows) != 1:
                    cards[arena] = {'status': 'ambiguous' if rows else 'unresolved', 'card': None}
                    ambiguous += bool(rows)
                    continue
                row = dict(rows[0]); _require(type(row.pop('GrpId')) is int)
                for key, value in row.items():
                    if key in ('TypeTextId', 'SubtypeTextId', 'LinkedFaceType', 'RebalancedCardGrpId', 'DefunctRebalancedCardGrpId'):
                        _require(_id(value))
                    elif key in ('IsToken', 'IsPrimaryCard', 'IsDigitalOnly', 'IsRebalanced'):
                        _require(type(value) is int and value in (0, 1))
                    else:
                        _text(value, 16384, False)
                # The empty links are literal source facts. A reverse link
                # prevents the narrow unlinked profile even if this row omits it.
                reverse = db.execute("SELECT GrpId FROM Cards WHERE instr(',' || COALESCE(LinkedFaceGrpIds,'') || ',', ?) > 0 LIMIT 2",
                                     (',' + str(arena) + ',',)).fetchall()
                card = {'schema_version': MTGA_LAND_VERSION, 'card_id': arena,
                    'type_line': localized(row['TypeTextId']), 'card_types': terms('CardType', row['Types']),
                    'supertypes': terms('SuperType', row['Supertypes']), 'subtypes': terms('SubType', row['Subtypes']),
                    'profile': row, 'reverse_face_link_observed': bool(reverse),
                    'current_face': None, 'effective_in_game': False, 'rules_verified': False}
                _catalog_numbers(row['LinkedFaceGrpIds'])
                _catalog_numbers(row['LinkedAbilityTemplateCardGrpIds'])
                cards[arena] = {'status': 'resolved', 'card': card}
        after = path.stat()
        _require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) ==
                 (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) and _file_sha256(path) == expected_sha256)
        metadata = {'schema_version': MTGA_LAND_VERSION, 'source_format': MTGA_LAND_FORMAT,
            'source_version': 'Data=' + source_versions['Data'] + ';GRP=' + source_versions['GRP'],
            'source_sha256': expected_sha256, 'source_version_is_user_supplied': False,
            'card_records': selected_rows, 'records_without_arena_id': 0,
            'unique_arena_ids': sum(item['status'] == 'resolved' for item in cards.values()),
            'ambiguous_arena_ids': ambiguous}
        return PreparedRulesIndex(metadata, cards)
    except (OSError, sqlite3.Error, ValueError, TypeError, RecursionError, KeyError, OverflowError):
        raise RulesIndexError('mtga_land_reference_unavailable_or_invalid') from None


MTGA_TARGET_EFFECT_VERSION = 'mtgaplayer.mtga-target-effect-reference.v1'
MTGA_TARGET_EFFECT_FORMAT = 'mtga_official_sqlite_target_effect_metadata'
TARGET_EFFECT_SHA256 = '1be0105411ad989ca60e233f1341eaaa9276e3a679c89f1ef6f07e07ede10d25'
TARGET_EFFECT_VERSIONS = {'Data': '2026.64.0.280', 'GRP': '280.1327372'}
_ABILITY_INTS = ('Id', 'BaseId', 'BaseIdNumeral', 'FakeBaseIdNumeral', 'TextId', 'Category',
    'SubCategory', 'AbilityWord', 'NumericAid', 'RequiresConfirmation', 'PaymentType',
    'FullyParsed', 'IsIntrinsicAbility')
_ABILITY_NULLS = ('OldSchoolManaText', 'LoyaltyCost', 'LevelRequirement', 'Power', 'Toughness',
    'MiscellaneousTerms', 'EmbeddedActiveAbilityIds', 'EmbeddedIntoAbilityIds', 'HiddenAbilityIds',
    'HiddenByAbilityIds', 'ReferencedAbilityIds', 'ReferencedKeywordNumerals', 'ReferencedAbilityTypes',
    'ModalChildIds', 'ModalParentIds', 'CostTypes', 'Tags', 'ReferencedAbilityManaText')
_EFFECT_TEXT = {
    839352: 'When CARDNAME enters, it deals 2 damage to any target.',
    943760: 'When this artifact enters, it deals 2 damage to any target.',
    1055993: 'When CARDNAME leaves the battlefield, it deals 2 damage to any target.',
    1055994: 'When this token leaves the battlefield, it deals 2 damage to any target.',
    757065: '{o2}, {oT}, Sacrifice another artifact: Create a 3/3 colorless Golem artifact creature token.',
    1055995: 'Whenever a nontoken artifact you control enters, create a colorless artifact token named Munitions with "When this token leaves the battlefield, it deals 2 damage to any target."',
}


def _effect_localization(ident):
    return {'LocId': ident, 'Formatted': 1, 'Loc': _EFFECT_TEXT[ident]}


def _expected_target_effect_card(arena):
    """Literal reviewed native rows, not a general card-text rules interpreter."""
    _require(arena in (90673, 96854) and type(arena) is int)
    token = arena == 96854
    profile = {'GrpId': arena, 'TitleId': 1056259 if token else 757062,
        'Types': '1', 'Supertypes': '', 'Subtypes': '', 'TypeTextId': 262981 if token else 7,
        'SubtypeTextId': 0, 'OldSchoolManaText': '' if token else 'o1oR', 'LinkedFaceType': 0,
        'LinkedFaceGrpIds': '', 'LinkedAbilityTemplateCardGrpIds': '',
        'IsToken': int(token), 'IsPrimaryCard': int(not token), 'IsDigitalOnly': 0, 'IsRebalanced': 0,
        'RebalancedCardGrpId': 0, 'DefunctRebalancedCardGrpId': 0, 'RawFrameDetail': '',
        'AdditionalFrameDetails': '', 'ExtraFrameDetails': '', 'TextChangeData': '',
        'AbilityIds': '191026:1055994' if token else '1553:943760,172054:757065', 'HiddenAbilityIds': ''}
    definitions = []
    for ident in ((191026, 191027) if token else (1553, 172054)):
        row = {key: 0 for key in _ABILITY_INTS}
        row.update(dict.fromkeys(_ABILITY_NULLS))
        row.update(Id=ident, TextId={1553:839352, 172054:757065, 191026:1055993, 191027:1055995}[ident],
            Category=1 if ident == 172054 else 2, SubCategory=10 if ident == 1553 else 0, FullyParsed=1)
        if ident == 172054: row.update(OldSchoolManaText='o2', RequiresConfirmation=6, PaymentType=1, CostTypes='2,4')
        if ident == 191026: row['HiddenByAbilityIds'] = '191027'
        if ident == 191027: row['HiddenAbilityIds'] = '191026'
        definitions.append({'row': row, 'generic_text': _effect_localization(row['TextId'])})
    specific = ([(191026,1055994)] if token else [(1553,943760),(172054,757065)])
    return {'schema_version': MTGA_TARGET_EFFECT_VERSION, 'card_id': arena, 'profile': profile,
        'ability_definitions': definitions,
        'specific_ability_texts': [{'ability_id': ability, 'text': _effect_localization(text)} for ability,text in specific],
        'base_effect_instruction': {'ability_id': 191026 if token else 1553,
            'category': 'fixed_base_damage', 'base_damage': 2,
            'trigger': 'leaves_battlefield' if token else 'enters', 'target_text_scope': 'any_target'},
        'effective_in_game': False, 'complete_legality_verified': False}


def reviewed_target_effect(card, ability_id):
    """Revalidate detached reference data before using its finite instruction."""
    _require(type(card) is dict and type(card.get('card_id')) is int and card['card_id'] in (90673,96854))
    expected = _expected_target_effect_card(card['card_id'])
    _require(json.dumps(card,sort_keys=True,ensure_ascii=False) == json.dumps(expected,sort_keys=True,ensure_ascii=False))
    _require(type(ability_id) is int and ability_id == expected['base_effect_instruction']['ability_id'])
    return copy.deepcopy(expected['base_effect_instruction'])


def prepare_mtga_target_effect_reference(db_path, arena_ids, *, expected_sha256, expected_source_version):
    """Prepare the two version-pinned, reviewed base-damage definitions offline.

    Preserve exact ability IDs, generic and card-specific texts, and the distinct
    cost/creator definitions. This source cannot certify current effective damage.
    No database, filesystem or text interpretation occurs during policy lookup.
    """
    ids = _lookup_ids(arena_ids)
    _require(ids <= {90673,96854} and expected_sha256 == TARGET_EFFECT_SHA256 and
        type(expected_sha256) is str and type(expected_source_version) is dict and
        expected_source_version == TARGET_EFFECT_VERSIONS and
        all(type(k) is str and type(v) is str for k,v in expected_source_version.items()))
    try:
        path = Path(db_path).resolve(); before = path.stat()
        _require(path.is_file() and 0 < before.st_size <= 512*1024*1024 and _file_sha256(path) == expected_sha256)
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro&immutable=1',uri=True)) as db:
            db.execute('PRAGMA query_only=ON'); db.row_factory = sqlite3.Row
            required = {'Cards': {'GrpId','TitleId',*MTGA_PROFILE_FIELDS},
                'Abilities': {*_ABILITY_INTS,*_ABILITY_NULLS},
                'Localizations_enUS': {'LocId','Formatted','Loc'}, 'Versions': {'Type','Version'}}
            integers = {'GrpId','TitleId','TypeTextId','SubtypeTextId','LinkedFaceType','IsToken','IsPrimaryCard',
                'IsDigitalOnly','IsRebalanced','RebalancedCardGrpId','DefunctRebalancedCardGrpId','LocId','Formatted',*_ABILITY_INTS}
            flags = {'IsToken','IsPrimaryCard','IsDigitalOnly','IsRebalanced','FullyParsed','IsIntrinsicAbility'}
            for table,columns in required.items():
                actual = {r[1]:r[2].upper() for r in db.execute('PRAGMA table_info('+table+')')}
                _require(columns <= actual.keys() and all(actual[k] in
                    (('INT','INTEGER','BOOLEAN') if k in flags else ('INT','INTEGER') if k in integers else ('TEXT',)) for k in columns))
            versions = db.execute('SELECT Type,Version FROM Versions LIMIT 3').fetchall()
            _require(len(versions)==2 and all(type(r['Type']) is str and type(r['Version']) is str for r in versions) and
                {r['Type']:r['Version'] for r in versions} == TARGET_EFFECT_VERSIONS)
            def localized(ident):
                rows = db.execute('SELECT LocId,Formatted,Loc FROM Localizations_enUS WHERE LocId=? LIMIT 2',(ident,)).fetchall()
                _require(len(rows)==1)
                return dict(rows[0])
            cards = {}
            for arena in sorted(ids):
                expected = _expected_target_effect_card(arena)
                rows = db.execute('SELECT '+','.join(expected['profile'])+' FROM Cards WHERE GrpId=? LIMIT 2',(arena,)).fetchall()
                _require(len(rows)==1)
                actual = copy.deepcopy(expected); actual['profile'] = dict(rows[0])
                for definition in actual['ability_definitions']:
                    ident = definition['row']['Id']
                    rows = db.execute('SELECT '+','.join(definition['row'])+' FROM Abilities WHERE Id=? LIMIT 2',(ident,)).fetchall()
                    _require(len(rows)==1); definition['row'] = dict(rows[0])
                    definition['generic_text'] = localized(definition['row']['TextId'])
                for specific in actual['specific_ability_texts']:
                    specific['text'] = localized(specific['text']['LocId'])
                # JSON distinguishes integers from bools/floats; all literal
                # fields including modes, costs and hidden/parent links matter.
                reviewed_target_effect(actual, expected['base_effect_instruction']['ability_id'])
                cards[arena] = {'status':'resolved','card':actual}
        _require(_file_sha256(path)==expected_sha256)
        after=path.stat()
        _require((before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns)==
            (after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns))
        return PreparedRulesIndex({'schema_version':MTGA_TARGET_EFFECT_VERSION,'source_format':MTGA_TARGET_EFFECT_FORMAT,
            'source_version':'Data=2026.64.0.280;GRP=280.1327372','source_sha256':expected_sha256,
            'source_version_is_user_supplied':False,'card_records':len(cards),'records_without_arena_id':0,
            'unique_arena_ids':len(cards),'ambiguous_arena_ids':0},cards)
    except (OSError,sqlite3.Error,ValueError,TypeError,RecursionError,KeyError,OverflowError):
        raise RulesIndexError('mtga_target_effect_reference_unavailable_or_invalid') from None


MTGA_CARDFLOW_VERSION = 'mtgaplayer.mtga-cardflow-reference.v1'
MTGA_CARDFLOW_FORMAT = 'mtga_official_sqlite_conditional_cardflow_metadata'


def _expected_cardflow_card():
    """One reviewed native profile; neither a text parser nor effective rules."""
    profile = dict.fromkeys(MTGA_PROFILE_FIELDS, '')
    profile.update(Types='1', TypeTextId=7, SubtypeTextId=0, OldSchoolManaText='o1oU',
        LinkedFaceType=0, IsToken=0, IsPrimaryCard=1, IsDigitalOnly=0, IsRebalanced=0,
        RebalancedCardGrpId=0, DefunctRebalancedCardGrpId=0,
        AbilityIds='190898:1055624,190899:1055625')
    definitions = []
    for ident, generic, specific, text, specific_text in (
        (190898, 1055623, 1055624,
         'When CARDNAME enters or leaves the battlefield, draw a card.',
         'When this artifact enters or leaves the battlefield, draw a card.'),
        (190899, 1092, 1055625,
         '{o1oU}, Sacrifice CARDNAME: Put a stun counter on up to one target tapped creature.',
         '{o1oU}, Sacrifice this artifact: Put a stun counter on up to one target tapped creature.')):
        row = dict.fromkeys(_ABILITY_INTS, 0)
        row.update(dict.fromkeys(_ABILITY_NULLS))
        row.update(Id=ident, TextId=generic, Category=2 if ident == 190898 else 1,
            SubCategory=10 if ident == 190898 else 0, FullyParsed=1)
        if ident == 190899:
            row.update(OldSchoolManaText='o1oU', RequiresConfirmation=5,
                MiscellaneousTerms='25', CostTypes='4')
        definitions.append({'row': row,
            'generic_text': {'LocId': generic, 'Formatted': 1, 'Loc': text},
            'specific_text': {'LocId': specific, 'Formatted': 1, 'Loc': specific_text}})
    return {'schema_version': MTGA_CARDFLOW_VERSION, 'card_id': 96626, 'profile': profile,
        'ability_definitions': definitions,
        'conditional_instruction': {'ability_id': 190898, 'category': 'conditional_card_flow',
            'trigger_events': ['enters_battlefield', 'leaves_battlefield'],
            'base_cards_drawn_per_trigger': 1, 'researched_branch': 'prospective_enters_only',
            'cast_direct_draw': False, 'leaves_branch_counted_as_cast_benefit': False},
        'effective_in_game': False, 'complete_legality_verified': False}


def reviewed_cast_cardflow(card):
    """Recheck exact detached definition, including the distinct activated ability."""
    expected = _expected_cardflow_card()
    _require(json.dumps(card, sort_keys=True, ensure_ascii=False) ==
        json.dumps(expected, sort_keys=True, ensure_ascii=False))
    return copy.deepcopy(expected['conditional_instruction'])


def prepare_mtga_cardflow_reference(db_path, arena_ids, *, expected_sha256, expected_source_version):
    """Explicit offline preparation; reuse native metadata and the prepared container.

    Only two ability rows and four localizations supplement the existing metadata
    loader. Current policy lookups perform no file, database or text interpretation.
    """
    ids = _lookup_ids(arena_ids)
    _require(ids == {96626} and type(expected_sha256) is str and expected_sha256 == TARGET_EFFECT_SHA256 and
        expected_source_version == TARGET_EFFECT_VERSIONS and type(expected_source_version) is dict and
        all(type(k) is str and type(v) is str for k, v in expected_source_version.items()))
    try:
        base = prepare_mtga_land_reference(db_path, ids, expected_sha256=expected_sha256,
            expected_source_version=expected_source_version)
        metadata, found = base.lookup(ids)
        expected = _expected_cardflow_card()
        _require(found[96626]['status'] == 'resolved' and
            json.dumps(found[96626]['card']['profile'], sort_keys=True) == json.dumps(expected['profile'], sort_keys=True) and
            found[96626]['card']['reverse_face_link_observed'] is False)
        path = Path(db_path).resolve(); before = path.stat()
        _require(_file_sha256(path) == expected_sha256)
        actual = copy.deepcopy(expected)
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro&immutable=1', uri=True)) as db:
            db.execute('PRAGMA query_only=ON'); db.row_factory = sqlite3.Row
            for definition in actual['ability_definitions']:
                rows = db.execute('SELECT '+','.join(definition['row'])+
                    ' FROM Abilities WHERE Id=? LIMIT 2', (definition['row']['Id'],)).fetchall()
                _require(len(rows) == 1); definition['row'] = dict(rows[0])
                for key in ('generic_text', 'specific_text'):
                    rows = db.execute('SELECT LocId,Formatted,Loc FROM Localizations_enUS WHERE LocId=? LIMIT 2',
                        (definition[key]['LocId'],)).fetchall()
                    _require(len(rows) == 1); definition[key] = dict(rows[0])
        reviewed_cast_cardflow(actual)
        after = path.stat()
        _require(_file_sha256(path) == expected_sha256 and
            (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns) ==
            (after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns))
        metadata.update(schema_version=MTGA_CARDFLOW_VERSION, source_format=MTGA_CARDFLOW_FORMAT)
        return PreparedRulesIndex(metadata, {96626: {'status': 'resolved', 'card': actual}})
    except (OSError,sqlite3.Error,ValueError,TypeError,RecursionError,KeyError,OverflowError):
        raise RulesIndexError('mtga_cardflow_reference_unavailable_or_invalid') from None
