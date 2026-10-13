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


def replay(path, dry=False):
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
                    'format': 'normalized-ndjson-v1 only; raw Player.log unsupported'},
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
    if args.command == 'doctor':
        result = doctor(args.config, args.log)
        code = 0 if result['interpreter_supported'] and result['config']['valid'] else 1
    elif args.command in {'replay', 'dry-run'}:
        try:
            result = replay(args.input, args.command == 'dry-run')
            code = 0 if result['current']['valid'] else 1
        except OSError as exc:
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
