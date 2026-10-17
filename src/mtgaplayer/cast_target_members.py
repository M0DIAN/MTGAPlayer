"""Finite same-request Blue1 Cast member probes; never final target sets.

No response or successor is an input. Missing source catalog/ability metadata
and proto3 tap literals remain unknown, rather than reconstructed from offers.
"""
import copy
import json

from .semantic_samples import _need, _keys
from .action_target_menus import CURRENT_PROFILE, CURRENT_VERSION, check_current
from .decision_consumer import EXECUTION

PROFILE = 'current_blue_one_cast_target_member'
REQUEST_VERSION = 'mtgaplayer.request-parameters.v7'
VERSION = 'mtgaplayer.known-choice-candidates.v5'
SCOPE = 'same_current_blue_one_cast_member_and_predictive_route'
GOOD = 'verified_known_constraints'
UNKNOWN = 'insufficient_evidence'
BAD = 'violated_known_constraints'
DENIALS = dict.fromkeys(('all_payment_options_verified', 'complete_costs_verified',
    'complete_payment_verified', 'target_quantity_verified', 'target_domain_complete_verified',
    'target_selection_legality_verified', 'global_target_legality_verified',
    'full_action_domain_complete', 'overall_payability_verified', 'payment_source_untapped_verified',
    'source_catalog_and_unique_ability_pair_verified', 'historical_response_used',
    'raw_source_reauthenticated', 'rules_effect_verified'), False)


def _equal(a, b):
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def inventory(value):
    return {'schema_version': CURRENT_VERSION, 'profile': CURRENT_PROFILE,
        **{k: value[k] for k in ('binding', 'rows', 'public_battlefield_refs', 'historical_response_used')}}


def _literal(raw, kind, *, target_projector=None):
    from .semantic_targets import action
    from .request_parameters import LiteralRefs
    cast = kind == 'ActionType_Cast'
    ids = {'instanceId', 'grpId', 'facetId'} | (set() if cast else {'abilityGrpId', 'uniqueAbilityId'})
    flags = {'shouldStop'} if cast else {'isBatchable'}
    params = {'manaCost', 'autoTapSolution', 'targets'} if cast else {'manaPaymentOptions', 'manaSelections'}
    _need(set(raw) == {'actionType', *ids, *flags, *params} and raw['actionType'] == kind)
    if target_projector is None:
        literal = action(raw, LiteralRefs(), ())
    else:
        from .semantic_cast import action as cast_action
        literal = cast_action(raw, LiteralRefs(), (), target_projector=target_projector)
    _need(literal['observed_empty_parameters'] == [] and set(literal['parameters']) == params and
        all(type(i) is int and i > 0 for i in literal['identifier_refs'].values()))
    pending = [literal['parameters']]
    while pending:
        item = pending.pop()
        if type(item) is list: pending.extend(item)
        elif type(item) is dict:
            for key, child in item.items():
                if key in ('targetIdx', 'targetInstanceId', 'manaId', 'instanceId', 'srcInstanceId', 'abilityGrpId'):
                    _need(type(child) is int and child > 0)
                pending.append(child)
    if cast:
        slots = literal['parameters']['targets']
        _need(len(slots) == 1 and len(slots[0]['targets']) <= 64)
        refs = [t['targetInstanceId'] for t in slots[0]['targets']]
        _need(len(refs) == len(set(refs)))
    return literal


def project(message, visible, seat, public, hand, mana_sources):
    """Inside the single reducer's accepted owner/digest/continuity path only."""
    from .semantic_activate import _base
    from .raw_log import _frontier_row
    from .request_parameters import LiteralRefs
    _need(set(message) == {'type', 'systemSeatIds', 'msgId', 'gameStateId', 'actionsAvailableReq'} and
        message['type'] == 'GREMessageType_ActionsAvailableReq')
    return _project_members(message, visible, seat, public, hand, mana_sources)


def _project_members(message, visible, seat, public, hand, mana_sources, *, literal_parser=_literal):
    """Shared finite body projection; callers must authenticate their full envelope."""
    from .semantic_activate import _base
    from .raw_log import _frontier_row
    from .request_parameters import LiteralRefs
    body = message['actionsAvailableReq']
    _need(type(body) is dict and not set(body)-{'actions', 'inactiveActions'})
    actions = body['actions']
    _need(type(actions) is list and len(actions) <= 256 and any(type(r) is dict and
        r.get('actionType') == 'ActionType_Cast' and r.get('targets') for r in actions))
    objects = {o['instance_id']: o for o in visible}
    _need(len(objects) == len(visible))
    rows = []; casts = []; mana = []
    for i, raw in enumerate(actions):
        base = _base(raw, LiteralRefs(), ())
        source = base['identifier_refs'].get('instanceId')
        _need(source is None or source in objects)
        shape = _frontier_row(i, base['action_type'], raw)
        rows.append({'list_position': i, **base, 'parameter_shapes': shape['known_parameter_shapes'],
            'other_fields_present': shape['other_top_level_fields_present'],
            'target_menu': None, 'ability_binding': None})
        try:
            kind = base['action_type']
            if kind not in ('ActionType_Cast', 'ActionType_Activate_Mana'): continue
            literal = literal_parser(raw, kind)
            if kind == 'ActionType_Cast':
                _need(source in hand and objects[source]['card_id'] == raw['grpId'])
                targets = literal['parameters']['targets'][0]['targets']
                _need(targets and all(t['targetInstanceId'] in public for t in targets))
                casts.append({'list_position': i, 'action': literal})
            else:
                _need(source in mana_sources)
                mana.append({'list_position': i, 'action': literal})
        except (ValueError, KeyError, TypeError):
            continue
    return {'profile': PROFILE, 'rows': rows, 'public_battlefield_refs': public,
        'cast_source_refs': hand, 'mana_source_refs': mana_sources,
        'cast_actions': casts, 'mana_actions': mana}


def check(value, binding, visible, *, literal_parser=_literal, profile=PROFILE, version=REQUEST_VERSION):
    from .decision_consumer import _integer
    from .semantic_activate import raw_action
    from .raw_log import _frontier_row
    _keys(value, ('schema_version', 'profile', 'binding', 'rows', 'public_battlefield_refs',
        'cast_source_refs', 'mana_source_refs', 'cast_actions', 'mana_actions', 'historical_response_used'))
    _need(value['schema_version'] == version and value['profile'] == profile)
    check_current(inventory(value), binding, visible)
    objects = {o['instance_id']: o for o in visible}; seat = binding['self_seat']
    for field, zone in (('cast_source_refs', 'ZoneType_Hand'), ('mana_source_refs', 'ZoneType_Battlefield')):
        refs = value[field]
        _need(type(refs) is list and len(refs) <= 512 and len(refs) == len(set(refs)))
        for ref in refs:
            _integer(ref, 1); obj = objects.get(ref)
            _need(obj is not None and obj['zone'] == zone and type(obj['owner_seat']) is int and
                obj['owner_seat'] == seat and type(obj['controller_seat']) is int and obj['controller_seat'] == seat)
            if field == 'mana_source_refs': _need(ref in value['public_battlefield_refs'])
    _need(all(r['target_menu'] is None and r['ability_binding'] is None for r in value['rows']))
    for field, kind in (('cast_actions', 'ActionType_Cast'), ('mana_actions', 'ActionType_Activate_Mana')):
        records = value[field]; _need(type(records) is list and len(records) <= 256)
        seen = set()
        for record in records:
            _keys(record, ('list_position', 'action'))
            pos = record['list_position']; _integer(pos, 0, len(value['rows'])-1)
            _need(pos not in seen); seen.add(pos)
            action = record['action']; raw = raw_action(action); _need(_equal(literal_parser(raw, kind), action))
            row = value['rows'][pos]
            _need(row['action_type'] == kind and _equal(row['identifier_refs'], action['identifier_refs']) and
                _equal(row['flags'], action['flags']) and row['other_fields_present'] is False and
                _equal(_frontier_row(pos, kind, raw)['known_parameter_shapes'], row['parameter_shapes']))
            source = action['identifier_refs']['instanceId']
            _need(source in value['cast_source_refs' if field == 'cast_actions' else 'mana_source_refs'])
            if field == 'cast_actions':
                _need(objects[source]['card_id'] == action['identifier_refs']['grpId'])
                refs = [t['targetInstanceId'] for t in action['parameters']['targets'][0]['targets']]
                _need(refs and len(refs) == len(set(refs)) and all(t in value['public_battlefield_refs'] for t in refs))


def check_space(space, binding, visible):
    """Reuse the full existing inventory/graph check, including opaque rows."""
    from .request_parameters import check_space as check_existing
    value = space['request_parameters']
    check_existing({**space, 'request_parameters': inventory(value)}, binding, visible, allow_targeted_activate=True)
    from .raw_log import _RAW_ID_FIELDS, _RAW_FLAG_FIELDS
    nodes = {n['action_key']['list_position']: n for n in space['choice_graph']['action_nodes']}
    for row in value['rows']:
        if row['list_position'] not in nodes: continue
        node = nodes[row['list_position']]; identity = node['action_identity']
        expected_key = {'request_identity': {'generation': binding['source_generation'],
            **{k: binding[k] for k in ('match', 'game', 'game_state_id', 'self_seat', 'request_id')}},
            'list_position': row['list_position']}
        _need(_equal(node['action_key'], expected_key) and _equal(identity['raw_identifiers'],
            {pub: row['identifier_refs'][raw] for raw, pub in _RAW_ID_FIELDS if raw in row['identifier_refs']}))
        _need(_equal(identity['raw_flags_observed_not_discriminators'],
            {pub: row['flags'][raw] for raw, pub in _RAW_FLAG_FIELDS if raw in row['flags']}))
    for record in value['cast_actions']:
        pos = record['list_position']; slot = record['action']['parameters']['targets'][0]
        constraints = [c for c in nodes[pos]['constraints'] if c['parameter_category'] == 'targets']
        expected = {'container_element_count': 1, 'total': 1, 'examined': 1, 'truncated': False,
            'groups': [{'position': 0, 'target_idx_raw': slot['targetIdx'], 'target_count': len(slot['targets'])}]}
        _need(len(constraints) == 1 and constraints[0]['observed_structure'] == {'kind': 'array'} and
              _equal(constraints[0]['observed_quantity_or_domain'], expected))


def route(value, position, visible):
    """Explicit Blue1 branch; the legacy Generic1 checker is unchanged."""
    return _colored_route(value, position, visible, color='ManaColor_Blue',
        unsupported='only_blue_one_single_predictive_route_reviewed',
        missing_unit='blue_one_predictive_unit_not_observed',
        consistent='same_request_blue_one_route_and_member_consistent')


def _colored_route(value, position, visible, *, color, unsupported, missing_unit, consistent):
    records = {r['list_position']: r['action'] for r in value['cast_actions']}
    action = records.get(position)
    if action is None: return UNKNOWN, 'cast_literal_profile_not_observed', None
    rows = value['rows']; row = rows[position]
    if sum(r['action_type'] == row['action_type'] and _equal(r['identifier_refs'], row['identifier_refs'])
           for r in rows) != 1: return UNKNOWN, 'ambiguous_cast_offer', None
    params = action['parameters']; taps = params['autoTapSolution']['autoTapActions']
    if params['manaCost'] != [{'color': [color], 'count': 1}] or len(taps) != 1:
        return UNKNOWN, unsupported, None
    tap = taps[0]; units = tap['manaPaymentOption']['mana']
    if len(units) != 1 or units[0]['color'] != color or units[0]['count'] != 1:
        return UNKNOWN, missing_unit, None
    unit = units[0]
    if unit['srcInstanceId'] != tap['instanceId'] or unit['abilityGrpId'] != tap['abilityGrpId']:
        return BAD, 'predictive_unit_source_or_group_mismatch', None
    matches = [i for i, r in enumerate(rows) if r['action_type'] == 'ActionType_Activate_Mana' and
        r['identifier_refs']['instanceId'] == tap['instanceId'] and r['identifier_refs']['abilityGrpId'] == tap['abilityGrpId']]
    if len(matches) != 1: return UNKNOWN, 'unique_active_mana_offer_not_observed', None
    pos = matches[0]; mana = next((r['action'] for r in value['mana_actions'] if r['list_position'] == pos), None)
    if mana is None: return UNKNOWN, 'current_public_mana_literal_not_observed', None
    expected = {'instanceId': tap['instanceId'], 'abilityGrpId': tap['abilityGrpId'],
        'options': [{'mana': [{'color': color, 'count': 1}]}]}
    if not _equal(mana['parameters'], {'manaPaymentOptions': [tap['manaPaymentOption']], 'manaSelections': [expected]}):
        return BAD, 'current_mana_option_or_selection_mismatch', None
    source = next(o for o in visible if o['instance_id'] == tap['instanceId'])
    if source['card_id'] is not None and source['card_id'] != mana['identifier_refs']['grpId']:
        return BAD, 'public_mana_catalog_contradiction', None
    if source['tapped'] is True: return UNKNOWN, 'explicitly_tapped_mana_source_withheld', None
    witness = {'list_position': pos, 'identifier_refs': copy.deepcopy(mana['identifier_refs']),
        'flags': copy.deepcopy(mana['flags']), 'predictive_payment': copy.deepcopy(tap),
        'current_tapped_literal': source['tapped']}
    return GOOD, consistent, witness


def check_member(value, member, position, visible, *, route_check=route):
    action = next((r['action'] for r in value['cast_actions'] if r['list_position'] == position), None)
    if action is None: return UNKNOWN, 'cast_literal_profile_not_observed', None
    if not _equal(member['identifier_refs'], action['identifier_refs']) or not _equal(member['flags'], action['flags']):
        return UNKNOWN, 'proposal_binding_invalid', None
    slot = action['parameters']['targets'][0]
    if member['target_idx'] != slot['targetIdx']: return BAD, 'target_slot_differs_from_this_offered_row', None
    if member['object_ref'] not in [t['targetInstanceId'] for t in slot['targets']]:
        return BAD, 'target_not_in_this_explicit_menu', None
    return route_check(value, position, visible)


def unknown(reason, ref=None):
    return {'schema_version': VERSION, 'scope': SCOPE, 'status': UNKNOWN, 'reason': reason,
        'source_snapshot_ref': copy.deepcopy(ref), 'request_binding': None,
        'engine_active_action_rows': None, 'target_bearing_cast_rows': None,
        'reviewed_cast_rows': 0, 'unknown_or_unreviewed_action_rows': None,
        'member_probes': {'observed': 0, 'examined': 0, 'verified': 0, 'unknown': 0, 'contradicted': 0,
            'unexamined': 0, 'returned': 0, 'omitted_due_to_return_limit': 0},
        'candidate_total_for_reviewed_constraints': None, 'returned_candidates': 0, 'truncated': False,
        'exhaustive_for_reviewed_constraints': False, 'candidates': [],
        'target_quantities': {'minimum': None, 'maximum': None, 'selected_count': None},
        'payment_source_readiness': 'unknown_not_evaluated', 'read_only': True, **DENIALS, **EXECUTION}


def enumerate_members(state, *, source_snapshot_ref=None, limit=64, _review=None):
    from .decision_consumer import _state, _bounded_json, _reference
    from .choice_validation import validate_proposed_choice, VERSION as VALIDATION_VERSION
    # A new opt-in family can reuse the complete probe/validator/limit path.
    # The default preserves the v5 values, including reasons and scopes.
    unknown_result = unknown if _review is None else _review.unknown_cast
    profile = PROFILE if _review is None else _review.CAST_PROFILE
    scope = SCOPE if _review is None else _review.CAST_SCOPE
    route_check = route if _review is None else _review.black_route
    if type(limit) is not int or not 1 <= limit <= 64:
        raise ValueError('invalid_known_candidate_limit')
    try:
        _bounded_json(state); _state(state, state['binding']); binding = state['binding']; ref = source_snapshot_ref
        if state['status'] != 'state_and_request_observed' or binding['request_id'] is None:
            return unknown_result('no_verified_current_request')
        if ref is not None:
            _reference(ref, ref['session_id'], ref['sequence'], snapshot=True)
            if ref['binding'] != binding: return unknown_result('snapshot_binding_invalid')
        value = state['legal_action_space']['request_parameters']
        if _review is not None: value = _review.cast_family(value)
        if value is None or value['profile'] != profile: return unknown_result('current_blue_one_cast_profile_not_observed' if _review is None else 'current_black_one_cast_profile_not_observed', ref)
        result = unknown_result('no_verified_cast_members', ref); rows = value['rows']; probes = result['member_probes']
        result.update(request_binding=copy.deepcopy(binding), engine_active_action_rows=len(rows),
            target_bearing_cast_rows=sum(r['action_type'] == 'ActionType_Cast' and
                (r['parameter_shapes'].get('targets', {}).get('element_count') or 0) > 0 for r in rows),
            reviewed_cast_rows=len(value['cast_actions']), unknown_or_unreviewed_action_rows=len(rows)-len(value['cast_actions']))
        nodes = {n['action_key']['list_position']: n for n in state['legal_action_space']['choice_graph']['action_nodes']}
        for record in value['cast_actions']:
            pos = record['list_position']; action = record['action']; slot = action['parameters']['targets'][0]
            for target in slot['targets']:
                probes['observed'] += 1
                if probes['examined'] >= 256:
                    probes['unexamined'] += 1; continue
                proposal = {'request_identity': copy.deepcopy(binding), 'list_position': pos,
                    'proposed_cast_target_member': {'identifier_refs': copy.deepcopy(action['identifier_refs']),
                        'flags': copy.deepcopy(action['flags']), 'target_idx': slot['targetIdx'], 'object_ref': target['targetInstanceId']}}
                if ref is not None: proposal['source_snapshot_ref'] = copy.deepcopy(ref)
                verdict = validate_proposed_choice(state, proposal, source_snapshot_ref=ref)
                expected_keys = {'schema_version', 'validation_scope', 'known_constraints', 'reasons',
                    'source_snapshot_ref', 'read_only', 'payment_witness', 'target_selection_count',
                    'target_minimum', 'target_maximum', 'payment_source_readiness', *DENIALS, *EXECUTION}
                if (type(verdict) is not dict or set(verdict) != expected_keys or
                    verdict.get('schema_version') != VALIDATION_VERSION or verdict.get('validation_scope') != scope or
                    not _equal(verdict.get('source_snapshot_ref'), ref) or
                    verdict.get('read_only') is not True or any(verdict.get(k) is not False for k in (*DENIALS, *EXECUTION)) or
                    verdict.get('target_selection_count') is not None or verdict.get('target_minimum') is not None or
                    verdict.get('target_maximum') is not None or verdict.get('payment_source_readiness') != 'unknown_not_evaluated'):
                    return unknown_result('choice_validator_contract_mismatch')
                if ref is not None:
                    _reference(verdict['source_snapshot_ref'], ref['session_id'], ref['sequence'], snapshot=True)
                current_route = route_check(value, pos, state['visible_objects'])
                if (verdict['known_constraints'] != current_route[0] or verdict['reasons'] != [current_route[1]] or
                        not _equal(verdict['payment_witness'], current_route[2])):
                    return unknown_result('choice_validator_contract_mismatch')
                category = {GOOD: 'verified', UNKNOWN: 'unknown', BAD: 'contradicted'}.get(verdict['known_constraints'])
                if category is None: return unknown_result('choice_validator_contract_mismatch')
                probes['examined'] += 1; probes[category] += 1
                if category == 'verified' and len(result['candidates']) < limit:
                    # Witness is diagnostic context, not a client response proposal.
                    result['candidates'].append({'action_key': copy.deepcopy(nodes[pos]['action_key']),
                        'proposal': proposal, 'payment_witness': copy.deepcopy(verdict['payment_witness'])})
        probes['returned'] = len(result['candidates']); probes['omitted_due_to_return_limit'] = probes['verified']-probes['returned']
        result.update(candidate_total_for_reviewed_constraints=probes['verified'], returned_candidates=probes['returned'],
            truncated=bool(probes['omitted_due_to_return_limit'] or probes['unexamined']),
            exhaustive_for_reviewed_constraints=not (probes['unknown'] or probes['unexamined'] or probes['omitted_due_to_return_limit']))
        if result['candidates']: result.update(status='reviewed_constraint_candidates_observed', reason='current_cast_members_verified')
        _bounded_json(result); return result
    except (ValueError, TypeError, KeyError, IndexError, RecursionError, UnicodeError, OverflowError):
        return unknown_result('state_or_request_evidence_invalid')
