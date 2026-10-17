"""Opt-in finite hand checks/observations; never a rules solver or input grant.

V6 adds London/AcceptHand and one TurnBased/Discard shape to v4. Identity and
continuity remain owned by RawReducer and the established response gate. Only
the first continuous successor belongs to these narrow observation episodes.
"""
import copy

from .raw_log import _id
from .semantic_samples import (_need, _keys, SampleError, _check_snapshot,
    _check_envelope, _check_episode_base, _check_successor)
from .semantic_cast import _detail


VERSION = 'mtgaplayer.semantic-samples.v6'
MULLIGAN = 'observed_london_accept_hand'
DISCARD = 'observed_turn_based_discard_single'
FIRST = 'first_continuous_state_observed'
ENDS = ('not_observed', 'eof', 'next_request_observed', 'interrupted',
        'full_baseline_not_continuous', FIRST)
UNKNOWN = ('allow_cancel', 'source_object_ref', 'unfiltered_domain', 'min_weight', 'max_weight')
ENUMS = {'id_type': 'IdType_InstanceId', 'list_type': 'SelectionListType_Dynamic',
    'context': 'SelectionContext_Discard', 'option_context': 'OptionContext_TurnBased',
    'validation_type': 'SelectionValidationType_NonRepeatable'}
CURRENT_PROFILE = 'current_visible_own_hand_discard_one_of_eight'
CURRENT_SCOPE = 'current_offered_one_of_eight_discard_consistency'


def check_current_discard(request, visible, seat):
    """Reuse the historical request check on current visible-to-self objects.

    This new current profile deliberately supports only the observed eight-offer
    shape. The legacy projector/check_request and unknown fields stay unchanged.
    """
    _need(type(seat) is int and seat in (1, 2) and type(visible) is list and len(visible) <= 512)
    refs = [obj['instance_id'] for obj in visible]
    _need(all(_id(ref) and ref > 0 for ref in refs) and len(refs) == len(set(refs)))
    snapshot = {'objects': [{'object_ref': obj['instance_id'], 'zone': obj['zone'],
        'owner': obj['owner_seat']} for obj in visible]}
    _need(request['kind'] == 'select_n' and request['payload']['profile'] == DISCARD)
    check_request(request, snapshot, seat)
    _need(len(request['payload']['offered_object_refs']) == 8)
    for obj in visible:
        if obj['instance_id'] in request['payload']['offered_object_refs']:
            _need(type(obj['owner_seat']) is int and obj['owner_seat'] == seat)


def check_current_discard_selection(request, selected, visible, seat):
    """Same-request single member/count consistency, without an outcome argument."""
    try:
        check_current_discard(request, visible, seat)
        _need(type(selected) is list and len(selected) <= 256 and
              all(_id(ref) and ref > 0 for ref in selected))
        check_response({'kind': 'select_n', 'payload': {'selected_object_refs': selected}}, request)
        return 'verified_known_constraints', 'current_single_offered_own_hand_member'
    except (SampleError, KeyError, TypeError) as exc:
        if isinstance(exc, SampleError) and str(exc) == 'known_constraints_violated':
            return 'violated_known_constraints', 'single_nonrepeatable_offered_selection_required'
        return 'insufficient_evidence', 'current_discard_constraints_not_verified'


def projection():
    from .semantic_targets import projection as v4_projection
    return {**v4_projection(), 'hand_choices': 'london_accept_and_single_turn_based_discard',
        'hand_trace': 'first_continuous_successor_only',
        'hand_prompt_numbers': 'uninterpreted_literals_without_prompt_identifiers',
        'hand_missing_constraints': 'unknown_not_protocol_defaults',
        'hand_complete_legality_and_server_acceptance': 'unverified'}


def is_hand(request):
    return (isinstance(request, dict) and (request.get('kind') == 'mulligan' or
        request.get('kind') == 'select_n' and isinstance(request.get('payload'), dict) and
        request['payload'].get('profile') == DISCARD))


def _numbers(value):
    _need(type(value) is list and len(value) == 1 and
          type(value[0]) is int and 0 <= value[0] <= 99)


def _prompt(value):
    _keys(value, ('promptId', 'parameters'))
    _need(_id(value['promptId']) and type(value['parameters']) is list and len(value['parameters']) == 1)
    parameter = value['parameters'][0]
    _keys(parameter, ('parameterName', 'type', 'numberValue'))
    _need(type(parameter['parameterName']) is str and 0 < len(parameter['parameterName']) <= 128 and
          parameter['type'] == 'ParameterType_Number')
    result = [parameter['numberValue']]
    _numbers(result)
    return result


def _objects(snapshot):
    return {obj['object_ref']: obj for obj in snapshot['objects']}


def _hand(snapshot, seat):
    return {obj['object_ref'] for obj in snapshot['objects']
            if obj['zone'] == 'ZoneType_Hand' and obj['owner'] == seat}


def check_request(request, before, seat):
    _keys(request, ('kind', 'payload'))
    value = request['payload']
    if request['kind'] == 'mulligan':
        _keys(value, ('profile', 'mulligan_type', 'prompt_numbers', 'choice_domain',
                      'mulligan_count', 'bottom_count', 'remaining_attempts'))
        _need(value['profile'] == MULLIGAN and value['mulligan_type'] == 'MulliganType_London' and
              all(value[key] is None for key in ('choice_domain', 'mulligan_count', 'bottom_count', 'remaining_attempts')))
    else:
        _need(request['kind'] == 'select_n')
        _keys(value, ('profile', 'offered_object_refs', 'min_sel', 'max_sel',
                      'prompt_numbers', *ENUMS, *UNKNOWN))
        offered = value['offered_object_refs']
        _need(value['profile'] == DISCARD and type(offered) is list and 1 <= len(offered) <= 256 and
              all(_id(ref) and ref > 0 for ref in offered) and len(offered) == len(set(offered)) and
              set(offered) <= _hand(before, seat) and
              type(value['min_sel']) is int and type(value['max_sel']) is int and
              value['min_sel'] == value['max_sel'] == 1 and
              all(value[key] == expected for key, expected in ENUMS.items()) and
              all(value[key] is None for key in UNKNOWN))
    _numbers(value['prompt_numbers'])


def project_request(message, refs, scope, snapshot):
    """Return None for legacy requests, otherwise a strict observed projection."""
    typ = message.get('type')
    discard = typ == 'GREMessageType_SelectNReq' and isinstance(message.get('selectNReq'), dict) and \
        message['selectNReq'].get('context') == 'SelectionContext_Discard'
    if typ != 'GREMessageType_MulliganReq' and not discard:
        return None
    try:
        field = 'selectNReq' if discard else 'mulliganReq'
        _keys(message, ('type', 'systemSeatIds', 'msgId', 'gameStateId', 'prompt', field))
        numbers = _prompt(message['prompt'])
        body = message[field]
        if not discard:
            _keys(body, ('mulliganType',))
            result = {'kind': 'mulligan', 'payload': {'profile': MULLIGAN,
                'mulligan_type': body['mulliganType'], 'prompt_numbers': numbers,
                'choice_domain': None, 'mulligan_count': None, 'bottom_count': None, 'remaining_attempts': None}}
        else:
            _keys(body, ('minSel', 'maxSel', 'context', 'optionContext', 'listType',
                         'ids', 'idType', 'validationType'))
            ids = body['ids']
            _need(type(ids) is list and 1 <= len(ids) <= 256 and all(_id(ref) for ref in ids) and
                  len(ids) == len(set(ids)))
            result = {'kind': 'select_n', 'payload': {'profile': DISCARD,
                'offered_object_refs': [refs.ref('object', scope, ref) for ref in ids],
                'min_sel': body['minSel'], 'max_sel': body['maxSel'], 'prompt_numbers': numbers,
                'id_type': body['idType'], 'list_type': body['listType'], 'context': body['context'],
                'option_context': body['optionContext'], 'validation_type': body['validationType'],
                **dict.fromkeys(UNKNOWN)}}
        check_request(result, snapshot, scope[3])
        return result
    except (SampleError, KeyError, TypeError):
        raise SampleError('request_unsupported') from None


def check_response(response, request):
    _keys(response, ('kind', 'payload'))
    _need(response['kind'] == request['kind'])
    value = response['payload']
    if request['kind'] == 'mulligan':
        _keys(value, ('decision',))
        _need(value['decision'] == 'MulliganOption_AcceptHand')
    else:
        _keys(value, ('selected_object_refs',))
        selected = value['selected_object_refs']
        _need(type(selected) is list and all(_id(ref) and ref > 0 for ref in selected))
        _need(len(selected) == len(set(selected)) == 1 and
              set(selected) <= set(request['payload']['offered_object_refs']), 'known_constraints_violated')


def project_response(payload, request, refs, scope):
    try:
        mulligan = request['kind'] == 'mulligan'
        field = 'mulliganResp' if mulligan else 'selectNResp'
        expected = 'ClientMessageType_MulliganResp' if mulligan else 'ClientMessageType_SelectNResp'
        _keys(payload, ('type', 'respId', 'gameStateId', field))
        _need(payload['type'] == expected)
        if mulligan:
            _keys(payload[field], ('decision',))
            result = {'kind': 'mulligan', 'payload': {'decision': payload[field]['decision']}}
        else:
            _keys(payload[field], ('ids',))
            ids = payload[field]['ids']
            _need(type(ids) is list and len(ids) <= 256 and all(_id(ref) for ref in ids))
            result = {'kind': 'select_n', 'payload': {'selected_object_refs':
                [refs.ref('object', scope, ref) for ref in ids]}}
        check_response(result, request)
        return result
    except (SampleError, KeyError, TypeError) as exc:
        if isinstance(exc, SampleError) and str(exc) == 'known_constraints_violated':
            raise
        raise SampleError('response_unsupported') from None


def facts(gs, reducer, refs, scope, before, after, request, response, seat):
    annotations = gs.get('annotations', [])
    if type(annotations) is not list or len(annotations) > 512:
        return [], 'unsupported_hand_annotation', 0
    if request['kind'] == 'mulligan':
        return [], 'reviewed_hand_subset', len(annotations)
    old, new = _objects(before), _objects(after)
    selected = set(response['payload']['selected_object_refs'])
    changed, result, omitted, unsupported = set(), [], 0, False
    for annotation in annotations:
        try:
            typ = annotation.get('type') if type(annotation) is dict else None
            if typ not in (['AnnotationType_ObjectIdChanged'], ['AnnotationType_ZoneTransfer']):
                omitted += 1
                continue
            affected = annotation.get('affectedIds')
            if type(affected) is not list or len(affected) != 1 or not _id(affected[0]):
                omitted += 1
                unsupported = True
                continue
            obj = refs.ref('object', scope, affected[0])
            if obj not in selected | changed:
                omitted += 1
                continue
            _keys(annotation, ('id', 'type', 'affectedIds', 'details'))
            _need(_id(annotation['id']))
            detail = _detail(annotation)
            if typ == ['AnnotationType_ObjectIdChanged']:
                _keys(detail, ('orig_id', 'new_id'))
                _need(all(_id(value) for value in detail.values()) and affected == [detail['orig_id']])
                migrated = refs.ref('object', scope, detail['new_id'])
                _need(not changed and obj in selected and obj in old and obj not in new and old[obj]['zone'] == 'ZoneType_Hand' and
                      old[obj]['owner'] == seat and migrated not in old and migrated in new and
                      new[migrated]['zone'] == 'ZoneType_Graveyard' and new[migrated]['owner'] == seat)
                result.append({'kind': 'object_id_changed', 'original_object_ref': obj, 'new_object_ref': migrated})
                changed.add(migrated)
            else:
                _keys(detail, ('zone_src', 'zone_dest', 'category'))
                _need(_id(detail['zone_src']) and _id(detail['zone_dest']) and obj in changed and
                      not any(row['kind'] == 'discard_transfer' for row in result) and
                      detail['category'] == 'Discard' and
                      reducer.zones.get(detail['zone_src'], {}).get('type') == 'ZoneType_Hand' and
                      reducer.zones.get(detail['zone_dest'], {}).get('type') == 'ZoneType_Graveyard')
                result.append({'kind': 'discard_transfer', 'object_ref': obj,
                    'source_zone': 'ZoneType_Hand', 'destination_zone': 'ZoneType_Graveyard'})
        except (SampleError, KeyError, TypeError):
            omitted += 1
            unsupported = True
    return result, 'unsupported_hand_annotation' if unsupported else 'reviewed_hand_subset', omitted


def _trace(sample):
    trace, before = sample['trace'], sample['before']
    _keys(trace, ('status', 'truncated', 'next_request_ref', 'states'))
    _need(trace['status'] in ENDS and trace['truncated'] is False and
          type(trace['states']) is list and len(trace['states']) <= 1 and
          bool(trace['states']) == (trace['status'] == FIRST))
    _need((_id(trace['next_request_ref']) and trace['next_request_ref'] > 0)
          if trace['status'] == 'next_request_observed' else trace['next_request_ref'] is None)
    if not trace['states']:
        expected = {'interrupted': 'interrupted', 'full_baseline_not_continuous': 'full_baseline_not_continuous',
                    'next_request_observed': 'next_request_observed'}.get(trace['status'], 'not_observed')
        _need(sample['successor']['status'] == expected)
        if expected == 'next_request_observed':
            _need(sample['successor']['request_ref'] == trace['next_request_ref'] and
                  sample['successor']['snapshot'] == before)
        return
    row = trace['states'][0]
    _keys(row, ('snapshot', 'previous_state_ref', 'facts', 'facts_status', 'omitted_annotations'))
    _check_snapshot(row['snapshot'])
    _need(_id(row['previous_state_ref']) and row['previous_state_ref'] > 0 and
          row['previous_state_ref'] == before['state_ref'] and
          row['snapshot']['state_ref'] != before['state_ref'] and
          row['facts_status'] in ('reviewed_hand_subset', 'unsupported_hand_annotation') and
          type(row['omitted_annotations']) is int and 0 <= row['omitted_annotations'] <= 512 and
          type(row['facts']) is list and len(row['facts']) <= 2 and
          sample['successor']['status'] == 'continuous_state_observed' and
          sample['successor']['snapshot'] == row['snapshot'])
    if sample['request']['kind'] == 'mulligan':
        _need(row['facts'] == [])
        return
    old, new = _objects(before), _objects(row['snapshot'])
    selected = set(sample['response']['payload']['selected_object_refs'])
    migrated = set()
    seat = sample['identity']['self_seat']
    for fact in row['facts']:
        _need(type(fact) is dict)
        if fact.get('kind') == 'object_id_changed':
            _keys(fact, ('kind', 'original_object_ref', 'new_object_ref'))
            original, target = fact['original_object_ref'], fact['new_object_ref']
            _need(_id(original) and _id(target) and original in selected and not migrated and
                  original in old and original not in new and old[original]['zone'] == 'ZoneType_Hand' and old[original]['owner'] == seat and
                  target not in old and target in new and new[target]['zone'] == 'ZoneType_Graveyard' and
                  new[target]['owner'] == seat)
            migrated.add(target)
        else:
            _keys(fact, ('kind', 'object_ref', 'source_zone', 'destination_zone'))
            _need(fact['kind'] == 'discard_transfer' and _id(fact['object_ref']) and fact['object_ref'] > 0 and
                  fact['object_ref'] in migrated and
                  fact['source_zone'] == 'ZoneType_Hand' and fact['destination_zone'] == 'ZoneType_Graveyard')


def _evaluate(sample, index):
    before, trace = sample['before'], sample['trace']
    after = trace['states'][0]['snapshot'] if trace['states'] else None
    seat = sample['identity']['self_seat']
    result = {'sample_index': index, 'request_kind': sample['request']['kind'],
        'successor_status': sample['successor']['status'], 'trace_status': trace['status'],
        'validation_scope': 'observed_hand_choice_and_first_visible_successor_only',
        'visible_own_hand_count_before': len(_hand(before, seat)),
        'visible_own_hand_count_after': len(_hand(after, seat)) if after is not None else None,
        'complete_legality_verified': False, 'server_acceptance_verified': False}
    if sample['request']['kind'] == 'mulligan':
        result['mulligan_evidence'] = {'accept_hand_submission_observed': True,
            'first_visible_hand_refs_preserved': _hand(before, seat) == _hand(after, seat) if after is not None else None,
            'choice_domain': None, 'mulligan_count': None, 'bottom_count': None, 'remaining_attempts': None,
            'prompt_number_semantics': 'uninterpreted_literal'}
        return result
    selected = sample['response']['payload']['selected_object_refs']
    observed = False
    if after is not None and trace['states'][0]['facts_status'] == 'reviewed_hand_subset':
        old, new = _objects(before), _objects(after)
        facts_seen = trace['states'][0]['facts']
        for fact in facts_seen:
            if fact['kind'] != 'object_id_changed':
                continue
            original, target = fact['original_object_ref'], fact['new_object_ref']
            known_identity = old[original]['card_id'] is not None and old[original]['card_id'] == new[target]['card_id']
            observed |= known_identity and any(f['kind'] == 'discard_transfer' and f['object_ref'] == target for f in facts_seen)
    result['selected_option_positions'] = [sample['request']['payload']['offered_object_refs'].index(ref) for ref in selected]
    result['discard_evidence'] = {'selection_submission_observed': True,
        'known_count_and_membership': 'verified_known_constraints',
        'selected_card_discard_observed': bool(observed),
        'selected_card_result': 'verified_known_constraints' if observed else 'insufficient_evidence',
        'missing_constraints': dict.fromkeys(UNKNOWN)}
    return result


def replay(document):
    from .semantic_targets import replay as v4_replay, VERSION as V4, projection as v4_projection
    from .decision_consumer import EXECUTION
    _check_envelope(document, VERSION, projection())
    reports, legacy, indices = {}, [], []
    for index, sample in enumerate(document['samples']):
        _need(type(sample) is dict and type(sample.get('request')) is dict)
        if not is_hand(sample['request']):
            legacy.append(sample)
            indices.append(index)
            continue
        _check_episode_base(sample, ('trace',))
        check_request(sample['request'], sample['before'], sample['identity']['self_seat'])
        check_response(sample['response'], sample['request'])
        _check_successor(sample['successor'], sample['before'])
        _trace(sample)
        reports[index] = _evaluate(sample, index)
    if legacy:
        normalized = copy.deepcopy(document)
        normalized.update(schema_version=V4, projection=v4_projection(), samples=legacy,
            counts={'matched_pairs': len(legacy), 'exported': len(legacy),
                    'sample_limit_omissions': 0, 'unsupported_pairs': 0}, unsupported_reasons=[])
        # One delegation preserves v4's second pass over complete target chains.
        for index, report in zip(indices, v4_replay(normalized)['samples']):
            report['sample_index'] = index
            reports[index] = report
    return {'schema_version': 'mtgaplayer.semantic-sample-replay.v6',
        'samples': [reports[index] for index in range(len(document['samples']))],
        'artifact_checks_passed': True, 'raw_source_auth_revalidated': False,
        'complete_legality_verified': False, 'server_acceptance_verified': False,
        'read_only': True, 'execution': dict(EXECUTION)}
