"""Same-request offered target/predictive-payment association, never payability."""
import copy

from .action_target_menus import (CURRENT_PROFILE, CURRENT_VERSION, CURRENT_SCOPE,
    project_current, check_current, reviewed_row)
from .semantic_activate import ability_observation, ABILITY, check_generic_two_route
from .semantic_samples import _need, _keys, IDS, BOOLS
from .decision_consumer import EXECUTION

PROFILE = 'current_target_generic_two_predictive_association'
REQUEST_VERSION = 'mtgaplayer.request-parameters.v6'
VERSION = 'mtgaplayer.activate-target-payment-relation.v1'
CONSISTENT = 'offered_target_and_predictive_payment_relation_consistent'
SCOPE = 'same_current_offered_target_and_predictive_payment_association_only'


def target_evidence(value):
    """View of the same current rows for the existing member/graph checks."""
    return {'schema_version': CURRENT_VERSION, 'profile': CURRENT_PROFILE,
        **{key: value[key] for key in ('binding', 'rows', 'public_battlefield_refs', 'historical_response_used')}}


def _own_public(ident, visible, public, seat):
    matches = [o for o in visible if o['instance_id'] == ident]
    return (ident in public and len(matches) == 1 and matches[0]['zone'] == 'ZoneType_Battlefield' and
        type(matches[0]['owner_seat']) is int and matches[0]['owner_seat'] == seat and
        type(matches[0]['controller_seat']) is int and matches[0]['controller_seat'] == seat)


def project(message, visible, seat, source_abilities, public):
    """Only called inside the existing authenticated RawReducer request path."""
    from .request_parameters import LiteralRefs, _visible_references
    from .semantic_targets import action as target_action
    from .semantic_activate import action as mana_action
    base = project_current(message, visible, seat, source_abilities, public)
    actions = message['actionsAvailableReq']['actions']; targets = []; payments = []
    public_objects = {o['instance_id']: {'zone': o['zone'], 'controller': o['controller_seat'],
        'card_id': o['card_id']} for o in visible if o['instance_id'] in public}
    for position, raw in enumerate(actions):
        menu = reviewed_row(raw, position, public_objects, seat, allow_highlight=True)
        if menu is None or menu['offered_visible_target_count'] != 1:
            continue
        try:
            _need(_own_public(raw['instanceId'], visible, public, seat) and
                _own_public(menu['offered_visible_target_refs'][0], visible, public, seat))
            normalized = copy.deepcopy(raw)
            # The existing menu check has validated every target/slot and the
            # optional string presentation field. Retain targets themselves.
            for entry in normalized['targets'][0]['targets']:
                entry.pop('highlight', None)
            literal = target_action(normalized, LiteralRefs(), ())
            _need(set(literal['parameters']) == {'manaCost', 'autoTapSolution', 'targets'} and
                literal['observed_empty_parameters'] == [] and _visible_references(literal, visible))
            taps = literal['parameters']['autoTapSolution']['autoTapActions']
            _need(len(taps) == 2)
            targets.append({'list_position': position, 'action': literal})
        except (ValueError, KeyError, TypeError):
            continue
    referenced = {(p['instanceId'], p['abilityGrpId']) for row in targets
        for p in row['action']['parameters']['autoTapSolution']['autoTapActions']}
    for position, raw in enumerate(actions):
        if (raw['actionType'] != 'ActionType_Activate_Mana' or
                (raw['instanceId'], raw['abilityGrpId']) not in referenced):
            continue
        try:
            _need(set(raw) <= {'actionType', *IDS, *BOOLS, 'manaPaymentOptions', 'manaSelections'} and
                _own_public(raw['instanceId'], visible, public, seat))
            literal = mana_action(raw, LiteralRefs(), ())
            _need(set(literal['parameters']) == {'manaPaymentOptions', 'manaSelections'} and
                literal['observed_empty_parameters'] == [] and _visible_references(literal, visible))
            payments.append({'list_position': position, 'action': literal,
                'ability_binding': ability_observation(raw, source_abilities.get(raw['instanceId']))})
        except (ValueError, KeyError, TypeError):
            continue
    return {**base, 'profile': PROFILE, 'target_actions': targets, 'mana_actions': payments}


def check(value, binding, visible):
    from .decision_consumer import _binding, _integer
    from .semantic_cast import check_action
    from .semantic_activate import check_action as check_mana_action
    _keys(value, ('schema_version', 'profile', 'binding', 'rows', 'public_battlefield_refs',
        'historical_response_used', 'target_actions', 'mana_actions'))
    _binding(value['binding'], complete=True)
    _need(value['schema_version'] == REQUEST_VERSION and value['profile'] == PROFILE)
    check_current(target_evidence(value), binding, visible)
    for field, kind in (('target_actions', 'ActionType_Activate'), ('mana_actions', 'ActionType_Activate_Mana')):
        records = value[field]
        _need(type(records) is list and len(records) <= 256)
        seen = set()
        for record in records:
            _keys(record, ('list_position', 'action', 'ability_binding') if field == 'mana_actions' else ('list_position', 'action'))
            position = record['list_position']; _integer(position, 0, len(value['rows'])-1)
            _need(position not in seen); seen.add(position)
            row = value['rows'][position]; action = record['action']
            (check_mana_action(action) if field == 'mana_actions' else check_action(action, target_actions=True))
            _need(row['action_type'] == action['action_type'] == kind and
                row['identifier_refs'] == action['identifier_refs'] and row['flags'] == action['flags'] and
                all(type(v) is int and v > 0 for v in action['identifier_refs'].values()))
            params = action['parameters']
            _need(action['observed_empty_parameters'] == [])
            if field == 'target_actions':
                _need(set(params) == {'manaCost', 'autoTapSolution', 'targets'} and row['target_menu'] is not None)
                menu = row['target_menu']; slots = params['targets']
                _need(len(slots) == 1 and slots[0]['targetIdx'] == menu['target_idx'] and
                    [r['targetInstanceId'] for r in slots[0]['targets']] == menu['offered_visible_target_refs'] and
                    len(menu['offered_visible_target_refs']) == 1)
            else:
                _need(set(params) == {'manaPaymentOptions', 'manaSelections'} and record['ability_binding'] in ABILITY)
            from .raw_log import _frontier_row
            from .semantic_activate import raw_action
            shapes = _frontier_row(position, kind, raw_action(action))['known_parameter_shapes']
            _need(shapes == row['parameter_shapes'] and row['other_fields_present'] is False)


def unknown(reason, ref=None):
    return {'schema_version': VERSION, 'scope': SCOPE, 'status': 'insufficient_evidence', 'reason': reason,
        'request_binding': None, 'source_snapshot_ref': copy.deepcopy(ref), 'returned_relations': 0,
        'relations': [], 'action_row_coverage': None, 'diagnostics_only': True,
        'payment_source_untapped_verified': False, 'payment_source_readiness': 'unknown_not_evaluated',
        'overall_payability_verified': False, 'complete_costs_verified': False, 'complete_payment_verified': False,
        'full_action_domain_complete': False, 'target_quantity_verified': False, 'target_domain_complete_verified': False,
        'target_selection_legality_verified': False, 'rules_effect_verified': False,
        'historical_response_used': False, 'raw_source_reauthenticated': False, 'read_only': True, **EXECUTION}


def evaluate_relation(state, *, source_snapshot_ref=None):
    """Offline consistency only. Live callers must use assess_current_relation."""
    from .decision_consumer import _bounded_json, _state, _reference
    from .choice_validation import VERSION as VALIDATION_VERSION, validate_proposed_choice
    ref = source_snapshot_ref
    try:
        _bounded_json(state); _state(state, state['binding']); binding = state['binding']
        if state['status'] != 'state_and_request_observed' or binding['request_id'] is None:
            return unknown('no_verified_current_request')
        if ref is not None:
            _reference(ref, ref['session_id'], ref['sequence'], snapshot=True)
            if ref['binding'] != binding:
                return unknown('snapshot_binding_invalid')
        value = state['legal_action_space'].get('request_parameters')
        from .cast_activate_associations import activate_family, PROFILE as FAMILIES_PROFILE, _expected_relations
        combined = type(value) is dict and value.get('profile') == FAMILIES_PROFILE
        value = activate_family(value)
        if value is None or value['profile'] != PROFILE:
            return unknown('joint_current_profile_not_observed', ref)
        result = unknown('no_verified_joint_association', ref); result['request_binding'] = copy.deepcopy(binding)
        rows = value['rows']; visible = state['visible_objects']; public = value['public_battlefield_refs']; seat = binding['self_seat']
        staged = [{**r, 'literal_action': None} for r in rows]
        for record in value['target_actions'] + value['mana_actions']:
            staged[record['list_position']]['literal_action'] = record['action']
        witnesses = {r['list_position']: r for r in value['mana_actions']}
        statuses = ['insufficient_evidence'] * len(rows)
        for record in value['target_actions']:
            position = record['list_position']; action = record['action']; menu = rows[position]['target_menu']
            member = {'identifier_refs': action['identifier_refs'], 'target_idx': menu['target_idx'],
                'object_ref': menu['offered_visible_target_refs'][0]}
            proposal = {'request_identity': binding, 'list_position': position, 'proposed_activate_target_member': member}
            if ref is not None: proposal['source_snapshot_ref'] = ref
            verdict = validate_proposed_choice(state, proposal, source_snapshot_ref=ref)
            if (type(verdict) is not dict or verdict.get('schema_version') != VALIDATION_VERSION or
                    verdict.get('validation_scope') != CURRENT_SCOPE or verdict.get('source_snapshot_ref') != ref or
                    verdict.get('read_only') is not True or any(verdict.get(k) is not False for k in
                    (*EXECUTION, 'all_payment_options_verified', 'complete_costs_verified', 'complete_payment_verified',
                     'target_quantity_verified', 'target_domain_complete_verified', 'target_selection_legality_verified',
                     'global_target_legality_verified', 'historical_response_used')) or any(
                    key in verdict and verdict[key] is not False for key in (
                        'mana_payment_verified', 'rules_effect_verified', 'overall_payability_verified',
                        'payment_source_untapped_verified', 'complete_target_legality_verified',
                        'full_action_domain_complete', 'global_restrictions_verified',
                        'target_quantity_completeness_verified', 'payment_completed_verified'))):
                return unknown('choice_validator_contract_mismatch')
            if ref is not None: _reference(verdict['source_snapshot_ref'], ref['session_id'], ref['sequence'], snapshot=True)
            known = verdict['known_constraints']
            if known != 'verified_known_constraints':
                statuses[position] = known; continue
            if not _own_public(member['object_ref'], visible, public, seat): continue
            checks = dict(verdict['known_checks'])
            status, reason, checks = check_generic_two_route(staged, action, action, visible, seat, checks)
            if status != 'verified_known_constraints':
                statuses[position] = status; continue
            taps = action['parameters']['autoTapSolution']['autoTapActions']; payment_rows = []; valid = True
            for payment in taps:
                unit = payment['manaPaymentOption']['mana'][0]
                matches = [i for i,r in enumerate(rows) if r['action_type'] == 'ActionType_Activate_Mana' and
                    r['identifier_refs']['instanceId'] == payment['instanceId'] and r['identifier_refs']['abilityGrpId'] == payment['abilityGrpId']]
                if len(matches) != 1 or matches[0] not in witnesses: valid = False; break
                witness = witnesses[matches[0]]; mana_action = witness['action']; params = mana_action['parameters']
                expected = {'instanceId': payment['instanceId'], 'abilityGrpId': payment['abilityGrpId'],
                    'options': [{'mana': [{'color': unit['color'], 'count': 1}]}]}
                source = next(o for o in visible if o['instance_id'] == payment['instanceId'])
                if (unit['color'] != 'ManaColor_Blue' or witness['ability_binding'] != 'verified_observed_pair' or
                        params['manaPaymentOptions'] != [payment['manaPaymentOption']] or params['manaSelections'] != [expected] or
                        not _own_public(payment['instanceId'], visible, public, seat) or
                        source['card_id'] is not None and source['card_id'] != mana_action['identifier_refs']['grpId']):
                    valid = False; break
                payment_rows.append({'list_position': matches[0], 'identifier_refs': copy.deepcopy(mana_action['identifier_refs']),
                    'flags': copy.deepcopy(mana_action['flags']), 'current_tapped_literal': source['tapped']})
            if not valid: continue
            statuses[position] = CONSISTENT
            result['relations'].append({'list_position': position, 'action_identifier_refs': copy.deepcopy(action['identifier_refs']),
                'action_flags': copy.deepcopy(action['flags']), 'target_member': copy.deepcopy(member),
                'mana_row_witnesses': payment_rows, 'relation_status': CONSISTENT})
        result['returned_relations'] = len(result['relations'])
        result['action_row_coverage'] = {'engine_active_action_rows': len(rows), 'consistent_relation_rows': statuses.count(CONSISTENT),
            'contradicted_known_relation_rows': statuses.count('violated_known_constraints'),
            'unknown_or_unreviewed_rows': sum(s not in (CONSISTENT, 'violated_known_constraints') for s in statuses),
            'row_statuses': [{'list_position': i, 'relation_status': s} for i,s in enumerate(statuses)]}
        if result['relations']: result.update(status=CONSISTENT, reason='same_current_target_and_predictive_route_observed')
        if combined:
            # New v12 entry points share the composite's current-source gate;
            # a claimed GOOD verdict cannot override a changed ability/menu.
            from .cast_target_members import _equal
            expected, expected_statuses = _expected_relations(state, value)
            if not _equal(result['relations'], expected) or [r['relation_status'] for r in result['action_row_coverage']['row_statuses']] != expected_statuses:
                return unknown('choice_validator_contract_mismatch')
        _bounded_json(result)
        return result
    except (ValueError, TypeError, KeyError, IndexError, RecursionError, UnicodeError, OverflowError):
        return unknown('state_or_request_evidence_invalid')


def assess_current_relation(consumer):
    from .choice_candidates import _assess_current_report
    return _assess_current_report(consumer, evaluate_relation, unknown)
