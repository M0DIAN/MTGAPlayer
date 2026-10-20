"""Explicit current one-offered-attacker-per-blocker research subset.

No mandatory-block inference, no no-block verdict, no global combat solver.
"""
import copy
import itertools
import threading

from .choice_candidates import _assess_current_report
from .choice_continuation import _scope
from .combat_frontier import BLOCK
from .current_target_request import _identity
from .decision_consumer import DecisionConsumer, EXECUTION, _bounded_json
from .decision_options import _option
from .request_parameters import LiteralRefs
from .semantic_combat import request as combat_request, check_request
from .semantic_samples import _need, _snapshot
from .cast_target_members import _equal
from .response_evidence import _current_verified_raw_request

VERSION = 'mtgaplayer.current-blocker-assignments.v1'
PROFILE = 'one_current_offered_attacker_per_listed_blocker'
SCOPE = 'whole_assignment_current_row_membership_and_explicit_max_one_only'
UNKNOWN = ('minimum_and_mandatory_blocking_unknown', 'global_combat_rules_unknown',
    'dynamic_restrictions_unknown', 'combat_costs_unknown', 'damage_order_and_assignment_unknown',
    'server_acceptance_unknown', 'response_encoding_unknown', 'strategic_utility_unknown')


def unknown(reason):
    return {'schema_version': VERSION, 'status': 'insufficient_evidence', 'reason': reason,
        'profile': PROFILE, 'request_binding': None, 'source_snapshot_ref': None,
        'blocker_row_count': None, 'offered_edge_count': None,
        'candidate_total_for_reviewed_profile': None, 'returned_candidates': 0,
        'truncated': False, 'candidates': [], 'count_scope': 'structural_subset_not_all_legal_blocks',
        'minimum_block_count': None, 'all_blockers_required_by_rules': None,
        'no_block_configuration_assessed': False, 'complete_legal_actions': None,
        'combat_cost': None, 'historical_response_used': False,
        'research_eligible': False, 'unknown': list(UNKNOWN), 'read_only': True,
        'complete_legality_verified': False, 'legal_choice_verified': False,
        'strategic_optimality_verified': False,
        'server_acceptance_verified': False, 'response_encoding_verified': False, **EXECUTION}


def _project(reducer, message, state, ref, completed_stamp, limit):
    from .raw_log import RawReducer
    from .shadow_runtime import _stamp
    _need(isinstance(reducer, RawReducer), 'same_current_reducer_required')
    current = _current_verified_raw_request(reducer, message)
    _need(current is not None and current['type'] == BLOCK and
          current.get('_blocker_evidence_interrupted') is not True,
          'uninterrupted_current_blocker_request_required')
    stamp = _stamp(reducer, message, state)
    _need(_equal(stamp, completed_stamp), 'completed_poll_context_changed')
    visible = state['visible_objects']
    public = reducer.document()['current']['objects']
    keys = ('instance_id', 'card_id', 'zone', 'owner_seat', 'controller_seat')
    _need(_equal([{k: o[k] for k in keys} for o in visible],
        [{'instance_id': o['id'], 'card_id': o['card_id'], 'zone': o['zone'],
          'owner_seat': o['owner'], 'controller_seat': o['controller']} for o in public]),
          'current_public_projection_mismatch')
    snapshot = _snapshot(reducer, LiteralRefs(), _scope(reducer))
    observed = combat_request(message, {'type': BLOCK}, LiteralRefs(), _scope(reducer), snapshot)
    rows = observed['payload']['blockers']
    _need(1 <= len(rows) <= 8 and all(r['selected_attacker_refs'] is None and
        type(r['candidate_attacker_refs']) is list and 1 <= len(r['candidate_attacker_refs']) <= 16
        for r in rows), 'complete_initial_offered_rows_required')
    frontier = state['legal_action_space']['immediate_frontier']
    _need(frontier['kind'] == 'declare_blockers' and frontier['availability'] == 'observed',
          'current_combat_frontier_required')
    projection = frontier['projection']
    listed = projection['engine_offered_candidates']
    _need(projection['combat_request_type'] == BLOCK and projection['truncated'] is False
        and len(listed) == len(rows), 'complete_current_combat_frontier_required')
    identities = {}
    total = 1
    for position, (row, offered) in enumerate(zip(rows, listed)):
        blocker, attackers = row['object_ref'], row['candidate_attacker_refs']
        _need(offered['candidate_position'] == position and offered['reference_verified'] is True
            and _equal(offered['candidate_instance_id'], blocker), 'blocker_row_identity_mismatch')
        edges = offered['engine_listed_attacker_references']
        _need(type(edges) is list and len(edges) == len(attackers) and all(
            e['public_reference_verified'] is True and e['list_position'] == index and
            _equal(e['attacker_instance_id'], target) for index, (target, e) in enumerate(zip(attackers, edges))),
            'current_row_attacker_identity_mismatch')
        for ident in (blocker, *attackers):
            identities[ident] = _identity(reducer, ident,
                ('GameObjectType_Card', 'GameObjectType_Token'), 'ZoneType_Battlefield')
        total *= len(attackers)  # bounded rows/edges, never expand the whole product
    candidates = []
    for position, targets in enumerate(itertools.islice(itertools.product(
            *(r['candidate_attacker_refs'] for r in rows)), limit)):
        proposed = copy.deepcopy(observed)
        for row, target in zip(proposed['payload']['blockers'], targets):
            row['selected_attacker_refs'] = [target]
        # Existing MP36 checker verifies WHOLE per-row capacity/membership and
        # side identities. Shared attackers are allowed, never globally deduped.
        check_request(proposed, snapshot, state['binding']['self_seat'])
        proposal = {'schema_version': VERSION, 'request_identity': copy.deepcopy(state['binding']),
            'source_snapshot_ref': copy.deepcopy(ref), 'blocker_assignments':[
                {'row_position': i, 'blocker_object_ref': row['object_ref'],
                 'attacker_object_ref': target} for i, (row, target) in enumerate(zip(rows, targets))]}
        option = _option(state['binding'], ref, 'reviewed_blocker_assignment', PROFILE,
                         position, proposal=proposal, scope=SCOPE)
        option.update(research_eligible=False, unresolved=list(UNKNOWN),
            local_validation={'status': 'verified_known_constraints', 'scope': SCOPE},
            complete_legality_verified=False, legal_choice_verified=False, strategic_optimality_verified=False,
            server_acceptance_verified=False, response_encoding_verified=False)
        candidates.append(option)
    after = _current_verified_raw_request(reducer, message)
    _need(after is not None and after.get('_blocker_evidence_interrupted') is not True and
        _equal(_stamp(reducer, message, state), stamp) and all(_equal(signature,
            _identity(reducer, ident, ('GameObjectType_Card', 'GameObjectType_Token'), 'ZoneType_Battlefield'))
            for ident, signature in identities.items()), 'current_blocker_context_changed')
    result = unknown('current_offered_rows_and_max_one_only')
    result.update(status='observed', request_binding=copy.deepcopy(state['binding']),
        source_snapshot_ref=copy.deepcopy(ref), blocker_row_count=len(rows),
        offered_edge_count=sum(len(r['candidate_attacker_refs']) for r in rows),
        candidate_total_for_reviewed_profile=total, returned_candidates=len(candidates),
        truncated=total > len(candidates), candidates=candidates,
        combat_cost='uninterpreted_single_empty_object')
    _bounded_json(result)
    return result


def assess_current_blocker_assignments(consumer, reducer, message, *, completed_stamp=None, limit=64):
    """Explicit trusted Owner context from the one completed Runtime poll.

    Data-only results are never cached or admitted to default policy options.
    Prefix/fixture replay is not private byte authentication or live gameplay.
    """
    if type(limit) is not int or not 1 <= limit <= 64:
        raise ValueError('invalid_current_blocker_assignment_limit')
    if not isinstance(consumer, DecisionConsumer): return unknown('requires_current_consumer')
    if threading.get_ident() != consumer._owner_thread_id: return unknown('owner_thread_required')
    if completed_stamp is None: return unknown('completed_poll_context_required')
    def evaluate(state, *, source_snapshot_ref):
        try: return _project(reducer, message, state, source_snapshot_ref, completed_stamp, limit)
        except (ValueError, TypeError, KeyError, IndexError, RecursionError, UnicodeError, OverflowError):
            return unknown('current_blocker_shape_identity_or_context_unreviewed')
    return _assess_current_report(consumer, evaluate, unknown)
