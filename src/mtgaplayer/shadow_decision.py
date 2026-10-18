"""Deterministic current research preferences; no response or input authority."""
import copy

from .choice_candidates import _assess_current_report
from .decision_advisor import assess_current_decision, SIMPLE_TYPE_POLICY
from .decision_consumer import DecisionConsumer, EXECUTION, _bounded_json
from .decision_options import VERSION as OPTIONS_VERSION, UNKNOWN

VERSION = 'mtgaplayer.shadow-decision.v1'
POLICY = 'deterministic_shadow.v1'
UNRESOLVED = (*UNKNOWN, 'strategic_utility_unknown', 'effects_and_tactics_unverified',
              'optimality_unverified')


def _withdraw(reason, ref=None):
    expired = (reason.startswith('consumer_') and reason != 'consumer_waiting' or
               reason in ('current_snapshot_binding_invalid', 'current_snapshot_expired_or_changed'))
    return {'schema_version': VERSION, 'policy_version': POLICY,
        'status': 'expired' if expired else 'abstain', 'reason': reason,
        'request_binding': None, 'source_snapshot_ref': copy.deepcopy(ref),
        'preferred_option_key': None, 'preference_basis': None,
        'evidence_level': None, 'validation_scope': None, 'advisor_policy': None,
        'candidate_coverage': None, 'source_unresolved': [],
        'unresolved': list(UNRESOLVED), 'read_only': True, **EXECUTION}


def _prefer(result, option, basis):
    result.update(status='research_preference', reason=basis, preference_basis=basis,
        preferred_option_key=copy.deepcopy(option['option_key']),
        evidence_level=option['evidence_level'], validation_scope=option['validation_scope'])
    result['unresolved'] = sorted(set((*result['unresolved'], *option['unresolved'])))
    return result


def _decide(options, advice=None):
    """Interpret existing evidence, never select by order, ID or evidence rank."""
    result = _withdraw('insufficient_policy_evidence')
    result.update(request_binding=copy.deepcopy(options['request_binding']),
        source_snapshot_ref=copy.deepcopy(options['source_snapshot_ref']),
        candidate_coverage=copy.deepcopy(options['coverage']),
        source_unresolved=copy.deepcopy(options['unresolved']))
    coverage = options['coverage']; rows = options['options']
    if (coverage['truncated'] is not False or coverage['omitted_constructed_options'] != 0 or
            any(s['truncated'] is not False or s['omitted_constructed_options'] != 0
                for s in coverage['sources'])):
        result['reason'] = 'candidate_coverage_truncated_or_omitted'
        return result
    if any(u['evidence_level'] == 'violated_known_constraints' for u in options['unresolved']):
        result['reason'] = 'known_constraint_contradiction_observed'
        return result
    request = options['request_binding']['request_type']
    if request == 'GREMessageType_ActionsAvailableReq':
        result['advisor_policy'] = SIMPLE_TYPE_POLICY
        if (advice is None or advice['source_snapshot_ref'] != options['source_snapshot_ref'] or
                advice['request_identity'] != options['request_binding']):
            return _withdraw('advisor_options_binding_mismatch')
        result['unresolved'] = sorted(set((*result['unresolved'], *advice['unresolved'])))
        if advice['assessment_status'] != 'research_preference':
            result['reason'] = advice['abstention_reason']
            return result
        key = advice['preferred_candidate']
        matches = [o for o in rows if o['kind'] == 'engine_action' and
            o['list_position'] == key['list_position'] and o['research_eligible'] is True]
        if (len(matches) != 1 or key['request_identity'] != options['request_binding'] or
                coverage['engine_offered_unit'] != 'active_action_row' or
                coverage['engine_offered_count'] != advice['candidate_coverage']['offered_count'] or
                len(rows) != coverage['engine_offered_count']):
            result['reason'] = 'advisor_preference_not_in_complete_option_inventory'
            return result
        return _prefer(result, matches[0], advice['preference_basis'])
    if request == 'GREMessageType_SelectTargetsReq':
        # Only a complete final-set proposal can use the uniqueness rule.
        # Parent probes and current-selected literals cannot stand in for it.
        if len(rows) != 1:
            result['reason'] = 'multiple_or_unresolved_target_choices'
            return result
        option = rows[0]; sources = coverage['sources']
        if option['kind'] != 'final_target_set':
            result['reason'] = 'selected_literal_or_probe_is_not_a_final_proposal'
            return result
        if (option['evidence_level'] != 'known_constraints_verified' or
                option['research_eligible'] is not True or option['proposal'] is None or
                len(sources) != 1 or sources[0]['source'] != 'known_candidates_v2' or
                sources[0]['coverage'].get('candidate_total_for_reviewed_constraints') != 1 or
                sources[0]['coverage'].get('returned_candidates') != 1):
            result['reason'] = 'unique_reviewed_final_proposal_not_established'
            return result
        return _prefer(result, option, 'unique_complete_proposal_for_reviewed_request_constraints')
    from .combat_frontier import ATTACK, BLOCK
    if request in ('GREMessageType_SelectNReq', ATTACK, BLOCK):
        result['reason'] = 'combination_or_tactical_basis_unverified'
    else:
        result.update(status='unsupported', reason='request_strategy_unsupported')
    return result


def assess_current_shadow_decision(consumer, *, policy_version=POLICY):
    """One owner flow through MP65, existing Advisor and a final ref/lease gate.

    No shadow-result cache or retained preference. A new call must establish
    currentness again; MP65's data cache never acts as currentness authority.
    """
    if policy_version != POLICY:
        result = _withdraw('unsupported_policy_version')
        result.update(status='unsupported', policy_version='unsupported')
        return result
    if not isinstance(consumer, DecisionConsumer):
        return _withdraw('requires_current_consumer')
    def evaluate(state, *, source_snapshot_ref):
        options = consumer.current_decision_options()
        if (options['schema_version'] != OPTIONS_VERSION or
                options['source_snapshot_ref'] != source_snapshot_ref or
                options['request_binding'] != state['binding'] or
                options['status'] not in ('partial', 'unsupported') or options['read_only'] is not True or
                any(options[k] is not False for k in EXECUTION) or any(
                    o['request_binding'] != state['binding'] or
                    o['source_snapshot_ref'] != source_snapshot_ref or
                    o['read_only'] is not True or any(o[k] is not False for k in EXECUTION)
                    for o in options['options'])):
            return _withdraw('current_options_not_available_or_binding_invalid')
        advice = (assess_current_decision(consumer, policy_version=SIMPLE_TYPE_POLICY)
            if state['binding']['request_type'] == 'GREMessageType_ActionsAvailableReq' else None)
        result = _decide(options, advice)
        _bounded_json(result)
        return result
    return _assess_current_report(consumer, evaluate, _withdraw)
