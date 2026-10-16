"""One observed hidden-library Search submission and first public successor.

Search items are request-scoped opaque identifiers, never visible object refs.
Only explicit accepted GRE annotations can map a submitted item to a new public
object. No hidden card identity, rule effect or parent-Activate cause is read.
"""
import copy

from .raw_log import _id
from .semantic_samples import (_need, _keys, SampleError, _check_snapshot,
    _check_envelope, _check_episode_base, _check_successor)
from .semantic_cast import _detail

VERSION = 'mtgaplayer.semantic-samples.v8'
PROFILE = 'observed_single_own_library_search'
KIND = 'search'
REQUEST = 'GREMessageType_SearchReq'
RESPONSE = 'ClientMessageType_SearchResp'
FIRST = 'first_continuous_state_observed'
ENDS = ('not_observed', 'eof', 'next_request_observed', 'interrupted',
        'full_baseline_not_continuous', FIRST)


def projection():
    from .semantic_effect_cost import projection as v7_projection
    return {**v7_projection(), 'search_choices': PROFILE,
        'search_items': 'request_scoped_identifier_only_not_visible_objects',
        'search_unfiltered_domain': 'count_only_no_identity_or_order',
        'search_trace': 'first_continuous_public_successor_only',
        'search_missing_minimum_and_fail_to_find_semantics': 'unknown',
        'search_rules_effect_and_parent_activate_cause': 'unknown'}


def is_search(request):
    return isinstance(request, dict) and request.get('kind') == KIND


def _ref(value):
    return _id(value) and value > 0


def _objects(visible):
    _need(type(visible) is list and len(visible) <= 512)
    result = {}
    for obj in visible:
        _need(type(obj) is dict and _ref(obj.get('object_ref')) and obj['object_ref'] not in result)
        result[obj['object_ref']] = obj
    return result


def _source(visible, source, seat):
    obj = _objects(visible).get(source)
    _need(type(seat) is int and seat in (1, 2) and obj is not None and
          obj.get('zone') == 'ZoneType_Stack' and type(obj.get('owner')) is int and
          obj['owner'] == seat and type(obj.get('controller')) is int and obj['controller'] == seat)
    # An observable Stack ability may have no card catalog identity.


def check_request(value, visible, seat):
    _keys(value, ('profile', 'source_object_ref', 'searched_zone', 'items_to_search_count',
        'items_sought', 'max_find', 'min_find', 'allow_fail_to_find', 'allow_cancel',
        'allow_undo', 'fail_to_find_semantics'))
    _need(value['profile'] == PROFILE and _ref(value['source_object_ref']) and
          type(value['max_find']) is int and value['max_find'] == 1 and
          value['min_find'] is None and value['allow_undo'] is None and
          value['fail_to_find_semantics'] is None and
          value['allow_fail_to_find'] == 'AllowFailToFind_Any' and value['allow_cancel'] == 'AllowCancel_No')
    _source(visible, value['source_object_ref'], seat)
    zone = value['searched_zone']
    _keys(zone, ('zone_ref', 'type', 'owner', 'visibility'))
    _need(_ref(zone['zone_ref']) and zone['type'] == 'ZoneType_Library' and
          type(zone['owner']) is int and zone['owner'] == seat and zone['visibility'] == 'Visibility_Hidden')
    items = value['items_sought']
    _need(type(items) is list and 1 <= len(items) <= 256 and
          type(value['items_to_search_count']) is int and len(items) <= value['items_to_search_count'] <= 512)
    seen = set()
    for item in items:
        _keys(item, ('search_item_ref', 'visibility'))
        ref = item['search_item_ref']
        _need(_ref(ref) and ref not in seen and item['visibility'] == 'request_identifier_only')
        seen.add(ref)


def _item_scope(scope, request_id):
    return (*scope, request_id)


def project_request(message, visible, seat, refs, scope, zone_metadata):
    """Bind the public source before aliases; never inspect hidden gameObjects."""
    try:
        _keys(message, ('type', 'systemSeatIds', 'msgId', 'gameStateId', 'prompt', 'searchReq', 'allowCancel'))
        _need(message['type'] == REQUEST and type(message['systemSeatIds']) is list and
              len(message['systemSeatIds']) == 1 and type(message['systemSeatIds'][0]) is int and
              message['systemSeatIds'][0] == seat and _ref(message['msgId']) and _id(message['gameStateId']))
        prompt = message['prompt']
        _keys(prompt, ('promptId', 'parameters'))
        _need(_id(prompt['promptId']) and type(prompt['parameters']) is list and len(prompt['parameters']) == 2)
        for parameter in prompt['parameters']:
            _keys(parameter, ('parameterName', 'type', 'numberValue'))
            _need(type(parameter['parameterName']) is str and 0 < len(parameter['parameterName']) <= 128 and
                  parameter['type'] == 'ParameterType_Number' and type(parameter['numberValue']) is int and
                  -2**31 <= parameter['numberValue'] < 2**31)
        body = message['searchReq']
        _keys(body, ('maxFind', 'zonesToSearch', 'itemsToSearch', 'itemsSought', 'sourceId', 'allowFailToFind'))
        _need(_ref(body['sourceId']))
        _source(visible, body['sourceId'], seat)
        zones, domain, sought = body['zonesToSearch'], body['itemsToSearch'], body['itemsSought']
        _need(type(zones) is list and len(zones) == 1 and _ref(zones[0]) and
              type(domain) is list and 1 <= len(domain) <= 512 and all(_ref(x) for x in domain) and
              len(set(domain)) == len(domain) and type(sought) is list and 1 <= len(sought) <= 256 and
              all(_ref(x) for x in sought) and len(set(sought)) == len(sought) and set(sought) <= set(domain))
        # This finite profile has opaque items. Historical public aliases must
        # not lend their identities to the currently hidden library request.
        _need(not set(sought) & _objects(visible).keys())
        _keys(zone_metadata, ('id', 'type', 'owner', 'visibility'))
        _need(type(zone_metadata['id']) is int and zone_metadata['id'] == zones[0] and
              zone_metadata['type'] == 'ZoneType_Library' and type(zone_metadata['owner']) is int and
              zone_metadata['owner'] == seat and zone_metadata['visibility'] == 'Visibility_Hidden' and
              type(body['maxFind']) is int and body['maxFind'] == 1 and
              body['allowFailToFind'] == 'AllowFailToFind_Any' and message['allowCancel'] == 'AllowCancel_No')
        item_scope = _item_scope(scope, message['msgId'])
        return {'profile': PROFILE, 'source_object_ref': refs.ref('object', scope, body['sourceId']),
            'searched_zone': {'zone_ref': refs.ref('zone', scope, zones[0]),
                'type': 'ZoneType_Library', 'owner': seat, 'visibility': 'Visibility_Hidden'},
            'items_to_search_count': len(domain),
            'items_sought': [{'search_item_ref': refs.ref('search_item', item_scope, ident),
                'visibility': 'request_identifier_only'} for ident in sought],
            'max_find': body['maxFind'], 'min_find': None, 'allow_fail_to_find': body['allowFailToFind'],
            'allow_cancel': message['allowCancel'], 'allow_undo': None, 'fail_to_find_semantics': None}
    except (SampleError, KeyError, TypeError):
        raise SampleError('request_unsupported') from None


def private_context(message, refs, scope):
    """Producer-only identifiers; the collector removes this before export."""
    body = message['searchReq']
    item_scope = _item_scope(scope, message['msgId'])
    return {'items': {ident: refs.ref('search_item', item_scope, ident) for ident in body['itemsSought']},
            'source_id': body['sourceId'], 'zone_id': body['zonesToSearch'][0]}


def check_response(response, request):
    _keys(response, ('kind', 'payload'))
    _need(response['kind'] == KIND)
    _keys(response['payload'], ('selected_search_item_refs',))
    chosen = response['payload']['selected_search_item_refs']
    # Empty/fail-to-find semantics have not been established by this episode.
    _need(type(chosen) is list and chosen, 'response_unsupported')
    _need(all(_ref(ref) for ref in chosen) and len(chosen) == len(set(chosen)) == 1 and
          chosen[0] in {row['search_item_ref'] for row in request['payload']['items_sought']},
          'known_constraints_violated')


def project_response(payload, request, context):
    try:
        _keys(payload, ('type', 'respId', 'gameStateId', 'searchResp'))
        _need(payload['type'] == RESPONSE and _ref(payload['respId']) and _id(payload['gameStateId']))
        _keys(payload['searchResp'], ('itemsFound',))
        chosen = payload['searchResp']['itemsFound']
        _need(type(chosen) is list and chosen, 'response_unsupported')
        _need(all(_ref(x) for x in chosen) and len(chosen) == len(set(chosen)) == 1 and
              chosen[0] in context['items'], 'known_constraints_violated')
        result = {'kind': KIND, 'payload': {'selected_search_item_refs': [context['items'][chosen[0]]]}}
        check_response(result, request)
        return result
    except (SampleError, KeyError, TypeError) as exc:
        if isinstance(exc, SampleError) and str(exc) == 'known_constraints_violated':
            raise
        raise SampleError('response_unsupported') from None


def facts(gs, reducer, refs, scope, before, after, request, response, context):
    """Only request-identifier migration and explicit public Put, never rules."""
    annotations = gs.get('annotations', [])
    if type(annotations) is not list or len(annotations) > 512:
        return [], 'unsupported_search_annotation', 0
    previous, current = _objects(before['objects']), _objects(after['objects'])
    selected_ref = response['payload']['selected_search_item_refs'][0]
    selected = next(raw for raw, ref in context['items'].items() if ref == selected_ref)
    source = request['payload']['source_object_ref']
    # The original raw identifier cannot simultaneously remain a public object
    # at this endpoint. Only the existing visibility-filtered projection is read.
    if any(obj['id'] == selected for obj in reducer.document()['current'].get('objects', [])):
        return [], 'unsupported_search_annotation', len(annotations)
    # Stage related identifiers before interpreting ordered facts. A foreign
    # annotation about the new endpoint must be rejected even if it appears
    # before its mapping. These raw IDs remain private and are never aliased here.
    related = {selected}
    for annotation in annotations:
        if type(annotation) is dict and annotation.get('type') == ['AnnotationType_ObjectIdChanged']:
            try:
                detail = _detail(annotation)
                _keys(detail, ('orig_id', 'new_id'))
                if all(_ref(value) for value in detail.values()) and detail['orig_id'] == selected:
                    related.add(detail['new_id'])
            except (SampleError, KeyError, TypeError):
                continue
    mapped, result, unsupported = None, [], False
    for annotation in annotations:
        if type(annotation) is not dict:
            continue
        typ = annotation.get('type')
        if typ not in (['AnnotationType_ObjectIdChanged'], ['AnnotationType_ZoneTransfer']):
            continue
        affected = annotation.get('affectedIds')
        if (annotation.get('affectorId') != context['source_id'] and
                not (type(affected) is list and any(x == known for x in affected for known in related))):
            continue
        try:
            _keys(annotation, ('id', 'affectorId', 'affectedIds', 'type', 'details'))
            _need(_id(annotation['id']) and type(annotation['affectorId']) is int and
                  annotation['affectorId'] == context['source_id'] and type(affected) is list and
                  len(affected) == 1 and _ref(affected[0]))
            detail = _detail(annotation)
            if typ == ['AnnotationType_ObjectIdChanged']:
                _keys(detail, ('orig_id', 'new_id'))
                _need(all(_ref(value) for value in detail.values()) and mapped is None and
                      detail['orig_id'] == selected and affected == [selected] and detail['new_id'] != selected)
                new_ref = refs.ref('object', scope, detail['new_id'])
                obj = current.get(new_ref)
                _need(new_ref not in previous and obj is not None and obj['zone'] == 'ZoneType_Battlefield' and
                      obj['owner'] == request['payload']['searched_zone']['owner'] and obj['controller'] == obj['owner'])
                mapped = detail['new_id']
                result.append({'kind': 'request_item_mapped_to_public_object', 'source_object_ref': source,
                    'selected_search_item_ref': selected_ref, 'public_object_ref': new_ref})
            else:
                _keys(detail, ('zone_src', 'zone_dest', 'category'))
                _need(mapped is not None and affected == [mapped] and len(result) == 1 and
                      all(_ref(detail[k]) for k in ('zone_src', 'zone_dest')) and
                      detail['zone_src'] == context['zone_id'] and detail['category'] == 'Put')
                old_zone, new_zone = (reducer.zones.get(detail[key], {}) for key in ('zone_src', 'zone_dest'))
                _need(old_zone.get('type') == 'ZoneType_Library' and
                      old_zone.get('ownerSeatId') == request['payload']['searched_zone']['owner'] and
                      old_zone.get('visibility') == 'Visibility_Hidden' and
                      new_zone.get('type') == 'ZoneType_Battlefield' and new_zone.get('visibility') == 'Visibility_Public')
                result.append({'kind': 'search_item_public_zone_transfer', 'source_object_ref': source,
                    'selected_search_item_ref': selected_ref, 'public_object_ref': result[0]['public_object_ref'],
                    'source_zone_ref': request['payload']['searched_zone']['zone_ref'],
                    'source_zone': 'ZoneType_Library', 'destination_zone': 'ZoneType_Battlefield', 'category': 'Put'})
        except (SampleError, KeyError, TypeError):
            unsupported = True
    if mapped is not None:
        # Another source/original mapping to this destination is ambiguous even
        # when its affector differs. Only identifiers are inspected here.
        mappings = 0
        for annotation in annotations:
            if type(annotation) is dict and annotation.get('type') == ['AnnotationType_ObjectIdChanged']:
                try:
                    detail = _detail(annotation)
                except (SampleError, KeyError, TypeError):
                    continue
                if detail.get('orig_id') == selected or detail.get('new_id') == mapped:
                    mappings += 1
        unsupported |= mappings != 1
    if unsupported:
        return [], 'unsupported_search_annotation', len(annotations)
    return result, 'reviewed_search_subset', len(annotations) - len(result)


def _trace(sample):
    trace, before = sample['trace'], sample['before']
    _keys(trace, ('status', 'truncated', 'next_request_ref', 'states'))
    _need(trace['status'] in ENDS and trace['truncated'] is False and
          type(trace['states']) is list and len(trace['states']) <= 1 and
          bool(trace['states']) == (trace['status'] == FIRST))
    _need(_ref(trace['next_request_ref']) if trace['status'] == 'next_request_observed'
          else trace['next_request_ref'] is None)
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
    _need(_ref(row['previous_state_ref']) and row['previous_state_ref'] == before['state_ref'] and
          row['snapshot']['state_ref'] != before['state_ref'] and
          row['facts_status'] in ('reviewed_search_subset', 'unsupported_search_annotation') and
          type(row['omitted_annotations']) is int and 0 <= row['omitted_annotations'] <= 512 and
          type(row['facts']) is list and len(row['facts']) <= 2 and
          sample['successor']['status'] == 'continuous_state_observed' and
          sample['successor']['snapshot'] == row['snapshot'])
    _need(row['facts_status'] != 'unsupported_search_annotation' or not row['facts'])
    request, chosen = sample['request']['payload'], sample['response']['payload']['selected_search_item_refs'][0]
    previous, current = _objects(before['objects']), _objects(row['snapshot']['objects'])
    mapped = None
    for fact in row['facts']:
        _need(type(fact) is dict)
        common = ('kind', 'source_object_ref', 'selected_search_item_ref', 'public_object_ref')
        if fact.get('kind') == 'request_item_mapped_to_public_object':
            _keys(fact, common)
            _need(mapped is None)
            mapped = fact['public_object_ref']
            obj = current.get(mapped)
            _need(_ref(mapped) and mapped not in previous and obj is not None and
                  obj['zone'] == 'ZoneType_Battlefield' and type(obj['owner']) is int and
                  obj['owner'] == request['searched_zone']['owner'] and type(obj['controller']) is int and
                  obj['controller'] == obj['owner'])
        else:
            _keys(fact, (*common, 'source_zone_ref', 'source_zone', 'destination_zone', 'category'))
            _need(fact['kind'] == 'search_item_public_zone_transfer' and mapped is not None and
                  _ref(fact['public_object_ref']) and fact['public_object_ref'] == mapped and _ref(fact['source_zone_ref']) and
                  fact['source_zone_ref'] == request['searched_zone']['zone_ref'] and
                  fact['source_zone'] == 'ZoneType_Library' and fact['destination_zone'] == 'ZoneType_Battlefield' and
                  fact['category'] == 'Put')
        _need(_ref(fact['source_object_ref']) and fact['source_object_ref'] == request['source_object_ref'] and
              _ref(fact['selected_search_item_ref']) and fact['selected_search_item_ref'] == chosen)


def replay(document):
    from .semantic_effect_cost import replay as v7_replay, VERSION as V7, projection as v7_projection
    from .decision_consumer import EXECUTION
    _check_envelope(document, VERSION, projection())
    reports, legacy, indices = {}, [], []
    for index, sample in enumerate(document['samples']):
        _need(type(sample) is dict and type(sample.get('request')) is dict)
        if not is_search(sample['request']):
            legacy.append(sample)
            indices.append(index)
            continue
        _check_episode_base(sample, ('trace',))
        _keys(sample['request'], ('kind', 'payload'))
        check_request(sample['request']['payload'], sample['before']['objects'], sample['identity']['self_seat'])
        check_response(sample['response'], sample['request'])
        _check_successor(sample['successor'], sample['before'])
        _trace(sample)
        req, trace = sample['request']['payload'], sample['trace']
        chosen = sample['response']['payload']['selected_search_item_refs'][0]
        rows = trace['states']
        facts_seen = rows[0]['facts'] if rows and rows[0]['facts_status'] == 'reviewed_search_subset' else []
        mapped = any(f['kind'] == 'request_item_mapped_to_public_object' for f in facts_seen)
        transferred = mapped and any(f['kind'] == 'search_item_public_zone_transfer' for f in facts_seen)
        reports[index] = {'sample_index': index, 'request_kind': KIND, 'validation_scope': PROFILE,
            'offered_option_count': len(req['items_sought']), 'candidate_visibility': 'request_identifier_only',
            'items_to_search_count': req['items_to_search_count'],
            'selected_option_positions': [[r['search_item_ref'] for r in req['items_sought']].index(chosen)],
            'selection_submission_observed': True, 'known_membership_and_upper_count': 'verified_known_constraints',
            'successor_status': sample['successor']['status'], 'trace_status': trace['status'],
            'first_continuous_state_observed': bool(rows), 'selected_item_public_mapping_observed': mapped,
            'selected_item_public_transfer_observed': transferred,
            'selected_item_result': 'observed_explicit_annotation_chain' if transferred else 'insufficient_evidence',
            'hidden_item_card_identity': None, 'min_find': None, 'fail_to_find_semantics': None,
            'parent_activate_causal_relation': None, 'rules_effect_verified': False,
            'complete_legality_verified': False, 'server_acceptance_verified': False}
    if legacy:
        normalized = copy.deepcopy(document)
        normalized.update(schema_version=V7, projection=v7_projection(), samples=legacy,
            counts={'matched_pairs': len(legacy), 'exported': len(legacy),
                    'sample_limit_omissions': 0, 'unsupported_pairs': 0}, unsupported_reasons=[])
        for index, report in zip(indices, v7_replay(normalized)['samples']):
            report['sample_index'] = index
            reports[index] = report
    return {'schema_version': 'mtgaplayer.semantic-sample-replay.v8',
        'samples': [reports[index] for index in range(len(document['samples']))],
        'artifact_checks_passed': True, 'raw_source_auth_revalidated': False,
        'complete_legality_verified': False, 'server_acceptance_verified': False,
        'read_only': True, 'execution': dict(EXECUTION)}
