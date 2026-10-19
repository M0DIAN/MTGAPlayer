"""Explicit MP84 role branch of the existing bounded RevisionStage.

No state owner or request ledger lives here. Current evidence is obtained from
the same Consumer; subsequent consumed submissions are historical facts only.
"""
import copy
import weakref

from .semantic_samples import _need, _keys
from .semantic_activate_targets import _same, _revision_binding_matches
from .semantic_targets import SELECT, UNSELECT, check_referent_final_set
from .current_target_request import ROLE_VERSION, ROLE_PROFILE, _role_identity, role_state_witness
from .choice_continuation import _binding, _scope
from .response_evidence import _current_verified_raw_request
from .decision_consumer import EXECUTION

VERSION = 'mtgaplayer.historical-player-target-stage.v1'
_ERRORS = (ValueError, TypeError, KeyError, IndexError, RecursionError, OverflowError)


def _identity(member):
    # Operation and row position must be checked independently at each end.
    return {k: v for k, v in member.items() if k not in ('legal_action', 'list_position')}


def _signatures(reducer, constraints, member=None):
    source = constraints['source_object_ref']
    result = {source: _role_identity(reducer, source, ('GameObjectType_Ability',), 'ZoneType_Stack')}
    if member is not None and member['target_referent_kind'] == 'verified_public_object':
        ident = member['public_object_ref']
        result[ident] = _role_identity(reducer, ident, ('GameObjectType_Card', 'GameObjectType_Token'), 'ZoneType_Battlefield')
    return result


def _witness(reducer, constraints, member):
    from .target_build import current_build
    signatures = _signatures(reducer, constraints, member)
    return copy.deepcopy((_scope(reducer), reducer.accepted_digest.hex(), current_build(reducer),
        role_state_witness(reducer, signatures), signatures))


def _current(stage, frozen):
    """Recheck lease/ref, raw request, version, roles and completed-poll stamp."""
    from .shadow_runtime import _raw_stamp
    consumer = frozen['consumer']()
    _need(consumer is not None)
    r = stage.reducer; message = frozen['message']; report = frozen['evidence']
    request = _current_verified_raw_request(r, message)
    _need(request is not None and _same(_binding(r, request), report['current_request_binding']) and
        _same(_raw_stamp(r), frozen['stamp']))
    current = consumer.current_decision_options(current_target_context=(r, message))['current_target_evidence']
    view = consumer.current_view()
    _need(_same(current, report) and view['consumer_status'] == 'OBSERVING' and
        _same(view['current_snapshot_ref'], report['source_snapshot_ref']) and
        _same(_raw_stamp(r), frozen['stamp']))
    return request


def freeze(stage, consumer, message, evidence, policy):
    """Freeze one first-current domain or independently current Unselect literal."""
    from .shadow_runtime import _raw_stamp
    try:
        r = stage.reducer
        _need(evidence.get('schema_version') == ROLE_VERSION and evidence['profile'] == ROLE_PROFILE and
            evidence['status'] == 'observed' and evidence['unresolved_memberships'] == 0 and
            evidence['truncated'] is False)
        _need(_same(consumer.shadow_decision(), policy) and
            _same(policy['request_binding'], evidence['current_request_binding']) and
            _same(policy['source_snapshot_ref'], evidence['source_snapshot_ref']))
        frozen = {'consumer': weakref.ref(consumer), 'message': copy.deepcopy(message),
            'evidence': copy.deepcopy(evidence), 'policy': copy.deepcopy(policy),
            'stamp': _raw_stamp(r), 'frozen_record': stage.record_ordinal}
        request = _current(stage, frozen); binding = _binding(r, request)
        if stage.cached and 'role_frozen' in stage.cached and _same(
                stage.cached['role_frozen']['evidence']['current_request_binding'], binding):
            return
        saved = stage.pending
        if saved is not None and 'role_first' in saved:
            _need(saved.get('intervening_diff_count') == 1 and saved.get('revised_message') is not None and
                _same(saved['revised_message'], message) and _scope(r) == saved['scope'] and
                _same(binding['game_state_id'], saved['state_id']))
            old = saved['role_first']['evidence']; old_binding = old['current_request_binding']
            now = evidence['target_constraints']; chosen = evidence['current_selected_literal']
            _need(binding['request_id'] != old_binding['request_id'] and
                all(_same(binding[k], old_binding[k]) for k in ('source_generation', 'match', 'game', 'self_seat')) and
                _same(evidence['version_mapping_evidence'], old['version_mapping_evidence']) and
                _revision_binding_matches(old['target_constraints'], now) and
                all(type(now[k]) is int and now[k] == 1 for k in ('min_targets', 'max_targets', 'selected_count')) and
                type(chosen) is list and len(chosen) == len(now['entries']) == 1 and
                chosen[0]['legal_action'] == UNSELECT and chosen[0]['list_position'] == 0 and
                _same(_identity(chosen[0]), _identity(saved['selected_member'])) and
                _same(_signatures(r, now, chosen[0]), saved['signatures']) and
                not evidence['complete_current_select_domain_verified'] and not evidence['local_proposals'])
            context = copy.deepcopy(saved['historical_fact'])
            context.update(status='historical_revised_selection_verified', revised_request_binding=copy.deepcopy(binding),
                revised_snapshot_ref=copy.deepcopy(evidence['source_snapshot_ref']),
                revised_selection_evidence=copy.deepcopy(evidence), revised_frozen_record=stage.record_ordinal)
            stage.pending = None; stage.active = {'role_context': context}
            stage.cached = {'message': copy.deepcopy(message), 'role_frozen': frozen}
            stage.player_completions.player_counts['independently_revised_selections'] += 1
            stage.player_completions.player_last = copy.deepcopy(context)
            return
        _need(saved is None and evidence['complete_current_select_domain_verified'] is True and
            evidence['current_selected_literal'] is None and evidence['local_proposals'] and
            any(m['target_referent_kind'] == 'verified_player' for m in evidence['target_referents']) and
            all(o['research_eligible'] is False for o in evidence['local_proposals']) and
            len(evidence['local_proposals']) == evidence['candidate_total_for_reviewed_constraints'])
        stage.reset()
        stage.cached = {'message': copy.deepcopy(message), 'role_frozen': frozen}
        c = stage.player_completions.player_counts
        c['frozen_reviewed_domains'] += 1; c['frozen_local_proposals'] += len(evidence['local_proposals'])
    except _ERRORS:
        stage._invalidate_record()


def prepare(stage, payload):
    """Return true only when this explicit role branch owns the current stage."""
    if not stage.cached or 'role_frozen' not in stage.cached:
        return False
    from .target_revision import _selection_shape
    frozen = stage.cached['role_frozen']; r = stage.reducer
    request = _current(stage, frozen); ev = frozen['evidence']; binding = ev['current_request_binding']
    if stage.active is not None and 'role_context' in stage.active:
        _keys(payload, ('type', 'respId', 'gameStateId'))
        _need(payload['type'] == 'ClientMessageType_SubmitTargetsReq' and
            type(payload['respId']) is int and payload['respId'] == binding['request_id'] and
            type(payload['gameStateId']) is int and payload['gameStateId'] == binding['game_state_id'])
        context = copy.deepcopy(stage.active['role_context'])
        terminal = {'before': copy.deepcopy(request), 'payload': copy.deepcopy(payload), 'scope': _scope(r),
            'role_context': context, 'witness': _witness(r, ev['target_constraints'], context['historical_selected_target'])}
        stage.reset(); stage.terminal = terminal
        return True
    _need(stage.active is None and stage.pending is None)
    update = _selection_shape(payload, binding); target = update['target']; constraints = ev['target_constraints']
    _need(_same(target['targetIdx'], constraints['target_idx']))
    chosen = target['targets'][0]['targetInstanceId']
    members = [m for m in ev['target_referents'] if _same(m['target_instance_ref'], chosen)]
    _need(len(members) == 1 and members[0]['legal_action'] == SELECT)
    member = members[0]
    _need(check_referent_final_set(constraints, {'source_object_ref': constraints['source_object_ref'],
        'target_idx': constraints['target_idx'], 'target_referents': [member]})[0] == 'verified_known_constraints')
    prepared = {'before': copy.deepcopy(request), 'payload': copy.deepcopy(payload), 'scope': _scope(r),
        'role_first': frozen, 'selection_update': update, 'selected_member': copy.deepcopy(member),
        'signatures': _signatures(r, constraints, member), 'witness': _witness(r, constraints, member),
        'update_record': stage.record_ordinal}
    stage.reset(); stage.prepared = prepared
    return True


def updated(stage, saved):
    try:
        ev = saved['role_first']['evidence']; member = saved['selected_member']
        _need(saved['role_first']['frozen_record'] < saved['update_record'] and
            _same(saved['witness'], _witness(stage.reducer, ev['target_constraints'], member)))
        fact = {'schema_version': VERSION, 'status': 'historical_target_update_verified',
            'first_request_binding': copy.deepcopy(ev['current_request_binding']),
            'first_snapshot_ref': copy.deepcopy(ev['source_snapshot_ref']),
            'frozen_current_target_domain': copy.deepcopy(ev), 'frozen_shadow_decision': copy.deepcopy(saved['role_first']['policy']),
            'historical_update_binding': copy.deepcopy(saved['selection_update']['request_binding']),
            'historical_selected_target': copy.deepcopy(member), 'historical_selected_role': member['target_referent_kind'],
            'update_record': saved['update_record'], 'first_frozen_record': saved['role_first']['frozen_record'],
            'revised_request_binding': None, 'revised_snapshot_ref': None, 'revised_selection_evidence': None,
            'terminal_submit_binding': None, 'terminal_consumed': False, 'continuity_verified': True,
            'historical_comparison_status': 'unavailable_no_comparable_frozen_preference',
            'parent_action_causality': 'unknown', 'complete_legality_verified': False,
            'server_acceptance_verified': False, 'current': False, 'historical_only': True, 'read_only': True, **EXECUTION}
        lineage = saved['role_first'].get('parent_source_lineage')
        if lineage is not None:
            _need(_same(lineage['child_request_binding'], ev['current_request_binding']) and
                _same(lineage['child_snapshot_ref'], ev['source_snapshot_ref']) and
                lineage['source_lineage_status'] == 'parent_child_source_lineage_verified')
            fact['parent_source_lineage'] = copy.deepcopy(lineage)
        saved['historical_fact'] = fact
        c = stage.player_completions.player_counts
        c['strictly_paired_target_updates'] += 1
        c['historically_selected_player_targets'] += member['target_referent_kind'] == 'verified_player'
        stage.player_completions.player_last = copy.deepcopy(fact)
    except _ERRORS:
        stage._invalidate_record()


def observe(stage, event, details):
    """The old bounded lineage owns ordering, interruption, age and consumption."""
    saved = stage.pending
    if saved is not None and 'role_first' in saved:
        r = stage.reducer; old = saved['role_first']['evidence']
        if event == 'state_accepted':
            from .target_revision import _no_identity_migration
            gs = details['message']
            _need(details['kind'] == 'diff' and 'intervening_diff_count' not in saved and
                _scope(r) == saved['scope'] and _same(gs['prevGameStateId'], old['current_request_binding']['game_state_id']))
            # A contradictory migration mentioning the selected entity also
            # breaks a player lineage. This is a conflict check, never an
            # attempt to resolve a player through the object table.
            _no_identity_migration(gs, {*saved['signatures'], saved['selected_member']['target_instance_ref']})
            _need(_same(_signatures(r, old['target_constraints'], saved['selected_member']), saved['signatures']))
            saved['intervening_diff_count'] = 1; saved['state_id'] = r.version
            return True
        if event == 'request_accepted':
            request = _current_verified_raw_request(r, details['message'])
            _need(request is not None and not details['is_retransmission'] and
                request['type'] == 'GREMessageType_SelectTargetsReq' and
                saved.get('intervening_diff_count') == 1 and 'revised_message' not in saved and
                _same(request['game_state_id'], saved['state_id']))
            saved['revised_message'] = copy.deepcopy(details['message'])
            return True
    if event == 'request_accepted':
        if stage.include_completions:
            return False
        # First domains never start in request_accepted; the owner must freeze
        # MP84 evidence at the completed poll through its current Consumer.
        stage.reset()
        return True
    return False


def submitted(stage, terminal):
    try:
        context = terminal['role_context']; revised = context['revised_selection_evidence']
        _need(stage.client_submit_observed and context['update_record'] < context['revised_frozen_record'] < stage.record_ordinal and
            _same(terminal['witness'], _witness(stage.reducer, revised['target_constraints'], context['historical_selected_target'])))
        context.update(status='historical_target_stage_complete', terminal_submit_binding=copy.deepcopy(context['revised_request_binding']),
            terminal_consumed=True, terminal_record=stage.record_ordinal)
        c = stage.player_completions.player_counts
        c['strictly_paired_terminal_submits'] += 1; c['fully_linked_historical_stages'] += 1
        stage.player_completions.player_last = context
    except _ERRORS:
        stage.client_submit_observed = False
