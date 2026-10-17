"""Finite current-request literals, projected after the existing visibility gate.

No response, raw message retention, private card lookup or execution authority.
The original mana profile is all-or-unknown across the active list. The explicit
v2 Activate profile keeps every position while marking unsupported values opaque.
"""
import copy
from collections import Counter

from .raw_log import _id

VERSION = 'mtgaplayer.request-parameters.v1'
PROFILE = 'reviewed_literal_mana_slice'
EFFECT_COST_VERSION = 'mtgaplayer.request-parameters.v3'
DISCARD_VERSION = 'mtgaplayer.request-parameters.v5'


class LiteralRefs:
    def ref(self, domain, scope, value):
        if not _id(value):
            raise ValueError('invalid_request_parameters')
        return value


def _action(value, *, activate=False):
    if activate:
        from .semantic_activate import check_action
        check_action(value)
        return
    from .semantic_cast import action
    from .semantic_samples import IDS, BOOLS, PARAMS
    if (type(value) is not dict or set(value) != {'action_type', 'identifier_refs', 'flags',
            'observed_empty_parameters', 'parameters'}):
        raise ValueError('invalid_request_parameters')
    ids, flags, empty, params = (value[k] for k in ('identifier_refs', 'flags',
        'observed_empty_parameters', 'parameters'))
    if (type(ids) is not dict or set(ids)-set(IDS) or type(flags) is not dict or set(flags)-set(BOOLS)
            or type(empty) is not list or len(empty) != len(set(empty)) or
            any(type(k) is not str or k not in PARAMS for k in empty) or
            type(params) is not dict or set(params)-set(PARAMS) or set(empty)&set(params)):
        raise ValueError('invalid_request_parameters')
    raw = {'actionType': value['action_type'], **ids, **flags, **copy.deepcopy(params)}
    for key in empty:
        raw[key] = {'autoTapActions': []} if key == 'autoTapSolution' else []
    if action(raw, LiteralRefs(), ()) != value:
        raise ValueError('invalid_request_parameters')


def _visible_references(action, visible):
    """All object-bearing literals must join uniquely to already visible objects."""
    counts = Counter(o['instance_id'] for o in visible)
    objects = {o['instance_id']: o for o in visible}
    ids = action['identifier_refs']
    source = ids.get('instanceId')
    if source is not None:
        obj = objects.get(source)
        if counts[source] != 1 or obj is None or obj['card_id'] != ids.get('grpId'):
            return False
    pending = [action['parameters']]
    while pending:
        value = pending.pop()
        if type(value) is list:
            pending.extend(value)
        elif type(value) is dict:
            for key, child in value.items():
                if key in ('instanceId', 'srcInstanceId') and counts[child] != 1:
                    return False
                pending.append(child)
    return True


def _project_existing(message, visible, seat=None):
    """Called only in the reducer's accepted, authenticated request path."""
    from .semantic_cast import action
    try:
        if message.get('type') == 'GREMessageType_SelectTargetsReq':
            from .semantic_targets import project_request
            objects = [{'object_ref': o['instance_id'], 'zone': o['zone']} for o in visible]
            return project_request(message, objects, seat, LiteralRefs(), ())
        if (set(message)-{'type', 'systemSeatIds', 'msgId', 'gameStateId', 'actionsAvailableReq'} or
                message['type'] != 'GREMessageType_ActionsAvailableReq'):
            return None
        payload = message['actionsAvailableReq']
        if type(payload) is not dict or set(payload)-{'actions', 'inactiveActions'}:
            return None
        rows = payload['actions']
        if type(rows) is not list or len(rows) > 256:
            return None
        result = [action(row, LiteralRefs(), ()) for row in rows]
        if not all(_visible_references(row, visible) for row in result):
            return None
        return result
    except (ValueError, TypeError, KeyError, RecursionError):
        return None


def effect_cost_objects(visible):
    """Translate only the existing visible projection, never reducer internals."""
    return [{'object_ref': obj['instance_id'], 'zone': obj['zone'],
             'owner': obj.get('owner_seat'), 'controller': obj['controller_seat']} for obj in visible]


def project(message, visible, seat=None, source_abilities=None, *, targeted_activate=False,
            public_battlefield_refs=None, current_discard=False, current_hand_refs=None, target_payment_relation=False):
    if target_payment_relation:
        from .activate_target_payment import project as joint_project
        try:
            return joint_project(message, visible, seat, source_abilities or {}, public_battlefield_refs or [])
        except (ValueError, TypeError, KeyError, RecursionError):
            pass
    if current_discard and message.get('type') == 'GREMessageType_SelectNReq':
        from .semantic_hand import project_request, check_current_discard
        try:
            snapshot = {'objects': [{'object_ref': o['instance_id'], 'zone': o['zone'],
                'owner': o['owner_seat']} for o in visible]}
            request = project_request(message, LiteralRefs(), (0, None, None, seat), snapshot)
            check_current_discard(request, visible, seat)
            if current_hand_refs is None or not set(request['payload']['offered_object_refs']) <= set(current_hand_refs):
                return None
            return request
        except (ValueError, TypeError, KeyError, RecursionError):
            return None
    if targeted_activate:
        from .action_target_menus import project_current
        try:
            return project_current(message,visible,seat,source_abilities or {},public_battlefield_refs or [])
        except (ValueError,TypeError,KeyError,RecursionError):
            pass
    from . import semantic_effect_cost as cost
    if message.get('type') == cost.REQUEST:
        try:
            return cost.project_request(message, effect_cost_objects(visible), seat, LiteralRefs(), ())
        except (ValueError, TypeError, KeyError, RecursionError):
            return None
    result = _project_existing(message, visible, seat)
    if result is not None or source_abilities is None:
        return result
    from .semantic_activate import project as activate_project
    try:
        return activate_project(message, visible, seat, source_abilities)
    except (ValueError, TypeError, KeyError, RecursionError):
        return None


def check(value, binding, visible):
    if value is None:
        return
    from .activate_target_payment import PROFILE as JOINT_PROFILE, check as check_joint
    if type(value) is dict and value.get('profile') == JOINT_PROFILE:
        check_joint(value, binding, visible)
        return
    from .semantic_hand import CURRENT_PROFILE as DISCARD_PROFILE, check_current_discard
    if type(value) is dict and value.get('profile') == DISCARD_PROFILE:
        from .decision_consumer import _binding
        _binding(value['binding'], complete=True)
        if (set(value) != {'schema_version', 'profile', 'binding', 'discard_request', 'historical_response_used'} or
                value['schema_version'] != DISCARD_VERSION or value['binding'] != binding or
                binding['request_type'] != 'GREMessageType_SelectNReq' or binding['request_id'] is None or
                value['historical_response_used'] is not False):
            raise ValueError('invalid_request_parameters')
        check_current_discard(value['discard_request'], visible, binding['self_seat'])
        return
    from .action_target_menus import CURRENT_PROFILE,check_current
    if type(value) is dict and value.get('profile')==CURRENT_PROFILE:
        check_current(value,binding,visible)
        return
    from . import semantic_effect_cost as cost
    if type(value) is dict and value.get('profile') == cost.PROFILE:
        if (set(value) != {'schema_version', 'profile', 'binding', 'cost_selection', 'historical_response_used'} or
                value['schema_version'] != EFFECT_COST_VERSION or value['binding'] != binding or
                binding['request_type'] != cost.REQUEST or binding['request_id'] is None or
                value['historical_response_used'] is not False):
            raise ValueError('invalid_request_parameters')
        cost.check_request(value['cost_selection'], effect_cost_objects(visible), binding['self_seat'])
        return
    from .semantic_activate import PROFILE as ACTIVATE_PROFILE, REQUEST_VERSION, check_rows
    if type(value) is dict and value.get('profile') == ACTIVATE_PROFILE:
        if (set(value) != {'schema_version', 'profile', 'binding', 'rows', 'historical_response_used'} or
                value['schema_version'] != REQUEST_VERSION or value['binding'] != binding or
                binding['request_type'] != 'GREMessageType_ActionsAvailableReq' or
                binding['request_id'] is None or value['historical_response_used'] is not False):
            raise ValueError('invalid_request_parameters')
        check_rows(value['rows'], visible)
        return
    from .semantic_targets import PROFILE as TARGET_PROFILE, check_request
    if type(value) is dict and value.get('profile') == TARGET_PROFILE:
        if (set(value) != {'schema_version', 'profile', 'binding', 'targets', 'historical_response_used'} or
                value['schema_version'] != VERSION or value['binding'] != binding or
                binding['request_type'] != 'GREMessageType_SelectTargetsReq' or
                binding['request_id'] is None or value['historical_response_used'] is not False):
            raise ValueError('invalid_request_parameters')
        check_request(value['targets'], [{'object_ref': o['instance_id'], 'zone': o['zone']} for o in visible],
                      binding['self_seat'])
        return
    if (type(value) is not dict or set(value) != {'schema_version', 'profile',
            'binding', 'actions', 'historical_response_used'} or
            value['schema_version'] != VERSION or value['profile'] != PROFILE or
            value['binding'] != binding or
            binding['request_type'] != 'GREMessageType_ActionsAvailableReq' or
            binding['request_id'] is None or value['historical_response_used'] is not False or
            type(value['actions']) is not list or len(value['actions']) > 256):
        raise ValueError('invalid_request_parameters')
    for row in value['actions']:
        _action(row)
        if not _visible_references(row, visible):
            raise ValueError('invalid_request_parameters')


def assemble(rows, binding, visible, *, allow_effect_cost=False, allow_targeted_activate=False, allow_current_discard=False,
             allow_target_payment_relation=False):
    if rows is None or binding['request_id'] is None:
        return None
    from .activate_target_payment import PROFILE as JOINT_PROFILE, REQUEST_VERSION as JOINT_VERSION
    if type(rows) is dict and rows.get('profile') == JOINT_PROFILE:
        if not allow_target_payment_relation: return None
        value = {'schema_version': JOINT_VERSION, **copy.deepcopy(rows), 'binding': copy.deepcopy(binding),
            'historical_response_used': False}
        check(value, binding, visible)
        return value
    from .semantic_hand import DISCARD, CURRENT_PROFILE as DISCARD_PROFILE
    if type(rows) is dict and rows.get('kind') == 'select_n' and rows.get('payload', {}).get('profile') == DISCARD:
        if not allow_current_discard:
            return None
        value = {'schema_version': DISCARD_VERSION, 'profile': DISCARD_PROFILE,
            'binding': copy.deepcopy(binding), 'discard_request': copy.deepcopy(rows), 'historical_response_used': False}
        check(value, binding, visible)
        return value
    from .action_target_menus import CURRENT_PROFILE,CURRENT_VERSION
    if type(rows) is dict and rows.get('profile')==CURRENT_PROFILE:
        if not allow_targeted_activate:return None
        value={'schema_version':CURRENT_VERSION,**copy.deepcopy(rows),
               'binding':copy.deepcopy(binding),'historical_response_used':False}
        check(value,binding,visible)
        return value
    from . import semantic_effect_cost as cost
    if type(rows) is dict and rows.get('profile') == cost.PROFILE:
        if not allow_effect_cost:
            return None  # Preserve the complete v5 contract.
        value = {'schema_version': EFFECT_COST_VERSION, 'profile': cost.PROFILE,
            'binding': copy.deepcopy(binding), 'cost_selection': copy.deepcopy(rows),
            'historical_response_used': False}
        check(value, binding, visible)
        return value
    from .semantic_activate import PROFILE as ACTIVATE_PROFILE, REQUEST_VERSION
    if type(rows) is dict and rows.get('profile') == ACTIVATE_PROFILE:
        value = {'schema_version': REQUEST_VERSION, **copy.deepcopy(rows),
                 'binding': copy.deepcopy(binding), 'historical_response_used': False}
        check(value, binding, visible)
        return value
    from .semantic_targets import PROFILE as TARGET_PROFILE
    target = binding['request_type'] == 'GREMessageType_SelectTargetsReq'
    value = {'schema_version': VERSION, 'profile': TARGET_PROFILE if target else PROFILE,
        'binding': copy.deepcopy(binding), 'targets' if target else 'actions': copy.deepcopy(rows),
        'historical_response_used': False}
    check(value, binding, visible)
    return value


def check_space(space, binding, visible, *, allow_effect_cost=False, allow_targeted_activate=False, allow_current_discard=False,
                allow_target_payment_relation=False):
    """Cross-check the existing frontier/graph, not a second request ledger."""
    value = space['request_parameters']
    check(value, binding, visible)
    if value is None:
        return
    from .activate_target_payment import PROFILE as JOINT_PROFILE, target_evidence
    if value['profile'] == JOINT_PROFILE:
        if not allow_target_payment_relation: raise ValueError('unsupported_target_payment_relation_profile')
        check_space({**space, 'request_parameters': target_evidence(value)}, binding, visible,
            allow_effect_cost=allow_effect_cost, allow_targeted_activate=True, allow_current_discard=allow_current_discard)
        # This opt-in profile joins complete row identities and observed flags.
        # JSON equality preserves Boolean/integer distinctions and old contracts.
        import json
        from .raw_log import _RAW_ID_FIELDS, _RAW_FLAG_FIELDS
        nodes = {n['action_key']['list_position']: n for n in space['choice_graph']['action_nodes']}
        for record in value['target_actions'] + value['mana_actions']:
            action = record['action']; identity = nodes[record['list_position']]['action_identity']
            expected = {
                'raw_identifiers': {public: action['identifier_refs'][raw] for raw, public in _RAW_ID_FIELDS
                                    if raw in action['identifier_refs']},
                'raw_flags_observed_not_discriminators': {public: action['flags'][raw] for raw, public in _RAW_FLAG_FIELDS
                                                         if raw in action['flags']}}
            for key, observed in expected.items():
                if json.dumps(identity[key], sort_keys=True) != json.dumps(observed, sort_keys=True):
                    raise ValueError('request_projection_mismatch')
        return
    from .semantic_hand import CURRENT_PROFILE as DISCARD_PROFILE
    if value['profile'] == DISCARD_PROFILE:
        if (not allow_current_discard or space['request_type'] != 'GREMessageType_SelectNReq' or
                space['immediate_frontier'] != {'kind': 'select_n', 'availability': 'not_applicable',
                    'completeness': 'unknown', 'projection': None} or space['choice_graph'] is not None):
            raise ValueError('request_projection_mismatch')
        return
    from .action_target_menus import CURRENT_PROFILE
    if value['profile']==CURRENT_PROFILE and not allow_targeted_activate:
        raise ValueError('unsupported_target_member_profile')
    from . import semantic_effect_cost as cost
    if value['profile'] == cost.PROFILE:
        if (not allow_effect_cost or space['request_type'] != cost.REQUEST or
                space['immediate_frontier'] != {'kind': None, 'availability': 'not_applicable',
                    'completeness': 'unknown', 'projection': None} or space['choice_graph'] is not None):
            raise ValueError('request_projection_mismatch')
        return
    from .semantic_activate import PROFILE as ACTIVATE_PROFILE
    if value['profile'] not in (PROFILE, ACTIVATE_PROFILE, CURRENT_PROFILE):
        # Target constraints live in this explicit v5 profile. The legacy graph
        # remains unknown rather than receiving an invented action inventory.
        if (space['request_type'] != 'GREMessageType_SelectTargetsReq' or
                space['immediate_frontier']['projection'] is not None or space['choice_graph'] is not None):
            raise ValueError('request_projection_mismatch')
        return
    from .raw_log import _RAW_ID_FIELDS
    frontier, graph = space['immediate_frontier']['projection'], space['choice_graph']
    partial = value['profile'] in (ACTIVATE_PROFILE,CURRENT_PROFILE)
    rows = value['rows'] if partial else value['actions']
    if (type(frontier) is not dict or frontier.get('engine_active_action_count') != len(rows) or
            type(frontier.get('templates')) is not list or len(frontier['templates']) != len(rows) or
            type(graph) is not dict or type(graph.get('action_nodes')) is not list):
        raise ValueError('request_projection_mismatch')
    nodes = {n['action_key']['list_position']: n for n in graph['action_nodes']}
    complex_positions = {i for i, row in enumerate(rows) if row['action_type'] in
                         ('ActionType_Cast', 'ActionType_Activate', 'ActionType_Activate_Mana')}
    if len(nodes) != len(graph['action_nodes']) or set(nodes) != complex_positions:
        raise ValueError('request_projection_mismatch')
    for position, (row, template) in enumerate(zip(rows, frontier['templates'])):
        if (template['list_position'] != position or template['engine_action_type'] != row['action_type'] or
                row['identifier_refs'].get('instanceId') != template.get('visible_object_id')):
            raise ValueError('request_projection_mismatch')
        shapes = copy.deepcopy(row['parameter_shapes']) if partial else {}
        if not partial:
            for key in set(row['parameters']) | set(row['observed_empty_parameters']):
                count = (len(row['parameters'][key]['autoTapActions']) if key == 'autoTapSolution' else
                         len(row['parameters'][key])) if key in row['parameters'] else 0
                shapes[key] = ({'kind': 'object', 'auto_tap_actions_count': count} if key == 'autoTapSolution' else
                               {'kind': 'array', 'element_count': count})
        if template['observed_parameter_shapes'] != shapes:
            raise ValueError('request_projection_mismatch')
        if partial and template['unknown_parameter_fields_present'] != row['other_fields_present']:
            raise ValueError('request_projection_mismatch')
        if position in nodes:
            identity = nodes[position]['action_identity']
            ids = {public: row['identifier_refs'][raw] for raw, public in _RAW_ID_FIELDS
                   if raw in row['identifier_refs']}
            if identity['engine_action_type'] != row['action_type'] or identity['raw_identifiers'] != ids:
                raise ValueError('request_projection_mismatch')
            if value['profile']==CURRENT_PROFILE and row['target_menu'] is not None:
                # Cross-check observed slot identity/menu length, never infer
                # a selection minimum/maximum from these structural counts.
                constraints=[c for c in nodes[position]['constraints'] if c['parameter_category']=='targets']
                menu=row['target_menu']
                expected={'container_element_count':1,'total':1,'examined':1,'truncated':False,
                    'groups':[{'position':0,'target_idx_raw':menu['target_idx'],
                               'target_count':menu['offered_visible_target_count']}]}
                import json
                if (len(constraints)!=1 or constraints[0]['observed_structure']!={'kind':'array'} or
                        json.dumps(constraints[0]['observed_quantity_or_domain'],sort_keys=True)!=
                        json.dumps(expected,sort_keys=True)):
                    raise ValueError('request_projection_mismatch')
