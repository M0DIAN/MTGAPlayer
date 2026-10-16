"""Read-only public target-menu observations bound to the existing RawReducer.

Never identify a legal target set, selection quantity, client response or
server acceptance from this offered list. Raw GRE messages are never retained.
"""
import copy
from .raw_log import _id
from .response_evidence import _current_verified_request,_current_verified_raw_request

VERSION='mtgaplayer.action-target-menu-observation.v1'
REQ='GREMessageType_ActionsAvailableReq'
ALLOWED={'actionType','grpId','instanceId','facetId','abilityGrpId',
         'uniqueAbilityId','shouldStop','manaCost','autoTapSolution','targets'}
DENIALS={'target_minimum_verified':False,'target_maximum_verified':False,
         'target_domain_complete_verified':False,'target_selection_legal_verified':False,
         'complete_payment_verified':False,'complete_legality_verified':False,
         'server_acceptance_verified':False,'response_encoding_verified':False,
         'historical_response_used':False,'input_sent':False,'read_only':True}


def unknown(reason):
    return {'schema_version':VERSION,'status':'insufficient_evidence','reason':reason,
            'request_binding':None,'request_id':None,'game_state_id':None,
            'engine_active_action_rows':None,'target_bearing_action_rows':None,
            'reviewed_public_menu_rows':0,'withheld_target_rows':None,'menus':[],
            'source_authentication':'not_currently_verified',
            'source_freshness_verified':False,**DENIALS}


def identity(req):
    b=req['binding']
    return (b['generation'],b['match'],b['game'],b['self_seat'],req['game_state_id'],req['id'])


def reviewed_row(row,position,visible,seat):
    if (type(row) is not dict or not set(row)<=ALLOWED or
            row.get('actionType')!='ActionType_Activate' or
            type(row.get('shouldStop')) is not bool or
            any(not _id(row.get(k)) or row[k]<1 for k in
                ('instanceId','grpId','facetId','abilityGrpId','uniqueAbilityId'))):
        return None
    src=visible.get(row['instanceId'])
    if (src is None or src.get('zone')!='ZoneType_Battlefield' or
            src.get('controller')!=seat or
            src.get('card_id') is not None and src['card_id']!=row['grpId']):
        return None
    slots=row.get('targets')
    if (type(slots) is not list or len(slots)!=1 or
            type(slots[0]) is not dict or set(slots[0])!={'targetIdx','targets'}):
        return None
    slot=slots[0]
    if not _id(slot['targetIdx']) or slot['targetIdx']<1:
        return None
    candidates=slot['targets']
    if type(candidates) is not list or not 1<=len(candidates)<=64:
        return None
    refs=[];seen=set()
    for cand in candidates:
        if type(cand) is not dict or set(cand)!={'targetInstanceId'}:
            return None
        ref=cand['targetInstanceId']
        obj=visible.get(ref) if _id(ref) and ref>0 else None
        if obj is None or obj.get('zone')!='ZoneType_Battlefield' or ref in seen:
            return None
        refs.append(ref);seen.add(ref)
    return {'list_position':position,'action_type':'ActionType_Activate',
            'source_visible_object_ref':row['instanceId'],
            'target_idx':slot['targetIdx'],'offered_visible_target_refs':refs,
            'offered_visible_target_count':len(refs),
            'scope':'reviewed_public_battlefield_ids_only',
            'selection_count':None,'parameter_mode':'future_choice_unverified',
            'offered_targets_form_complete_legal_domain':False,
            'target_selection_legality_verified':False}


def project(reducer,message,req):
    body=message.get('actionsAvailableReq')
    if type(body) is not dict or type(body.get('actions')) is not list or len(body['actions'])>256:
        return unknown('unsupported_active_action_inventory')
    current=reducer.document().get('current',{})
    objects=current.get('objects')
    if current.get('valid') is not True or type(objects) is not list or len(objects)>512:
        return unknown('public_state_unavailable')
    visible={}
    for obj in objects:
        if type(obj) is not dict or not _id(obj.get('id')) or obj['id'] in visible:
            return unknown('public_object_inventory_invalid')
        visible[obj['id']]=obj
    targeted=withheld=0;menus=[]
    for i,row in enumerate(body['actions']):
        if type(row) is not dict or 'targets' not in row or row['targets']==[]:
            continue
        targeted+=1
        menu=reviewed_row(row,i,visible,req['binding']['self_seat'])
        if menu is None:withheld+=1
        else:menus.append(menu)
    result=unknown(None if menus else 'no_reviewed_public_target_menu')
    result.update(status='observed_public_target_menus' if menus else 'insufficient_evidence',
                  request_binding=copy.deepcopy(req['binding']),request_id=req['id'],
                  game_state_id=req['game_state_id'],
                  engine_active_action_rows=len(body['actions']),
                  target_bearing_action_rows=targeted,
                  reviewed_public_menu_rows=len(menus),
                  withheld_target_rows=withheld,menus=menus,
                  source_authentication='same_current_request_digest_verified')
    return result


class TargetMenuObserver:
    """Store only sanitized current evidence; drop any stale request at output."""
    def __init__(self):
        self._ref=None
        self._report=None

    def observe(self,reducer,record):
        gre=record.get('greToClientEvent') if type(record) is dict else None
        messages=gre.get('greToClientMessages') if type(gre) is dict else None
        if type(messages) is not list:return
        matching=[]
        for msg in messages:
            if type(msg) is not dict or msg.get('type')!=REQ:continue
            req=_current_verified_raw_request(reducer,msg)
            if req is not None and req.get('_continuity_verified') is True:
                matching.append((msg,req))
        if len(matching)!=1:return
        msg,req=matching[0]
        try:report=project(reducer,msg,req)
        except (ValueError,TypeError,KeyError,RecursionError):return
        self._ref=identity(req);self._report=report

    def current(self,reducer,*,source_complete=True):
        if source_complete is not True:return unknown('source_framing_incomplete')
        req=_current_verified_request(reducer)
        if (req is None or req.get('type')!=REQ or
                req.get('_continuity_verified') is not True or
                self._ref!=identity(req) or self._report is None):
            return unknown('no_current_authenticated_target_menu')
        return copy.deepcopy(self._report)
