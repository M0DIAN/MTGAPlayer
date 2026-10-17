"""Finite reviewed current-request choice alternatives, never full MTG legality."""
import copy
from itertools import combinations
from math import comb

from .decision_consumer import DecisionConsumer, EXECUTION, _bounded_json, _state

VERSION = 'mtgaplayer.known-choice-candidates.v2'
SCOPE = 'reviewed_current_request_known_constraints_only'
MAX_CANDIDATES = 64
PROPOSAL_VERSION = 'mtgaplayer.known-choice-candidates.v3'
DISCARD_VERSION = 'mtgaplayer.known-choice-candidates.v4'
MAX_TARGET_PROBES = 256


def check_version(version):
    if type(version) is not int or version not in (2, 3, 4, 5):
        raise ValueError('invalid_known_candidate_version')


def _unknown(reason, ref=None):
    return {'schema_version': VERSION, 'scope': SCOPE,
        'status': 'insufficient_evidence', 'reason': reason,
        'source_snapshot_ref': copy.deepcopy(ref), 'request_type': None, 'profile': None,
        'candidate_total_for_reviewed_constraints': None, 'returned_candidates': 0,
        'truncated': False, 'exhaustive_for_reviewed_constraints': False, 'candidates': [],
        'action_row_coverage': None,
        'full_action_domain_complete': False, 'global_restrictions_verified': False,
        'complete_payment_verified': False, 'complete_legality_verified': False,
        'server_acceptance_verified': False, 'historical_response_used': False,
        'read_only': True, **EXECUTION}


def enumerate_known_candidates(state, *, source_snapshot_ref=None, limit=MAX_CANDIDATES, version=2):
    """Reviewed choices (v2), target probes (v3), or eight-offer Discard (v4).

    Does not establish freshness: supplied offline states are research only.
    Live users must call assess_current_known_candidates on the Consumer.
    """
    check_version(version)
    if type(limit) is not int or not 1 <= limit <= MAX_CANDIDATES:
        raise ValueError('invalid_known_candidate_limit')
    if version == 3:
        return _reviewed_target_proposals(state, source_snapshot_ref, limit)
    if version == 4:
        return _discard_proposals(state, source_snapshot_ref, limit)
    if version == 5:
        from .cast_target_members import enumerate_members
        return enumerate_members(state, source_snapshot_ref=source_snapshot_ref, limit=limit)
    try:
        _bounded_json(state)
        _state(state, state['binding'])
        if state['status'] != 'state_and_request_observed' or state['binding']['request_id'] is None:
            return _unknown('no_verified_current_request')
        binding = state['binding']
        if source_snapshot_ref is not None:
            from .decision_consumer import _reference
            _reference(source_snapshot_ref, source_snapshot_ref['session_id'],
                       source_snapshot_ref['sequence'], snapshot=True)
            if source_snapshot_ref['binding'] != binding:
                return _unknown('snapshot_binding_invalid')
        evidence = state['legal_action_space']['request_parameters']
        if evidence is None:
            return _unknown('reviewed_request_parameters_not_observed')
        from .request_parameters import check, effect_cost_objects
        from .semantic_targets import PROFILE as TARGET_PROFILE, SELECT, check_final_set
        from .semantic_effect_cost import REQUEST as COST_REQUEST, PROFILE as COST_PROFILE, check_selection
        from .choice_validation import check_proposal
        check(evidence, binding, state['visible_objects'])
        from .action_target_menus import CURRENT_PROFILE
        if evidence['profile']==CURRENT_PROFILE:
            # A member observation cannot enumerate final target sets without
            # quantity bounds. Use the explicit proposal checker instead.
            return _unknown('target_member_proposal_required',source_snapshot_ref)
        request_type, profile = binding['request_type'], evidence['profile']
        proposals = []
        action_coverage = None
        if request_type == COST_REQUEST and profile == COST_PROFILE:
            current = evidence['cost_selection']
            domain = current['offered_object_refs']
            total = len(domain)
            visible = effect_cost_objects(state['visible_objects'])
            for ident in domain[:limit]:
                proposed = {'request_identity': copy.deepcopy(binding),
                    'proposed_cost_selection': {'selected_object_refs': [ident]}}
                if source_snapshot_ref is not None:
                    proposed['source_snapshot_ref'] = copy.deepcopy(source_snapshot_ref)
                check_proposal(proposed)
                status, _ = check_selection(current, [ident], visible=visible,
                                            seat=binding['self_seat'])
                if status != 'verified_known_constraints':
                    return _unknown('known_constraints_not_verified')
                proposals.append(proposed)
        elif request_type == 'GREMessageType_SelectTargetsReq' and profile == TARGET_PROFILE:
            request = evidence['targets']
            entries = request['entries']
            minimum, maximum = request['min_targets'], request['max_targets']
            if entries is None or any(row['legal_action'] != SELECT for row in entries):
                return _unknown('complete_current_select_domain_not_observed')
            if minimum is None or maximum is None:
                return _unknown('final_target_count_bounds_not_observed')
            domain = [row['object_ref'] for row in entries]
            if minimum > len(domain):
                return _unknown('required_target_count_exceeds_offered_domain')
            upper = min(maximum, len(domain))
            total = sum(comb(len(domain), count) for count in range(minimum, upper+1))
            if total == 0:
                return _unknown('no_supported_final_target_sets')
            for count in range(minimum, upper+1):
                for selected in combinations(domain, count):
                    if len(proposals) == limit:
                        break
                    final = {'source_object_ref': request['source_object_ref'],
                             'target_idx': request['target_idx'], 'object_refs': list(selected)}
                    proposed = {'request_identity': copy.deepcopy(binding),
                                'proposed_final_target_set': final}
                    if source_snapshot_ref is not None:
                        proposed['source_snapshot_ref'] = copy.deepcopy(source_snapshot_ref)
                    check_proposal(proposed)
                    status, _ = check_final_set(request, final)
                    if status != 'verified_known_constraints':
                        return _unknown('known_constraints_not_verified')
                    proposals.append(proposed)
                if len(proposals) == limit:
                    break
        elif request_type == 'GREMessageType_ActionsAvailableReq':
            # Preserve the complete active denominator while admitting only
            # existing, request-bound Cast/Activate checks. Unknown other rows
            # are NOT classified as illegal.
            from .request_parameters import PROFILE as MANA_PROFILE
            from .semantic_activate import PROFILE as ACTIVATE_PROFILE
            from .choice_validation import validate_proposed_choice
            if profile not in (MANA_PROFILE, ACTIVATE_PROFILE):
                return _unknown('request_profile_not_supported_for_enumeration')
            partial_activate = profile == ACTIVATE_PROFILE
            rows = evidence['rows'] if partial_activate else evidence['actions']
            selected_type = 'ActionType_Activate' if partial_activate else 'ActionType_Cast'
            total, unknown_rows, contradicted_rows = 0, 0, 0
            for position, row in enumerate(rows):
                if row['action_type'] != selected_type:
                    unknown_rows += 1
                    continue
                literal = row['literal_action'] if partial_activate else row
                if literal is None:
                    unknown_rows += 1
                    continue
                proposal = {'request_identity': copy.deepcopy(binding),
                    'list_position': position, 'proposed_action': copy.deepcopy(literal)}
                if source_snapshot_ref is not None:
                    proposal['source_snapshot_ref'] = copy.deepcopy(source_snapshot_ref)
                # Existing validator checks the *current* row, source, ability,
                # visibility and observed cost. No response/future-state input.
                verdict = validate_proposed_choice(
                    state, proposal, source_snapshot_ref=source_snapshot_ref)
                known = verdict['known_constraints']
                if verdict['source_snapshot_ref'] != source_snapshot_ref or any(
                        verdict.get(key) is True for key in (
                            'complete_costs_verified', 'complete_legality_verified',
                            'payment_completed_verified', 'server_acceptance_verified',
                            'all_payment_options_verified')):
                    return _unknown('choice_validator_contract_mismatch')
                if known == 'verified_known_constraints':
                    total += 1
                    if len(proposals) < limit:
                        proposals.append(proposal)
                elif known == 'violated_known_constraints':
                    contradicted_rows += 1
                else:
                    unknown_rows += 1
            action_coverage = {
                'engine_active_action_rows': len(rows),
                'verified_known_consistent_rows': total,
                'unknown_or_unreviewed_rows': unknown_rows,
                'contradicted_known_constraint_rows': contradicted_rows}
            if total + unknown_rows + contradicted_rows != len(rows):
                return _unknown('action_coverage_inconsistent')
            if not total:
                result = _unknown('no_verified_action_row_candidates', source_snapshot_ref)
                result['action_row_coverage'] = action_coverage
                return result
        else:
            return _unknown('request_profile_not_supported_for_enumeration')
        result = _unknown('additional_rules_and_future_requests_unverified', source_snapshot_ref)
        result.update(status='reviewed_constraint_candidates_observed',
                      request_type=request_type, profile=profile,
                      candidate_total_for_reviewed_constraints=total,
                      returned_candidates=len(proposals), truncated=total>len(proposals),
                      exhaustive_for_reviewed_constraints=total==len(proposals),
                      candidates=proposals, action_row_coverage=action_coverage)
        # Prevent bounded candidate *count* from producing an oversized
        # Consumer diagnostic if each projected parameter row is large.
        _bounded_json(result)
        return result
    except (ValueError, TypeError, KeyError, IndexError, RecursionError,
            UnicodeError, OverflowError):
        return _unknown('state_or_request_evidence_invalid')


def assess_current_known_candidates(consumer, *, limit=MAX_CANDIDATES, version=2):
    """Owner-thread lease/binding check, with no last_valid fallback."""
    check_version(version)
    from .cast_target_members import unknown as cast_unknown
    unknown = {2: _unknown, 3: _proposal_unknown, 4: _discard_unknown, 5: cast_unknown}[version]
    if type(limit) is not int or not 1 <= limit <= MAX_CANDIDATES:
        raise ValueError('invalid_known_candidate_limit')
    def evaluate(state, *, source_snapshot_ref):
        return enumerate_known_candidates(state, source_snapshot_ref=source_snapshot_ref, limit=limit, version=version)
    return _assess_current_report(consumer, evaluate, unknown)


def _assess_current_report(consumer, evaluate, unknown):
    """Shared owner-thread current/ref/lease gate for read-only reports."""
    if not isinstance(consumer, DecisionConsumer):
        return unknown('requires_current_consumer')
    try:
        view = consumer.current_view()
        if view['consumer_status'] != 'OBSERVING':
            return unknown('consumer_' + view['consumer_status'].lower())
        state, ref = view['decision_state'], view['current_snapshot_ref']
        if (state is None or ref is None or view['new_request_observed'] is not True or
                view['transport_alive'] is not True or view['read_only'] is not True or
                any(view[k] is not False for k in EXECUTION) or
                ref['binding'] != state['binding'] or ref['session_id'] != view['session_id'] or
                not 1 <= ref['sequence'] <= view['last_sequence'] or
                state['status'] != 'state_and_request_observed' or
                state['source']['mode'] != 'watch' or
                state['source']['phase'] != 'append' or
                state['source']['stopped'] is not False):
            return unknown('current_snapshot_binding_invalid')
        result = evaluate(state, source_snapshot_ref=ref)
        after = consumer.current_view()
        if (after['consumer_status'] != 'OBSERVING' or
                after['current_snapshot_ref'] != ref or
                after['new_request_observed'] is not True):
            return unknown('current_snapshot_expired_or_changed')
        return result
    except (ValueError, TypeError, KeyError, RecursionError, UnicodeError):
        return unknown('current_view_unavailable')


def _proposal_unknown(reason, ref=None):
    result = _unknown(reason, ref)
    result.update(schema_version=PROPOSAL_VERSION, scope='reviewed_current_target_proposals_only',
        request_binding=None, probe_kind=None, validation_scope=None,
        known_constraints='insufficient_evidence',
        probe_coverage={'observed_probes': 0, 'examined': 0, 'verified': 0,
            'unknown': 0, 'contradicted': 0, 'unexamined': 0, 'omitted_due_to_return_limit': 0},
        target_quantities={'minimum': None, 'maximum': None, 'selected_count': None,
            'basis': 'not_observed_in_action_menu', 'quantity_rules_complete_verified': False},
        target_domain_complete_verified=False, target_selection_legality_verified=False,
        complete_costs_verified=False, mana_payment_verified=False,
        new_selectable_domain_used=False, target_set_enumeration_performed=False)
    return result


def _discard_unknown(reason, ref=None):
    result = _unknown(reason, ref)
    result.update(schema_version=DISCARD_VERSION, scope='reviewed_current_discard_proposals_only',
        request_binding=None, probe_kind='discard_single_member_probe', validation_scope=None,
        known_constraints='insufficient_evidence', offered_member_count=None,
        minimum=None, maximum=None, selected_count=None,
        verified_probes=0, unknown_probes=0, contradicted_probes=0, omitted_due_to_return_limit=0,
        complete_costs_verified=False, mana_payment_verified=False, rules_effect_verified=False,
        unfiltered_domain_complete_verified=False, quantity_rules_complete_verified=False)
    return result


def _discard_proposals(state, ref, limit):
    """V4 only: existing pure validator, current eight offers, no outcome input."""
    try:
        from .semantic_hand import CURRENT_PROFILE, CURRENT_SCOPE
        from .choice_validation import VERSION as VALIDATION_VERSION, validate_proposed_choice
        from .decision_consumer import _reference
        _bounded_json(state)
        _state(state, state['binding'])
        binding = state['binding']
        if state['status'] != 'state_and_request_observed' or binding['request_id'] is None:
            return _discard_unknown('no_verified_current_request')
        if ref is not None:
            _reference(ref, ref['session_id'], ref['sequence'], snapshot=True)
            if ref['binding'] != binding:
                return _discard_unknown('snapshot_binding_invalid')
        evidence = state['legal_action_space'].get('request_parameters')
        if evidence is None or evidence['profile'] != CURRENT_PROFILE:
            return _discard_unknown('current_discard_profile_not_observed', ref)
        payload = evidence['discard_request']['payload']
        result = _discard_unknown('no_verified_discard_proposals', ref)
        result.update(request_binding=copy.deepcopy(binding), request_type=binding['request_type'],
            profile=CURRENT_PROFILE, validation_scope=CURRENT_SCOPE, offered_member_count=8,
            minimum=payload['min_sel'], maximum=payload['max_sel'])
        for member in payload['offered_object_refs']:
            proposal = {'request_identity': copy.deepcopy(binding),
                'proposed_discard_selection': {'selected_object_refs': [member]}}
            if ref is not None:
                proposal['source_snapshot_ref'] = copy.deepcopy(ref)
            verdict = validate_proposed_choice(state, proposal, source_snapshot_ref=ref)
            if (type(verdict) is not dict or verdict.get('schema_version') != VALIDATION_VERSION or
                    verdict.get('validation_scope') != CURRENT_SCOPE or verdict.get('source_snapshot_ref') != ref or
                    verdict.get('read_only') is not True or any(verdict.get(k) is not False for k in
                    (*EXECUTION, 'all_payment_options_verified', 'complete_costs_verified',
                     'complete_payment_verified', 'mana_payment_verified', 'historical_response_used',
                     'unfiltered_domain_complete_verified', 'quantity_rules_complete_verified', 'rules_effect_verified')) or
                    any(k in verdict and verdict[k] is not False for k in
                        ('target_domain_complete_verified', 'complete_target_legality_verified',
                         'target_selection_legality_verified', 'target_quantity_completeness_verified',
                         'complete_legality_verified', 'server_acceptance_verified', 'payment_completed_verified',
                         'global_restrictions_verified', 'full_action_domain_complete'))):
                return _discard_unknown('choice_validator_contract_mismatch')
            if ref is not None:
                try:
                    _reference(verdict['source_snapshot_ref'], ref['session_id'], ref['sequence'], snapshot=True)
                except (ValueError, TypeError, KeyError):
                    return _discard_unknown('choice_validator_contract_mismatch')
            category = {'verified_known_constraints': 'verified_probes', 'insufficient_evidence': 'unknown_probes',
                'violated_known_constraints': 'contradicted_probes'}.get(verdict['known_constraints'])
            if category is None:
                return _discard_unknown('choice_validator_contract_mismatch')
            result[category] += 1
            if category == 'verified_probes' and len(result['candidates']) < limit:
                result['candidates'].append(proposal)
        count = len(result['candidates'])
        result.update(candidate_total_for_reviewed_constraints=result['verified_probes'], returned_candidates=count,
            omitted_due_to_return_limit=result['verified_probes']-count, truncated=result['verified_probes']>count,
            exhaustive_for_reviewed_constraints=not result['unknown_probes'] and result['verified_probes']==count)
        if count:
            result.update(status='reviewed_constraint_candidates_observed', reason='current_discard_proposals_verified',
                known_constraints='verified_known_constraints')
        _bounded_json(result)
        return result
    except (ValueError, TypeError, KeyError, IndexError, RecursionError, UnicodeError, OverflowError):
        return _discard_unknown('state_or_request_evidence_invalid')


def _reviewed_target_proposals(state, ref, limit):
    """Construct existing proposals and ask the same validator, never solve rules.

    V3 intentionally covers only the two target profiles. Counts describe
    examined probes and original rows separately; a fixed probe budget leaves
    unexamined offers explicitly unknown, never silently verified.
    """
    try:
        from .choice_validation import VERSION as VALIDATION_VERSION, validate_proposed_choice
        from .action_target_menus import CURRENT_PROFILE, CURRENT_SCOPE
        from .semantic_targets import PROFILE as TARGET_PROFILE, CURRENT_SELECTED_SCOPE, literal_selected
        from .decision_consumer import _reference
        _bounded_json(state)
        _state(state, state['binding'])
        binding = state['binding']
        if state['status'] != 'state_and_request_observed' or binding['request_id'] is None:
            return _proposal_unknown('no_verified_current_request')
        if ref is not None:
            _reference(ref, ref['session_id'], ref['sequence'], snapshot=True)
            if ref['binding'] != binding:
                return _proposal_unknown('snapshot_binding_invalid')
        evidence = state['legal_action_space'].get('request_parameters')
        if evidence is None:
            return _proposal_unknown('reviewed_request_parameters_not_observed', ref)
        result = _proposal_unknown('no_verified_target_proposals', ref)
        result.update(request_binding=copy.deepcopy(binding), request_type=binding['request_type'],
                      profile=evidence['profile'])
        probes = []
        row_statuses = None
        if evidence['profile'] == CURRENT_PROFILE:
            result['probe_kind'] = 'target_member_probe'
            validation_scope = CURRENT_SCOPE
            required_false = ('target_domain_complete_verified', 'target_selection_legality_verified',
                'target_set_combinations_enumerated', 'complete_costs_verified', 'complete_payment_verified',
                'target_quantity_verified', 'global_target_legality_verified', 'historical_response_used')
            row_statuses = []
            for row in evidence['rows']:
                menu = row['target_menu']
                row_statuses.append({'list_position': row['list_position'],
                    'source_ability_pair_status': row['ability_binding'],
                    'explicit_public_member_count': len(menu['offered_visible_target_refs']) if menu else None,
                    'known_constraints': 'insufficient_evidence'})
                if menu is None:
                    continue
                for target in menu['offered_visible_target_refs']:
                    # Bound construction too: retain only a count of later
                    # offers beyond the fixed examination budget.
                    if len(probes) < MAX_TARGET_PROBES:
                        probes.append({'request_identity': copy.deepcopy(binding),
                            'list_position': row['list_position'], 'proposed_activate_target_member': {
                                'identifier_refs': copy.deepcopy(row['identifier_refs']),
                                'target_idx': menu['target_idx'], 'object_ref': target}})
            observed = sum(row['explicit_public_member_count'] or 0 for row in row_statuses)
        elif evidence['profile'] == TARGET_PROFILE:
            result['probe_kind'] = 'already_selected_literal_probe'
            validation_scope = CURRENT_SELECTED_SCOPE
            required_false = ('complete_target_legality_verified', 'target_domain_complete_verified',
                'target_quantity_completeness_verified', 'complete_costs_verified', 'complete_payment_verified',
                'mana_payment_verified', 'new_selectable_domain_used', 'target_set_enumeration_performed',
                'historical_response_used')
            request = evidence['targets']
            result['target_quantities'].update(minimum=request['min_targets'], maximum=request['max_targets'],
                selected_count=request['selected_count'], basis='current_request_literals')
            selected = literal_selected(request)
            if selected is None:
                return _proposal_unknown('current_selected_literal_not_observed', ref)
            probes.append({'request_identity': copy.deepcopy(binding), 'proposed_current_selected_target_set': {
                **{key: request[key] for key in ('source_object_ref', 'ability_grp_ref',
                    'targeting_ability_grp_ref', 'target_idx', 'targeting_player')}, 'object_refs': selected}})
            observed = 1
        else:
            return _proposal_unknown('request_profile_not_supported_for_proposal_discovery', ref)
        coverage = result['probe_coverage']
        coverage.update(observed_probes=observed, unexamined=observed-len(probes))
        for proposal in probes:
            if ref is not None:
                proposal['source_snapshot_ref'] = copy.deepcopy(ref)
            verdict = validate_proposed_choice(state, proposal, source_snapshot_ref=ref)
            if (type(verdict) is not dict or verdict.get('schema_version') != VALIDATION_VERSION or
                    verdict.get('validation_scope') != validation_scope or
                    verdict.get('source_snapshot_ref') != ref or verdict.get('read_only') is not True or
                    any(verdict.get(key) is not False for key in (*EXECUTION, *required_false, 'all_payment_options_verified')) or any(
                    key in verdict and verdict[key] is not False for key in ('complete_costs_verified', 'complete_payment_verified',
                        'all_payment_options_verified', 'target_domain_complete_verified',
                        'complete_target_legality_verified', 'target_selection_legality_verified',
                        'target_quantity_completeness_verified', 'mana_payment_verified',
                        'complete_legality_verified', 'server_acceptance_verified'))):
                return _proposal_unknown('choice_validator_contract_mismatch')
            known = verdict['known_constraints']
            category = {'verified_known_constraints': 'verified', 'insufficient_evidence': 'unknown',
                        'violated_known_constraints': 'contradicted'}.get(known)
            if category is None:
                return _proposal_unknown('choice_validator_contract_mismatch')
            coverage['examined'] += 1
            coverage[category] += 1
            if row_statuses is not None:
                row = row_statuses[proposal['list_position']]
                if known == 'verified_known_constraints' or row['known_constraints'] == 'insufficient_evidence':
                    row['known_constraints'] = known
            if known == 'verified_known_constraints':
                result['validation_scope'] = verdict['validation_scope']
                if len(result['candidates']) < limit:
                    result['candidates'].append(proposal)
        if row_statuses is not None:
            verified = sum(r['known_constraints'] == 'verified_known_constraints' for r in row_statuses)
            contradicted = sum(r['known_constraints'] == 'violated_known_constraints' for r in row_statuses)
            result['action_row_coverage'] = {'engine_active_action_rows': len(row_statuses),
                'verified_known_consistent_rows': verified, 'unknown_or_unreviewed_rows': len(row_statuses)-verified-contradicted,
                'contradicted_known_constraint_rows': contradicted, 'row_statuses': row_statuses}
        returned = len(result['candidates'])
        coverage['omitted_due_to_return_limit'] = coverage['verified']-returned
        result.update(candidate_total_for_reviewed_constraints=coverage['verified'] if not coverage['unexamined'] else None,
            returned_candidates=returned, truncated=bool(coverage['unexamined'] or coverage['verified']>returned),
            exhaustive_for_reviewed_constraints=not coverage['unexamined'] and not coverage['unknown'] and coverage['verified']==returned)
        if returned:
            result.update(status='reviewed_constraint_candidates_observed', reason='reviewed_target_proposals_verified',
                          known_constraints='verified_known_constraints')
        _bounded_json(result)
        return result
    except (ValueError, TypeError, KeyError, IndexError, RecursionError, UnicodeError, OverflowError):
        return _proposal_unknown('state_or_request_evidence_invalid')
