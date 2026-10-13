"""Persistent read/decide/locate/input/confirm loop, restricted to our harness."""
import json
from pathlib import Path
import time
from . import markers
from .native import NativeBlocked
from .policy import Unsupported, decide
from .state import Reducer
from .stream import Follower


class Reader:
    def __init__(self, path):
        self.follower = Follower(path)
        self.reducer = Reducer()
        self.observed = {}
        self.opportunities = {}

    def sample(self):
        reset, events = self.follower.poll()
        if reset:
            self.reducer.reset(self.follower.generation)
        for event in events:
            observed = time.monotonic()
            self.reducer.apply(event, observed)
            req = self.reducer.document(observed)['current'].get('request')
            if req and req.get('kind') == 'priority':
                key = self.reducer.key(req)
                self.observed.setdefault(key, observed)
                self.opportunities.setdefault(key, req.copy())
        view = self.reducer.document()['current']
        if self.follower.framer.partial:
            view = {**view, 'valid': False}  # wait for complete producer record
        return view


def verify_effect(before, after, plan):
    outcome = after.get('outcome') or {}
    if not after.get('valid') or after.get('request') is not None:
        return False
    if (outcome.get('root'), outcome.get('action'), outcome.get('source'), outcome.get('target')) != (
            plan.request, plan.action, plan.source, plan.target):
        return False
    old = {o['id']: o for o in before['objects']}
    new = {o['id']: o for o in after['objects']}
    if plan.action == 'land':
        return (old.get(plan.source, {}).get('zone') == 'hand' and
                new.get(plan.source, {}).get('zone') == 'battlefield' and
                after.get('land_plays') == before['land_plays'] + 1 and
                after.get('mana') == before['mana'])
    if plan.action == 'cast':
        return (old.get(plan.source, {}).get('zone') == 'hand' and
                new.get(plan.source, {}).get('zone') == 'graveyard' and
                after.get('mana') == before['mana'] - plan.cost and
                new.get(plan.target, {}).get('hp') == old[plan.target]['hp'] - 1 and
                new[plan.target]['zone'] == 'battlefield')
    return plan.action == 'pass' and after.get('priority') == 3 - before['self_seat']


class Executor:
    def __init__(self, reader, adapter, nonce, stop=lambda: False):
        self.reader, self.adapter, self.nonce, self.stop = reader, adapter, nonce, stop
        self.phase = 'pending'
        self.before = None

    def context(self, plan, request, version, kind):
        if self.stop():
            raise InterruptedError('cancelled')
        if time.monotonic() >= plan.expiry:
            raise TimeoutError('action_deadline')
        view = self.reader.sample()
        req = view.get('request') or {}
        if not view.get('valid'):
            raise NativeBlocked('invalid_or_partial_state')
        if (view['source_generation'], view['match'], view['game'], view['state_version'],
                req.get('id'), req.get('kind')) != (plan.generation, plan.match, plan.game,
                                                  version, request, kind):
            raise NativeBlocked('context_changed')
        if req.get('opportunity_id') != plan.opportunity_id or req.get('root') != plan.request:
            raise NativeBlocked('root_context_changed')
        if self.before is not None and any(view.get(field) != self.before.get(field) for field in
                    ('self_seat', 'objects', 'mana', 'land_plays', 'phase', 'priority', 'effects')):
            raise NativeBlocked('unexpected_substage_game_change')
        if kind != 'priority' and (req.get('source') != plan.source or req.get('targets') != [plan.target]):
            raise NativeBlocked('unsupported_child_prompt')
        if plan.target is not None and not any(o['id'] == plan.target for o in view['objects']):
            raise NativeBlocked('target_disappeared')
        if plan.source is not None and not any(o['id'] == plan.source and o['zone'] == 'hand'
                                               for o in view['objects']):
            raise NativeBlocked('source_disappeared')
        self.adapter.check()
        return view

    def point(self, plan, request, version, kind, object_id):
        # A frame may lag a just-published log record. Re-observe only before
        # dispatch. Never repeat semantic input on an unknown result.
        until = min(plan.expiry, time.monotonic() + 0.2)
        while True:
            view = self.context(plan, request, version, kind)
            frame = self.adapter.capture()
            try:
                locations = markers.locate(frame, view['layout'], markers.tag(self.nonce, view))
                if object_id not in locations:
                    raise NativeBlocked('object_marker_missing')
                # Double check state after capture; stale image cannot bind input.
                self.context(plan, request, version, kind)
                return locations[object_id]
            except ValueError:
                if time.monotonic() >= until:
                    raise NativeBlocked('visual_identity_unavailable')
                time.sleep(0.02)

    def event(self, plan, request, version, kind, obj, flag):
        point = self.point(plan, request, version, kind, obj)
        self.context(plan, request, version, kind)
        self.adapter.dispatch(point, flag)

    def click(self, plan, request, version, kind, obj):
        self.event(plan, request, version, kind, obj, 0x0002)
        self.event(plan, request, version, kind, obj, 0x0004)

    def transition(self, plan, old_request, version, new_request, kind):
        self.phase = 'awaiting_prompt'
        while time.monotonic() < plan.expiry:
            if self.stop():
                raise InterruptedError('cancelled')
            self.adapter.check()
            view = self.reader.sample()
            req = view.get('request') or {}
            if (req.get('id'), view.get('state_version')) == (new_request, version + 1):
                return self.context(plan, new_request, version + 1, kind)
            if (not view.get('valid') or (view.get('source_generation'), view.get('match'), view.get('game')) !=
                    (plan.generation, plan.match, plan.game) or
                    (req.get('id'), view.get('state_version')) != (old_request, version)):
                raise NativeBlocked('unexpected_transition_result_unknown')
            time.sleep(0.02)
        raise TimeoutError('prompt_timeout_result_unknown')

    def execute(self, plan, before):
        self.before = before
        self.adapter.first_input = self.adapter.last_input = None
        request, version, kind = plan.request, plan.state_version, 'priority'
        self.context(plan, request, version, kind)
        self.reader.reducer.consume('executing')
        self.phase = 'inputting'
        try:
            if plan.action == 'land':
                self.event(plan, request, version, kind, plan.source, 0x0002)
                self.event(plan, request, version, kind, markers.DROP, 0x0001)
                self.event(plan, request, version, kind, markers.DROP, 0x0004)
            elif plan.action == 'pass':
                self.click(plan, request, version, kind, markers.PASS)
            elif plan.action == 'cast':
                self.click(plan, request, version, kind, plan.source)
                self.transition(plan, request, version, plan.request + ':target', 'target')
                request, version, kind = plan.request + ':target', version + 1, 'target'
                self.click(plan, request, version, kind, plan.target)
                self.transition(plan, request, version, plan.request + ':submit', 'submit')
                request, version, kind = plan.request + ':submit', version + 1, 'submit'
                self.click(plan, request, version, kind, markers.SUBMIT)
            else:
                raise Unsupported('action_not_implemented')
            self.phase = 'awaiting_confirmation'
            while time.monotonic() < plan.expiry:
                if self.stop():
                    raise InterruptedError('cancelled')
                self.adapter.check()
                after = self.reader.sample()
                if (after.get('source_generation'), after.get('match'), after.get('game')) != (
                        plan.generation, plan.match, plan.game) or not after.get('valid'):
                    raise NativeBlocked('confirmation_context_invalid')
                if after.get('state_version') == version + 1 and verify_effect(before, after, plan):
                    # Screenshot also belongs to this exact accepted post-state.
                    markers.locate(self.adapter.capture(), after['layout'], markers.tag(self.nonce, after))
                    self.phase = 'completed'
                    self.reader.reducer.ledger[(plan.generation, plan.match, plan.game, plan.request)] = 'confirmed'
                    return time.monotonic(), after
                if after.get('state_version') != version:
                    raise NativeBlocked('postcondition_failed_result_unknown')
                time.sleep(0.02)
            raise TimeoutError('confirmation_timeout_result_unknown')
        finally:
            self.adapter.release()


def run_loop(reader, adapter, nonce, evidence_path, count=30, duration=90, stop=lambda: False):
    executor = Executor(reader, adapter, nonce, stop)
    rows, recorded = [], set()
    end = time.monotonic() + duration
    with Path(evidence_path).open('x', encoding='utf-8', buffering=1) as evidence:
        while time.monotonic() < end and len(rows) < count:
            view = reader.sample()
            if stop():
                break
            if not reader.reducer.actionable() or not view.get('valid'):
                # No new request: interruptible, low-frequency observation.
                time.sleep(0.05)
                continue
            key = reader.reducer.key()
            if key in recorded:
                time.sleep(0.05)
                continue
            req = view['request']
            row = {'opportunity_id': req['opportunity_id'], 'request_key': list(key),
                   'opportunity_at': req.get('opportunity_at'), 'observed': reader.observed[key],
                   'state_ready': time.monotonic(), 'decision_end': None, 'first_input': None,
                   'last_input': None, 'confirm': None, 'ended_at': None, 'status': None,
                   'action': None, 'plan': None, 'reason': None}
            adapter.first_input = adapter.last_input = None
            try:
                deadline = min(end, time.monotonic() + 2.5, req['received_at'] + 3)
                plan = decide(view, deadline, stop)
                row.update(decision_end=time.monotonic(), action=plan.action, plan=plan.to_dict())
                confirm, after = executor.execute(plan, view)
                row.update(status='confirmed', confirm=confirm, post_state=after)
            except Unsupported as exc:
                row.update(status='unsupported', reason=str(exc))
            except InterruptedError as exc:
                row.update(status='cancelled', reason=str(exc))
            except TimeoutError as exc:
                row.update(status='timeout', reason=str(exc))
            except (NativeBlocked, ValueError, OSError) as exc:
                row.update(status='uncertain' if adapter.first_input is not None else 'paused', reason=str(exc))
            except Exception as exc:
                row.update(status='uncertain' if adapter.first_input is not None else 'fail',
                           reason='executor_exception:' + type(exc).__name__)
            finally:
                row['decision_end'] = row['decision_end'] or time.monotonic()
                row.update(first_input=adapter.first_input, last_input=adapter.last_input,
                           ended_at=time.monotonic(), phase=executor.phase)
                reader.reducer.ledger[key] = row['status']
                recorded.add(key)
                rows.append(row)
                evidence.write(json.dumps(row) + '\n')
            if row['status'] != 'confirmed':
                break  # Fail closed; explicit new run required to re-enable.
        # Include every observed root opportunity, even when stopped or deadline
        # prevented a decision; do not silently drop failed/unprocessed chances.
        for key, req in reader.opportunities.items():
            if key not in recorded:
                row = {'opportunity_id': req['opportunity_id'], 'request_key': list(key),
                       'opportunity_at': req.get('opportunity_at'), 'observed': reader.observed[key],
                       'state_ready': None, 'decision_end': None, 'first_input': None,
                       'last_input': None, 'confirm': None, 'ended_at': time.monotonic(),
                       'status': 'cancelled' if stop() else 'paused', 'action': None,
                       'reason': 'loop_stopped_before_decision'}
                rows.append(row)
                evidence.write(json.dumps(row) + '\n')
    return rows
