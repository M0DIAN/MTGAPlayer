"""Read-only, bounded Player.log GRE projection. No native or policy imports.

The JSON brace framing algorithm is adapted from mtga-play 0.4.6 arena_log.py
(MIT Copyright (c) 2026 MODIAN); see THIRD_PARTY.md. Raw private data is
held only during reduction and never returned by document().
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import re


COMBAT_SUBMITS = {
    'ClientMessageType_SubmitAttackersReq': 'GREMessageType_DeclareAttackersReq',
    'ClientMessageType_SubmitBlockersReq': 'GREMessageType_DeclareBlockersReq',
}
TERMINAL_SUBMITS = {**COMBAT_SUBMITS,
    'ClientMessageType_SubmitTargetsReq': 'GREMessageType_SelectTargetsReq'}


def _id(value):
    return type(value) is int and 0 <= value <= 2**53 - 1


def _key(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()[:16] if isinstance(value, str) and value else None


def _label(value, prefix):
    return isinstance(value, str) and re.fullmatch(prefix + r'[A-Za-z0-9_]{1,80}', value) is not None


def _seat(value):
    return type(value) is int and value in (1, 2)


def _request_digest(message):
    return hashlib.sha256(json.dumps(message, sort_keys=True,
                          separators=(',', ':')).encode('utf-8')).digest()


def _viewer_list(value):
    return isinstance(value, list) and all(_seat(seat) for seat in value)


def _supported_revealed_view(obj, zones, self_seat):
    """Recognize only the observed nonself Hand/Revealed opaque view.

    This preserves both GRE relations without treating the view as a physical
    card or inferring which Card it represents. Created annotations establish
    the sampled protocol shape, but need not recur on later unchanged Diffs.
    """
    if (obj.get('type') != 'GameObjectType_RevealedCard' or
            obj.get('visibility') != 'Visibility_Private' or
            not _seat(obj.get('ownerSeatId')) or obj['ownerSeatId'] == self_seat or
            not _seat(obj.get('controllerSeatId')) or
            obj['controllerSeatId'] != obj['ownerSeatId'] or
            not _id(obj.get('zoneId'))):
        return False
    owner = obj['ownerSeatId']
    hand = zones.get(obj['zoneId'])
    if (not isinstance(hand, dict) or hand.get('type') != 'ZoneType_Hand' or
            hand.get('visibility') != 'Visibility_Private' or
            not _seat(hand.get('ownerSeatId')) or hand['ownerSeatId'] != owner or
            not isinstance(hand.get('objectInstanceIds'), list)):
        return False
    memberships = [zone for zone in zones.values()
                   if isinstance(zone.get('objectInstanceIds'), list) and
                   obj['instanceId'] in zone['objectInstanceIds']]
    if len(memberships) != 1:
        return False
    revealed = memberships[0]
    return (revealed.get('type') == 'ZoneType_Revealed' and
            revealed.get('visibility') == 'Visibility_Public' and
            _seat(revealed.get('ownerSeatId')) and revealed['ownerSeatId'] == owner)


def _timestamp(value):
    if type(value) is int and value >= 0:
        return value
    if isinstance(value, str) and 1 <= len(value) <= 20 and value.isascii() and value.isdecimal():
        return value
    return None


_OBSERVED_ACTION_TYPES = frozenset({
    'ActionType_Activate', 'ActionType_Activate_Mana', 'ActionType_Cast',
    'ActionType_FloatMana', 'ActionType_Pass', 'ActionType_Play',
})


_COMPLEX_ACTION_TYPES = frozenset({
    'ActionType_Cast', 'ActionType_Activate', 'ActionType_Activate_Mana',
})
_RAW_ID_FIELDS = (
    ('instanceId', 'instance_id'), ('grpId', 'grp_id'),
    ('facetId', 'facet_id'), ('abilityGrpId', 'ability_grp_id'),
    ('uniqueAbilityId', 'unique_ability_id'),
)
_RAW_FLAG_FIELDS = (
    ('shouldStop', 'should_stop'), ('isBatchable', 'is_batchable'),
    ('isManaAbilityWithSideEffect', 'is_mana_ability_with_side_effect'),
)
_OPAQUE_LIST_FIELDS = (
    'manaCost', 'targets', 'manaPaymentOptions', 'manaSelections',
)



_RELATION_LIMIT = 64


def _mana_position_index(actions):
    """Same-request active mana row locations keyed by exact raw ID pair."""
    lookup = {}
    for index, row in enumerate(actions):
        if (row.get('actionType') == 'ActionType_Activate_Mana' and
                _id(row.get('instanceId')) and _id(row.get('abilityGrpId'))):
            lookup.setdefault((row['instanceId'], row['abilityGrpId']), []).append(index)
    return lookup


def _positional_links(rows, mana_index):
    """Position only: numeric identity equality does not prove usable payment."""
    if not isinstance(rows, list):
        return {'valid_array': False, 'total': None, 'examined': 0,
                'truncated': False, 'entries': []}
    entries = []
    for index, row in enumerate(rows[:_RELATION_LIMIT]):
        item = {'position': index}
        if not isinstance(row, dict):
            item['status'] = 'non_object'
        elif not _id(row.get('instanceId')) or not _id(row.get('abilityGrpId')):
            item['status'] = 'missing_or_invalid_pair'
        else:
            matches = mana_index.get((row['instanceId'], row['abilityGrpId']), ())
            if len(matches) == 1:
                item.update(status='unique_pair', active_mana_position=matches[0])
            else:
                item['status'] = 'ambiguous_pair' if matches else 'no_active_pair'
        entries.append(item)
    return {'valid_array': True, 'total': len(rows), 'examined': len(entries),
            'truncated': len(rows) > _RELATION_LIMIT, 'entries': entries}


def _raw_target_slots(rows):
    """Only group position, strict raw targetIdx and nested element count."""
    if not isinstance(rows, list):
        return {'valid_array': False, 'total': None, 'examined': 0,
                'truncated': False, 'entries': []}
    entries = []
    for index, row in enumerate(rows[:_RELATION_LIMIT]):
        item = {'position': index}
        if isinstance(row, dict):
            raw_idx = row.get('targetIdx')
            targets = row.get('targets')
            item['target_idx_raw'] = raw_idx if _id(raw_idx) else None
            item['target_count'] = len(targets) if isinstance(targets, list) else None
            item['valid_shape'] = _id(raw_idx) and isinstance(targets, list)
        else:
            item['valid_shape'] = False
        entries.append(item)
    return {'valid_array': True, 'total': len(rows), 'examined': len(entries),
            'truncated': len(rows) > _RELATION_LIMIT, 'entries': entries}


def _raw_action_relations(row, mana_index):
    auto = row.get('autoTapSolution')
    taps = auto.get('autoTapActions') if isinstance(auto, dict) else None
    return {
        'auto_tap_mana_links': (_positional_links(taps, mana_index)
                                if 'autoTapSolution' in row else None),
        'mana_selection_links': (_positional_links(row['manaSelections'], mana_index)
                                 if 'manaSelections' in row else None),
        'target_slots': (_raw_target_slots(row['targets'])
                          if 'targets' in row else None),
        'pair_equality_only': True, 'payment_legal': False,
        'targets_legal': False, 'executable': False, 'read_only': True,
    }


def _complex_raw_shape(position, action_type, row, mana_index):
    """Only request-scoped raw IDs and presence/size of opaque parameters.

    Nested payment, target and tapping contents are deliberately NOT decoded,
    even when their container is a list. This cannot establish a legal response.
    """
    identifiers, flags, invalid_types, parameters = {}, {}, [], {}
    for field, public_field in _RAW_ID_FIELDS:
        if field in row:
            if _id(row[field]):
                identifiers[public_field] = row[field]
            else:
                invalid_types.append(field)
    for field, public_field in _RAW_FLAG_FIELDS:
        if field in row:
            if type(row[field]) is bool:
                flags[public_field] = row[field]
            else:
                invalid_types.append(field)
    for field in _OPAQUE_LIST_FIELDS:
        if field in row:
            value = row[field]
            parameters[field] = {'kind': 'array' if isinstance(value, list) else 'unexpected',
                                 'element_count': len(value) if isinstance(value, list) else None}
            if not isinstance(value, list):
                invalid_types.append(field)
    if 'autoTapSolution' in row:
        value = row['autoTapSolution']
        nested = value.get('autoTapActions') if isinstance(value, dict) else None
        parameters['autoTapSolution'] = {
            'kind': 'object' if isinstance(value, dict) else 'unexpected',
            'auto_tap_actions_count': len(nested) if isinstance(nested, list) else None}
        if not isinstance(value, dict) or ('autoTapActions' in value and
                                           not isinstance(nested, list)):
            invalid_types.append('autoTapSolution')
    accounted = ({'actionType', 'autoTapSolution'} |
                 {key for key, _ in _RAW_ID_FIELDS} |
                 {key for key, _ in _RAW_FLAG_FIELDS} |
                 set(_OPAQUE_LIST_FIELDS))
    return {
        'list_position': position, 'action_type': action_type,
        'raw_identifiers': identifiers, 'raw_flags': flags,
        'opaque_parameter_shapes': parameters,
        'invalid_known_field_types': sorted(invalid_types),
        'other_top_level_fields_present': bool(set(row) - accounted),
        'raw_relations': _raw_action_relations(row, mana_index),
        'semantics_complete': False, 'legal_action_verified': False,
        'executable': False, 'read_only': True}


def _frontier_row(position, action_type, row):
    """Safe per-active-position metadata for the opt-in frontier only."""
    parameters = {}
    for field in _OPAQUE_LIST_FIELDS:
        if field in row:
            value = row[field]
            parameters[field] = {
                'kind': 'array' if isinstance(value, list) else 'unexpected',
                'element_count': len(value) if isinstance(value, list) else None,
            }
    if 'autoTapSolution' in row:
        value = row['autoTapSolution']
        nested = value.get('autoTapActions') if isinstance(value, dict) else None
        parameters['autoTapSolution'] = {
            'kind': 'object' if isinstance(value, dict) else 'unexpected',
            'auto_tap_actions_count': len(nested) if isinstance(nested, list) else None,
        }
    accounted = ({'actionType', 'autoTapSolution'} |
                 {key for key, _ in _RAW_ID_FIELDS} |
                 {key for key, _ in _RAW_FLAG_FIELDS} |
                 set(_OPAQUE_LIST_FIELDS))
    return {'list_position': position, 'action_type': action_type,
            'known_parameter_shapes': parameters,
            'other_top_level_fields_present': bool(set(row) - accounted),
            'structurally_interpreted': False}


def _available_action_inventory(message):
    """Observe engine-listed action rows; never infer legality or execution.

    The six type labels and flat Pass/Play shapes are grounded in the local
    2026-10-13 schema inventory. Other action details remain uninterpreted.
    """
    def unsupported(reason):
        return {'supported': False, 'unsupported_reason': reason,
                'candidates': [], 'selection': None, 'candidate_evidence': None,
                'action_inventory': None}

    payload = message.get('actionsAvailableReq')
    if not isinstance(payload, dict):
        return unsupported('missing_actions_available_payload')
    actions = payload.get('actions')
    inactive = payload.get('inactiveActions')
    if (not isinstance(actions, list) or len(actions) > 256 or
            ('inactiveActions' in payload and
             (not isinstance(inactive, list) or len(inactive) > 512)) or
            not all(isinstance(row, dict) for row in actions)):
        return unsupported('invalid_actions_available_shape')

    counts, simple, complex_shapes, frontier_rows = {}, [], [], []
    mana_index = _mana_position_index(actions)
    type_labels_complete = True
    for position, row in enumerate(actions):
        typ = row.get('actionType')
        if type(typ) is not str or typ not in _OBSERVED_ACTION_TYPES:
            typ = '_unrecognized_action_type'
            type_labels_complete = False
        counts[typ] = counts.get(typ, 0) + 1
        frontier_rows.append(_frontier_row(position, typ, row))
        if typ == 'ActionType_Pass' and set(row) == {'actionType'}:
            simple.append({'list_position': position, 'action_type': typ})
            frontier_rows[-1]['structurally_interpreted'] = True
        elif (typ == 'ActionType_Play' and
              set(row) == {'actionType', 'facetId', 'grpId', 'instanceId', 'shouldStop'} and
              all(_id(row[name]) for name in ('facetId', 'grpId', 'instanceId')) and
              type(row['shouldStop']) is bool):
            simple.append({'list_position': position, 'action_type': typ,
                           'instance_id': row['instanceId'], 'grp_id': row['grpId'],
                           'facet_id': row['facetId'],
                           'should_stop_raw': row['shouldStop']})
            frontier_rows[-1]['structurally_interpreted'] = True
        elif typ in _COMPLEX_ACTION_TYPES:
            shape = _complex_raw_shape(position, typ, row, mana_index)
            complex_shapes.append(shape)
            targets = shape['raw_relations']['target_slots']
            frontier_rows[-1]['structurally_interpreted'] = (
                not shape['invalid_known_field_types'] and
                not shape['other_top_level_fields_present'] and
                all(parameter['kind'] == ('object' if name == 'autoTapSolution'
                                               else 'array') and
                    (name != 'autoTapSolution' or
                     parameter['auto_tap_actions_count'] is not None)
                    for name, parameter in shape['opaque_parameter_shapes'].items()) and
                (targets is None or targets['valid_array'] and
                 all(item['valid_shape'] for item in targets['entries']) and
                 not targets['truncated']))

    # 'supported' stays false: typed observation is NOT proof of the
    # complete legal response, mana payment, target choice or native action.
    return {'supported': False, 'unsupported_reason': 'action_details_unverified',
            'candidates': [], 'selection': None, 'candidate_evidence': None,
            'action_inventory': {
                'field': 'actionsAvailableReq.actions',
                'kind': 'engine_listed_action_types_only',
                'offered_count': len(actions),
                'types': [{'action_type': kind, 'count': counts[kind]}
                          for kind in sorted(counts)],
                'type_labels_complete': type_labels_complete,
                'inactive_count': len(inactive) if inactive is not None else None,
                'inactive_excluded': True,
                'simple_shapes': simple,
                'simple_shapes_count': len(simple),
                'complex_raw_shapes': complex_shapes,
                'complex_raw_shapes_count': len(complex_shapes),
                '_frontier_rows': frontier_rows,
                'remaining_action_details_unverified': len(actions) - len(simple),
                'other_payload_fields_present': bool(set(payload) - {'actions', 'inactiveActions'}),
                'other_message_fields_present': bool(set(message) - {
                    'type', 'systemSeatIds', 'msgId', 'gameStateId', 'actionsAvailableReq'}),
                'semantics_complete': False, 'legal_actions_complete': False,
                'executable': False, 'read_only': True}}



def _join_action_sources_to_visible(inventory, visible):
    """Same-state observable object join; never inspect hidden/raw game objects.

    Action instance IDs can refer to invisible zones. Only objects which
    passed the existing visibility projection may produce a reference.
    """
    indexed = {}
    for obj in visible:
        instance = obj.get('id')
        if _id(instance):
            indexed.setdefault(instance, []).append(obj)
    links = []
    for item in inventory.get('simple_shapes', []) + inventory.get('complex_raw_shapes', []):
        if item.get('action_type') == 'ActionType_Pass':
            continue  # A Pass has no source card, not an unresolved card.
        instance = (item.get('instance_id') if 'instance_id' in item else
                    item.get('raw_identifiers', {}).get('instance_id'))
        row = {'list_position': item['list_position'],
               'action_type': item['action_type']}
        if not _id(instance):
            row['status'] = 'missing_source_instance'
        else:
            hits = indexed.get(instance, ())
            if not hits:
                row['status'] = 'not_in_visible_projection'
            elif len(hits) != 1:
                row['status'] = 'ambiguous_visible_projection'
            else:
                row['status'] = 'visible_unique'
                row['visible_object_id'] = instance
                group_id = (item.get('grp_id') if 'grp_id' in item else
                            item.get('raw_identifiers', {}).get('grp_id'))
                card_id = hits[0].get('card_id')
                row['raw_group_equals_visible_card_id'] = (
                    group_id == card_id if _id(group_id) and _id(card_id) else None)
        links.append(row)
    links.sort(key=lambda item: item['list_position'])
    return {'scope': 'described_active_actions_and_current_visible_objects_only',
            'links': links, 'link_count': len(links),
            'unique_visible_count': sum(x['status'] == 'visible_unique' for x in links),
            'all_legal_actions_known': False, 'read_only': True, 'executable': False}


def _request_semantics(message):
    """Decode only the observed, own-seat SelectN option shape.

    IDs are explicit engine options in this request, including when the
    referenced cards occupy a hidden zone. Never enrich them from raw objects.
    """
    def unsupported(reason):
        return {'supported': False, 'unsupported_reason': reason,
                'candidates': [], 'selection': None, 'candidate_evidence': None}
    if message.get('type') == 'GREMessageType_ActionsAvailableReq':
        return _available_action_inventory(message)
    if message.get('type') != 'GREMessageType_SelectNReq':
        return unsupported('unsupported_request_type')
    payload = message.get('selectNReq')
    if not isinstance(payload, dict):
        return unsupported('missing_selectn_payload')
    observed = {'maxSel', 'context', 'optionContext', 'listType', 'ids', 'prompt',
                'idType', 'unfilteredIds', 'sourceId', 'validationType',
                'minWeight', 'maxWeight'}
    # Additional fields could narrow the choices. Refuse an unobserved shape.
    if set(payload) != observed or set(message) - {
            'type', 'systemSeatIds', 'msgId', 'gameStateId', 'prompt',
            'selectNReq', 'allowCancel'}:
        return unsupported('unsupported_selectn_shape')
    ids, unfiltered = payload['ids'], payload['unfilteredIds']
    if (not isinstance(ids, list) or not ids or
            not all(_id(value) for value in ids) or len(ids) != len(set(ids)) or
            not isinstance(unfiltered, list) or
            not all(_id(value) for value in unfiltered) or
            len(unfiltered) != len(set(unfiltered)) or
            not set(ids) <= set(unfiltered)):
        return unsupported('invalid_selectn_candidates')
    if (payload['idType'] != 'IdType_InstanceId' or
            payload['listType'] != 'SelectionListType_Dynamic' or
            payload['context'] != 'SelectionContext_Resolution' or
            payload['optionContext'] != 'OptionContext_Resolution' or
            payload['validationType'] != 'SelectionValidationType_NonRepeatable' or
            payload['minWeight'] != -2147483648 or
            payload['maxWeight'] != 2147483647 or
            not _id(payload['sourceId']) or
            type(payload['maxSel']) is not int or
            not 1 <= payload['maxSel'] <= len(ids) or
            message.get('allowCancel') != 'AllowCancel_No' or
            not isinstance(payload['prompt'], dict) or
            not isinstance(message.get('prompt'), dict)):
        return unsupported('unsupported_selectn_shape')
    return {'supported': True, 'unsupported_reason': None,
            'candidates': [{'instance_id': value} for value in ids],
            'candidate_evidence': {'field': 'selectNReq.ids',
                                   'kind': 'engine_offered_instance_ids',
                                   'all_legal_actions': False},
            'selection': {'id_type': payload['idType'], 'list_type': payload['listType'],
                          'context': payload['context'], 'option_context': payload['optionContext'],
                          'validation_type': payload['validationType'],
                          'max_sel': payload['maxSel'], 'min_sel': None,
                          'min_weight': payload['minWeight'], 'max_weight': payload['maxWeight'],
                          'source_id': payload['sourceId'], 'allow_cancel': False,
                          'combinations_complete': False}}


class RawFramer:
    def __init__(self, limit=4 * 1024 * 1024):
        self.limit = limit
        self.buffer = bytearray()
        self.depth = 0
        self.quoted = self.escaped = False
        self.errors = 0

    def feed(self, data):
        found = []
        for byte in data:
            if not self.depth:
                if byte != 123:
                    continue
                self.buffer = bytearray([byte])
                self.depth = 1
                self.quoted = self.escaped = False
                continue
            self.buffer.append(byte)
            if len(self.buffer) > self.limit:
                self.errors += 1
                found.append(None)
                self.buffer.clear()
                self.depth = 0
                continue
            if self.quoted:
                if self.escaped:
                    self.escaped = False
                elif byte == 92:
                    self.escaped = True
                elif byte == 34:
                    self.quoted = False
            elif byte == 34:
                self.quoted = True
            elif byte in (123, 91):
                self.depth += 1
            elif byte in (125, 93):
                self.depth -= 1
                if not self.depth:
                    try:
                        value = json.loads(self.buffer)
                        if not isinstance(value, dict):
                            raise ValueError('root')
                        found.append(value)
                    except (ValueError, UnicodeError):
                        self.errors += 1
                        found.append(None)
                    self.buffer.clear()
        return found

    @property
    def partial(self):
        return bool(self.depth)


class RawFollower:
    def __init__(self, path, max_history_bytes=64 * 1024 * 1024, *, byte_observer=None,
                 max_poll_bytes=None):
        if max_poll_bytes is not None and (type(max_poll_bytes) is not int or not 1 <= max_poll_bytes <= 16*1024*1024):
            raise ValueError('invalid_raw_poll_byte_limit')
        self.path = Path(path)
        self.max_history_bytes = max_history_bytes
        self.byte_observer, self.max_poll_bytes = byte_observer, max_poll_bytes
        self.byte_observer_error = None
        self.identity = None
        self.offset = self.generation = 0
        self.prefix = self.anchor = b''
        self.anchor_start = 0
        self.framer = RawFramer()

    def _bytes(self, method, *args):
        # Optional evidence I/O must never change the production reducer path.
        if self.byte_observer is not None:
            try:
                getattr(self.byte_observer, method)(*args)
            except Exception as exc:
                self.byte_observer_error = {'error_type': type(exc).__name__,
                    'errno': getattr(exc, 'errno', None)}
                try:self.byte_observer.failed()
                except Exception:pass
                self.byte_observer = None

    def poll(self):
        try:return self._poll()
        except (OSError, ValueError) as exc:
            if self.byte_observer is not None:
                self._bytes('failed')
                self.byte_observer_error={'error_type':type(exc).__name__, 'errno':getattr(exc,'errno',None)}
                self.byte_observer=None
            raise

    def _poll(self):
        with self.path.open('rb') as stream:
            stat = os.fstat(stream.fileno())
            identity = (stat.st_dev, stat.st_ino) if stat.st_ino else (stat.st_ctime_ns,)
            reset = identity != self.identity or stat.st_size < self.offset
            if not reset and self.offset:
                reset = stream.read(len(self.prefix)) != self.prefix
                stream.seek(self.anchor_start)
                reset |= stream.read(len(self.anchor)) != self.anchor
            if reset:
                if stat.st_size > self.max_history_bytes:
                    raise ValueError('raw_history_limit_exceeded')
                self.identity, self.offset = identity, 0
                self.generation += 1
                self.framer = RawFramer()
            stream.seek(self.offset)
            records = []
            remaining = stat.st_size - self.offset
            self._bytes('begin', {'generation': self.generation, 'identity': list(identity),
                'reset': reset, 'byte_start': self.offset, 'source_size': stat.st_size})
            if self.max_poll_bytes is not None:remaining = min(remaining, self.max_poll_bytes)
            while remaining:
                chunk = stream.read(min(65536, remaining))
                if not chunk:
                    break
                self._bytes('write', self.offset, chunk)
                records.extend(self.framer.feed(chunk))
                self.offset += len(chunk)
                remaining -= len(chunk)
            stream.seek(0)
            self.prefix = stream.read(min(256, self.offset))
            self.anchor_start = max(0, self.offset - 64)
            stream.seek(self.anchor_start)
            self.anchor = stream.read(self.offset - self.anchor_start)
            final = os.fstat(stream.fileno())
            self._bytes('end', {'byte_end': self.offset, 'source_size': stat.st_size,
                'source_size_after': final.st_size, 'source_changed_during_poll':
                    (stat.st_size, stat.st_mtime_ns) != (final.st_size, final.st_mtime_ns),
                'partial_record': self.framer.partial, 'framing_errors': self.framer.errors})
        return reset, records


class RawReducer:
    def __init__(self, observer=None, *, include_state_messages=False, include_request_parameters=False,
                 include_targeted_activate=False, include_current_discard=False, include_target_payment_relation=False,
                 include_cast_target_members=False, include_cast_activate_associations=False,
                 include_multi_slot_cast=False):
        # Opt-in instrumentation only. Private request identities stay in the
        # caller's memory; default replay/watch have no observer.
        self.observer = observer
        self._include_state_messages = include_state_messages
        self._include_request_parameters = include_request_parameters
        self._include_targeted_activate = include_targeted_activate
        self._include_current_discard = include_current_discard
        self._include_target_payment_relation = include_target_payment_relation
        self._include_cast_target_members = include_cast_target_members
        self._include_cast_activate_associations = include_cast_activate_associations
        if type(include_multi_slot_cast) is not bool or include_multi_slot_cast and not include_request_parameters:
            raise ValueError('multi_slot_cast_requires_request_parameters')
        self._include_multi_slot_cast = include_multi_slot_cast
        self.reset(0)

    def _observe(self, event, **details):
        if self.observer is not None:
            self.observer(event, details)

    def _interrupt_current_target(self):
        # Bounded private witnesses for opt-in current-target/cost evidence.
        # Legacy currentness, public documents and policy remain unchanged.
        if self.request is not None and self.request['type'] == 'GREMessageType_SelectTargetsReq':
            self.request['_target_evidence_interrupted'] = True
        if self.request is not None and self.request['type'] == 'GREMessageType_PayCostsReq':
            self.request['_cost_evidence_interrupted'] = True
        if self.request is not None and self.request['type'] == 'GREMessageType_SearchReq':
            self.request['_search_evidence_interrupted'] = True
        if self.request is not None and self.request['type'] == 'GREMessageType_GroupReq':
            self.request['_group_evidence_interrupted'] = True

    def _request_ended(self, disposition):
        if self.observer is not None and self.request is not None:
            self._observe('request_ended', request=self.request,
                          disposition=disposition)

    def reset(self, generation):
        self.generation = generation
        self.client_id = None
        self.match = self.game = self.seat = None
        self.room_match = self.room_seat = self.room_state = None
        self.room_players = None
        self.version = None
        self.objects = self.zones = self.players = {}
        self.turn = self.game_info = {}
        self.request = None
        self.last_state_timestamp = None
        self.error = 'no_full_baseline'
        self.first_error = None
        self.last_valid = None
        self.retired = set()
        self.accepted_digest = None
        self.accepted_kind = None
        self.conflict = False
        self.consumed = set()
        self.request_ids = {}
        self.superseded = set()
        self.submitted = None
        self._target_record_mixed = False
        self._target_state_continuity_verified = False
        self.unsupported_broadcast_requests = 0

    def _invalidate(self, reason):
        self._target_state_continuity_verified = False
        if self.request is not None and self.request['type']=='GREMessageType_SearchReq':
            self.request['_search_evidence_interrupted']=True
        if self.request is not None and self.request['type']=='GREMessageType_GroupReq':
            self.request['_group_evidence_interrupted']=True
        if self.request:
            self.request['_continuity_verified'] = False
        if self.observer is not None:
            self._observe('continuity_error', reason=reason)
        if reason in ('room_seat_conflict', 'gre_recipient_or_self_seat_unverified',
                      'client_identity_changed', 'conflicting_duplicate_state'):
            self.conflict = True
        self.error = reason
        if self.first_error is None:
            self.first_error = {'reason': reason, 'generation': self.generation,
                                'match': self.match, 'game': self.game}

    def _revoke_seat(self, reason, revoke_client=False):
        if revoke_client:
            self.client_id = None
        self.room_seat = self.seat = None
        self.room_players = None
        self._invalidate(reason)

    def _boundary(self, match, game=None):
        self._target_state_continuity_verified = False
        if self.match is not None and self.game is not None:
            self.retired.add((self.match, self.game))
        self.match, self.game = match, game
        self.version = None
        self.objects, self.zones, self.players = {}, {}, {}
        self.turn, self.game_info = {}, {}
        self._request_ended('superseded')
        self.request = None
        self.accepted_digest = None
        self.accepted_kind = None
        self.conflict = False
        self.consumed.clear()
        self.request_ids.clear()
        self.superseded.clear()
        self.submitted = None
        self.unsupported_broadcast_requests = 0
        self.error = 'await_full_baseline'

    def apply(self, entry):
        self._target_record_mixed = (isinstance(entry, dict) and len(set(entry) & {
            'payload', 'authenticateResponse', 'matchGameRoomStateChangedEvent', 'greToClientEvent'}) > 1)
        if self._target_record_mixed: self._interrupt_current_target()
        if entry is None:
            self._invalidate('malformed_raw_record')
            return
        for field in ('authenticateResponse', 'matchGameRoomStateChangedEvent',
                      'greToClientEvent'):
            if field in entry and not isinstance(entry[field], dict):
                reason = 'invalid_' + field
                if field in ('authenticateResponse', 'matchGameRoomStateChangedEvent'):
                    self._revoke_seat(reason, revoke_client=field == 'authenticateResponse')
                else:
                    self._invalidate(reason)
                return
        auth = entry.get('authenticateResponse')
        if isinstance(auth, dict):
            if not isinstance(auth.get('clientId'), str) or not auth['clientId']:
                self._revoke_seat('invalid_auth_identity', revoke_client=True)
                return
            if self.client_id is not None and self.client_id != auth['clientId']:
                self._revoke_seat('client_identity_changed', revoke_client=True)
            self.client_id = auth['clientId']
            if self.room_players is not None and self.room_seat is None:
                hits = [p.get('systemSeatId') for p in self.room_players if isinstance(p, dict) and
                        p.get('userId') == self.client_id]
                if len(hits) == 1 and type(hits[0]) is int and hits[0] in (1, 2):
                    self.room_seat = hits[0]
        payload = entry.get('payload')
        if ('payload' in entry and self.request is not None and self.request['type']=='GREMessageType_GroupReq' and
                not (type(payload) is dict and payload.get('type')=='ClientMessageType_UIMessage')):
            self._interrupt_current_target()
        if ('payload' in entry and self.request is not None and self.request['type']=='GREMessageType_SearchReq' and
                not (type(payload) is dict and payload.get('type')=='ClientMessageType_UIMessage')):
            self._interrupt_current_target()
        if ('payload' in entry and self.request is not None and
                self.request['type'] == 'GREMessageType_PayCostsReq' and
                not (type(payload) is dict and payload.get('type') == 'ClientMessageType_UIMessage')):
            self._interrupt_current_target()
        if 'payload' in entry and self.request is not None and self.request['type'] == 'GREMessageType_SelectTargetsReq':
            typ = payload.get('type') if type(payload) is dict else None
            paired_header = (type(payload) is dict and type(payload.get('respId')) is int and
                type(payload.get('gameStateId')) is int and payload['respId'] == self.request['id'] and
                payload['gameStateId'] == self.request['game_state_id'])
            if not (typ == 'ClientMessageType_UIMessage' or paired_header and
                    (typ == 'ClientMessageType_SelectTargetsResp' or typ == 'ClientMessageType_SubmitTargetsReq' and
                     set(payload) == {'type', 'respId', 'gameStateId'})):
                self._interrupt_current_target()
        response = (isinstance(payload, dict) and isinstance(payload.get('type'), str) and
                    payload['type'].startswith('ClientMessageType_') and
                    payload['type'].endswith('Resp') and _id(payload.get('respId')))
        combat_submit = False
        if (isinstance(payload, dict) and isinstance(payload.get('type'), str) and
                payload['type'] in TERMINAL_SUBMITS):
            req = self.request
            binding = req.get('binding') if isinstance(req, dict) else None
            ident, version = payload.get('respId'), payload.get('gameStateId')
            combat_submit = (not any(k in entry for k in ('greToClientEvent', 'authenticateResponse',
                    'matchGameRoomStateChangedEvent')) and self.error is None and not self.conflict and _id(ident) and _id(version) and
                (payload['type'] != 'ClientMessageType_SubmitTargetsReq' or
                 set(payload) == {'type', 'respId', 'gameStateId'}) and
                isinstance(binding, dict) and req.get('current') is True and
                req.get('_continuity_verified') is True and req.get('type') == TERMINAL_SUBMITS[payload['type']] and
                req.get('id') == ident and req.get('game_state_id') == version == self.version and
                binding == {'generation': self.generation, 'match': self.match, 'game': self.game,
                            'game_state_id': version, 'self_seat': self.seat, 'ownership_verified': True} and
                type(binding.get('generation')) is int and type(binding.get('game')) is int and
                type(binding.get('game_state_id')) is int and
                type(binding.get('self_seat')) is int and binding.get('ownership_verified') is True and
                type(self.seat) is int and type(self.room_seat) is int and self.room_seat == self.seat and
                self.seat in (1, 2) and self.room_match == self.match and
                self.room_state != 'MatchGameRoomStateType_MatchCompleted' and
                self.game_info.get('stage') != 'GameStage_GameOver' and
                (self.match, self.game, ident) not in self.consumed and ident not in self.superseded and
                self.request_ids.get(ident, ())[:2] == (version, req['type']))
        if response or combat_submit:
            response_id = payload['respId']
            prior = self.request_ids.get(response_id)
            request_state = prior[0] if prior else None
            if request_state is not None and payload.get('gameStateId') == request_state:
                self.consumed.add((self.match, self.game, response_id))
                if self.request and self.request['id'] == response_id:
                    self._request_ended('consumed')
                    self.request = None
                self.submitted = {'request_id': response_id, 'game_state_id': request_state,
                                  'confirmation': 'client_submission_only'}
        room = entry.get('matchGameRoomStateChangedEvent')
        if isinstance(room, dict):
            info = room.get('gameRoomInfo')
            info = info if isinstance(info, dict) else {}
            config = info.get('gameRoomConfig')
            config = config if isinstance(config, dict) else {}
            match = _key(config.get('matchId'))
            state_type = info.get('stateType')
            if match is None or not _label(state_type, 'MatchGameRoomStateType_'):
                self._revoke_seat('room_identity_or_state_invalid')
            else:
                if match != self.room_match and any(old_match == match for old_match, _ in self.retired):
                    return  # Late room completion cannot retire a newer match.
                if match != self.room_match:
                    self.room_match = match
                    self.room_seat = None
                    self._boundary(match)
                players = config.get('reservedPlayers')
                valid_players = (isinstance(players, list) and len(players) == 2 and
                                 all(isinstance(p, dict) and isinstance(p.get('userId'), str) and
                                     bool(p['userId']) and _seat(p.get('systemSeatId')) for p in players))
                if valid_players:
                    valid_players = (len({p['userId'] for p in players}) == 2 and
                                     {p['systemSeatId'] for p in players} == {1, 2})
                hits = [p['systemSeatId'] for p in players if p['userId'] == self.client_id] if (
                    valid_players and self.client_id) else []
                if len(hits) == 1:
                    if self.room_seat is not None and self.room_seat != hits[0]:
                        self._revoke_seat('room_seat_conflict')
                    else:
                        self.room_seat = hits[0]
                        self.room_players = copy.deepcopy(players)
                else:
                    self._revoke_seat('self_seat_unverified')
                self.room_state = state_type
                if state_type == 'MatchGameRoomStateType_MatchCompleted' and self.request:
                    self.superseded.add(self.request['id'])
                    self._request_ended('superseded')
                    self.request = None
        gre = entry.get('greToClientEvent')
        if isinstance(gre, dict):
            messages = gre.get('greToClientMessages')
            if not isinstance(messages, list):
                self._invalidate('invalid_gre_messages')
                return
            if self.observer is not None:
                self._observe('gre_messages', count=len(messages))
            for message in messages:
                if isinstance(message, dict):
                    self._message(message, entry.get('timestamp'))
                else:
                    self._invalidate('invalid_gre_message')

    def _message(self, message, timestamp):
        state = message.get('gameStateMessage')
        is_request = isinstance(message.get('type'), str) and message['type'].endswith('Req')
        if message.get('type') in ('GREMessageType_GameStateMessage',
                                   'GREMessageType_QueuedGameStateMessage') and state is None:
            self._invalidate('missing_game_state_payload')
            return
        if state is None and not is_request:
            return
        recipients = message.get('systemSeatIds')
        own_recipient = (isinstance(recipients, list) and len(recipients) == 1 and
                         _seat(recipients[0]) and recipients[0] == self.room_seat)
        if state is None and not own_recipient:
            if isinstance(recipients, list) and any(
                    _seat(seat) and seat == self.room_seat for seat in recipients):
                self.unsupported_broadcast_requests += 1
                self._interrupt_current_target()
                if self.observer is not None:
                    self._observe('unsupported_broadcast_request')
            return  # Broadcast and other-seat prompts are not own requests.
        if self.room_seat not in (1, 2):
            self._invalidate('self_seat_unverified')
            return
        if not own_recipient:
            self._invalidate('gre_recipient_or_self_seat_unverified')
            return
        self.seat = self.room_seat
        if state is not None:
            self._state(state, timestamp)
        if is_request:
            if not _label(message.get('type'), 'GREMessageType_'):
                self._invalidate('invalid_request_type')
                return
            msg_id, state_id = message.get('msgId'), message.get('gameStateId')
            if not _id(msg_id) or not _id(state_id):
                self._invalidate('request_identity_missing')
                return
            digest = _request_digest(message)
            prior = self.request_ids.get(msg_id)
            if prior is not None and prior != (state_id, message['type'], digest):
                self._invalidate('conflicting_request_identity')
                self.conflict = True
                return
            self.request_ids[msg_id] = (state_id, message['type'], digest)
            if (state_id == self.version and self.error is None and
                    self.room_state != 'MatchGameRoomStateType_MatchCompleted' and
                    self.game_info.get('stage') != 'GameStage_GameOver' and
                    (self.match, self.game, msg_id) not in self.consumed and
                    msg_id not in self.superseded):
                if self.request and self.request['id'] != msg_id:
                    self.superseded.add(self.request['id'])
                    self._request_ended('superseded')
                target_interrupted = (self._target_record_mixed or prior is not None and bool(self.request and
                    self.request['id'] == msg_id and self.request.get('_target_evidence_interrupted') is True))
                cost_interrupted = (self._target_record_mixed or prior is not None and bool(self.request and
                    self.request['id'] == msg_id and self.request.get('_cost_evidence_interrupted') is True))
                search_interrupted = (self._target_record_mixed or prior is not None and bool(self.request and
                    self.request['id'] == msg_id and self.request.get('_search_evidence_interrupted') is True))
                group_interrupted = (self._target_record_mixed or prior is not None and bool(self.request and
                    self.request['id'] == msg_id and self.request.get('_group_evidence_interrupted') is True))
                self.request = {'id': msg_id, 'type': message['type'],
                                '_continuity_verified': prior is None or bool(self.request and
                                    self.request['id'] == msg_id and
                                    self.request.get('_continuity_verified') is True),
                                'game_state_id': state_id, 'current': True,
                                'binding': {'generation': self.generation,
                                            'match': self.match, 'game': self.game,
                                            'game_state_id': state_id,
                                            'self_seat': self.seat,
                                            'ownership_verified': True},
                                **_request_semantics(message)}
                if message['type'] == 'GREMessageType_SelectTargetsReq' and target_interrupted:
                    self.request['_target_evidence_interrupted'] = True
                if message['type'] == 'GREMessageType_PayCostsReq' and cost_interrupted:
                    self.request['_cost_evidence_interrupted'] = True
                if message['type']=='GREMessageType_SearchReq' and search_interrupted:
                    self.request['_search_evidence_interrupted']=True
                if message['type']=='GREMessageType_GroupReq' and group_interrupted:
                    self.request['_group_evidence_interrupted']=True
                if self._include_request_parameters:
                    from .request_parameters import project
                    current_objects = self._current()['objects']
                    visible = [{'instance_id': o['id'], 'card_id': o['card_id'], 'zone': o['zone'],
                                'owner_seat': o['owner'], 'controller_seat': o['controller']}
                               for o in current_objects]
                    # Current whole-row replacement applies before this read.
                    # The narrow producer evidence never exports the raw list.
                    source_abilities = {o['instance_id']: self.objects[o['instance_id']].get('uniqueAbilities')
                        for o in visible if o['zone'] == 'ZoneType_Battlefield' and
                        o['controller_seat'] == self.seat and
                        self.objects[o['instance_id']].get('visibility') == 'Visibility_Public'}
                    from .action_target_menus import public_battlefield_refs
                    cast_refs = (self._cast_source_refs() if self._include_cast_target_members or
                                 self._include_cast_activate_associations or self._include_multi_slot_cast else None)
                    public_refs = (public_battlefield_refs(self, current_objects if self._include_multi_slot_cast else None)
                                   if self._include_targeted_activate or self._include_cast_target_members or
                                   self._include_cast_activate_associations or self._include_multi_slot_cast else None)
                    self.request['_request_parameters'] = project(message, visible, self.seat, source_abilities,
                        targeted_activate=self._include_targeted_activate, current_discard=self._include_current_discard,
                        target_payment_relation=self._include_target_payment_relation,
                        cast_target_members=self._include_cast_target_members,
                        cast_activate_associations=self._include_cast_activate_associations,
                        cast_source_refs=cast_refs,
                        mana_source_refs=self._mana_source_refs() if self._include_cast_target_members or self._include_cast_activate_associations else None,
                        current_hand_refs=self._reviewed_current_hand_refs() if self._include_current_discard else None,
                        public_battlefield_refs=public_refs)
                    if self._include_multi_slot_cast:
                        from .multi_slot_cast import project as project_multi
                        self.request['_multi_slot_cast'] = project_multi(message, visible, self.seat,
                            cast_refs, public_refs)
                if self.observer is not None:
                    self._observe('request_accepted', request=self.request, message=message,
                                  is_retransmission=prior is not None)

    def _state(self, gs, timestamp):
        if isinstance(gs, dict) and gs.get('type') == 'GameStateType_Full':
            self._interrupt_current_target()
        if not isinstance(gs, dict) or gs.get('type') not in ('GameStateType_Full', 'GameStateType_Diff'):
            self._invalidate('unsupported_game_state')
            return
        version = gs.get('gameStateId')
        if not _id(version):
            self._invalidate('game_state_id_missing')
            return
        info = gs.get('gameInfo')
        if info is not None and not isinstance(info, dict):
            self._invalidate('invalid_game_info')
            return
        match = _key(info.get('matchID')) if isinstance(info, dict) and 'matchID' in info else self.match
        game = info.get('gameNumber') if isinstance(info, dict) and 'gameNumber' in info else self.game
        if match != self.room_match or not _id(game) or game < 1:
            self._invalidate('game_identity_unverified')
            return
        if (match, game) in self.retired:
            return
        if (match, game) != (self.match, self.game):
            self._boundary(match, game)
        if self.conflict:
            self._invalidate(self.error or 'identity_conflict')
            return
        full = gs['type'] == 'GameStateType_Full'
        if full and (not isinstance(info, dict) or _key(info.get('matchID')) != match or
                     info.get('gameNumber') != game):
            self._invalidate('full_identity_missing')
            return
        digest = hashlib.sha256(json.dumps(gs, sort_keys=True, separators=(',', ':')).encode()).digest()
        if not full and version == self.version:
            if self.accepted_kind == 'diff' and digest == self.accepted_digest:
                return  # Transport replay never refreshes state or request.
            self._invalidate('conflicting_duplicate_state')
            self.conflict = True
            return
        if not full and (self.version is None or self.error is not None or
                         gs.get('prevGameStateId') != self.version or version <= self.version):
            self._invalidate('state_gap_or_missing_full')
            return
        if full and self.version is not None and version < self.version:
            self._invalidate('state_rollback')
            return
        if full and version == self.version:
            if self.accepted_kind != 'full' or digest != self.accepted_digest:
                self.conflict = True
                self._invalidate('conflicting_duplicate_state')
            elif not self.conflict and self.error in ('malformed_raw_record', 'state_gap_or_missing_full'):
                self.error = None  # identical retransmit repairs continuity, never freshness
                self._target_state_continuity_verified = True
                if self.observer is not None:
                    self._observe('state_accepted', kind='full_retransmit',
                                  baseline='recovered')
            return
        objects = {} if full else copy.deepcopy(self.objects)
        zones = {} if full else copy.deepcopy(self.zones)
        players = {} if full else copy.deepcopy(self.players)
        try:
            for name, target, key in (('gameObjects', objects, 'instanceId'),
                                      ('zones', zones, 'zoneId'), ('players', players, 'systemSeatNumber')):
                rows = gs.get(name, [])
                if not isinstance(rows, list):
                    raise ValueError('invalid_' + name)
                seen = set()
                for row in rows:
                    if not isinstance(row, dict) or not _id(row.get(key)):
                        raise ValueError('invalid_' + name)
                    if row[key] in seen:
                        raise ValueError('duplicate_' + name)
                    seen.add(row[key])
                    target[row[key]] = copy.deepcopy(row)
            for name, target in (('diffDeletedInstanceIds', objects), ('diffDeletedZoneIds', zones)):
                deleted = gs.get(name, [])
                if not isinstance(deleted, list) or not all(_id(x) for x in deleted):
                    raise ValueError('invalid_deleted_ids')
                if full:
                    continue  # Full replaces the prior state; delete metadata is historical.
                for item in deleted:
                    target.pop(item, None)
                    if name == 'diffDeletedInstanceIds':
                        for zone in zones.values():
                            members = zone.get('objectInstanceIds')
                            if isinstance(members, list) and item in members:
                                zone['objectInstanceIds'] = [x for x in members if x != item]
            revealed_views = {instance for instance, obj in objects.items()
                              if _supported_revealed_view(obj, zones, self.seat)}
            for zone_id, zone in zones.items():
                ids = zone.get('objectInstanceIds', [])
                if not isinstance(ids, list) or not all(_id(x) for x in ids) or len(ids) != len(set(ids)):
                    raise ValueError('invalid_zone_membership')
                if any(instance in objects and objects[instance].get('zoneId') != zone_id and
                       instance not in revealed_views for instance in ids):
                    raise ValueError('object_zone_conflict')
                if not _label(zone.get('type'), 'ZoneType_'):
                    raise ValueError('invalid_zone_type')
                if 'ownerSeatId' in zone and not _seat(zone['ownerSeatId']):
                    raise ValueError('invalid_zone_owner')
                if 'viewers' in zone and not _viewer_list(zone['viewers']):
                    raise ValueError('invalid_zone_viewers')
                if any(instance in objects and 'visibility' not in objects[instance] for instance in ids):
                    raise ValueError('missing_object_visibility')
            for obj in objects.values():
                if (obj.get('type') == 'GameObjectType_RevealedCard' and
                        obj['instanceId'] not in revealed_views and
                        any(obj['instanceId'] in zone.get('objectInstanceIds', [])
                            for zone in zones.values())):
                    raise ValueError('unsupported_revealed_card')
                if 'zoneId' in obj and not _id(obj['zoneId']):
                    raise ValueError('invalid_object_zone')
                if 'grpId' in obj and not _id(obj['grpId']):
                    raise ValueError('invalid_card_id')
                if 'visibility' in obj and obj['visibility'] not in ('Visibility_Public', 'Visibility_Private'):
                    raise ValueError('invalid_object_visibility')
                if 'viewers' in obj and not _viewer_list(obj['viewers']):
                    raise ValueError('invalid_object_viewers')
                if any(field in obj and not _seat(obj[field]) for field in
                       ('ownerSeatId', 'controllerSeatId')):
                    raise ValueError('invalid_object_seat')
                if 'isTapped' in obj and type(obj['isTapped']) is not bool:
                    raise ValueError('invalid_object_tapped')
            for player in players.values():
                if not _seat(player['systemSeatNumber']):
                    raise ValueError('invalid_player_seat')
                if 'lifeTotal' in player and (type(player['lifeTotal']) is not int or
                                              abs(player['lifeTotal']) > 2**31 - 1):
                    raise ValueError('invalid_player_life')
            turn = copy.deepcopy(gs.get('turnInfo', self.turn if not full else {}))
            game_info = copy.deepcopy(info if info is not None else self.game_info)
            if not isinstance(turn, dict) or not isinstance(game_info, dict):
                raise ValueError('invalid_state_fields')
            if any(field in turn and turn[field] is not None and not _seat(turn[field])
                   for field in ('activePlayer', 'decisionPlayer')):
                raise ValueError('invalid_turn_seat')
            if 'turnNumber' in turn and turn['turnNumber'] is not None and not _id(turn['turnNumber']):
                raise ValueError('invalid_turn_number')
            if 'stage' in game_info and not _label(game_info['stage'], 'GameStage_'):
                raise ValueError('invalid_game_stage')
            if full:
                kinds = {z.get('type') for z in zones.values()}
                if not ({1, 2} <= set(players) and
                        {'ZoneType_Battlefield', 'ZoneType_Stack', 'ZoneType_Hand'} <= kinds and
                        any(z.get('type') == 'ZoneType_Hand' and z.get('ownerSeatId') == self.seat
                            for z in zones.values())):
                    raise ValueError('incomplete_full_schema')
            # Build the only output-facing projection before touching accepted
            # state. A malformed GRE field cannot leave a new version behind.
            preview = copy.copy(self)
            preview.objects, preview.zones, preview.players = objects, zones, players
            preview.turn, preview.game_info = turn, game_info
            preview.version = version
            preview.last_state_timestamp = _timestamp(timestamp)
            preview.request = None
            projection = preview._current()
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            self._invalidate(str(exc))
            return
        baseline = ('acquired' if self.version is None else
                    'recovered' if self.error is not None else 'none') if full else 'none'
        # Separate opt-in evidence witness; retain legacy state acceptance.
        typed_continuity = (full or self._target_state_continuity_verified is True and
            type(gs.get('prevGameStateId')) is int and gs['prevGameStateId'] == self.version)
        self.objects, self.zones, self.players = objects, zones, players
        self._target_state_continuity_verified = typed_continuity
        self.turn, self.game_info = turn, game_info
        self.version = version
        self.accepted_digest = digest
        self.accepted_kind = 'full' if full else 'diff'
        self.last_state_timestamp = _timestamp(timestamp)
        if self.request:
            self.superseded.add(self.request['id'])
            self._request_ended('superseded')
        self.request = None
        self.error = None
        self.last_valid = projection
        if self.observer is not None:
            self._observe('state_accepted', kind='full' if full else 'diff',
                          baseline=baseline,
                          **({'message': gs} if self._include_state_messages else {}))

    def _current(self, include_frontier_rows=False, include_decision_state=False):
        visible, hidden = [], {}
        for zone in self.zones.values():
            kind = zone.get('type')
            owner = zone.get('ownerSeatId')
            ids = zone.get('objectInstanceIds', [])
            if not isinstance(ids, list) or not all(_id(x) for x in ids):
                continue
            own_hand = kind == 'ZoneType_Hand' and owner == self.seat
            public_zone = kind in ('ZoneType_Battlefield', 'ZoneType_Stack', 'ZoneType_Graveyard')
            public_exile = kind == 'ZoneType_Exile' and zone.get('visibility') == 'Visibility_Public'
            for instance in ids:
                obj = self.objects.get(instance)
                if not isinstance(obj, dict):
                    label = f'{owner if owner in (1, 2) else "unknown"}:{kind}'
                    hidden[label] = hidden.get(label, 0) + 1
                    continue
                if obj.get('type') == 'GameObjectType_RevealedCard':
                    continue  # Opaque view: neither a physical card nor a hidden card count.
                can_see = (public_zone and obj.get('visibility') == 'Visibility_Public') or (
                    own_hand and (self.seat in obj.get('viewers', []) or
                                  obj.get('visibility') == 'Visibility_Public')) or (
                    public_exile and obj.get('type') == 'GameObjectType_Card' and
                    obj.get('zoneId') == zone.get('zoneId') and
                    obj.get('visibility') == 'Visibility_Public')
                if can_see:
                    # An ability/token group number is not established as an
                    # Arena card catalog ID. Preserve its visible instance.
                    visible.append({'id': instance, 'card_id': obj.get('grpId') if
                                    obj.get('type') == 'GameObjectType_Card' and _id(obj.get('grpId')) else None,
                                    'owner': obj.get('ownerSeatId') if _id(obj.get('ownerSeatId')) else None,
                                    'controller': obj.get('controllerSeatId') if _id(obj.get('controllerSeatId')) else None,
                                    'zone': kind, 'tapped': obj.get('isTapped') if type(obj.get('isTapped')) is bool else None})
                else:
                    label = f'{owner if owner in (1, 2) else "unknown"}:{kind}'
                    hidden[label] = hidden.get(label, 0) + 1
        request = copy.deepcopy(self.request)
        if request: request.pop('_target_evidence_interrupted', None)
        if request: request.pop('_cost_evidence_interrupted', None)
        if request: request.pop('_search_evidence_interrupted', None)
        if request: request.pop('_group_evidence_interrupted', None)
        if request and not include_decision_state:
            request.pop('_continuity_verified', None)
            request.pop('_request_parameters', None)
            request.pop('_multi_slot_cast', None)
        if request and isinstance(request.get('action_inventory'), dict):
            inventory = request['action_inventory']
            if include_frontier_rows:
                inventory['_frontier_request_identity'] = {
                    'generation': request['binding']['generation'],
                    'match': request['binding']['match'],
                    'game': request['binding']['game'],
                    'game_state_id': request['binding']['game_state_id'],
                    'self_seat': request['binding']['self_seat'],
                    'request_id': request['id'],
                }
            else:
                inventory.pop('_frontier_rows', None)
            request['action_inventory']['visible_source_links'] = (
                _join_action_sources_to_visible(request['action_inventory'], visible))
        return {'valid': True, 'match': self.match, 'game': self.game,
                'self_seat': self.seat, 'game_state_id': self.version,
                'source_state_timestamp': self.last_state_timestamp,
                'room_state': self.room_state,
                'game_stage': self.game_info.get('stage') if isinstance(self.game_info.get('stage'), str) else None,
                'turn': {k: self.turn.get(k) for k in ('turnNumber', 'activePlayer', 'decisionPlayer')},
                'players': [{'seat': s, 'life': p.get('lifeTotal') if type(p.get('lifeTotal')) is int else None}
                            for s, p in sorted(self.players.items()) if s in (1, 2)],
                'objects': sorted(visible, key=lambda obj: obj['id']), 'hidden_counts': hidden,
                'request': request, 'legal_actions': None,
                'submission': copy.deepcopy(self.submitted), 'mana': None, 'layout': None,
                'opportunity': None, 'rules': None, 'actionable': False,
                'unsupported_broadcast_requests': self.unsupported_broadcast_requests}

    def _cast_source_refs(self):
        """Narrow extra producer proofs for the explicit Cast profile only."""
        result = []
        for ref in self._reviewed_current_hand_refs():
            obj = self.objects[ref]; zone = self.zones[obj['zoneId']]
            viewers = zone.get('viewers')
            if (obj.get('visibility') in ('Visibility_Public', 'Visibility_Private') and
                    type(obj.get('controllerSeatId')) is int and obj['controllerSeatId'] == self.seat and
                    (zone.get('visibility') == 'Visibility_Public' or
                     zone.get('visibility') == 'Visibility_Private' and type(viewers) is list and
                     any(type(s) is int and s == self.seat for s in viewers))):
                result.append(ref)
        return result

    def _mana_source_refs(self):
        from .action_target_menus import public_battlefield_refs
        return [ref for ref in public_battlefield_refs(self) if
                self.objects[ref].get('type') == 'GameObjectType_Card' and
                type(self.objects[ref].get('ownerSeatId')) is int and self.objects[ref]['ownerSeatId'] == self.seat and
                type(self.objects[ref].get('controllerSeatId')) is int and self.objects[ref]['controllerSeatId'] == self.seat]

    def _reviewed_current_hand_refs(self):
        """Private producer proof; never expose other-player/hidden identities."""
        from collections import Counter
        memberships = Counter(ref for zone in self.zones.values()
            if type(zone.get('objectInstanceIds')) is list
            for ref in zone['objectInstanceIds'] if _id(ref))
        refs = []
        for zone in self.zones.values():
            if (zone.get('type') != 'ZoneType_Hand' or type(zone.get('ownerSeatId')) is not int or
                    zone['ownerSeatId'] != self.seat):
                continue
            for ref in zone.get('objectInstanceIds', []) if type(zone.get('objectInstanceIds')) is list else []:
                obj = self.objects.get(ref, {})
                viewers = obj.get('viewers', [])
                if (memberships[ref] == 1 and obj.get('type') == 'GameObjectType_Card' and
                        obj.get('zoneId') == zone.get('zoneId') and type(obj.get('zoneId')) is int and
                        type(obj.get('ownerSeatId')) is int and obj['ownerSeatId'] == self.seat and
                        (obj.get('visibility') == 'Visibility_Public' or type(viewers) is list and
                         any(type(seat) is int and seat == self.seat for seat in viewers))):
                    refs.append(ref)
        return refs

    def _public_stack(self, current):
        """Private literal membership staging; no top/resolution semantics.

        Missing membership in a replaced zone is unknown, unlike explicit [].
        Never publish a prefix or identifiers outside the visible projection.
        """
        result = {'availability': 'unknown', 'zone_id': None, 'members': None,
                  'order_basis': 'literal_gre_zone_objectInstanceIds'}
        zones = [z for z in self.zones.values() if z.get('type') == 'ZoneType_Stack']
        if len(zones) != 1 or zones[0].get('visibility') != 'Visibility_Public':
            return result
        zone = zones[0]
        ids = zone.get('objectInstanceIds')
        if (not _id(zone.get('zoneId')) or not isinstance(ids, list) or len(ids) > 512 or
                not all(_id(i) for i in ids) or len(set(ids)) != len(ids)):
            return result
        visible = {}
        for obj in current['objects']:
            visible.setdefault(obj['id'], []).append(obj)
        members = []
        for position, ident in enumerate(ids):
            matches = visible.get(ident, [])
            if len(matches) != 1 or matches[0]['zone'] != 'ZoneType_Stack':
                return result
            kind = self.objects[ident].get('type')
            members.append({'list_position': position, 'instance_id': ident,
                'object_type': kind if kind in ('GameObjectType_Card', 'GameObjectType_Ability',
                                               'GameObjectType_Token') else None})
        result.update(availability='observed' if members else 'confirmed_empty',
                      zone_id=zone['zoneId'], members=members)
        return result

    def document(self, include_frontier_rows=False, include_decision_state=False):
        current = self._current(include_frontier_rows, include_decision_state) if self.error is None and self.version is not None else {
            'valid': False, 'match': self.match, 'game': self.game,
            'self_seat': self.seat, 'game_state_id': self.version, 'actionable': False}
        if include_decision_state and current['valid']:
            # Private assembly facts; legacy raw/DecisionInput turn is unchanged.
            # Versioned assemblers validate these; the CLI removes the staging.
            current['_turn_context'] = {key: copy.deepcopy(self.turn.get(key))
                                       for key in ('phase', 'step', 'priorityPlayer')}
            current['_public_stack'] = self._public_stack(current)
            # Only the existing visible projection may admit a source object.
            # Rows omitted by a Diff remain reduced rows; a replaced row with
            # no stat has no value. No catalog, modifier or protobuf default.
            def literal(value):
                return value['value'] if (type(value) is dict and set(value) == {'value'} and
                    type(value['value']) is int and -2**31 <= value['value'] <= 2**31 - 1) else None
            current['_observed_combat_stats'] = [
                {'instance_id': obj['id'], 'effective_power': literal(raw.get('power')),
                 'effective_toughness': literal(raw.get('toughness'))}
                for obj in current['objects']
                if obj['zone'] == 'ZoneType_Battlefield' and
                (raw := self.objects[obj['id']]).get('type') in
                    ('GameObjectType_Card', 'GameObjectType_Token')]
        return {'current': current, 'last_valid': copy.deepcopy(self.last_valid),
                'first_error': copy.deepcopy(self.first_error), 'error': self.error}
