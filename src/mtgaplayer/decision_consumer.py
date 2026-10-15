"""Bounded, fail-closed DecisionEvent v1 consumption; no GRE or input adapter.

The schemas remain the formal Draft 2020-12 contracts. These stdlib checks
cover the consumer's supported shapes and safety/identity invariants, not a
general JSON Schema implementation. Local leases are policy, not server TTLs.
"""
import copy
import json
import math
import os
import queue
import re
import threading
import time
from collections import deque

from .decision_publisher import EVENT_VERSION, IDENTITY, MAX_AGE_NS, STOP_REASONS
from .decision_state import FLAGS, KINDS, SCHEMA_VERSION, _bound_readonly

MAX_LINE_BYTES = 2 * 1024 * 1024
MAX_ID = 9_007_199_254_740_991
INVALIDATE_REASONS = ('source_reset', 'source_invalid', 'request_conflict',
    'source_partial', 'identity_changed', 'state_advanced', 'request_consumed',
    'request_replaced', 'request_ended', 'projection_changed',
    'observation_stale', 'session_stopped')
STATUSES = ('state_and_request_observed', 'state_observed_without_request')
EXECUTION = {'actionable': False, 'executor_connected': False, **FLAGS}
TIMINGS = ('poll_started_ns', 'poll_completed_ns', 'published_ns',
    'last_new_evidence_ns', 'last_state_change_ns', 'last_request_change_ns',
    'observation_age_ns', 'observation_age_limit_ns', 'observation_stale',
    'poll_to_publish_ns', 'poll_read_ns', 'reducer_apply_ns',
    'decision_state_assembly_ns', 'event_publication_ns')
COMMON = ('schema_version', 'session_id', 'sequence', 'event_type', 'binding',
    'phase', 'source_status', 'subscription_active', 'timing', 'read_only', 'execution')
EXTRAS = {'snapshot': ('snapshot_ref', 'decision_state', 'new_request_observed'),
    'invalidate': ('revoked', 'reason'), 'liveness': ('current_snapshot_ref',),
    'stopped': ('current_snapshot_ref', 'reason')}


def _require(condition):
    if not condition:
        raise ValueError('invalid_event_contract')


def _keys(value, required, optional=()):
    _require(type(value) is dict and set(required) <= value.keys() <= set(required) | set(optional))


def _integer(value, minimum=0, maximum=MAX_ID, nullable=False):
    _require(nullable and value is None or
             type(value) is int and minimum <= value <= maximum)


def _string(value, nullable=False):
    _require(nullable and value is None or type(value) is str and 0 < len(value) <= 4096)


def _list(value, maximum=512):
    _require(type(value) is list and len(value) <= maximum)


def _binding(value, complete=False):
    _keys(value, IDENTITY)
    for key in ('source_generation', 'game_state_id', 'request_id'):
        _integer(value[key], nullable=not complete or key == 'request_id')
    _integer(value['game'], 1, nullable=not complete)
    _require(value['self_seat'] is None and not complete or
             type(value['self_seat']) is int and value['self_seat'] in (1, 2))
    _string(value['match'], nullable=not complete)
    _string(value['request_type'], nullable=True)
    _require((value['request_id'] is None) == (value['request_type'] is None))


def _session(value):
    _require(type(value) is str and re.fullmatch(r'[A-Za-z0-9_-]{1,64}', value) is not None)


def _reference(value, session, sequence, snapshot=False):
    _keys(value, ('session_id', 'sequence', 'binding'))
    _session(value['session_id'])
    _integer(value['sequence'], 1)
    _require(value['session_id'] == session and
             (value['sequence'] == sequence if snapshot else value['sequence'] < sequence))
    _binding(value['binding'], complete=True)


def _bounded_json(value):
    # Check before recursion/deepcopy: reject cycles, non-JSON objects, huge or
    # deep graphs, and nonfinite values even in extensible legacy parameters.
    stack, nodes, size = [(value, 0)], 0, 0
    while stack:
        node, depth = stack.pop()
        nodes += 1
        _require(depth <= 32 and nodes <= 50_000)
        if type(node) is dict:
            _require(all(type(k) is str for k in node))
            size += sum(len(k.encode('utf-8')) for k in node)
            stack.extend((v, depth + 1) for v in node.values())
        elif type(node) is list:
            _require(len(node) <= 4096)
            stack.extend((v, depth + 1) for v in node)
        elif type(node) is str:
            size += len(node.encode('utf-8'))
        else:
            _require(node is None or type(node) in (bool, int, float))
            if type(node) is float:
                _require(math.isfinite(node))
            if type(node) is int:
                _require(node.bit_length() <= 64)
            size += 8
        _require(size <= MAX_LINE_BYTES)


def _state(value, binding):
    _keys(value, ('schema_version', 'status', 'binding', 'source', 'game',
        'visible_objects', 'card_knowledge', 'effect_claims', 'legal_action_space',
        'unresolved', 'execution', 'read_only'))
    _require(value['schema_version'] == SCHEMA_VERSION and value['status'] in STATUSES)
    _binding(value['binding'], complete=True)
    _require(value['binding'] == binding and value['read_only'] is True and value['execution'] == EXECUTION)
    source = value['source']
    _keys(source, ('format', 'mode', 'byte_offset', 'phase', 'stopped',
        'partial_record', 'freshness_verified', 'snapshot_scope'))
    _require(source['format'] == 'player-log-gre-v1' and source['mode'] in ('offline', 'watch') and
             source['phase'] in (None, 'history', 'append') and
             (source['stopped'] is None or type(source['stopped']) is bool) and
             source['partial_record'] is False and source['freshness_verified'] is False and
             source['snapshot_scope'] == 'single_reducer_document')
    _integer(source['byte_offset'], nullable=True)
    game = value['game']
    _keys(game, ('room_state', 'game_stage', 'source_state_timestamp', 'turn', 'players',
        'hidden_counts', 'mana', 'effective_combat_stats', 'rules'))
    for key in ('room_state', 'game_stage', 'source_state_timestamp'):
        _require(game[key] is None or type(game[key]) is str)
    _keys(game['turn'], ('turnNumber', 'activePlayer', 'decisionPlayer'))
    for number in game['turn'].values():
        _integer(number, -MAX_ID, nullable=True)
    _list(game['players'], 2)
    for player in game['players']:
        _keys(player, ('seat', 'life'))
        _integer(player['seat'], 1, 2)
        _integer(player['life'], -MAX_ID, nullable=True)
    _require(type(game['hidden_counts']) is dict)
    for count in game['hidden_counts'].values():
        _integer(count)
    _require(all(game[k] is None for k in ('mana', 'effective_combat_stats', 'rules')) and
             value['effect_claims'] is None)
    _list(value['visible_objects'])
    for obj in value['visible_objects']:
        _keys(obj, ('instance_id', 'card_id', 'zone', 'owner_seat', 'controller_seat',
            'tapped', 'effective_power', 'effective_toughness'))
        _integer(obj['instance_id'])
        _integer(obj['card_id'], nullable=True)
        for key in ('owner_seat', 'controller_seat'):
            _integer(obj[key], 1, 2, nullable=True)
        _require((obj['zone'] is None or type(obj['zone']) is str) and
                 (obj['tapped'] is None or type(obj['tapped']) is bool) and
                 obj['effective_power'] is None and obj['effective_toughness'] is None)
    cards = value['card_knowledge']
    if cards is not None:
        _keys(cards, ('source', 'objects'))
        _require(cards['source'] == 'local_catalog_static_only')
        _list(cards['objects'])
        for card in cards['objects']:
            _keys(card, ('instance_id', 'card_id', 'knowledge'))
            _integer(card['instance_id'])
            _integer(card['card_id'], nullable=True)
            knowledge = card['knowledge']
            _keys(knowledge, ('status',), ('name', 'set_code', 'collector_number', 'static_catalog_stats'))
            _require(knowledge['status'] in ('resolved', 'unresolved', 'ambiguous', 'missing_card_id'))
            for key in ('name', 'set_code', 'collector_number'):
                if key in knowledge:
                    _require(type(knowledge[key]) is str or key != 'name' and knowledge[key] is None)
            if 'static_catalog_stats' in knowledge:
                stats = knowledge['static_catalog_stats']
                _keys(stats, ('power', 'toughness', 'source', 'effective_in_game', 'rules_verified'))
                for key in ('power', 'toughness'):
                    _integer(stats[key], -MAX_ID, nullable=True)
                _require(stats['source'] == 'Cards.Power/Toughness' and
                         stats['effective_in_game'] is False and stats['rules_verified'] is False)
    _list(value['unresolved'], 4096)
    _require(all(type(v) is str for v in value['unresolved']))
    space = value['legal_action_space']
    _keys(space, ('request_type', 'immediate_frontier', 'choice_graph', 'expanded_plans'))
    _require(space['request_type'] == binding['request_type'])
    _keys(space['expanded_plans'], ('completeness', 'plans'))
    _require(space['expanded_plans'] == {'completeness': 'unknown', 'plans': None})
    frontier = space['immediate_frontier']
    _keys(frontier, ('kind', 'availability', 'completeness', 'projection'))
    kind, availability, projection = (frontier[k] for k in ('kind', 'availability', 'projection'))
    _require(kind == KINDS.get(binding['request_type']) and
             availability in ('observed', 'confirmed_empty', 'unknown', 'not_provided', 'unsupported', 'not_applicable') and
             frontier['completeness'] in ('partial', 'unknown'))
    if kind is None:
        _require(projection is None and frontier['completeness'] == 'unknown')
    if availability in ('observed', 'confirmed_empty'):
        _require(type(projection) is dict and frontier['completeness'] == 'partial')
    else:
        _require(frontier['completeness'] == 'unknown')
    if projection is not None:
        _projection(projection, kind, availability)
    graph = space['choice_graph']
    if graph is not None:
        _require(kind == 'actions_available')
        _keys(graph, ('schema_version', 'request_identity', 'action_nodes', 'completeness',
            'read_only', 'legal_choice_verified', 'response_encoding_verified', 'execution_ready', 'input_sent'),
            tuple(graph))  # Legacy projections are extensible by contract.
        _require(graph['schema_version'] == 'mtga-choice-graph-v1' and graph['completeness'] in ('partial', 'unknown'))
        _list(graph['action_nodes'], 256)
        for node in graph['action_nodes']:
            _keys(node, ('action_key', 'constraints', 'legal_choice_verified',
                'response_encoding_verified', 'execution_ready', 'input_sent'), tuple(node))
            _action_key(node['action_key'])
            _list(node['constraints'], 4096)
            _require(all(type(v) is dict for v in node['constraints']))
    has_request = binding['request_id'] is not None
    _require((value['status'] == STATUSES[0]) == has_request)
    if not has_request:
        _require(kind is None and availability == 'not_provided' and graph is None)


def _action_key(value):
    _keys(value, ('request_identity', 'list_position'), tuple(value))
    _integer(value['list_position'])


def _projection(value, kind, availability):
    _require(type(value) is dict)
    if kind == 'select_n':
        _keys(value, ('offered_instance_ids', 'max_sel_raw', 'min_sel_verified',
            'combinations_complete', 'source_ids_not_visibility_joined'))
        _list(value['offered_instance_ids'], 256)
        for ident in value['offered_instance_ids']:
            _integer(ident)
        _integer(value['max_sel_raw'], -MAX_ID, nullable=True)
        _require(value['min_sel_verified'] is None and value['combinations_complete'] is False and
                 value['source_ids_not_visibility_joined'] is True)
        rows = value['offered_instance_ids']
    elif kind == 'actions_available':
        _keys(value, ('schema', 'request_identity', 'templates', 'immediate_completeness',
            'expanded_choice_completeness', 'read_only', 'actionable', 'input_sent'), tuple(value))
        _require(value['schema'] == 'mtga-action-frontier-v1' and
                 value['immediate_completeness'] in ('partial', 'unknown') and
                 value['expanded_choice_completeness'] == 'unknown')
        rows = value['templates']
        if rows is not None:
            _list(rows, 256)
            for row in rows:
                _keys(row, ('action_key', 'request_identity', 'list_position', 'engine_action_type',
                    'engine_offered', 'observed_parameter_shapes', 'unresolved_parameters',
                    'legal_choice_verified', 'response_encoding_verified', 'execution_ready',
                    'actionable', 'input_sent'), tuple(row))
                _action_key(row['action_key'])
                _integer(row['list_position'])
                _require(row['list_position'] == row['action_key']['list_position'] and
                         type(row['engine_action_type']) is str and row['engine_offered'] is True and
                         type(row['observed_parameter_shapes']) is dict)
                _list(row['unresolved_parameters'], 4096)
                _require(all(type(v) is str for v in row['unresolved_parameters']))
        if availability == 'confirmed_empty':
            _require(type(value.get('engine_active_action_count')) is int and value['engine_active_action_count'] == 0)
    else:
        _require(kind in ('declare_attackers', 'declare_blockers'))
        _keys(value, ('schema', 'request_identity', 'combat_request_type', 'engine_offered_candidates',
            'completeness', 'known_constraints', 'read_only', *FLAGS), tuple(value))
        _require(value['schema'] == 'mtga-combat-frontier-v1' and
                 KINDS.get(value['combat_request_type']) == kind and
                 value['completeness'] in ('partial', 'unknown') and value['known_constraints'] == [])
        rows = value['engine_offered_candidates']
        if rows is not None:
            _list(rows, 256)
            for row in rows:
                _keys(row, ('candidate_key', 'candidate_position', 'candidate_instance_id',
                    'reference_verified', *FLAGS), tuple(row))
                _keys(row['candidate_key'], ('request_identity', 'candidate_position'), tuple(row['candidate_key']))
                _integer(row['candidate_position'])
                _integer(row['candidate_key']['candidate_position'])
                _integer(row['candidate_instance_id'], nullable=True)
                _require(row['candidate_position'] == row['candidate_key']['candidate_position'] and
                         type(row['reference_verified']) is bool)
        if availability == 'confirmed_empty':
            _require(type(value.get('observed_candidate_count')) is int and value['observed_candidate_count'] == 0)
    if availability == 'confirmed_empty':
        _require(rows == [])


def _validate(event):
    _bounded_json(event)
    _require(type(event) is dict and type(event.get('event_type')) is str and event['event_type'] in EXTRAS)
    kind = event['event_type']
    _keys(event, COMMON + EXTRAS[kind])
    _require(event['schema_version'] == EVENT_VERSION)
    _session(event['session_id'])
    _integer(event['sequence'], 1)
    _binding(event['binding'])
    _require(event['phase'] in (None, 'history', 'append') and
             event['source_status'] in ('no_observation', *STATUSES, 'partial', 'invalid', 'stopped') and
             type(event['subscription_active']) is bool and event['read_only'] is True)
    _keys(event['execution'], EXECUTION)
    identity = {'generation': event['binding']['source_generation'],
        **{k: event['binding'][k] for k in IDENTITY if k not in ('source_generation', 'request_type')}}
    _require(_bound_readonly(event, identity, event['binding']['request_type']))
    timing = event['timing']
    _keys(timing, TIMINGS)
    for key in TIMINGS:
        if key == 'observation_stale':
            _require(timing[key] is None or type(timing[key]) is bool)
        else:
            _integer(timing[key], maximum=(MAX_AGE_NS if key == 'observation_age_limit_ns' else 2**64 - 1),
                     minimum=1 if key == 'observation_age_limit_ns' else 0,
                     nullable=key not in ('published_ns', 'event_publication_ns'))
    if kind == 'snapshot':
        _reference(event['snapshot_ref'], event['session_id'], event['sequence'], snapshot=True)
        _state(event['decision_state'], event['binding'])
        _require(event['snapshot_ref']['binding'] == event['binding'] and
                 event['source_status'] == event['decision_state']['status'] and
                 event['phase'] == event['decision_state']['source']['phase'] and
                 event['subscription_active'] is True and type(event['new_request_observed']) is bool and
                 (not event['new_request_observed'] or event['phase'] == 'append' and event['binding']['request_id'] is not None) and
                 timing['observation_age_ns'] is not None)
    elif kind == 'invalidate':
        # The outer binding can belong to the *next* state. Do not recursively
        # compare the revoked snapshot binding to that outer identity.
        _reference(event['revoked'], event['session_id'], event['sequence'])
        _require(event['reason'] in INVALIDATE_REASONS)
        _require(event['subscription_active'] is (event['reason'] != 'session_stopped'))
        if event['reason'] == 'session_stopped':
            _require(event['source_status'] == 'stopped')
    else:
        ref = event['current_snapshot_ref']
        if ref is not None:
            _reference(ref, event['session_id'], event['sequence'])
        if kind == 'liveness':
            _require(event['subscription_active'] is True)
        else:
            _require(ref is None and event['reason'] in STOP_REASONS and
                     event['subscription_active'] is False and event['source_status'] == 'stopped')


class DecisionConsumer:
    """One explicit subscription. STALE/errors/close require a new instance.

    accept_event returns False on rejection; all diagnostics are bounded reason
    codes. current_view returns a detached dictionary and checks local leases.
    Default five-second limits are consumer policy, never MTGA protocol TTLs.
    """

    def __init__(self, max_event_silence_ns=5_000_000_000,
                 max_observation_age_ns=5_000_000_000, clock_ns=None):
        for value in (max_event_silence_ns, max_observation_age_ns):
            if type(value) is not int or not 1 <= value <= MAX_AGE_NS:
                raise ValueError('invalid_consumer_lease')
        self._clock = clock_ns or time.perf_counter_ns
        self._last_clock = None
        self._silence_limit, self._age_limit = max_event_silence_ns, max_observation_age_ns
        self._session = None
        self._sequence = 0
        self._ref = self._state = None
        self._last_event = self._snapshot_received = None
        self._reported_age = self._age_anchor = self._age_received = None
        self._status, self._reason = 'WAITING', None
        self._new_request = False
        self._stopped = False
        self._stopping = False
        self._started = self._now()

    def _now(self):
        now = self._clock()
        if type(now) is not int or now < 0 or self._last_clock is not None and now < self._last_clock:
            self._clear('PROTOCOL_ERROR', 'consumer_clock_not_monotonic')
            raise ValueError('consumer_clock_not_monotonic')
        self._last_clock = now
        return now

    def _clear(self, status, reason):
        self._ref = self._state = None
        self._new_request = False
        self._status, self._reason = status, reason

    def _age(self, now):
        return None if self._age_anchor is None else self._age_anchor + now - self._age_received

    def _tick(self, now):
        if self._status in ('CLOSED', 'PROTOCOL_ERROR', 'STALE'):
            return
        if now - (self._last_event if self._last_event is not None else self._started) > self._silence_limit:
            self._clear('STALE', 'event_silence_expired')
        elif self._ref is not None and self._age(now) > self._age_limit:
            self._clear('STALE', 'observation_age_expired')

    def tick(self):
        self._tick(self._now())
        return self.current_view()

    def accept_event(self, event, *, received_ns=None):
        """Accept one event; optional receipt time must use this local clock.

        The JSONL adapter stamps receipt before queueing, so local queue/decode
        delay counts toward both leases. Direct callers default to now.
        """
        now = self._now()
        self._tick(now)
        if self._status in ('CLOSED', 'PROTOCOL_ERROR', 'STALE'):
            return False
        try:
            received = now if received_ns is None else received_ns
            _integer(received, maximum=2**64 - 1)
            _require(received <= now and (self._last_event is None or received >= self._last_event))
            _validate(event)
            if event['sequence'] != self._sequence + 1 or self._session not in (None, event['session_id']):
                raise ValueError('session_or_sequence_mismatch')
            kind = event['event_type']
            _require(not self._stopping or kind == 'stopped')
            if kind == 'snapshot':
                _require(self._ref is None)
                self._ref = copy.deepcopy(event['snapshot_ref'])
                self._state = copy.deepcopy(event['decision_state'])
                self._new_request = event['new_request_observed']
                self._snapshot_received = received
                self._reported_age = self._age_anchor = event['timing']['observation_age_ns']
                self._age_received = received
                self._status, self._reason = 'OBSERVING', None
            elif kind == 'invalidate':
                _require(self._ref is not None and event['revoked'] == self._ref)
                self._clear('INVALIDATED', event['reason'])
                self._stopping = event['reason'] == 'session_stopped'
            elif kind == 'liveness':
                _require(event['current_snapshot_ref'] == self._ref)
                if self._ref is not None:
                    _require(event['binding'] == self._ref['binding'])
                    age = event['timing']['observation_age_ns']
                    _require(age is not None and age >= self._reported_age)
                    # Never move the original observation forward on heartbeat.
                    self._age_anchor = max(self._age(now), age + now - received)
                    self._age_received, self._reported_age = now, age
            else:
                self._stopped = True
                self._clear('CLOSED', event['reason'])
            self._session, self._sequence, self._last_event = event['session_id'], event['sequence'], received
            self._tick(now)
            return True
        except (ValueError, TypeError, KeyError, RecursionError, UnicodeError):
            self._clear('PROTOCOL_ERROR', 'invalid_event_or_stream_order')
            return False

    def close(self, reason='cancelled'):
        """EOF without stopped, input errors, disconnect and cancellation revoke.

        A normal stopped/EOF pair preserves the producer's stop reason. Prior
        quarantine diagnoses are never overwritten by a later stream close.
        """
        if self._status not in ('CLOSED', 'PROTOCOL_ERROR', 'STALE'):
            self._clear('CLOSED', 'unexpected_eof' if reason == 'eof' else reason)
        return self.current_view()

    def current_view(self):
        now = self._now()
        self._tick(now)
        return {'consumer_status': self._status, 'session_id': self._session,
            'last_sequence': self._sequence, 'current_snapshot_ref': copy.deepcopy(self._ref),
            'decision_state': copy.deepcopy(self._state), 'new_request_observed': self._new_request,
            'observation_age_ns': self._age(now),
            'last_event_received_ns': self._last_event,
            'last_snapshot_received_ns': self._snapshot_received,
            'producer_reported_observation_age_ns': self._reported_age,
            'transport_alive': self._status not in ('CLOSED', 'PROTOCOL_ERROR', 'STALE') and self._last_event is not None,
            'unresolved': [self._reason] if self._reason else [],
            'read_only': True, **EXECUTION}


def _json_line(line):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate_json_key')
            result[key] = value
        return result

    if isinstance(line, bytes):
        line = line.decode('utf-8')
    _require(type(line) is str and line.endswith('\n') and len(line.encode('utf-8')) <= MAX_LINE_BYTES)
    return json.loads(line, object_pairs_hook=unique,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError('nonfinite_json')))


class _DiagnosticOutput:
    """One bounded, consumer-independent writer. Never emit under its lock.

    Capacity bounds pending ordinary diagnostics, plus one in-flight call and
    one terminal slot. An arbitrary blocking callback cannot be cancelled;
    close abandons at most that daemon call after the bounded grace period.
    """
    def __init__(self, emit, capacity):
        self._emit, self._capacity = emit, capacity
        self._condition = threading.Condition()
        self._pending = deque()
        self._terminal = None
        self._closed = False
        self.failure = None
        self._peak = self._overflows = self._dropped = 0
        self._inflight = False
        self.thread = threading.Thread(target=self._run, name='decision-diagnostic-writer', daemon=True)
        self.thread.start()

    def metrics(self):
        with self._condition:
            return {'capacity': self._capacity, 'pending': len(self._pending), 'peak': self._peak,
                    'overflows': self._overflows, 'dropped': self._dropped,
                    'inflight': self._inflight, 'terminal_pending': self._terminal is not None,
                    'writer_alive': self.thread.is_alive()}

    def offer(self, diagnostic):
        with self._condition:
            if len(self._pending) >= self._capacity:
                self._overflows += 1
                self._dropped += 1
                return False
            self._pending.append(diagnostic)
            self._peak = max(self._peak, len(self._pending))
            self._condition.notify()
            return True

    def finish(self, diagnostic, priority=False):
        with self._condition:
            if priority:
                self._dropped += len(self._pending)
                self._pending.clear()
            self._terminal = dict(diagnostic)
            if self._dropped:
                self._terminal.update(diagnostics_complete=False, diagnostics_dropped=self._dropped)
            self._closed = True
            self._condition.notify()

    def close(self, grace):
        with self._condition:
            self._closed = True
            self._condition.notify()
        self.thread.join(grace)
        # A later callback exit cannot turn abandoned output into success.
        drained = not self.thread.is_alive()
        with self._condition:
            # Never begin another emit after abandoning a blocked callback.
            self._dropped += len(self._pending) + int(self._terminal is not None)
            self._pending.clear()
            self._terminal = None
        return drained

    def _run(self):
        try:
            while True:
                with self._condition:
                    self._condition.wait_for(lambda: self._pending or self._terminal is not None or self._closed)
                    if self._pending:
                        value = self._pending.popleft()
                    elif self._terminal is not None:
                        value, self._terminal = self._terminal, None
                    else:
                        return
                    self._inflight = True
                try:
                    self._emit(value)
                finally:
                    with self._condition:
                        self._inflight = False
        except BaseException as exc:
            with self._condition:
                self.failure = exc
                self._closed = True
                self._dropped += len(self._pending) + int(self._terminal is not None)
                self._pending.clear()
                self._terminal = None


def consume_events(stream, emit, consumer=None, tick_seconds=.05, queue_capacity=64,
                   output_queue_capacity=64, output_grace_seconds=.75):
    """One-shot JSONL adapter with bounded independent input/output workers.

    Input ordering is strict; overflow quarantines rather than skipping events.
    Output backpressure cannot stop core lease checks. Pending diagnostics may
    be discarded on quarantine, explicitly marked incomplete in the terminal
    diagnostic. A blocked output cannot guarantee terminal delivery. Workers
    own no consumer state; process exit closes the CLI-owned OS pipes.
    """
    if (not 0 < tick_seconds <= 1 or type(queue_capacity) is not int or not 1 <= queue_capacity <= 1024
            or type(output_queue_capacity) is not int or not 1 <= output_queue_capacity <= 1024
            or not 0 < output_grace_seconds <= 1):
        raise ValueError('invalid_consumer_stream_bounds')
    consumer = consumer if consumer is not None else DecisionConsumer()
    inbox, overflow, done = queue.Queue(queue_capacity), threading.Event(), threading.Event()

    def lines():
        try:
            descriptor = stream.fileno()
        except (AttributeError, OSError, ValueError):
            while not done.is_set():
                line = stream.readline(MAX_LINE_BYTES + 1)
                yield line
                if line in ('', b''):
                    return
        else:
            # Do not hold a BufferedReader lock in an abandoned daemon during
            # interpreter shutdown (notably on Windows with an open stdin).
            pending = b''
            while not done.is_set():
                chunk = os.read(descriptor, 65536)
                if not chunk:
                    if pending:
                        yield pending  # A tail without newline is rejected.
                    yield b''
                    return
                pending += chunk
                while b'\n' in pending:
                    line, pending = pending.split(b'\n', 1)
                    yield line + b'\n'
                if len(pending) > MAX_LINE_BYTES:
                    yield pending
                    return

    def reader():
        try:
            for line in lines():
                if done.is_set():
                    return
                item = ('eof', None, None) if line in ('', b'') else ('line', line, consumer._clock())
                try:
                    inbox.put_nowait(item)
                except queue.Full:
                    overflow.set()
                    return
                if item[0] == 'eof':
                    return
        except Exception:
            try:
                inbox.put_nowait(('error', None, None))
            except queue.Full:
                overflow.set()

    threading.Thread(target=reader, name='decision-jsonl-reader', daemon=True).start()
    output = _DiagnosticOutput(emit, output_queue_capacity)
    last_diagnostic = None
    result = 1

    def diagnostic():
        view = consumer.current_view()
        # Deliberately omit binding, private state and candidate content.
        return {k: view[k] for k in ('consumer_status', 'last_sequence',
            'new_request_observed', 'transport_alive', 'unresolved', 'read_only', *EXECUTION)}

    try:
        while True:
            if output.failure is not None:
                raise output.failure
            if overflow.is_set():
                consumer._clear('PROTOCOL_ERROR', 'input_queue_overflow')
            else:
                try:
                    kind, line, received = inbox.get(timeout=tick_seconds)
                except queue.Empty:
                    consumer.tick()
                else:
                    if kind == 'eof':
                        consumer.close('eof')
                    elif kind == 'error':
                        consumer.close('input_stream_error')
                    else:
                        try:
                            event = _json_line(line)
                        except (ValueError, UnicodeError, RecursionError):
                            consumer._clear('PROTOCOL_ERROR', 'invalid_json_line')
                        else:
                            consumer.accept_event(event, received_ns=received)
            value = diagnostic()
            if value['consumer_status'] in ('CLOSED', 'PROTOCOL_ERROR', 'STALE'):
                result = 0 if consumer._stopped and value['unresolved'] != ['source_error'] else 1
                output.finish(value, priority=result != 0)
                break
            if value != last_diagnostic:
                if not output.offer(value):
                    consumer._clear('PROTOCOL_ERROR', 'diagnostic_output_queue_overflow')
                    output.finish(diagnostic(), priority=True)
                    break
                last_diagnostic = value
    except KeyboardInterrupt:
        consumer.close('cancelled')
        output.finish(diagnostic(), priority=True)
    except OSError:
        consumer.close('output_stream_error')
    finally:
        done.set()
        if consumer._status not in ('CLOSED', 'PROTOCOL_ERROR', 'STALE'):
            consumer._clear('CLOSED', 'subscription_ended')
        drained = output.close(output_grace_seconds)
    # A failure during normal terminal drain must never report success.
    if output.failure is not None:
        if isinstance(output.failure, OSError):
            return 1
        raise output.failure
    return result if drained else 1
