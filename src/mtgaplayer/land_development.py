"""Explicit, finite land-development research; no response or input authority."""
import copy
import threading

from .choice_candidates import _assess_current_report
from .choice_continuation import _prompt
from .decision_consumer import DecisionConsumer, EXECUTION, _bounded_json
from .decision_options import UNKNOWN, VERSION as OPTIONS_VERSION
from .request_parameters import LiteralRefs
from .rule_context import build_static_rule_context, MAX_REFERENCE_BYTES
from .rules_index import PreparedRulesIndex, MTGA_LAND_VERSION, MTGA_LAND_FORMAT
from .semantic_samples import _need
from .semantic_targets import action
from .semantic_activate_targets import _without_highlight
from .raw_log import _id
from .cast_target_members import _equal

POLICY = 'land_development_research.v1'
SWAMP_POLICY = 'land_development_research.v2'
VERSION = 'mtgaplayer.land-development-research.v1'
SWAMP_VERSION = 'mtgaplayer.land-development-research.v2'
REFERENCE_SOURCE = {'schema_version': MTGA_LAND_VERSION, 'source_format': MTGA_LAND_FORMAT,
    'source_version': 'Data=2026.64.0.280;GRP=280.1327372',
    'source_sha256': '1be0105411ad989ca60e233f1341eaaa9276e3a679c89f1ef6f07e07ede10d25',
    'source_version_is_user_supplied': False}
REASONS = frozenset(('unsupported_policy_version', 'request_strategy_unsupported',
    'completed_poll_context_required',
    'current_options_not_available_or_binding_invalid', 'active_inventory_incomplete',
    'active_action_structure_unreviewed', 'request_structure_unreviewed', 'no_play_offered',
    'multiple_play_competitors', 'play_source_identity_unverified', 'reference_source_unverified',
    'static_land_identity_unverified', 'ordinary_land_profile_unverified', 'land_phase_unverified',
    'nonempty_stack_observed', 'verified_land_development_heuristic'))
SWAMP_REASONS = REASONS | {'exact_build_resource_provenance_unverified'}
UNRESOLVED = (*UNKNOWN, 'dynamic_land_restrictions_unknown', 'land_drop_limit_unverified',
    'other_actions_tactical_value_not_compared', 'strategic_optimality_unverified',
    'prompt_semantics_and_general_routing_unknown', 'step_unknown_not_defaulted',
    'dataset_freshness_and_current_dynamic_characteristics_unverified',
    'empty_explicit_ability_list_does_not_exclude_intrinsic_mana_abilities')


def _unknown(reason, ref=None):
    expired = (reason.startswith('consumer_') and reason != 'consumer_waiting' or
        reason in ('current_snapshot_binding_invalid', 'current_snapshot_expired_or_changed',
                   'raw_current_binding_unverified', 'raw_state_changed_during_frame'))
    return {'schema_version': VERSION, 'policy_version': POLICY,
        'status': 'expired' if expired else 'abstain', 'reason': reason,
        'request_binding': None, 'source_snapshot_ref': copy.deepcopy(ref),
        'preferred_option_key': None, 'preference_basis': None, 'source_identity': None,
        'static_reference_source': None, 'phase_evidence': None,
        'coverage': dict.fromkeys(('active_action_rows', 'play_offers', 'verified_play_sources',
                                  'verified_static_land_candidates', 'ordinary_profile_candidates')),
        'unresolved': list(UNRESOLVED), 'strategic_optimality_verified': False,
        'payment_verified': False, 'read_only': True, **EXECUTION}


def _ordinary_basic(card, subtype, label, loc_id, frame):
    """The two separately reviewed literal basic-land profiles.

    These literal metadata checks do not choose a current face or prove that
    empty explicit abilities mean no intrinsic abilities or dynamic effects.
    """
    profile = card['profile']
    return (card['type_line'] == 'Basic Land' and
        _equal(card['card_types'], [{'value': 5, 'loc_id': 11, 'label': 'Land'}]) and
        _equal(card['supertypes'], [{'value': 1, 'loc_id': 2, 'label': 'Basic'}]) and
        _equal(card['subtypes'], [{'value': subtype, 'loc_id': loc_id, 'label': label}]) and
        profile['Types'] == '5' and profile['Supertypes'] == '1' and profile['Subtypes'] == str(subtype) and
        type(profile['TypeTextId']) is int and profile['TypeTextId'] == 261494 and
        type(profile['SubtypeTextId']) is int and profile['SubtypeTextId'] == loc_id and
        profile['RawFrameDetail'] == frame and
        type(profile['LinkedFaceType']) is int and profile['LinkedFaceType'] == 0 and
        type(profile['IsPrimaryCard']) is int and profile['IsPrimaryCard'] == 1 and
        all(type(profile[key]) is int and profile[key] == 0 for key in
            ('IsToken', 'IsDigitalOnly', 'IsRebalanced', 'RebalancedCardGrpId', 'DefunctRebalancedCardGrpId')) and
        all(type(profile[key]) is str and profile[key] == '' for key in
            ('LinkedFaceGrpIds', 'LinkedAbilityTemplateCardGrpIds', 'OldSchoolManaText',
             'AdditionalFrameDetails', 'ExtraFrameDetails', 'TextChangeData', 'AbilityIds', 'HiddenAbilityIds')) and
        card['reverse_face_link_observed'] is False and card['current_face'] is None and
        card['effective_in_game'] is False and card['rules_verified'] is False)


def _ordinary(card):
    # The original policy remains restricted to its exact Island profile.
    return _ordinary_basic(card, 43, 'Island', 652, 'U')


def _ordinary_swamp(card):
    return _ordinary_basic(card, 69, 'Swamp', 653, '')


def _phase_evidence(state):
    turn = state['game']['turn']; seat = state['binding']['self_seat']
    _need(type(seat) is int and seat in (1, 2) and type(turn.get('turnNumber')) is int and
        0 < turn['turnNumber'] <= 2**53-1 and turn.get('phase') == 'Phase_Main1' and turn.get('step') is None and
        all(type(turn.get(key)) is int and turn[key] == seat for key in ('activePlayer', 'decisionPlayer', 'priorityPlayer')),
        'land_phase_unverified')
    stack = state['game']['stack']
    _need(stack['availability'] in ('unknown', 'confirmed_empty'), 'nonempty_stack_observed')
    return {**copy.deepcopy(turn), 'stack_availability': stack['availability']}


def _swamp_unknown(reason, ref=None):
    result = _unknown(reason, ref)
    result.update(schema_version=SWAMP_VERSION, policy_version=SWAMP_POLICY, land_profile_evidence=None)
    return result


def _swamp_extension(options, reviewed, prepared):
    """Extend this invocation's v1 source/structure audit, not a saved result.

    Production calls this only inside the existing current Consumer/raw stamp
    guard, after _evaluate. Offline research may use a frozen v1/options pair;
    that computation establishes no live request or lease authority.
    """
    result = copy.deepcopy(reviewed)
    result.update(schema_version=SWAMP_VERSION, policy_version=SWAMP_POLICY, land_profile_evidence=None)
    if reviewed['status'] != 'abstain' or reviewed['reason'] not in (
            'static_land_identity_unverified', 'ordinary_land_profile_unverified'):
        return result
    binding = options['request_binding']; ref = options['source_snapshot_ref']
    _need(options['schema_version'] == OPTIONS_VERSION and options['status'] == 'partial' and
        binding['request_type'] == 'GREMessageType_ActionsAvailableReq' and
        _equal(reviewed['request_binding'], binding) and _equal(reviewed['source_snapshot_ref'], ref),
        'current_options_not_available_or_binding_invalid')
    coverage = options['coverage']
    rows = [row for row in options['options'] if row['kind'] == 'engine_action']
    plays = [row for row in rows if row['observation']['engine_action_type'] == 'ActionType_Play']
    _need(coverage['truncated'] is False and coverage['omitted_constructed_options'] == 0 and
        all(source['truncated'] is False and source.get('omitted_constructed_options', 0) == 0
            for source in coverage['sources']) and
        reviewed['coverage']['active_action_rows'] == coverage['engine_offered_count'] == len(rows) and
        reviewed['coverage']['play_offers'] == reviewed['coverage']['verified_play_sources'] == len(plays) == 1,
        'active_inventory_incomplete')
    option = plays[0]; observation = option['observation']; ident = observation['visible_object_id']
    _need(_equal(option['request_binding'], binding) and _equal(option['source_snapshot_ref'], ref) and
        options['read_only'] is True and option['read_only'] is True and
        all(options[key] is False and option[key] is False for key in EXECUTION) and
        observation['source_card_identity_agreement'] is True and
        observation['unknown_parameter_fields_present'] is False,
        'play_source_identity_unverified')
    visible = [obj for obj in options['visible_state']['visible_objects'] if obj['instance_id'] == ident]
    seat = binding['self_seat']
    _need(len(visible) == 1 and type(visible[0]['card_id']) is int and visible[0]['card_id'] > 0 and
        visible[0]['zone'] == 'ZoneType_Hand' and
        all(type(visible[0][key]) is int and visible[0][key] == seat for key in ('owner_seat', 'controller_seat')),
        'play_source_identity_unverified')
    _need(isinstance(prepared, PreparedRulesIndex), 'reference_source_unverified')
    card_id = visible[0]['card_id']
    metadata, matches = prepared.lookup([card_id], max_reference_bytes=MAX_REFERENCE_BYTES)
    _need(_equal({key: metadata[key] for key in REFERENCE_SOURCE}, REFERENCE_SOURCE), 'reference_source_unverified')
    match = matches[card_id]
    if match['status'] != 'resolved':
        return result
    card = match['card']
    _need(card['schema_version'] == MTGA_LAND_VERSION and type(card['card_id']) is int and
        card['card_id'] == card_id, 'static_land_identity_unverified')
    if not _ordinary_swamp(card):
        return result
    phase = _phase_evidence({'binding': binding, **options['visible_state']})
    result['coverage'].update(verified_static_land_candidates=1, ordinary_profile_candidates=1)
    result.update(status='research_preference', reason='verified_land_development_heuristic',
        preference_basis='verified_land_development_heuristic',
        preferred_option_key=copy.deepcopy(option['option_key']),
        source_identity={'list_position': option['list_position'], 'instance_id': ident, 'card_id': card_id},
        static_reference_source=copy.deepcopy(REFERENCE_SOURCE), phase_evidence=phase,
        land_profile_evidence={'scope': 'literal_unlinked_primary_basic_swamp_metadata_only',
            'reference': copy.deepcopy(card), 'effective_mana_production_verified': False})
    if phase['stack_availability'] == 'unknown':
        result['unresolved'].append('stack_emptiness_unknown_not_inferred')
    _bounded_json(result)
    return result


def _evaluate(state, ref, consumer, reducer, message, prepared, *, supplied_options=None):
    result = _unknown('request_strategy_unsupported', ref)
    result.update(request_binding=copy.deepcopy(state['binding']))
    if state['binding']['request_type'] != 'GREMessageType_ActionsAvailableReq':
        result['status'] = 'unsupported'
        return result
    options = consumer.current_decision_options() if supplied_options is None else supplied_options
    _need(options['schema_version'] == OPTIONS_VERSION and options['status'] == 'partial' and
        _equal(options['request_binding'], state['binding']) and _equal(options['source_snapshot_ref'], ref) and
        options['read_only'] is True and all(options[key] is False for key in EXECUTION),
        'current_options_not_available_or_binding_invalid')
    coverage = options['coverage']
    _need(coverage['truncated'] is False and coverage['omitted_constructed_options'] == 0 and
        all(source['truncated'] is False and source.get('omitted_constructed_options', 0) == 0
            for source in coverage['sources']), 'active_inventory_incomplete')
    _need(type(message) is dict and set(message) == {'type', 'systemSeatIds', 'msgId', 'gameStateId',
        'prompt', 'actionsAvailableReq'}, 'request_structure_unreviewed')
    _prompt(message['prompt'])  # Shape only; its meaning/routing remain unknown.
    body = message['actionsAvailableReq']
    _need(type(body) is dict and {'actions'} <= body.keys() <= {'actions', 'inactiveActions'} and
        type(body['actions']) is list and 1 <= len(body['actions']) <= 256 and
        type(body.get('inactiveActions', [])) is list and len(body.get('inactiveActions', [])) <= 256 and
        all(type(row) is dict for row in body.get('inactiveActions', [])), 'request_structure_unreviewed')
    rows = body['actions']; engine = [row for row in options['options'] if row['kind'] == 'engine_action']
    _need(coverage['engine_offered_unit'] == 'active_action_row' and
        type(coverage['engine_offered_count']) is int and coverage['engine_offered_count'] == len(rows) == len(engine),
        'active_inventory_incomplete')
    for position, (row, option) in enumerate(zip(rows, engine)):
        _need(option['list_position'] == position and type(option['list_position']) is int and
            _equal(option['request_binding'], state['binding']) and _equal(option['source_snapshot_ref'], ref) and
            option['read_only'] is True and all(option[key] is False for key in EXECUTION) and
            option['observation']['engine_action_type'] == row.get('actionType') and
            option['observation']['unknown_parameter_fields_present'] is False,
            'active_action_structure_unreviewed')
        try:
            # Reuse the reviewed finite action shape projector for every row.
            # This checks structure, never complete costs/targets/legality.
            raw = (_without_highlight(row) if row.get('actionType') in
                ('ActionType_Cast', 'ActionType_Activate', 'ActionType_Activate_Mana') and row.get('targets') else row)
            action(raw, LiteralRefs(), ())
        except (ValueError, KeyError, TypeError):
            raise ValueError('active_action_structure_unreviewed') from None
    plays = [(position, row, engine[position]) for position, row in enumerate(rows)
             if row['actionType'] == 'ActionType_Play']
    result['coverage'].update(active_action_rows=len(rows), play_offers=len(plays),
        verified_play_sources=0, verified_static_land_candidates=0, ordinary_profile_candidates=0)
    if not plays:
        result['reason'] = 'no_play_offered'
        return result
    _need(isinstance(prepared, PreparedRulesIndex), 'reference_source_unverified')
    context = build_static_rule_context(state, prepared, max_reference_bytes=MAX_REFERENCE_BYTES)
    source = context['rules_source']
    _need(context['status'] == 'reference_context_observed' and _equal(context['binding'], state['binding']) and
        _equal(source, REFERENCE_SOURCE),
        'reference_source_unverified')
    result['static_reference_source'] = copy.deepcopy(source)
    refs = reducer._cast_source_refs()
    admitted = []
    for position, row, option in plays:
        ident = row['instanceId']; card_id = row['grpId']
        _need(all(_id(row[key]) and row[key] > 0 for key in ('instanceId', 'grpId', 'facetId')) and
            ident in refs and option['observation']['source_card_identity_agreement'] is True and
            option['observation']['visible_object_id'] == ident,
            'play_source_identity_unverified')
        obj = reducer.objects[ident]
        visible = [item for item in state['visible_objects'] if item['instance_id'] == ident]
        _need(type(obj.get('grpId')) is int and obj['grpId'] == card_id and
            obj.get('type') == 'GameObjectType_Card' and len(visible) == 1 and
            visible[0]['card_id'] == card_id and type(visible[0]['card_id']) is int and
            visible[0]['zone'] == 'ZoneType_Hand' and
            all(type(obj.get(key)) is int and obj[key] == state['binding']['self_seat'] for key in ('ownerSeatId', 'controllerSeatId')),
            'play_source_identity_unverified')
        result['coverage']['verified_play_sources'] += 1
        matches = [item for item in context['objects'] if item['instance_id'] == ident]
        if len(matches) != 1 or matches[0]['status'] != 'resolved_static_reference':
            continue
        card = matches[0]['reference']
        _need(card['schema_version'] == MTGA_LAND_VERSION and type(card['card_id']) is int and card['card_id'] == card_id,
            'static_land_identity_unverified')
        if not any(_equal(term, {'value': 5, 'loc_id': 11, 'label': 'Land'}) for term in card['card_types']):
            continue
        result['coverage']['verified_static_land_candidates'] += 1
        if _ordinary(card):
            admitted.append((position, row, option))
            result['coverage']['ordinary_profile_candidates'] += 1
    if len(plays) != 1:
        result['reason'] = 'multiple_play_competitors'
        return result
    if result['coverage']['verified_static_land_candidates'] != 1:
        result['reason'] = 'static_land_identity_unverified'
        return result
    if len(admitted) != 1:
        result['reason'] = 'ordinary_land_profile_unverified'
        return result
    result['phase_evidence'] = _phase_evidence(state)
    if result['phase_evidence']['stack_availability'] == 'unknown':
        result['unresolved'].append('stack_emptiness_unknown_not_inferred')
    position, row, option = admitted[0]
    result.update(status='research_preference', reason='verified_land_development_heuristic',
        preference_basis='verified_land_development_heuristic', preferred_option_key=copy.deepcopy(option['option_key']),
        source_identity={'list_position': position, 'instance_id': row['instanceId'], 'card_id': row['grpId'], 'facet_id': row['facetId']})
    _bounded_json(result)
    return result


def assess_current_land_development(consumer, reducer, message, prepared_rules, *, policy_version=POLICY,
                                    completed_stamp=None):
    """Same Consumer/raw owner and its existing completed-poll witness.

    A caller cannot establish the preexisting poll context by taking a fresh
    fingerprint at evaluation time. Runtime supplies its original poll stamp.
    """
    unknown = _swamp_unknown if policy_version == SWAMP_POLICY else _unknown
    if policy_version not in (POLICY, SWAMP_POLICY):
        result = _unknown('unsupported_policy_version')
        result.update(status='unsupported', policy_version='unsupported')
        return result
    if completed_stamp is None:
        return unknown('completed_poll_context_required')
    if not isinstance(consumer, DecisionConsumer):
        return unknown('requires_current_consumer')
    if getattr(consumer, '_owner_thread_id', None) != threading.get_ident():
        return unknown('owner_thread_required')
    def evaluate(state, *, source_snapshot_ref):
        try:
            # Same existing raw/current fingerprint before and after *all*
            # results, including abstentions. No separate state or ledger.
            from .shadow_runtime import _stamp
            stamp = _stamp(reducer, message, state)
            _need(_equal(stamp, completed_stamp), 'raw_state_changed_during_frame')
            turn_keys = ('turnNumber', 'activePlayer', 'decisionPlayer', 'phase', 'step', 'priorityPlayer')
            _need(_equal({key: reducer.turn.get(key) for key in turn_keys},
                         {key: state['game']['turn'].get(key) for key in turn_keys}), 'raw_state_changed_during_frame')
            options = None
            if policy_version == SWAMP_POLICY and state['binding']['request_type'] == 'GREMessageType_ActionsAvailableReq':
                from .target_build import current_resource
                _need(current_resource(reducer) is not None, 'exact_build_resource_provenance_unverified')
                options = consumer.current_decision_options()
            result = _evaluate(state, source_snapshot_ref, consumer, reducer, message, prepared_rules,
                supplied_options=options)
            if policy_version == SWAMP_POLICY:
                result = _swamp_extension(options, result, prepared_rules)
            _need(_equal(stamp, _stamp(reducer, message, state)), 'raw_state_changed_during_frame')
            _need(_equal({key: reducer.turn.get(key) for key in turn_keys},
                         {key: state['game']['turn'].get(key) for key in turn_keys}), 'raw_state_changed_during_frame')
            return result
        except (ValueError, TypeError, KeyError, IndexError, RecursionError, UnicodeError, OverflowError) as exc:
            reason = str(exc)
            return unknown(reason if reason in (SWAMP_REASONS if policy_version == SWAMP_POLICY else REASONS) or reason in ('raw_current_binding_unverified',
                'raw_state_changed_during_frame', 'owner_context_unavailable') else 'current_options_not_available_or_binding_invalid')
    return _assess_current_report(consumer, evaluate, unknown)
