"""Request-bound proposal research on the current Consumer; never an input grant."""
import copy
import json
from pathlib import Path

VERSION = 'mtgaplayer.choice-validation.v1'
MAX_PROPOSAL_BYTES = 256 * 1024
SCOPE = 'offered_generic_one_predictive_payment_consistency'


def check_proposal(value):
    from .decision_consumer import _bounded_json, _binding, _integer, _keys, _reference
    from .request_parameters import _action
    _bounded_json(value)
    if type(value) is dict and 'proposed_current_selected_target_set' in value:
        from .semantic_targets import check_current_selected_proposal
        _keys(value, ('request_identity', 'proposed_current_selected_target_set'), ('source_snapshot_ref',))
        _binding(value['request_identity'], complete=True)
        if (value['request_identity']['request_id'] is None or
                value['request_identity']['request_type'] != 'GREMessageType_SelectTargetsReq'):
            raise ValueError('invalid_choice_proposal')
        check_current_selected_proposal(value['proposed_current_selected_target_set'])
        if 'source_snapshot_ref' in value:
            ref = value['source_snapshot_ref']
            _reference(ref, ref['session_id'], ref['sequence'], snapshot=True)
            if ref['binding'] != value['request_identity']:
                raise ValueError('invalid_choice_proposal')
        return
    if type(value) is dict and 'proposed_activate_target_member' in value:
        _keys(value,('request_identity','list_position','proposed_activate_target_member'),('source_snapshot_ref',))
        _binding(value['request_identity'],complete=True)
        if (value['request_identity']['request_id'] is None or
                value['request_identity']['request_type']!='GREMessageType_ActionsAvailableReq'):
            raise ValueError('invalid_choice_proposal')
        _integer(value['list_position'],0,255)
        member=value['proposed_activate_target_member']
        _keys(member,('identifier_refs','target_idx','object_ref'))
        _keys(member['identifier_refs'],('instanceId','grpId','facetId','abilityGrpId','uniqueAbilityId'))
        for ref in member['identifier_refs'].values():_integer(ref,1)
        _integer(member['target_idx'],1);_integer(member['object_ref'],1)
        if 'source_snapshot_ref' in value:
            ref=value['source_snapshot_ref']
            _reference(ref,ref['session_id'],ref['sequence'],snapshot=True)
            if ref['binding']!=value['request_identity']:raise ValueError('invalid_choice_proposal')
        return
    if (type(value) is dict and type(value.get('request_identity')) is dict and
            value['request_identity'].get('request_type') == 'GREMessageType_PayCostsReq'):
        from .decision_consumer import _list
        _keys(value, ('request_identity', 'proposed_cost_selection'), ('source_snapshot_ref',))
        _binding(value['request_identity'], complete=True)
        if value['request_identity']['request_id'] is None:
            raise ValueError('invalid_choice_proposal')
        proposed = value['proposed_cost_selection']
        _keys(proposed, ('selected_object_refs',))
        _list(proposed['selected_object_refs'], 256)
        for ref in proposed['selected_object_refs']:
            _integer(ref, 1)
        if 'source_snapshot_ref' in value:
            ref = value['source_snapshot_ref']
            _reference(ref, ref['session_id'], ref['sequence'], snapshot=True)
            if ref['binding'] != value['request_identity']:
                raise ValueError('invalid_choice_proposal')
        return
    if (type(value) is dict and type(value.get('request_identity')) is dict and
            value['request_identity'].get('request_type') == 'GREMessageType_SelectTargetsReq'):
        from .semantic_targets import check_final_set
        _keys(value, ('request_identity', 'proposed_final_target_set'), ('source_snapshot_ref',))
        _binding(value['request_identity'], complete=True)
        if value['request_identity']['request_id'] is None:
            raise ValueError('invalid_choice_proposal')
        # Structural validation only. Quantity/membership contradictions are
        # meaningful verdicts, not loader failures.
        proposed = value['proposed_final_target_set']
        check_final_set({'source_object_ref': proposed['source_object_ref'],
            'target_idx': proposed['target_idx'], 'min_targets': None, 'max_targets': None,
            'entries': None}, proposed)
        if 'source_snapshot_ref' in value:
            ref = value['source_snapshot_ref']
            _reference(ref, ref['session_id'], ref['sequence'], snapshot=True)
            if ref['binding'] != value['request_identity']:
                raise ValueError('invalid_choice_proposal')
        return
    _keys(value, ('request_identity', 'list_position', 'proposed_action'), ('source_snapshot_ref',))
    _binding(value['request_identity'], complete=True)
    if value['request_identity']['request_id'] is None:
        raise ValueError('invalid_choice_proposal')
    _integer(value['list_position'], 0, 255)
    _action(value['proposed_action'], activate=type(value['proposed_action']) is dict and
            value['proposed_action'].get('action_type') == 'ActionType_Activate')
    if 'source_snapshot_ref' in value:
        ref = value['source_snapshot_ref']
        _reference(ref, ref['session_id'], ref['sequence'], snapshot=True)
        if ref['binding'] != value['request_identity']:
            raise ValueError('invalid_choice_proposal')


def load_proposal(path):
    """Read once, bounded, before subscription timers or input workers start."""
    def pairs(rows):
        result = {}
        for key, value in rows:
            if key in result:
                raise ValueError('invalid_choice_proposal')
            result[key] = value
        return result
    def constant(value):
        raise ValueError('invalid_choice_proposal')
    try:
        with Path(path).open('rb') as stream:
            raw = stream.read(MAX_PROPOSAL_BYTES + 1)
        if len(raw) > MAX_PROPOSAL_BYTES:
            raise ValueError('invalid_choice_proposal')
        value = json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
        check_proposal(value)
        return value
    except (OSError, ValueError, UnicodeError, TypeError, KeyError, RecursionError):
        raise ValueError('choice_proposal_unavailable_or_invalid') from None


def _result(reason=None):
    from .decision_consumer import EXECUTION
    return {'schema_version': VERSION, 'validation_scope': SCOPE,
        'known_constraints': 'insufficient_evidence',
        'reasons': [reason] if reason else [], 'source_snapshot_ref': None,
        'all_payment_options_verified': False, 'read_only': True, **EXECUTION}


def validate_proposed_choice(state, proposal, *, source_snapshot_ref=None):
    """Pure visible-state check. No response or successor is an argument.

    Passing only establishes the reviewed offered proposal's internal and
    same-request consistency. It never means the entire Cast is legal.
    """
    from .decision_consumer import _state, _bounded_json
    from .request_parameters import check
    from .semantic_cast import check_predictive_payment
    result = _result()
    try:
        check_proposal(proposal)
        _bounded_json(state)
        _state(state, state['binding'])
        if (proposal['request_identity'] != state['binding'] or
                'source_snapshot_ref' in proposal and proposal['source_snapshot_ref'] != source_snapshot_ref):
            return _result('proposal_binding_invalid')
        def unknown(reason):
            r = _result(reason)
            r['source_snapshot_ref'] = copy.deepcopy(source_snapshot_ref)
            return r
        evidence = state['legal_action_space'].get('request_parameters')
        if evidence is None:
            return unknown('reviewed_request_parameters_not_observed')
        check(evidence, state['binding'], state['visible_objects'])
        if 'proposed_current_selected_target_set' in proposal:
            from .semantic_targets import PROFILE, CURRENT_SELECTED_SCOPE, check_current_selected_set
            from .decision_consumer import _binding
            if evidence['profile'] != PROFILE:
                return unknown('current_selected_target_profile_not_observed')
            # Keep legacy validators unchanged, while refusing bool/int
            # equality in this new check's nested request scope.
            _binding(evidence['binding'], complete=True)
            status, reason = check_current_selected_set(evidence['targets'],
                proposal['proposed_current_selected_target_set'],
                [{'object_ref': o['instance_id'], 'zone': o['zone']} for o in state['visible_objects']],
                state['binding']['self_seat'], state['game']['stack'])
            result.update(validation_scope=CURRENT_SELECTED_SCOPE, known_constraints=status,
                reasons=[reason], source_snapshot_ref=copy.deepcopy(source_snapshot_ref),
                current_selected_literal_verified=status == 'verified_known_constraints',
                complete_target_legality_verified=False, target_domain_complete_verified=False,
                target_quantity_completeness_verified=False, complete_costs_verified=False,
                complete_payment_verified=False, mana_payment_verified=False,
                new_selectable_domain_used=False, target_set_enumeration_performed=False,
                historical_response_used=False)
            return result
        from .action_target_menus import CURRENT_PROFILE,CURRENT_SCOPE,check_member
        if evidence['profile']==CURRENT_PROFILE:
            if 'proposed_activate_target_member' not in proposal:
                return unknown('target_member_proposal_required')
            status,reason,checks=check_member(evidence,proposal['proposed_activate_target_member'],
                proposal['list_position'],state['visible_objects'],state['binding']['self_seat'])
            result.update(validation_scope=CURRENT_SCOPE,known_constraints=status,reasons=[reason],
                known_checks=checks,source_snapshot_ref=copy.deepcopy(source_snapshot_ref),
                target_selection_count=None,target_minimum=None,target_maximum=None,
                target_domain_complete_verified=False,target_selection_legality_verified=False,
                target_set_combinations_enumerated=False,complete_costs_verified=False,
                complete_payment_verified=False,target_quantity_verified=False,
                global_target_legality_verified=False,historical_response_used=False,
                future_parameters='unknown')
            return result
        if 'proposed_activate_target_member' in proposal:
            return unknown('current_target_member_profile_not_observed')
        from . import semantic_effect_cost as cost
        if state['binding']['request_type'] == cost.REQUEST:
            if evidence['profile'] != cost.PROFILE:
                return unknown('effect_cost_profile_not_observed')
            from .request_parameters import effect_cost_objects
            status, reason = cost.check_selection(evidence['cost_selection'],
                proposal['proposed_cost_selection']['selected_object_refs'],
                visible=effect_cost_objects(state['visible_objects']), seat=state['binding']['self_seat'])
            result.update(validation_scope='offered_visible_single_nonmana_selection_consistency',
                known_constraints=status, reasons=[reason, 'complete_payment_and_rules_effect_unverified'],
                complete_costs_verified=False, payment_completed_verified=False, rules_effect_verified=False,
                future_parameters='unknown', source_snapshot_ref=copy.deepcopy(source_snapshot_ref))
            return result
        from .semantic_activate import PROFILE as ACTIVATE_PROFILE, SCOPE as ACTIVATE_SCOPE, check_payment
        if evidence['profile'] == ACTIVATE_PROFILE:
            result['validation_scope'] = ACTIVATE_SCOPE
            result['complete_costs_verified'] = False
            result['additional_costs'] = 'unknown'
            result['future_parameters'] = 'unknown'
            position = proposal['list_position']
            rows, chosen = evidence['rows'], proposal['proposed_action']
            if (position >= len(rows) or chosen['action_type'] != rows[position]['action_type'] or
                    chosen['identifier_refs'] != rows[position]['identifier_refs']):
                return _result('proposal_binding_invalid')
            status, reason, checks = check_payment(rows, chosen, state['visible_objects'],
                state['binding']['self_seat'], position)
            result.update(known_constraints=status, reasons=[reason], known_checks=checks,
                          source_snapshot_ref=copy.deepcopy(source_snapshot_ref))
            return result
        if state['binding']['request_type'] == 'GREMessageType_SelectTargetsReq':
            from .semantic_targets import PROFILE, SCOPE as TARGET_SCOPE, check_final_set
            if evidence['profile'] != PROFILE:
                return unknown('target_profile_not_observed')
            status, reason = check_final_set(evidence['targets'], proposal['proposed_final_target_set'])
            if reason == 'proposal_binding_invalid':
                return _result(reason)
            result['validation_scope'] = TARGET_SCOPE
            result['known_constraints'] = status
            result['reasons'] = [reason, 'incremental_ui_reachability_and_additional_constraints_unverified']
            result['source_snapshot_ref'] = copy.deepcopy(source_snapshot_ref)
            return result
        rows, position = evidence['actions'], proposal['list_position']
        if position >= len(rows):
            return _result('proposal_binding_invalid')
        offered, chosen = rows[position], proposal['proposed_action']
        if chosen['action_type'] != offered['action_type'] or chosen['identifier_refs'] != offered['identifier_refs']:
            return _result('proposal_binding_invalid')
        if chosen['action_type'] != 'ActionType_Cast':
            return unknown('action_profile_not_supported')
        objects = state['visible_objects']
        source = [o for o in objects if o['instance_id'] == chosen['identifier_refs']['instanceId']]
        if (len(source) != 1 or source[0]['zone'] != 'ZoneType_Hand' or
                source[0]['owner_seat'] != state['binding']['self_seat']):
            return unknown('cast_source_not_verified')
        for row in (offered, chosen):
            if not {'manaCost', 'autoTapSolution'} <= set(row['parameters']) | set(row['observed_empty_parameters']):
                return unknown('required_mana_parameters_not_observed')
        if any(offered['parameters'].get(k) != chosen['parameters'].get(k) or
                (k in offered['observed_empty_parameters']) != (k in chosen['observed_empty_parameters'])
                for k in ('manaCost', 'autoTapSolution')):
            return unknown('alternative_payment_path_not_supported')
        before = [{'object_ref': o['instance_id'], 'zone': o['zone'], 'controller': o['controller_seat']}
                  for o in objects]
        status, _ = check_predictive_payment(rows, chosen, before, state['binding']['self_seat'], position)
        result['known_constraints'] = status
        result['reasons'] = [{'verified_known_constraints': 'offered_proposal_consistent',
            'violated_known_constraints': 'observed_predictive_payment_relation_contradicted',
            'insufficient_evidence': 'payment_profile_or_visible_source_insufficient'}[status]]
        result['source_snapshot_ref'] = copy.deepcopy(source_snapshot_ref)
        return result
    except (ValueError, TypeError, KeyError, IndexError, RecursionError, UnicodeError):
        return _result('proposal_or_state_invalid')


def assess_current_choice(consumer, proposal):
    """Owner-thread current-only wrapper; never falls back to last_valid."""
    from .decision_consumer import DecisionConsumer, EXECUTION, _bounded_json
    if not isinstance(consumer, DecisionConsumer):
        return _result('requires_current_consumer')
    try:
        view = consumer.current_view()
        _bounded_json(view)
        if view['consumer_status'] != 'OBSERVING':
            return _result('consumer_' + view['consumer_status'].lower())
        state, ref = view['decision_state'], view['current_snapshot_ref']
        if state is None or ref is None or view['new_request_observed'] is not True:
            return _result('current_request_not_observed')
        if (view['transport_alive'] is not True or view['read_only'] is not True or
                any(view[k] is not False for k in EXECUTION) or ref['binding'] != state['binding'] or
                ref['session_id'] != view['session_id'] or not 1 <= ref['sequence'] <= view['last_sequence'] or
                state['status'] != 'state_and_request_observed' or state['source']['mode'] != 'watch' or
                state['source']['phase'] != 'append' or state['source']['stopped'] is not False):
            return _result('current_snapshot_binding_invalid')
        result = validate_proposed_choice(state, proposal, source_snapshot_ref=ref)
        # Even a slow pure check cannot retain an expired current assessment.
        after = consumer.current_view()
        if after['consumer_status'] != 'OBSERVING' or after['current_snapshot_ref'] != ref:
            return _result('current_snapshot_expired_or_changed')
        return result
    except (ValueError, TypeError, KeyError, RecursionError, UnicodeError):
        return _result('current_view_unavailable')
