"""Opt-in conditional card-flow research, never an all-action ranking or input."""
import copy
import threading

from .cast_target_members import _equal
from .choice_candidates import _assess_current_report
from .choice_continuation import _prompt
from .decision_consumer import DecisionConsumer, EXECUTION, _bounded_json
from .decision_options import VERSION as OPTIONS_VERSION
from .land_development import _phase_evidence
from .raw_log import _id
from .request_parameters import LiteralRefs
from .rules_index import (PreparedRulesIndex, MTGA_CARDFLOW_VERSION, MTGA_CARDFLOW_FORMAT,
    TARGET_EFFECT_SHA256, reviewed_cast_cardflow)
from .rule_context import MAX_REFERENCE_BYTES
from .semantic_activate_targets import _without_highlight
from .semantic_targets import action
from .semantic_samples import _need
from .target_build import current_resource

POLICY = 'cast_cardflow_research.v1'
VERSION = 'mtgaplayer.cast-cardflow-research.v1'
GOAL = 'conditional_card_flow_research'
SCOPE = 'goal_conditioned_heuristic_only'
EVIDENCE = 'version_bound_conditional_effect_goal_heuristic'
REFERENCE_SOURCE = {'schema_version': MTGA_CARDFLOW_VERSION, 'source_format': MTGA_CARDFLOW_FORMAT,
    'source_version': 'Data=2026.64.0.280;GRP=280.1327372',
    'source_sha256': TARGET_EFFECT_SHA256, 'source_version_is_user_supplied': False}
REASONS = frozenset(('unsupported_policy_version', 'request_strategy_unsupported',
    'completed_poll_context_required', 'current_options_not_available_or_binding_invalid',
    'active_inventory_incomplete', 'request_structure_unreviewed', 'active_action_structure_unreviewed',
    'exact_build_resource_provenance_unverified', 'reference_source_unverified',
    'specific_effect_identity_unverified', 'cast_source_identity_unverified',
    'cast_parameters_unreviewed', 'no_reviewed_cardflow_cast', 'multiple_cardflow_casts',
    'land_phase_unverified', 'nonempty_stack_observed', 'cardflow_goal_context_unverified',
    'known_constraint_contradiction_observed', 'conditional_cardflow_goal_heuristic'))
UNKNOWN = ('actual_cast_resolution_unknown', 'trigger_event_unknown', 'trigger_suppression_unknown',
    'draw_replacement_effects_unknown', 'dynamic_card_characteristics_unknown',
    'net_hand_gain_unknown', 'complete_payment_unknown', 'future_request_constraints_unknown',
    'competitor_goal_values_unknown', 'other_goals_not_compared', 'tactical_opportunity_cost_unknown',
    'stack_emptiness_unknown_not_inferred', 'complete_legality_unknown',
    'server_acceptance_unknown', 'response_encoding_unknown', 'strategic_optimality_unverified')
FALSE_CLAIMS = ('effect_triggered_verified', 'net_hand_gain_verified', 'payment_verified',
    'strategic_dominance_verified', 'strategic_optimality_verified', 'server_acceptance_verified')


def _unknown(reason, ref=None):
    expired = (reason.startswith('consumer_') and reason != 'consumer_waiting' or reason in
        ('current_snapshot_binding_invalid', 'current_snapshot_expired_or_changed',
         'raw_current_binding_unverified', 'raw_state_changed_during_frame', 'owner_thread_required'))
    return {'schema_version': VERSION, 'policy_version': POLICY,
        'status': 'expired' if expired else 'abstain', 'reason': reason,
        'request_binding': None, 'source_snapshot_ref': copy.deepcopy(ref),
        'preferred_option_key': None, 'selected_goal': GOAL, 'goal_evidence': None,
        'source_identity': None, 'effect_identity': None, 'conditional_effect_evidence': None,
        'static_reference_source': None, 'cast_action_evidence': None, 'phase_evidence': None,
        'unranked_competitors': [], 'unranked_competitor_count': None,
        'unresolved_competitor_values': [], 'comparison_scope': SCOPE,
        'preference_basis': None, 'abstention_reason': reason, 'evidence_level': None,
        'validation_scope': SCOPE, 'coverage': dict.fromkeys(('active_action_rows',
            'inactive_action_rows', 'cast_offers', 'reviewed_cardflow_casts')),
        'unresolved': list(UNKNOWN), **dict.fromkeys(FALSE_CLAIMS, False),
        'read_only': True, **EXECUTION}


def _inventory(state, ref, message, options):
    """Relate the existing finite projector to MP65's original ordered inventory."""
    _need(options['schema_version'] == OPTIONS_VERSION and options['status'] == 'partial' and
        _equal(options['request_binding'], state['binding']) and _equal(options['source_snapshot_ref'], ref) and
        _equal(options['visible_state'], {k: state[k] for k in ('game', 'visible_objects', 'card_knowledge')}) and
        options['read_only'] is True and all(options[k] is False for k in EXECUTION),
        'current_options_not_available_or_binding_invalid')
    coverage = options['coverage']
    _need(not any(r.get('evidence_level') == 'violated_known_constraints' for r in options['unresolved']),
        'known_constraint_contradiction_observed')
    _need(coverage['truncated'] is False and coverage['omitted_constructed_options'] == 0 and
        all(s['truncated'] is False and s.get('omitted_constructed_options', 0) == 0
            for s in coverage['sources']), 'active_inventory_incomplete')
    _need(type(message) is dict and set(message) == {'type', 'systemSeatIds', 'msgId',
        'gameStateId', 'prompt', 'actionsAvailableReq'}, 'request_structure_unreviewed')
    _prompt(message['prompt'])  # Shape only; no interpretation of prompt values.
    body = message['actionsAvailableReq']
    _need(type(body) is dict and {'actions'} <= body.keys() <= {'actions', 'inactiveActions'} and
        type(body['actions']) is list and 1 <= len(body['actions']) <= 64 and
        type(body.get('inactiveActions', [])) is list and len(body.get('inactiveActions', [])) <= 256 and
        all(type(a) is dict for a in body.get('inactiveActions', [])), 'request_structure_unreviewed')
    rows = body['actions']; engine = [o for o in options['options'] if o['kind'] == 'engine_action']
    _need(coverage['engine_offered_unit'] == 'active_action_row' and
        type(coverage['engine_offered_count']) is int and
        coverage['engine_offered_count'] == len(engine) == len(rows), 'active_inventory_incomplete')
    for pos, (raw, option) in enumerate(zip(rows, engine)):
        _need(type(raw) is dict and type(option['list_position']) is int and option['list_position'] == pos and
            _equal(option['option_key'], {'kind': 'engine_action', 'source': 'decision_advisor', 'source_position': pos}) and
            _equal(option['request_binding'], state['binding']) and _equal(option['source_snapshot_ref'], ref) and
            option['read_only'] is True and all(option[k] is False for k in EXECUTION) and
            option['observation']['engine_action_type'] == raw.get('actionType') and
            option['observation']['unknown_parameter_fields_present'] is False, 'active_action_structure_unreviewed')
        try:
            projected = _without_highlight(raw) if raw.get('targets') else raw
            action(projected, LiteralRefs(), ())
        except (ValueError, KeyError, TypeError):
            raise ValueError('active_action_structure_unreviewed') from None
    return rows, engine, body.get('inactiveActions', [])


def _evaluate(state, ref, consumer, reducer, message, prepared):
    result = _unknown('request_strategy_unsupported', ref)
    result['request_binding'] = copy.deepcopy(state['binding'])
    if state['binding']['request_type'] != 'GREMessageType_ActionsAvailableReq':
        result['status'] = 'unsupported'
        return result
    resource = current_resource(reducer)
    _need(resource is not None, 'exact_build_resource_provenance_unverified')
    options = consumer.current_decision_options()
    rows, engine, inactive = _inventory(state, ref, message, options)
    frozen_options = copy.deepcopy(options)
    casts = [(pos, raw, engine[pos]) for pos, raw in enumerate(rows) if raw['actionType'] == 'ActionType_Cast']
    result['coverage'].update(active_action_rows=len(rows), inactive_action_rows=len(inactive),
        cast_offers=len(casts), reviewed_cardflow_casts=0)
    # Unknown effects of every other offered Card remain unranked. This is not
    # a claim that they cannot draw cards or have lower utility for other goals.
    reviewed = [(pos, raw, opt) for pos, raw, opt in casts if type(raw.get('grpId')) is int and raw['grpId'] == 96626]
    if not reviewed:
        result.update(reason='no_reviewed_cardflow_cast', abstention_reason='no_reviewed_cardflow_cast')
        return result
    _need(isinstance(prepared, PreparedRulesIndex), 'reference_source_unverified')
    metadata, matches = prepared.lookup([96626], max_reference_bytes=MAX_REFERENCE_BYTES)
    _need(_equal({k: metadata[k] for k in REFERENCE_SOURCE}, REFERENCE_SOURCE) and
        metadata['source_sha256'] == resource['catalog_sha256'], 'reference_source_unverified')
    _need(matches[96626]['status'] == 'resolved', 'specific_effect_identity_unverified')
    card = matches[96626]['card']
    try:
        effect = reviewed_cast_cardflow(card)
    except (ValueError, KeyError, TypeError):
        raise ValueError('specific_effect_identity_unverified') from None
    seat = state['binding']['self_seat']; refs = reducer._cast_source_refs()
    admitted = []
    for pos, raw, option in reviewed:
        _need({'actionType','instanceId','grpId','facetId','manaCost'} <= raw.keys() and
            not set(raw)-{'actionType','instanceId','grpId','facetId','manaCost','autoTapSolution','shouldStop','highlight'} and
            _equal(raw['manaCost'], [{'color':['ManaColor_Generic'], 'count':1},
                {'color':['ManaColor_Blue'], 'count':1}]), 'cast_parameters_unreviewed')
        _need(all(_id(raw[k]) and raw[k] > 0 for k in ('instanceId','grpId','facetId')) and
            raw['instanceId'] in refs, 'cast_source_identity_unverified')
        ident = raw['instanceId']; obj = reducer.objects[ident]
        visible = [o for o in state['visible_objects'] if o['instance_id'] == ident]
        _need(len(visible) == 1 and type(visible[0]['card_id']) is int and visible[0]['card_id'] == 96626 and
            visible[0]['zone'] == 'ZoneType_Hand' and
            all(type(visible[0][k]) is int and visible[0][k] == seat for k in ('owner_seat','controller_seat')) and
            obj.get('type') == 'GameObjectType_Card' and type(obj.get('grpId')) is int and obj['grpId'] == 96626 and
            type(obj.get('overlayGrpId')) is int and obj['overlayGrpId'] == 96626 and
            obj.get('cardTypes') == ['CardType_Artifact'] and
            all(type(obj.get(k)) is int and obj[k] == seat for k in ('ownerSeatId','controllerSeatId')) and
            option['observation']['source_card_identity_agreement'] is True and
            type(option['observation']['visible_object_id']) is int and option['observation']['visible_object_id'] == ident,
            'cast_source_identity_unverified')
        abilities = obj.get('uniqueAbilities')
        _need(type(abilities) is list and len(abilities) == 2 and
            all(type(a) is dict and set(a) == {'id','grpId'} and
                all(_id(a[k]) and a[k] > 0 for k in a) for a in abilities) and
            len({a['id'] for a in abilities}) == 2 and
            sorted(a['grpId'] for a in abilities) == [190898,190899], 'specific_effect_identity_unverified')
        admitted.append((pos, raw, option))
    result['coverage']['reviewed_cardflow_casts'] = len(admitted)
    if len(admitted) != 1:
        result.update(reason='multiple_cardflow_casts', abstention_reason='multiple_cardflow_casts')
        return result
    _need(not any(o['zone'] == 'ZoneType_Stack' for o in state['visible_objects']), 'nonempty_stack_observed')
    phase = _phase_evidence(state)
    library = state['game']['hidden_counts'].get(str(seat)+':ZoneType_Library')
    players = state['game']['players']
    _need(type(library) is int and library > 0 and len(players) == 2 and
        {p['seat'] for p in players} == {1,2} and
        all(type(p['life']) is int and p['life'] > 0 for p in players), 'cardflow_goal_context_unverified')
    pos, raw, option = admitted[0]
    competitors = [{'option_key': copy.deepcopy(o['option_key']),
        'action_type': rows[i]['actionType'], 'goal_value': None}
        for i, o in enumerate(engine) if i != pos]
    result.update(status='research_preference', reason='conditional_cardflow_goal_heuristic',
        abstention_reason=None, preferred_option_key=copy.deepcopy(option['option_key']),
        evidence_level=EVIDENCE, preference_basis='research_unique_reviewed_prospective_enters_draw_profile',
        goal_evidence={'goal': GOAL, 'scope': SCOPE, 'reviewed_matching_offers': 1,
            'library_count': library, 'other_action_goals_not_ranked': True},
        source_identity={'list_position': pos, 'instance_id': raw['instanceId'],
            'card_id': 96626, 'facet_id': raw['facetId']},
        effect_identity={'card_id': 96626, 'ability_id': 190898},
        conditional_effect_evidence={'reference': copy.deepcopy(card), 'instruction': effect,
            'scope': 'version_bound_printed_base_trigger_only'},
        static_reference_source=copy.deepcopy(REFERENCE_SOURCE),
        cast_action_evidence=action(raw, LiteralRefs(), ()), phase_evidence=phase,
        unranked_competitors=competitors, unranked_competitor_count=len(competitors),
        unresolved_competitor_values=[{'option_key': copy.deepcopy(c['option_key']), 'utility': None} for c in competitors])
    _need(_equal(options, frozen_options) and
        _equal(options['visible_state'], {k: state[k] for k in ('game','visible_objects','card_knowledge')}),
        'current_options_not_available_or_binding_invalid')
    _bounded_json(result)
    return result


def validate_current_preference(options, report, candidate):
    """Cast-only arbitration permission, never a global research_eligible change."""
    _need(report['schema_version'] == VERSION and report['policy_version'] == POLICY and
        report['status'] == 'research_preference' and report['selected_goal'] == GOAL and
        report['comparison_scope'] == report['validation_scope'] == SCOPE and report['evidence_level'] == EVIDENCE and
        all(report[k] is False for k in (*FALSE_CLAIMS, *EXECUTION)) and
        report['static_reference_source'] == REFERENCE_SOURCE and
        _equal(report['effect_identity'], {'card_id':96626,'ability_id':190898}), 'current_candidate_unverified')
    evidence = report['conditional_effect_evidence']
    _need(_equal(reviewed_cast_cardflow(evidence['reference']), evidence['instruction']), 'current_candidate_unverified')
    binding = options['request_binding']; ident = report['source_identity']
    goal = report['goal_evidence']; library = options['visible_state']['game']['hidden_counts'].get(str(binding['self_seat'])+':ZoneType_Library')
    _need(report['reason'] == 'conditional_cardflow_goal_heuristic' and
        report['preference_basis'] == 'research_unique_reviewed_prospective_enters_draw_profile' and
        _equal(goal, {'goal':GOAL,'scope':SCOPE,'reviewed_matching_offers':1,
            'library_count':library,'other_action_goals_not_ranked':True}) and
        type(library) is int and library > 0 and
        _equal(report['phase_evidence'], _phase_evidence({'binding':binding,**options['visible_state']})),
        'current_candidate_unverified')
    _need(binding['request_type'] == 'GREMessageType_ActionsAvailableReq' and
        _equal(report['request_binding'], binding) and _equal(report['source_snapshot_ref'], options['source_snapshot_ref']) and
        candidate['kind'] == 'engine_action' and candidate['observation']['engine_action_type'] == 'ActionType_Cast' and
        candidate['observation']['source_card_identity_agreement'] is True and
        candidate['observation']['visible_object_id'] == ident['instance_id'] and
        type(ident['list_position']) is int and ident['list_position'] == candidate['list_position'] and
        type(ident['facet_id']) is int and ident['facet_id'] > 0 and ident['card_id'] == 96626,
        'current_candidate_unverified')
    visible = [o for o in options['visible_state']['visible_objects'] if o['instance_id'] == ident['instance_id']]
    _need(len(visible) == 1 and visible[0]['card_id'] == 96626 and visible[0]['zone'] == 'ZoneType_Hand' and
        visible[0]['owner_seat'] == visible[0]['controller_seat'] == binding['self_seat'], 'current_candidate_unverified')
    from .semantic_cast import check_action
    projected = report['cast_action_evidence']
    check_action(projected, target_actions=True)
    _need(projected['action_type'] == 'ActionType_Cast' and
        _equal(projected['identifier_refs'], {'instanceId':ident['instance_id'], 'grpId':96626,'facetId':ident['facet_id']}) and
        not projected['observed_empty_parameters'] and
        set(projected['parameters']) <= {'manaCost','autoTapSolution'} and
        _equal(projected['parameters']['manaCost'], [{'color':['ManaColor_Generic'],'count':1},
            {'color':['ManaColor_Blue'],'count':1}]), 'current_candidate_unverified')
    rows = [o for o in options['options'] if o['kind'] == 'engine_action']
    _need(options['coverage']['truncated'] is False and options['coverage']['omitted_constructed_options'] == 0 and
        len(rows) == options['coverage']['engine_offered_count'] == report['coverage']['active_action_rows'] and
        report['coverage']['reviewed_cardflow_casts'] == 1 and
        report['unranked_competitor_count'] == len(rows)-1 and
        _equal(report['unranked_competitors'], [{'option_key':o['option_key'],
            'action_type':o['observation']['engine_action_type'], 'goal_value':None}
            for o in rows if not _equal(o['option_key'], candidate['option_key'])]) and
        _equal(report['unresolved_competitor_values'], [{'option_key':o['option_key'],'utility':None}
            for o in rows if not _equal(o['option_key'],candidate['option_key'])]), 'current_candidate_unverified')


def assess_current_cast_cardflow(consumer, reducer, message, prepared_rules, *, policy_version=POLICY,
                                completed_stamp=None):
    if policy_version != POLICY:
        result = _unknown('unsupported_policy_version'); result.update(status='unsupported', policy_version='unsupported')
        return result
    if completed_stamp is None:
        return _unknown('completed_poll_context_required')
    if not isinstance(consumer, DecisionConsumer):
        return _unknown('requires_current_consumer')
    if getattr(consumer, '_owner_thread_id', None) != threading.get_ident():
        return _unknown('owner_thread_required')
    def evaluate(state, *, source_snapshot_ref):
        try:
            from .shadow_runtime import _stamp
            def relevant_raw():
                # The shared stamp stays unchanged for all old policies. These
                # additional fields are used only by this opt-in policy.
                return copy.deepcopy((reducer.turn, [(o['instance_id'],
                    reducer.objects.get(o['instance_id'], {}).get('overlayGrpId'),
                    reducer.objects.get(o['instance_id'], {}).get('cardTypes')) for o in state['visible_objects']]))
            stamp = _stamp(reducer, message, state)
            extra = relevant_raw()
            _need(_equal(stamp, completed_stamp), 'raw_state_changed_during_frame')
            result = _evaluate(state, source_snapshot_ref, consumer, reducer, message, prepared_rules)
            _need(_equal(stamp, _stamp(reducer, message, state)) and _equal(extra, relevant_raw()),
                'raw_state_changed_during_frame')
            return result
        except (ValueError, TypeError, KeyError, IndexError, RecursionError, UnicodeError, OverflowError) as exc:
            reason = str(exc)
            return _unknown(reason if reason in REASONS or reason in
                ('raw_current_binding_unverified', 'raw_state_changed_during_frame', 'owner_context_unavailable')
                else 'current_options_not_available_or_binding_invalid')
    return _assess_current_report(consumer, evaluate, _unknown)
