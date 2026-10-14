"""MP16: read-only correlation of historic PerformActionResp with offered Pass/Play.

Caller MUST first validate authenticated own current request, exact ID/state,
compatible type, and reducer-recorded client submission. This module never
exposes action IDs, cards, names, response payloads or server-success claims.
"""
from collections import Counter


# Raw type strings are *read* locally, but only fixed types are ever reported.
_TYPES = frozenset({
    'ActionType_Pass', 'ActionType_Play', 'ActionType_Cast',
    'ActionType_Activate', 'ActionType_Activate_Mana',
    'ActionType_FloatMana',
})
_RESULT_KINDS = ('unique', 'multiple', 'no_match', 'incomplete_or_unsupported')
_FIELDS = frozenset({'actionType', 'instanceId', 'grpId', 'facetId', 'shouldStop'})
_ID_FIELDS = ('instanceId', 'grpId', 'facetId')


def _valid_id(value):
    return type(value) is int and 0 <= value <= 2**53 - 1


def _classify(request, response):
    """Return (fixed response action category, same-request correlation outcome).

    Matching is strictly syntactic: even unique does not imply legality,
    complete response encoding, or that the engine accepted the action.
    """
    body = response.get('performActionResp') if isinstance(response, dict) else None
    actions = body.get('actions') if isinstance(body, dict) else None
    if not isinstance(actions, list) or len(actions) != 1 or not isinstance(actions[0], dict):
        return 'incomplete_or_unknown_type', 'incomplete_or_unsupported'
    action = actions[0]
    typ = action.get('actionType')
    if type(typ) is not str or typ not in _TYPES:
        return 'incomplete_or_unknown_type', 'incomplete_or_unsupported'
    if typ not in ('ActionType_Pass', 'ActionType_Play'):
        return typ, 'incomplete_or_unsupported'
    expected = {'actionType'} if typ == 'ActionType_Pass' else _FIELDS
    if set(action) != expected or (typ == 'ActionType_Play' and (
            not all(_valid_id(action.get(f)) for f in _ID_FIELDS) or
            type(action.get('shouldStop')) is not bool)):
        return typ, 'incomplete_or_unsupported'
    inventory = request.get('action_inventory') if isinstance(request, dict) else None
    if (not isinstance(inventory, dict) or
            type(inventory.get('offered_count')) is not int or
            not 0 <= inventory['offered_count'] <= 256 or
            not isinstance(inventory.get('simple_shapes'), list) or
            not isinstance(inventory.get('types'), list)):
        return typ, 'incomplete_or_unsupported'
    offered = inventory['offered_count']
    described_types = {}
    for entry in inventory['types']:
        if (not isinstance(entry, dict) or
                type(entry.get('action_type')) is not str or
                type(entry.get('count')) is not int or
                not 0 <= entry['count'] <= offered or
                entry['action_type'] in described_types):
            return typ, 'incomplete_or_unsupported'
        described_types[entry['action_type']] = entry['count']
    if sum(described_types.values()) != offered:
        return typ, 'incomplete_or_unsupported'
    matches = []
    seen = set()
    for row in inventory['simple_shapes']:
        if not isinstance(row, dict):
            return typ, 'incomplete_or_unsupported'
        position = row.get('list_position')
        if type(position) is not int or not 0 <= position < offered or position in seen:
            return typ, 'incomplete_or_unsupported'
        seen.add(position)
        if row.get('action_type') != typ:
            continue
        if typ == 'ActionType_Pass':
            if set(row) != {'list_position', 'action_type'}:
                return typ, 'incomplete_or_unsupported'
            matches.append(position)
            continue
        # Existing request schema is already reviewed MP7 simple Play.
        if (set(row) != {'list_position', 'action_type', 'instance_id',
                         'grp_id', 'facet_id', 'should_stop_raw'} or
                not all(_valid_id(row.get(field)) for field in
                        ('instance_id', 'grp_id', 'facet_id')) or
                type(row.get('should_stop_raw')) is not bool):
            return typ, 'incomplete_or_unsupported'
        if (row['instance_id'] == action['instanceId'] and
                row['grp_id'] == action['grpId'] and
                row['facet_id'] == action['facetId'] and
                row['should_stop_raw'] is action['shouldStop']):
            matches.append(position)
    # Absence of a *described* row is not evidence that no matching raw
    # action was offered; incomplete same-type source coverage is unknown.
    if sum(row.get('action_type') == typ for row in inventory['simple_shapes']) != (
            described_types.get(typ, 0)):
        return typ, 'incomplete_or_unsupported'
    if len(matches) == 1:
        return typ, 'unique'
    if len(matches) > 1:
        return typ, 'multiple'
    return typ, 'no_match'


class SemanticChoiceCounter:
    """Aggregate only matches already validated by the MP15 envelope gate."""

    def __init__(self):
        self.responses = 0
        self.result_counts = Counter()
        self.type_counts = Counter()

    def add(self, verified_request, matched_client_response):
        # This method is intentionally never called on unmatched responses.
        kind, result = _classify(verified_request, matched_client_response)
        self.responses += 1
        self.type_counts[kind] += 1
        self.result_counts[result] += 1

    def report(self):
        return {
            'scope': 'matched_own_actions_available_perform_action_resp_only',
            'matched_action_responses_classified': self.responses,
            'correlation_results': [
                {'status': result, 'count': self.result_counts[result]}
                for result in _RESULT_KINDS],
            'observed_response_action_types': [
                {'type': kind, 'count': self.type_counts[kind]}
                for kind in sorted(self.type_counts)],
            'counts_account_for_all_matched_action_responses': (
                sum(self.result_counts.values()) == self.responses),
            'unique_is_request_candidate_equality_only': True,
            'historical_client_submission_only': True,
            'complete_response_encoding_verified': False,
            'gameplay_effect_verified': False,
            'legal_actions': None,
            'read_only': True, 'actionable': False, 'input_sent': False,
        }
