"""Finite reviewed current-request choice alternatives, never full MTG legality."""
import copy
from itertools import combinations
from math import comb

from .decision_consumer import DecisionConsumer, EXECUTION, _bounded_json, _state

VERSION = 'mtgaplayer.known-choice-candidates.v1'
SCOPE = 'reviewed_current_request_known_constraints_only'
MAX_CANDIDATES = 64


def _unknown(reason, ref=None):
    return {'schema_version': VERSION, 'scope': SCOPE,
        'status': 'insufficient_evidence', 'reason': reason,
        'source_snapshot_ref': copy.deepcopy(ref), 'request_type': None, 'profile': None,
        'candidate_total_for_reviewed_constraints': None, 'returned_candidates': 0,
        'truncated': False, 'exhaustive_for_reviewed_constraints': False, 'candidates': [],
        'full_action_domain_complete': False, 'global_restrictions_verified': False,
        'complete_payment_verified': False, 'complete_legality_verified': False,
        'server_acceptance_verified': False, 'historical_response_used': False,
        'read_only': True, **EXECUTION}


def enumerate_known_candidates(state, *, source_snapshot_ref=None, limit=MAX_CANDIDATES):
    """No game rules beyond existing current PayCosts/SelectTargets validators.

    Does not establish freshness: supplied offline states are research only.
    Live users must call assess_current_known_candidates on the Consumer.
    """
    if type(limit) is not int or not 1 <= limit <= MAX_CANDIDATES:
        raise ValueError('invalid_known_candidate_limit')
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
        request_type, profile = binding['request_type'], evidence['profile']
        proposals = []
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
        else:
            return _unknown('request_profile_not_supported_for_enumeration')
        result = _unknown('additional_rules_and_future_requests_unverified', source_snapshot_ref)
        result.update(status='reviewed_constraint_candidates_observed',
                      request_type=request_type, profile=profile,
                      candidate_total_for_reviewed_constraints=total,
                      returned_candidates=len(proposals), truncated=total>len(proposals),
                      exhaustive_for_reviewed_constraints=total==len(proposals),
                      candidates=proposals)
        return result
    except (ValueError, TypeError, KeyError, IndexError, RecursionError,
            UnicodeError, OverflowError):
        return _unknown('state_or_request_evidence_invalid')


def assess_current_known_candidates(consumer, *, limit=MAX_CANDIDATES):
    """Owner-thread lease/binding check, with no last_valid fallback."""
    if type(limit) is not int or not 1 <= limit <= MAX_CANDIDATES:
        raise ValueError('invalid_known_candidate_limit')
    if not isinstance(consumer, DecisionConsumer):
        return _unknown('requires_current_consumer')
    try:
        view = consumer.current_view()
        if view['consumer_status'] != 'OBSERVING':
            return _unknown('consumer_' + view['consumer_status'].lower())
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
            return _unknown('current_snapshot_binding_invalid')
        result = enumerate_known_candidates(state, source_snapshot_ref=ref, limit=limit)
        after = consumer.current_view()
        if (after['consumer_status'] != 'OBSERVING' or
                after['current_snapshot_ref'] != ref or
                after['new_request_observed'] is not True):
            return _unknown('current_snapshot_expired_or_changed')
        return result
    except (ValueError, TypeError, KeyError, RecursionError, UnicodeError):
        return _unknown('current_view_unavailable')
