"""Snapshot-bound static reference sidecar; DecisionState v1 stays unchanged."""
from collections import Counter
import copy

from .decision_advisor import _validate_state
from .decision_consumer import DecisionConsumer, EXECUTION
from .rules_index import lookup_rules, PreparedRulesIndex, RulesIndexError

VERSION = 'mtgaplayer.static-rule-context.v1'
CURRENT_VERSION = 'mtgaplayer.current-static-rule-context.v1'
MAX_REFERENCE_BYTES = 1024 * 1024
STATUSES = ('resolved_static_reference', 'not_in_index', 'missing_card_id',
            'ambiguous_catalog_id', 'ambiguous_visible_identity')


def _empty_context():
    return {'schema_version': VERSION, 'status': 'unavailable',
        'scope': 'snapshot_static_reference_only', 'binding': None,
        'rules_source': None, 'objects': [], 'counts': None,
        'unresolved': ['current_state_unavailable'], 'effect_claims': None,
        'legal_actions': None, 'read_only': True, 'execution': dict(EXECUTION)}


def build_static_rule_context(state, index_path, *, max_reference_bytes=None):
    """Associate only validated visible objects, using a path or prepared index.

    This association grants no continuing currentness. A caller must
    discard it when its bound state/request changes. SelectN references and
    hidden objects never supply catalog lookup IDs; names never repair gaps.
    A pre-copy reference budget requires a prepared index.
    """
    result = _empty_context()
    try:
        _validate_state(state)
    except (ValueError, KeyError, TypeError, RecursionError, UnicodeError):
        return result
    result['binding'] = copy.deepcopy(state['binding'])
    visible = state['visible_objects']
    identities = Counter(obj['instance_id'] for obj in visible)
    ids = {obj['card_id'] for obj in visible if obj['card_id'] is not None
           and identities[obj['instance_id']] == 1}
    try:
        if isinstance(index_path, PreparedRulesIndex):
            # Preserve instance multiplicity in the output-budget preflight.
            query = [obj['card_id'] for obj in visible if obj['card_id'] is not None
                     and identities[obj['instance_id']] == 1]
            metadata, found = index_path.lookup(query, max_reference_bytes=max_reference_bytes)
        elif max_reference_bytes is not None:
            result['unresolved'] = ['rules_index_not_prepared']
            return result
        else:
            metadata, found = lookup_rules(index_path, ids)
    except RulesIndexError as exc:
        result['unresolved'] = ['rules_context_limits_exceeded' if
            str(exc) == 'rules_context_limits_exceeded' else 'rules_index_unavailable_or_invalid']
        return result
    result['status'] = 'reference_context_observed'
    result['rules_source'] = {key: metadata[key] for key in ('schema_version',
        'source_format', 'source_version', 'source_sha256', 'source_version_is_user_supplied')}
    counts = dict.fromkeys(STATUSES, 0)
    for position, obj in enumerate(visible):
        reference = None
        if identities[obj['instance_id']] != 1:
            status = 'ambiguous_visible_identity'
        elif obj['card_id'] is None:
            status = 'missing_card_id'
        else:
            match = found[obj['card_id']]
            status = {'resolved': 'resolved_static_reference', 'ambiguous': 'ambiguous_catalog_id',
                      'unresolved': 'not_in_index'}[match['status']]
            reference = match['card']
        result['objects'].append({'object_position': position,
            'instance_id': obj['instance_id'], 'card_id': obj['card_id'],
            'status': status, 'reference': reference, 'current_face': None,
            'association_basis': 'exact_visible_catalog_id_only',
            'effective_in_game': False, 'rules_verified': False})
        counts[status] += 1
    result['counts'] = counts
    result['unresolved'] = ['current_face_unknown', 'dataset_freshness_unverified',
        'dynamic_effects_unknown', 'reference_text_is_not_current_rules_or_legality']
    return copy.deepcopy(result)


def _current_unavailable(status, reason):
    result = _empty_context()
    result.update(schema_version=CURRENT_VERSION, scope='consumer_snapshot_static_reference_only',
        source_snapshot_ref=None, source_phase=None, consumer_status=status, new_live_opportunity=False,
        unresolved=[reason])
    return result


def assess_current_rule_context(consumer, prepared=None, *, rules_error=None):
    """Owner-thread current reference data, with no index I/O or new opportunity.

    History and requestless snapshots can supply static reference only. Expiry
    or any ref change discards all content; no last-valid fallback is used.
    """
    if not isinstance(consumer, DecisionConsumer):
        return _current_unavailable(None, 'requires_current_consumer')
    try:
        view = consumer.current_view()
        status = view['consumer_status']
        if status != 'OBSERVING':
            return _current_unavailable(status, 'consumer_' + status.lower())
        state, ref = view['decision_state'], view['current_snapshot_ref']
        if state is None or ref is None:
            return _current_unavailable(status, 'current_snapshot_not_provided')
        _validate_state(state)
        if (view['read_only'] is not True or any(view[k] is not False for k in EXECUTION) or
                view['transport_alive'] is not True or ref['binding'] != state['binding'] or
                ref['session_id'] != view['session_id'] or
                not 1 <= ref['sequence'] <= view['last_sequence'] or
                state['source']['mode'] != 'watch' or state['source']['phase'] not in ('history', 'append') or
                state['source']['stopped'] is not False):
            return _current_unavailable(status, 'current_snapshot_binding_invalid')
        if rules_error is not None or not isinstance(prepared, PreparedRulesIndex):
            result = _current_unavailable(status, rules_error or 'rules_index_not_prepared')
            result['binding'] = copy.deepcopy(state['binding'])
        else:
            result = build_static_rule_context(state, prepared, max_reference_bytes=MAX_REFERENCE_BYTES)
            result.update(schema_version=CURRENT_VERSION, scope='consumer_snapshot_static_reference_only',
                          consumer_status=status, new_live_opportunity=False)
        result.update(source_snapshot_ref=copy.deepcopy(ref), source_phase=state['source']['phase'])
        final = consumer.current_view()  # Computation may cross a lease boundary.
        if final['consumer_status'] != 'OBSERVING' or final['current_snapshot_ref'] != ref:
            return _current_unavailable(final['consumer_status'], 'current_snapshot_changed')
        return result
    except (ValueError, KeyError, TypeError, RecursionError, UnicodeError):
        return _current_unavailable(None, 'current_view_unavailable')
