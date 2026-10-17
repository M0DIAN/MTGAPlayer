"""Opt-in Black1 member probes alongside the same request's Activate relation.

The client-code gate concerns offered data only. Prompt and target annotations
are retained; no UI choice, target quantity, payability or response is inferred.
"""
import copy
import sys

from . import cast_target_members as cast
from . import activate_target_payment as activate
from .semantic_samples import _need, _keys
from .decision_consumer import EXECUTION

PROFILE = 'current_offered_cast_activate_associations'
REQUEST_VERSION = 'mtgaplayer.request-parameters.v8'
VERSION = 'mtgaplayer.known-choice-candidates.v6'
SCOPE = 'separate_same_request_cast_members_and_activate_payment_associations'
CAST_PROFILE = 'current_black_one_cast_target_member'
CAST_SCOPE = 'same_current_black_one_cast_member_and_predictive_route'
ROUTING = 'multiple_actions_hand_battlefield_activate_no_opening_parameters_absent'


def _prompt(value):
    _keys(value, ('promptId',))
    _need(type(value['promptId']) is int and 0 < value['promptId'] < 2**32)


def _highlight_targets(value, refs, scope):
    """The newly witnessed target shape; retain every typed annotation."""
    from .raw_log import _id
    _need(type(value) is list and len(value) == 1)
    result = []
    for slot in value:
        _keys(slot, ('targetIdx', 'targets'))
        _need(_id(slot['targetIdx']) and slot['targetIdx'] > 0 and
            type(slot['targets']) is list and 1 <= len(slot['targets']) <= 64)
        entries = []
        for entry in slot['targets']:
            _keys(entry, ('targetInstanceId', 'highlight'))
            _need(type(entry['highlight']) is str and len(entry['highlight']) <= 128)
            entries.append({'targetInstanceId': refs.ref('object', scope, entry['targetInstanceId']),
                'highlight': entry['highlight']})
        result.append({'targetIdx': slot['targetIdx'], 'targets': entries})
    return result


def _literal(raw, kind):
    return cast._literal(raw, kind,
        target_projector=_highlight_targets if kind == 'ActionType_Cast' else None)


def cast_family(value):
    return value['cast_members'] if type(value) is dict and value.get('profile') == PROFILE else value


def activate_family(value):
    return value['activate_payment'] if type(value) is dict and value.get('profile') == PROFILE else value


def _routing(rows, visible):
    """Finite predicates excluding special/resolution/single/multi-zone routes.

    Under the inspected build, Hand and Battlefield are never NHC-remapped.
    An active Activate excludes all-resolution-Cast even with a resolving card.
    This does not establish the running UI's Loop/roundtrip behavior.
    """
    objects = {o['instance_id']: o for o in visible}
    _need(1 < len(rows) <= 256 and all(r['action_type'] != 'ActionType_OpeningHandAction' for r in rows))
    _need(any(r['action_type'] == 'ActionType_Activate' and
        objects.get(r['identifier_refs'].get('instanceId'), {}).get('zone') == 'ZoneType_Battlefield' for r in rows))
    _need(any(r['action_type'] == 'ActionType_Cast' and
        objects.get(r['identifier_refs'].get('instanceId'), {}).get('zone') == 'ZoneType_Hand' for r in rows))


def project(message, visible, seat, public, hand, mana_sources, source_abilities):
    _need(type(message) is dict and set(message) == {'type', 'systemSeatIds', 'msgId',
        'gameStateId', 'prompt', 'actionsAvailableReq'} and message['type'] == 'GREMessageType_ActionsAvailableReq')
    _prompt(message['prompt'])
    body = message['actionsAvailableReq']
    _keys(body, ('actions', 'inactiveActions'))
    _need(type(body['inactiveActions']) is list and len(body['inactiveActions']) <= 256)
    members = cast._project_members(message, visible, seat, public, hand, mana_sources, literal_parser=_literal)
    _routing(members['rows'], visible)
    # Do not shadow another profile merely because a target-shaped Cast exists.
    _need(any(r['action']['parameters']['manaCost'] == [{'color': ['ManaColor_Black'], 'count': 1}]
        for r in members['cast_actions']))
    members['profile'] = CAST_PROFILE
    payment = activate.project(message, visible, seat, source_abilities, public)
    return {'profile': PROFILE, 'prompt': copy.deepcopy(message['prompt']), 'routing_scope': ROUTING,
        'inactive_action_count': len(body['inactiveActions']), 'cast_members': members, 'activate_payment': payment}


def assemble(rows, binding, visible):
    from .request_parameters import assemble as assemble_existing
    value = copy.deepcopy(rows)
    value.update(schema_version=REQUEST_VERSION, binding=copy.deepcopy(binding), historical_response_used=False)
    value['cast_members'].update(schema_version=REQUEST_VERSION, binding=copy.deepcopy(binding), historical_response_used=False)
    value['activate_payment'] = assemble_existing(value['activate_payment'], binding, visible, allow_target_payment_relation=True)
    check(value, binding, visible)
    return value


def check(value, binding, visible):
    from .decision_consumer import _binding, _integer
    _keys(value, ('schema_version', 'profile', 'binding', 'historical_response_used', 'prompt',
        'routing_scope', 'inactive_action_count', 'cast_members', 'activate_payment'))
    _need(value['schema_version'] == REQUEST_VERSION and value['profile'] == PROFILE and
        value['historical_response_used'] is False and cast._equal(value['binding'], binding) and value['routing_scope'] == ROUTING)
    _binding(value['binding'], complete=True)
    _prompt(value['prompt']); _integer(value['inactive_action_count'], 0, 256)
    members = value['cast_members']; payment = value['activate_payment']
    cast.check(members, binding, visible, literal_parser=_literal, profile=CAST_PROFILE, version=REQUEST_VERSION)
    activate.check(payment, binding, visible)
    _routing(members['rows'], visible)
    # Families are views of one inventory, never independently sourced ledgers.
    def identities(rows):
        return [{k: v for k, v in r.items() if k not in ('target_menu', 'ability_binding')} for r in rows]
    _need(cast._equal(identities(members['rows']), identities(payment['rows'])) and
        cast._equal(members['public_battlefield_refs'], payment['public_battlefield_refs']))


def check_space(space, binding, visible):
    from .request_parameters import check_space as check_existing
    value = space['request_parameters']
    cast.check_space({**space, 'request_parameters': value['cast_members']}, binding, visible)
    check_existing({**space, 'request_parameters': value['activate_payment']}, binding, visible,
        allow_targeted_activate=True, allow_target_payment_relation=True)


def black_route(value, position, visible):
    return cast._colored_route(value, position, visible, color='ManaColor_Black',
        unsupported='only_black_one_single_predictive_route_reviewed',
        missing_unit='black_one_predictive_unit_not_observed',
        consistent='same_request_black_one_route_and_member_consistent')


def check_black_member(value, member, position, visible):
    return cast.check_member(value['cast_members'], member, position, visible, route_check=black_route)


def unknown_cast(reason, ref=None):
    return {**cast.unknown(reason, ref), 'schema_version': VERSION, 'scope': CAST_SCOPE}


def unknown(reason, ref=None):
    return {'schema_version': VERSION, 'scope': SCOPE, 'status': cast.UNKNOWN, 'reason': reason,
        'request_binding': None, 'source_snapshot_ref': copy.deepcopy(ref),
        'engine_active_action_rows': None, 'inactive_action_rows': None,
        'returned_candidates': 0, 'returned_relations': 0,
        'cast_members': unknown_cast(reason, ref), 'activate_payment': activate.unknown(reason, ref),
        'families_jointly_executable': False, 'read_only': True, **cast.DENIALS, **EXECUTION}


def _expected_relations(state, value):
    """Recheck this finite family without trusting a validator's claimed GOOD.

    Reuse the existing member and Generic2 checkers; this is no new rules model.
    """
    from .action_target_menus import check_member
    from .semantic_activate import check_generic_two_route
    if type(value) is not dict or value.get('profile') != activate.PROFILE: return [], None
    rows = value['rows']; visible = state['visible_objects']; seat = state['binding']['self_seat']
    staged = [{**r, 'literal_action': None} for r in rows]
    for r in value['target_actions'] + value['mana_actions']:
        staged[r['list_position']]['literal_action'] = r['action']
    expected = []; statuses = [cast.UNKNOWN] * len(rows)
    for r in value['target_actions']:
        pos = r['list_position']; action = r['action']; slot = action['parameters']['targets'][0]
        member = {'identifier_refs': action['identifier_refs'], 'target_idx': slot['targetIdx'],
            'object_ref': slot['targets'][0]['targetInstanceId']}
        status, _, checks = check_member(activate.target_evidence(value), member, pos, visible, seat)
        if status != cast.GOOD:
            statuses[pos] = status; continue
        if not activate._own_public(member['object_ref'], visible, value['public_battlefield_refs'], seat): continue
        status, _, _ = check_generic_two_route(staged, action, action, visible, seat, checks)
        if status != cast.GOOD:
            statuses[pos] = status; continue
        payments = []
        for tap in action['parameters']['autoTapSolution']['autoTapActions']:
            matches = [m for m in value['mana_actions'] if
                m['action']['identifier_refs']['instanceId'] == tap['instanceId'] and
                m['action']['identifier_refs']['abilityGrpId'] == tap['abilityGrpId']]
            active = [i for i, row in enumerate(rows) if row['action_type'] == 'ActionType_Activate_Mana' and
                row['identifier_refs']['instanceId'] == tap['instanceId'] and row['identifier_refs']['abilityGrpId'] == tap['abilityGrpId']]
            if len(matches) != 1 or len(active) != 1 or matches[0]['list_position'] != active[0]: break
            m = matches[0]; unit = tap['manaPaymentOption']['mana'][0]
            source = next(o for o in visible if o['instance_id'] == tap['instanceId'])
            selection = {'instanceId': tap['instanceId'], 'abilityGrpId': tap['abilityGrpId'],
                'options': [{'mana': [{'color': unit['color'], 'count': 1}]}]}
            if (unit['color'] != 'ManaColor_Blue' or m['ability_binding'] != 'verified_observed_pair' or
                not cast._equal(m['action']['parameters'], {'manaPaymentOptions': [tap['manaPaymentOption']], 'manaSelections': [selection]}) or
                not activate._own_public(tap['instanceId'], visible, value['public_battlefield_refs'], seat) or
                source['card_id'] is not None and source['card_id'] != m['action']['identifier_refs']['grpId']): break
            payments.append({'list_position': m['list_position'], 'identifier_refs': m['action']['identifier_refs'],
                'flags': m['action']['flags'], 'current_tapped_literal': source['tapped']})
        else:
            statuses[pos] = activate.CONSISTENT
            expected.append({'list_position': pos, 'action_identifier_refs': action['identifier_refs'],
                'action_flags': action['flags'], 'target_member': member, 'mana_row_witnesses': payments,
                'relation_status': activate.CONSISTENT})
    return expected, statuses


def _check_reports(state, members, relation, ref, limit):
    """Pin both child contracts and join every positive back to this snapshot."""
    from .decision_consumer import _binding, _integer
    from .choice_validation import check_proposal
    value = state['legal_action_space']['request_parameters']; combined = type(value) is dict and value.get('profile') == PROFILE
    _keys(members, cast.unknown('contract'))
    _keys(relation, activate.unknown('contract'))
    _need(members['schema_version'] == (VERSION if combined else cast.VERSION) and
        members['scope'] == (CAST_SCOPE if combined else cast.SCOPE) and
        relation['schema_version'] == activate.VERSION and relation['scope'] == activate.SCOPE)
    for report in (members, relation):
        _need(report['read_only'] is True and cast._equal(report['source_snapshot_ref'], ref))
        fixed_false = (*cast.DENIALS, *EXECUTION) if report is members else tuple(
            k for k, v in activate.unknown('contract').items() if v is False)
        _need(all(report[k] is False for k in fixed_false))
        if report['request_binding'] is not None:
            _binding(report['request_binding'], complete=True)
            _need(cast._equal(report['request_binding'], state['binding']))
    _need(members['target_quantities'] == {'minimum': None, 'maximum': None, 'selected_count': None} and
        members['payment_source_readiness'] == relation['payment_source_readiness'] == 'unknown_not_evaluated' and
        relation['diagnostics_only'] is True)
    _integer(members['returned_candidates'], 0, limit); _integer(relation['returned_relations'], 0, 256)
    _need(type(members['candidates']) is list and len(members['candidates']) == members['returned_candidates'] and
        type(relation['relations']) is list and len(relation['relations']) == relation['returned_relations'])
    _need((members['status'] == 'reviewed_constraint_candidates_observed' and members['returned_candidates'] > 0 or
        members['status'] == cast.UNKNOWN and members['returned_candidates'] == 0) and
        (relation['status'] == activate.CONSISTENT and relation['returned_relations'] > 0 or
        relation['status'] == cast.UNKNOWN and relation['returned_relations'] == 0))
    family = cast_family(value); payment = activate_family(value)
    if members['engine_active_action_rows'] is not None:
        _need(type(family) is dict and family.get('profile') == (CAST_PROFILE if combined else cast.PROFILE))
        counts = {'engine_active_action_rows': len(family['rows']), 'reviewed_cast_rows': len(family['cast_actions']),
            'unknown_or_unreviewed_action_rows': len(family['rows']) - len(family['cast_actions']),
            'target_bearing_cast_rows': sum(r['action_type'] == 'ActionType_Cast' and
                (r['parameter_shapes'].get('targets', {}).get('element_count') or 0) > 0 for r in family['rows'])}
        for name, expected in counts.items():
            _integer(members[name], expected, expected)
    else:
        _integer(members['reviewed_cast_rows'], 0, 0)
        _need(members['target_bearing_cast_rows'] is None and
            members['unknown_or_unreviewed_action_rows'] is None)
    if members['returned_candidates']:
        _need(members['request_binding'] is not None and members['engine_active_action_rows'] is not None and
            members['reason'] == 'current_cast_members_verified')
        _need(type(family) is dict and family.get('profile') == (CAST_PROFILE if combined else cast.PROFILE))
        nodes = {n['action_key']['list_position']: n for n in state['legal_action_space']['choice_graph']['action_nodes']}
        seen = set()
        for candidate in members['candidates']:
            _keys(candidate, ('action_key', 'proposal', 'payment_witness'))
            proposal = candidate['proposal']; check_proposal(proposal)
            _need(cast._equal(proposal['request_identity'], state['binding']) and
                cast._equal(proposal.get('source_snapshot_ref'), ref) and 'proposed_cast_target_member' in proposal)
            pos = proposal['list_position']; member = proposal['proposed_cast_target_member']
            status, _, witness = cast.check_member(family, member, pos, state['visible_objects'],
                route_check=black_route if combined else cast.route)
            _need(status == cast.GOOD and cast._equal(candidate['payment_witness'], witness) and
                cast._equal(candidate['action_key'], nodes[pos]['action_key']))
            key = (pos, member['target_idx'], member['object_ref']); _need(key not in seen); seen.add(key)
    probes = members['member_probes']; _keys(probes, cast.unknown('contract')['member_probes'])
    for n in probes.values(): _integer(n, 0, 16384)
    _need(probes['examined'] <= 256 and probes['verified'] + probes['unknown'] + probes['contradicted'] == probes['examined'] and
        probes['examined'] + probes['unexamined'] == probes['observed'] and probes['returned'] == members['returned_candidates'] and
        probes['omitted_due_to_return_limit'] == probes['verified'] - probes['returned'])
    _need(type(members['truncated']) is bool and type(members['exhaustive_for_reviewed_constraints']) is bool)
    _need(probes['returned'] == min(probes['verified'], limit) and
        members['truncated'] is bool(probes['omitted_due_to_return_limit'] or probes['unexamined']) and
        (members['exhaustive_for_reviewed_constraints'] is not bool(probes['unknown'] or probes['unexamined'] or probes['omitted_due_to_return_limit'])
            if members['engine_active_action_rows'] is not None else members['exhaustive_for_reviewed_constraints'] is False))
    _need(members['candidate_total_for_reviewed_constraints'] is None and probes['verified'] == 0 or
        type(members['candidate_total_for_reviewed_constraints']) is int and members['candidate_total_for_reviewed_constraints'] == probes['verified'])
    if members['engine_active_action_rows'] is not None:
        # Coverage is checked against the current menus and actual 256 budget,
        # not just arithmetic supplied by the child report.
        expected_probes = dict.fromkeys(probes, 0); expected_candidates = []
        nodes = {n['action_key']['list_position']: n for n in state['legal_action_space']['choice_graph']['action_nodes']}
        for record in family['cast_actions']:
            pos = record['list_position']; action = record['action']; slot = action['parameters']['targets'][0]
            status, _, witness = (black_route if combined else cast.route)(family, pos, state['visible_objects'])
            for target in slot['targets']:
                expected_probes['observed'] += 1
                if expected_probes['examined'] >= 256:
                    expected_probes['unexamined'] += 1; continue
                expected_probes['examined'] += 1
                expected_probes[{cast.GOOD: 'verified', cast.UNKNOWN: 'unknown', cast.BAD: 'contradicted'}[status]] += 1
                if status == cast.GOOD and len(expected_candidates) < limit:
                    proposal = {'request_identity': state['binding'], 'list_position': pos,
                        'proposed_cast_target_member': {'identifier_refs': action['identifier_refs'], 'flags': action['flags'],
                            'target_idx': slot['targetIdx'], 'object_ref': target['targetInstanceId']}}
                    if ref is not None: proposal['source_snapshot_ref'] = ref
                    expected_candidates.append({'action_key': nodes[pos]['action_key'], 'proposal': proposal, 'payment_witness': witness})
        expected_probes['returned'] = len(expected_candidates)
        expected_probes['omitted_due_to_return_limit'] = expected_probes['verified'] - expected_probes['returned']
        _need(cast._equal(probes, expected_probes) and cast._equal(members['candidates'], expected_candidates))
    expected_relations, expected_statuses = _expected_relations(state, payment)
    _need(cast._equal(relation['relations'], expected_relations))
    if relation['returned_relations']:
        _need(relation['request_binding'] is not None)
    coverage = relation['action_row_coverage']
    if coverage is not None:
        _keys(coverage, ('engine_active_action_rows', 'consistent_relation_rows', 'contradicted_known_relation_rows', 'unknown_or_unreviewed_rows', 'row_statuses'))
        _need(type(payment) is dict and payment.get('profile') == activate.PROFILE)
        count = len(payment['rows'])
        for name in ('engine_active_action_rows', 'consistent_relation_rows', 'contradicted_known_relation_rows', 'unknown_or_unreviewed_rows'):
            _integer(coverage[name], 0, count)
        _need(coverage['engine_active_action_rows'] == count and coverage['consistent_relation_rows'] == relation['returned_relations'] and
            coverage['consistent_relation_rows'] + coverage['contradicted_known_relation_rows'] + coverage['unknown_or_unreviewed_rows'] == count and
            type(coverage['row_statuses']) is list and len(coverage['row_statuses']) == count)
        positions = []
        for i, row in enumerate(coverage['row_statuses']):
            _keys(row, ('list_position', 'relation_status')); _integer(row['list_position'], i, i)
            _need(row['relation_status'] in (cast.UNKNOWN, cast.BAD, activate.CONSISTENT))
            if row['relation_status'] == activate.CONSISTENT: positions.append(i)
        _need(positions == [r['list_position'] for r in relation['relations']])
        _need([r['relation_status'] for r in coverage['row_statuses']] == expected_statuses and
            coverage['contradicted_known_relation_rows'] == expected_statuses.count(cast.BAD) and
            coverage['unknown_or_unreviewed_rows'] == expected_statuses.count(cast.UNKNOWN))
    else:
        _need(relation['returned_relations'] == 0)


def enumerate_associations(state, *, source_snapshot_ref=None, limit=64):
    from .decision_consumer import _state, _bounded_json, _reference
    try:
        _bounded_json(state); _state(state, state['binding'])
        if source_snapshot_ref is not None:
            _reference(source_snapshot_ref, source_snapshot_ref['session_id'], source_snapshot_ref['sequence'], snapshot=True)
            _need(cast._equal(source_snapshot_ref['binding'], state['binding']))
        value = state['legal_action_space']['request_parameters']
        if type(value) is dict and value.get('profile') == PROFILE:
            members = cast.enumerate_members(state, source_snapshot_ref=source_snapshot_ref,
                limit=limit, _review=sys.modules[__name__])
            inactive = value['inactive_action_count']
        else:
            # Existing public Blue1 and Activate profiles retain their own bounds.
            members = cast.enumerate_members(state, source_snapshot_ref=source_snapshot_ref, limit=limit)
            inactive = None
        relation = activate.evaluate_relation(state, source_snapshot_ref=source_snapshot_ref)
        _check_reports(state, members, relation, source_snapshot_ref, limit)
        result = unknown('no_reviewed_associations', source_snapshot_ref)
        result.update(request_binding=copy.deepcopy(state['binding']), cast_members=members, activate_payment=relation,
            engine_active_action_rows=members['engine_active_action_rows'] if members['engine_active_action_rows'] is not None else
                (relation['action_row_coverage']['engine_active_action_rows'] if relation['action_row_coverage'] else None),
            inactive_action_rows=inactive, returned_candidates=members['returned_candidates'], returned_relations=relation['returned_relations'])
        if result['returned_candidates'] or result['returned_relations']:
            result.update(status='reviewed_offered_associations_observed', reason='separate_current_families_observed')
        _bounded_json(result)
        return result
    except (ValueError, TypeError, KeyError, IndexError, RecursionError, UnicodeError, OverflowError):
        return unknown('state_or_request_evidence_invalid')
