"""Historical visible sacrifice after one authenticated nonmana selection.

No mana solver, request-source inference, payment-complete claim or current
decision input. The existing collector owns identity, visibility and continuity.
"""
import copy

from .raw_log import _id
from .semantic_cast import _detail
from .semantic_samples import _keys, _need, _check_envelope, SampleError
from . import semantic_effect_cost as cost

VERSION = 'mtgaplayer.semantic-samples.v9'
REVIEWED = 'reviewed_effect_cost_sacrifice_subset'
MISSING = 'incomplete_effect_cost_result_annotations'
UNSUPPORTED = 'unsupported_effect_cost_result_annotations'


def projection():
    from .semantic_search import projection as v8_projection
    return {**v8_projection(), 'effect_cost_trace': 'first_continuous_visible_sacrifice_subset'}


def _ref(value):
    return _id(value) and value > 0


def _endpoints(before, after, selected, target, affector, seat):
    old = {o['object_ref']: o for o in before['objects']}
    new = {o['object_ref']: o for o in after['objects']}
    _need(all(_ref(x) for x in (selected, target, affector)) and
          len({selected, target, affector}) == 3 and selected in old and selected not in new and
          target not in old and target in new and affector in old and affector in new)
    a, b = old[selected], new[target]
    _need(a['zone'] == 'ZoneType_Battlefield' and b['zone'] == 'ZoneType_Graveyard' and
          a['owner'] == b['owner'] == a['controller'] == b['controller'] == seat and
          _ref(a['card_id']) and a['card_id'] == b['card_id'])
    _need(all(objects[affector]['zone'] == 'ZoneType_Stack' and
              objects[affector]['owner'] == objects[affector]['controller'] == seat
              for objects in (old, new)))


def facts(gs, reducer, refs, scope, before, after, response, selected_raw, seat):
    """Finite raw shape: one migration and one explicit Sacrifice in this state.

    Additional migration/transfer annotations withhold the result, even when
    apparently unrelated. This avoids deciding causal relevance speculatively.
    Only already-visible endpoint references are aliased for publication.
    """
    annotations = gs.get('annotations', [])
    if type(annotations) is not list or len(annotations) > 512:
        return [], UNSUPPORTED, 0
    count = len(annotations)
    try:
        mappings, transfers = [], []
        for row in annotations:
            _need(type(row) is dict and type(row.get('type')) is list and row['type'] and
                  all(type(t) is str for t in row['type']))
            if 'AnnotationType_ObjectIdChanged' in row['type']:
                _need(row['type'] == ['AnnotationType_ObjectIdChanged'])
                mappings.append(row)
            if 'AnnotationType_ZoneTransfer' in row['type']:
                _need(row['type'] == ['AnnotationType_ZoneTransfer'])
                transfers.append(row)
        _need(len(mappings) <= 1 and len(transfers) <= 1)
        if not mappings or not transfers:
            return [], MISSING, count
        migration, transfer = mappings[0], transfers[0]
        for row in (migration, transfer):
            _keys(row, ('id', 'affectorId', 'affectedIds', 'type', 'details'))
            _need(_ref(row['id']) and _ref(row['affectorId']) and
                  type(row['affectedIds']) is list and len(row['affectedIds']) == 1 and
                  _ref(row['affectedIds'][0]))
        _need(migration['id'] != transfer['id'] and migration['affectorId'] == transfer['affectorId'])
        mapping, movement = _detail(migration), _detail(transfer)
        _keys(mapping, ('orig_id', 'new_id'))
        _keys(movement, ('zone_src', 'zone_dest', 'category'))
        _need(_ref(selected_raw) and all(_ref(v) for v in mapping.values()) and
              mapping['orig_id'] == selected_raw and migration['affectedIds'] == [selected_raw] and
              transfer['affectedIds'] == [mapping['new_id']] and
              all(_ref(movement[k]) for k in ('zone_src', 'zone_dest')) and
              movement['category'] == 'Sacrifice')
        visible = {o['id']: o for o in reducer.document()['current']['objects']}
        target_raw, affector_raw = mapping['new_id'], migration['affectorId']
        _need(target_raw in visible and affector_raw in visible)
        source_zone, destination_zone = (reducer.zones.get(movement[k], {})
                                         for k in ('zone_src', 'zone_dest'))
        _need(source_zone.get('type') == 'ZoneType_Battlefield' and
              source_zone.get('visibility') == 'Visibility_Public' and
              destination_zone.get('type') == 'ZoneType_Graveyard' and
              destination_zone.get('visibility') == 'Visibility_Public' and
              type(destination_zone.get('ownerSeatId')) is int and destination_zone['ownerSeatId'] == seat)
        selected = response['payload']['selected_object_refs'][0]
        _need(refs.ref('object', scope, selected_raw) == selected)
        target, affector = (refs.ref('object', scope, ident) for ident in (target_raw, affector_raw))
        _endpoints(before, after, selected, target, affector, seat)
        return [
            {'kind': 'object_id_changed', 'original_object_ref': selected,
             'new_object_ref': target, 'observed_affector_ref': affector},
            {'kind': 'sacrifice_transfer', 'object_ref': target, 'observed_affector_ref': affector,
             'source_zone': 'ZoneType_Battlefield', 'destination_zone': 'ZoneType_Graveyard'},
        ], REVIEWED, count - 2
    except (SampleError, KeyError, TypeError):
        return [], UNSUPPORTED, count


def _check_result(sample):
    """Check portable facts; private source authentication is not re-established."""
    rows = sample['trace']['states']
    if not rows:
        return None
    row = rows[0]
    _need(row['facts_status'] in (REVIEWED, MISSING, UNSUPPORTED) and
          type(row['omitted_annotations']) is int and 0 <= row['omitted_annotations'] <= 512 and
          type(row['facts']) is list)
    if row['facts_status'] != REVIEWED:
        _need(row['facts'] == [])
        return None
    _need(len(row['facts']) == 2 and row['omitted_annotations'] <= 510)
    mapping, transfer = row['facts']
    _keys(mapping, ('kind', 'original_object_ref', 'new_object_ref', 'observed_affector_ref'))
    _keys(transfer, ('kind', 'object_ref', 'observed_affector_ref', 'source_zone', 'destination_zone'))
    selected = sample['response']['payload']['selected_object_refs'][0]
    target, affector = mapping['new_object_ref'], mapping['observed_affector_ref']
    _need(mapping['kind'] == 'object_id_changed' and mapping['original_object_ref'] == selected and
          _ref(mapping['original_object_ref']) and transfer['kind'] == 'sacrifice_transfer' and
          _ref(transfer['object_ref']) and _ref(transfer['observed_affector_ref']) and
          transfer['object_ref'] == target and transfer['observed_affector_ref'] == affector and
          transfer['source_zone'] == 'ZoneType_Battlefield' and transfer['destination_zone'] == 'ZoneType_Graveyard')
    _endpoints(sample['before'], row['snapshot'], selected, target, affector, sample['identity']['self_seat'])
    return affector


def replay(document):
    from .semantic_search import replay as v8_replay, VERSION as V8, projection as v8_projection
    _check_envelope(document, VERSION, projection())
    normalized = copy.deepcopy(document)
    normalized.update(schema_version=V8, projection=v8_projection())
    # Delegate all existing structural/choice/trace and cross-sample checks once.
    # Only the new result slice is normalized to v7's old endpoint-only contract.
    for sample in normalized['samples']:
        _need(type(sample) is dict and type(sample.get('request')) is dict)
        if cost.is_effect_cost(sample.get('request')):
            for row in sample['trace']['states']:
                _keys(row, ('snapshot', 'previous_state_ref', 'facts', 'facts_status', 'omitted_annotations'))
                row.update(facts=[], facts_status='visible_snapshot_only', omitted_annotations=None)
    result = v8_replay(normalized)
    result['schema_version'] = 'mtgaplayer.semantic-sample-replay.v9'
    for sample, report in zip(document['samples'], result['samples']):
        if cost.is_effect_cost(sample['request']):
            affector = _check_result(sample)
            report.update(observed_result_scope='selected_visible_card_first_successor_sacrifice',
                selected_card_sacrifice_observed=affector is not None,
                selected_card_result='observed_explicit_annotation_chain' if affector is not None else 'insufficient_evidence',
                observed_affector_ref=affector, parent_activate_causal_relation=None)
    return result
