"""Explicit current Search members over semantic v8; no complete proposals."""
import copy

from .decision_consumer import EXECUTION,_bounded_json
from .response_evidence import _current_verified_raw_request
from .choice_continuation import _binding
from .cast_target_members import _equal
from .semantic_samples import _Refs,_need
from .request_parameters import LiteralRefs
from .current_target_request import _identity
from . import semantic_search as search

VERSION='mtgaplayer.current-search-evidence.v1'
NAMESPACE='request_scoped_search_item_not_object_or_card'
UNKNOWN=('hidden_card_identity_unknown','minimum_find_unknown','fail_to_find_semantics_unknown',
    'complete_search_domain_unknown','complete_search_legality_unknown','strategic_utility_unknown',
    'response_encoding_unknown','server_acceptance_unknown')


def unknown(reason):
    return {'schema_version':VERSION,'status':'insufficient_evidence','reason':reason,
        'profile':None,'request_binding':None,'source_snapshot_ref':None,
        'source_object_ref':None,'source_object_type':None,'searched_zone':None,
        'item_namespace':NAMESPACE,'items_to_search_count':None,'offered_item_count':None,
        'offered_search_item_refs':[],'returned_members':0,'truncated':False,
        'max_find':None,'min_find':None,'allow_fail_to_find':None,'fail_to_find_semantics':None,
        'current_local_constraints_verified':False,'local_constraint_scope':None,
        'complete_proposals':[],'complete_proposal_count':None,'hidden_item_card_identity':None,
        'historical_response_used':False,'complete_legality_verified':False,
        'unresolved_constraints':list(UNKNOWN),'research_eligible':False,'read_only':True,**EXECUTION}


class _ItemRefs(LiteralRefs):
    """Only search items get request-local aliases; public refs stay literal."""
    def __init__(self):self.items=_Refs()
    def ref(self,domain,scope,value):
        return self.items.ref(domain,scope,value) if domain=='search_item' else super().ref(domain,scope,value)


def _project(reducer,message,state,ref,limit):
    from .raw_log import RawReducer
    if not isinstance(reducer,RawReducer):return unknown('requires_same_current_reducer')
    request=_current_verified_raw_request(reducer,message)
    if request is None or request['type']!=search.REQUEST or not _equal(_binding(reducer,request),state['binding']):
        return unknown('authenticated_current_search_request_not_observed')
    if request.get('_search_evidence_interrupted') is True:return unknown('current_search_request_interrupted')
    if request.get('_continuity_verified') is not True or reducer._target_state_continuity_verified is not True:
        return unknown('typed_current_search_continuity_unverified')
    current=reducer.document()['current'];visible=state['visible_objects']
    expected=[{'instance_id':o['id'],'card_id':o['card_id'],'zone':o['zone'],
        'owner_seat':o['owner'],'controller_seat':o['controller']} for o in current['objects']]
    keys=('instance_id','card_id','zone','owner_seat','controller_seat')
    if not _equal(expected,[{k:o[k] for k in keys} for o in visible]):
        return unknown('current_visible_projection_disagrees_with_reducer')
    _bounded_json(message)
    body=message['searchReq'];zones=body['zonesToSearch']
    _need(type(zones) is list and len(zones)==1 and type(zones[0]) is int)
    zone=reducer.zones[zones[0]]
    _need(type(zone['zoneId']) is int and zone['zoneId']==zones[0])
    zone_signature=copy.deepcopy({k:zone.get(k) for k in ('zoneId','type','ownerSeatId','visibility')})
    # Requested-zone labels only: no hidden faces or search-item object lookup.
    metadata={'id':zones[0],'type':zone.get('type'),'owner':zone.get('ownerSeatId'),'visibility':zone.get('visibility')}
    refs=_ItemRefs();scope=(reducer.generation,reducer.match,reducer.game,reducer.seat)
    literals=[{'object_ref':o['instance_id'],'zone':o['zone'],
        'owner':o['owner_seat'],'controller':o['controller_seat']} for o in visible]
    ident=body['sourceId'];kinds=('GameObjectType_Ability','GameObjectType_Card','GameObjectType_Token')
    signature=_identity(reducer,ident,kinds,'ZoneType_Stack')
    source_type=reducer.objects[ident]['type'];stack=state['game']['stack']
    _need(stack['availability']=='observed' and any(_equal(m['instance_id'],ident) and
        m['object_type']==source_type for m in stack['members']))
    value=search.project_request(message,literals,state['binding']['self_seat'],refs,scope,metadata)
    search.check_request(value,literals,state['binding']['self_seat'])
    members=[{'search_item_ref':item['search_item_ref'],'list_position':position,
        'visibility':item['visibility'],'namespace':NAMESPACE,
        'request_binding':copy.deepcopy(state['binding']),'source_snapshot_ref':copy.deepcopy(ref)}
        for position,item in enumerate(value['items_sought'][:limit])]
    after=_current_verified_raw_request(reducer,message)
    _need(after is not None and after.get('_search_evidence_interrupted') is not True and
        after.get('_continuity_verified') is True and reducer._target_state_continuity_verified is True and
        _equal(_binding(reducer,after),state['binding']) and
        _equal(_identity(reducer,ident,kinds,'ZoneType_Stack'),signature) and
        _equal({k:reducer.zones[zones[0]].get(k) for k in ('zoneId','type','ownerSeatId','visibility')},
               zone_signature) and
        _equal(expected,[{'instance_id':o['id'],'card_id':o['card_id'],'zone':o['zone'],
            'owner_seat':o['owner'],'controller_seat':o['controller']} for o in reducer.document()['current']['objects']]))
    result=unknown('current_search_members_and_explicit_upper_count_only')
    result.update(status='observed',profile=search.PROFILE,request_binding=copy.deepcopy(state['binding']),
        source_snapshot_ref=copy.deepcopy(ref),source_object_ref=value['source_object_ref'],
        source_object_type=source_type,searched_zone=copy.deepcopy(value['searched_zone']),
        items_to_search_count=value['items_to_search_count'],offered_item_count=len(value['items_sought']),
        offered_search_item_refs=members,returned_members=len(members),truncated=len(members)<len(value['items_sought']),
        max_find=value['max_find'],allow_fail_to_find=value['allow_fail_to_find'],
        current_local_constraints_verified=True,local_constraint_scope='offered_request_membership_unique_ids_and_explicit_maximum_only')
    _bounded_json(result);return result
