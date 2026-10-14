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


# Phase 2 is a separate opt-in contract; the Phase 1 classifier/report above
# intentionally remain unchanged. These identities were observed in the local
# value-free, exact-envelope probe. They identify offered rows, not legal plans.
_COMPLEX_TYPES = frozenset({
    'ActionType_Cast', 'ActionType_Activate', 'ActionType_Activate_Mana'})
_IDENTIFIERS = {
    'instanceId': 'instance_id', 'grpId': 'grp_id', 'facetId': 'facet_id',
    'abilityGrpId': 'ability_grp_id', 'uniqueAbilityId': 'unique_ability_id',
}
_FLAGS = {'shouldStop': 'should_stop', 'isBatchable': 'is_batchable',
          'isManaAbilityWithSideEffect': 'is_mana_ability_with_side_effect'}
_PARAMETERS = frozenset({
    'targets', 'manaCost', 'manaSelections', 'manaPaymentOptions',
    'autoTapSolution'})
_FIXED_TYPES = tuple(sorted(_TYPES)) + ('incomplete_or_unknown_type',)


def _parameter_structure(action):
    """Observe only top-level containers; parameter contents remain opaque."""
    truncated = invalid = False
    for key in _PARAMETERS & action.keys():
        value = action[key]
        expected = dict if key == 'autoTapSolution' else list
        if not isinstance(value, expected):
            invalid = True
        else:
            truncated |= len(value) > (32 if expected is dict else 64)
    return truncated, invalid


def _candidate_parameter_bounds(candidate, frontier):
    """Validate existing projection metadata, never read nested GRE parameters."""
    params = candidate.get('opaque_parameter_shapes')
    if (not isinstance(params, dict) or set(params) - _PARAMETERS or
            params != frontier.get('known_parameter_shapes')):
        return False, False
    relations = candidate.get('raw_relations')
    if not isinstance(relations, dict):
        return False, False
    truncated = False
    for name, shape in params.items():
        if not isinstance(shape, dict):
            return False, truncated
        count = shape.get('auto_tap_actions_count' if name == 'autoTapSolution' else 'element_count')
        if (shape.get('kind') != ('object' if name == 'autoTapSolution' else 'array') or
                type(count) is not int or count < 0):
            return False, truncated
        truncated |= count > 64
    for name, relation_name in (('autoTapSolution', 'auto_tap_mana_links'),
                                ('manaSelections', 'mana_selection_links'),
                                ('targets', 'target_slots')):
        if relation_name not in relations:
            return False, truncated
        relation = relations[relation_name]
        if name not in params:
            if relation is not None:
                return False, truncated
            continue
        if not isinstance(relation, dict):
            return False, truncated
        total, examined, entries = relation.get('total'), relation.get('examined'), relation.get('entries')
        if (relation.get('valid_array') is not True or type(total) is not int or
                total < 0 or type(examined) is not int or
                examined != min(total, 64) or not isinstance(entries, list) or
                len(entries) != examined or type(relation.get('truncated')) is not bool or
                relation['truncated'] != (total > 64)):
            return False, truncated
        expected = params[name].get('auto_tap_actions_count' if name == 'autoTapSolution' else 'element_count')
        if total != expected:
            return False, truncated
        truncated |= relation['truncated']
    return True, truncated


def _complex_classify(request, response):
    """Four-way identity correlation, failing closed on incomplete candidates."""
    kind, outcome = 'incomplete_or_unknown_type', 'incomplete_or_unsupported'
    truncated = unknown = False
    present = set()
    body = response.get('performActionResp') if isinstance(response, dict) else None
    actions = body.get('actions') if isinstance(body, dict) else None
    if not isinstance(actions, list) or len(actions) != 1 or not isinstance(actions[0], dict):
        return kind, outcome, isinstance(actions, list) and len(actions) > 64, unknown, present
    action = actions[0]
    typ = action.get('actionType')
    if type(typ) is str and typ in _TYPES:
        kind = typ
    present = _PARAMETERS & action.keys()
    truncated, invalid = _parameter_structure(action)
    truncated |= len(action) > 24
    if kind == 'incomplete_or_unknown_type':
        return kind, outcome, truncated, True, present
    allowed = {'actionType'} | set(_IDENTIFIERS) | set(_FLAGS) | _PARAMETERS
    unknown |= bool(set(action) - allowed)
    if kind in ('ActionType_Pass', 'ActionType_Play'):
        # Preserve the Phase 1 decision exactly, including unrelated complex
        # rows and opaque wrapper siblings. Its strict flat schema owns these.
        typ, result = _classify(request, response)
        return typ, result, truncated, unknown, present
    inventory = request.get('action_inventory') if isinstance(request, dict) else None
    if not isinstance(inventory, dict):
        return kind, outcome, truncated, unknown, present
    unknown |= inventory.get('other_payload_fields_present') is True
    offered = inventory.get('offered_count')
    rows = inventory.get('_frontier_rows')
    types = inventory.get('types')
    if (type(offered) is not int or not 0 <= offered <= 256 or
            inventory.get('type_labels_complete') is not True or
            inventory.get('inactive_excluded') is not True or
            inventory.get('other_payload_fields_present') is not False or
            not isinstance(rows, list) or len(rows) != offered or
            not isinstance(types, list)):
        return kind, outcome, truncated or (type(offered) is int and offered > 256), unknown, present
    counts = Counter()
    for position, row in enumerate(rows):
        if (not isinstance(row, dict) or type(row.get('list_position')) is not int or
                row['list_position'] != position or type(row.get('action_type')) is not str or
                row['action_type'] not in _TYPES or
                type(row.get('structurally_interpreted')) is not bool or
                type(row.get('other_top_level_fields_present')) is not bool):
            return kind, outcome, truncated, unknown, present
        counts[row['action_type']] += 1
    listed = {}
    for item in types:
        if (not isinstance(item, dict) or type(item.get('action_type')) is not str or
                item['action_type'] not in _TYPES or
                item['action_type'] in listed or type(item.get('count')) is not int or
                not 0 <= item['count'] <= offered):
            return kind, outcome, truncated, unknown, present
        listed[item['action_type']] = item['count']
    if counts != listed:
        return kind, outcome, truncated, unknown, present
    if kind not in _COMPLEX_TYPES:
        return kind, outcome, truncated, unknown, present
    required = set(_ID_FIELDS)
    if kind != 'ActionType_Cast':
        required |= {'abilityGrpId', 'uniqueAbilityId'}
    # All present identifiers must agree in presence and value. Boolean flags
    # have only observed storage semantics; never use them to disambiguate IDs.
    identity_fields = set(action) & _IDENTIFIERS.keys()
    flag_fields = set(action) & _FLAGS.keys()
    invalid |= not required <= identity_fields
    invalid |= any(not _valid_id(action[f]) for f in identity_fields)
    invalid |= any(type(action[f]) is not bool for f in flag_fields)
    candidates = inventory.get('complex_raw_shapes')
    if not isinstance(candidates, list) or len(candidates) > 256:
        return kind, outcome, truncated or isinstance(candidates, list), unknown, present
    seen, matches, same_type = set(), 0, 0
    for candidate in candidates:
        if not isinstance(candidate, dict):
            return kind, outcome, truncated, unknown, present
        position = candidate.get('list_position')
        if (type(position) is not int or not 0 <= position < offered or position in seen or
                type(candidate.get('action_type')) is not str or
                candidate['action_type'] not in _COMPLEX_TYPES or
                rows[position]['action_type'] != candidate['action_type']):
            return kind, outcome, truncated, unknown, present
        seen.add(position)
        if candidate['action_type'] != kind:
            continue
        same_type += 1
        unknown |= candidate.get('other_top_level_fields_present') is not False
        unknown |= rows[position]['other_top_level_fields_present']
        ids, flags = candidate.get('raw_identifiers'), candidate.get('raw_flags')
        parameters_complete, parameters_truncated = _candidate_parameter_bounds(candidate, rows[position])
        invalid |= not parameters_complete
        truncated |= parameters_truncated
        if (rows[position]['structurally_interpreted'] is not True or
                candidate.get('invalid_known_field_types') != [] or
                not isinstance(ids, dict) or not isinstance(flags, dict)):
            invalid = True
            continue
        if (set(ids) != {_IDENTIFIERS[f] for f in identity_fields} or
                set(flags) != {_FLAGS[f] for f in flag_fields} or
                any(not _valid_id(value) for value in ids.values()) or
                any(type(value) is not bool for value in flags.values())):
            invalid = True
            continue
        if all(ids[_IDENTIFIERS[f]] == action[f] for f in identity_fields):
            matches += 1
    if same_type != counts[kind] or invalid or truncated or unknown:
        return kind, outcome, truncated, unknown, present
    return kind, ('unique' if matches == 1 else 'multiple' if matches > 1 else 'no_match'), truncated, unknown, present


class ComplexSemanticChoiceCounter:
    """Value-free Phase 2 aggregates, called only behind the MP15 exact gate."""

    def __init__(self):
        self.responses = 0
        self.counts = {typ: Counter() for typ in _FIXED_TYPES}
        self.parameters = Counter()
        self.parameter_kinds = Counter()
        self.flag_kinds = Counter()

    def add(self, verified_request, matched_client_response):
        typ, result, truncated, unknown, present = _complex_classify(
            verified_request, matched_client_response)
        body = matched_client_response.get('performActionResp') if isinstance(matched_client_response, dict) else None
        unknown |= isinstance(body, dict) and bool(set(body) - {'actions'})
        # Any observed parameter contents remain unknown at this identity-only
        # layer, even when their top-level storage shape is supported.
        unknown |= bool(present)
        self.responses += 1
        counts = self.counts[typ]
        counts['matched_response_count'] += 1
        counts[result + '_count'] += 1
        counts['truncated_count'] += int(truncated)
        counts['unknown_parameter_count'] += int(unknown)
        self.parameters.update(present)
        actions = body.get('actions') if isinstance(body, dict) else None
        if isinstance(actions, list) and len(actions) == 1 and isinstance(actions[0], dict):
            for name in present:
                value = actions[0][name]
                kind = ('array' if isinstance(value, list) else
                        'object' if isinstance(value, dict) else 'unexpected')
                self.parameter_kinds[(name, kind)] += 1
            for name in _FLAGS.keys() & actions[0].keys():
                kind = 'bool' if type(actions[0][name]) is bool else 'unexpected'
                self.flag_kinds[(name, kind)] += 1

    def report(self):
        fields = ('matched_response_count',) + tuple(r + '_count' for r in _RESULT_KINDS) + (
            'truncated_count', 'unknown_parameter_count')
        results = [{'action_type': typ, **{key: self.counts[typ][key] for key in fields}}
                   for typ in _FIXED_TYPES]
        return {
            'scope': 'matched_own_actions_available_perform_action_resp_only',
            'matched_action_responses_classified': self.responses,
            'selected_action_identity': {
                'meaning': 'same_request_active_candidate_identity_equality_only',
                'results_by_action_type': results,
                'counts_account_for_all_matched_action_responses': (
                    sum(r['matched_response_count'] for r in results) == self.responses and
                    all(sum(r[k + '_count'] for k in _RESULT_KINDS) ==
                        r['matched_response_count'] for r in results))},
            'response_parameter_evidence': {
                'meaning': 'field_presence_and_bounded_storage_only',
                'unknown_parameter_count_meaning': 'responses_with_opaque_parameters_or_unknown_fields',
                'observed_fields': [{'field': name, 'response_count': self.parameters[name]}
                                    for name in sorted(_PARAMETERS)],
                'container_kind_counts': [
                    {'field': name, 'kind': kind,
                     'response_count': self.parameter_kinds[(name, kind)]}
                    for name in sorted(_PARAMETERS)
                    for kind in ('array', 'object', 'unexpected')],
                'boolean_flag_kind_counts': [
                    {'field': name, 'kind': kind,
                     'response_count': self.flag_kinds[(name, kind)]}
                    for name in sorted(_FLAGS) for kind in ('bool', 'unexpected')],
                'future_choice_requests_inferred': False},
            'legal_parameter_verification': {
                'status': 'unverified', 'targets_verified': False,
                'costs_verified': False, 'modes_verified': False,
                'mana_payment_verified': False},
            'historical_client_submission_only': True,
            'response_encoding_verified': False, 'legal_choice_verified': False,
            'execution_ready': False, 'gameplay_effect_verified': False,
            'legal_actions': None, 'read_only': True,
            'actionable': False, 'input_sent': False,
        }
