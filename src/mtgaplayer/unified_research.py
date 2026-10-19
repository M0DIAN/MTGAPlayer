"""Bounded arbitration of already-current research reports; no policy or state.

The runtime supplies its existing current inventories and independently assessed
reports. This module neither interprets GRE nor turns a report into a candidate.
"""
import copy

from .cast_target_members import _equal
from .decision_consumer import EXECUTION, _bounded_json
from .decision_options import MAX_OPTIONS
from .semantic_samples import _need
from .shadow_decision import POLICY as SHADOW_POLICY
from .land_development import POLICY as LAND_POLICY, SWAMP_POLICY
from .target_effect import POLICY as TARGET_POLICY
from .cast_cardflow import POLICY as CAST_POLICY, validate_current_preference

POLICY = 'unified_research.v1'
V2_POLICY = 'unified_research.v2'
V3_POLICY = 'unified_research.v3'
POLICIES = (POLICY, V2_POLICY, V3_POLICY)
VERSION = 'mtgaplayer.unified-research-decision.v1'
REASONS = frozenset(('research_policy_conflict', 'current_candidate_unverified',
    'current_policy_binding_invalid', 'exact_build_resource_provenance_unverified'))
GLOBAL_FAILURES = frozenset(('current_snapshot_binding_invalid', 'current_snapshot_expired_or_changed',
    'raw_current_binding_unverified', 'raw_state_changed_during_frame', 'owner_context_unavailable',
    'owner_thread_required', 'current_options_not_available_or_binding_invalid',
    'current_view_unavailable', 'frame_report_binding_invalid'))


def _applicable_policy(request_type, *, policy_version=POLICY):
    _need(type(policy_version) is str and policy_version in POLICIES, 'current_policy_binding_invalid')
    return {'GREMessageType_ActionsAvailableReq': LAND_POLICY if policy_version == POLICY else SWAMP_POLICY,
            'GREMessageType_SelectTargetsReq': TARGET_POLICY}.get(request_type)


def _unknown(reason, ref=None, *, policy_version=POLICY):
    _need(type(policy_version) is str and policy_version in POLICIES, 'current_policy_binding_invalid')
    return {'schema_version': VERSION, 'policy_version': policy_version, 'selected_policy': None,
        'selected_policy_version': None, 'status': 'expired', 'reason': reason,
        'request_binding': None, 'source_snapshot_ref': copy.deepcopy(ref),
        'preferred_option_key': None, 'candidate_namespace': None, 'preference_basis': None,
        'abstention_reason': reason, 'evidence_level': None, 'validation_scope': None,
        'contributing_policies': [], 'unresolved_constraints': [],
        'strategic_optimality_verified': False, 'server_acceptance_verified': False,
        'read_only': True, **EXECUTION}


def combine_current_research(options, shadow, research=None, target_evidence=None, *, policy_version=POLICY,
                             cast_research=None):
    """One result from the same frame's reports; conflicting candidates abstain.

    Matching numeric positions across inventories never establishes identity.
    Only identical keys AND full candidates in the same namespace can agree.
    Currentness remains the enclosing runtime/Consumer's responsibility.
    """
    _need(type(options['options']) is list and len(options['options']) <= MAX_OPTIONS,
        'current_candidate_unverified')
    binding, ref = options['request_binding'], options['source_snapshot_ref']
    result = _unknown('insufficient_policy_evidence', ref, policy_version=policy_version)
    result.update(status='abstain', request_binding=copy.deepcopy(binding))
    typ = binding['request_type']
    applicable = _applicable_policy(typ, policy_version=policy_version)
    reports = [(SHADOW_POLICY, shadow)]
    if research is not None:
        _need(applicable is not None, 'current_policy_binding_invalid')
        reports.append((applicable, research))
    if cast_research is not None:
        _need(policy_version == V3_POLICY and typ == 'GREMessageType_ActionsAvailableReq',
            'current_policy_binding_invalid')
        reports.append((CAST_POLICY, cast_research))
    preferences = []
    unresolved = []
    for policy, report in reports:
        _need(type(report) is dict and report['policy_version'] == policy and report['read_only'] is True and
            all(report[k] is False for k in EXECUTION), 'current_policy_binding_invalid')
        _need(report['status'] in ('research_preference','abstain','unsupported','expired'),
            'current_policy_binding_invalid')
        if (report['status'] == 'expired' or report.get('reason') in GLOBAL_FAILURES or
                str(report.get('reason','')).startswith('consumer_')):
            return _unknown('current_policy_binding_invalid', policy_version=policy_version)
        if report['request_binding'] is not None or report['source_snapshot_ref'] is not None:
            _need((_equal(report['request_binding'],binding) and _equal(report['source_snapshot_ref'],ref)) or
                (report['request_binding'] is None and report['status'] != 'research_preference' and
                 report['source_snapshot_ref'] is None), 'current_policy_binding_invalid')
        if report.get('unresolved') is not None:
            _need(type(report['unresolved']) is list and len(report['unresolved']) <= 4096 and
                all(type(v) is str for v in report['unresolved']), 'current_policy_binding_invalid')
            unresolved.extend(report['unresolved'])
        if report['status'] != 'research_preference':
            _need(report.get('preferred_option_key') is None, 'current_candidate_unverified')
            continue
        _need(_equal(report['request_binding'],binding) and _equal(report['source_snapshot_ref'],ref),
            'current_policy_binding_invalid')
        namespace = 'current_decision_options'
        candidates = options['options']
        if policy == TARGET_POLICY:
            namespace = 'current_target_role_proposals'
            _need(type(target_evidence) is dict and target_evidence.get('status') == 'observed' and
                target_evidence.get('complete_current_select_domain_verified') is True and
                target_evidence.get('truncated') is False and
                _equal(target_evidence['current_request_binding'],binding) and
                _equal(target_evidence['source_snapshot_ref'],ref), 'current_candidate_unverified')
            candidates = target_evidence['local_proposals']
            _need(type(candidates) is list and len(candidates) <= MAX_OPTIONS, 'current_candidate_unverified')
        matches = [o for o in candidates if _equal(o['option_key'],report['preferred_option_key'])]
        _need(len(matches) == 1, 'current_candidate_unverified')
        candidate = matches[0]
        _need(_equal(candidate['request_binding'],binding) and _equal(candidate['source_snapshot_ref'],ref) and
            candidate['read_only'] is True and all(candidate[k] is False for k in EXECUTION),
            'current_candidate_unverified')
        if policy == TARGET_POLICY:
            _need(candidate['kind'] == 'reviewed_role_target_set' and
                candidate['local_validation']['status'] == 'verified_known_constraints' and
                candidate['proposal'] is not None, 'current_candidate_unverified')
        elif policy == CAST_POLICY:
            validate_current_preference(options, report, candidate)
        else:
            _need(candidate['research_eligible'] is True, 'current_candidate_unverified')
        if policy == SHADOW_POLICY:
            _need(_equal(report['evidence_level'],candidate['evidence_level']) and
                _equal(report['validation_scope'],candidate['validation_scope']), 'current_candidate_unverified')
        preferences.append((policy, report, namespace, candidate))
    result['unresolved_constraints'] = sorted(set(unresolved))
    if preferences:
        first = preferences[0]
        if any(row[2] != first[2] or not _equal(row[3],first[3]) for row in preferences[1:]):
            result.update(reason='research_policy_conflict',abstention_reason='research_policy_conflict',
                contributing_policies=[row[0] for row in preferences])
        else:
            # All contributors identify one identical current candidate. Keep
            # the specialist's explanation if present; no evidence is promoted.
            policy, report, namespace, candidate = preferences[-1]
            result.update(status='research_preference', reason=report['reason'],
                selected_policy=policy, selected_policy_version=policy,
                preferred_option_key=copy.deepcopy(candidate['option_key']), candidate_namespace=namespace,
                preference_basis=report['preference_basis'], abstention_reason=None,
                evidence_level=report.get('evidence_level',candidate['evidence_level']),
                validation_scope=report.get('validation_scope',candidate['validation_scope']),
                contributing_policies=[row[0] for row in preferences])
    else:
        # An unrelated/unsupported specialist never overwrites a supported
        # baseline abstention. Applicable specialist reasons remain available.
        policy, report = reports[-1]
        if report['status'] == 'unsupported' and shadow['status'] != 'unsupported':
            policy, report = reports[0]
        result.update(status=report['status'], reason=report['reason'], abstention_reason=report['reason'],
            selected_policy=policy, selected_policy_version=policy)
    _bounded_json(result)
    return result
