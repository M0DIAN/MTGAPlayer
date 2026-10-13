"""Windows ctypes/GDI screenshots and SendInput. No third-party runtime.

Only a HWND owned by the launched harness PID with its nonce title can be used.
All Win32 prototypes are explicit (including pointer-width handles).
"""
import ctypes as c
from ctypes import wintypes as w
import os
from pathlib import Path
import struct
import time


class NativeBlocked(RuntimeError):
    pass


def api():
    if os.name != 'nt':
        raise NativeBlocked('Windows_required')
    u, g = c.WinDLL('user32', use_last_error=True), c.WinDLL('gdi32', use_last_error=True)
    specs = {
        'GetForegroundWindow': (w.HWND, []), 'GetDesktopWindow': (w.HWND, []),
        'GetWindowThreadProcessId': (w.DWORD, [w.HWND, c.POINTER(w.DWORD)]),
        'GetWindowTextW': (c.c_int, [w.HWND, w.LPWSTR, c.c_int]),
        'IsWindowVisible': (w.BOOL, [w.HWND]), 'IsWindow': (w.BOOL, [w.HWND]),
        'IsIconic': (w.BOOL, [w.HWND]), 'SetForegroundWindow': (w.BOOL, [w.HWND]),
        'GetClientRect': (w.BOOL, [w.HWND, c.POINTER(w.RECT)]),
        'GetDpiForWindow': (w.UINT, [w.HWND]),
        'ClientToScreen': (w.BOOL, [w.HWND, c.POINTER(w.POINT)]),
        'GetDC': (w.HDC, [w.HWND]), 'ReleaseDC': (c.c_int, [w.HWND, w.HDC]),
        'GetSystemMetrics': (c.c_int, [c.c_int]), 'GetAsyncKeyState': (c.c_short, [c.c_int]),
        'OpenInputDesktop': (w.HANDLE, [w.DWORD, w.BOOL, w.DWORD]),
        'CloseDesktop': (w.BOOL, [w.HANDLE]),
        'GetLastInputInfo': (w.BOOL, [c.c_void_p]),
    }
    for name, (restype, args) in specs.items():
        fn = getattr(u, name)
        fn.restype, fn.argtypes = restype, args
    for name, restype, args in [
        ('CreateCompatibleDC', w.HDC, [w.HDC]),
        ('CreateCompatibleBitmap', w.HBITMAP, [w.HDC, c.c_int, c.c_int]),
        ('SelectObject', w.HANDLE, [w.HDC, w.HANDLE]),
        ('BitBlt', w.BOOL, [w.HDC, c.c_int, c.c_int, c.c_int, c.c_int, w.HDC, c.c_int, c.c_int, w.DWORD]),
        ('GetDIBits', c.c_int, [w.HDC, w.HBITMAP, w.UINT, w.UINT, c.c_void_p, c.c_void_p, w.UINT]),
        ('DeleteObject', w.BOOL, [w.HANDLE]), ('DeleteDC', w.BOOL, [w.HDC]),
    ]:
        fn = getattr(g, name)
        fn.restype, fn.argtypes = restype, args
    try:
        u.SetProcessDpiAwarenessContext.argtypes = [c.c_void_p]
        u.SetProcessDpiAwarenessContext(c.c_void_p(-4))
    except AttributeError:
        u.SetProcessDPIAware()
    return u, g


def probe():
    result = {'platform': os.name, 'input_sent': False, 'scope': 'read_only',
              'MTGA_object_location': 'NOT_IMPLEMENTED'}
    try:
        u, _ = api()
        desktop = u.OpenInputDesktop(0, False, 0x100)
        result.update(screen=[u.GetSystemMetrics(0), u.GetSystemMetrics(1)],
                      foreground_hwnd=int(u.GetForegroundWindow() or 0), input_desktop=bool(desktop))
        if desktop:
            u.CloseDesktop(desktop)
        # Enumerate titles only, no screenshots and no input to arbitrary windows.
        windows = []
        callback_type = c.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
        def enum(hwnd, param):
            title = c.create_unicode_buffer(512)
            u.GetWindowTextW(hwnd, title, 512)
            if u.IsWindowVisible(hwnd) and ('MTGA' in title.value or 'Arena' in title.value):
                windows.append({'hwnd': int(hwnd), 'title': title.value})
            return True
        u.EnumWindows.argtypes = [callback_type, w.LPARAM]
        u.EnumWindows(callback_type(enum), 0)
        result['matching_visible_windows'] = windows
        result['status'] = 'AVAILABLE_FOR_PROBE' if desktop else 'BLOCKED_NATIVE'
        result['limitations'] = 'Session visibility is scoped to this process; no MTGA input adapter.'
    except (OSError, NativeBlocked) as exc:
        result.update(status='BLOCKED_NATIVE', reason=str(exc))
    return result


class LASTINPUTINFO(c.Structure):
    _fields_ = [('cbSize', w.UINT), ('dwTime', w.DWORD)]


class MOUSEINPUT(c.Structure):
    _fields_ = [('dx', w.LONG), ('dy', w.LONG), ('mouseData', w.DWORD),
                ('dwFlags', w.DWORD), ('time', w.DWORD), ('dwExtraInfo', c.c_size_t)]


class KEYBDINPUT(c.Structure):
    _fields_ = [('wVk', w.WORD), ('wScan', w.WORD), ('dwFlags', w.DWORD),
                ('time', w.DWORD), ('dwExtraInfo', c.c_size_t)]


class HARDWAREINPUT(c.Structure):
    _fields_ = [('uMsg', w.DWORD), ('wParamL', w.WORD), ('wParamH', w.WORD)]


class INPUTUNION(c.Union):
    _fields_ = [('mi', MOUSEINPUT), ('ki', KEYBDINPUT), ('hi', HARDWAREINPUT)]


class INPUT(c.Structure):
    _anonymous_ = ('data',)
    _fields_ = [('type', w.DWORD), ('data', INPUTUNION)]


class Adapter:
    def __init__(self, handshake, process_pid, control_dir):
        self.u, self.g = api()
        self.hwnd, self.pid, self.nonce = handshake['hwnd'], process_pid, handshake['nonce']
        if handshake['pid'] != process_pid:
            raise NativeBlocked('handshake_PID_mismatch')
        self.control = Path(control_dir)
        self.expected_size = (820, 580)
        self.pressed = False
        self.first_input = self.last_input = None
        self.last_tick = self.input_tick()
        self.u.SendInput.argtypes = [w.UINT, c.POINTER(INPUT), c.c_int]
        self.u.SendInput.restype = w.UINT

    def input_tick(self):
        info = LASTINPUTINFO(c.sizeof(LASTINPUTINFO), 0)
        if not self.u.GetLastInputInfo(c.byref(info)):
            raise NativeBlocked('last_input_unavailable')
        return info.dwTime

    def check(self, takeover=True):
        if (self.control / 'stop').exists() or self.u.GetAsyncKeyState(0x1B) & 0x8000:
            raise InterruptedError('stop_or_escape')
        if (self.control / 'pause').exists():
            raise NativeBlocked('paused_remove_pause_and_explicitly_restart')
        pid = w.DWORD()
        self.u.GetWindowThreadProcessId(self.hwnd, c.byref(pid))
        title = c.create_unicode_buffer(256)
        self.u.GetWindowTextW(self.hwnd, title, 256)
        if (not self.u.IsWindow(self.hwnd) or pid.value != self.pid or
                title.value != 'MTGAPlayer Harness ' + self.nonce or
                not self.u.IsWindowVisible(self.hwnd) or self.u.IsIconic(self.hwnd)):
            raise NativeBlocked('harness_window_identity_or_visibility')
        if self.u.GetForegroundWindow() != self.hwnd:
            raise NativeBlocked('focus_lost')
        if takeover and self.input_tick() != self.last_tick:
            raise NativeBlocked('manual_takeover')
        rect = w.RECT()
        if not self.u.GetClientRect(self.hwnd, c.byref(rect)):
            raise NativeBlocked('client_rect_failed')
        if (rect.right, rect.bottom) != self.expected_size:
            raise NativeBlocked('unsupported_client_size_or_DPI')
        if self.u.GetDpiForWindow(self.hwnd) != 96:
            raise NativeBlocked('unsupported_DPI_requires_96')

    def capture(self):
        self.check()
        width, height = self.expected_size
        origin = w.POINT(0, 0)
        if not self.u.ClientToScreen(self.hwnd, c.byref(origin)):
            raise NativeBlocked('client_origin_failed')
        source = self.u.GetDC(0)
        memory = self.g.CreateCompatibleDC(source)
        bitmap = self.g.CreateCompatibleBitmap(source, width, height)
        old = self.g.SelectObject(memory, bitmap)
        try:
            if not source or not memory or not bitmap or not old:
                raise NativeBlocked('capture_allocation_failed')
            if not self.g.BitBlt(memory, 0, 0, width, height, source, origin.x, origin.y, 0x40CC0020):
                raise NativeBlocked('BitBlt_failed')
            self.g.SelectObject(memory, old)
            header = struct.pack('<IiiHHIIiiII', 40, width, -height, 1, 32, 0,
                                 width * height * 4, 0, 0, 0, 0)
            info = c.create_string_buffer(header)
            pixels = c.create_string_buffer(width * height * 4)
            if self.g.GetDIBits(memory, bitmap, 0, height, pixels, info, 0) != height:
                raise NativeBlocked('GetDIBits_failed')
            self.check()
            return width, height, pixels.raw
        finally:
            if old:
                self.g.SelectObject(memory, old)
            if bitmap:
                self.g.DeleteObject(bitmap)
            if memory:
                self.g.DeleteDC(memory)
            if source:
                self.u.ReleaseDC(0, source)

    def dispatch(self, point, flags):
        self.check()
        if (len(point) != 2 or not all(type(v) is int for v in point) or
                not (0 <= point[0] < self.expected_size[0] and 0 <= point[1] < self.expected_size[1])):
            raise NativeBlocked('point_outside_harness_client')
        origin = w.POINT(*point)
        if not self.u.ClientToScreen(self.hwnd, c.byref(origin)):
            raise NativeBlocked('client_origin_failed')
        left, top = self.u.GetSystemMetrics(76), self.u.GetSystemMetrics(77)
        width, height = self.u.GetSystemMetrics(78), self.u.GetSystemMetrics(79)
        if not (width > 1 and height > 1 and left <= origin.x < left + width and top <= origin.y < top + height):
            raise NativeBlocked('point_outside_virtual_desktop')
        item = INPUT(type=0, mi=MOUSEINPUT(round((origin.x - left) * 65535 / (width - 1)),
                    round((origin.y - top) * 65535 / (height - 1)), 0,
                    flags | 0x0001 | 0x8000 | 0x4000, 0, 0))
        at = time.monotonic()
        if self.first_input is None:
            self.first_input = at
        self.last_input = at
        if self.u.SendInput(1, c.byref(item), c.sizeof(INPUT)) != 1:
            raise NativeBlocked('SendInput_dispatch_failed_result_unknown')
        self.pressed = flags == 0x0002 or (self.pressed and flags != 0x0004)
        time.sleep(0.015)  # Allow queue delivery before acknowledging our input tick.
        self.last_tick = self.input_tick()

    def release(self):
        # Release a button owned by this adapter even after focus/stop failure.
        # No click or coordinate movement is sent in the emergency path.
        if self.pressed:
            item = INPUT(type=0, mi=MOUSEINPUT(0, 0, 0, 0x0004, 0, 0))
            self.u.SendInput(1, c.byref(item), c.sizeof(INPUT))
            self.pressed = False
            self.last_tick = self.input_tick()


def save_bmp(path, frame):
    width, height, data = frame
    header = struct.pack('<IiiHHIIiiII', 40, width, -height, 1, 32, 0, len(data), 0, 0, 0, 0)
    Path(path).write_bytes(struct.pack('<2sIHHI', b'BM', 54 + len(data), 0, 0, 54) + header + data)
