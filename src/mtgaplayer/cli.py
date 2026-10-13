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


def replay(path, dry=False, format='normalized'):
    if format == 'player-log':
        follower, reducer = RawFollower(path), RawReducer()
        reset, records = follower.poll()
        if reset:
            reducer.reset(follower.generation)
        for record in records:
            reducer.apply(record)
        document = reducer.document()
        if follower.framer.partial:
            document['current'] = {k: document['current'].get(k) for k in
                                   ('match', 'game', 'self_seat', 'game_state_id')}
            document['current']['valid'] = False
            document['error'] = 'partial_raw_record_waiting'
        document['source'] = {'format': 'player-log-gre-v1', 'generation': follower.generation,
                              'byte_offset': follower.offset, 'partial_record': follower.framer.partial,
                              'mode': 'offline', 'input_sent': False, 'executor_connected': False}
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


def watch(path, interval=0.25, samples=5, max_history_bytes=64 * 1024 * 1024):
    """Finite read-only observations. Each yielded sample is a standalone document."""
    follower, reducer = RawFollower(path, max_history_bytes), RawReducer()
    for index in range(samples):
        reset, records = follower.poll()
        if reset:
            reducer.reset(follower.generation)
        for record in records:
            reducer.apply(record)
        document = reducer.document()
        if follower.framer.partial:
            document['current'] = {k: document['current'].get(k) for k in
                                   ('match', 'game', 'self_seat', 'game_state_id')}
            document['current']['valid'] = False
            document['error'] = 'partial_raw_record_waiting'
        document['source'] = {'format': 'player-log-gre-v1', 'generation': follower.generation,
                              'byte_offset': follower.offset, 'partial_record': follower.framer.partial,
                              'mode': 'watch', 'phase': 'history' if index == 0 or reset else 'append',
                              'new_records': len(records), 'input_sent': False,
                              'executor_connected': False, 'stopped': index + 1 == samples,
                              'stop_reason': 'sample_limit' if index + 1 == samples else None}
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
    watch_parser = sub.add_parser('watch', help='bounded read-only Player.log observations')
    watch_parser.add_argument('input', type=Path)
    watch_parser.add_argument('--interval', type=float, default=0.25)
    watch_parser.add_argument('--samples', type=int, default=5)
    watch_parser.add_argument('--max-history-bytes', type=int, default=64 * 1024 * 1024)
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
            result = replay(args.input, args.command == 'dry-run', args.format)
            code = 0 if result['current']['valid'] else 1
        except (OSError, ValueError) as exc:
            result, code = {'error': str(exc), 'input_sent': False}, 1
    elif args.command == 'watch':
        try:
            for result in watch(args.input, args.interval, args.samples, args.max_history_bytes):
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
