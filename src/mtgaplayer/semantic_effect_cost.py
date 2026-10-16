"""Observed single visible-object nonmana payment selection; no payment claim."""
import copy

from .raw_log import _id
from .semantic_samples import (_need, _keys, SampleError, _check_snapshot,
    _check_envelope, _check_episode_base, _check_successor)

VERSION = 'mtgaplayer.semantic-samples.v7'
PROFILE = 'observed_nonmana_payment_select_single'
KIND = 'effect_cost_select'
REQUEST = 'GREMessageType_PayCostsReq'
RESPONSE = 'ClientMessageType_EffectCostResp'
FIRST = 'first_continuous_state_observed'
ENUMS = {'effect_cost_type': 'EffectCostType_Select',
    'context': 'SelectionContext_NonMana_Payment', 'option_context': 'OptionContext_Payment',
    'list_type': 'SelectionListType_Dynamic', 'id_type': 'IdType_InstanceId',
    'validation_type': 'SelectionValidationType_NonRepeatable', 'allow_cancel': 'AllowCancel_Abort'}
ENDS = ('not_observed', 'eof', 'next_request_observed', 'interrupted',
        'full_baseline_not_continuous', FIRST)


def projection():
    from .semantic_hand import projection as v6_projection
    return {**v6_projection(), 'effect_cost_choices': PROFILE,
        'effect_cost_trace': 'first_continuous_visible_snapshot_only',
        'effect_cost_payment_and_rules_effect': 'unknown'}


def is_effect_cost(request):
    return isinstance(request, dict) and request.get('kind') == KIND


def check_request(value, visible, seat):
    """Validate one projected request against its existing visible endpoint.

    References may be raw visible IDs (LiteralRefs) or portable aliases. No raw
    reducer objects, later response or successor is consulted.
    """
    _keys(value, ('profile', 'offered_object_refs', 'weights', 'min_sel', 'max_sel',
        'min_weight', 'max_weight', 'allow_undo', 'source_object_ref', *ENUMS))
    offered, weights = value['offered_object_refs'], value['weights']
    _need(value['profile'] == PROFILE and type(seat) is int and seat in (1, 2) and
          type(offered) is list and 1 <= len(offered) <= 256 and
          all(_id(ref) and ref > 0 for ref in offered) and len(offered) == len(set(offered)) and
          type(weights) is list and len(weights) == len(offered) and
          all(type(weight) is int and weight == 1 for weight in weights) and
          type(value['min_sel']) is int and type(value['max_sel']) is int and
          value['min_sel'] == value['max_sel'] == 1 and
          type(value['min_weight']) is int and value['min_weight'] == -2147483648 and
          type(value['max_weight']) is int and value['max_weight'] == 2147483647 and
          value['allow_undo'] is True and value['source_object_ref'] is None and
          all(value[key] == expected for key, expected in ENUMS.items()))
    _need(type(visible) is list and len(visible) <= 512)
    objects = {}
    for obj in visible:
        _need(type(obj) is dict and _id(obj.get('object_ref')) and obj['object_ref'] > 0 and
              obj['object_ref'] not in objects)
        objects[obj['object_ref']] = obj
    for ref in offered:
        obj = objects.get(ref)
        _need(obj is not None and obj.get('zone') == 'ZoneType_Battlefield' and
              type(obj.get('owner')) is int and obj['owner'] == seat and
              type(obj.get('controller')) is int and obj['controller'] == seat)


def check_selection(value, selected, *, visible, seat):
    """Pure current-request known constraints; no response identity authority."""
    check_request(value, visible, seat)
    if type(selected) is not list or not all(_id(ref) and ref > 0 for ref in selected):
        return 'violated_known_constraints', 'selection_ids_not_strict_integer_array'
    if len(selected) != 1 or len(set(selected)) != len(selected):
        return 'violated_known_constraints', 'single_nonrepeatable_selection_required'
    if selected[0] not in value['offered_object_refs']:
        return 'violated_known_constraints', 'selected_object_not_offered'
    return 'verified_known_constraints', 'offered_single_visible_selection_consistent'


def project_request(message, visible, seat, refs, scope):
    """Project only the observed shape; filter raw visible IDs before aliasing."""
    try:
        _keys(message, ('type', 'systemSeatIds', 'msgId', 'gameStateId', 'prompt',
                       'payCostsReq', 'allowCancel', 'allowUndo'))
        _need(message['type'] == REQUEST and type(message['systemSeatIds']) is list and
              len(message['systemSeatIds']) == 1 and type(message['systemSeatIds'][0]) is int and
              message['systemSeatIds'][0] == seat and _id(message['msgId']) and _id(message['gameStateId']))
        prompt = message['prompt']
        _keys(prompt, ('promptId', 'parameters'))
        _need(_id(prompt['promptId']) and type(prompt['parameters']) is list and len(prompt['parameters']) == 1)
        parameter = prompt['parameters'][0]
        _keys(parameter, ('parameterName', 'type', 'numberValue'))
        _need(type(parameter['parameterName']) is str and 0 < len(parameter['parameterName']) <= 128 and
              parameter['type'] == 'ParameterType_Number' and type(parameter['numberValue']) is int and
              -2**31 <= parameter['numberValue'] <= 2**31 - 1)
        body = message['payCostsReq']
        _keys(body, ('paymentActions', 'effectCostReq'))
        _need(type(body['paymentActions']) is dict and not body['paymentActions'])
        effect = body['effectCostReq']
        _keys(effect, ('effectCostType', 'costSelection'))
        selection = effect['costSelection']
        _keys(selection, ('minSel', 'maxSel', 'context', 'optionContext', 'listType', 'ids',
                          'weights', 'idType', 'validationType', 'minWeight', 'maxWeight'))
        value = {'profile': PROFILE, 'offered_object_refs': copy.deepcopy(selection['ids']),
            'weights': copy.deepcopy(selection['weights']), 'min_sel': selection['minSel'],
            'max_sel': selection['maxSel'], 'min_weight': selection['minWeight'],
            'max_weight': selection['maxWeight'], 'allow_cancel': message['allowCancel'],
            'allow_undo': message['allowUndo'], 'source_object_ref': None,
            'effect_cost_type': effect['effectCostType'], 'context': selection['context'],
            'option_context': selection['optionContext'], 'list_type': selection['listType'],
            'id_type': selection['idType'], 'validation_type': selection['validationType']}
        check_request(value, visible, seat)
        value['offered_object_refs'] = [refs.ref('object', scope, ref) for ref in value['offered_object_refs']]
        return value
    except (SampleError, TypeError, KeyError):
        raise SampleError('request_unsupported') from None


def project_response(payload, request, refs, scope):
    try:
        _keys(payload, ('type', 'respId', 'gameStateId', 'effectCostResp'))
        _need(payload['type'] == RESPONSE and _id(payload['respId']) and _id(payload['gameStateId']))
        effect = payload['effectCostResp']
        _keys(effect, ('effectCostType', 'costSelection'))
        _need(effect['effectCostType'] == 'EffectCostType_Select')
        _keys(effect['costSelection'], ('ids',))
        ids = effect['costSelection']['ids']
        _need(type(ids) is list and len(ids) <= 256 and all(_id(ref) and ref > 0 for ref in ids))
        return {'kind': KIND, 'payload': {'selected_object_refs': [refs.ref('object', scope, ref) for ref in ids]}}
    except (SampleError, TypeError, KeyError):
        raise SampleError('response_unsupported') from None


def check_response(response, request, visible, seat):
    _keys(response, ('kind', 'payload'))
    _keys(response['payload'], ('selected_object_refs',))
    _need(response['kind'] == KIND)
    status, _ = check_selection(request['payload'], response['payload']['selected_object_refs'],
                                visible=visible, seat=seat)
    _need(status == 'verified_known_constraints', 'known_constraints_violated')


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
          row['previous_state_ref'] == before['state_ref'] and row['snapshot']['state_ref'] != before['state_ref'] and
          row['facts'] == [] and row['facts_status'] == 'visible_snapshot_only' and
          row['omitted_annotations'] is None and sample['successor']['status'] == 'continuous_state_observed' and
          sample['successor']['snapshot'] == row['snapshot'])


def replay(document):
    from .semantic_hand import replay as v6_replay, VERSION as V6, projection as v6_projection
    from .decision_consumer import EXECUTION
    _check_envelope(document, VERSION, projection())
    reports, legacy, indices = {}, [], []
    for index, sample in enumerate(document['samples']):
        _need(type(sample) is dict and type(sample.get('request')) is dict)
        if not is_effect_cost(sample['request']):
            legacy.append(sample)
            indices.append(index)
            continue
        _check_episode_base(sample, ('trace',))
        _keys(sample['request'], ('kind', 'payload'))
        check_request(sample['request']['payload'], sample['before']['objects'], sample['identity']['self_seat'])
        check_response(sample['response'], sample['request'], sample['before']['objects'], sample['identity']['self_seat'])
        _check_successor(sample['successor'], sample['before'])
        _trace(sample)
        selected = sample['response']['payload']['selected_object_refs']
        reports[index] = {'sample_index': index, 'request_kind': KIND,
            'selected_option_positions': [sample['request']['payload']['offered_object_refs'].index(ref) for ref in selected],
            'successor_status': sample['successor']['status'], 'trace_status': sample['trace']['status'],
            'validation_scope': PROFILE, 'known_constraints': 'verified_known_constraints',
            'selection_submission_observed': True, 'payment_completed_verified': False,
            'rules_effect_verified': False, 'source_object_ref': None,
            'complete_legality_verified': False, 'server_acceptance_verified': False}
    if legacy:
        normalized = copy.deepcopy(document)
        normalized.update(schema_version=V6, projection=v6_projection(), samples=legacy,
            counts={'matched_pairs': len(legacy), 'exported': len(legacy),
                    'sample_limit_omissions': 0, 'unsupported_pairs': 0}, unsupported_reasons=[])
        # Whole-batch v6 delegation preserves its v4 target-chain second pass.
        for index, report in zip(indices, v6_replay(normalized)['samples']):
            report['sample_index'] = index
            reports[index] = report
    return {'schema_version': 'mtgaplayer.semantic-sample-replay.v7',
        'samples': [reports[index] for index in range(len(document['samples']))],
        'artifact_checks_passed': True, 'raw_source_auth_revalidated': False,
        'complete_legality_verified': False, 'server_acceptance_verified': False,
        'read_only': True, 'execution': dict(EXECUTION)}
