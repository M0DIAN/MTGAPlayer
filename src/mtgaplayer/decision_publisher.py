"""Poll-level read-only publication. No reader, reducer or request ledger.

Input is a completed watch observation plus bounded existing-reducer facts.
Only the final poll state is published; transient requests within a poll are
not exported as opportunities. Monotonic ages describe local observation only.
"""
import copy
import hashlib
import json
import re
import time
import uuid

from .decision_state import FLAGS, SCHEMA_VERSIONS, state_schema_version, _bound_readonly

EVENT_VERSION = 'mtgaplayer.decision-event.v1'
EVENT_VERSIONS = {1: EVENT_VERSION, 2: 'mtgaplayer.decision-event.v2'}
EVENT_STATE_VERSIONS = {EVENT_VERSIONS[key]: value for key, value in SCHEMA_VERSIONS.items()}
IDENTITY = ('source_generation', 'match', 'game', 'self_seat', 'game_state_id',
            'request_id', 'request_type')
MAX_AGE_NS = 86_400_000_000_000  # Consumer policy bound (24h), not protocol TTL.
STOP_REASONS = ('sample_limit', 'user_interrupt', 'source_error', 'other_supported_reason')


def _binding(document):
    state = document.get('decision_state')
    if isinstance(state, dict):
        return copy.deepcopy(state['binding'])
    current, source = document.get('current', {}), document.get('source', {})
    result = dict.fromkeys(IDENTITY)
    for key, value in (('source_generation', source.get('generation')),
                       ('game', current.get('game')), ('self_seat', current.get('self_seat')),
                       ('game_state_id', current.get('game_state_id'))):
        if (type(value) is int and value >= 0 and (key != 'self_seat' or value in (1, 2)) and
                (key != 'game' or value >= 1)):
            result[key] = value
    if isinstance(current.get('match'), str) and current['match']:
        result['match'] = current['match']
    return result


def _signature(state):
    value = copy.deepcopy(state)
    # Transport progress, history/append and finite-watch metadata never turn
    # an unchanged state/request into a new decision observation.
    for key in ('byte_offset', 'phase', 'stopped'):
        value['source'].pop(key, None)
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    allow_nan=False).encode()).digest()


class DecisionPublisher:
    """Consume completed observations; cache only the last published reference.

    RawReducer remains the authority for request consumption/supersession.
    An age limit revokes a consumer reference, without changing game continuity.
    No empty poll or retransmission can reactivate an expired reference.
    """

    def __init__(self, max_observation_age_ns=None, clock_ns=None, session_id=None, *, state_version=1):
        self.state_version = state_schema_version(state_version)
        self.event_version = EVENT_VERSIONS[state_version]
        if max_observation_age_ns is not None and (
                type(max_observation_age_ns) is not int or
                not 1 <= max_observation_age_ns <= MAX_AGE_NS):
            raise ValueError('invalid_observation_age_limit')
        self.session_id = session_id if session_id is not None else str(uuid.uuid4())
        if not isinstance(self.session_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', self.session_id):
            raise ValueError('invalid_publication_session_id')
        self.clock_ns = clock_ns or time.perf_counter_ns
        self.limit = max_observation_age_ns
        self.sequence = 0
        self.closed = False
        self._last_clock = None
        self._active = None
        self._last_signature = None
        self._snapshot_evidence_ns = None
        self._last_evidence = self._last_state = self._last_request = None
        self._recovering = False
        self._binding = dict.fromkeys(IDENTITY)
        self._phase = None
        self._status = 'no_observation'
        self._metadata = {}

    def _now(self):
        value = self.clock_ns()
        if type(value) is not int or value < 0 or self._last_clock is not None and value < self._last_clock:
            raise ValueError('publication_clock_not_monotonic')
        self._last_clock = value
        return value

    def _event(self, kind, **fields):
        self.sequence += 1
        return {'schema_version': self.event_version, 'session_id': self.session_id,
                'sequence': self.sequence, 'event_type': kind,
                'binding': copy.deepcopy(self._binding), 'phase': self._phase,
                'source_status': self._status, 'subscription_active': not self.closed,
                'read_only': True, 'execution': {'actionable': False,
                    'executor_connected': False, **FLAGS}, **fields}

    def _invalidate(self, events, reason):
        if self._active is not None:
            events.append(self._event('invalidate', revoked=self._active.copy(), reason=reason))
            self._active = None

    def _finish(self, events, started, liveness=False):
        now = self._now()
        age = None if self._snapshot_evidence_ns is None else now - self._snapshot_evidence_ns
        stale = None if age is None else self.limit is not None and age > self.limit
        if liveness:
            # Check at the publication timestamp, including assembler/publisher
            # work in the age; empty polls cannot reactivate an expired ref.
            if stale:
                self._invalidate(events, 'observation_stale')
            events.append(self._event('liveness', current_snapshot_ref=copy.deepcopy(self._active)))
        metadata = self._metadata
        timing = {'poll_started_ns': metadata.get('poll_started_ns'),
                  'poll_completed_ns': metadata.get('poll_completed_ns'),
                  'published_ns': now, 'last_new_evidence_ns': self._last_evidence,
                  'last_state_change_ns': self._last_state,
                  'last_request_change_ns': self._last_request,
                  'observation_age_ns': age, 'observation_age_limit_ns': self.limit,
                  'observation_stale': stale,
                  'poll_to_publish_ns': now - metadata['poll_started_ns'] if metadata else None,
                  'poll_read_ns': metadata.get('poll_read_ns'),
                  'reducer_apply_ns': metadata.get('reducer_apply_ns'),
                  'decision_state_assembly_ns': metadata.get('decision_state_assembly_ns'),
                  'event_publication_ns': now - started}
        for event in events:
            event['timing'] = timing.copy()
        return events

    def observe(self, document, metadata):
        """Return ordered events for one completed production watch poll.

        metadata contains scalar timings and fixed lifecycle facts only. New
        evidence excludes duplicate Full/Diff and request retransmissions.
        """
        if self.closed:
            raise ValueError('publication_session_stopped')
        started = self._now()
        for name in ('poll_started_ns', 'poll_completed_ns', 'poll_read_ns',
                     'reducer_apply_ns', 'decision_state_assembly_ns'):
            if type(metadata.get(name)) is not int or metadata[name] < 0:
                raise ValueError('invalid_poll_timing')
        if not metadata['poll_started_ns'] <= metadata['poll_completed_ns'] <= started:
            raise ValueError('invalid_poll_timing')
        self._metadata = metadata.copy()
        self._binding = _binding(document)
        self._phase = document['source']['phase']
        state = document.get('decision_state')
        if state is not None:
            identity = {'generation': self._binding['source_generation'],
                        **{k: self._binding[k] for k in IDENTITY if k not in ('source_generation', 'request_type')}}
            if (state.get('schema_version') != self.state_version or state.get('read_only') is not True or
                    not _bound_readonly(state, identity, self._binding['request_type'])):
                raise ValueError('invalid_decision_state_observation')
        self._status = (state['status'] if state is not None else
                        'partial' if document['source']['partial_record'] else 'invalid')
        observed = metadata['poll_completed_ns']
        if metadata.get('state_changed'):
            self._last_state = observed
        if metadata.get('request_changed'):
            self._last_request = observed
        if any(metadata.get(k) for k in ('state_changed', 'request_changed', 'reset', 'continuity_error')):
            self._last_evidence = observed
        events = []
        signature = _signature(state) if state is not None else None
        previous_binding = self._active['binding'] if self._active is not None else None
        reason = None
        if metadata.get('reset'):
            reason = 'source_reset'
        elif metadata.get('continuity_error'):
            reason = 'request_conflict' if metadata.get('request_conflict') else 'source_invalid'
        elif self._status == 'partial':
            reason = 'source_partial'
        elif state is None:
            reason = 'source_invalid'
        elif previous_binding is not None:
            if any(previous_binding[k] != self._binding[k] for k in
                   ('source_generation', 'match', 'game', 'self_seat')):
                reason = 'identity_changed'
            elif previous_binding['game_state_id'] != self._binding['game_state_id']:
                reason = 'state_advanced'
            elif previous_binding['request_id'] is not None and metadata.get('request_consumed'):
                reason = 'request_consumed'
            elif previous_binding['request_id'] != self._binding['request_id']:
                reason = 'request_replaced' if self._binding['request_id'] is not None else 'request_ended'
            elif signature != self._last_signature:
                reason = 'projection_changed'
        if reason is not None:
            self._invalidate(events, reason)
        if metadata.get('reset') or metadata.get('continuity_error') or state is None:
            self._recovering = True
        if state is not None and (signature != self._last_signature or self._recovering):
            self._snapshot_evidence_ns = self._last_evidence if self._last_evidence is not None else observed
            snapshot = self._event('snapshot', decision_state=copy.deepcopy(state),
                new_request_observed=(self._phase == 'append' and self._binding['request_id'] is not None and
                                      metadata.get('new_final_request') is True))
            self._active = {'session_id': self.session_id, 'sequence': snapshot['sequence'],
                            'binding': copy.deepcopy(self._binding)}
            snapshot['snapshot_ref'] = copy.deepcopy(self._active)
            events.append(snapshot)
            self._last_signature = signature
            self._recovering = False
        return self._finish(events, started, liveness=True)

    def stop(self, reason='sample_limit'):
        if reason not in STOP_REASONS:
            raise ValueError('unsupported_publication_stop_reason')
        if self.closed:
            return []
        started = self._now()
        self.closed = True
        self._status = 'stopped'
        events = []
        self._invalidate(events, 'session_stopped')
        events.append(self._event('stopped', reason=reason, current_snapshot_ref=None))
        return self._finish(events, started)
