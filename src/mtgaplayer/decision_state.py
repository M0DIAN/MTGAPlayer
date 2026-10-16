"""Pure assembly of one projected GRE snapshot; no reader or input authority."""
import copy
import re
from collections import Counter
from typing import TypedDict

from .decision_input import build_decision_input, _catalog, _id

SCHEMA_VERSION = 'mtgaplayer.decision-state.v1'
SCHEMA_VERSIONS = {1: SCHEMA_VERSION, 2: 'mtgaplayer.decision-state.v2',
                   3: 'mtgaplayer.decision-state.v3', 4: 'mtgaplayer.decision-state.v4',
                   5: 'mtgaplayer.decision-state.v5', 6: 'mtgaplayer.decision-state.v6'}
EFFECTIVE_STATS = {'basis': 'accepted_gre_reduced_object_literals', 'scope': 'visible_battlefield',
                   'effect_sources': None, 'durations': None}
FLAGS = {name: False for name in ('legal_choice_verified', 'complete_legality_verified',
    'response_encoding_verified', 'server_acceptance_verified', 'execution_ready', 'input_sent')}
IDENTITY_FIELDS = ('generation', 'match', 'game', 'self_seat', 'game_state_id', 'request_id')
KINDS = {'GREMessageType_ActionsAvailableReq': 'actions_available',
         'GREMessageType_SelectNReq': 'select_n',
         'GREMessageType_DeclareAttackersReq': 'declare_attackers',
         'GREMessageType_DeclareBlockersReq': 'declare_blockers'}


class DecisionState(TypedDict):
    schema_version: str
    status: str
    binding: dict
    source: dict
    game: dict
    visible_objects: list[dict]
    card_knowledge: dict | None
    effect_claims: None
    legal_action_space: dict
    unresolved: list[str]
    execution: dict
    read_only: bool


def state_schema_version(version):
    if type(version) is not int or version not in SCHEMA_VERSIONS:
        raise ValueError('unsupported_decision_state_version')
    return SCHEMA_VERSIONS[version]


def _stack(value, visible):
    """Shared validation of literal public Stack references, not game rules."""
    def require(ok):
        if not ok:
            raise ValueError('invalid_public_stack')
    require(type(value) is dict and set(value) == {'availability', 'zone_id', 'members', 'order_basis'})
    require(value['order_basis'] == 'literal_gre_zone_objectInstanceIds')
    if value['availability'] == 'unknown':
        require(value['zone_id'] is None and value['members'] is None)
        return
    require(value['availability'] in ('observed', 'confirmed_empty') and _id(value['zone_id']))
    rows = value['members']
    require(type(rows) is list and len(rows) <= 512)
    require((value['availability'] == 'observed') == bool(rows))
    counts = Counter(obj['instance_id'] for obj in visible)
    public = {obj['instance_id'] for obj in visible if obj['zone'] == 'ZoneType_Stack'}
    ids = []
    for position, row in enumerate(rows):
        require(type(row) is dict and set(row) == {'list_position', 'instance_id', 'object_type'})
        require(type(row['list_position']) is int and row['list_position'] == position and _id(row['instance_id']))
        require(row['object_type'] in (None, 'GameObjectType_Card', 'GameObjectType_Ability', 'GameObjectType_Token'))
        require(counts[row['instance_id']] == 1 and row['instance_id'] in public)
        ids.append(row['instance_id'])
    require(len(set(ids)) == len(ids) and set(ids) == public)


def _effective_stats(value, visible):
    """Public v4 observation constraints; not raw-source reauthentication.

    Only the producer can check the original Card/Token type. Consumer checks
    the fixed claim, public zone, literal scalar bounds and enclosing binding.
    """
    if type(value) is not dict or value != EFFECTIVE_STATS or set(value) != set(EFFECTIVE_STATS):
        raise ValueError('invalid_effective_stats')
    ids = [obj['instance_id'] for obj in visible]
    if len(ids) != len(set(ids)):
        raise ValueError('ambiguous_effective_stats_identity')
    for obj in visible:
        for key in ('effective_power', 'effective_toughness'):
            stat = obj[key]
            if stat is not None and (type(stat) is not int or not -2**31 <= stat <= 2**31 - 1 or
                                     obj['zone'] != 'ZoneType_Battlefield'):
                raise ValueError('invalid_effective_stats')


def _same_identity(value, identity):
    return isinstance(value, dict) and all(
        type(value.get(k)) is type(v) and value.get(k) == v for k, v in identity.items())


def _bound_readonly(value, identity, request_type):
    """Do not import stale nested action keys or elevated child authority."""
    if isinstance(value, list):
        return all(_bound_readonly(row, identity, request_type) for row in value)
    if not isinstance(value, dict):
        return True
    for key, child in value.items():
        if key in FLAGS or key in ('actionable', 'usable_now', 'executor_connected'):
            if child is not False:
                return False
        if key == 'read_only' and child is not True:
            return False
        if key == 'request_identity' and not _same_identity(child, identity):
            return False
        if key == 'request_identity' and 'request_type' in child and child['request_type'] != request_type:
            return False
        if 'completeness' in key and child == 'complete_verified':
            return False
        if not _bound_readonly(child, identity, request_type):
            return False
    return True


def build_decision_state(document, *, version=1):
    """Consume only current visible state and child projections of that snapshot.

    CLI stages children on a private copy before consuming action row metadata.
    Invalid/discontinuous/partial input returns None. No-request state is useful
    but confers no knowledge of an empty legal-action domain. Never last_valid.
    Request continuity requires the opt-in RawReducer document fact; legacy
    public documents without it can supply visible state but no current choices.
    """
    schema_version = state_schema_version(version)
    if not isinstance(document, dict):
        return None
    current, source = document.get('current'), document.get('source')
    if (not isinstance(current, dict) or not isinstance(source, dict) or
            current.get('valid') is not True or current.get('actionable') is not False or
            current.get('legal_actions') is not None or document.get('error') is not None or
            source.get('format') != 'player-log-gre-v1' or
            source.get('mode') not in ('offline', 'watch') or source.get('partial_record') is not False or
            source.get('input_sent') is not False or source.get('executor_connected') is not False or
            not _id(source.get('generation')) or not _id(current.get('game_state_id')) or
            not _id(current.get('game')) or current['game'] < 1 or
            type(current.get('self_seat')) is not int or current['self_seat'] not in (1, 2) or
            not isinstance(current.get('match'), str) or not current['match']):
        return None
    identity = {'generation': source['generation'], **{k: current[k] for k in
                ('match', 'game', 'self_seat', 'game_state_id')}, 'request_id': None}
    request = current.get('request')
    request_type = None
    decision = build_decision_input(document)
    if request is not None:
        binding = request.get('binding') if isinstance(request, dict) else None
        if (not isinstance(binding, dict) or binding.get('ownership_verified') is not True or
                request.get('current') is not True or not _id(request.get('id')) or
                type(request.get('game_state_id')) is not int or
                request['game_state_id'] != identity['game_state_id'] or
                not isinstance(request.get('type'), str) or
                not _same_identity(binding, {k: v for k, v in identity.items() if k != 'request_id'})):
            return None
        identity['request_id'], request_type = request['id'], request['type']
    if 'decision_input' in document and document['decision_input'] != decision:
        return None
    # The legacy public snapshot intentionally omits continuity metadata and
    # may retain recovered requests for diagnostics. Only the opt-in reducer
    # snapshot can certify an uninterrupted current request for this contract.
    unverified_request = request is not None and request.get('_continuity_verified') is not True
    if unverified_request:
        request, request_type, decision = None, None, None
        identity['request_id'] = None
    objects = current.get('objects')
    if not isinstance(objects, list) or len(objects) > 512:
        return None
    visible, knowledge = [], []
    for obj in objects:
        if not isinstance(obj, dict) or not _id(obj.get('id')):
            return None
        visible.append({'instance_id': obj['id'], 'card_id': obj.get('card_id') if _id(obj.get('card_id')) else None,
            'zone': obj.get('zone') if isinstance(obj.get('zone'), str) else None,
            'owner_seat': obj.get('owner') if type(obj.get('owner')) is int and obj['owner'] in (1, 2) else None,
            'controller_seat': obj.get('controller') if type(obj.get('controller')) is int and obj['controller'] in (1, 2) else None,
            'tapped': obj.get('tapped') if type(obj.get('tapped')) is bool else None,
            'effective_power': None, 'effective_toughness': None})
        card = _catalog(obj.get('local_card'))
        if card is not None:
            knowledge.append({'instance_id': obj['id'], 'card_id': visible[-1]['card_id'], 'knowledge': card})
    players = current.get('players')
    if not isinstance(players, list) or any(not isinstance(p, dict) or
            type(p.get('seat')) is not int or p['seat'] not in (1, 2) for p in players):
        return None
    turn = current.get('turn') or {}
    hidden = current.get('hidden_counts')
    if not isinstance(turn, dict) or not isinstance(hidden, dict) or any(
            not isinstance(k, str) or not _id(v) for k, v in hidden.items()):
        return None
    game = {k: current.get(k) if isinstance(current.get(k), str) else None for k in
            ('room_state', 'game_stage', 'source_state_timestamp')}
    game.update({'turn': {k: turn.get(k) if type(turn.get(k)) is int else None for k in
                         ('turnNumber', 'activePlayer', 'decisionPlayer')},
        'players': [{'seat': p['seat'], 'life': p.get('life') if type(p.get('life')) is int else None} for p in players],
        'hidden_counts': hidden, 'mana': None, 'effective_combat_stats': None, 'rules': None})
    if version >= 2:
        context = current.get('_turn_context')
        if not isinstance(context, dict) or set(context) != {'phase', 'step', 'priorityPlayer'}:
            return None
        for key, prefix in (('phase', 'Phase_'), ('step', 'Step_')):
            value = context[key]
            if value is not None and (type(value) is not str or
                    re.fullmatch(prefix + r'[A-Za-z0-9_]{1,80}', value) is None):
                return None
        priority = context['priorityPlayer']
        if priority is not None and (type(priority) is not int or priority not in (1, 2)):
            return None
        game['turn'].update(context)
    if version >= 3:
        stack = current.get('_public_stack')
        try:
            _stack(stack, visible)
        except (ValueError, KeyError, TypeError):
            return None
        game['stack'] = copy.deepcopy(stack)
    if version >= 4:
        observed = current.get('_observed_combat_stats')
        counts = Counter(obj['instance_id'] for obj in visible)
        if type(observed) is not list or len(observed) > 512:
            return None
        by_id = {}
        for row in observed:
            if (type(row) is not dict or
                    set(row) != {'instance_id', 'effective_power', 'effective_toughness'} or
                    not _id(row.get('instance_id')) or counts[row['instance_id']] != 1 or
                    row['instance_id'] in by_id):
                return None
            by_id[row['instance_id']] = row
        for obj in visible:
            if obj['instance_id'] in by_id:
                row = by_id[obj['instance_id']]
                if obj['zone'] != 'ZoneType_Battlefield':
                    return None
                obj.update({key: row[key] for key in ('effective_power', 'effective_toughness')})
        game['effective_combat_stats'] = dict(EFFECTIVE_STATS)
        try:
            _effective_stats(game['effective_combat_stats'], visible)
        except (ValueError, KeyError, TypeError):
            return None
    kind = KINDS.get(request_type)
    projection, graph, availability, completeness = None, None, 'not_provided', 'unknown'
    unresolved = ['effective_stats_unknown', 'effects_not_observed', 'mana_payment_unknown',
                  'complete_legality_unknown', 'response_encoding_unknown', 'server_acceptance_unknown']
    if version >= 4:
        unresolved.remove('effective_stats_unknown')
        unresolved.extend(('current_power_toughness_scope_limited', 'current_power_toughness_unknown_where_null',
                           'effective_stat_effect_sources_unknown', 'effective_stat_durations_unknown'))
    if version >= 3:
        unresolved.extend(('stack_order_orientation_unverified', 'stack_resolution_unverified'))
        if game['stack']['availability'] == 'unknown':
            unresolved.append('public_stack_membership_unknown')
        elif any(row['object_type'] is None for row in game['stack']['members']):
            unresolved.append('stack_object_type_unknown')
    if request_type is None:
        unresolved.append('current_own_request_not_provided')
        if unverified_request:
            unresolved.append('current_request_continuity_unverified')
    elif kind is None:
        availability = 'unsupported'
        unresolved.append('request_type_unsupported')
    elif decision is None:
        availability = 'unknown'
        unresolved.append('decision_input_projection_unavailable')
    elif kind == 'select_n':
        projection = decision['request']['select_n']
        if projection is not None:
            availability = 'confirmed_empty' if not projection['offered_instance_ids'] else 'observed'
            completeness = 'partial'
        unresolved.extend(('select_n_minimum_unknown', 'select_n_combinations_unverified'))
    else:
        name = 'action_frontier' if kind == 'actions_available' else 'combat_frontier'
        child = document.get(name)
        schema = 'mtga-action-frontier-v1' if name == 'action_frontier' else 'mtga-combat-frontier-v1'
        if (isinstance(child, dict) and child.get('schema') == schema and
                _same_identity(child.get('request_identity'), identity) and
                (name != 'combat_frontier' or child.get('combat_request_type') == request_type and
                 child['request_identity'].get('request_type') == request_type) and
                _bound_readonly(child, identity, request_type)):
            projection = child
            count = child.get('engine_active_action_count' if name == 'action_frontier' else 'observed_candidate_count')
            rows = child.get('templates' if name == 'action_frontier' else 'engine_offered_candidates')
            if isinstance(rows, list):
                availability = 'confirmed_empty' if count == 0 and rows == [] else 'observed'
                completeness = 'partial'
            else:
                availability = 'unknown'
            if name == 'action_frontier':
                candidate_graph = document.get('choice_graph')
                provenance = candidate_graph.get('provenance') if isinstance(candidate_graph, dict) else None
                if (isinstance(candidate_graph, dict) and candidate_graph.get('schema_version') == 'mtga-choice-graph-v1' and
                        _same_identity(candidate_graph.get('request_identity'), identity) and
                        _bound_readonly(candidate_graph, identity, request_type) and
                        isinstance(provenance, dict) and provenance.get('historical_response_used') is False):
                    graph = candidate_graph
                else:
                    unresolved.append('choice_graph_unavailable_or_mismatched')
            unresolved.append('parameter_combinations_unverified')
        else:
            availability = 'unknown' if child is not None else 'not_provided'
            unresolved.append('current_frontier_unavailable_or_mismatched')
    binding = {'source_generation': identity['generation'], **{k: identity[k] for k in IDENTITY_FIELDS if k != 'generation'},
               'request_type': request_type}
    result = {'schema_version': schema_version,
        'status': 'state_and_request_observed' if request is not None else 'state_observed_without_request',
        'binding': binding, 'source': {'format': source['format'], 'mode': source['mode'],
            'byte_offset': source.get('byte_offset') if _id(source.get('byte_offset')) else None,
            'phase': source.get('phase') if source.get('phase') in ('history', 'append') else None,
            'stopped': source.get('stopped') if type(source.get('stopped')) is bool else None,
            'partial_record': False,
            'freshness_verified': False, 'snapshot_scope': 'single_reducer_document'},
        'game': game, 'visible_objects': visible,
        'card_knowledge': {'source': 'local_catalog_static_only', 'objects': knowledge} if knowledge else None,
        'effect_claims': None, 'legal_action_space': {'request_type': request_type,
            'immediate_frontier': {'kind': kind, 'availability': availability,
                'completeness': completeness, 'projection': projection},
            'choice_graph': graph, 'expanded_plans': {'completeness': 'unknown', 'plans': None}},
        'unresolved': sorted(set(unresolved)), 'execution': {'actionable': False,
            'executor_connected': False, **FLAGS}, 'read_only': True}
    if version >= 5:
        from .request_parameters import assemble, check_space
        try:
            result['legal_action_space']['request_parameters'] = assemble(
                request.get('_request_parameters') if request is not None else None, binding, visible,
                allow_effect_cost=version >= 6)
            from .semantic_effect_cost import PROFILE as COST_PROFILE
            parameters = result['legal_action_space']['request_parameters']
            if parameters is not None and parameters['profile'] == COST_PROFILE:
                result['legal_action_space']['immediate_frontier']['availability'] = 'not_applicable'
                result['unresolved'] = sorted(set(result['unresolved']) - {'request_type_unsupported'} |
                    {'complete_payment_unknown', 'payment_rules_effect_unknown',
                     'payment_parent_source_unknown', 'cancellation_undo_reachability_unknown',
                     'future_payment_parameters_unknown'})
            check_space(result['legal_action_space'], binding, visible, allow_effect_cost=version >= 6)
        except (ValueError, TypeError, KeyError, RecursionError):
            return None
    return copy.deepcopy(result)
