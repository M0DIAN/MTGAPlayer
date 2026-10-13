"""Local candidate verification with raw outputs and a working-tree hash manifest.

Run using the installed project's Python 3.11. This is author validation, not
independent review. Native failure remains a nonzero command in the manifest.
"""
import hashlib
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--suffix', default='')
    suffix = parser.parse_args().suffix
    if suffix and not suffix.replace('-', '').isalnum():
        parser.error('suffix must be alphanumeric or hyphens')
    destination = ROOT / 'artifacts' / ('offline' + suffix)
    destination.mkdir(parents=True, exist_ok=True)
    scratch = ROOT / '.tmp'
    scratch.mkdir(exist_ok=True)
    environment = os.environ.copy()
    environment['TEMP'] = environment['TMP'] = str(scratch)
    commands = [
        ('unittest', ['-m', 'unittest', 'discover', '-s', 'tests', '-v']),
        ('doctor', ['-m', 'mtgaplayer', 'doctor']),
        ('replay', ['-m', 'mtgaplayer', 'replay', 'examples/synthetic.jsonl']),
        ('dry-run', ['-m', 'mtgaplayer', 'dry-run', 'examples/synthetic.jsonl']),
        ('native-final', ['-m', 'mtgaplayer', 'benchmark', '--output', 'artifacts/native-final' + suffix]),
    ]
    entries = []
    for name, args in commands:
        started = time.monotonic()
        with (destination / (name + '.stdout.txt')).open('x', encoding='utf-8') as stdout, \
                (destination / (name + '.stderr.txt')).open('x', encoding='utf-8') as stderr:
            command = [sys.executable, *args]
            run = subprocess.run(command, cwd=ROOT, env=environment, stdout=stdout, stderr=stderr)
        entry = {'name': name, 'argv': command, 'exit_code': run.returncode,
                 'elapsed_ms': (time.monotonic() - started) * 1000}
        entries.append(entry)
        print(json.dumps(entry), flush=True)
    paths = list((ROOT / 'src').rglob('*.py')) + list((ROOT / 'tests').glob('*.py')) + [
        ROOT / x for x in ('README.md', 'AGENTS.md', 'THIRD_PARTY.md', 'docs/progress.md',
        'pyproject.toml', '.python-version', '.gitignore', '.github/workflows/checks.yml',
        'examples/synthetic.jsonl', 'LICENSES/mtga-play-MIT.txt', 'scripts/validate.py')]
    paths += [p for p in (ROOT / 'artifacts').rglob('*') if p.is_file()]
    manifest = {'scope': 'uncommitted_working_tree_author_validation',
                'head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                'branch': subprocess.check_output(['git', 'branch', '--show-current'], cwd=ROOT, text=True).strip(),
                'python': sys.version, 'commands': entries,
                'sha256': {str(p.relative_to(ROOT)).replace('\\', '/'): hashlib.sha256(p.read_bytes()).hexdigest()
                           for p in sorted(paths)}}
    with (destination / 'validation.json').open('x', encoding='utf-8') as stream:
        json.dump(manifest, stream, indent=2)
    return 0 if all(e['exit_code'] == 0 for e in entries) else 2


if __name__ == '__main__':
    raise SystemExit(main())
