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


def _id(value):
    return type(value) is int and 0 <= value <= 2**53 - 1


def _key(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()[:16] if isinstance(value, str) and value else None


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
    def __init__(self, path, max_history_bytes=64 * 1024 * 1024):
        self.path = Path(path)
        self.max_history_bytes = max_history_bytes
        self.identity = None
        self.offset = self.generation = 0
        self.prefix = self.anchor = b''
        self.anchor_start = 0
        self.framer = RawFramer()

    def poll(self):
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
            while remaining:
                chunk = stream.read(min(65536, remaining))
                if not chunk:
                    break
                records.extend(self.framer.feed(chunk))
                self.offset += len(chunk)
                remaining -= len(chunk)
            stream.seek(0)
            self.prefix = stream.read(min(256, self.offset))
            self.anchor_start = max(0, self.offset - 64)
            stream.seek(self.anchor_start)
            self.anchor = stream.read(self.offset - self.anchor_start)
        return reset, records


class RawReducer:
    def __init__(self):
        self.reset(0)

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
        self.submitted = None
        self.unsupported_broadcast_requests = 0

    def _invalidate(self, reason):
        if reason in ('room_seat_conflict', 'gre_recipient_or_self_seat_unverified',
                      'client_identity_changed', 'conflicting_duplicate_state'):
            self.conflict = True
        self.error = reason
        if self.first_error is None:
            self.first_error = {'reason': reason, 'generation': self.generation,
                                'match': self.match, 'game': self.game}

    def _boundary(self, match, game=None):
        if self.match is not None and self.game is not None:
            self.retired.add((self.match, self.game))
        self.match, self.game = match, game
        self.version = None
        self.objects, self.zones, self.players = {}, {}, {}
        self.turn, self.game_info = {}, {}
        self.request = None
        self.accepted_digest = None
        self.accepted_kind = None
        self.conflict = False
        self.consumed.clear()
        self.request_ids.clear()
        self.submitted = None
        self.unsupported_broadcast_requests = 0
        self.error = 'await_full_baseline'

    def apply(self, entry):
        if entry is None:
            self._invalidate('malformed_raw_record')
            return
        for field in ('authenticateResponse', 'matchGameRoomStateChangedEvent',
                      'greToClientEvent'):
            if field in entry and not isinstance(entry[field], dict):
                self._invalidate('invalid_' + field)
                return
        auth = entry.get('authenticateResponse')
        if isinstance(auth, dict) and isinstance(auth.get('clientId'), str):
            if self.client_id is not None and self.client_id != auth['clientId']:
                self._invalidate('client_identity_changed')
                self.room_seat = self.seat = None
            self.client_id = auth['clientId']
            if self.room_players is not None and self.room_seat is None:
                hits = [p.get('systemSeatId') for p in self.room_players if isinstance(p, dict) and
                        p.get('userId') == self.client_id]
                if len(hits) == 1 and type(hits[0]) is int and hits[0] in (1, 2):
                    self.room_seat = hits[0]
        payload = entry.get('payload')
        if (isinstance(payload, dict) and isinstance(payload.get('type'), str) and
                payload['type'].startswith('ClientMessageType_') and
                payload['type'].endswith('Resp') and _id(payload.get('respId'))):
            response_id = payload['respId']
            prior = self.request_ids.get(response_id)
            request_state = prior[0] if prior else None
            if request_state is not None and payload.get('gameStateId') == request_state:
                self.consumed.add((self.match, self.game, response_id))
                if self.request and self.request['id'] == response_id:
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
            if match is None:
                self._invalidate('room_identity_missing')
            else:
                if match != self.room_match and any(old_match == match for old_match, _ in self.retired):
                    return  # Late room completion cannot retire a newer match.
                if match != self.room_match:
                    self.room_match = match
                    self.room_seat = None
                    self._boundary(match)
                players = config.get('reservedPlayers')
                self.room_players = copy.deepcopy(players) if isinstance(players, list) else None
                hits = [p.get('systemSeatId') for p in players if isinstance(p, dict) and
                        p.get('userId') == self.client_id] if isinstance(players, list) and self.client_id else []
                if len(hits) == 1 and hits[0] in (1, 2) and type(hits[0]) is int:
                    if self.room_seat is not None and self.room_seat != hits[0]:
                        self._invalidate('room_seat_conflict')
                    else:
                        self.room_seat = hits[0]
                else:
                    self._invalidate('self_seat_unverified')
                self.room_state = info.get('stateType') if isinstance(info.get('stateType'), str) else None
        gre = entry.get('greToClientEvent')
        if isinstance(gre, dict):
            messages = gre.get('greToClientMessages')
            if not isinstance(messages, list):
                self._invalidate('invalid_gre_messages')
                return
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
        if state is None and recipients != [self.room_seat]:
            if isinstance(recipients, list) and self.room_seat in recipients:
                self.unsupported_broadcast_requests += 1
            return  # Broadcast and other-seat prompts are not own requests.
        if recipients != [self.room_seat] or self.room_seat not in (1, 2):
            self._invalidate('gre_recipient_or_self_seat_unverified')
            return
        self.seat = self.room_seat
        if state is not None:
            self._state(state, timestamp)
        if is_request:
            msg_id, state_id = message.get('msgId'), message.get('gameStateId')
            if not _id(msg_id) or not _id(state_id):
                self._invalidate('request_identity_missing')
                return
            digest = hashlib.sha256(json.dumps(message, sort_keys=True,
                        separators=(',', ':')).encode('utf-8')).digest()
            prior = self.request_ids.get(msg_id)
            if prior is not None and prior != (state_id, message['type'], digest):
                self._invalidate('conflicting_request_identity')
                self.conflict = True
                return
            self.request_ids[msg_id] = (state_id, message['type'], digest)
            if (state_id == self.version and self.error is None and
                    (self.match, self.game, msg_id) not in self.consumed):
                self.request = {'id': msg_id, 'type': message['type'],
                                'game_state_id': state_id, 'current': True,
                                'supported': False}

    def _state(self, gs, timestamp):
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
        if (match, game) in self.retired:
            return
        if match != self.room_match or not _id(game) or game < 1:
            self._invalidate('game_identity_unverified')
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
            for zone_id, zone in zones.items():
                ids = zone.get('objectInstanceIds', [])
                if not isinstance(ids, list) or not all(_id(x) for x in ids) or len(ids) != len(set(ids)):
                    raise ValueError('invalid_zone_membership')
                if any(instance in objects and objects[instance].get('zoneId') != zone_id for instance in ids):
                    raise ValueError('object_zone_conflict')
            turn = copy.deepcopy(gs.get('turnInfo', self.turn if not full else {}))
            game_info = copy.deepcopy(info if info is not None else self.game_info)
            if not isinstance(turn, dict) or not isinstance(game_info, dict):
                raise ValueError('invalid_state_fields')
            if full:
                kinds = {z.get('type') for z in zones.values()}
                if not ({1, 2} <= set(players) and
                        {'ZoneType_Battlefield', 'ZoneType_Stack', 'ZoneType_Hand'} <= kinds and
                        any(z.get('type') == 'ZoneType_Hand' and z.get('ownerSeatId') == self.seat
                            for z in zones.values())):
                    raise ValueError('incomplete_full_schema')
        except ValueError as exc:
            self._invalidate(str(exc))
            return
        self.objects, self.zones, self.players = objects, zones, players
        self.turn, self.game_info = turn, game_info
        self.version = version
        self.accepted_digest = digest
        self.accepted_kind = 'full' if full else 'diff'
        self.last_state_timestamp = timestamp if isinstance(timestamp, (str, int)) else None
        self.request = None
        self.error = None
        self.last_valid = self._current()

    def _current(self):
        visible, hidden = [], {}
        for zone in self.zones.values():
            kind = zone.get('type')
            owner = zone.get('ownerSeatId')
            ids = zone.get('objectInstanceIds', [])
            if not isinstance(ids, list) or not all(_id(x) for x in ids):
                continue
            own_hand = kind == 'ZoneType_Hand' and owner == self.seat
            public_zone = kind in ('ZoneType_Battlefield', 'ZoneType_Stack', 'ZoneType_Graveyard')
            for instance in ids:
                obj = self.objects.get(instance)
                if not isinstance(obj, dict):
                    label = f'{owner if owner in (1, 2) else "unknown"}:{kind}'
                    hidden[label] = hidden.get(label, 0) + 1
                    continue
                can_see = (public_zone and obj.get('visibility') == 'Visibility_Public') or (
                    own_hand and (self.seat in obj.get('viewers', []) or
                                  obj.get('visibility') == 'Visibility_Public'))
                if can_see:
                    visible.append({'id': instance, 'card_id': obj.get('grpId') if _id(obj.get('grpId')) else None,
                                    'owner': obj.get('ownerSeatId') if _id(obj.get('ownerSeatId')) else None,
                                    'controller': obj.get('controllerSeatId') if _id(obj.get('controllerSeatId')) else None,
                                    'zone': kind, 'tapped': obj.get('isTapped') if type(obj.get('isTapped')) is bool else None})
                else:
                    label = f'{owner if owner in (1, 2) else "unknown"}:{kind}'
                    hidden[label] = hidden.get(label, 0) + 1
        return {'valid': True, 'match': self.match, 'game': self.game,
                'self_seat': self.seat, 'game_state_id': self.version,
                'source_state_timestamp': self.last_state_timestamp,
                'room_state': self.room_state,
                'game_stage': self.game_info.get('stage') if isinstance(self.game_info.get('stage'), str) else None,
                'turn': {k: self.turn.get(k) for k in ('turnNumber', 'activePlayer', 'decisionPlayer')},
                'players': [{'seat': s, 'life': p.get('lifeTotal') if _id(p.get('lifeTotal')) else None}
                            for s, p in sorted(self.players.items()) if s in (1, 2)],
                'objects': sorted(visible, key=lambda obj: obj['id']), 'hidden_counts': hidden,
                'request': copy.deepcopy(self.request), 'legal_actions': None,
                'submission': copy.deepcopy(self.submitted), 'mana': None, 'layout': None,
                'opportunity': None, 'rules': None, 'actionable': False,
                'unsupported_broadcast_requests': self.unsupported_broadcast_requests}

    def document(self):
        current = self._current() if self.error is None and self.version is not None else {
            'valid': False, 'match': self.match, 'game': self.game,
            'self_seat': self.seat, 'game_state_id': self.version, 'actionable': False}
        return {'current': current, 'last_valid': copy.deepcopy(self.last_valid),
                'first_error': copy.deepcopy(self.first_error), 'error': self.error}
