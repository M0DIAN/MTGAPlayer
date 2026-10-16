"""Offline safety regressions; none establishes real MTGA capture success."""
import importlib.util
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import zlib


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('live_poc_capture', ROOT / 'scripts/live_poc_capture.py')
capture = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(capture)


def snapshot():
    return {'hwnd': 123, 'pid': 456, 'visible': True, 'minimized': False,
            'foreground': False, 'client_rect': [0, 0, 2, 2],
            'window_rect': [10, 10, 12, 12], 'client_screen_rect': [10, 10, 12, 12],
            'size': [2, 2], 'dpi': 96}


class CaptureSafetyTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.output = Path(self.directory.name) / 'sample.bmp'
        self.frame = (2, 2, bytes([0, 0, 0, 0, 255, 255, 255, 0] * 2))

    def test_quality_rejects_black_white_and_flat_color(self):
        for color, expected in (([0, 0, 0, 0], 'black_frame'),
                                ([255, 255, 255, 0], 'white_frame'),
                                ([40, 80, 120, 0], 'low_variance_frame')):
            with self.subTest(color=color):
                result = capture._quality((2, 2, bytes(color * 4)))
                self.assertEqual(result['failure_reason'], expected)
                self.assertFalse(result['game_content_verified'])

    def test_nonblank_output_still_requires_game_content_verification(self):
        with patch.object(capture, '_window_snapshot', return_value=snapshot()), \
                patch.object(capture, '_copy_frame', return_value=self.frame):
            result = capture.capture_window(123, 456, self.output)
        self.assertEqual(result['status'], 'success')
        self.assertFalse(result['quality']['game_content_verified'])
        self.assertFalse(result['input_sent'])
        self.assertEqual(len(result['sha256']), 64)
        self.assertTrue(self.output.read_bytes().startswith(b'BM'))

    def test_blank_saved_as_failed_evidence(self):
        with patch.object(capture, '_window_snapshot', return_value=snapshot()), \
                patch.object(capture, '_copy_frame', return_value=(2, 2, bytes(16))):
            result = capture.capture_window(123, 456, self.output)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['reason'], 'black_frame')
        self.assertTrue(self.output.is_file())
        self.assertIsNotNone(result['sha256'])

    def test_png_encodes_real_rgb_channels_without_gdi_alpha(self):
        output = self.output.with_suffix('.png')
        capture._save_image(output, (2, 1, bytes([255, 0, 0, 0, 0, 0, 255, 0])))
        data = output.read_bytes()
        self.assertEqual(data[:8], b'\x89PNG\r\n\x1a\n')
        offset, chunks = 8, {}
        while offset < len(data):
            length = struct.unpack('>I', data[offset:offset + 4])[0]
            kind, payload = data[offset + 4:offset + 8], data[offset + 8:offset + 8 + length]
            checksum = struct.unpack('>I', data[offset + 8 + length:offset + 12 + length])[0]
            self.assertEqual(checksum, zlib.crc32(kind + payload) & 0xffffffff)
            chunks[kind] = payload
            offset += 12 + length
        self.assertEqual(struct.unpack('>IIBBBBB', chunks[b'IHDR']), (2, 1, 8, 2, 0, 0, 0))
        self.assertEqual(zlib.decompress(chunks[b'IDAT']), b'\x00\x00\x00\xff\xff\x00\x00')

    def test_minimized_never_copies_or_saves(self):
        row = snapshot()
        row['minimized'] = True
        with patch.object(capture, '_window_snapshot', return_value=row), \
                patch.object(capture, '_copy_frame') as copy_frame:
            result = capture.capture_window(123, 456, self.output)
        self.assertEqual(result['reason'], 'window_minimized')
        copy_frame.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_geometry_change_discards_pixels(self):
        before, after = snapshot(), snapshot()
        after['size'] = [4, 4]
        with patch.object(capture, '_window_snapshot', side_effect=[before, after]), \
                patch.object(capture, '_copy_frame', return_value=self.frame):
            result = capture.capture_window(123, 456, self.output)
        self.assertEqual(result['reason'], 'window_geometry_changed_during_capture')
        self.assertFalse(self.output.exists())

    def test_identity_change_discards_pixels(self):
        with patch.object(capture, '_window_snapshot', side_effect=[snapshot(), ValueError('window_pid_changed')]), \
                patch.object(capture, '_copy_frame', return_value=self.frame):
            result = capture.capture_window(123, 456, self.output)
        self.assertEqual(result['reason'], 'window_pid_changed')
        self.assertFalse(self.output.exists())

    def test_screen_occlusion_refuses_copy_and_save(self):
        class Metrics:
            def GetSystemMetrics(self, metric):
                return {76: 0, 77: 0, 78: 1920, 79: 1080}[metric]
        with patch.object(capture, '_window_snapshot', return_value=snapshot()), \
                patch.object(capture, '_apis', return_value=(Metrics(), None, None)), \
                patch.object(capture, '_occluders', return_value=[999]), \
                patch.object(capture, '_copy_frame') as copy_frame:
            result = capture.capture_window(123, 456, self.output, 'screen')
        self.assertEqual(result['reason'], 'window_occluded')
        copy_frame.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_screen_occlusion_after_copy_discards_pixels(self):
        class Metrics:
            def GetSystemMetrics(self, metric):
                return {76: 0, 77: 0, 78: 1920, 79: 1080}[metric]
        with patch.object(capture, '_window_snapshot', return_value=snapshot()), \
                patch.object(capture, '_apis', return_value=(Metrics(), None, None)), \
                patch.object(capture, '_occluders', side_effect=[[], [999]]), \
                patch.object(capture, '_copy_frame', return_value=self.frame):
            result = capture.capture_window(123, 456, self.output, 'screen')
        self.assertEqual(result['reason'], 'window_occluded_during_capture')
        self.assertFalse(self.output.exists())

    def test_invalid_method_never_probes(self):
        with patch.object(capture, '_window_snapshot') as probe:
            result = capture.capture_window(123, 456, self.output, 'unknown')
        self.assertEqual(result['reason'], 'unsupported_capture_method')
        probe.assert_not_called()

    def test_gdi_resources_released_on_printwindow_and_readback_failures(self):
        for failure in ('printwindow', 'readback'):
            with self.subTest(failure=failure):
                calls = []

                class User:
                    def GetDC(self, hwnd):
                        return 1

                    def PrintWindow(self, *args):
                        return failure != 'printwindow'

                    def ReleaseDC(self, hwnd, dc):
                        calls.append(('release', hwnd, dc))

                class Gdi:
                    def CreateCompatibleDC(self, source):
                        return 2

                    def CreateCompatibleBitmap(self, source, width, height):
                        return 3

                    def SelectObject(self, memory, obj):
                        calls.append(('select', memory, obj))
                        return 4

                    def PatBlt(self, *args):
                        return True

                    def GetDIBits(self, *args):
                        return 0

                    def DeleteObject(self, obj):
                        calls.append(('delete_bitmap', obj))

                    def DeleteDC(self, dc):
                        calls.append(('delete_dc', dc))

                expected = 'PrintWindow_failed' if failure == 'printwindow' else 'GetDIBits_failed'
                with patch.object(capture, '_apis', return_value=(User(), Gdi(), None)):
                    with self.assertRaisesRegex(ValueError, expected):
                        capture._copy_frame(123, snapshot(), 'printwindow')
                self.assertEqual(calls[-3:], [('delete_bitmap', 3), ('delete_dc', 2), ('release', 0, 1)])
                self.assertIn(('select', 2, 4), calls)

    def test_gdi_allocation_failure_releases_available_resources(self):
        calls = []

        class User:
            def GetDC(self, hwnd):
                return 1

            def ReleaseDC(self, hwnd, dc):
                calls.append(('release', hwnd, dc))

        class Gdi:
            def CreateCompatibleDC(self, source):
                return 2

            def CreateCompatibleBitmap(self, source, width, height):
                return None

            def DeleteDC(self, dc):
                calls.append(('delete_dc', dc))

        with patch.object(capture, '_apis', return_value=(User(), Gdi(), None)):
            with self.assertRaisesRegex(ValueError, 'capture_allocation_failed'):
                capture._copy_frame(123, snapshot(), 'printwindow')
        self.assertEqual(calls, [('delete_dc', 2), ('release', 0, 1)])


if __name__ == '__main__':
    unittest.main()
