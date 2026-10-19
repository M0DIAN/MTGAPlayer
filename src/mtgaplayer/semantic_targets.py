"""One observed public single-slot target slice; no complete legality claim.

The same finite projection/checker serves current requests and portable history.
Select/Unselect remain literal per-entry operations, not a complete rules model.
"""
import copy

from .raw_log import _id
from .semantic_samples import _need, _keys, SampleError

VERSION = 'mtgaplayer.semantic-samples.v4'
PROFILE = 'reviewed_single_slot_public_targets'
SCOPE = 'current_single_slot_final_set_membership_and_count'
SELECT = 'SelectAction_Select'
UNSELECT = 'SelectAction_Unselect'


def _number(value):
    return type(value) is int and 0 <= value <= 256


def _objects(visible):
    result = {}
    for row in visible:
        ident = row['object_ref']
        _need(_id(ident) and ident not in result)
        result[ident] = row
    return result


def project_request(message, visible, seat, refs, scope, *, allow_no_cancel=False, referent_roles=None):
    """Only after accepted request authentication and existing visibility filtering."""
    _need(type(message) is dict and not set(message)-{'type', 'msgId', 'gameStateId',
        'systemSeatIds', 'prompt', 'allowCancel', 'allowUndo', 'selectTargetsReq'}, 'request_unsupported')
    _need(message['type'] == 'GREMessageType_SelectTargetsReq', 'request_unsupported')
    _need(type(allow_no_cancel) is bool)
    _need((message.get('allowCancel') == 'AllowCancel_Abort' or
           allow_no_cancel and message.get('allowCancel') == 'AllowCancel_No') and
          ('allowUndo' not in message or type(message['allowUndo']) is bool), 'request_unsupported')
    body = message.get('selectTargetsReq')
    _keys(body, ('sourceId', 'abilityGrpId', 'targets'))
    _need(type(body['targets']) is list and len(body['targets']) == 1, 'request_unsupported')
    slot = body['targets'][0]
    _need(type(slot) is dict and {'targetIdx', 'targetingAbilityGrpId', 'targetingPlayer'} <= slot.keys()
          and not set(slot)-{'targetIdx', 'targetingAbilityGrpId', 'targetingPlayer', 'minTargets',
                            'maxTargets', 'selectedTargets', 'targets', 'prompt'}, 'request_unsupported')
    _need(all(_id(v) for v in (body['sourceId'], body['abilityGrpId'], slot['targetIdx'],
                              slot['targetingAbilityGrpId'])) and
          type(slot['targetingPlayer']) is int and slot['targetingPlayer'] == seat, 'request_unsupported')
    entries = None
    if 'targets' in slot:
        _need(type(slot['targets']) is list and len(slot['targets']) <= 256, 'request_unsupported')
        entries = []
        for position, row in enumerate(slot['targets']):
            _need(type(row) is dict and set(row) in ({'targetInstanceId', 'legalAction'},
                {'targetInstanceId', 'legalAction', 'highlight'}), 'request_unsupported')
            _need(_id(row['targetInstanceId']) and row['legalAction'] in (SELECT, UNSELECT), 'request_unsupported')
            # Highlight is presentation-only. Its value never leaves this boundary.
            _need('highlight' not in row or type(row['highlight']) is str, 'request_unsupported')
            if referent_roles is None:
                entries.append({'object_ref': refs.ref('object', scope, row['targetInstanceId']),
                                'legal_action': row['legalAction']})
            else:
                member = copy.deepcopy(referent_roles[row['targetInstanceId']])
                _need(member['list_position'] == position)
                entries.append({**member, 'legal_action': row['legalAction']})
        if referent_roles is not None:
            ids = [row['targetInstanceId'] for row in slot['targets']]
            _need(len(ids) == len(set(ids)) and set(ids) == set(referent_roles))
    value = {'source_object_ref': refs.ref('object', scope, body['sourceId']),
        'ability_grp_ref': refs.ref('abilityGrpId', scope, body['abilityGrpId']),
        'targeting_ability_grp_ref': refs.ref('targetingAbilityGrpId', scope, slot['targetingAbilityGrpId']),
        'target_idx': slot['targetIdx'], 'targeting_player': slot['targetingPlayer'],
        'min_targets': slot.get('minTargets'), 'max_targets': slot.get('maxTargets'),
        'selected_count': slot.get('selectedTargets'), 'entries': entries,
        'allow_cancel': message['allowCancel'], 'allow_undo': message.get('allowUndo')}
    if referent_roles is None:
        check_request(value, visible, seat, allow_no_cancel=allow_no_cancel)
    else:
        check_referent_request(value, visible, seat, allow_no_cancel=allow_no_cancel)
    return value


def check_referent_request(value, visible, seat, *, allow_no_cancel=False):
    """Explicit role contract; never feeds player IDs into legacy object_refs."""
    base = {**value, 'entries': None}
    check_request(base, visible, seat, allow_no_cancel=allow_no_cancel)
    _need(type(value['entries']) is list and 1 <= len(value['entries']) <= 64)
    objects = _objects(visible)
    seen = set()
    for position, row in enumerate(value['entries']):
        _keys(row, ('target_instance_ref', 'target_referent_kind', 'namespace', 'player_seat',
            'public_object_ref', 'object_type', 'zone', 'reason', 'list_position', 'legal_action'))
        ident, kind = row['target_instance_ref'], row['target_referent_kind']
        _need(type(ident) is int and 0 < ident <= 2**32-1 and row['list_position'] == position and
            type(row['list_position']) is int and row['legal_action'] in (SELECT, UNSELECT))
        if kind == 'verified_player':
            _need(row['namespace'] == 'version_verified_player_instance' and type(row['player_seat']) is int and
                row['player_seat'] in (1, 2) and ident == row['player_seat'] and ident not in objects and
                all(row[k] is None for k in ('public_object_ref', 'object_type', 'zone', 'reason')))
        elif kind == 'verified_public_object':
            _need(row['namespace'] == 'public_game_object' and row['public_object_ref'] == ident and
                type(row['public_object_ref']) is int and ident in objects and
                objects[ident]['zone'] == row['zone'] == 'ZoneType_Battlefield' and
                row['object_type'] in ('GameObjectType_Card', 'GameObjectType_Token') and
                row['player_seat'] is None and row['reason'] is None)
        else:
            _need(kind == 'unresolved' and row['namespace'] == 'unresolved_request_member' and
                ident == position+1 and all(row[k] is None for k in
                    ('player_seat', 'public_object_ref', 'object_type', 'zone')) and
                row['reason'] in ('player_entity_collision', 'player_list_unverified', 'target_role_unreviewed'))
        key = (row['namespace'], ident)
        _need(key not in seen); seen.add(key)


def referent_identity(row):
    return tuple((type(row[k]).__name__, row[k]) for k in ('target_referent_kind',
        'namespace', 'target_instance_ref', 'player_seat', 'public_object_ref',
        'object_type', 'zone', 'reason', 'list_position', 'legal_action'))


def check_referent_final_set(request, proposed):
    """Membership/count only for the explicit namespaced offered role domain."""
    _keys(proposed, ('source_object_ref', 'target_idx', 'target_referents'))
    _need(type(proposed['target_referents']) is list and len(proposed['target_referents']) <= 64)
    if any(type(proposed[k]) is not int or proposed[k] != request[k] for k in ('source_object_ref', 'target_idx')):
        return 'insufficient_evidence', 'proposal_binding_invalid'
    entries = request['entries']
    if not entries or any(r['legal_action'] != SELECT or r['target_referent_kind'] == 'unresolved' for r in entries):
        return 'insufficient_evidence', 'complete_current_referent_domain_not_observed'
    minimum, maximum = request['min_targets'], request['max_targets']
    if minimum is None or maximum is None:
        return 'insufficient_evidence', 'final_target_count_bounds_not_observed'
    for row in proposed['target_referents']:
        _keys(row, ('target_instance_ref', 'target_referent_kind', 'namespace', 'player_seat',
            'public_object_ref', 'object_type', 'zone', 'reason', 'list_position', 'legal_action'))
    chosen = [referent_identity(r) for r in proposed['target_referents']]
    if len(set(chosen)) != len(chosen):
        return 'violated_known_constraints', 'final_target_set_contains_duplicates'
    if not minimum <= len(chosen) <= maximum:
        return 'violated_known_constraints', 'final_target_count_outside_observed_bounds'
    offered = {referent_identity(r) for r in entries}
    if any(r not in offered for r in chosen):
        return 'violated_known_constraints', 'target_outside_current_referent_domain'
    return 'verified_known_constraints', 'role_set_satisfies_observed_membership_and_count'


def check_request(value, visible, seat, *, allow_no_cancel=False):
    _keys(value, ('source_object_ref', 'ability_grp_ref', 'targeting_ability_grp_ref',
        'target_idx', 'targeting_player', 'min_targets', 'max_targets', 'selected_count',
        'entries', 'allow_cancel', 'allow_undo'))
    _need(all(_id(value[k]) for k in ('source_object_ref', 'ability_grp_ref',
                                     'targeting_ability_grp_ref', 'target_idx')))
    _need(type(value['targeting_player']) is int and value['targeting_player'] == seat)
    _need(type(allow_no_cancel) is bool)
    _need((value['allow_cancel'] == 'AllowCancel_Abort' or
           allow_no_cancel and value['allow_cancel'] == 'AllowCancel_No') and
          (value['allow_undo'] is None or type(value['allow_undo']) is bool))
    for key in ('min_targets', 'max_targets', 'selected_count'):
        _need(value[key] is None or _number(value[key]))
    if value['min_targets'] is not None and value['max_targets'] is not None:
        _need(value['min_targets'] <= value['max_targets'])
    objects = _objects(visible)
    _need(value['source_object_ref'] in objects and
          objects[value['source_object_ref']]['zone'] == 'ZoneType_Stack')
    entries = value['entries']
    if entries is not None:
        _need(type(entries) is list and len(entries) <= 256)
        seen = set()
        for row in entries:
            _keys(row, ('object_ref', 'legal_action'))
            ident = row['object_ref']
            _need(_id(ident) and ident in objects and ident not in seen and
                  objects[ident]['zone'] == 'ZoneType_Battlefield' and row['legal_action'] in (SELECT, UNSELECT))
            seen.add(ident)


def check_final_set(request, proposed):
    """Count applies to a proposed complete set, never to an incremental update."""
    _keys(proposed, ('source_object_ref', 'target_idx', 'object_refs'))
    _need(_id(proposed['source_object_ref']) and _id(proposed['target_idx']) and
          type(proposed['object_refs']) is list and len(proposed['object_refs']) <= 256 and
          all(_id(x) for x in proposed['object_refs']))
    if any(proposed[k] != request[k] for k in ('source_object_ref', 'target_idx')):
        return 'insufficient_evidence', 'proposal_binding_invalid'
    chosen = proposed['object_refs']
    if len(set(chosen)) != len(chosen):
        return 'violated_known_constraints', 'final_target_set_contains_duplicates'
    minimum, maximum = request['min_targets'], request['max_targets']
    if ((minimum is not None and len(chosen) < minimum) or
            (maximum is not None and len(chosen) > maximum)):
        return 'violated_known_constraints', 'final_target_count_outside_observed_bounds'
    entries = request['entries']
    # A re-presented request containing only Unselect rows is not a complete
    # current domain. Never reuse a previous request's Select domain here.
    if entries is None or any(row['legal_action'] != SELECT for row in entries):
        return 'insufficient_evidence', 'complete_current_select_domain_not_observed'
    offered = {row['object_ref'] for row in entries}
    if any(x not in offered for x in chosen):
        return 'violated_known_constraints', 'target_outside_current_select_domain'
    if minimum is None or maximum is None:
        return 'insufficient_evidence', 'final_target_count_bounds_not_observed'
    return 'verified_known_constraints', 'final_set_satisfies_observed_membership_and_count'


def literal_selected(request):
    """The observed selected-count/Unselect shape only; no domain completeness."""
    rows = request['entries']
    count = request['selected_count']
    if (rows is not None and count is not None and len(rows) == count and
            all(row['legal_action'] == UNSELECT for row in rows)):
        return [row['object_ref'] for row in rows]
    return None


CURRENT_SELECTED_SCOPE = 'current_exact_one_selected_target_set_consistency'


def check_current_selected_proposal(proposed):
    """Explicit opt-in literal-set proposal, separate from a new Select domain."""
    _keys(proposed, ('source_object_ref', 'ability_grp_ref', 'targeting_ability_grp_ref',
                     'target_idx', 'targeting_player', 'object_refs'))
    _need(all(_id(proposed[k]) for k in ('source_object_ref', 'ability_grp_ref',
                                       'targeting_ability_grp_ref', 'target_idx')))
    _need(type(proposed['targeting_player']) is int and proposed['targeting_player'] in (1, 2))
    _need(type(proposed['object_refs']) is list and len(proposed['object_refs']) <= 256 and
          all(_id(ref) for ref in proposed['object_refs']))


def check_current_selected_set(request, proposed, visible, seat, public_stack):
    """One current 1/1/1 Unselect literal only; no history or response input.

    Bounds/count agreement is not complete quantity-rule or domain evidence.
    check_final_set deliberately retains its Select-only domain requirement.
    """
    from .decision_state import _stack
    _need(type(seat) is int and seat in (1, 2))
    check_request(request, visible, seat)
    check_current_selected_proposal(proposed)
    # The existing State Stack projection supplies explicit public membership
    # and object type. A null card ID never implies an Ability.
    _stack(public_stack, [{'instance_id': o['object_ref'], 'zone': o['zone']} for o in visible])
    if public_stack['availability'] != 'observed' or not any(
            row['instance_id'] == request['source_object_ref'] and
            row['object_type'] == 'GameObjectType_Ability' for row in public_stack['members']):
        return 'insufficient_evidence', 'current_public_stack_ability_not_observed'
    if any(type(request[k]) is not int or request[k] != 1 for k in
           ('min_targets', 'max_targets', 'selected_count')):
        return 'insufficient_evidence', 'exact_one_selected_request_profile_not_observed'
    selected = literal_selected(request)
    if selected is None or len(selected) != 1:
        return 'insufficient_evidence', 'exact_one_current_unselect_literal_not_observed'
    if any(proposed[k] != request[k] for k in ('source_object_ref', 'ability_grp_ref',
               'targeting_ability_grp_ref', 'target_idx', 'targeting_player')):
        return 'insufficient_evidence', 'proposal_binding_invalid'
    if proposed['object_refs'] != selected:
        return 'violated_known_constraints', 'proposal_differs_from_current_selected_literal'
    return 'verified_known_constraints', 'current_selected_literal_satisfies_explicit_one_bounds'


def action_targets(value, refs, scope):
    """Cast action candidates lack selection counts; preserve them as literals."""
    _need(type(value) is list and len(value) <= 64, 'request_unsupported')
    result = []
    for slot in value:
        _keys(slot, ('targetIdx', 'targets'))
        _need(_id(slot['targetIdx']) and type(slot['targets']) is list and len(slot['targets']) <= 256,
              'request_unsupported')
        rows = []
        for row in slot['targets']:
            _keys(row, ('targetInstanceId',))
            _need(_id(row['targetInstanceId']), 'request_unsupported')
            rows.append({'targetInstanceId': refs.ref('object', scope, row['targetInstanceId'])})
        result.append({'targetIdx': slot['targetIdx'], 'targets': rows})
    return result


def action(row, refs, scope):
    from .semantic_cast import action as cast_action
    # The complete real inventory also contains an unchosen Activate cost
    # carrying an ability identifier. Retain that identifier as opaque; this
    # profile adds no interpretation of the cost/ability relationship.
    raw = copy.deepcopy(row); opaque = {}
    if type(raw) is dict and type(raw.get('manaCost')) is list:
        for index, amount in enumerate(raw['manaCost']):
            if type(amount) is dict and 'abilityGrpId' in amount:
                _need(set(amount) == {'color', 'count', 'abilityGrpId'} and _id(amount['abilityGrpId']),
                      'request_unsupported')
                opaque[index] = refs.ref('abilityGrpId', scope, amount.pop('abilityGrpId'))
    result = cast_action(raw, refs, scope, target_projector=action_targets)
    for index, ability in opaque.items():
        result['parameters']['manaCost'][index]['abilityGrpId'] = ability
    return result


def response(payload, binding, request, refs, scope):
    from .raw_log import TERMINAL_SUBMITS
    if payload.get('type') == 'ClientMessageType_SubmitTargetsReq':
        _keys(payload, ('type', 'respId', 'gameStateId'))
        _need(TERMINAL_SUBMITS.get(payload['type']) == binding['type'], 'response_unsupported')
        return {'kind': 'select_targets', 'payload': {'operation': 'final_submit'}}
    _keys(payload, ('type', 'respId', 'gameStateId', 'selectTargetsResp'))
    _need(payload['type'] == 'ClientMessageType_SelectTargetsResp', 'response_unsupported')
    _keys(payload['selectTargetsResp'], ('target',))
    target = payload['selectTargetsResp']['target']
    _keys(target, ('targetIdx', 'targets'))
    _need(target['targetIdx'] == request['target_idx'] and type(target['targets']) is list and
          len(target['targets']) == 1, 'response_unsupported')
    row = target['targets'][0]
    _need(type(row) is dict and set(row) in ({'targetInstanceId', 'legalAction'},
          {'targetInstanceId', 'legalAction', 'highlight'}) and _id(row['targetInstanceId']) and
          row['legalAction'] in (SELECT, UNSELECT), 'response_unsupported')
    chosen = {'object_ref': refs.ref('object', scope, row['targetInstanceId']), 'legal_action': row['legalAction']}
    _need(request['entries'] is not None and chosen in request['entries'], 'known_constraints_violated')
    return {'kind': 'select_targets', 'payload': {'operation': 'selection_update',
        'target_idx': target['targetIdx'], 'entries': [chosen]}}


def facts(gs, reducer, refs, scope, previous, current, request):
    """Explicit source resolution/submission only.

    Hidden-endpoint migrations and Return causation remain unprojected.
    """
    from .semantic_cast import _detail
    before = _objects(previous['objects']); after = _objects(current['objects'])
    source = request['source_object_ref']
    result = []; omitted = 0; unsupported = False
    annotations = gs.get('annotations', [])
    if type(annotations) is not list or len(annotations) > 512:
        return [], 'unsupported_target_annotation', 0
    for annotation in annotations:
        try:
            typ = annotation.get('type')
            if typ == ['AnnotationType_PlayerSubmittedTargets']:
                _keys(annotation, ('id', 'affectorId', 'affectedIds', 'type'))
                _need(annotation['affectorId'] == request['targeting_player'] and
                      [refs.ref('object', scope, x) for x in annotation['affectedIds']] == [source])
                _need(source in before or source in after)
                result.append({'kind': 'targets_submitted', 'source_object_ref': source})
            elif typ in (['AnnotationType_ResolutionStart'], ['AnnotationType_ResolutionComplete']):
                _keys(annotation, ('id', 'affectorId', 'affectedIds', 'type', 'details'))
                details = _detail(annotation); _keys(details, ('grpid',))
                _need(refs.ref('object', scope, annotation['affectorId']) == source and
                      [refs.ref('object', scope, x) for x in annotation['affectedIds']] == [source])
                obj = before.get(source, after.get(source)); _need(obj is not None and obj['card_id'] == details['grpid'])
                result.append({'kind': 'resolution_start' if typ[0].endswith('Start') else 'resolution_complete',
                               'source_object_ref': source})
            else:
                omitted += 1
        except (SampleError, KeyError, TypeError, ValueError):
            omitted += 1; unsupported = True
    return result, 'unsupported_target_annotation' if unsupported else 'reviewed_target_subset', omitted


def projection():
    from .semantic_combat import PROJECTION_V3
    return {**copy.deepcopy(PROJECTION_V3),
        'nonempty_action_parameters': 'reviewed_literal_mana_target_candidates_and_opaque_cost_ability_ref',
        'targets': 'single_slot_public_literals_and_actual_submission_chain',
        'target_selected_count_missing': 'unknown_not_zero', 'target_domain_after_selection': 'incomplete',
        'target_reachability_and_complete_legality': 'unverified'}


def _trace(trace, before, request):
    from .semantic_cast import TRACE_ENDS
    from .semantic_samples import _check_snapshot
    _keys(trace, ('status', 'truncated', 'next_request_ref', 'states'))
    _need(trace['status'] in TRACE_ENDS and type(trace['truncated']) is bool and
          trace['truncated'] == (trace['status'] == 'limit_reached'))
    _need((_id(trace['next_request_ref']) and trace['next_request_ref'] > 0)
          if trace['status'] == 'next_request_observed' else trace['next_request_ref'] is None)
    _need(type(trace['states']) is list and len(trace['states']) <= 64)
    if trace['status'] == 'not_observed':
        _need(not trace['states'])
    previous = before; seen = {before['state_ref']}; source = request['source_object_ref']
    for row in trace['states']:
        _keys(row, ('snapshot', 'previous_state_ref', 'facts', 'facts_status', 'omitted_annotations'))
        _check_snapshot(row['snapshot']); snapshot = row['snapshot']
        _need(row['previous_state_ref'] == previous['state_ref'] and snapshot['state_ref'] not in seen)
        seen.add(snapshot['state_ref'])
        _need(row['facts_status'] in ('reviewed_target_subset', 'unsupported_target_annotation') and
              type(row['omitted_annotations']) is int and 0 <= row['omitted_annotations'] <= 512)
        _need(type(row['facts']) is list and len(row['facts']) <= 512)
        for fact in row['facts']:
            kind = fact.get('kind')
            _keys(fact, ('kind', 'source_object_ref'))
            _need(kind in ('targets_submitted', 'resolution_start', 'resolution_complete') and
                  fact['source_object_ref'] == source)
            old_objects = _objects(previous['objects']); new_objects = _objects(snapshot['objects'])
            _need(source in old_objects or source in new_objects)
        previous = snapshot


def replay(document):
    from .semantic_samples import (_check_envelope, _check_episode_base, _check_successor)
    from .semantic_cast import replay as cast_replay, VERSION as V2, PROJECTION_V2
    from .semantic_combat import replay as combat_replay, VERSION as V3, PROJECTION_V3
    from .decision_consumer import EXECUTION
    _check_envelope(document, VERSION, projection())
    reports = []
    for index, sample in enumerate(document['samples']):
        kind = sample['request']['kind']
        if kind != 'select_targets':
            combat = kind in ('declare_attackers', 'declare_blockers')
            if kind == 'actions_available':
                public = {o['object_ref'] for o in sample['before']['objects'] if o['zone'] == 'ZoneType_Battlefield'}
                for action in [*sample['request']['payload']['actions'], sample['response']['payload']['action']]:
                    for slot in action['parameters'].get('targets', []):
                        _need(all(t['targetInstanceId'] in public for t in slot['targets']))
            one = copy.deepcopy(document); one['schema_version'] = V3 if combat else V2
            one['projection'] = copy.deepcopy(PROJECTION_V3 if combat else PROJECTION_V2)
            one['samples'] = [sample]; one['counts'] = {'matched_pairs': 1, 'exported': 1,
                'sample_limit_omissions': 0, 'unsupported_pairs': 0}; one['unsupported_reasons'] = []
            report = (combat_replay(one) if combat else cast_replay(one, target_actions=True))['samples'][0]
            report['sample_index'] = index; reports.append(report); continue
        _check_episode_base(sample, ('trace',)); request = sample['request']['payload']
        _keys(sample['request'], ('kind', 'payload'))
        check_request(request, sample['before']['objects'], sample['identity']['self_seat'])
        _keys(sample['response'], ('kind', 'payload')); _need(sample['response']['kind'] == kind)
        response = sample['response']['payload']; operation = response.get('operation')
        _need(operation in ('selection_update', 'final_submit'))
        if operation == 'selection_update':
            _keys(response, ('operation', 'target_idx', 'entries'))
            _need(response['target_idx'] == request['target_idx'] and type(response['entries']) is list and
                  len(response['entries']) == 1 and request['entries'] is not None and
                  response['entries'][0] in request['entries'])
        else:
            _keys(response, ('operation',))
        _check_successor(sample['successor'], sample['before']); _trace(sample['trace'], sample['before'], request)
        if sample['trace']['states']:
            _need(sample['successor']['status'] == 'continuous_state_observed' and
                  sample['successor']['snapshot'] == sample['trace']['states'][0]['snapshot'])
        elif sample['trace']['status'] == 'next_request_observed':
            _need(sample['successor']['status'] == 'next_request_observed' and
                  sample['successor']['request_ref'] == sample['trace']['next_request_ref'])
        else:
            expected = {'interrupted': 'interrupted',
                'full_baseline_not_continuous': 'full_baseline_not_continuous'}.get(
                    sample['trace']['status'], 'not_observed')
            _need(sample['successor']['status'] == expected)
        selected = literal_selected(request) if operation == 'final_submit' else None
        facts_seen = [f for s in sample['trace']['states'] if s['facts_status'] == 'reviewed_target_subset' for f in s['facts']]
        reports.append({'sample_index': index, 'request_kind': kind, 'validation_scope': SCOPE,
            'successor_status': sample['successor']['status'], 'trace_status': sample['trace']['status'],
            'target_evidence': {'operation': operation, 'literal_current_selected_refs': selected,
                'incremental_membership_verified': operation == 'selection_update',
                'final_submission_observed': operation == 'final_submit',
                'targets_submitted_annotation_observed': any(f['kind'] == 'targets_submitted' for f in facts_seen),
                'source_resolution_observed': all(any(f['kind'] == k for f in facts_seen) for k in ('resolution_start', 'resolution_complete')),
                'actual_selected_public_departure_observed': bool(selected) and any(
                    all(target not in _objects(s['snapshot']['objects']) for target in selected) for s in sample['trace']['states']),
                'return_causation': 'unverified',
                'linked_previous_actual_selection': False, 'linked_cast_origin': False,
                'complete_legality_verified': False, 'server_acceptance_verified': False}})
    # Existing next-request references are the only cross-episode linkage.
    for index, sample in enumerate(document['samples']):
        if sample['request']['kind'] != 'select_targets': continue
        current = reports[index]['target_evidence']; req = sample['request']['payload']
        for earlier_index, earlier in enumerate(document['samples'][:index]):
            if (earlier['identity']['match_ref'] != sample['identity']['match_ref'] or
                    earlier['identity']['game'] != sample['identity']['game'] or
                    earlier['identity']['self_seat'] != sample['identity']['self_seat'] or
                    earlier['trace']['next_request_ref'] != sample['identity']['request_ref'] or
                    earlier['trace']['status'] != 'next_request_observed'):
                continue
            states = earlier['trace']['states']
            endpoint = states[-1]['snapshot'] if states else earlier['before']
            if not states:
                # With no intervening accepted state, a request-only successor
                # must still describe the unchanged visible endpoint.
                _need(earlier['successor']['status'] == 'next_request_observed' and
                      earlier['successor']['snapshot'] == endpoint)
            # State reference equality alone cannot reconcile contradictory
            # object, player or turn observations across an episode boundary.
            _need(endpoint == sample['before'])
            if earlier['request']['kind'] == 'select_targets':
                p = earlier['request']['payload']; response = earlier['response']['payload']
                same = all(req[k] == p[k] for k in ('source_object_ref', 'ability_grp_ref',
                    'targeting_ability_grp_ref', 'target_idx', 'targeting_player'))
                if same and response['operation'] == 'selection_update' and current['literal_current_selected_refs'] is not None:
                    current['linked_previous_actual_selection'] = (
                        current['literal_current_selected_refs'] == [r['object_ref'] for r in response['entries']]
                        and all(r['legal_action'] == SELECT for r in response['entries']))
                    if current['linked_previous_actual_selection']:
                        current['linked_cast_origin'] = reports[earlier_index]['target_evidence']['linked_cast_origin']
            elif earlier['request']['kind'] == 'actions_available':
                action = earlier['response']['payload']['action']
                if action['action_type'] != 'ActionType_Cast': continue
                original = action['identifier_refs'].get('instanceId')
                fs = [f for s in earlier['trace']['states'] if s['facts_status'] == 'reviewed_subset' for f in s['facts']]
                current['linked_cast_origin'] = (reports[earlier_index]['cast_evidence']['cast_on_stack_observed'] and
                    any(f['kind'] == 'object_id_changed' and
                    f['original_object_ref'] == original and f['new_object_ref'] == req['source_object_ref'] for f in fs) and
                    any(f['kind'] == 'zone_transfer' and f['object_ref'] == req['source_object_ref'] and f['category'] == 'CastSpell' for f in fs))
    return {'schema_version': 'mtgaplayer.semantic-sample-replay.v4', 'samples': reports,
        'artifact_checks_passed': True, 'raw_source_auth_revalidated': False,
        'complete_legality_verified': False, 'server_acceptance_verified': False,
        'read_only': True, 'execution': dict(EXECUTION)}
