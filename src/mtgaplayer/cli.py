import argparse
import copy
import json
import math
import os
from pathlib import Path
import platform
import sys
import time
from .native import probe
from .policy import decide
from .state import Reducer
from .stream import Follower
from .raw_log import RawFollower, RawReducer


def _emit_consumer_diagnostic(value):
    """Raw stdout writes avoid an abandoned daemon holding BufferedWriter.

    Only consume-events uses this path. In-memory redirected stdout remains
    supported for callers that do not expose an OS descriptor.
    """
    line = json.dumps(value, ensure_ascii=False) + '\n'
    try:
        descriptor = sys.stdout.fileno()
    except (AttributeError, OSError, ValueError):
        sys.stdout.write(line)
        sys.stdout.flush()
        return
    pending = line.encode('utf-8')
    while pending:
        written = os.write(descriptor, pending)
        if written <= 0:
            raise OSError('consumer_diagnostic_short_write')
        pending = pending[written:]


def _project_action_frontier(document):
    """Consume private row evidence, then remove it from the public snapshot."""
    from .action_frontier import build_action_frontier
    request = document['current'].get('request')
    inventory = request.get('action_inventory') if isinstance(request, dict) else None
    evidence = None
    if isinstance(inventory, dict):
        evidence = {
            'request_identity': inventory.pop('_frontier_request_identity', None),
            'rows': inventory.pop('_frontier_rows', None),
        }
    document['action_frontier'] = build_action_frontier(
        document['decision_input'], evidence)


def _project_choice_graph(document):
    from .choice_graph import build_choice_graph
    request = document['current'].get('request')
    document['choice_graph'] = build_choice_graph(
        document.get('decision_input'), document.get('action_frontier'), request)


def _observe_combat(reducer):
    from .combat_frontier import CombatFrontierObserver
    observer = CombatFrontierObserver()
    reducer.observer = lambda event, details: observer.observe(reducer, event, details)
    return observer


def _project_decision_state(reducer, document, combat, retain_rows, version=1):
    """Stage children from this document only; never poll or advance the reducer."""
    from .decision_input import build_decision_input
    from .decision_state import build_decision_state
    staged = {'current': copy.deepcopy(document['current']),
              'source': copy.deepcopy(document['source']), 'error': document.get('error')}
    request = staged['current'].get('request')
    interrupted = isinstance(request, dict) and request.get('_continuity_verified') is False
    if interrupted:
        staged['current']['request'] = None
    staged['decision_input'] = build_decision_input(staged)
    request = staged['current'].get('request')
    typ = request.get('type') if isinstance(request, dict) else None
    if typ == 'GREMessageType_ActionsAvailableReq':
        _project_action_frontier(staged)
        _project_choice_graph(staged)
    elif typ in ('GREMessageType_DeclareAttackersReq', 'GREMessageType_DeclareBlockersReq'):
        staged['combat_frontier'] = combat.project(reducer, staged)
    document['decision_state'] = build_decision_state(staged, version=version)
    document['current'].pop('_turn_context', None)
    document['current'].pop('_public_stack', None)
    document['current'].pop('_observed_combat_stats', None)
    if isinstance(document['current'].get('request'), dict):
        document['current']['request'].pop('_request_parameters', None)
    if interrupted and document['decision_state'] is not None:
        document['decision_state']['unresolved'].append('current_request_continuity_unverified')
        document['decision_state']['unresolved'].sort()
    request = document['current'].get('request')
    if isinstance(request, dict):
        request.pop('_continuity_verified', None)
    if not retain_rows:
        request = document['current'].get('request')
        inventory = request.get('action_inventory') if isinstance(request, dict) else None
        if isinstance(inventory, dict):
            inventory.pop('_frontier_rows', None)
            inventory.pop('_frontier_request_identity', None)


def replay(path, dry=False, format='normalized', card_db_path=None,
           decision_input=False, action_gaps=False, action_frontier=False,
           choice_graph=False, combat_frontier=False, decision_state=False,
           rules_index_path=None, advice_policy=None, decision_state_version=1,
           known_choice_candidates=False):
    from .decision_state import state_schema_version
    state_schema_version(decision_state_version)
    if known_choice_candidates and (format != 'player-log' or decision_state_version < 5):
        raise ValueError('known_choice_candidates_require_player_log_state_v5_or_v6')
    decision_state = decision_state or decision_state_version != 1
    if advice_policy is not None:
        if format != 'player-log':
            raise ValueError('advice_requires_player_log_format')
        decision_state = True
    if rules_index_path is not None:
        if format != 'player-log':
            raise ValueError('rules_index_requires_player_log_format')
        decision_state = True
    if decision_state and format != 'player-log':
        raise ValueError('decision_state_requires_player_log_format')
    if combat_frontier and not decision_input:
        raise ValueError('combat_frontier_requires_decision_input')
    if action_gaps and not decision_input:
        raise ValueError('action_gaps_requires_decision_input')
    if action_frontier and not decision_input:
        raise ValueError('action_frontier_requires_decision_input')
    if choice_graph and not action_frontier:
        raise ValueError('choice_graph_requires_action_frontier')
    if card_db_path is not None and format != 'player-log':
        raise ValueError('card_db_requires_player_log_format')
    if decision_input and format != 'player-log':
        raise ValueError('decision_input_requires_player_log_format')
    if format == 'player-log':
        follower, reducer = RawFollower(path), RawReducer(include_request_parameters=decision_state_version >= 5)
        combat = _observe_combat(reducer) if combat_frontier or decision_state else None
        reset, records = follower.poll()
        if reset:
            reducer.reset(follower.generation)
        for record in records:
            reducer.apply(record)
        document = reducer.document(include_frontier_rows=action_frontier or decision_state,
                                    include_decision_state=decision_state)
        if follower.framer.partial:
            document['current'] = {k: document['current'].get(k) for k in
                                   ('match', 'game', 'self_seat', 'game_state_id')}
            document['current']['valid'] = False
            document['current']['actionable'] = False
            document['error'] = 'partial_raw_record_waiting'
        if card_db_path is not None and document['current'].get('valid') is True:
            from .card_catalog import enrich_visible_document
            enrich_visible_document(document, card_db_path)
        document['source'] = {'format': 'player-log-gre-v1', 'generation': follower.generation,
                              'byte_offset': follower.offset, 'partial_record': follower.framer.partial,
                              'mode': 'offline', 'input_sent': False, 'executor_connected': False}
        if decision_state:
            _project_decision_state(reducer, document, combat, action_frontier, decision_state_version)
        if known_choice_candidates:
            from .choice_candidates import enumerate_known_candidates
            document['known_choice_candidates'] = enumerate_known_candidates(document['decision_state'])
        if rules_index_path is not None:
            from .rule_context import build_static_rule_context
            document['static_rule_context'] = build_static_rule_context(
                document['decision_state'], rules_index_path)
        if advice_policy is not None:
            from .decision_advisor import assess_decision_state
            document['decision_advice'] = assess_decision_state(
                document['decision_state'], policy_version=advice_policy)
        if decision_input:
            from .decision_input import build_decision_input
            document['decision_input'] = build_decision_input(document)
            if action_gaps:
                from .action_gaps import assess_action_gaps
                document['action_gap_report'] = assess_action_gaps(
                    document['decision_input'])
            if action_frontier:
                _project_action_frontier(document)
            if choice_graph:
                _project_choice_graph(document)
            if combat_frontier:
                document['combat_frontier'] = combat.project(reducer, document)
        return document
    follower, reducer = Follower(path), Reducer()
    reset, records = follower.poll()
    if reset:
        reducer.reset(follower.generation)
    for record in records:
        reducer.apply(record)
    document = reducer.document()
    document['source'] = {'format': 'normalized-ndjson-v1', 'generation': follower.generation,
                          'byte_offset': follower.offset, 'partial_record': follower.framer.partial,
                          'mode': 'offline', 'input_sent': False}
    # Replay timestamps are not live freshness evidence. Decisions here are
    # recommendations only, never plans accepted by the native executor.
    if dry:
        try:
            document['recommendation'] = decide(document['current'], time.monotonic() + 1).to_dict()
        except (ValueError, TimeoutError, InterruptedError) as exc:
            document['recommendation'] = {'status': 'unsupported', 'reason': str(exc)}
    if follower.framer.partial:
        document['current'] = {**document['current'], 'valid': False}
        document['error'] = 'partial_record_waiting'
        document.pop('recommendation', None)
    return document


def watch(path, interval=0.25, samples=5, max_history_bytes=64 * 1024 * 1024,
          decision_input=False, action_gaps=False, action_frontier=False,
          choice_graph=False, combat_frontier=False, decision_state=False,
          _poll_observer=None, _clock_ns=None, decision_state_version=1):
    """Finite read-only observations. Each yielded sample is a standalone document."""
    from .decision_state import state_schema_version
    state_schema_version(decision_state_version)
    decision_state = decision_state or decision_state_version != 1
    if combat_frontier and not decision_input:
        raise ValueError('combat_frontier_requires_decision_input')
    if action_gaps and not decision_input:
        raise ValueError('action_gaps_requires_decision_input')
    if action_frontier and not decision_input:
        raise ValueError('action_frontier_requires_decision_input')
    if choice_graph and not action_frontier:
        raise ValueError('choice_graph_requires_action_frontier')
    follower, reducer = RawFollower(path, max_history_bytes), RawReducer(include_request_parameters=decision_state_version >= 5)
    combat = _observe_combat(reducer) if combat_frontier or decision_state else None
    clock = _clock_ns or time.perf_counter_ns
    facts = {}
    previous_request = None
    history_pending = _poll_observer is not None
    def request_identity(request):
        binding = request.get('binding') if isinstance(request, dict) else None
        return tuple(binding.get(k) for k in ('generation', 'match', 'game', 'self_seat',
                                              'game_state_id')) + (request['id'], request['type']) if binding else None
    if _poll_observer is not None:
        def observe(event, details):
            # Copy scalar facts immediately; never retain raw messages or the
            # mutable reducer request. This is a per-poll summary, not a ledger.
            if combat is not None:
                combat.observe(reducer, event, details)
            if event == 'state_accepted' and details['kind'] != 'full_retransmit':
                facts['state_changed'] = True
            elif event == 'request_accepted' and not details['is_retransmission']:
                facts['request_changed'] = True
                facts['last_new_request'] = request_identity(details['request'])
            elif event == 'request_ended':
                facts['request_changed'] = True
                if request_identity(details['request']) == previous_request:
                    facts['request_consumed'] = details['disposition'] == 'consumed'
            elif event == 'continuity_error':
                facts['continuity_error'] = True
                facts['request_conflict'] = facts.get('request_conflict', False) or details['reason'] == 'conflicting_request_identity'
        reducer.observer = observe
    # History is a baseline, never a new opportunity. A request can be emitted
    # only on its first complete, supported append observation.
    seen_requests = set()
    for index in range(samples):
        if _poll_observer is not None:
            started = clock()
            facts = {}
            previous_request = request_identity(reducer.request)
        reset, records = follower.poll()
        if _poll_observer is not None:
            after_read = clock()
        if reset:
            reducer.reset(follower.generation)
            if _poll_observer is not None:
                history_pending = True
        phase = 'history' if index == 0 or reset or history_pending else 'append'
        newly_accepted = set()
        for record in records:
            reducer.apply(record)
            # Record *every* accepted supported request before a later record
            # can invalidate the outward snapshot. A subsequent identical Full
            # recovery must not turn its retransmission into a new opportunity.
            # A later failure (even in this same GRE record) does not erase
            # a previously accepted request. Its identity still belongs in
            # the deduplication ledger, but can never make an invalid current
            # snapshot actionable.
            accepted = reducer.request
            binding = accepted.get('binding') if accepted and accepted.get('supported') else None
            if binding and binding.get('ownership_verified') is True:
                identity = (binding.get('generation'), binding.get('match'), binding.get('game'),
                            binding.get('game_state_id'), binding.get('self_seat'), accepted['id'])
                if identity not in seen_requests:
                    gre = record.get('greToClientEvent') if isinstance(record, dict) else None
                    messages = gre.get('greToClientMessages') if isinstance(gre, dict) else None
                    if phase == 'append' and isinstance(messages, list) and any(
                            isinstance(message, dict) and
                            message.get('type') == accepted['type'] and
                            message.get('msgId') == accepted['id'] and
                            message.get('gameStateId') == accepted['game_state_id'] and
                            message.get('systemSeatIds') == [binding['self_seat']]
                            for message in messages):
                        newly_accepted.add(identity)
                    seen_requests.add(identity)
        if _poll_observer is not None:
            after_apply = clock()
            facts['new_final_request'] = (facts.get('last_new_request') is not None and
                                           facts['last_new_request'] == request_identity(reducer.request))
            facts.pop('last_new_request', None)
            # Incomplete source observation must not restore a pre-tail request
            # when an unrelated record later completes. Reuse its existing bit;
            # do not alter Full/Diff continuity or create another request ledger.
            if follower.framer.partial and reducer.request is not None:
                reducer.request['_continuity_verified'] = False
        document = reducer.document(include_frontier_rows=action_frontier or decision_state,
                                    include_decision_state=decision_state)
        reduced_current = document['current']
        if _poll_observer is not None and reduced_current.get('valid') and not follower.framer.partial:
            history_pending = False
        if follower.framer.partial:
            document['current'] = {k: reduced_current.get(k) for k in
                                   ('match', 'game', 'self_seat', 'game_state_id')}
            document['current']['valid'] = False
            document['current']['actionable'] = False
            document['error'] = 'partial_raw_record_waiting'
        request = reduced_current.get('request') if reduced_current.get('valid') else None
        binding = request.get('binding') if request and request.get('supported') else None
        candidate_event = None
        if binding and binding.get('ownership_verified') is True:
            identity = (binding.get('generation'), binding.get('match'), binding.get('game'),
                        binding.get('game_state_id'), binding.get('self_seat'), request['id'])
            if phase == 'append' and not follower.framer.partial and identity in newly_accepted:
                candidate_event = {'kind': 'supported_request_observed',
                                   'binding': binding, 'request_id': request['id'],
                                   'candidate_count': len(request['candidates']),
                                   'read_only': True}
        document['source'] = {'format': 'player-log-gre-v1', 'generation': follower.generation,
                              'byte_offset': follower.offset, 'partial_record': follower.framer.partial,
                              'mode': 'watch', 'phase': phase, 'new_records': len(records),
                              'candidate_event': candidate_event, 'input_sent': False,
                              'executor_connected': False, 'stopped': index + 1 == samples,
                              'stop_reason': 'sample_limit' if index + 1 == samples else None}
        if decision_state:
            if _poll_observer is not None:
                assembly_start = clock()
            _project_decision_state(reducer, document, combat, action_frontier, decision_state_version)
            if _poll_observer is not None:
                assembly_ns = clock() - assembly_start
        if decision_input:
            from .decision_input import build_decision_input
            document['decision_input'] = build_decision_input(document)
            if action_gaps:
                from .action_gaps import assess_action_gaps
                document['action_gap_report'] = assess_action_gaps(
                    document['decision_input'])
            if action_frontier:
                _project_action_frontier(document)
            if choice_graph:
                _project_choice_graph(document)
            if combat_frontier:
                document['combat_frontier'] = combat.project(reducer, document)
        if _poll_observer is not None:
            _poll_observer({**facts, 'reset': reset,
                'poll_started_ns': started, 'poll_completed_ns': clock(),
                'poll_read_ns': after_read - started,
                'reducer_apply_ns': after_apply - after_read,
                'decision_state_assembly_ns': assembly_ns if decision_state else 0})
        yield document
        if index + 1 < samples:
            time.sleep(interval)


def watch_decision_events(path, interval=0.25, samples=5, max_history_bytes=64 * 1024 * 1024,
                          max_observation_age_ns=None, clock_ns=None, session_id=None, decision_state_version=1):
    """Iterate poll-level DecisionEvent JSON objects; source is read only once.

    EOF/consumer abandonment also ends the subscription; consumers must discard
    cached references when the stream ends. Transient intra-poll requests are
    intentionally not exported. No server freshness or input permission.
    """
    from .decision_publisher import DecisionPublisher
    if (type(samples) is not int or not 1 <= samples <= 1000 or
            not math.isfinite(interval) or not 0 <= interval <= 60 or
            type(max_history_bytes) is not int or not 1 <= max_history_bytes <= 1024 * 1024 * 1024):
        raise ValueError('invalid_decision_event_watch_bounds')
    publisher = DecisionPublisher(max_observation_age_ns, clock_ns, session_id, state_version=decision_state_version)
    metadata = None
    def observed(facts):
        nonlocal metadata
        metadata = facts
    reason = 'sample_limit'
    try:
        for document in watch(path, interval, samples, max_history_bytes, decision_state=True,
                              _poll_observer=observed, _clock_ns=publisher.clock_ns,
                              decision_state_version=decision_state_version):
            yield from publisher.observe(document, metadata)
    except KeyboardInterrupt:
        reason = 'user_interrupt'
    except (OSError, ValueError):
        reason = 'source_error'
    yield from publisher.stop(reason)


def doctor(config_path=None, log_path=None):
    config, error = {}, None
    if config_path:
        try:
            import tomllib
            config = tomllib.loads(Path(config_path).read_text(encoding='utf-8'))
            if set(config) - {'log_path'} or ('log_path' in config and not isinstance(config['log_path'], str)):
                raise ValueError('only string log_path is accepted')
        except (ValueError, OSError) as exc:
            error = str(exc)
    path = log_path or config.get('log_path')
    return {'python': sys.version, 'executable': sys.executable, 'base_prefix': sys.base_prefix,
            'venv': sys.prefix != sys.base_prefix, 'python_lock': '3.11',
            'interpreter_supported': sys.version_info[:2] == (3, 11),
            'dependencies': 'stdlib only; setuptools used only to install',
            'os': platform.platform(), 'config': {'path': config_path, 'valid': error is None, 'error': error},
            'log': {'path': path, 'exists': Path(path).is_file() if path else None,
                    'format': 'normalized-ndjson-v1 or read-only player-log-gre-v1'},
            'desktop': probe(), 'default_mode': 'replay/dry-run', 'input_sent': False,
            'LIVE_MTGA': 'NOT_RUN'}


def main(argv=None):
    from .decision_advisor import EVIDENCE_POLICY, SIMPLE_TYPE_POLICY
    parser = argparse.ArgumentParser(prog='mtgaplayer')
    sub = parser.add_subparsers(dest='command', required=True)
    doc = sub.add_parser('doctor', help='read-only environment/config/window probe')
    doc.add_argument('--config')
    doc.add_argument('--log')
    export_parser = sub.add_parser('export-semantic-samples', help='export NEW sanitized offline observation episodes')
    export_parser.add_argument('input', type=Path, help='explicit local Player.log; no directory discovery')
    export_parser.add_argument('--output', type=Path, required=True, help='new JSON file, never overwritten')
    export_parser.add_argument('--schema-version', type=int, choices=(1, 2, 3, 4, 5, 6, 7, 8, 9), default=1,
                               help='v2 Cast/mana; v3 combat; v4 targets; v5 partial Activate; v6 hand; v7 cost selection; v8 Search; v9 observed sacrifice result')
    export_parser.add_argument('--max-samples', type=int, default=16)
    export_parser.add_argument('--max-history-bytes', type=int, default=64 * 1024 * 1024)
    export_parser.add_argument('--origin', choices=('unclassified_local', 'retained_scrubbed_real', 'synthetic'),
                               default='unclassified_local', help='operator label, not proof of origin')
    sample_replay = sub.add_parser('replay-semantic-samples', help='validate sanitized choices; not raw GRE authentication or effects')
    sample_replay.add_argument('input', type=Path)
    sample_replay.add_argument('--shared-stack-observation', action='store_true',
                               help='opt-in v9 same-export visible Stack candidate only; never establishes causality')
    for name in ('replay', 'dry-run'):
        replay_parser = sub.add_parser(name, help='consume explicit normalized JSONL; never sends input')
        replay_parser.add_argument('input', type=Path)
        replay_parser.add_argument('--format', choices=['normalized', 'player-log'], default='normalized')
        replay_parser.add_argument('--card-db', type=Path,
                                   help='opt-in local read-only MTGA card SQLite (raw replay only)')
        replay_parser.add_argument('--rules-index', type=Path,
                                   help='opt-in static reference sidecar; implies --decision-state (player-log only)')
        replay_parser.add_argument('--advice', action='store_true',
                                   help='historical read-only Advisor assessment; implies --decision-state')
        replay_parser.add_argument('--advice-policy', choices=[EVIDENCE_POLICY, SIMPLE_TYPE_POLICY],
                                   help='requires --advice; default evidence_only.v1')
        replay_parser.add_argument('--decision-input', action='store_true',
                                   help='MP13 read-only, own-request-bound observation (player-log only)')
        replay_parser.add_argument('--action-gaps', action='store_true',
                                   help='MP14 unverified rule/response evidence gaps; needs --decision-input')
        replay_parser.add_argument('--action-frontier', action='store_true',
                                   help='read-only MP15 active action templates; needs --decision-input')
        replay_parser.add_argument('--choice-graph', action='store_true',
                                   help='read-only MP16 observed complex constraints; needs --action-frontier')
        replay_parser.add_argument('--combat-frontier', action='store_true',
                                   help='read-only strict combat references; needs --decision-input')
        replay_parser.add_argument('--decision-state', action='store_true',
                                   help='unified read-only DecisionState v1 (player-log only)')
        replay_parser.add_argument('--known-choice-candidates', action='store_true',
                                   help='opt-in MP47 current known choices; requires player-log v5/v6')
        replay_parser.add_argument('--decision-state-version', type=int, choices=(1, 2, 3, 4, 5, 6), default=1,
                                   help='explicit v2 adds turn context; v3 adds public Stack order; v4 adds observed current P/T; v5 adds reviewed request literals; v6 adds observed payment selection')
    watch_parser = sub.add_parser('watch', help='bounded read-only Player.log observations')
    watch_parser.add_argument('input', type=Path)
    watch_parser.add_argument('--interval', type=float, default=0.25)
    watch_parser.add_argument('--samples', type=int, default=5)
    watch_parser.add_argument('--max-history-bytes', type=int, default=64 * 1024 * 1024)
    watch_parser.add_argument('--decision-input', action='store_true',
                              help='MP13 read-only own-request observations (no executor)')
    watch_parser.add_argument('--action-gaps', action='store_true',
                              help='MP14 evidence gaps on observation only; needs --decision-input')
    watch_parser.add_argument('--action-frontier', action='store_true',
                              help='read-only MP15 active action templates; needs --decision-input')
    watch_parser.add_argument('--choice-graph', action='store_true',
                              help='read-only MP16 observed complex constraints; needs --action-frontier')
    watch_parser.add_argument('--combat-frontier', action='store_true',
                              help='read-only strict combat references; needs --decision-input')
    watch_parser.add_argument('--decision-state', action='store_true',
                              help='unified read-only DecisionState v1')
    watch_parser.add_argument('--decision-state-version', type=int, choices=(1, 2, 3, 4, 5, 6), default=1,
                              help='State/Event version; default1; explicit2/3/4/5/6 implies DecisionState')
    watch_parser.add_argument('--decision-events', action='store_true',
                              help='separate read-only DecisionEvent JSONL stream (implies DecisionState)')
    watch_parser.add_argument('--max-observation-age-ms', type=float,
                              help='consumer observation age limit >0..86400000ms; needs --decision-events; no protocol TTL')
    rules_parser = sub.add_parser('import-rules', help='build a NEW offline Scryfall static-rule index')
    rules_parser.add_argument('input', type=Path, help='explicit local Scryfall card JSON array')
    rules_parser.add_argument('--output', type=Path, required=True, help='new versioned SQLite path; never overwritten')
    rules_parser.add_argument('--source-version', required=True, help='user-supplied dataset version; not freshness proof')
    consumer_parser = sub.add_parser('consume-events', help='read-only DecisionEvent JSONL from stdin')
    consumer_parser.add_argument('--known-choice-candidates', action='store_true',
                                 help='opt-in current-only bounded choice alternatives sidecar')
    consumer_parser.add_argument('--validate-choice', type=Path,
        help='read one explicit request-bound proposal before consumption; no input or strategy')
    consumer_parser.add_argument('--observed-changes', action='store_true',
        help='snapshot-bound visible endpoint changes; no effects or event-history claims')
    consumer_parser.add_argument('--rules-index', type=Path,
        help='explicit offline rules index prepared once before consumption; static reference only')
    consumer_parser.add_argument('--advice', action='store_true',
                                 help='opt-in snapshot-bound current Advisor output on the same Consumer')
    consumer_parser.add_argument('--advice-policy', choices=[EVIDENCE_POLICY, SIMPLE_TYPE_POLICY],
                                 help='requires --advice; default evidence_only.v1')
    consumer_parser.add_argument('--max-event-silence-ms', type=float, default=5000,
                                 help='local transport silence policy >0..86400000ms (default 5000)')
    consumer_parser.add_argument('--max-observation-age-ms', type=float, default=5000,
                                 help='local observation age policy >0..86400000ms (default 5000); not server TTL')
    performance = sub.add_parser('performance-baseline',
                                 help='opt-in read-only 600..900s pipeline timing; final safe aggregate only')
    performance.add_argument('input', type=Path)
    performance.add_argument('--duration', type=float, default=600)
    performance.add_argument('--interval', type=float, default=.25)
    performance.add_argument('--max-history-bytes', type=int, default=64 * 1024 * 1024)
    harness = sub.add_parser('harness', help='independent synthetic interactive test window')
    harness.add_argument('--directory', type=Path, required=True)
    harness.add_argument('--nonce', required=True)
    harness.add_argument('--count', type=int, default=30)
    harness.add_argument('--scenario', choices=['normal', 'reorder', 'unsupported', 'target-disappear'], default='normal')
    bench = sub.add_parser('benchmark', help='native harness only; actual screenshot/SendInput')
    bench.add_argument('--output', type=Path, required=True)
    bench.add_argument('--count', type=int, default=30)
    bench.add_argument('--duration', type=float, default=90)
    bench.add_argument('--scenario', choices=['normal', 'reorder', 'unsupported', 'target-disappear'], default='normal')
    args = parser.parse_args(argv)
    if args.command in ('export-semantic-samples', 'replay-semantic-samples'):
        from .semantic_samples import export_samples, load_and_replay, SampleError
        try:
            if args.command == 'export-semantic-samples':
                result = export_samples(args.input, args.output, origin=args.origin,
                    max_samples=args.max_samples, max_history_bytes=args.max_history_bytes, schema_version=args.schema_version)
                report = {'schema_version': result['schema_version'], 'counts': result['counts'],
                          'unsupported_reasons': result['unsupported_reasons'], 'read_only': True, 'input_sent': False}
            else:
                report = load_and_replay(args.input,
                                         shared_stack_observation=args.shared_stack_observation)
        except (SampleError, OSError, ValueError, TypeError, RecursionError, UnicodeError) as exc:
            print(json.dumps({'error': str(exc) if isinstance(exc, SampleError) else
                              'semantic_sample_io_or_format_error', 'read_only': True, 'input_sent': False}))
            return 1
        print(json.dumps(report, ensure_ascii=False))
        return 0
    if getattr(args, 'advice_policy', None) is not None and not args.advice:
        parser.error('--advice-policy requires --advice')
    advice_policy = ((args.advice_policy or EVIDENCE_POLICY)
                     if getattr(args, 'advice', False) else None)
    if hasattr(args, 'count') and args.count < 1:
        parser.error('--count must be positive')
    if hasattr(args, 'duration') and args.duration <= 0:
        parser.error('--duration must be positive')
    if args.command == 'watch' and (not 0 < args.interval <= 60 or
                                    not 1 <= args.samples <= 1000 or
                                    not 1 <= args.max_history_bytes <= 1024 * 1024 * 1024):
        parser.error('watch bounds must be positive (interval <=60, samples <=1000, history <=1GiB)')
    if args.command == 'watch':
        if args.max_observation_age_ms is not None and (
                not args.decision_events or not math.isfinite(args.max_observation_age_ms) or
                not 0 < args.max_observation_age_ms <= 86_400_000 or
                round(args.max_observation_age_ms * 1_000_000) < 1):
            parser.error('observation age limit requires --decision-events and >0..86400000ms (at least 1ns)')
        if args.decision_events and any((args.decision_input, args.action_gaps, args.action_frontier,
                                        args.choice_graph, args.combat_frontier, args.decision_state)):
            parser.error('--decision-events is a separate output mode; omit legacy projection flags')
    if args.command == 'performance-baseline' and (
            not math.isfinite(args.duration) or not 600 <= args.duration <= 900 or
            not math.isfinite(args.interval) or not 0 < args.interval <= 60 or
            round(args.interval * 1_000_000_000) < 1 or
            not 1 <= args.max_history_bytes <= 1024 * 1024 * 1024):
        parser.error('performance bounds: duration 600..900s, interval >0..60s, history >0..1GiB')
    if args.command == 'doctor':
        result = doctor(args.config, args.log)
        code = 0 if result['interpreter_supported'] and result['config']['valid'] else 1
    elif args.command == 'import-rules':
        from .rules_index import build_rules_index, RulesIndexError
        try:
            result = build_rules_index(args.input, args.output, source_version=args.source_version)
            code = 0
        except RulesIndexError as exc:
            result, code = {'error': str(exc), 'input_sent': False}, 1
    elif args.command == 'consume-events':
        from .decision_consumer import DecisionConsumer, consume_events
        limits = (args.max_event_silence_ms, args.max_observation_age_ms)
        if any(not math.isfinite(v) or not 0 < v <= 86_400_000 or round(v * 1_000_000) < 1 for v in limits):
            parser.error('consumer leases must be >0..86400000ms (at least 1ns)')
        proposal = None
        if args.validate_choice is not None:
            from .choice_validation import load_proposal
            try:
                proposal = load_proposal(args.validate_choice)
            except ValueError as exc:
                parser.error(str(exc))
        prepared, rules_error = None, None
        if args.rules_index is not None:
            from .rules_index import load_rules_index, RulesIndexError
            try:
                prepared = load_rules_index(args.rules_index)
            except RulesIndexError as exc:
                rules_error = str(exc)
        consumer = DecisionConsumer(*(round(v * 1_000_000) for v in limits))
        return consume_events(getattr(sys.stdin, 'buffer', sys.stdin), _emit_consumer_diagnostic,
                              consumer, advice_policy=advice_policy,
                              prepared_rules=prepared, rules_error=rules_error,
                              observed_changes=args.observed_changes, choice_proposal=proposal,
                              known_choice_candidates=args.known_choice_candidates)
    elif args.command in {'replay', 'dry-run'}:
        try:
            result = replay(args.input, args.command == 'dry-run', args.format,
                            args.card_db, decision_input=args.decision_input,
                            action_gaps=args.action_gaps,
                            action_frontier=args.action_frontier,
                            choice_graph=args.choice_graph, combat_frontier=args.combat_frontier,
                            decision_state=args.decision_state, rules_index_path=args.rules_index,
                            advice_policy=advice_policy, decision_state_version=args.decision_state_version,
                            known_choice_candidates=args.known_choice_candidates)
            code = 0 if result['current']['valid'] and (
                args.decision_state_version != 2 or result.get('decision_state') is not None) else 1
        except (OSError, ValueError) as exc:
            result, code = {'error': str(exc), 'input_sent': False}, 1
    elif args.command == 'watch':
        if args.decision_events:
            limit = (round(args.max_observation_age_ms * 1_000_000)
                     if args.max_observation_age_ms is not None else None)
            events = watch_decision_events(args.input, args.interval, args.samples,
                                           args.max_history_bytes, limit,
                                           decision_state_version=args.decision_state_version)
            reason = None
            try:
                for result in events:
                    print(json.dumps(result, ensure_ascii=False), flush=True)
                    if result['event_type'] == 'stopped':
                        reason = result['reason']
            except KeyboardInterrupt:
                # An interrupt in stdout/consumer code occurs outside the
                # generator. Deliver it back to the same publisher so its exact
                # outstanding reference is revoked; never emit legacy watch JSON.
                try:
                    terminal = events.throw(KeyboardInterrupt)
                except StopIteration:
                    return 0
                print(json.dumps(terminal, ensure_ascii=False), flush=True)
                for terminal in events:
                    print(json.dumps(terminal, ensure_ascii=False), flush=True)
                return 0
            return 1 if reason == 'source_error' else 0
        try:
            for result in watch(args.input, args.interval, args.samples,
                                args.max_history_bytes, decision_input=args.decision_input,
                                action_gaps=args.action_gaps,
                                action_frontier=args.action_frontier,
                                choice_graph=args.choice_graph, combat_frontier=args.combat_frontier,
                                decision_state=args.decision_state, decision_state_version=args.decision_state_version):
                print(json.dumps(result, ensure_ascii=False), flush=True)
            return 0
        except KeyboardInterrupt:
            print(json.dumps({'source': {'mode': 'watch', 'stopped': True,
                                         'stop_reason': 'keyboard_interrupt',
                                         'input_sent': False, 'executor_connected': False}}), flush=True)
            return 0
        except (OSError, ValueError) as exc:
            result, code = {'error': str(exc), 'input_sent': False}, 1
    elif args.command == 'performance-baseline':
        from .live_performance import run, serialize_report
        result = run(args.input, args.duration, args.interval, args.max_history_bytes)
        print(serialize_report(result), flush=True)
        return 1 if result['failure_category'] is not None else 0
    elif args.command == 'harness':
        if os.name != 'nt':
            result, code = {'status': 'BLOCKED_NATIVE', 'reason': 'Windows_required'}, 2
        else:
            from .harness import run
            run(args.directory, args.nonce, args.count, args.scenario)
            return 0
    else:
        from .benchmark import run
        result = run(args.output, args.count, args.scenario, args.duration)
        code = 0 if result['NATIVE_HARNESS'] == 'PASS' else 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return code
