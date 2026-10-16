"""Opt-in, narrow historical Cast evidence; no rules solver or input path.

Numeric protocol identifiers are aliased by the producer. Predictive mana is
an offered proposal, not observed payment or a proof of all payment choices.
"""
import copy
from .raw_log import _id
from .semantic_samples import (_need, _keys, SampleError, IDS, BOOLS, PARAMS,
                               COMPLEX, PROJECTION, _check_snapshot)

VERSION = 'mtgaplayer.semantic-samples.v2'
PROJECTION_V2 = {**copy.deepcopy(PROJECTION),
    'nonempty_action_parameters': 'reviewed_literal_mana_slice_only',
    'trace_annotations': 'visible_references_and_fixed_fact_schemas_only'}
COLORS = ('ManaColor_Generic', 'ManaColor_White', 'ManaColor_Blue', 'ManaColor_Black',
          'ManaColor_Red', 'ManaColor_Green', 'ManaColor_Colorless')
TRACE_LIMIT = 64
TRACE_ENDS = ('not_observed', 'eof', 'next_request_observed', 'interrupted',
              'full_baseline_not_continuous', 'limit_reached')


def _bounded(rows, limit=64):
    _need(type(rows) is list and len(rows) <= limit, 'request_unsupported')
    return rows


def _amount(row, array_color=False):
    _keys(row, ('color', 'count'))
    color = row['color']
    _need(type(row['count']) is int and 1 <= row['count'] <= 99, 'request_unsupported')
    _need((type(color) is list and len(color) == 1 and color[0] in COLORS) if array_color else
          type(color) is str and color in COLORS[1:], 'request_unsupported')
    return copy.deepcopy(row)


def _mana_option(value, refs, scope):
    _keys(value, ('mana',))
    mana = []
    for row in _bounded(value['mana']):
        _keys(row, ('manaId', 'color', 'srcInstanceId', 'specs', 'abilityGrpId', 'count'))
        _need(all(_id(row[k]) for k in ('manaId','srcInstanceId','abilityGrpId')), 'request_unsupported')
        _amount({'color':row['color'], 'count':row['count']})
        _need(row['specs'] == [{'type':'ManaSpecType_Predictive'}], 'request_unsupported')
        mana.append({**{k:row[k] for k in ('color','count')},
            'manaId': refs.ref('mana', scope, row['manaId']),
            'srcInstanceId':refs.ref('object',scope,row['srcInstanceId']),
            'abilityGrpId':refs.ref('abilityGrpId',scope,row['abilityGrpId']),
            'specs':[{'type':'ManaSpecType_Predictive'}]})
    return {'mana':mana}


def _parameter(key, value, refs, scope):
    if key == 'manaCost':
        return [_amount(row, True) for row in _bounded(value)]
    if key == 'manaPaymentOptions':
        return [_mana_option(row, refs, scope) for row in _bounded(value)]
    if key == 'autoTapSolution':
        _keys(value, ('autoTapActions',))
        rows=[]
        for row in _bounded(value['autoTapActions']):
            _keys(row, ('instanceId','abilityGrpId','manaPaymentOption'))
            _need(_id(row['instanceId']) and _id(row['abilityGrpId']), 'request_unsupported')
            rows.append({'instanceId':refs.ref('object',scope,row['instanceId']),
                'abilityGrpId':refs.ref('abilityGrpId',scope,row['abilityGrpId']),
                'manaPaymentOption':_mana_option(row['manaPaymentOption'],refs,scope)})
        return {'autoTapActions':rows}
    if key == 'manaSelections':
        rows=[]
        for row in _bounded(value):
            _keys(row, ('instanceId','abilityGrpId','options'))
            _need(_id(row['instanceId']) and _id(row['abilityGrpId']), 'request_unsupported')
            options=[]
            for option in _bounded(row['options']):
                _keys(option, ('mana',))
                options.append({'mana':[_amount(m) for m in _bounded(option['mana'])]})
            rows.append({'instanceId':refs.ref('object',scope,row['instanceId']),
                'abilityGrpId':refs.ref('abilityGrpId',scope,row['abilityGrpId']), 'options':options})
        return rows
    raise SampleError('request_unsupported')


class RequestManaRefs:
    def __init__(self, refs, request):
        self.refs, self.request = refs, (request['game_state_id'], request['id'])

    def ref(self, domain, scope, value):
        return self.refs.ref(domain, scope + self.request if domain == 'mana' else scope, value)


def action(row, refs, scope, *, target_projector=None):
    _need(type(row) is dict, 'request_unsupported')
    kind=row.get('actionType')
    if kind in ('ActionType_Pass','ActionType_FloatMana'):
        _need(set(row)=={'actionType'}, 'request_unsupported')
    elif kind=='ActionType_Play':
        _need(set(row)=={'actionType','instanceId','grpId','facetId','shouldStop'}, 'request_unsupported')
    else:
        _need(kind in COMPLEX and not set(row)-{'actionType',*IDS,*BOOLS,*PARAMS}, 'request_unsupported')
        required={'instanceId','grpId','facetId'}
        if kind!='ActionType_Cast':required.update(('abilityGrpId','uniqueAbilityId'))
        _need(required<=row.keys(), 'request_unsupported')
    _need(all(_id(row[k]) for k in IDS if k in row), 'request_unsupported')
    _need(all(type(row[k]) is bool for k in BOOLS if k in row), 'request_unsupported')
    empty=[]; parameters={}
    for key in PARAMS:
        if key not in row:continue
        value=row[key]
        if type(value) is (dict if key=='autoTapSolution' else list) and value==({'autoTapActions':[]} if key=='autoTapSolution' else []):empty.append(key)
        elif key == 'targets' and target_projector is not None:
            parameters[key] = target_projector(value, refs, scope)
        else:parameters[key]=_parameter(key,value,refs,scope)
    return {'action_type':kind,
        'identifier_refs':{k:refs.ref('object' if k=='instanceId' else k,scope,row[k]) for k in IDS if k in row},
        'flags':{k:row[k] for k in BOOLS if k in row},
        'observed_empty_parameters':empty, 'parameters':parameters}


class _IdentityRefs:
    def ref(self, domain, scope, value):
        _need(_id(value) and value>0)
        return value


def check_action(row, *, target_actions=False):
    _keys(row, ('action_type','identifier_refs','flags','observed_empty_parameters','parameters'))
    ids,flags,empty,params=(row[k] for k in ('identifier_refs','flags','observed_empty_parameters','parameters'))
    _need(type(ids) is dict and not set(ids)-set(IDS))
    _need(type(flags) is dict and not set(flags)-set(BOOLS))
    _need(type(empty) is list and all(type(k) is str and k in PARAMS for k in empty) and
          len(set(empty))==len(empty) and type(params) is dict and not set(params)-set(PARAMS) and
          not set(empty)&set(params))
    raw={'actionType':row['action_type'], **ids, **flags, **copy.deepcopy(params)}
    for key in empty:raw[key]={'autoTapActions':[]} if key=='autoTapSolution' else []
    if target_actions:
        from .semantic_targets import action as target_action
        _need(target_action(raw, _IdentityRefs(), ()) == row)
    else:
        _need(action(raw, _IdentityRefs(), ()) == row)


def _detail(annotation):
    rows=annotation.get('details')
    _need(type(rows) is list and len(rows)<=8)
    result={}
    for row in rows:
        _need(type(row) is dict and type(row.get('key')) is str and row['key'] not in result)
        key=row['key']; typ=row.get('type')
        field='valueInt32' if typ=='KeyValuePairValueType_int32' else 'valueString'
        _keys(row, ('key','type',field))
        _need(typ in ('KeyValuePairValueType_int32','KeyValuePairValueType_string') and
              type(row[field]) is list and len(row[field])==1)
        result[key]=row[field][0]
    return result


def facts(gs, reducer, refs, scope, previous, current, related):
    """Only accepted message facts whose references were/are safely visible."""
    before={o['object_ref']:o for o in previous['objects']}; after={o['object_ref']:o for o in current['objects']}
    result=[]; omitted=0; unsupported=False
    annotations=gs.get('annotations',[])
    if type(annotations) is not list or len(annotations)>512:
        return [], 'unsupported_relevant_annotation', 0
    recognized={'AnnotationType_ObjectIdChanged','AnnotationType_ZoneTransfer',
                'AnnotationType_ResolutionStart','AnnotationType_ResolutionComplete','AnnotationType_ManaPaid'}
    for a in annotations:
        if type(a) is not dict or type(a.get('type')) is not list or len(a['type'])!=1 or a['type'][0] not in recognized:
            omitted+=1;continue
        try:
            _need(_id(a.get('id')))
            typ=a['type'][0]; d=_detail(a); affected=a.get('affectedIds')
            _need(type(affected) is list and len(affected)==1 and _id(affected[0]))
            obj=refs.ref('object',scope,affected[0])
            if obj not in related and (not _id(a.get('affectorId')) or refs.ref('object',scope,a['affectorId']) not in related):
                omitted+=1;continue
            if typ=='AnnotationType_ObjectIdChanged':
                _keys(a, ('id','affectedIds','type','details'));_keys(d, ('orig_id','new_id'))
                _need(all(_id(v) for v in d.values()) and affected==[d['orig_id']])
                old,new=(refs.ref('object',scope,d[k]) for k in ('orig_id','new_id'))
                if old not in before or new not in after:omitted+=1;continue
                result.append({'kind':'object_id_changed','original_object_ref':old,'new_object_ref':new})
                related.add(new)
            elif typ=='AnnotationType_ZoneTransfer':
                _need(set(a) in ({'id','affectedIds','type','details'}, {'id','affectorId','affectedIds','type','details'}))
                _keys(d, ('zone_src','zone_dest','category'))
                if obj not in before and obj not in after:omitted+=1;continue
                _need(_id(d['zone_src']) and _id(d['zone_dest']))
                src=reducer.zones.get(d['zone_src'],{}).get('type');dst=reducer.zones.get(d['zone_dest'],{}).get('type')
                _need((d['category'],src,dst) in (('CastSpell','ZoneType_Hand','ZoneType_Stack'),('Resolve','ZoneType_Stack','ZoneType_Battlefield')))
                result.append({'kind':'zone_transfer','object_ref':obj,'source_zone':src,'destination_zone':dst,'category':d['category']})
            elif typ in ('AnnotationType_ResolutionStart','AnnotationType_ResolutionComplete'):
                _keys(a, ('id','affectorId','affectedIds','type','details'));_keys(d, ('grpid',))
                _need(a['affectorId']==affected[0] and _id(d['grpid']))
                visible=after.get(obj,before.get(obj))
                if visible is None:omitted+=1;continue
                _need(visible['card_id']==d['grpid'])
                result.append({'kind':'resolution_start' if typ.endswith('Start') else 'resolution_complete',
                               'object_ref':obj,'card_id':d['grpid']})
            else:
                _keys(a, ('id','affectorId','affectedIds','type','details'));_keys(d, ('id','color'))
                _need(_id(a['affectorId']) and all(_id(v) for v in d.values()))
                source=refs.ref('object',scope,a['affectorId'])
                if source not in before or obj not in after:omitted+=1;continue
                result.append({'kind':'mana_paid','source_object_ref':source,'spell_object_ref':obj})
        except (SampleError,TypeError,KeyError):
            omitted+=1;unsupported=True
    return result, 'unsupported_relevant_annotation' if unsupported else 'reviewed_subset', omitted


def check_trace(trace, before):
    _keys(trace, ('status','truncated','next_request_ref','states'))
    _need(trace['status'] in TRACE_ENDS and type(trace['truncated']) is bool and
          trace['truncated']==(trace['status']=='limit_reached'))
    _need((trace['next_request_ref'] is not None and _id(trace['next_request_ref']) and trace['next_request_ref']>0)
          if trace['status']=='next_request_observed' else trace['next_request_ref'] is None)
    _need(type(trace['states']) is list and len(trace['states'])<=TRACE_LIMIT)
    previous=before['state_ref']; seen={previous}; previous_objects={o['object_ref']:o for o in before['objects']}
    for row in trace['states']:
        _keys(row, ('snapshot','previous_state_ref','facts','facts_status','omitted_annotations'))
        _check_snapshot(row['snapshot']);current=row['snapshot']['state_ref']
        _need(_id(row['previous_state_ref']) and row['previous_state_ref']==previous and current not in seen)
        seen.add(current);previous=current
        _need(row['facts_status'] in ('reviewed_subset','unsupported_relevant_annotation') and
              _id(row['omitted_annotations']) and type(row['facts']) is list and len(row['facts'])<=512)
        current_objects={o['object_ref']:o for o in row['snapshot']['objects']}
        for f in row['facts']:
            _need(type(f) is dict)
            kind=f.get('kind')
            keys={'object_id_changed':('kind','original_object_ref','new_object_ref'),
                  'zone_transfer':('kind','object_ref','source_zone','destination_zone','category'),
                  'resolution_start':('kind','object_ref','card_id'),
                  'resolution_complete':('kind','object_ref','card_id'),
                  'mana_paid':('kind','source_object_ref','spell_object_ref')}
            _need(kind in keys);_keys(f,keys[kind])
            for k,v in f.items():
                if k not in ('kind','source_zone','destination_zone','category'):_need(_id(v) and (v>0 or k in ('card_id','observed_id','observed_color_code')))
            if kind=='object_id_changed':
                _need(f['original_object_ref'] in previous_objects and f['new_object_ref'] in current_objects and
                      f['original_object_ref'] != f['new_object_ref'])
            elif kind in ('resolution_start','resolution_complete'):
                obj=current_objects.get(f['object_ref'],previous_objects.get(f['object_ref']))
                _need(obj is not None and obj['card_id']==f['card_id'])
            elif kind=='mana_paid':
                _need(f['source_object_ref'] in previous_objects and f['spell_object_ref'] in current_objects)
            if kind=='zone_transfer':
                _need(f['object_ref'] in current_objects and current_objects[f['object_ref']]['zone']==f['destination_zone'])
                _need((f['category'],f['source_zone'],f['destination_zone']) in
                      (('CastSpell','ZoneType_Hand','ZoneType_Stack'),('Resolve','ZoneType_Stack','ZoneType_Battlefield')))
        previous_objects=current_objects
    if trace['status']=='not_observed':_need(not trace['states'])


def check_predictive_payment(rows, chosen, objects, self_seat, position, *, historical=False):
    """Pure generic-one offered-proposal check; no response or future state.

    Historical replay retains its exact-row agreement check. Decision-time
    checks ignore flags and leave alternative payment routes unsupported.
    """
    unknown='insufficient_evidence'; violated='violated_known_constraints'
    if position is None:return unknown, None
    # Missing on either side is unknown. Explicitly empty parameters remain
    # observed values, so a later comparison may identify a real disagreement.
    for row in (rows[position],chosen):
        observed=set(row['parameters'])|set(row['observed_empty_parameters'])
        if not {'manaCost','autoTapSolution'}<=observed:return unknown, None
    if historical and rows[position]!=chosen:return violated, None
    if not historical and any(rows[position]['parameters'].get(key) != chosen['parameters'].get(key) or
            (key in rows[position]['observed_empty_parameters']) != (key in chosen['observed_empty_parameters'])
            for key in ('manaCost', 'autoTapSolution')):
        return unknown, None
    params=chosen['parameters'];cost=params.get('manaCost');tap=params.get('autoTapSolution')
    if cost is None or tap is None:return unknown, None
    taps=tap['autoTapActions']
    if cost!=[{'color':['ManaColor_Generic'],'count':1}] or len(taps)!=1:return unknown, None
    payment=taps[0]; mana=payment['manaPaymentOption']['mana']
    if len(mana)!=1:return unknown, payment['instanceId']
    m=mana[0]
    if m['count']!=1:return unknown, payment['instanceId']
    if m['srcInstanceId']!=payment['instanceId'] or m['abilityGrpId']!=payment['abilityGrpId']:
        return violated, payment['instanceId']
    mana_rows=[a for a in rows if a['action_type']=='ActionType_Activate_Mana' and
               a['identifier_refs']['instanceId']==payment['instanceId'] and
               a['identifier_refs']['abilityGrpId']==payment['abilityGrpId']]
    if len(mana_rows)!=1:return unknown, payment['instanceId']
    a=mana_rows[0]['parameters'];options=a.get('manaPaymentOptions');selections=a.get('manaSelections')
    if options is None or selections is None:return unknown, payment['instanceId']
    expected={'instanceId':payment['instanceId'],'abilityGrpId':payment['abilityGrpId'],
              'options':[{'mana':[{'color':m['color'],'count':1}]}]}
    if payment['manaPaymentOption'] not in options or expected not in selections:return violated, payment['instanceId']
    before={o['object_ref']:o for o in objects}
    source=before.get(payment['instanceId'])
    if source is None or source['zone']!='ZoneType_Battlefield' or source['controller']!=self_seat:
        return unknown, payment['instanceId']
    return 'verified_known_constraints', payment['instanceId']


def _prediction(sample, position):
    return check_predictive_payment(sample['request']['payload']['actions'],
        sample['response']['payload']['action'], sample['before']['objects'],
        sample['identity']['self_seat'], position, historical=True)


def evaluate(sample, position):
    """Keep client choice, predictive consistency and server facts separate."""
    chosen=sample['response']['payload']['action']
    result={'known_cost_and_predictive_payment':'insufficient_evidence',
        'cast_submission_observed':False,'cast_on_stack_observed':False,
        'resolution_to_battlefield_observed':False,
        'mana_paid_source_to_spell_observed':False,'payment_source_tapped_observed':False,
        'payment_path_observed':False,
        'validation_scope':'one_observed_generic_one_predictive_payment_path',
        'all_payment_options_verified':False,'complete_legality_verified':False,
        'complete_observed_interaction':False}
    if chosen['action_type']!='ActionType_Cast':return result
    validation,payment_source=_prediction(sample,position)
    result['known_cost_and_predictive_payment']=validation
    result['cast_submission_observed']=position is not None
    source=chosen['identifier_refs']['instanceId']
    before={o['object_ref']:o for o in sample['before']['objects']}
    if source not in before or before[source]['zone']!='ZoneType_Hand':return result
    spell=None; stack_seen=False
    for state in sample['trace']['states']:
        if state['facts_status']!='reviewed_subset':break
        objects={o['object_ref']:o for o in state['snapshot']['objects']}; fs=state['facts']
        changes=[f for f in fs if f['kind']=='object_id_changed' and f['original_object_ref']==source]
        if spell is None and len(changes)==1:spell=changes[0]['new_object_ref']
        if spell is None:continue
        visible=objects.get(spell)
        if visible is None or visible['card_id']!=before[source]['card_id']:continue
        paid=any(f['kind']=='mana_paid' and f['source_object_ref']==payment_source and f['spell_object_ref']==spell for f in fs)
        payment=objects.get(payment_source)
        tapped=(payment is not None and payment['zone']=='ZoneType_Battlefield' and
                payment['controller']==sample['identity']['self_seat'] and payment['tapped'] is True)
        result['mana_paid_source_to_spell_observed'] |= paid
        result['payment_source_tapped_observed'] |= tapped
        result['payment_path_observed'] |= paid and tapped
        transfer=any(f['kind']=='zone_transfer' and f['object_ref']==spell and f['category']=='CastSpell' for f in fs)
        if transfer and visible['zone']=='ZoneType_Stack':stack_seen=True;result['cast_on_stack_observed']=True
        if stack_seen and visible['zone']=='ZoneType_Battlefield' and all(any(
            f['kind']==kind and f.get('object_ref')==spell and f.get('card_id')==visible['card_id']
            for f in fs) for kind in ('resolution_start','resolution_complete')) and any(
            f['kind']=='zone_transfer' and f['object_ref']==spell and f['category']=='Resolve' for f in fs):
            result['resolution_to_battlefield_observed']=True
    result['complete_observed_interaction'] = (result['known_cost_and_predictive_payment']=='verified_known_constraints' and
        result['payment_path_observed'] and result['cast_on_stack_observed'] and
        result['resolution_to_battlefield_observed'] and sample['trace']['status'] in ('eof','next_request_observed') and
        all(s['facts_status']=='reviewed_subset' for s in sample['trace']['states']))
    return result


def replay(document, *, target_actions=False):
    # Reuse the v1 envelope/SelectN/first-successor checks after validating and
    # removing only this opt-in extension. No second state reducer is involved.
    from .semantic_samples import _replay_samples, VERSION as V1
    _need(document.get('projection') == PROJECTION_V2)
    normalized=copy.deepcopy(document)
    normalized['schema_version']=V1;normalized['projection']=copy.deepcopy(PROJECTION)
    reports=[]
    for index,sample in enumerate(document['samples']):
        _keys(sample, ('identity','before','request','response','successor','provenance','trace'))
        check_trace(sample['trace'],sample['before'])
        if sample['trace']['states']:
            _need(sample['successor']['status']=='continuous_state_observed' and
                  sample['successor']['snapshot']==sample['trace']['states'][0]['snapshot'])
        elif sample['trace']['status']=='next_request_observed':
            _need(sample['successor']['status']=='next_request_observed' and
                  sample['successor']['request_ref']==sample['trace']['next_request_ref'])
        target=normalized['samples'][index];target.pop('trace')
        position=None
        if sample['request']['kind']=='actions_available':
            _keys(sample['request']['payload'],('actions',))
            payload=sample['response']['payload']
            _need(type(payload) is dict and set(payload) in ({'action'},{'action','auto_pass_priority'}))
            if 'auto_pass_priority' in payload:_need(payload['auto_pass_priority']=='AutoPassPriority_Yes')
            rows=sample['request']['payload']['actions'];chosen=payload['action']
            _need(type(rows) is list and len(rows)<=256)
            for a in [*rows,chosen]:check_action(a, target_actions=target_actions)
            matches=[i for i,a in enumerate(rows) if a['action_type']==chosen['action_type'] and
                     a['identifier_refs']==chosen['identifier_refs']]
            position=matches[0] if len(matches)==1 else None
            def base(a):
                b={k:copy.deepcopy(a[k]) for k in ('action_type','identifier_refs','flags','observed_empty_parameters')}
                b['observed_empty_parameters'] += list(a['parameters'])
                # V1's empty-descriptor checker has no FloatMana label. This
                # internal adapter checks only the already validated empty
                # shape; the reported position/type use the original v2 rows.
                if b['action_type']=='ActionType_FloatMana':b['action_type']='ActionType_Pass'
                return b
            target['request']['payload']['actions']=[base(a) for a in rows]
            target['response']['payload']={'action':base(chosen)}
            reports.append(evaluate(sample,position))
        else:
            reports.append(None)
    result=_replay_samples(normalized)
    result['schema_version']='mtgaplayer.semantic-sample-replay.v2'
    for index,(report,extended) in enumerate(zip(result['samples'],reports)):
        sample=document['samples'][index]
        report['trace_status']=sample['trace']['status']
        report['trace_truncated']=sample['trace']['truncated']
        if extended is not None:
            rows=sample['request']['payload']['actions'];chosen=sample['response']['payload']['action']
            matches=[i for i,a in enumerate(rows) if a['action_type']==chosen['action_type'] and a['identifier_refs']==chosen['identifier_refs']]
            report['selected_action_position']=matches[0] if len(matches)==1 else None
            report['cast_evidence']=extended
            report['validation_scope']='reviewed_literal_mana_and_observed_cast_trace_only'
    result['server_acceptance_verified']=False  # no blanket claim across samples/actions
    return result
