"""Explicit owner-thread current PayCosts evidence, never a payment solver.

The accepted raw message stays with its existing reducer. The Consumer owns
freshness; MP65 owns existing nonmana proposals. No state/event extension,
retained result, response encoding or independently maintained request ledger.
"""
import copy
from collections import Counter

from .choice_candidates import _assess_current_report
from .decision_consumer import EXECUTION, _bounded_json
from .response_evidence import _current_verified_raw_request
from .choice_continuation import _binding
from .cast_target_members import _equal
from .semantic_samples import _keys, _need
from .semantic_cast import COLORS, _amount, _parameter, action
from .request_parameters import LiteralRefs, _visible_references

VERSION = 'mtgaplayer.current-cost-stage.v1'
MANA_PROFILE = 'observed_mana_payment_actions_with_associated_object'
UNKNOWN = ('complete_payment_unknown', 'payment_combination_unknown',
    'additional_costs_unknown', 'requirement_object_role_unknown',
    'prompt_routing_unknown', 'payment_selection_semantics_unknown',
    'explicit_parent_cost_link_unknown', 'complete_legality_unknown',
    'response_encoding_unknown', 'server_acceptance_unknown')
MATCH_VERSION = 'mtgaplayer.current-mana-requirement-match.v1'
MATCHED = 'reviewed_predictive_mana_amount_consistent'
UNSUPPORTED_MATCH_SHAPES = ('single_concrete_mana_requirement_not_observed',
    'single_predictive_solution_not_observed', 'single_predictive_descriptor_not_observed',
    'single_predictive_unit_not_observed', 'duplicate_predictive_source_not_reviewed')


def unknown(reason):
    return {'schema_version': VERSION, 'status': 'insufficient_evidence', 'reason': reason,
        'current_request_binding': None, 'source_snapshot_ref': None,
        'cost_request_profile': None, 'reviewed_cost_selection': None,
        'local_candidates': [], 'local_candidate_coverage': None,
        'mana_requirements': [], 'payment_actions': [], 'predictive_auto_tap_solutions': [],
        'historical_parent_context': None, 'historical_parent_current': False,
        'explicit_parent_cost_link_verified': False, 'causal_relationship_unverified': True,
        'complete_payment_verified': False, 'complete_legality_verified': False,
        'unresolved_cost_constraints': list(UNKNOWN), 'read_only': True, **EXECUTION}


def _unknown_match(reason):
    return {'schema_version': MATCH_VERSION, 'status': 'insufficient_evidence', 'reason': reason,
        'current_request_binding': None, 'source_snapshot_ref': None,
        'requirement_amounts': [], 'predictive_amounts': [], 'predictive_solution_position': None,
        'matched_payment_action_positions': [], 'requirement_observed': False,
        'predictive_output_observed': False, 'color_count_consistency': None,
        'source_identity_consistency': None, 'ability_identity_consistency': None,
        'payment_source_ref': None, 'payment_ability_grp_ref': None,
        'additional_costs_unknown': True, 'source_readiness_unknown': True,
        'complete_payment_unknown': True, 'source_readiness_verified': False,
        'complete_payment_verified': False, 'complete_legality_verified': False, 'full_action_legality_verified': False,
        'ability_catalog_verified': False, 'all_payment_routes_verified': False,
        'historical_response_used': False, 'read_only': True, **EXECUTION}


def _review_mana_requirement(stage, visible, seat, reducer):
    """Compare already parsed literals; never parse GRE or sum alternative sources.

    Only one concrete requirement, one solution/descriptor/unit is reviewed.
    Ability identity here is the offered descriptor/unit/action join, not a
    proof from a card's ability catalog. Source readiness stays unknown.
    """
    result = _unknown_match('single_concrete_mana_requirement_not_observed')
    requirements = stage['mana_requirements']; solutions = stage['predictive_auto_tap_solutions']
    result.update(requirement_amounts=[copy.deepcopy(r['amount']) for r in requirements],
        requirement_observed=bool(requirements), predictive_output_observed=bool(solutions))
    if len(requirements) != 1 or requirements[0]['amount']['color'][0] not in COLORS[1:]:
        return result
    if len(solutions) != 1:
        result['reason'] = 'single_predictive_solution_not_observed'; return result
    solution = solutions[0]; descriptors = solution['solution']['autoTapActions']
    result.update(predictive_solution_position=solution['list_position'],
        matched_payment_action_positions=copy.deepcopy(solution['current_payment_action_positions']))
    if len({d['instanceId'] for d in descriptors}) != len(descriptors):
        result['reason'] = 'duplicate_predictive_source_not_reviewed'; return result
    if len(descriptors) != 1:
        result['reason'] = 'single_predictive_descriptor_not_observed'; return result
    descriptor = descriptors[0]; units = descriptor['manaPaymentOption']['mana']
    if len(units) != 1:
        result['reason'] = 'single_predictive_unit_not_observed'; return result
    unit = units[0]; position = solution['current_payment_action_positions'][0]
    offered = stage['payment_actions'][position]['action']; ids = offered['identifier_refs']
    _need(all(type(ids[k]) is int and ids[k] > 0 for k in ('instanceId', 'abilityGrpId', 'uniqueAbilityId')) and
        type(unit['manaId']) is int and unit['manaId'] > 0)
    result.update(predictive_amounts=[{k:unit[k] for k in ('color', 'count')}],
        payment_source_ref=descriptor['instanceId'], payment_ability_grp_ref=descriptor['abilityGrpId'])
    result['source_identity_consistency'] = (_equal(unit['srcInstanceId'], descriptor['instanceId']) and
        _equal(descriptor['instanceId'], ids['instanceId']))
    result['ability_identity_consistency'] = (_equal(unit['abilityGrpId'], descriptor['abilityGrpId']) and
        _equal(descriptor['abilityGrpId'], ids['abilityGrpId']))
    if not result['source_identity_consistency'] or not result['ability_identity_consistency']:
        result.update(status='violated_known_constraints', reason='predictive_source_or_ability_identity_contradicted')
        return result
    # Reuse the existing raw public/unique-zone identity gate. Only the chosen
    # descriptor is reviewed; repeated sources among alternative offers are OK.
    from .current_target_request import _identity
    signature = _identity(reducer, descriptor['instanceId'], ('GameObjectType_Card',), 'ZoneType_Battlefield')
    source = next((o for o in visible if _equal(o['instance_id'], descriptor['instanceId'])), None)
    _need(source is not None and all(type(source[k]) is int and source[k] == seat for k in ('owner_seat', 'controller_seat')))
    _need(_equal(source['card_id'], ids['grpId']))
    result['color_count_consistency'] = _equal(requirements[0]['amount'],
        {'color': [unit['color']], 'count': unit['count']})
    result.update(status=MATCHED if result['color_count_consistency'] else 'violated_known_constraints',
        reason='single_concrete_requirement_and_predictive_unit_equal' if result['color_count_consistency'] else
            'predictive_color_or_count_contradicted')
    # Raw object mutation during calculation cannot preserve the source proof.
    _need(_equal(_identity(reducer, descriptor['instanceId'], ('GameObjectType_Card',),
        'ZoneType_Battlefield'), signature))
    return result


def _prompt(prompt):
    # Representation only. No string/name/id values are exported or interpreted
    # as routing, a source identity, a cost or a parent-action reference.
    _keys(prompt, ('promptId', 'parameters'))
    _need(type(prompt['promptId']) is int and 0 < prompt['promptId'] < 2**32)
    _need(type(prompt['parameters']) is list and len(prompt['parameters']) == 1)
    p = prompt['parameters'][0]
    _keys(p, ('parameterName', 'type', 'stringValue'))
    _need(type(p['parameterName']) is str and 0 < len(p['parameterName']) <= 128 and
        p['type'] == 'ParameterType_NonLocalizedString' and type(p['stringValue']) is str and len(p['stringValue']) <= 4096)


def project_mana_stage(message, visible, seat):
    """Finite witnessed shape; delegate amounts/actions/predictive mana checks.

    ObjectId is preserved as an associated visible object, with its rule role
    explicitly unknown. It is never dropped to force the old amount parser to
    accept a different whole shape, nor treated as a mana source/parent Cast.
    """
    _keys(message, ('type', 'systemSeatIds', 'msgId', 'gameStateId', 'prompt',
        'payCostsReq', 'allowCancel', 'allowUndo'))
    _need(message['type'] == 'GREMessageType_PayCostsReq' and
        type(message['systemSeatIds']) is list and len(message['systemSeatIds']) == 1 and
        type(seat) is int and seat in (1, 2) and type(message['systemSeatIds'][0]) is int and
        message['systemSeatIds'][0] == seat and message['allowCancel'] == 'AllowCancel_Abort' and
        message['allowUndo'] is True)
    for key in ('msgId', 'gameStateId'):
        _need(type(message[key]) is int and 0 <= message[key] < 2**53)
    _prompt(message['prompt'])
    body = message['payCostsReq']
    _keys(body, ('manaCost', 'paymentActions', 'paymentSelection', 'autoTapActionsReq'))
    counts = Counter(o['instance_id'] for o in visible)
    objects = {o['instance_id']: o for o in visible}
    _need(type(body['manaCost']) is list and 1 <= len(body['manaCost']) <= 64)
    requirements = []
    for position, row in enumerate(body['manaCost']):
        _keys(row, ('color', 'count', 'objectId'))
        ident = row['objectId']
        _need(type(ident) is int and 0 < ident < 2**32 and counts[ident] == 1 and
            objects[ident]['zone'] in ('ZoneType_Battlefield', 'ZoneType_Stack'))
        amount = _amount({'color': row['color'], 'count': row['count']}, True)
        requirements.append({'list_position': position, 'amount': amount,
            'associated_object_ref': ident, 'associated_object_rule_role': 'unknown'})
    payment = body['paymentActions']; _keys(payment, ('actions',))
    _need(type(payment['actions']) is list and 1 <= len(payment['actions']) <= 64)
    actions = []
    for position, raw in enumerate(payment['actions']):
        literal = action(raw, LiteralRefs(), ())
        _need(literal['action_type'] == 'ActionType_Activate_Mana' and
            _visible_references(literal, visible))
        actions.append({'list_position': position, 'action': literal})
    # Preserve absence of ids/minSel/maxSel as unknown, not empty/zero choices.
    selector = body['paymentSelection']
    _keys(selector, ('context', 'optionContext', 'listType', 'idType',
        'validationType', 'minWeight', 'maxWeight'))
    _need(all(type(selector[k]) is str and 0 < len(selector[k]) <= 128 for k in
        ('context', 'optionContext', 'listType', 'idType', 'validationType')) and
        all(type(selector[k]) is int and -2**31 <= selector[k] < 2**31 for k in ('minWeight', 'maxWeight')))
    auto = body['autoTapActionsReq']; _keys(auto, ('autoTapSolutions',))
    _need(type(auto['autoTapSolutions']) is list and 1 <= len(auto['autoTapSolutions']) <= 64)
    solutions = []
    for position, raw in enumerate(auto['autoTapSolutions']):
        literal = _parameter('autoTapSolution', raw, LiteralRefs(), ())
        _need(_visible_references({'identifier_refs': {}, 'parameters': {'autoTapSolution': literal}}, visible))
        witnesses = []
        for descriptor in literal['autoTapActions']:
            matches = [a['list_position'] for a in actions if
                _equal(a['action']['identifier_refs'].get('instanceId'), descriptor['instanceId']) and
                _equal(a['action']['identifier_refs'].get('abilityGrpId'), descriptor['abilityGrpId']) and
                any(_equal(option, descriptor['manaPaymentOption']) for option in
                    a['action']['parameters'].get('manaPaymentOptions', []))]
            _need(len(matches) == 1)
            witnesses.append(matches[0])
        solutions.append({'list_position': position, 'solution': literal,
            'current_payment_action_positions': witnesses, 'payment_completed_verified': False})
    return {'mana_requirements': requirements, 'payment_actions': actions,
        'predictive_auto_tap_solutions': solutions}


def assess_current_cost_stage(consumer, reducer, message, *, mana_requirement_match=False):
    """Same owner thread supplies its accepted message; no offline-state bypass.

    Existing digest authentication is checked before AND after projection in
    addition to the shared Consumer ref/lease/append gate. No result cache.
    """
    if type(mana_requirement_match) is not bool: raise ValueError('invalid_mana_requirement_match_flag')
    def denied(reason):
        result = unknown(reason)
        if mana_requirement_match: result['mana_requirement_match'] = _unknown_match(reason)
        return result
    def evaluate(state, *, source_snapshot_ref):
        request = _current_verified_raw_request(reducer, message)
        if (request is None or request['type'] != 'GREMessageType_PayCostsReq' or
                not _equal(_binding(reducer, request), state['binding'])):
            return denied('authenticated_current_cost_request_not_observed')
        expected = [{'instance_id': o['id'], 'card_id': o['card_id'], 'zone': o['zone'],
            'owner_seat': o['owner'], 'controller_seat': o['controller']}
            for o in reducer.document()['current']['objects']]
        observed = [{k: o[k] for k in ('instance_id', 'card_id', 'zone', 'owner_seat', 'controller_seat')}
            for o in state['visible_objects']]
        if not _equal(expected, observed):
            return denied('current_visible_projection_disagrees_with_reducer')
        options = consumer.current_decision_options()
        if (not _equal(options['request_binding'], state['binding']) or
                not _equal(options['source_snapshot_ref'], source_snapshot_ref) or
                options['status'] not in ('partial', 'unsupported') or options['read_only'] is not True or
                any(options[k] is not False for k in EXECUTION) or any(
                    not _equal(o['request_binding'], state['binding']) or
                    not _equal(o['source_snapshot_ref'], source_snapshot_ref) or
                    o['read_only'] is not True or any(o[k] is not False for k in EXECUTION)
                    for o in options['options'])):
            return denied('current_options_binding_invalid')
        result = denied('current_cost_local_evidence_only')
        params = state['legal_action_space']['request_parameters']
        from .semantic_effect_cost import PROFILE, project_request
        if params is not None and params['profile'] == PROFILE:
            from .request_parameters import effect_cost_objects
            if not _equal(project_request(message, effect_cost_objects(state['visible_objects']),
                    state['binding']['self_seat'], LiteralRefs(), ()), params['cost_selection']):
                return denied('raw_cost_projection_disagrees_with_current_parameters')
            result.update(cost_request_profile=PROFILE,
                reviewed_cost_selection=copy.deepcopy(params['cost_selection']),
                local_candidates=[copy.deepcopy(o) for o in options['options'] if o['kind'] == 'cost_selection'],
                local_candidate_coverage=copy.deepcopy(options['coverage']))
            if mana_requirement_match:
                result['mana_requirement_match'] = _unknown_match('nonmana_stage_has_no_mana_requirement_match')
        else:
            result.update(project_mana_stage(message, state['visible_objects'], state['binding']['self_seat']),
                cost_request_profile=MANA_PROFILE)
            if mana_requirement_match:
                # Stronger MP75 proof gates must not rewrite MP72's independent
                # structural observation or misclassify its shape in history.
                if reducer._target_state_continuity_verified is not True or request.get('_cost_evidence_interrupted') is True:
                    match = _unknown_match('current_mana_match_continuity_not_verified')
                else:
                    try:
                        match = _review_mana_requirement(result, state['visible_objects'], state['binding']['self_seat'], reducer)
                    except (ValueError, TypeError, KeyError, IndexError, RecursionError):
                        match = _unknown_match('current_mana_match_identity_unverified')
                result['mana_requirement_match'] = match
        after = _current_verified_raw_request(reducer, message)
        if after is None or not _equal(_binding(reducer, after), state['binding']):
            return denied('authenticated_cost_request_expired_or_changed')
        if mana_requirement_match and result['cost_request_profile'] == MANA_PROFILE:
            if reducer._target_state_continuity_verified is not True or after.get('_cost_evidence_interrupted') is True:
                result['mana_requirement_match'] = _unknown_match('current_mana_match_continuity_not_verified')
            now = [{'instance_id': o['id'], 'card_id': o['card_id'], 'zone': o['zone'],
                'owner_seat': o['owner'], 'controller_seat': o['controller']}
                for o in reducer.document()['current']['objects']]
            if not _equal(expected, now):
                result['mana_requirement_match'] = _unknown_match('current_visible_projection_changed')
            result['mana_requirement_match'].update(current_request_binding=copy.deepcopy(state['binding']),
                source_snapshot_ref=copy.deepcopy(source_snapshot_ref))
        result.update(status='observed', current_request_binding=copy.deepcopy(state['binding']),
            source_snapshot_ref=copy.deepcopy(source_snapshot_ref))
        _bounded_json(result)
        return result
    return _assess_current_report(consumer, evaluate, denied)
