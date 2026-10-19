"""One version-bound base-damage target heuristic; no effective-damage solver."""
import copy
import threading

from .choice_candidates import _assess_current_report
from .cast_target_members import _equal
from .current_target_request import ROLE_VERSION, _role_identity, _players_verified
from .decision_consumer import DecisionConsumer, EXECUTION, _bounded_json
from .decision_options import VERSION as OPTIONS_VERSION
from .rules_index import (PreparedRulesIndex, MTGA_TARGET_EFFECT_VERSION, MTGA_TARGET_EFFECT_FORMAT,
    TARGET_EFFECT_SHA256, reviewed_target_effect)
from .rule_context import MAX_REFERENCE_BYTES
from .semantic_samples import _need
from .target_build import current_resource

POLICY = 'target_effect_research.v1'
VERSION = 'mtgaplayer.target-effect-research.v1'
REFERENCE_SOURCE = {'schema_version': MTGA_TARGET_EFFECT_VERSION, 'source_format': MTGA_TARGET_EFFECT_FORMAT,
    'source_version': 'Data=2026.64.0.280;GRP=280.1327372', 'source_sha256': TARGET_EFFECT_SHA256,
    'source_version_is_user_supplied': False}
REASONS = frozenset(('unsupported_policy_version', 'completed_poll_context_required',
    'request_strategy_unsupported', 'current_options_not_available_or_binding_invalid',
    'exact_build_resource_provenance_unverified', 'request_source_not_reviewed_ability',
    'current_source_identity_unverified', 'complete_current_target_domain_unverified',
    'current_selected_literal_not_complete_domain', 'reference_source_unverified',
    'specific_effect_identity_unverified', 'current_parent_ability_disagrees',
    'target_value_comparison_unreviewed', 'current_player_context_unverified',
    'indistinguishable_verified_utilities', 'verified_opponent_base_damage_heuristic'))
UNKNOWN = ('actual_damage_unknown', 'damage_prevention_unknown', 'replacement_effects_unknown',
    'dynamic_damage_modifications_unknown', 'tactical_opportunity_cost_unknown',
    'strategic_optimality_unverified', 'complete_legality_unknown', 'payment_unknown',
    'prompt_routing_unknown', 'server_acceptance_unknown', 'response_encoding_unknown')
_SOURCE_FIELDS = {'instanceId','grpId','type','zoneId','parentId','objectSourceGrpId',
    'ownerSeatId','controllerSeatId','visibility'}


def _unknown(reason, ref=None):
    expired = (reason.startswith('consumer_') and reason != 'consumer_waiting' or reason in
        ('current_snapshot_binding_invalid','current_snapshot_expired_or_changed',
         'raw_current_binding_unverified','raw_state_changed_during_frame'))
    return {'schema_version': VERSION, 'policy_version': POLICY, 'status': 'expired' if expired else 'abstain',
        'reason': reason, 'request_binding': None, 'source_snapshot_ref': copy.deepcopy(ref),
        'effect_evidence': None, 'effect_source': None, 'effect_semantic_scope': None,
        'reviewed_target_candidates': [], 'candidate_utility_evidence': [],
        'preferred_option_key': None, 'preference_basis': None, 'abstention_reason': reason,
        'coverage': dict.fromkeys(('reviewed_target_members','local_proposals','verified_player_targets',
            'verified_public_object_targets','effect_identified')),
        'unknown': list(UNKNOWN), 'unresolved': list(UNKNOWN), 'strategic_optimality_verified': False,
        'payment_verified': False, 'server_acceptance_verified': False, 'read_only': True, **EXECUTION}


def _uint(value):
    return type(value) is int and 0 < value <= 2**32-1


def _evaluate(state, ref, consumer, reducer, message, prepared):
    result = _unknown('request_strategy_unsupported', ref)
    result['request_binding'] = copy.deepcopy(state['binding'])
    if state['binding']['request_type'] != 'GREMessageType_SelectTargetsReq':
        result['status'] = 'unsupported'
        return result
    resource = current_resource(reducer)
    _need(resource is not None, 'exact_build_resource_provenance_unverified')
    options = consumer.current_decision_options(current_target_context=(reducer,message))
    # MP84 intentionally leaves these role proposals outside MP65's default
    # inventory, which can therefore remain unsupported. Only its explicit,
    # independently checked sidecar below supplies this policy's candidates.
    _need(options['schema_version'] == OPTIONS_VERSION and options['status'] in ('partial','unsupported') and
        _equal(options['request_binding'],state['binding']) and _equal(options['source_snapshot_ref'],ref) and
        options['read_only'] is True and all(options[k] is False for k in EXECUTION),
        'current_options_not_available_or_binding_invalid')
    coverage = options['coverage']
    _need(coverage['truncated'] is False and coverage['omitted_constructed_options'] == 0 and
        all(row['truncated'] is False and row.get('omitted_constructed_options',0) == 0
            for row in coverage['sources']), 'complete_current_target_domain_unverified')
    body = message['selectTargetsReq']; source_id = body['sourceId']
    visible = [o for o in state['visible_objects'] if o['instance_id'] == source_id]
    _need(len(visible) == 1, 'current_source_identity_unverified')
    source = reducer.objects[source_id]
    if source.get('type') != 'GameObjectType_Ability':
        result.update(status='unsupported',reason='request_source_not_reviewed_ability',
            abstention_reason='request_source_not_reviewed_ability')
        return result
    evidence = options['current_target_evidence']
    _need(evidence['schema_version'] == ROLE_VERSION and evidence['status'] == 'observed' and
        _equal(evidence['current_request_binding'],state['binding']) and _equal(evidence['source_snapshot_ref'],ref),
        'complete_current_target_domain_unverified')
    if evidence['current_selected_literal'] is not None:
        result.update(reason='current_selected_literal_not_complete_domain',
            abstention_reason='current_selected_literal_not_complete_domain')
        return result
    constraints = evidence['target_constraints']; members = evidence['current_offered_members']
    _need(evidence['complete_current_select_domain_verified'] is True and evidence['truncated'] is False and
        type(members) is list and bool(members) and evidence['unresolved_memberships'] == 0 and
        evidence['returned_proposals'] == evidence['candidate_total_for_reviewed_constraints'] == len(members) and
        len(evidence['local_proposals']) == len(members) and constraints['selected_count'] is None and
        all(type(constraints[k]) is int and constraints[k] == 1 for k in ('target_idx','min_targets','max_targets')),
        'complete_current_target_domain_unverified')
    _need(set(source) == _SOURCE_FIELDS and all(_uint(source[k]) for k in
        ('instanceId','grpId','zoneId','parentId','objectSourceGrpId','ownerSeatId','controllerSeatId')) and
        source['instanceId'] == source_id and source['visibility'] == 'Visibility_Public' and
        source['ownerSeatId'] == source['controllerSeatId'] == state['binding']['self_seat'] and
        source['grpId'] == constraints['ability_grp_ref'] == constraints['targeting_ability_grp_ref'] and
        constraints['source_object_ref'] == source_id and
        constraints['targeting_player'] == state['binding']['self_seat'], 'current_source_identity_unverified')
    _role_identity(reducer,source_id,('GameObjectType_Ability',),'ZoneType_Stack')
    _need(isinstance(prepared,PreparedRulesIndex),'reference_source_unverified')
    metadata, matches = prepared.lookup([source['objectSourceGrpId']],max_reference_bytes=MAX_REFERENCE_BYTES)
    _need(_equal({k:metadata[k] for k in REFERENCE_SOURCE},REFERENCE_SOURCE) and
        metadata['source_sha256'] == resource['catalog_sha256'], 'reference_source_unverified')
    match = matches[source['objectSourceGrpId']]
    _need(match['status'] == 'resolved', 'specific_effect_identity_unverified')
    try:
        effect = reviewed_target_effect(match['card'],source['grpId'])
    except (ValueError,KeyError,TypeError):
        raise ValueError('specific_effect_identity_unverified') from None
    parent = [o for o in state['visible_objects'] if o['instance_id'] == source['parentId']]
    _need(len(parent) <= 1, 'current_parent_ability_disagrees')
    parent_verified = None
    if parent:
        # Inspect only an already-public parent, never a hidden departed token.
        raw = reducer.objects[source['parentId']]
        _role_identity(reducer,source['parentId'],('GameObjectType_Card','GameObjectType_Token'),'ZoneType_Battlefield')
        abilities = raw.get('uniqueAbilities')
        _need(type(raw.get('grpId')) is int and raw['grpId'] == source['objectSourceGrpId'] and
            type(abilities) is list and 1 <= len(abilities) <= 64 and all(type(a) is dict and
                set(a) == {'id','grpId'} and _uint(a['id']) and _uint(a['grpId']) for a in abilities) and
            len({a['id'] for a in abilities}) == len(abilities) and
            sum(a['grpId'] == source['grpId'] for a in abilities) == 1, 'current_parent_ability_disagrees')
        parent_verified = True
    proposals = evidence['local_proposals']
    result.update(effect_source={'resource_provenance':resource,'static_reference_source':
            {k:copy.deepcopy(metadata[k]) for k in REFERENCE_SOURCE}},
        effect_evidence={'source_object_ref':source_id,'source_kind':'GameObjectType_Ability',
            'ability_grp_ref':source['grpId'],'source_catalog_id':source['objectSourceGrpId'],
            'source_catalog_namespace':'public_ability_objectSourceGrpId',
            'visible_parent_crosscheck':parent_verified,'base_effect_instruction':effect,
            'actual_damage_verified':False},
        effect_semantic_scope='version_bound_specific_ability_fixed_BASE_damage_instruction_only',
        reviewed_target_candidates=copy.deepcopy(proposals),
        coverage={'reviewed_target_members':len(members),'local_proposals':len(proposals),
            'verified_player_targets':evidence['verified_player_memberships'],
            'verified_public_object_targets':evidence['verified_public_object_memberships'],'effect_identified':1})
    # Preserve the full reviewed domain. Objects are never discarded to create
    # an artificial two-player comparison.
    if len(members) != 2 or any(m['target_referent_kind'] != 'verified_player' for m in members):
        result.update(reason='target_value_comparison_unreviewed',abstention_reason='target_value_comparison_unreviewed')
        return result
    seat = state['binding']['self_seat']
    _need(type(seat) is int and seat in (1,2) and _players_verified(reducer) and
        {m['player_seat'] for m in members} == {1,2} and
        all(type(p.get('lifeTotal')) is int and -2**31 <= p['lifeTotal'] < 2**31 and
            _uint(p.get('teamId')) for p in reducer.players.values()) and
        len({p['teamId'] for p in reducer.players.values()}) == 2,
        'current_player_context_unverified')
    _need(_equal(sorted(state['game']['players'],key=lambda p:p['seat']),
        [{'seat':s,'life':reducer.players[s]['lifeTotal']} for s in (1,2)]), 'current_player_context_unverified')
    utilities = []
    for proposal in proposals:
        _need(_equal(proposal['request_binding'],state['binding']) and _equal(proposal['source_snapshot_ref'],ref) and
            proposal['local_validation']['status'] == 'verified_known_constraints' and
            all(proposal[k] is False for k in EXECUTION), 'complete_current_target_domain_unverified')
        chosen = proposal['proposal']['proposed_current_target_referent_set']['target_referents']
        _need(type(chosen) is list and len(chosen) == 1 and chosen[0] in members and
            chosen[0]['namespace'] == 'version_verified_player_instance', 'complete_current_target_domain_unverified')
        target = chosen[0]['player_seat']; opponent = target != seat
        utilities.append({'option_key':copy.deepcopy(proposal['option_key']),
            'target_referent':copy.deepcopy(chosen[0]), 'affiliation':'opponent' if opponent else 'self',
            'current_life':reducer.players[target]['lifeTotal'],'base_damage':effect['base_damage'],
            'utility':effect['base_damage'] if opponent else -effect['base_damage'],
            'basis':'prefer_base_damage_toward_opponent_over_self_only', 'actual_damage_predicted':False})
    result['candidate_utility_evidence'] = utilities
    maximum = max(row['utility'] for row in utilities)
    preferred = [row for row in utilities if row['utility'] == maximum]
    if len(preferred) != 1:
        result.update(reason='indistinguishable_verified_utilities',abstention_reason='indistinguishable_verified_utilities')
        return result
    result.update(status='research_preference',reason='verified_opponent_base_damage_heuristic',
        preferred_option_key=copy.deepcopy(preferred[0]['option_key']),
        preference_basis='prefer_base_damage_toward_opponent_over_self_only',abstention_reason=None)
    _bounded_json(result)
    return result


def assess_current_target_effect(consumer,reducer,message,prepared_rules,*,policy_version=POLICY,completed_stamp=None):
    """Owner supplied current request only, using the original completed poll."""
    if policy_version != POLICY:
        result=_unknown('unsupported_policy_version');result.update(status='unsupported',policy_version='unsupported')
        return result
    if completed_stamp is None:return _unknown('completed_poll_context_required')
    if not isinstance(consumer,DecisionConsumer):return _unknown('requires_current_consumer')
    if getattr(consumer,'_owner_thread_id',None) != threading.get_ident():return _unknown('owner_thread_required')
    def evaluate(state,*,source_snapshot_ref):
        try:
            from .shadow_runtime import _stamp
            stamp=_stamp(reducer,message,state)
            _need(_equal(stamp,completed_stamp),'raw_state_changed_during_frame')
            result=_evaluate(state,source_snapshot_ref,consumer,reducer,message,prepared_rules)
            _need(_equal(stamp,_stamp(reducer,message,state)),'raw_state_changed_during_frame')
            return result
        except (ValueError,TypeError,KeyError,IndexError,RecursionError,UnicodeError,OverflowError) as exc:
            reason=str(exc)
            return _unknown(reason if reason in REASONS or reason in
                ('raw_current_binding_unverified','raw_state_changed_during_frame','owner_context_unavailable')
                else 'current_options_not_available_or_binding_invalid')
    return _assess_current_report(consumer,evaluate,_unknown)
