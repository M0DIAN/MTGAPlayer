"""Explicit nonempty current attacker-row structural research subset only."""
import copy
import threading

from .choice_candidates import _assess_current_report
from .choice_continuation import _scope
from .combat_frontier import ATTACK
from .current_target_request import _identity
from .decision_consumer import DecisionConsumer, EXECUTION, _bounded_json
from .decision_options import _option
from .request_parameters import LiteralRefs
from .semantic_combat import request as combat_request, check_request
from .semantic_samples import _need, _snapshot
from .cast_target_members import _equal
from .response_evidence import _current_verified_raw_request

VERSION = 'mtgaplayer.current-attacker-configurations.v1'
PROFILE = 'nonempty_initial_rows_single_offered_opposing_player'
SCOPE = 'whole_nonempty_attacker_row_structure_and_current_player_recipient_membership_only'
UNKNOWN = ('minimum_and_mandatory_attacking_unknown', 'unselected_row_legality_unknown',
    'global_combat_rules_unknown', 'dynamic_restrictions_unknown', 'combat_costs_unknown',
    'blocking_and_damage_assignment_unknown', 'server_acceptance_unknown',
    'response_encoding_unknown', 'strategic_utility_unknown')


def unknown(reason):
    return {'schema_version': VERSION, 'status': 'insufficient_evidence', 'reason': reason,
        'profile': PROFILE, 'request_binding': None, 'source_snapshot_ref': None,
        'attacker_row_count': None, 'offered_recipient_memberships': None,
        'candidate_total_for_reviewed_profile': None, 'returned_candidates': 0,
        'truncated': False, 'candidates': [], 'count_scope': 'nonempty_structural_subset_not_all_legal_attacks',
        'minimum_attack_count': None, 'zero_attack_configuration_assessed': False,
        'nonselection_legality_verified': False, 'mandatory_attack_requirements_verified': False,
        'complete_legal_actions': None, 'can_submit_attackers_literal': None,
        'combat_cost': None, 'historical_response_used': False, 'research_eligible': False,
        'unknown': list(UNKNOWN), 'read_only': True, 'complete_legality_verified': False,
        'legal_choice_verified': False, 'strategic_optimality_verified': False,
        'server_acceptance_verified': False, 'response_encoding_verified': False, **EXECUTION}


def _project(reducer, message, state, ref, completed_stamp, limit):
    from .raw_log import RawReducer
    from .shadow_runtime import _stamp
    _need(isinstance(reducer, RawReducer), 'same_current_reducer_required')
    current = _current_verified_raw_request(reducer, message)
    _need(current is not None and current['type'] == ATTACK and
        current.get('_attacker_evidence_interrupted') is not True,
        'uninterrupted_current_attacker_request_required')
    stamp = _stamp(reducer, message, state)
    _need(_equal(stamp, completed_stamp), 'completed_poll_context_changed')
    public = reducer.document()['current']['objects']
    keys = ('instance_id', 'card_id', 'zone', 'owner_seat', 'controller_seat')
    _need(_equal([{k: o[k] for k in keys} for o in state['visible_objects']],
        [{'instance_id': o['id'], 'card_id': o['card_id'], 'zone': o['zone'],
          'owner_seat': o['owner'], 'controller_seat': o['controller']} for o in public]),
        'current_public_projection_mismatch')
    snapshot = _snapshot(reducer, LiteralRefs(), _scope(reducer))
    # The existing parser/checker verifies typed identities, full qualified/row
    # equality, strict opposite Player recipients, known fields and cost shape.
    observed = combat_request(message, {'type': ATTACK}, LiteralRefs(), _scope(reducer), snapshot)
    rows = observed['payload']['attackers']
    _need(1 <= len(rows) <= 8 and all(r['selected_recipient'] is None and
        len(r['legal_recipients']) == 1 for r in rows), 'complete_initial_unselected_rows_required')
    frontier = state['legal_action_space']['immediate_frontier']
    _need(frontier['kind'] == 'declare_attackers' and frontier['availability'] == 'observed',
        'current_combat_frontier_required')
    projection = frontier['projection']; listed = projection['engine_offered_candidates']
    _need(projection['combat_request_type'] == ATTACK and projection['truncated'] is False and
        len(listed) == len(rows), 'complete_current_combat_frontier_required')
    identities = {}
    for position, (row, offered) in enumerate(zip(rows, listed)):
        ident = row['object_ref']
        _need(offered['candidate_position'] == position and offered['reference_verified'] is True and
            _equal(offered['candidate_instance_id'], ident) and offered['observed_recipient_count'] == 1,
            'attacker_row_identity_or_recipient_count_mismatch')
        identities[ident] = _identity(reducer, ident,
            ('GameObjectType_Card', 'GameObjectType_Token'), 'ZoneType_Battlefield')
    total = (1 << len(rows)) - 1
    candidates = []
    # A bounded nonempty hypothetical subset, never a must/need-not-attack proof.
    # All rows stay present. No omitted row or default/other-row recipient.
    for position, mask in enumerate(range(1, min(total, limit) + 1)):
        proposed = copy.deepcopy(observed)
        configuration = []
        for index, row in enumerate(proposed['payload']['attackers']):
            selected = bool(mask & (1 << index))
            recipient = copy.deepcopy(row['legal_recipients'][0]) if selected else None
            row['selected_recipient'] = recipient
            configuration.append({'row_position': index, 'attacker_object_ref': row['object_ref'],
                'selected': selected, 'selected_recipient': None if recipient is None else {
                    'namespace': 'player_system_seat', 'type': 'DamageRecType_Player', 'seat': recipient['seat']}})
        check_request(proposed, snapshot, state['binding']['self_seat'])
        proposal = {'schema_version': VERSION, 'request_identity': copy.deepcopy(state['binding']),
            'source_snapshot_ref': copy.deepcopy(ref), 'attacker_configuration': configuration}
        option = _option(state['binding'], ref, 'reviewed_attacker_configuration', PROFILE,
            position, proposal=proposal, scope=SCOPE)
        option.update(research_eligible=False, unresolved=list(UNKNOWN),
            local_validation={'status': 'verified_known_constraints', 'scope': SCOPE},
            nonselection_legality_verified=False, mandatory_attack_requirements_verified=False,
            complete_legality_verified=False, legal_choice_verified=False, strategic_optimality_verified=False,
            server_acceptance_verified=False, response_encoding_verified=False)
        candidates.append(option)
    after = _current_verified_raw_request(reducer, message)
    _need(after is not None and after.get('_attacker_evidence_interrupted') is not True and
        _equal(_stamp(reducer, message, state), stamp) and all(_equal(signature,
            _identity(reducer, ident, ('GameObjectType_Card', 'GameObjectType_Token'), 'ZoneType_Battlefield'))
            for ident, signature in identities.items()), 'current_attacker_context_changed')
    result = unknown('current_row_structure_and_offered_player_recipient_only')
    result.update(status='observed', request_binding=copy.deepcopy(state['binding']),
        source_snapshot_ref=copy.deepcopy(ref), attacker_row_count=len(rows),
        offered_recipient_memberships=sum(len(r['legal_recipients']) for r in rows),
        candidate_total_for_reviewed_profile=total, returned_candidates=len(candidates),
        truncated=total > len(candidates), candidates=candidates,
        can_submit_attackers_literal=observed['payload']['can_submit_attackers'],
        combat_cost='uninterpreted_single_empty_object')
    _bounded_json(result)
    return result


def assess_current_attacker_configurations(consumer, reducer, message, *, completed_stamp=None, limit=64):
    """Trusted same-Owner completed-poll context; no cached or default options."""
    if type(limit) is not int or not 1 <= limit <= 64:
        raise ValueError('invalid_current_attacker_configuration_limit')
    if not isinstance(consumer, DecisionConsumer): return unknown('requires_current_consumer')
    if threading.get_ident() != consumer._owner_thread_id: return unknown('owner_thread_required')
    if completed_stamp is None: return unknown('completed_poll_context_required')
    def evaluate(state, *, source_snapshot_ref):
        try: return _project(reducer, message, state, source_snapshot_ref, completed_stamp, limit)
        except (ValueError, TypeError, KeyError, IndexError, RecursionError, UnicodeError, OverflowError):
            return unknown('current_attacker_shape_identity_or_context_unreviewed')
    return _assess_current_report(consumer, evaluate, unknown)
