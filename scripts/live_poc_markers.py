"""Explicit user or Codex window-validation click markers; no game input."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
import uuid
from contextlib import contextmanager


GAME_ACTION_TYPES = {
    '打出土地': 'play_land', '无目标咒语': 'cast_no_target',
    '有目标咒语': 'cast_targeted', '起动异能': 'activate',
    '宣告攻击': 'declare_attackers', '宣告阻挡': 'declare_blockers',
    '让过优先权': 'pass_priority', '观察咒语结算': 'observe_resolution',
}
WINDOW_ACTION_TYPES = {
    '最小化窗口': 'window_minimize', '恢复窗口': 'window_restore',
    '调整窗口尺寸': 'window_resize',
}
ACTION_TYPES = {**GAME_ACTION_TYPES, **WINDOW_ACTION_TYPES}
SOURCES = ('user_explicit_click', 'codex_window_validation')


def marker_options(source='user_explicit_click'):
    if source not in SOURCES:
        raise ValueError('unsupported_marker_source')
    return dict(WINDOW_ACTION_TYPES if source == 'codex_window_validation' else ACTION_TYPES)


@contextmanager
def marker_lock(path):
    # A Windows byte-range lock is released on process exit, including crashes.
    # The harmless lock file can remain without preventing a later restart.
    import msvcrt
    stream = Path(path).open('a+b')
    locked = False
    try:
        if stream.seek(0, 2) == 0:
            stream.write(b'0')
            stream.flush()
        stream.seek(0)
        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        locked = True
        yield
    finally:
        if locked:
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        stream.close()


def append_marker(directory, event_type, phase, note='', *, source='user_explicit_click'):
    options = marker_options(source)
    if event_type not in ACTION_TYPES.values() or phase not in ('before', 'after'):
        raise ValueError('unsupported_marker')
    if event_type not in options.values():
        raise ValueError('codex_marker_requires_window_event')
    window_event = event_type in WINDOW_ACTION_TYPES.values()
    row = {
        'event_id': str(uuid.uuid4()), 'event_type': event_type, 'phase': phase,
        'wall_time_utc': datetime.now(timezone.utc).isoformat(),
        'monotonic_ns': time.monotonic_ns(), 'note': note,
        'source': source, 'game_input_sent': False,
        'action_verification': ('window_event_marker_pending_evidence' if window_event
                                else 'user_report_pending_evidence'),
    }
    with (Path(directory) / 'action_markers.jsonl').open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(row, ensure_ascii=False) + '\n')
        stream.flush()
    return row


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--session', required=True, type=Path)
    parser.add_argument('--topmost', action='store_true', help='keep marker window visible; use PrintWindow capture')
    parser.add_argument('--source', choices=SOURCES, default='user_explicit_click',
                        help='Codex window validation exposes only window events; default records user clicks')
    args = parser.parse_args(argv)
    if not (args.session / 'manifest.json').is_file():
        parser.error('session manifest missing; start collector first')
    import tkinter as tk
    from tkinter import ttk
    options = marker_options(args.source)
    codex_window = args.source == 'codex_window_validation'
    with marker_lock(args.session / 'markers.lock'):
        root = tk.Tk()
        root.title('MTGA PoC 窗口验证标记（Codex）' if codex_window else 'MTGA PoC 操作标记（仅记录）')
        root.geometry('340x270+5+90')
        root.attributes('-topmost', args.topmost)
        ttk.Label(root, text=('选窗口事件 → 操作前 → 窗口管理 → 操作后' if codex_window
                             else '选动作 → 操作前 → 手动操作 → 操作后')).pack(pady=10)
        selected = tk.StringVar(value=next(iter(options)))
        ttk.Combobox(root, textvariable=selected, values=list(options),
                     state='readonly', width=28).pack(pady=5)
        ttk.Label(root, text='备注（可留空）').pack()
        note = ttk.Entry(root, width=36)
        note.pack(pady=5)
        status = tk.StringVar(value='来源：Codex 窗口验证；尚未记录' if codex_window
                              else '尚未记录；只记录本窗口按钮点击')

        def mark(phase):
            row = append_marker(args.session, options[selected.get()], phase, note.get(), source=args.source)
            status.set(f"已记录 {selected.get()} {'前' if phase == 'before' else '后'}\n"
                       f"{row['wall_time_utc']}\n{row['event_id'][:8]}")

        buttons = ttk.Frame(root)
        buttons.pack(pady=8)
        ttk.Button(buttons, text='操作前', command=lambda: mark('before')).pack(side='left', padx=12)
        ttk.Button(buttons, text='操作后', command=lambda: mark('after')).pack(side='left', padx=12)
        ttk.Label(root, textvariable=status, justify='center').pack(pady=5)
        ttk.Label(root, text='关闭此窗口不会停止后台采集').pack()
        root.mainloop()


if __name__ == '__main__':
    main()
