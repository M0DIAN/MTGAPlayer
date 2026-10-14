import argparse
import json
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


def replay(path, dry=False, format='normalized', card_db_path=None,
           decision_input=False, action_gaps=False, action_frontier=False):
    if action_gaps and not decision_input:
        raise ValueError('action_gaps_requires_decision_input')
    if action_frontier and not decision_input:
        raise ValueError('action_frontier_requires_decision_input')
    if card_db_path is not None and format != 'player-log':
        raise ValueError('card_db_requires_player_log_format')
    if decision_input and format != 'player-log':
        raise ValueError('decision_input_requires_player_log_format')
    if format == 'player-log':
        follower, reducer = RawFollower(path), RawReducer()
        reset, records = follower.poll()
        if reset:
            reducer.reset(follower.generation)
        for record in records:
            reducer.apply(record)
        document = reducer.document(include_frontier_rows=action_frontier)
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
        if decision_input:
            from .decision_input import build_decision_input
            document['decision_input'] = build_decision_input(document)
            if action_gaps:
                from .action_gaps import assess_action_gaps
                document['action_gap_report'] = assess_action_gaps(
                    document['decision_input'])
            if action_frontier:
                _project_action_frontier(document)
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
          decision_input=False, action_gaps=False, action_frontier=False):
    """Finite read-only observations. Each yielded sample is a standalone document."""
    if action_gaps and not decision_input:
        raise ValueError('action_gaps_requires_decision_input')
    if action_frontier and not decision_input:
        raise ValueError('action_frontier_requires_decision_input')
    follower, reducer = RawFollower(path, max_history_bytes), RawReducer()
    # History is a baseline, never a new opportunity. A request can be emitted
    # only on its first complete, supported append observation.
    seen_requests = set()
    for index in range(samples):
        reset, records = follower.poll()
        if reset:
            reducer.reset(follower.generation)
        phase = 'history' if index == 0 or reset else 'append'
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
        document = reducer.document(include_frontier_rows=action_frontier)
        reduced_current = document['current']
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
        if decision_input:
            from .decision_input import build_decision_input
            document['decision_input'] = build_decision_input(document)
            if action_gaps:
                from .action_gaps import assess_action_gaps
                document['action_gap_report'] = assess_action_gaps(
                    document['decision_input'])
            if action_frontier:
                _project_action_frontier(document)
        yield document
        if index + 1 < samples:
            time.sleep(interval)


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
    parser = argparse.ArgumentParser(prog='mtgaplayer')
    sub = parser.add_subparsers(dest='command', required=True)
    doc = sub.add_parser('doctor', help='read-only environment/config/window probe')
    doc.add_argument('--config')
    doc.add_argument('--log')
    for name in ('replay', 'dry-run'):
        replay_parser = sub.add_parser(name, help='consume explicit normalized JSONL; never sends input')
        replay_parser.add_argument('input', type=Path)
        replay_parser.add_argument('--format', choices=['normalized', 'player-log'], default='normalized')
        replay_parser.add_argument('--card-db', type=Path,
                                   help='opt-in local read-only MTGA card SQLite (raw replay only)')
        replay_parser.add_argument('--decision-input', action='store_true',
                                   help='MP13 read-only, own-request-bound observation (player-log only)')
        replay_parser.add_argument('--action-gaps', action='store_true',
                                   help='MP14 unverified rule/response evidence gaps; needs --decision-input')
        replay_parser.add_argument('--action-frontier', action='store_true',
                                   help='read-only MP15 active action templates; needs --decision-input')
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
    if hasattr(args, 'count') and args.count < 1:
        parser.error('--count must be positive')
    if hasattr(args, 'duration') and args.duration <= 0:
        parser.error('--duration must be positive')
    if args.command == 'watch' and (not 0 < args.interval <= 60 or
                                    not 1 <= args.samples <= 1000 or
                                    not 1 <= args.max_history_bytes <= 1024 * 1024 * 1024):
        parser.error('watch bounds must be positive (interval <=60, samples <=1000, history <=1GiB)')
    if args.command == 'doctor':
        result = doctor(args.config, args.log)
        code = 0 if result['interpreter_supported'] and result['config']['valid'] else 1
    elif args.command in {'replay', 'dry-run'}:
        try:
            result = replay(args.input, args.command == 'dry-run', args.format,
                            args.card_db, decision_input=args.decision_input,
                            action_gaps=args.action_gaps,
                            action_frontier=args.action_frontier)
            code = 0 if result['current']['valid'] else 1
        except (OSError, ValueError) as exc:
            result, code = {'error': str(exc), 'input_sent': False}, 1
    elif args.command == 'watch':
        try:
            for result in watch(args.input, args.interval, args.samples,
                                args.max_history_bytes, decision_input=args.decision_input,
                                action_gaps=args.action_gaps,
                                action_frontier=args.action_frontier):
                print(json.dumps(result, ensure_ascii=False), flush=True)
            return 0
        except KeyboardInterrupt:
            print(json.dumps({'source': {'mode': 'watch', 'stopped': True,
                                         'stop_reason': 'keyboard_interrupt',
                                         'input_sent': False, 'executor_connected': False}}), flush=True)
            return 0
        except (OSError, ValueError) as exc:
            result, code = {'error': str(exc), 'input_sent': False}, 1
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
