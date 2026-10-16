"""Local PoC: read-only MTGA window discovery and window-scoped BMP capture.

No input adapter is instantiated and no game input is dispatched. PrintWindow
is attempted explicitly; a caller may separately try ``method='screen'``.
Screen capture refuses overlapping visible top-level windows. That check is
best effort, not a guarantee against a window appearing during the copy.
"""
from __future__ import annotations

import ctypes as c
from ctypes import wintypes as w
import hashlib
import math
import os
from pathlib import Path
import struct
import zlib

from mtgaplayer.native import api, save_bmp


_APIS = None


def _apis():
    global _APIS
    if _APIS is None:
        u, g = api()
        k = c.WinDLL('kernel32', use_last_error=True)
        for name, restype, args in (
            ('GetWindowRect', w.BOOL, [w.HWND, c.POINTER(w.RECT)]),
            ('PrintWindow', w.BOOL, [w.HWND, w.HDC, w.UINT]),
            ('GetWindow', w.HWND, [w.HWND, w.UINT]),
        ):
            fn = getattr(u, name)
            fn.restype, fn.argtypes = restype, args
        k.OpenProcess.restype = w.HANDLE
        k.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
        k.QueryFullProcessImageNameW.restype = w.BOOL
        k.QueryFullProcessImageNameW.argtypes = [w.HANDLE, w.DWORD, w.LPWSTR, c.POINTER(w.DWORD)]
        k.CloseHandle.restype = w.BOOL
        k.CloseHandle.argtypes = [w.HANDLE]
        g.PatBlt.restype = w.BOOL
        g.PatBlt.argtypes = [w.HDC, c.c_int, c.c_int, c.c_int, c.c_int, w.DWORD]
        _APIS = u, g, k
    return _APIS


def _process_image(pid):
    _, _, k = _apis()
    handle = k.OpenProcess(0x1000, False, pid)
    if not handle:
        return None
    try:
        name, size = c.create_unicode_buffer(32768), w.DWORD(32768)
        return name.value if k.QueryFullProcessImageNameW(handle, 0, name, c.byref(size)) else None
    finally:
        k.CloseHandle(handle)


def _rect(rect):
    return [rect.left, rect.top, rect.right, rect.bottom]


def _window_snapshot(hwnd, expected_pid=None):
    u, _, _ = _apis()
    if not u.IsWindow(hwnd):
        raise ValueError('window_invalid')
    pid = w.DWORD()
    if not u.GetWindowThreadProcessId(hwnd, c.byref(pid)):
        raise ValueError('window_pid_unavailable')
    if expected_pid is not None and pid.value != expected_pid:
        raise ValueError('window_pid_changed')
    image = _process_image(pid.value)
    if image is None or Path(image).name.casefold() != 'mtga.exe':
        raise ValueError('process_is_not_mtga')
    client, window, origin = w.RECT(), w.RECT(), w.POINT(0, 0)
    if not u.GetClientRect(hwnd, c.byref(client)) or not u.GetWindowRect(hwnd, c.byref(window)):
        raise ValueError('window_rect_unavailable')
    if not u.ClientToScreen(hwnd, c.byref(origin)):
        raise ValueError('client_origin_unavailable')
    width, height = client.right - client.left, client.bottom - client.top
    return {
        'hwnd': int(hwnd), 'pid': pid.value, 'process_name': Path(image).name,
        'visible': bool(u.IsWindowVisible(hwnd)), 'minimized': bool(u.IsIconic(hwnd)),
        'foreground': int(u.GetForegroundWindow() or 0) == int(hwnd),
        'client_rect': _rect(client), 'window_rect': _rect(window),
        'client_screen_rect': [origin.x, origin.y, origin.x + width, origin.y + height],
        'size': [width, height], 'dpi': int(u.GetDpiForWindow(hwnd)),
    }


def find_mtga_window():
    """Find a real MTGA.exe-owned top-level HWND; title alone is never trusted."""
    if os.name != 'nt':
        return {'status': 'failed', 'reason': 'Windows_required'}
    u, _, _ = _apis()
    windows = []
    callback_type = c.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)

    def visit(hwnd, _):
        try:
            row = _window_snapshot(hwnd)
            if all(value > 0 for value in row['size']):
                windows.append(row)
        except (OSError, ValueError):
            pass
        return True

    u.EnumWindows.restype = w.BOOL
    u.EnumWindows.argtypes = [callback_type, w.LPARAM]
    callback = callback_type(visit)
    if not u.EnumWindows(callback, 0):
        return {'status': 'failed', 'reason': 'EnumWindows_failed', 'winerror': c.get_last_error()}
    if not windows:
        return {'status': 'failed', 'reason': 'mtga_window_not_found'}
    windows.sort(key=lambda row: (row['visible'], not row['minimized'], row['size'][0] * row['size'][1]),
                 reverse=True)
    return {'status': 'success', **windows[0], 'matching_window_count': len(windows)}


def _intersects(a, b):
    return max(a[0], b[0]) < min(a[2], b[2]) and max(a[1], b[1]) < min(a[3], b[3])


def _occluders(hwnd, rect):
    u, _, _ = _apis()
    result, seen = [], set()
    other = u.GetWindow(hwnd, 3)  # GW_HWNDPREV: windows higher in the Z order.
    while other and int(other) not in seen:
        seen.add(int(other))
        if u.IsWindowVisible(other) and not u.IsIconic(other):
            bounds = w.RECT()
            if u.GetWindowRect(other, c.byref(bounds)) and _intersects(rect, _rect(bounds)):
                # No titles, pixels or unrelated application input are collected.
                result.append(int(other))
        other = u.GetWindow(other, 3)
    return result


def _quality(frame):
    width, height, pixels = frame
    count = width * height
    step = max(1, math.ceil(count / 65536))
    total = squared = black = white = sampled = 0
    for index in range(0, count, step):
        b, g, r = pixels[index * 4:index * 4 + 3]
        value = (r + g + b) / 3
        total += value
        squared += value * value
        sampled += 1
        black += max(r, g, b) <= 8
        white += min(r, g, b) >= 247
    mean = total / sampled
    variance = max(0.0, squared / sampled - mean * mean)
    reason = ('black_frame' if black / sampled > .995 else
              'white_frame' if white / sampled > .995 else
              'low_variance_frame' if variance < 1.0 else None)
    return {'sampled_pixels': sampled, 'mean_rgb_intensity': mean,
            'variance_rgb_intensity': variance, 'black_fraction': black / sampled,
            'white_fraction': white / sampled, 'failure_reason': reason,
            'heuristic_only': True, 'game_content_verified': False}


def _save_image(path, frame):
    if path.suffix.casefold() == '.bmp':
        save_bmp(path, frame)
        return
    width, height, pixels = frame
    # GDI's alpha byte is undefined; encode opaque RGB rather than hiding valid
    # captured pixels behind zero alpha. BGRA bytes are explicitly reordered.
    rgb = bytearray(width * height * 3)
    rgb[0::3], rgb[1::3], rgb[2::3] = pixels[2::4], pixels[1::4], pixels[0::4]
    scanlines = b''.join(b'\x00' + rgb[row * width * 3:(row + 1) * width * 3]
                         for row in range(height))

    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)

    path.write_bytes(b'\x89PNG\r\n\x1a\n' +
                     chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)) +
                     chunk(b'IDAT', zlib.compress(scanlines, 1)) + chunk(b'IEND', b''))


def _copy_frame(hwnd, snapshot, method):
    u, g, _ = _apis()
    if method == 'printwindow':
        left, top, right, bottom = snapshot['window_rect']
        width, height = right - left, bottom - top
    else:
        width, height = snapshot['size']
    if width <= 0 or height <= 0 or width * height > 100_000_000:
        raise ValueError('invalid_capture_dimensions')
    source = u.GetDC(0)
    memory = bitmap = old = None
    try:
        if not source:
            raise ValueError('capture_source_unavailable')
        memory = g.CreateCompatibleDC(source)
        bitmap = g.CreateCompatibleBitmap(source, width, height)
        if not memory or not bitmap:
            raise ValueError('capture_allocation_failed')
        old = g.SelectObject(memory, bitmap)
        if not old or old == c.c_void_p(-1).value:
            old = None
            raise ValueError('capture_selection_failed')
        if not g.PatBlt(memory, 0, 0, width, height, 0x00000042):  # BLACKNESS
            raise ValueError('capture_initialization_failed')
        if method == 'printwindow':
            if not u.PrintWindow(hwnd, memory, 2):  # PW_RENDERFULLCONTENT, no input.
                raise ValueError('PrintWindow_failed')
        else:
            x, y, _, _ = snapshot['client_screen_rect']
            if not g.BitBlt(memory, 0, 0, width, height, source, x, y, 0x40CC0020):
                raise ValueError('BitBlt_failed')
        if not g.SelectObject(memory, old):
            raise ValueError('capture_restore_selection_failed')
        info = c.create_string_buffer(struct.pack('<IiiHHIIiiII', 40, width, -height, 1, 32,
                                                  0, width * height * 4, 0, 0, 0, 0))
        pixels = c.create_string_buffer(width * height * 4)
        if g.GetDIBits(memory, bitmap, 0, height, pixels, info, 0) != height:
            raise ValueError('GetDIBits_failed')
        data = pixels.raw
        if method == 'printwindow':
            client_width, client_height = snapshot['size']
            x = snapshot['client_screen_rect'][0] - snapshot['window_rect'][0]
            y = snapshot['client_screen_rect'][1] - snapshot['window_rect'][1]
            if x < 0 or y < 0 or x + client_width > width or y + client_height > height:
                raise ValueError('client_crop_outside_window')
            data = b''.join(data[((y + row) * width + x) * 4:
                                 ((y + row) * width + x + client_width) * 4]
                            for row in range(client_height))
            width, height = client_width, client_height
        return width, height, data
    finally:
        if old and memory:
            g.SelectObject(memory, old)
        if bitmap:
            g.DeleteObject(bitmap)
        if memory:
            g.DeleteDC(memory)
        if source:
            u.ReleaseDC(0, source)


def capture_window(hwnd: int, pid: int, output_path: Path, method='printwindow') -> dict:
    """Capture only the identified MTGA client to PNG/BMP with honest metadata.

    A successful API/quality result still requires independent visual inspection.
    Blank images are saved as local failure evidence, never labeled valid game
    frames. Occluded screen captures and changed-window frames are not saved.
    PrintWindow can block while the game responds: run this in a separately
    bounded collector process rather than the analysis process.
    """
    result = {'status': 'failed', 'hwnd': hwnd, 'pid': pid, 'method': method,
              'input_sent': False, 'path': None, 'sha256': None}
    try:
        if os.name != 'nt':
            raise ValueError('Windows_required')
        if method not in {'printwindow', 'screen'}:
            raise ValueError('unsupported_capture_method')
        output_path = Path(output_path)
        if output_path.suffix.casefold() not in {'.png', '.bmp'}:
            raise ValueError('unsupported_output_extension')
        before = _window_snapshot(hwnd, pid)
        result.update(before)
        if before['minimized']:
            raise ValueError('window_minimized')
        if not before['visible']:
            raise ValueError('window_not_visible')
        if not all(value > 0 for value in before['size']):
            raise ValueError('empty_client_area')
        if method == 'screen':
            u, _, _ = _apis()
            x, y = u.GetSystemMetrics(76), u.GetSystemMetrics(77)
            desktop = [x, y, x + u.GetSystemMetrics(78), y + u.GetSystemMetrics(79)]
            rect = before['client_screen_rect']
            if rect[0] < desktop[0] or rect[1] < desktop[1] or rect[2] > desktop[2] or rect[3] > desktop[3]:
                raise ValueError('client_outside_virtual_desktop')
            occluders = _occluders(hwnd, rect)
            result['occlusion_check'] = 'visible_window_rectangles_before_and_after_best_effort'
            if occluders:
                result['occluding_hwnds'] = occluders
                raise ValueError('window_occluded')
        frame = _copy_frame(hwnd, before, method)
        after = _window_snapshot(hwnd, pid)
        for key in ('client_rect', 'client_screen_rect', 'window_rect', 'size', 'dpi'):
            if after[key] != before[key]:
                result['after'] = after
                raise ValueError('window_geometry_changed_during_capture')
        if after['minimized'] or not after['visible']:
            raise ValueError('window_visibility_changed_during_capture')
        if method == 'screen':
            occluders = _occluders(hwnd, after['client_screen_rect'])
            if occluders:
                result['occluding_hwnds'] = occluders
                raise ValueError('window_occluded_during_capture')
        quality = _quality(frame)
        result['quality'] = quality
        output_path.parent.mkdir(parents=True, exist_ok=True)
        _save_image(output_path, frame)
        result.update(path=str(output_path.resolve()), sha256=hashlib.sha256(output_path.read_bytes()).hexdigest(),
                      foreground_after=after['foreground'])
        if quality['failure_reason']:
            raise ValueError(quality['failure_reason'])
        result.update(status='success', reason=None)
    except (OSError, ValueError, RuntimeError) as exc:
        result.update(reason=str(exc), last_winerror=c.get_last_error())
    return result
