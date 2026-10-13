"""Synthetic rules v1 only: land, generic-1 spark (1 damage), inert creature.

This is a finite tactic, not an MTGA legality oracle or global optimizer.
"""
from dataclasses import asdict, dataclass
import time
from .state import integer


class Unsupported(ValueError):
    pass


@dataclass(frozen=True)
class Plan:
    generation: int
    match: str
    game: str
    request: str
    state_version: int
    action_id: str
    action: str
    source: int | None
    target: int | None
    expiry: float
    opportunity_id: str
    cost: int
    effect: str

    def to_dict(self):
        return asdict(self)


def decide(view, deadline, cancelled=lambda: False):
    def check():
        if cancelled():
            raise InterruptedError('cancelled')
        if time.monotonic() >= deadline:
            raise TimeoutError('decision_deadline')
    check()
    req = view.get('request') or {}
    if not view.get('valid') or req.get('kind') != 'priority':
        raise Unsupported('requires_valid_priority')
    if (view.get('effects') != [] or view.get('phase') != 'main' or
            view.get('priority') != view.get('self_seat') or
            not integer(view.get('mana')) or not integer(view.get('land_plays'))):
        raise Unsupported('unknown_effect_or_required_rule_field')
    candidates = [(0, 'pass', None, None, 0, 'priority_transfer')]
    objects = view.get('objects', [])
    for obj in objects:
        check()
        if obj.get('rule') not in {'land', 'spark', 'inert_creature'}:
            raise Unsupported('unknown_visible_rule')
        if obj['rule'] == 'inert_creature' and not integer(obj.get('hp')):
            raise Unsupported('unknown_target_health')
        if obj.get('owner') == view['self_seat'] and obj.get('zone') == 'hand':
            if obj['rule'] == 'land' and view['land_plays'] == 0:
                candidates.append((30, 'land', obj['id'], None, 0, 'land_enters'))
            if obj['rule'] == 'spark' and view['mana'] >= 1:
                for target in objects:
                    check()
                    if (target.get('rule') == 'inert_creature' and target.get('zone') == 'battlefield'
                            and target.get('owner') != view['self_seat'] and target.get('hp', 0) > 0):
                        candidates.append((20, 'cast', obj['id'], target['id'], 1, 'damage_1'))
    check()
    choice = sorted(candidates, key=lambda c: (-c[0], c[2] or 0, c[3] or 0))[0]
    _, action, source, target, cost, effect = choice
    return Plan(view['source_generation'], view['match'], view['game'], req['id'],
                view['state_version'], f"{view['source_generation']}:{view['match']}:{view['game']}:{req['id']}",
                action, source, target, min(deadline, req['received_at'] + 3),
                req['opportunity_id'], cost, effect)
