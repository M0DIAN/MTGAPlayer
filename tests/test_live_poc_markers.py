"""Marker source boundaries only; these tests launch no GUI or MTGA process."""
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('live_poc_markers', ROOT / 'scripts/live_poc_markers.py')
markers = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(markers)


class MarkerSourceTests(unittest.TestCase):
    def setUp(self):
        (ROOT / '.tmp').mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=ROOT / '.tmp')
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.path = self.directory / 'action_markers.jsonl'

    def read(self):
        return [json.loads(line) for line in self.path.read_text(encoding='utf-8').splitlines()]

    def test_legacy_default_keeps_user_source_fields_and_game_report_scope(self):
        before = markers.append_marker(self.directory, 'play_land', 'before', 'manual note')
        after = markers.append_marker(self.directory, 'play_land', 'after')
        self.assertEqual(self.read(), [before, after])
        self.assertEqual(set(before), {'event_id', 'event_type', 'phase', 'wall_time_utc',
            'monotonic_ns', 'note', 'source', 'game_input_sent', 'action_verification'})
        self.assertEqual(before['source'], 'user_explicit_click')
        self.assertEqual(before['action_verification'], 'user_report_pending_evidence')
        self.assertEqual(before['note'], 'manual note')
        self.assertNotEqual(before['event_id'], after['event_id'])
        self.assertEqual(datetime.fromisoformat(before['wall_time_utc']).tzinfo, timezone.utc)
        self.assertIs(type(before['monotonic_ns']), int)
        self.assertGreaterEqual(after['monotonic_ns'], before['monotonic_ns'])
        self.assertFalse(before['game_input_sent'])

    def test_codex_options_and_window_markers_are_automated_source_with_no_game_claim(self):
        expected = {'window_minimize', 'window_restore', 'window_resize'}
        self.assertEqual(set(markers.marker_options('codex_window_validation').values()), expected)
        for event in sorted(expected):
            for phase in ('before', 'after'):
                markers.append_marker(self.directory, event, phase, None, source='codex_window_validation')
        rows = self.read()
        self.assertEqual(len(rows), 6)
        self.assertTrue(all(row['source'] == 'codex_window_validation' for row in rows))
        self.assertTrue(all(row['action_verification'] == 'window_event_marker_pending_evidence' for row in rows))
        self.assertTrue(all(row['note'] is None and row['game_input_sent'] is False for row in rows))

    def test_codex_source_rejects_every_game_event_without_writing(self):
        markers.append_marker(self.directory, 'play_land', 'before')
        original = self.path.read_bytes()
        for game_event in markers.GAME_ACTION_TYPES.values():
            with self.subTest(event=game_event), self.assertRaisesRegex(ValueError, 'codex_marker_requires_window_event'):
                markers.append_marker(self.directory, game_event, 'after', source='codex_window_validation')
        self.assertEqual(self.path.read_bytes(), original)

    def test_user_window_event_keeps_honest_window_scope_and_old_default_selection(self):
        row = markers.append_marker(self.directory, 'window_resize', 'before')
        self.assertEqual(row['source'], 'user_explicit_click')
        self.assertEqual(row['action_verification'], 'window_event_marker_pending_evidence')
        choices = markers.marker_options()
        self.assertEqual(next(iter(choices.values())), 'play_land')
        self.assertTrue(set(markers.GAME_ACTION_TYPES.values()) <= set(choices.values()))

    def test_unknown_source_or_event_or_phase_does_not_create_evidence(self):
        for event, phase, source in (('window_resize', 'before', 'unknown'),
                                     ('not_an_event', 'before', 'user_explicit_click'),
                                     ('window_resize', 'during', 'codex_window_validation')):
            with self.subTest(event=event, phase=phase, source=source), self.assertRaises(ValueError):
                markers.append_marker(self.directory, event, phase, source=source)
        self.assertFalse(self.path.exists())

    def test_cli_exposes_explicit_source_and_rejects_unknown_before_loading_UI(self):
        output = io.StringIO()
        with redirect_stdout(output), self.assertRaises(SystemExit) as ended:
            markers.main(['--help'])
        self.assertEqual(ended.exception.code, 0)
        self.assertIn('codex_window_validation', output.getvalue())
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as ended:
            markers.main(['--session', str(self.directory), '--source', 'unknown'])
        self.assertEqual(ended.exception.code, 2)
        self.assertFalse(self.path.exists())


if __name__ == '__main__':
    unittest.main()
