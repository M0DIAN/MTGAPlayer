"""Schema 1 normalized input: explicit begin, full/diff, request, response.

All state mutations are transactional; projection strips hidden identities.
Source rotation invalidates the baseline. A heartbeat never repairs an error.
"""
import copy
import time


class StateError(ValueError):
    pass


def require(test, reason):
    if not test:
        raise StateError(reason)


def integer(value):
    return type(value) is int and value >= 0


class Reducer:
    def __init__(self, max_age=3.0):
        self.max_age = max_age
        self.generation = 0
        self.identity = None
        self.state_seat = None
        self.retired = set()
        self.state = None
        self.last_valid = None
        self.first_error = None
        self.error = 'no_baseline'
        self.conflict = None
        self.ledger = {}
        self.requests = {}
        self.last_observed = None

    def reset(self, generation):
        self.generation = generation
        self.identity = self.state = None
        self.state_seat = self.last_observed = None
        self.retired.clear()
        self.ledger.clear()
        self.requests.clear()
        self.conflict = None
        self.error = 'source_generation_changed'

    def invalidate(self, reason):
        reason = str(reason)
        if reason in {'same_game_seat_conflict', 'identity_without_begin',
                      'conflicting_duplicate_state', 'conflicting_request_identity'}:
            self.conflict = self.conflict or reason
        # Corruption or late traffic must not downgrade a conflicting binding.
        self.error = self.conflict or reason
        if self.first_error is None:
            self.first_error = {'reason': str(reason), 'generation': self.generation,
                                'identity': self.identity, 'at': time.monotonic()}

    def key(self, request=None):
        req = request or (self.state or {}).get('request')
        return (self.generation, *(self.identity or (None, None)), req['id']) if req else None

    def consume(self, status):
        require(status in {'executing', 'confirmed', 'uncertain', 'cancelled', 'paused',
                           'unsupported', 'timeout', 'fail'}, 'ledger_status')
        key = self.key()
        if key:
            self.ledger[key] = status

    def apply(self, event, now=None):
        now = time.monotonic() if now is None else now
        saved_requests = self.requests.copy()
        try:
            if isinstance(event, Exception):
                raise StateError(str(event))
            require(event.get('schema') == 1, 'unsupported_schema')
            kind = event.get('type')
            if kind == 'heartbeat':
                return
            ident = (event.get('match'), event.get('game'))
            require(all(isinstance(x, str) and 0 < len(x) <= 128 for x in ident), 'missing_identity')
            if ident in self.retired:
                return  # Explicitly retired prior games cannot reopen from late traffic.
            if kind == 'begin':
                if ident == self.identity:
                    require(type(event.get('self_seat')) is int and event['self_seat'] == self.state_seat,
                            'same_game_seat_conflict')
                    return
                require(event.get('self_seat') in (1, 2) and type(event['self_seat']) is int,
                        'invalid_self_seat')
                if self.identity:
                    self.retired.add(self.identity)
                self.identity, self.state_seat = ident, event['self_seat']
                self.state = None
                self.last_observed = None
                self.conflict = None
                self.error = 'await_full_baseline'
                return
            require(ident == self.identity, 'identity_without_begin')
            require(type(event.get('self_seat')) is int and event['self_seat'] == self.state_seat,
                    'same_game_seat_conflict')
            require(self.conflict is None, self.conflict)
            if kind == 'response':
                req = event.get('request_id')
                require(isinstance(req, str), 'missing_response_identity')
                self.ledger[(self.generation, *ident, req)] = 'confirmed'
                if self.state and (self.state.get('request') or {}).get('id') == req:
                    self.state = {**self.state, 'request': None}
                return
            require(kind in {'full', 'diff', 'request'}, 'unsupported_event')
            require(integer(event.get('state_version')), 'missing_state_version')
            version = event['state_version']
            old_version = self.state['state_version'] if self.state else None
            if kind == 'request':
                require(self.state is not None and not self.error and version == old_version,
                        'request_without_current_state')
                candidate = copy.deepcopy(self.state)
                candidate['request'] = self._request(event.get('request'), now)
                candidate = self._project(candidate, candidate.get('hidden_counts'))
            else:
                require(old_version is None or version >= old_version, 'state_rollback')
                if kind == 'diff':
                    require(self.state is not None and not self.error and
                            event.get('previous') == old_version and version > old_version, 'state_gap')
                    changes = event.get('changes')
                    require(isinstance(changes, dict) and not (set(changes) - {
                        'objects', 'mana', 'land_plays', 'phase', 'priority', 'effects',
                        'request', 'layout', 'outcome'}), 'invalid_diff_fields')
                    candidate = copy.deepcopy(self.state)
                    # Objects are complete replacements, never guessed field patches.
                    candidate.update(copy.deepcopy(changes))
                    candidate['state_version'] = version
                else:
                    candidate = {k: copy.deepcopy(event.get(k)) for k in
                                 ('objects', 'mana', 'land_plays', 'phase', 'priority',
                                  'effects', 'request', 'layout', 'outcome')}
                    candidate['state_version'] = version
                candidate['request'] = self._request(candidate.get('request'), now)
                kept_counts = (self.state.get('hidden_counts') if kind == 'diff' and
                               'objects' not in changes else None)
                candidate = self._project(candidate, kept_counts)
                if old_version == version:
                    require(candidate == self.state, 'conflicting_duplicate_state')
                    if not self.error:
                        return
                    # An identical complete baseline can repair corruption or a
                    # gap, but cannot replace an accepted version or a conflict.
            self.state = candidate
            self.error = None
            self.last_observed = now
            self.last_valid = copy.deepcopy(self._view(now))
        except (StateError, TypeError, KeyError, AttributeError) as exc:
            self.requests = saved_requests
            self.invalidate(str(exc) if isinstance(exc, StateError) else 'malformed_schema')

    def _request(self, req, now):
        if req is None:
            return None
        require(isinstance(req, dict) and isinstance(req.get('id'), str) and bool(req['id']),
                'missing_request_identity')
        # Root opportunity is defined by the producer; a child target request
        # retains the same opportunity and starts no new semantic-action timer.
        fields = {k: copy.deepcopy(req.get(k)) for k in
                  ('id', 'kind', 'opportunity_id', 'opportunity_at', 'root', 'source', 'targets')}
        key = self.key(fields)
        prior = self.requests.get(key)
        if prior:
            require({k: v for k, v in prior.items() if k != 'received_at'} == fields,
                    'conflicting_request_identity')
            return copy.deepcopy(prior)
        fields['received_at'] = now
        self.requests[key] = copy.deepcopy(fields)
        return fields

    def _project(self, state, kept_counts=None):
        objects = state.get('objects')
        require(isinstance(objects, list), 'missing_objects')
        visible, counts, ids = [], copy.deepcopy(kept_counts) if kept_counts else {}, set()
        for obj in objects:
            require(isinstance(obj, dict) and integer(obj.get('id')) and obj['id'] not in ids,
                    'invalid_object_identity')
            ids.add(obj['id'])
            zone, owner = obj.get('zone'), obj.get('owner')
            require(type(owner) is int and owner in (1, 2), 'unknown_object_owner')
            public = obj.get('visibility') == 'public' and zone in {'battlefield', 'graveyard', 'stack'}
            own_hand = zone == 'hand' and owner == self.state_seat and obj.get('visibility') == 'self'
            if public or own_hand:
                visible.append({k: copy.deepcopy(obj.get(k)) for k in
                                ('id', 'owner', 'zone', 'visibility', 'rule', 'hp', 'tapped')})
            else:
                label = f'{owner}:{zone}'
                counts[label] = counts.get(label, 0) + 1
        state['objects'], state['hidden_counts'] = visible, counts
        visible_ids = {o['id'] for o in visible}
        req = state.get('request')
        if req:
            require(req.get('source') is None or req['source'] in visible_ids,
                    'request_source_not_visible')
            require(req.get('targets') is None or (isinstance(req['targets'], list) and
                    all(integer(i) and i in visible_ids for i in req['targets'])),
                    'request_targets_not_visible')
        effects = state.get('effects')
        require(effects is None or (isinstance(effects, list) and
                all(isinstance(e, str) for e in effects)), 'invalid_effect_labels')
        outcome = state.get('outcome')
        if outcome is not None:
            require(isinstance(outcome, dict), 'invalid_outcome')
            state['outcome'] = {k: copy.deepcopy(outcome.get(k)) for k in
                                ('root', 'opportunity_id', 'action', 'source', 'target', 'accepted_at')}
            require(all(state['outcome'][k] is None or state['outcome'][k] in visible_ids
                        for k in ('source', 'target')), 'outcome_identity_not_visible')
        for field in ('mana', 'land_plays', 'phase', 'priority', 'effects', 'layout', 'outcome'):
            state.setdefault(field, None)  # None is unknown; never a game-rule default.
        return state

    def _view(self, now):
        return {'schema_version': 1, 'source_generation': self.generation,
                'match': self.identity[0] if self.identity else None,
                'game': self.identity[1] if self.identity else None,
                'self_seat': getattr(self, 'state_seat', None),
                'last_observed': self.last_observed, **(copy.deepcopy(self.state) if self.state else {}),
                'valid_until': self.last_observed + self.max_age if self.last_observed is not None else None,
                'missing_fields': [k for k in ('mana', 'land_plays', 'phase', 'priority', 'effects', 'layout')
                                   if not self.state or self.state.get(k) is None],
                'valid': self.state is not None and self.error is None and
                         self.last_observed is not None and now - self.last_observed <= self.max_age}

    def document(self, now=None):
        now = time.monotonic() if now is None else now
        view = self._view(now)
        if not view['valid']:
            # No stale objects/request at the actionable boundary.
            view = {k: view[k] for k in ('schema_version', 'source_generation', 'match',
                                        'game', 'self_seat', 'last_observed', 'valid_until',
                                        'missing_fields', 'valid')}
        return {'current': view, 'last_valid': copy.deepcopy(self.last_valid),
                'first_error': self.first_error, 'error': self.error or
                ('expired_state' if not view['valid'] else None)}

    def actionable(self, now=None):
        now = time.monotonic() if now is None else now
        view = self.document(now)['current']
        req = view.get('request')
        return bool(view['valid'] and req and self.key(req) not in self.ledger and
                    now - req['received_at'] <= self.max_age)
