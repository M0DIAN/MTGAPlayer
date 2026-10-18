"""Finite current Group structure over the existing raw/current Consumer gate."""
import copy

from .decision_consumer import EXECUTION,_bounded_json
from .response_evidence import _current_verified_raw_request
from .choice_continuation import _binding
from .cast_target_members import _equal
from .semantic_samples import _keys,_need
from .current_target_request import _identity

VERSION='mtgaplayer.current-group-evidence.v1'
PROFILE='observed_ordered_scry_two_unresolved_items'
REQUEST='GREMessageType_GroupReq'
RESPONSE='ClientMessageType_GroupResp'
NAMESPACE='request_scoped_group_item_not_confirmed_object_or_card'
UNKNOWN=('item_object_identity_unknown','group_lower_bounds_unknown','complete_group_constraints_unknown',
    'complete_group_legality_unknown','prompt_number_semantics_unknown','strategic_utility_unknown',
    'response_encoding_unknown','server_acceptance_unknown')


def unknown(reason):
    return {'schema_version':VERSION,'status':'insufficient_evidence','reason':reason,'profile':None,
        'request_binding':None,'source_snapshot_ref':None,'source_object_ref':None,'source_object_type':None,
        'group_type':None,'context':None,'allow_cancel':None,'prompt_parameter_count':None,'prompt_number_semantics':None,
        'observed_item_count':None,'observed_group_specs':[],'reviewed_count_bounds':False,
        'item_namespace':NAMESPACE,'reviewed_visible_items':[],'reviewed_member_count':0,
        'unresolved_item_references':[],'unresolved_item_count':None,'returned_members':0,'truncated':False,
        'current_local_constraints_verified':False,'local_constraint_scope':None,
        'complete_proposals':[],'complete_legal_choices':None,'research_eligible':False,
        'historical_response_used':False,'unknown_group_constraints':list(UNKNOWN),'read_only':True,**EXECUTION}


def _uint(value):return type(value) is int and 0<value<2**32


def project_request(message,visible,seat):
    """Only the observed two-item Scry shape; no hidden-object table access."""
    _keys(message,('type','systemSeatIds','msgId','gameStateId','prompt','groupReq','allowCancel'))
    _need(message['type']==REQUEST and type(seat) is int and seat in (1,2) and
        type(message['systemSeatIds']) is list and len(message['systemSeatIds'])==1 and
        type(message['systemSeatIds'][0]) is int and message['systemSeatIds'][0]==seat and
        _uint(message['msgId']) and _uint(message['gameStateId']) and message['allowCancel']=='AllowCancel_No')
    # Group's Number is not the v6 hand-quantity profile (0..99). Observe its
    # bounded type only, as in v8; no prompt value/identity or quantity inference.
    prompt=message['prompt'];_keys(prompt,('promptId','parameters'))
    _need(_uint(prompt['promptId']) and type(prompt['parameters']) is list and len(prompt['parameters'])==1)
    parameter=prompt['parameters'][0];_keys(parameter,('parameterName','type','numberValue'))
    _need(type(parameter['parameterName']) is str and 0<len(parameter['parameterName'])<=128 and
        parameter['type']=='ParameterType_Number' and type(parameter['numberValue']) is int and
        -2**31<=parameter['numberValue']<2**31)
    body=message['groupReq']
    _keys(body,('instanceIds','groupSpecs','groupType','context','sourceId'))
    ids=body['instanceIds'];specs=body['groupSpecs']
    _need(body['groupType']=='GroupType_Ordered' and body['context']=='GroupingContext_Scry' and _uint(body['sourceId']) and
        type(ids) is list and len(ids)==2 and all(_uint(i) for i in ids) and len(set(ids))==2 and
        type(specs) is list and len(specs)==2)
    _need(not any(i in {o['instance_id'] for o in visible} for i in ids), 'visible_group_member_profile_not_reviewed')
    groups=[]
    for position,(spec,subzone) in enumerate(zip(specs,('SubZoneType_Top','SubZoneType_Bottom'))):
        _keys(spec,('upperBound','zoneType','subZoneType'))
        _need(type(spec['upperBound']) is int and spec['upperBound']==2 and
            spec['zoneType']=='ZoneType_Library' and spec['subZoneType']==subzone)
        groups.append({'list_position':position,'zone_type':spec['zoneType'],'sub_zone_type':subzone,
            'lower_bound':None,'upper_bound':spec['upperBound']})
    return {'group_type':body['groupType'],'context':body['context'],'allow_cancel':message['allowCancel'],
        'source_object_ref':body['sourceId'],'prompt_parameter_count':1,'observed_group_specs':groups,
        'observed_item_count':len(ids)}


def _visible(reducer):
    return [{'instance_id':o['id'],'card_id':o['card_id'],'zone':o['zone'],
        'owner_seat':o['owner'],'controller_seat':o['controller']} for o in reducer.document()['current']['objects']]


def _project(reducer,message,state,ref,limit):
    from .raw_log import RawReducer
    if not isinstance(reducer,RawReducer):return unknown('requires_same_current_reducer')
    request=_current_verified_raw_request(reducer,message)
    if request is None or request['type']!=REQUEST or not _equal(_binding(reducer,request),state['binding']):
        return unknown('authenticated_current_group_request_not_observed')
    if request.get('_group_evidence_interrupted') is True:return unknown('current_group_request_interrupted')
    if request.get('_continuity_verified') is not True or reducer._target_state_continuity_verified is not True:
        return unknown('typed_current_group_continuity_unverified')
    visible=state['visible_objects'];expected=_visible(reducer)
    keys=('instance_id','card_id','zone','owner_seat','controller_seat')
    _need(_equal(expected,[{k:o[k] for k in keys} for o in visible]))
    _bounded_json(message);ident=message['groupReq']['sourceId']
    signature=_identity(reducer,ident,('GameObjectType_Ability',),'ZoneType_Stack')
    source=reducer.objects[ident]
    _need(all(type(source[k]) is int and source[k]==state['binding']['self_seat'] for k in ('ownerSeatId','controllerSeatId')))
    stack=state['game']['stack']
    _need(stack['availability']=='observed' and any(_equal(m['instance_id'],ident) and
        m['object_type']=='GameObjectType_Ability' for m in stack['members']))
    value=project_request(message,visible,state['binding']['self_seat'])
    members=[{'group_item_ref':position+1,'list_position':position,'namespace':NAMESPACE,
        'object_ref':None,'card_id':None,'zone':None,'visibility':'not_in_current_visible_projection',
        'request_binding':copy.deepcopy(state['binding']),'source_snapshot_ref':copy.deepcopy(ref)}
        for position in range(min(limit,value['observed_item_count']))]
    after=_current_verified_raw_request(reducer,message)
    _need(after is not None and after.get('_group_evidence_interrupted') is not True and
        after.get('_continuity_verified') is True and reducer._target_state_continuity_verified is True and
        _equal(_binding(reducer,after),state['binding']) and _equal(expected,_visible(reducer)) and
        _equal(signature,_identity(reducer,ident,('GameObjectType_Ability',),'ZoneType_Stack')))
    result=unknown('current_group_structure_membership_and_explicit_upper_bounds_only')
    result.update(value,status='observed',profile=PROFILE,request_binding=copy.deepcopy(state['binding']),
        source_snapshot_ref=copy.deepcopy(ref),source_object_type='GameObjectType_Ability',reviewed_count_bounds=True,
        unresolved_item_references=members,unresolved_item_count=value['observed_item_count'],returned_members=len(members),
        truncated=len(members)<value['observed_item_count'],current_local_constraints_verified=True,
        local_constraint_scope='unique_request_items_ordered_specs_and_explicit_upper_bounds_only')
    _bounded_json(result);return result


def review_response(payload,frozen):
    """Later client submission only; omitted ids remain unknown, not empty."""
    _keys(payload,('type','respId','gameStateId','groupResp'))
    _need(payload['type']==RESPONSE and _uint(payload['respId']) and _uint(payload['gameStateId']))
    body=payload['groupResp'];_keys(body,('groups','groupType'))
    _need(body['groupType']=='GroupType_Ordered' and type(body['groups']) is list and len(body['groups'])==2)
    seen=set();missing=0
    for group,spec in zip(body['groups'],frozen['specs']):
        _need(type(group) is dict and set(group) in ({'zoneType','subZoneType'},{'zoneType','subZoneType','ids'}) and
            group['zoneType']==spec['zone_type'] and group['subZoneType']==spec['sub_zone_type'])
        if 'ids' not in group:missing+=1;continue
        ids=group['ids']
        _need(type(ids) is list and len(ids)<=spec['upper_bound'] and all(_uint(i) for i in ids) and
            len(set(ids))==len(ids) and set(ids)<=set(frozen['items']) and not (set(ids)&seen))
        seen.update(ids)
    return {'explicit_submitted_members':len(seen),'groups_with_unobserved_ids':missing}
