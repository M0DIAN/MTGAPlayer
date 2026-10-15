"""Finite historical combat configuration evidence, not a legality solver."""
import copy
from .raw_log import _id, COMBAT_SUBMITS
from .semantic_samples import _need, _keys, SampleError, _check_snapshot
from .semantic_cast import PROJECTION_V2

VERSION = 'mtgaplayer.semantic-samples.v3'
KINDS = ('declare_attackers', 'declare_blockers')
PROJECTION_V3 = {**copy.deepcopy(PROJECTION_V2),
    'combat': 'complete_current_request_selection_and_selected_public_result_only',
    'combat_cost': 'single_empty_object_uninterpreted',
    'combat_damage_and_global_requirements': 'unverified'}
FIRST = 'first_continuous_state_observed'


def _array(value):
    _need(type(value) is list and len(value) <= 256, 'request_unsupported')
    return value


def _ids(value):
    _array(value)
    _need(all(_id(x) and x > 0 for x in value) and len(set(value)) == len(value), 'request_unsupported')
    return value


def _public(snapshot, seat):
    return {o['object_ref'] for o in snapshot['objects']
            if o['zone'] == 'ZoneType_Battlefield' and o['controller'] == seat}


def _recipient(value, seat):
    _keys(value, ('type', 'playerSystemSeatId'))
    _need(value['type'] == 'DamageRecType_Player' and type(value['playerSystemSeatId']) is int and
          value['playerSystemSeatId'] == 3-seat, 'request_unsupported')
    return {'type': 'player', 'seat': value['playerSystemSeatId']}


def request(message, binding, refs, scope, snapshot):
    kind = 'declare_attackers' if binding['type'].endswith('AttackersReq') else 'declare_blockers'
    wrapper = 'declareAttackersReq' if kind == KINDS[0] else 'declareBlockersReq'
    _need(not set(message)-{'type','systemSeatIds','msgId','gameStateId','prompt',wrapper}, 'request_unsupported')
    body=message.get(wrapper)
    _keys(body, ('attackers','qualifiedAttackers','canSubmitAttackers','manaCost') if kind==KINDS[0] else ('blockers','manaCost'))
    _need(type(body['manaCost']) is list and body['manaCost']==[{}], 'request_unsupported')
    seat=scope[3]; own=_public(snapshot,seat); opposing=_public(snapshot,3-seat)
    def ref(value, domain):
        _need(_id(value) and value>0, 'request_unsupported')
        result=refs.ref('object',scope,value)
        _need(result in domain, 'request_unsupported')
        return result
    def attack(row, qualified=False):
        _need(type(row) is dict and set(row) in (
            {'attackerInstanceId','legalDamageRecipients'},
            *([] if qualified else [{'attackerInstanceId','legalDamageRecipients','selectedDamageRecipient'}])), 'request_unsupported')
        return {'object_ref':ref(row['attackerInstanceId'],own),
            'legal_recipients':[_recipient(x,seat) for x in _array(row['legalDamageRecipients'])],
            **({} if qualified else {'selected_recipient':_recipient(row['selectedDamageRecipient'],seat)
                                     if 'selectedDamageRecipient' in row else None})}
    payload={'mana_cost_shape':'single_empty_object_uninterpreted'}
    if kind==KINDS[0]:
        _need(body['canSubmitAttackers'] is True, 'request_unsupported')
        payload.update(attackers=[attack(row) for row in _array(body['attackers'])],
            qualified_attackers=[attack(row,True) for row in _array(body['qualifiedAttackers'])],
            can_submit_attackers=body['canSubmitAttackers'])
    else:
        rows=[]
        for row in _array(body['blockers']):
            _need(type(row) is dict and {'blockerInstanceId','maxAttackers'}<=row.keys() and
                  not set(row)-{'blockerInstanceId','maxAttackers','attackerInstanceIds','selectedAttackerInstanceIds'}, 'request_unsupported')
            _need(type(row['maxAttackers']) is int and row['maxAttackers']==1, 'request_unsupported')
            rows.append({'object_ref':ref(row['blockerInstanceId'],own), 'max_attackers':1,
                'candidate_attacker_refs':[ref(x,opposing) for x in _ids(row['attackerInstanceIds'])]
                                          if 'attackerInstanceIds' in row else None,
                'selected_attacker_refs':[ref(x,opposing) for x in _ids(row['selectedAttackerInstanceIds'])]
                                         if 'selectedAttackerInstanceIds' in row else None})
        payload['blockers']=rows
    value={'kind':kind,'payload':payload}
    try: check_request(value,snapshot,seat)
    except SampleError: raise SampleError('request_unsupported') from None
    return value


def check_request(value, snapshot, seat):
    _keys(value,('kind','payload'));_need(value['kind'] in KINDS)
    p=value['payload']; attack=value['kind']==KINDS[0]
    _keys(p, ('mana_cost_shape','attackers','qualified_attackers','can_submit_attackers') if attack else
          ('mana_cost_shape','blockers'))
    _need(p['mana_cost_shape']=='single_empty_object_uninterpreted')
    own,opposing=_public(snapshot,seat),_public(snapshot,3-seat)
    def recipient(v):
        _keys(v,('type','seat'));_need(v['type']=='player' and type(v['seat']) is int and v['seat']==3-seat)
    def rows(values, qualified=False):
        _array(values);seen=set()
        for row in values:
            _keys(row, ('object_ref','legal_recipients') if qualified else
                  ('object_ref','legal_recipients','selected_recipient') if attack else
                  ('object_ref','max_attackers','candidate_attacker_refs','selected_attacker_refs'))
            obj=row['object_ref'];_need(_id(obj) and obj in own and obj not in seen);seen.add(obj)
            if attack:
                _array(row['legal_recipients']);_need(len(row['legal_recipients'])==1)
                for r in row['legal_recipients']:recipient(r)
                if not qualified and row['selected_recipient'] is not None:
                    recipient(row['selected_recipient']);_need(row['selected_recipient'] in row['legal_recipients'])
            else:
                _need(type(row['max_attackers']) is int and row['max_attackers']==1)
                for key in ('candidate_attacker_refs','selected_attacker_refs'):
                    ids=row[key]
                    if ids is not None:_ids(ids);_need(set(ids)<=opposing)
                chosen=row['selected_attacker_refs']; offered=row['candidate_attacker_refs']
                _need(chosen is not None or offered is not None)
                if chosen is not None:
                    _need(len(chosen)<=row['max_attackers'])
                    if offered is not None:_need(set(chosen)<=set(offered))
        return seen
    if attack:
        _need(p['can_submit_attackers'] is True)
        _need(rows(p['attackers'])==rows(p['qualified_attackers'],True))
        _need([{k:v for k,v in r.items() if k!='selected_recipient'} for r in p['attackers']]==p['qualified_attackers'])
    else:rows(p['blockers'])


def response(payload, binding):
    _keys(payload,('type','respId','gameStateId'))
    _need(COMBAT_SUBMITS.get(payload['type'])==binding['type'], 'response_unsupported')
    return {'kind':'declare_attackers' if binding['type'].endswith('AttackersReq') else 'declare_blockers',
            'payload':{'submission_type':payload['type']}}


def facts(gs, refs, scope, snapshot):
    """Only explicit updates of public Battlefield objects; absent updates stay unknown."""
    public={o['object_ref'] for o in snapshot['objects'] if o['zone']=='ZoneType_Battlefield'}
    result=[];omitted=0
    try:
        annotations=gs.get('annotations',[])
        _need(type(annotations) is list and len(annotations)<=512)
        omitted=len(annotations)  # Values remain private; no annotation semantics are claimed.
        rows=gs.get('gameObjects',[]);_need(type(rows) is list and len(rows)<=512)
        for row in rows:
            obj=refs.ref('object',scope,row['instanceId'])
            if obj not in public:continue
            attack=row.get('attackState');block=row.get('blockState')
            _need(attack in (None,'AttackState_Declared','AttackState_Attacking') and
                  block in (None,'BlockState_Declared','BlockState_Blocking','BlockState_Blocked','BlockState_Unblocked'))
            target=None; attackers=None
            if 'attackInfo' in row:
                info=row['attackInfo'];_need(type(info) is dict and not set(info)-{'targetId','orderedBlockers'})
                if 'targetId' in info:
                    target=info['targetId'];_need(type(target) is int and target in (1,2))
            if 'blockInfo' in row:
                info=row['blockInfo'];_need(type(info) is dict and not set(info)-{'attackerIds','orderedAttackers'})
                if 'attackerIds' in info:attackers=[refs.ref('object',scope,x) for x in _ids(info['attackerIds'])]
                _need(attackers is None or set(attackers)<=public)
            result.append({'kind':'combat_object_update','object_ref':obj,'attack_state':attack,
                           'block_state':block,'target_seat':target,'attacker_refs':attackers})
        return result,'reviewed_combat_subset',omitted
    except (SampleError,KeyError,TypeError):
        return [],'unsupported_combat_update',omitted


def check_trace(trace, before):
    _keys(trace,('status','truncated','next_request_ref','states'))
    _need(trace['status'] in ('not_observed','eof','next_request_observed','interrupted',
                             'full_baseline_not_continuous',FIRST) and trace['truncated'] is False)
    _need(type(trace['states']) is list and len(trace['states'])<=1)
    _need(bool(trace['states'])==(trace['status']==FIRST))
    _need((_id(trace['next_request_ref']) and trace['next_request_ref']>0) if trace['status']=='next_request_observed'
          else trace['next_request_ref'] is None)
    if not trace['states']:return
    row=trace['states'][0]
    _keys(row,('snapshot','previous_state_ref','facts','facts_status','omitted_annotations'))
    _check_snapshot(row['snapshot']);_need(row['previous_state_ref']==before['state_ref'] and
        _id(row['previous_state_ref']) and row['snapshot']['state_ref']!=before['state_ref'])
    _need(row['facts_status'] in ('reviewed_combat_subset','unsupported_combat_update') and
          type(row['omitted_annotations']) is int and 0<=row['omitted_annotations']<=512)
    _need(type(row['facts']) is list and len(row['facts'])<=512)
    _need(row['facts_status']=='reviewed_combat_subset' or row['facts']==[])
    public={o['object_ref'] for o in row['snapshot']['objects'] if o['zone']=='ZoneType_Battlefield'};seen=set()
    for f in row['facts']:
        _keys(f,('kind','object_ref','attack_state','block_state','target_seat','attacker_refs'))
        _need(f['kind']=='combat_object_update' and _id(f['object_ref']) and f['object_ref'] in public and f['object_ref'] not in seen)
        seen.add(f['object_ref'])
        _need(f['attack_state'] in (None,'AttackState_Declared','AttackState_Attacking') and
              f['block_state'] in (None,'BlockState_Declared','BlockState_Blocking','BlockState_Blocked','BlockState_Unblocked'))
        _need(f['target_seat'] is None or type(f['target_seat']) is int and f['target_seat'] in (1,2))
        if f['attacker_refs'] is not None:_ids(f['attacker_refs']);_need(set(f['attacker_refs'])<=public)


def evaluate(sample):
    attack=sample['request']['kind']==KINDS[0];p=sample['request']['payload'];seat=sample['identity']['self_seat']
    rows=p['attackers'] if attack else p['blockers']
    selected={r['object_ref']:r['selected_recipient'] if attack else r['selected_attacker_refs'] for r in rows
              if (r['selected_recipient'] is not None if attack else bool(r['selected_attacker_refs']))}
    known='verified_known_constraints' if attack or all(
        r['candidate_attacker_refs'] is not None for r in rows if r['object_ref'] in selected) else 'insufficient_evidence'
    matched=False
    trace=sample['trace']
    if selected and trace['status']==FIRST:
        state=trace['states'][0];current=state['snapshot'];own=_public(current,seat);opposing=_public(current,3-seat)
        fs={f['object_ref']:f for f in state['facts']}
        positive={obj for obj,f in fs.items() if obj in own and
                  (f['attack_state']=='AttackState_Attacking' if attack else f['block_state']=='BlockState_Blocking')}
        matched=state['facts_status']=='reviewed_combat_subset' and positive==set(selected)
        for obj,target in selected.items():
            f=fs.get(obj)
            matched=matched and obj in own and f is not None and (
                f['target_seat']==target['seat'] if attack else f['attacker_refs']==target and set(target)<=opposing)
            if f is not None:
                # This finite profile has disjoint attacking/blocking roles.
                # Blocked/Unblocked describe an attacker and remain allowed.
                matched=matched and (f['block_state'] not in ('BlockState_Declared','BlockState_Blocking') and
                    f['attacker_refs'] is None if attack else
                    f['attack_state'] is None and f['target_seat'] is None)
            if not attack:
                for attacker in target:
                    observed=fs.get(attacker)
                    if observed is not None:
                        matched=matched and observed['block_state'] in (None,'BlockState_Blocked') and \
                            observed['attack_state'] in (None,'AttackState_Attacking') and \
                            observed['target_seat'] in (None,seat)
    return {'current_request_selection_preserved':True,'final_submission_observed':True,
        'selected_configuration':[{'object_ref':obj,'recipient':value} if attack else
                                  {'object_ref':obj,'attacker_refs':value} for obj,value in selected.items()],
        'known_capacity_and_membership':known,'selected_public_result_observed':bool(matched),
        'unobserved_participants':'unknown','combat_cost':'uninterpreted_single_empty_object',
        'complete_combination_validation':'insufficient_evidence','complete_legality_verified':False,
        'server_acceptance_verified':False}


def replay(document):
    from .semantic_samples import _check_envelope, _check_episode_base, _check_successor
    from .semantic_cast import replay as replay_v2, VERSION as V2
    _check_envelope(document,VERSION,PROJECTION_V3)
    reports=[]
    for index,sample in enumerate(document['samples']):
        _need(type(sample) is dict and type(sample.get('request')) is dict)
        if sample['request'].get('kind') not in KINDS:
            one=copy.deepcopy(document);one['schema_version']=V2;one['projection']=copy.deepcopy(PROJECTION_V2)
            one['samples']=[sample];one['counts']={'matched_pairs':1,'exported':1,'sample_limit_omissions':0,'unsupported_pairs':0};one['unsupported_reasons']=[]
            report=replay_v2(one)['samples'][0];report['sample_index']=index;reports.append(report);continue
        _check_episode_base(sample,('trace',))
        _check_successor(sample['successor'],sample['before'])
        check_request(sample['request'],sample['before'],sample['identity']['self_seat'])
        _keys(sample['response'],('kind','payload'));_keys(sample['response']['payload'],('submission_type',))
        expected='ClientMessageType_SubmitAttackersReq' if sample['request']['kind']==KINDS[0] else 'ClientMessageType_SubmitBlockersReq'
        _need(sample['response']['kind']==sample['request']['kind'] and sample['response']['payload']['submission_type']==expected)
        check_trace(sample['trace'],sample['before'])
        if sample['trace']['states']:
            _need(sample['successor']['status']=='continuous_state_observed' and
                  sample['successor']['snapshot']==sample['trace']['states'][0]['snapshot'])
        elif sample['trace']['status']=='next_request_observed':
            _need(sample['successor']['status']=='next_request_observed' and
                  sample['successor']['request_ref']==sample['trace']['next_request_ref'])
        else:
            expected={'interrupted':'interrupted',
                      'full_baseline_not_continuous':'full_baseline_not_continuous'}.get(
                          sample['trace']['status'],'not_observed')
            _need(sample['successor']['status']==expected)
        reports.append({'sample_index':index,'request_kind':sample['request']['kind'],
            'validation_scope':'literal_current_combat_configuration_and_selected_public_result_only',
            'successor_status':sample['successor']['status'],'trace_status':sample['trace']['status'],
            'combat_evidence':evaluate(sample)})
    from .decision_consumer import EXECUTION
    return {'schema_version':'mtgaplayer.semantic-sample-replay.v3','samples':reports,'artifact_checks_passed':True,
        'raw_source_auth_revalidated':False,'complete_legality_verified':False,'server_acceptance_verified':False,
        'read_only':True,'execution':dict(EXECUTION)}
