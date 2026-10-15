"""Snapshot-bound static reference sidecar; DecisionState v1 stays unchanged."""
from collections import Counter
import copy

from .decision_advisor import _validate_state
from .decision_consumer import EXECUTION
from .rules_index import lookup_rules, RulesIndexError

VERSION = 'mtgaplayer.static-rule-context.v1'
STATUSES = ('resolved_static_reference', 'not_in_index', 'missing_card_id',
            'ambiguous_catalog_id', 'ambiguous_visible_identity')


def build_static_rule_context(state, index_path):
    """Associate only the validated snapshot's visible objects, by exact ID.

    This association grants no continuing currentness. A caller must
    discard it when its bound state/request changes. SelectN references and
    hidden objects never supply catalog lookup IDs; names never repair gaps.
    """
    result = {'schema_version': VERSION, 'status': 'unavailable',
        'scope': 'snapshot_static_reference_only', 'binding': None,
        'rules_source': None, 'objects': [], 'counts': None,
        'unresolved': ['current_state_unavailable'], 'effect_claims': None,
        'legal_actions': None, 'read_only': True, 'execution': dict(EXECUTION)}
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
        metadata, found = lookup_rules(index_path, ids)
    except RulesIndexError:
        result['unresolved'] = ['rules_index_unavailable_or_invalid']
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
