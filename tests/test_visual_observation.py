"""Scoped evidence regressions. Counts 5/6 are public categories, not private IDs."""
import copy
import importlib.util
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from mtgaplayer.visual_observation import visual_count, gre_presence_count, compare_counts, capture_diagnostics

SPEC = importlib.util.spec_from_file_location('phase2_capture', ROOT / 'scripts/live_poc_capture.py')
capture = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(capture)


def visual(value=5, **options):
    return visual_count('opponent_battlefield', value,
                        frame_ref='capture-309', frame_sha256='a' * 64, **options)


def gre(value=6):
    return gre_presence_count('opponent_battlefield', value, source_ref='sanitized-record-120/state-97')


class ObservationTests(unittest.TestCase):
    def test_real_frame309_numbers_remain_different_without_parser_error_claim(self):
        observation = visual(5, uncertainty_reasons=['attached_card_visibility_or_animation_unknown'])
        original = copy.deepcopy(observation)
        result = compare_counts(observation, gre(6), gre(6))
        self.assertEqual(result['status'], 'scope_mismatch')
        self.assertEqual((result['visual_value'], result['GRE_before_value'], result['GRE_after_value']), (5, 6, 6))
        self.assertFalse(result['scope_comparable'])
        self.assertFalse(result['parser_error_proven'])
        self.assertEqual(observation, original)

    def test_explicit_complete_coverage_can_report_numeric_agreement_or_difference(self):
        observation = visual(5, coverage='explicit_complete_coverage', coverage_evidence='All relevant card edges inspected')
        agreed = compare_counts(observation, gre(5), gre(5))
        different = compare_counts(observation, gre(6), gre(6))
        self.assertEqual(agreed['status'], 'verified_consistent')
        self.assertEqual(different['status'], 'conflict_in_observed_bracket')
        self.assertFalse(different['parser_error_proven'])
        self.assertFalse(agreed['causal_proof'])
        self.assertEqual(agreed['renderer_synchronization'], 'unknown')

    def test_subset_equality_is_not_complete_state_verification(self):
        self.assertEqual(compare_counts(visual(5), gre(5), gre(5))['status'], 'scope_mismatch')

    def test_partial_unknown_missing_and_changed_brackets_stay_unverified(self):
        self.assertEqual(compare_counts(visual(5, visibility='partial'), gre(), gre())['status'], 'scope_mismatch')
        self.assertEqual(compare_counts(visual(None, visibility='uncertain'), gre(), gre())['status'], 'insufficient_evidence')
        self.assertEqual(compare_counts(visual(), None, gre())['status'], 'insufficient_evidence')
        self.assertEqual(compare_counts(visual(), gre(None), gre())['status'], 'insufficient_evidence')
        self.assertEqual(compare_counts(visual(2), gre(2), gre(3))['status'], 'time_association_uncertain')

    def test_animation_uncertainty_does_not_become_verified_through_numeric_agreement(self):
        observation = visual(6, coverage='explicit_complete_coverage', coverage_evidence='All edges visible',
                             uncertainty_reasons=['animation_in_progress'])
        self.assertEqual(compare_counts(observation, gre(), gre())['status'], 'insufficient_evidence')

    def test_GRE_presence_cannot_fill_a_visual_value(self):
        result = compare_counts(gre(), gre(), gre())
        self.assertEqual(result['status'], 'GRE_presence_only')
        self.assertIsNone(result['visual_value'])
        forged = gre()
        forged['source'] = 'visual'
        with self.assertRaises(ValueError):
            compare_counts(forged, gre(), gre())

    def test_count_and_coverage_contracts_reject_unsupported_claims(self):
        for invalid in (True, -1, 1.5, '5'):
            with self.subTest(value=invalid), self.assertRaises(ValueError):
                visual(invalid)
        with self.assertRaises(ValueError):
            visual(coverage='explicit_complete_coverage')
        with self.assertRaises(ValueError):
            visual(visibility='partial', coverage='explicit_complete_coverage', coverage_evidence='Claim')
        with self.assertRaises(ValueError):
            visual_count('count', 1, frame_ref='frame', frame_sha256='bad')
        wrong = gre()
        wrong['field'] = 'other_field'
        with self.assertRaises(ValueError):
            compare_counts(visual(), wrong, wrong)

    def test_same_content_at_different_capture_times_is_not_deduplicated(self):
        first = visual_count('count', 1, frame_ref='capture-1-at-t1', frame_sha256='a' * 64)
        second = visual_count('count', 1, frame_ref='capture-2-at-t2', frame_sha256='a' * 64)
        source = gre_presence_count('count', 1, source_ref='source')
        results = [compare_counts(row, source, source) for row in (first, second)]
        self.assertEqual(len(results), 2)
        self.assertNotEqual(results[0]['observation']['evidence']['reference'], results[1]['observation']['evidence']['reference'])


class DiagnosticsTests(unittest.TestCase):
    def row(self, identity=2, digest='a' * 64):
        return {'capture_id': identity, 'sha256': digest, 'file_completed': True,
                'capture_started': {'monotonic_ns': 1_000_000_000},
                'capture_completed': {'monotonic_ns': 1_125_000_000},
                'capture_result': {'status': 'failed', 'reason': 'black_frame',
                    'quality': {'failure_reason': 'black_frame', 'heuristic_only': True}}}

    def test_legacy_quality_failure_has_unknown_acquisition_and_no_blankness_proof(self):
        result = capture_diagnostics(self.row())
        self.assertEqual(result['overall_capture_status'], 'failed')
        self.assertEqual(result['pixel_acquisition_status'], 'unknown')
        self.assertEqual(result['quality_status'], 'failed')
        self.assertTrue(result['file_saved'])
        self.assertFalse(result['blank_content_proven'])
        self.assertEqual(result['visual_state_usable'], 'unknown')

    def test_explicit_pixel_success_does_not_upgrade_failed_quality(self):
        row = self.row()
        row['capture_result'].update(pixel_acquisition_status='succeeded', capture_stage='quality_check')
        result = capture_diagnostics(row)
        self.assertEqual(result['pixel_acquisition_status'], 'succeeded')
        self.assertEqual(result['quality_status'], 'failed')
        self.assertEqual(result['overall_capture_status'], 'failed')
        self.assertEqual(result['visual_state_usable'], 'unknown')

    def test_repeated_content_and_GRE_progress_only_report_uncertainty(self):
        previous, current = self.row(1), self.row(2)
        result = capture_diagnostics(current, previous, gre_advanced=True)
        self.assertEqual(result['freshness']['content_relation'], 'unchanged')
        self.assertEqual(result['freshness']['assessment'], 'uncertain')
        self.assertFalse(result['freshness']['stale_capture_proven'])
        self.assertIsNone(result['freshness']['network_delay_seconds'])
        self.assertEqual(result['freshness']['capture_duration_seconds'], .125)
        self.assertEqual(result['capture_id'], 2)

    def test_changed_hash_is_not_renderer_freshness_proof(self):
        result = capture_diagnostics(self.row(2, 'b' * 64), self.row(1))
        self.assertEqual(result['freshness']['content_relation'], 'changed')
        self.assertEqual(result['freshness']['renderer_freshness'], 'unknown')
        self.assertIsNone(result['freshness']['render_timestamp'])


class CaptureStageTests(unittest.TestCase):
    def setUp(self):
        platform = patch.object(capture, 'os', SimpleNamespace(name='nt'))
        platform.start()
        self.addCleanup(platform.stop)
        (ROOT / '.tmp').mkdir(exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(dir=ROOT / '.tmp')
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'frame.png'
        self.snapshot = {'hwnd': 123, 'pid': 456, 'visible': True, 'minimized': False,
            'foreground': True, 'client_rect': [0, 0, 2, 2], 'window_rect': [0, 0, 2, 2],
            'client_screen_rect': [0, 0, 2, 2], 'size': [2, 2], 'dpi': 96}

    def test_pixel_success_and_black_quality_failure_are_separate(self):
        with patch.object(capture, '_window_snapshot', return_value=self.snapshot), \
                patch.object(capture, '_copy_frame', return_value=(2, 2, bytes(16))):
            result = capture.capture_window(123, 456, self.path)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['reason'], 'black_frame')
        self.assertEqual(result['pixel_acquisition_status'], 'succeeded')
        self.assertEqual(result['capture_stage'], 'quality_check')
        self.assertTrue(self.path.is_file())

    def test_prevalidation_and_pixel_failure_are_separate(self):
        with patch.object(capture, '_window_snapshot', side_effect=ValueError('window_invalid')):
            early = capture.capture_window(123, 456, self.path)
        self.assertEqual(early['pixel_acquisition_status'], 'not_attempted')
        with patch.object(capture, '_window_snapshot', return_value=self.snapshot), \
                patch.object(capture, '_copy_frame', side_effect=ValueError('PrintWindow_failed')):
            attempted = capture.capture_window(123, 456, self.path)
        self.assertEqual(attempted['pixel_acquisition_status'], 'failed')
        self.assertEqual(attempted['capture_stage'], 'pixel_acquisition')

    def test_postvalidation_failure_does_not_relabel_pixel_success(self):
        changed = {**self.snapshot, 'size': [4, 4]}
        with patch.object(capture, '_window_snapshot', side_effect=[self.snapshot, changed]), \
                patch.object(capture, '_copy_frame', return_value=(2, 2, bytes(16))):
            result = capture.capture_window(123, 456, self.path)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['pixel_acquisition_status'], 'succeeded')
        self.assertEqual(result['capture_stage'], 'post_capture_validation')
        self.assertFalse(self.path.exists())
