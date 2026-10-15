"""Owner-thread visible snapshot endpoint facts, never effects or event history."""
from collections import Counter
import copy
import json

from .decision_advisor import _validate_state
from .decision_consumer import DecisionConsumer, EXECUTION

VERSION = 'mtgaplayer.observed-changes.v1'
MAX_CHANGE_BYTES = 1024 * 1024
_UNKNOWN = ['intermediate_changes_not_enumerated', 'causes_and_effects_unverified',
            'visibility_entry_exit_is_not_creation_or_destruction', 'unknown_fields_not_compared']


def _empty(reason):
    return {'schema_version': VERSION, 'status': 'unavailable',
        'scope': 'published_visible_snapshot_endpoints_only', 'source_snapshot_ref': None,
        'before_snapshot_ref': None, 'after_snapshot_ref': None, 'changes': [], 'counts': None,
        'unresolved': [reason, *_UNKNOWN], 'effect_claims': None, 'new_live_opportunity': False,
        'read_only': True, 'execution': dict(EXECUTION)}


def _compare(before, after):
    """Only values present at both endpoints; no event/cause reconstruction."""
    changes, unresolved = [], []
    old_players, new_players = before['game']['players'], after['game']['players']
    old_counts, new_counts = Counter(p['seat'] for p in old_players), Counter(p['seat'] for p in new_players)
    old_life = {p['seat']: p['life'] for p in old_players if old_counts[p['seat']] == 1}
    new_life = {p['seat']: p['life'] for p in new_players if new_counts[p['seat']] == 1}
    for seat in sorted(old_life.keys() & new_life.keys()):
        old, new = old_life[seat], new_life[seat]
        if old is not None and new is not None and old != new:
            changes.append({'kind': 'life_changed', 'seat': seat, 'before': old, 'after': new})
    if any(n != 1 for n in (*old_counts.values(), *new_counts.values())):
        unresolved.append('ambiguous_player_identity')
    old_objects, new_objects = before['visible_objects'], after['visible_objects']
    old_counts = Counter(o['instance_id'] for o in old_objects)
    new_counts = Counter(o['instance_id'] for o in new_objects)
    old = {o['instance_id']: o for o in old_objects if old_counts[o['instance_id']] == 1}
    new = {o['instance_id']: o for o in new_objects if new_counts[o['instance_id']] == 1}
    if any(n != 1 for n in (*old_counts.values(), *new_counts.values())):
        unresolved.append('ambiguous_visible_instance_identity')
    for ident in sorted(old.keys() - new_counts.keys()):
        changes.append({'kind': 'left_visible_projection', 'instance_id': ident})
    for ident in sorted(new.keys() - old_counts.keys()):
        changes.append({'kind': 'entered_visible_projection', 'instance_id': ident})
    for ident in sorted(old.keys() & new.keys()):
        if old[ident]['card_id'] is None or old[ident]['card_id'] != new[ident]['card_id']:
            unresolved.append('visible_card_identity_changed_or_unknown')
            continue
        for field in ('zone', 'tapped', 'controller_seat'):
            a, b = old[ident][field], new[ident][field]
            if a is not None and b is not None and a != b:
                changes.append({'kind': field + '_changed', 'instance_id': ident,
                    'card_id': new[ident]['card_id'], 'before': a, 'after': b})
    return changes, sorted(set(unresolved))


class ObservedChanges:
    """One bounded comparison baseline adjunct to ONE existing Consumer.

    Only the adapter owner supplies scalar metadata from an accepted event.
    Consumer remains the lifecycle authority. A state_advanced invalidation can
    retain the prior endpoint only until the immediately following snapshot;
    any intervening tick/liveness clears it. No independent clock or thread.
    """
    def __init__(self, consumer):
        if not isinstance(consumer, DecisionConsumer):
            raise ValueError('requires_current_consumer')
        self.consumer = consumer
        self.clear('comparison_baseline_unavailable')

    def clear(self, reason):
        self._baseline, self._awaiting = None, False
        self._result = _empty(reason)

    def observe(self, event=None):
        try:
            view = self.consumer.current_view()
            kind, reason = event or (None, None)
            if (view['consumer_status'] == 'INVALIDATED' and kind == 'invalidate' and
                    reason == 'state_advanced' and self._baseline is not None):
                self._awaiting = True
                self._result = _empty('awaiting_advanced_snapshot')
                return copy.deepcopy(self._result)
            state, ref = view['decision_state'], view['current_snapshot_ref']
            if view['consumer_status'] != 'OBSERVING' or state is None or ref is None:
                self.clear('current_snapshot_unavailable')
                return copy.deepcopy(self._result)
            _validate_state(state)
            if (view['transport_alive'] is not True or view['read_only'] is not True or
                    any(view[k] is not False for k in EXECUTION) or ref['binding'] != state['binding'] or
                    ref['session_id'] != view['session_id'] or not 1 <= ref['sequence'] <= view['last_sequence'] or
                    state['source']['mode'] != 'watch' or state['source']['stopped'] is not False or
                    state['source']['phase'] not in ('history', 'append')):
                self.clear('current_snapshot_binding_invalid')
                return copy.deepcopy(self._result)
            if self._baseline is None or self._baseline['ref'] != ref:
                previous = self._baseline
                result = _empty('previous_comparable_snapshot_unavailable')
                result.update(status='baseline_observed', source_snapshot_ref=copy.deepcopy(ref),
                              after_snapshot_ref=copy.deepcopy(ref))
                if previous is not None and self._awaiting and kind == 'snapshot' and state['source']['phase'] == 'append':
                    old = previous['state']
                    comparable = (old['schema_version'] == state['schema_version'] and
                        previous['ref']['session_id'] == ref['session_id'] and previous['ref']['sequence'] < ref['sequence'] and
                        old['binding']['game_state_id'] < state['binding']['game_state_id'] and
                        all(old['binding'][k] == state['binding'][k] for k in
                            ('source_generation', 'match', 'game', 'self_seat')))
                    if comparable:
                        rows, unknown = _compare(old, state)
                        if len(json.dumps(rows, ensure_ascii=False, allow_nan=False).encode('utf-8')) > MAX_CHANGE_BYTES:
                            result['status'], result['unresolved'] = 'unavailable', ['observed_changes_limits_exceeded', *_UNKNOWN]
                        else:
                            result.update(status='endpoints_compared', before_snapshot_ref=copy.deepcopy(previous['ref']),
                                changes=rows, counts=dict(Counter(row['kind'] for row in rows)),
                                unresolved=[*unknown, *_UNKNOWN])
                self._baseline = {'ref': copy.deepcopy(ref), 'state': state}
                self._awaiting, self._result = False, result
            final = self.consumer.current_view()
            if final['consumer_status'] != 'OBSERVING' or final['current_snapshot_ref'] != ref:
                self.clear('current_snapshot_changed')
            return copy.deepcopy(self._result)
        except (ValueError, KeyError, TypeError, RecursionError, UnicodeError):
            self.clear('current_view_unavailable')
            return copy.deepcopy(self._result)
