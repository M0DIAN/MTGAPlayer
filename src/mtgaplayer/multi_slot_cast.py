"""Opt-in current Cast slot observations, never complete target proposals.

The sole RawReducer attests raw visibility and retains the action's group. Consumers can
validate the bounded observation against its enclosing current state, not
reauthenticate private GRE bytes or infer rules from a protocol group ID.
"""
import copy
import json

from .raw_log import _id
from .request_parameters import LiteralRefs
from .semantic_samples import SampleError, _need
from .semantic_targets import action
from .semantic_cast import check_action

FIELD = 'current_multi_slot_cast'
VERSION = 'mtgaplayer.current-multi-slot-cast.v1'
SCOPE = 'current_cast_ordered_slots_and_public_member_identity_only'
DENIALS = {k: False for k in ('target_combination_verified', 'target_domain_complete',
    'complete_payment_verified', 'complete_legality_verified', 'response_encoding_verified',
    'execution_ready', 'input_sent', 'historical_response_used', 'catalog_rules_identity_verified')}
UNKNOWN = ['target_combination_legality_unknown', 'selection_quantities_unknown',
    'future_request_constraints_unknown', 'payment_legality_unknown', 'additional_costs_unknown',
    'mode_and_x_unknown', 'card_rules_unknown']


def _same(left, right):
    return json.dumps(left, sort_keys=True) == json.dumps(right, sort_keys=True)


def _slots(literal):
    check_action(literal, target_actions=True)
    _need(literal['action_type'] == 'ActionType_Cast' and
          set(literal['identifier_refs']) == {'instanceId', 'grpId', 'facetId'} and
          set(literal['flags']) == {'shouldStop'} and
          not literal['observed_empty_parameters'] and
          set(literal['parameters']) == {'manaCost', 'targets'})
    slots = literal['parameters']['targets']
    _need(2 <= len(slots) <= 8 and literal['parameters']['manaCost'])
    seen = set(); result = []
    for position, slot in enumerate(slots):
        idx = slot['targetIdx']; refs = [row['targetInstanceId'] for row in slot['targets']]
        _need(_id(idx) and idx > 0 and idx not in seen and 1 <= len(refs) <= 64 and
              len(set(refs)) == len(refs) and all(_id(ref) and ref > 0 for ref in refs))
        seen.add(idx)
        result.append({'slot_position': position, 'target_idx': idx,
            'provided_object_refs': refs, 'minimum': None, 'maximum': None, 'selected_count': None})
    return result


def _evidence(literal, key):
    return {'schema_version': VERSION, 'action_key': copy.deepcopy(key),
        'action_literal': copy.deepcopy(literal), 'slots': _slots(literal),
        'validation_scope': SCOPE, 'evidence_level': 'local_structure_and_membership',
        'source_group_identity': 'current_action_literal_only',
        'provided_members_current_public_battlefield': True,
        'auto_tap_solution_observed': False, 'payment_status': 'unknown',
        'unresolved': list(UNKNOWN), 'read_only': True, **DENIALS}


def project(message, visible, seat, cast_sources, public_refs):
    """Accepted current request only; reuse existing bounded literal decoder."""
    if (set(message) != {'type', 'systemSeatIds', 'msgId', 'gameStateId', 'actionsAvailableReq'} or
            not _same(message['systemSeatIds'], [seat]) or
            type(message['actionsAvailableReq']) is not dict or
            set(message['actionsAvailableReq']) - {'actions', 'inactiveActions'}):
        return {}
    rows = message['actionsAvailableReq'].get('actions')
    if message.get('type') != 'GREMessageType_ActionsAvailableReq' or type(rows) is not list or len(rows) > 256:
        return {}
    objects = {obj['instance_id']: obj for obj in visible}
    if len(objects) != len(visible): return {}
    result = {}
    for position, row in enumerate(rows):
        try:
            # Skip unrelated rows without decoding a second action inventory.
            if type(row) is not dict or row.get('actionType') != 'ActionType_Cast' or type(row.get('targets')) is not list or len(row['targets']) < 2:
                continue
            literal = action(row, LiteralRefs(), ()); slots = _slots(literal)
            ids = literal['identifier_refs']; source = objects.get(ids['instanceId'])
            _need(source is not None and source['instance_id'] in cast_sources and
                  source['zone'] == 'ZoneType_Hand' and source['owner_seat'] == seat and
                  source['controller_seat'] == seat and
                  (source['card_id'] is None or type(source['card_id']) is int and source['card_id'] == ids['grpId']))
            _need(all(ref in public_refs and ref in objects and objects[ref]['zone'] == 'ZoneType_Battlefield'
                      for slot in slots for ref in slot['provided_object_refs']))
            result[position] = literal
        except (SampleError, ValueError, TypeError, KeyError):
            continue
    return result


def attach(node, request):
    literal = request.get('_multi_slot_cast', {}).get(node['action_key']['list_position'])
    if literal is not None:
        for constraint in node['constraints']:
            if constraint['parameter_category'] == 'targets':
                constraint[FIELD] = _evidence(literal, node['action_key'])


def checked_observations(graph, frontier, visible, binding):
    """Strict additive v1 contract. An absent extension leaves legacy data alone."""
    if graph is None: return {}
    result = {}; objects = {obj['instance_id']: obj for obj in visible}
    for node in graph['action_nodes']:
        for constraint in node['constraints']:
            if FIELD not in constraint: continue
            _need(len(objects) == len(visible))
            value = constraint[FIELD]; key = node['action_key']; pos = key['list_position']
            _need(type(pos) is int and 0 <= pos < len(frontier['templates']) and pos not in result)
            expected_identity = {k: binding['source_generation' if k == 'generation' else k]
                                 for k in ('generation', 'match', 'game', 'game_state_id', 'self_seat', 'request_id')}
            _need(binding['request_type'] == 'GREMessageType_ActionsAvailableReq' and
                  _same(key['request_identity'], expected_identity) and
                  _same(graph['request_identity'], expected_identity) and
                  _same(constraint['action_key'], key) and constraint['parameter_category'] == 'targets' and
                  constraint['validation_level'] == 'observed_structure')
            literal = value['action_literal']; expected = _evidence(literal, key)
            _need(_same(value, expected))
            ids = literal['identifier_refs']; source = objects.get(ids['instanceId'])
            _need(source is not None and source['zone'] == 'ZoneType_Hand' and
                  type(source['owner_seat']) is int and source['owner_seat'] == binding['self_seat'] and
                  type(source['controller_seat']) is int and source['controller_seat'] == binding['self_seat'])
            _need(source['card_id'] is None or type(source['card_id']) is int and source['card_id'] == ids['grpId'])
            raw_ids = {'instance_id': ids['instanceId'], 'grp_id': ids['grpId'], 'facet_id': ids['facetId']}
            identity = node['action_identity']; template = frontier['templates'][pos]
            _need(identity['engine_action_type'] == template['engine_action_type'] == 'ActionType_Cast' and
                  _same(identity['raw_identifiers'], raw_ids) and
                  _same(identity['raw_flags_observed_not_discriminators'], {'should_stop': literal['flags']['shouldStop']}) and
                  _same(template['action_key'], key) and template['visible_object_id'] == ids['instanceId'])
            slots = expected['slots']
            _need(all(ref in objects and objects[ref]['zone'] == 'ZoneType_Battlefield'
                      for slot in slots for ref in slot['provided_object_refs']))
            groups = [{'position': s['slot_position'], 'target_idx_raw': s['target_idx'],
                       'target_count': len(s['provided_object_refs'])} for s in slots]
            _need(_same(constraint['observed_quantity_or_domain'], {'container_element_count': len(slots),
                'total': len(slots), 'examined': len(slots), 'truncated': False, 'groups': groups}))
            # Existing parameter metadata must agree; absence is not free payment.
            shapes = template['observed_parameter_shapes']
            _need(set(shapes) == {'targets', 'manaCost'} and
                  shapes['targets']['element_count'] == len(slots) and
                  shapes['manaCost']['element_count'] == len(literal['parameters']['manaCost']))
            result[pos] = copy.deepcopy(value)
    return result
