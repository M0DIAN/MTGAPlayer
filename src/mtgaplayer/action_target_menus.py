"""Read-only public target-menu observations bound to the existing RawReducer.

Never identify a legal target set, selection quantity, client response or
server acceptance from this offered list. Raw GRE messages are never retained.
"""
import copy
from .raw_log import _id
from .response_evidence import _current_verified_request,_current_verified_raw_request

VERSION='mtgaplayer.action-target-menu-observation.v2'
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
            'verified_source_ability_menu_rows':0,'unverified_source_ability_menu_rows':0,
            'contradicted_source_ability_rows_withheld':0,
            'source_authentication':'not_currently_verified',
            'source_freshness_verified':False,**DENIALS}


def identity(req):
    b=req['binding']
    return (b['generation'],b['match'],b['game'],b['self_seat'],req['game_state_id'],req['id'])


def reviewed_row(row,position,visible,seat,*,allow_highlight=False):
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
        if (type(cand) is not dict or
                (set(cand)!={'targetInstanceId'} and not
                 (allow_highlight and set(cand)=={'targetInstanceId','highlight'})) or
                'highlight' in cand and type(cand['highlight']) is not str):
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


# One opt-in current-request member profile. The v2 observer above/below and
# historical sample contracts retain their original strict projection.
CURRENT_VERSION='mtgaplayer.request-parameters.v4'
CURRENT_PROFILE='current_public_activate_target_member'
CURRENT_SCOPE='current_request_activate_target_member_consistency'


def public_battlefield_refs(reducer):
    """Strict raw public object AND agreeing unique public BF membership."""
    result=[]
    for obj in reducer.document()['current'].get('objects',[]):
        ref=obj['id'];raw=reducer.objects.get(ref,{})
        zone=reducer.zones.get(raw.get('zoneId'),{})
        memberships=[z for z in reducer.zones.values()
                     if ref in z.get('objectInstanceIds',[])]
        if (raw.get('visibility')=='Visibility_Public' and
                zone.get('visibility')=='Visibility_Public' and
                zone.get('type')=='ZoneType_Battlefield' and
                len(memberships)==1 and memberships[0] is zone):
            result.append(ref)
    return result


def project_current(message,visible,seat,source_abilities,public_refs):
    """Called ONLY by RawReducer's accepted current/digest-bound request path.

    Preserve every original position as opaque fixed metadata. Decode only a
    reviewed target menu; payment values and future target domains stay absent.
    """
    from .semantic_activate import _base,ability_observation
    from .raw_log import _frontier_row
    from .request_parameters import LiteralRefs
    from .semantic_samples import _need
    _need(type(message) is dict and not set(message)-{'type','systemSeatIds',
        'msgId','gameStateId','prompt','actionsAvailableReq'} and message.get('type')==REQ)
    body=message.get('actionsAvailableReq')
    _need(type(body) is dict and not set(body)-{'actions','inactiveActions'})
    actions=body.get('actions')
    _need(type(actions) is list and len(actions)<=256 and any(type(r) is dict and
        r.get('actionType')=='ActionType_Activate' and r.get('targets') for r in actions))
    objects={o['instance_id']:o for o in visible}
    _need(len(objects)==len(visible))
    public={ref:{'zone':objects[ref]['zone'],'controller':objects[ref]['controller_seat'],
                 'card_id':objects[ref]['card_id']} for ref in public_refs}
    rows=[]
    for position,raw in enumerate(actions):
        base=_base(raw,LiteralRefs(),())
        source=base['identifier_refs'].get('instanceId')
        _need(source is None or source in objects)
        shape=_frontier_row(position,base['action_type'],raw)
        menu=reviewed_row(raw,position,public,seat,allow_highlight=True)
        pair=(ability_observation(raw,source_abilities.get(source))
              if base['action_type']=='ActionType_Activate' and source in public
              else None)
        rows.append({'list_position':position,**base,
            'parameter_shapes':shape['known_parameter_shapes'],
            'other_fields_present':shape['other_top_level_fields_present'],
            'target_menu':menu,'ability_binding':pair})
    for row in rows:
        if sum(other['action_type']==row['action_type'] and
               other['identifier_refs']==row['identifier_refs'] for other in rows)!=1:
            row['target_menu']=None
    return {'profile':CURRENT_PROFILE,'rows':rows,'public_battlefield_refs':public_refs}


def check_current(value,binding,visible):
    """Strict sanitized contract; raw authentication remains the producer's job."""
    from .semantic_samples import _keys,_need
    from .semantic_activate import _base,ABILITY
    from .semantic_samples import PARAMS
    from .request_parameters import LiteralRefs
    from .decision_consumer import _binding
    _keys(value,('schema_version','profile','binding','rows','public_battlefield_refs',
                 'historical_response_used'))
    _binding(value['binding'],complete=True)
    _need(value['schema_version']==CURRENT_VERSION and value['profile']==CURRENT_PROFILE and
          value['binding']==binding and binding['request_type']==REQ and
          binding['request_id'] is not None and value['historical_response_used'] is False)
    objects={o['instance_id']:o for o in visible};_need(len(objects)==len(visible))
    refs=value['public_battlefield_refs']
    _need(type(refs) is list and len(refs)<=512 and all(_id(r) for r in refs) and
          len(refs)==len(set(refs)) and all(r in objects and
          objects[r]['zone']=='ZoneType_Battlefield' for r in refs))
    rows=value['rows'];_need(type(rows) is list and len(rows)<=256)
    for i,row in enumerate(rows):
        _keys(row,('list_position','action_type','identifier_refs','flags',
                   'parameter_shapes','other_fields_present','target_menu','ability_binding'))
        _need(type(row['list_position']) is int and row['list_position']==i)
        raw={'actionType':row['action_type'],**row['identifier_refs'],**row['flags']}
        base=_base(raw,LiteralRefs(),())
        _need(all(row[k]==base[k] for k in base))
        source=row['identifier_refs'].get('instanceId')
        _need(source is None or source in objects)
        shapes=row['parameter_shapes']
        _need(type(shapes) is dict and not set(shapes)-set(PARAMS) and
              type(row['other_fields_present']) is bool)
        for key,shape in shapes.items():
            count='auto_tap_actions_count' if key=='autoTapSolution' else 'element_count'
            _keys(shape,('kind',count))
            _need(shape['kind'] in ('object' if key=='autoTapSolution' else 'array','unexpected'))
            _need(shape[count] is None or type(shape[count]) is int and 0<=shape[count]<=1000000)
        pair=row['ability_binding']
        _need(pair in ABILITY or pair is None)
        _need(pair is None or row['action_type']=='ActionType_Activate' and source in refs)
        menu=row['target_menu']
        if menu is None:continue
        _need(sum(other['action_type']==row['action_type'] and
                  other['identifier_refs']==row['identifier_refs'] for other in rows)==1)
        _keys(menu,('list_position','action_type','source_visible_object_ref','target_idx',
                   'offered_visible_target_refs','offered_visible_target_count','scope',
                   'selection_count','parameter_mode','offered_targets_form_complete_legal_domain',
                   'target_selection_legality_verified'))
        targets=menu['offered_visible_target_refs']
        _need(row['action_type']==menu['action_type']=='ActionType_Activate' and
              type(menu['list_position']) is int and menu['list_position']==i and
              _id(menu['source_visible_object_ref']) and menu['source_visible_object_ref']>0 and
              menu['source_visible_object_ref']==source and source in refs and
              (objects[source]['card_id'] is None or objects[source]['card_id']==row['identifier_refs']['grpId']) and
              _id(menu['target_idx']) and menu['target_idx']>0 and
              type(targets) is list and 1<=len(targets)<=64 and
              all(_id(t) and t in refs for t in targets) and len(targets)==len(set(targets)) and
              type(menu['offered_visible_target_count']) is int and menu['offered_visible_target_count']==len(targets) and
              menu['scope']=='reviewed_public_battlefield_ids_only' and
              menu['selection_count'] is None and menu['parameter_mode']=='future_choice_unverified' and
              menu['offered_targets_form_complete_legal_domain'] is False and
              menu['target_selection_legality_verified'] is False and
              not row['other_fields_present'] and shapes.get('targets')=={'kind':'array','element_count':1})


def check_member(value,member,position,visible,seat):
    """One explicit member, never a final target set or legal-action verdict."""
    unknown='insufficient_evidence';bad='violated_known_constraints';good='verified_known_constraints'
    checks={k:unknown for k in ('offered_position_identity','source_identity','ability_identity',
                               'target_slot','explicit_menu_membership','target_quantity')}
    rows=value['rows']
    if position>=len(rows):return unknown,'proposal_binding_invalid',checks
    row=rows[position]
    if row['action_type']!='ActionType_Activate' or member['identifier_refs']!=row['identifier_refs']:
        return unknown,'proposal_binding_invalid',checks
    checks['offered_position_identity']=good
    menu=row['target_menu']
    if menu is None:return unknown,'target_menu_profile_not_observed',checks
    source=next(o for o in visible if o['instance_id']==menu['source_visible_object_ref'])
    if source['owner_seat']!=seat or source['controller_seat']!=seat:
        return unknown,'own_public_battlefield_source_not_verified',checks
    checks['source_identity']=good
    if row['ability_binding']=='observed_group_contradiction':
        checks['ability_identity']=bad
        return bad,'current_source_ability_group_contradiction',checks
    if row['ability_binding']!='verified_observed_pair':
        return unknown,'unique_public_source_ability_pair_not_verified',checks
    checks['ability_identity']=good
    if member['target_idx']!=menu['target_idx']:
        checks['target_slot']=bad
        return bad,'target_slot_differs_from_this_offered_row',checks
    checks['target_slot']=good
    if member['object_ref'] not in menu['offered_visible_target_refs']:
        checks['explicit_menu_membership']=bad
        return bad,'target_not_in_this_explicit_menu',checks
    checks['explicit_menu_membership']=good
    return good,'current_explicit_target_member_consistent',checks


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
    # Reuse semantic_activate's pre-response uniqueAbilityId -> abilityGrpId
    # observation, rather than constructing new rules for target-bearing rows.
    from .semantic_activate import ability_observation
    targeted=withheld=verified=unverified=contradicted=0;menus=[]
    for i,row in enumerate(body['actions']):
        if type(row) is not dict or 'targets' not in row or row['targets']==[]:
            continue
        targeted+=1
        menu=reviewed_row(row,i,visible,req['binding']['self_seat'])
        if menu is None:
            withheld+=1
            continue
        # Raw object's uniqueAbilities list is consulted ONLY for the
        # already-accepted, own-visible public Battlefield source. None and
        # ambiguous rows are evidence gaps, not game illegality.
        source=reducer.objects.get(menu['source_visible_object_ref'])
        abilities=(source.get('uniqueAbilities')
                   if type(source) is dict and source.get('visibility')=='Visibility_Public'
                   else None)
        pair=ability_observation(row,abilities)
        if pair=='observed_group_contradiction':
            # The request row contradicts the *current* public source's
            # explicit ability pairing; do not attach a usable menu to it.
            contradicted+=1
            withheld+=1
            continue
        menu['source_ability_pair_status']=pair
        menu['source_ability_pair_verified']=pair=='verified_observed_pair'
        verified+=int(menu['source_ability_pair_verified'])
        unverified+=int(not menu['source_ability_pair_verified'])
        menus.append(menu)
    result=unknown(None if menus else 'no_reviewed_public_target_menu')
    result.update(status='observed_public_target_menus' if menus else 'insufficient_evidence',
                  request_binding=copy.deepcopy(req['binding']),request_id=req['id'],
                  game_state_id=req['game_state_id'],
                  engine_active_action_rows=len(body['actions']),
                  target_bearing_action_rows=targeted,
                  reviewed_public_menu_rows=len(menus),
                  withheld_target_rows=withheld,menus=menus,
                  verified_source_ability_menu_rows=verified,
                  unverified_source_ability_menu_rows=unverified,
                  contradicted_source_ability_rows_withheld=contradicted,
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
