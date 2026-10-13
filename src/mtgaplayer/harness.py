"""Independent Tk process. Semantic changes occur only in mouse callbacks.

Scene preparation creates opportunities; it never completes a semantic action.
Observation channel contains identities/state, no object coordinates. Layouts
alternate and object IDs do not encode position. All assets are synthetic.
"""
import ctypes as c
import json
import os
from pathlib import Path
import time
import tkinter as tk
from . import markers
from .native import api
from .files import atomic


class Harness:
    def __init__(self, directory, nonce, count=30, scenario='normal'):
        self.directory, self.nonce = Path(directory), nonce
        self.directory.mkdir(parents=True, exist_ok=True)
        self.count, self.scenario = count, scenario
        self.log = (self.directory / 'normalized.jsonl').open('a', encoding='utf-8', buffering=1)
        self.audit = (self.directory / 'ui-events.jsonl').open('a', encoding='utf-8', buffering=1)
        u, _ = api()
        self.root = tk.Tk()
        self.root.title('MTGAPlayer Harness ' + nonce)
        self.root.geometry('820x580+60+60')
        self.root.resizable(False, False)
        self.canvas = tk.Canvas(self.root, width=820, height=580, bg='#253344', highlightthickness=0)
        self.canvas.pack(fill='both', expand=True)
        self.canvas.bind('<ButtonPress-1>', self.press)
        self.canvas.bind('<ButtonRelease-1>', self.release)
        self.root.bind('<Escape>', lambda event: self.stop())
        self.root.protocol('WM_DELETE_WINDOW', self.stop)
        self.match, self.game, self.version, self.layout = 'synthetic-match', 'game-1', 0, 0
        self.index, self.completed, self.outcome = 0, 0, None
        self.drag_source = None
        self.request = None
        self.regions = {}
        self.root.update()
        u.GetParent.restype, u.GetParent.argtypes = c.c_void_p, [c.c_void_p]
        self.hwnd = u.GetParent(self.root.winfo_id()) or self.root.winfo_id()
        self.root.lift()
        u.SetForegroundWindow(self.hwnd)
        self.write({'type': 'begin', 'self_seat': 1})
        self.scene()
        self.root.update()
        atomic(self.directory / 'handshake.json', {'pid': os.getpid(), 'hwnd': self.hwnd,
               'nonce': nonce, 'client_size': [820, 580], 'dpi': 96, 'protocol': 'markers-v1',
               'scenario': scenario, 'ready_at': time.monotonic()})
        self.root.after(50, self.controls)

    def write(self, value):
        self.log.write(json.dumps({'schema': 1, 'match': self.match, 'game': self.game, **value}) + '\n')

    def request_for(self, kind, suffix='', **extra):
        return {'id': f'req-{self.index}{suffix}', 'kind': kind,
                'opportunity_id': f'opp-{self.index}', 'opportunity_at': self.opportunity_at,
                'root': f'req-{self.index}', **extra}

    def scene(self):
        if self.index >= self.count:
            self.request = None
            self.publish()
            atomic(self.directory / 'complete.json', {'completed': self.completed, 'at': time.monotonic()})
            return
        self.index += 1
        self.outcome = None
        self.mode = ('land', 'cast', 'pass')[(self.index - 1) % 3]
        self.mana, self.land_plays, self.priority = 2, 0, 1
        self.objects = [{'id': 91, 'owner': 2, 'zone': 'battlefield', 'visibility': 'public',
                         'rule': 'inert_creature', 'hp': 5, 'tapped': False}]
        if self.mode != 'pass':
            self.objects.append({'id': 17, 'owner': 1, 'zone': 'hand', 'visibility': 'self',
                                 'rule': 'land' if self.mode == 'land' else 'spark',
                                 'hp': None, 'tapped': False})
        self.opportunity_at = time.monotonic()
        self.request = self.request_for('priority')
        self.selected_target = None
        self.publish()
        if self.scenario == 'reorder':
            self.root.after(15, self.reorder)
        elif self.scenario == 'target-disappear' and self.mode == 'cast':
            self.root.after(120, self.disappear)

    def reorder(self):
        # New layout with unchanged logical version/request; screen tags still
        # bind layout. Player must rescan, never use an earlier point.
        self.layout += 1
        self.render()

    def disappear(self):
        self.objects = [o for o in self.objects if o['id'] != 91]
        self.publish()

    def publish(self):
        self.version += 1
        self.layout += 1
        view = {'state_version': self.version, 'objects': self.objects, 'mana': self.mana,
                'land_plays': self.land_plays, 'phase': 'main', 'priority': self.priority,
                'effects': ['unknown_test_effect'] if self.scenario == 'unsupported' else [],
                'request': self.request, 'layout': self.layout, 'outcome': self.outcome}
        self.write({'type': 'full', 'self_seat': 1, **view})
        self.render()

    def render(self):
        self.canvas.delete('all')
        view = {'match': self.match, 'game': self.game, 'state_version': self.version,
                'request': self.request}
        context = markers.tag(self.nonce, view)
        self.regions = {}
        def region(obj, x, y, label, height=60):
            self.canvas.create_rectangle(x, y, x + 210, y + height, fill='#526576', outline='white')
            markers.draw(self.canvas, x + 4, y + 4, obj, self.layout, context)
            self.canvas.create_text(x + 105, y + 36, text=label, fill='white')
            self.regions[obj] = (x, y, x + 210, y + height)
        markers.draw(self.canvas, 8, 8, markers.HEADER, self.layout, context)
        self.canvas.create_text(510, 22, text=f'SYNTHETIC ONLY | {self.index}/{self.count} | {self.mode}', fill='white')
        positions = [30, 300, 570]
        if self.layout % 2:
            positions.reverse()
        for i, obj in enumerate(sorted(self.objects, key=lambda o: -o['id'])):
            if obj['zone'] in {'hand', 'battlefield'}:
                region(obj['id'], positions[i], 420 if obj['zone'] == 'hand' else 90,
                       f"object {obj['id']} {obj['rule']} hp={obj['hp']}")
        region(markers.DROP, 300, 240, 'Drag land here')
        region(markers.PASS, 30, 510, 'Pass priority')
        if self.request and self.request['kind'] == 'submit':
            region(markers.SUBMIT, 570, 510, 'Confirm spell')
        self.canvas.create_text(410, 360, text='Escape / stop file stops. pause file pauses; restart explicitly to re-enable.', fill='white')

    def hit(self, x, y):
        for obj, (left, top, right, bottom) in self.regions.items():
            if left <= x < right and top <= y < bottom:
                return obj
        return None

    def record_input(self, kind, event, hit):
        self.audit.write(json.dumps({'at': time.monotonic(), 'kind': kind,
                         'hit_object': hit, 'x': event.x, 'y': event.y,
                         'request': (self.request or {}).get('id'), 'state_version': self.version}) + '\n')

    def press(self, event):
        obj = self.hit(event.x, event.y)
        self.record_input('press', event, obj)
        self.drag_source = obj

    def release(self, event):
        obj = self.hit(event.x, event.y)
        self.record_input('release', event, obj)
        source, self.drag_source = self.drag_source, None
        if not self.request or (self.directory / 'pause').exists() or (self.directory / 'stop').exists():
            return
        kind = self.request['kind']
        if kind == 'priority' and self.mode == 'land' and source == 17 and obj == markers.DROP:
            self.objects = [{**o, 'zone': 'battlefield', 'visibility': 'public'} if o['id'] == 17 else o
                            for o in self.objects]
            self.land_plays += 1
            self.finish('land', 17, None)
        elif kind == 'priority' and self.mode == 'cast' and source == obj == 17:
            self.request = self.request_for('target', ':target', source=17, targets=[91])
            self.publish()
        elif kind == 'target' and source == obj == 91 and any(o['id'] == 91 for o in self.objects):
            self.selected_target = 91
            self.request = self.request_for('submit', ':submit', source=17, targets=[91])
            self.publish()
        elif kind == 'submit' and source == obj == markers.SUBMIT and self.selected_target == 91:
            self.mana -= 1
            self.objects = [{**o, 'zone': 'graveyard', 'visibility': 'public'} if o['id'] == 17 else
                            {**o, 'hp': o['hp'] - 1} if o['id'] == 91 else o for o in self.objects]
            self.finish('cast', 17, 91)
        elif kind == 'priority' and self.mode == 'pass' and source == obj == markers.PASS:
            self.priority = 2
            self.finish('pass', None, None)

    def finish(self, action, source, target):
        self.outcome = {'root': f'req-{self.index}', 'opportunity_id': f'opp-{self.index}',
                        'action': action, 'source': source, 'target': target, 'accepted_at': time.monotonic()}
        self.request = None
        self.completed += 1
        self.publish()
        self.root.after(350, self.scene)

    def controls(self):
        if (self.directory / 'stop').exists():
            self.stop()
        else:
            self.root.after(50, self.controls)

    def stop(self):
        self.root.destroy()

    def run(self):
        try:
            self.root.mainloop()
        finally:
            self.log.close()
            self.audit.close()


def run(directory, nonce, count=30, scenario='normal'):
    Harness(directory, nonce, count, scenario).run()
