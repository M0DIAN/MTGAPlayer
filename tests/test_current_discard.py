"""One real sanitized current request; all mutations/transport/raw controls synthetic."""
import copy,io,json,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from mtgaplayer.choice_candidates import enumerate_known_candidates,assess_current_known_candidates,DISCARD_VERSION
from mtgaplayer.choice_validation import validate_proposed_choice,check_proposal,assess_current_choice
from mtgaplayer.decision_consumer import DecisionConsumer,EXECUTION,consume_events,_state
from mtgaplayer.decision_publisher import DecisionPublisher
from mtgaplayer.decision_advisor import assess_decision_state
from mtgaplayer.semantic_hand import check_current_discard_selection,ENUMS,UNKNOWN
from mtgaplayer.request_parameters import project
from mtgaplayer.raw_log import RawReducer
from test_decision_publisher import ManualClock

FIXTURES=Path(__file__).parent/'fixtures'


class CurrentDiscardTests(unittest.TestCase):
    def setUp(self):
        self.fixture=json.loads((FIXTURES/'current_discard_real_v8.json').read_text(encoding='utf-8'))
        self.state=self.fixture['before_response'];self.params=self.state['legal_action_space']['request_parameters']
        self.payload=self.params['discard_request']['payload'];self.offered=self.payload['offered_object_refs']
    def discover(self,state=None,**kwargs):return enumerate_known_candidates(self.state if state is None else state,version=4,**kwargs)
    def unknown(self,result):
        self.assertEqual(result['schema_version'],DISCARD_VERSION);self.assertEqual(result['returned_candidates'],0)
        self.assertEqual(result['candidates'],[]);self.assertEqual(result['known_constraints'],'insufficient_evidence')
        self.assertTrue(all(result[k] is False for k in EXECUTION))
    def transport(self,history=False):
        clock=ManualClock();pub=DecisionPublisher(clock_ns=clock,session_id='synthetic-discard',state_version=8)
        state=copy.deepcopy(self.state);state['source'].update(mode='watch',phase='history' if history else 'append',stopped=False)
        doc={'decision_state':state,'source':{'phase':state['source']['phase'],'partial_record':False}}
        meta={'poll_started_ns':clock(),'poll_completed_ns':clock(),'poll_read_ns':0,'reducer_apply_ns':0,
            'decision_state_assembly_ns':0,'request_changed':True,'new_final_request':True}
        events=pub.observe(doc,meta);consumer=DecisionConsumer(10000,500,clock)
        for event in events:self.assertTrue(consumer.accept_event(event))
        return pub,consumer,clock,doc,meta,events

    def test_real_eight_equal_proposals_reuse_same_validator_and_never_lend_chosen_outcome(self):
        before=copy.deepcopy(self.state);r=self.discover()
        self.assertEqual(r['candidates'],self.fixture['proposals']);self.assertEqual(r['returned_candidates'],8)
        self.assertEqual(r['candidate_total_for_reviewed_constraints'],8)
        self.assertEqual((r['minimum'],r['maximum'],r['selected_count'],r['offered_member_count']),(1,1,None,8))
        self.assertEqual((r['verified_probes'],r['unknown_probes'],r['contradicted_probes']),(8,0,0))
        self.assertEqual([p['proposed_discard_selection']['selected_object_refs'] for p in r['candidates']],[[i] for i in self.offered])
        self.assertEqual(self.state,before)
        for p in r['candidates']:
            check_proposal(p);v=validate_proposed_choice(self.state,p)
            self.assertEqual(v['known_constraints'],'verified_known_constraints')
            for key in ('historical_response_used','rules_effect_verified','complete_costs_verified',
                'complete_payment_verified','mana_payment_verified','unfiltered_domain_complete_verified',
                'quantity_rules_complete_verified',*EXECUTION):self.assertIs(v[key],False,key)
        self.assertNotIn('selected_card_discard_observed',json.dumps(r))
        self.assertIsNone(r['source_snapshot_ref']);self.assertEqual(assess_decision_state(self.state)['assessment_status'],'abstain')
        for state in (self.fixture['after_response'],self.fixture['after_successor_record']):
            self.unknown(self.discover(state))
            for p in r['candidates']:self.assertEqual(validate_proposed_choice(state,p)['known_constraints'],'insufficient_evidence')

    def test_return_limit_and_bounds_are_explicit(self):
        r=self.discover(limit=3)
        self.assertEqual((r['returned_candidates'],r['candidate_total_for_reviewed_constraints'],r['omitted_due_to_return_limit']),(3,8,5))
        self.assertTrue(r['truncated']);self.assertFalse(r['exhaustive_for_reviewed_constraints'])
        for limit in (0,65,True):
            with self.assertRaises(ValueError):self.discover(limit=limit)
        for version in (1,5,True,4.0,'4'):
            with self.assertRaises(ValueError):enumerate_known_candidates(self.state,version=version)

    def test_manual_nonmember_zero_duplicate_and_count_are_not_valid_discards(self):
        for values in ([],self.offered[:2],[self.offered[0]]*2,[999999]):
            proposal=copy.deepcopy(self.fixture['proposals'][0]);proposal['proposed_discard_selection']['selected_object_refs']=values
            self.assertEqual(validate_proposed_choice(self.state,proposal)['known_constraints'],'violated_known_constraints')
        for value in (0,True,1.0,'1'):
            proposal=copy.deepcopy(self.fixture['proposals'][0]);proposal['proposed_discard_selection']['selected_object_refs']=[value]
            with self.assertRaises(ValueError):check_proposal(proposal)
            self.assertEqual(validate_proposed_choice(self.state,proposal)['known_constraints'],'insufficient_evidence')

    def test_missing_unknown_or_nonexact_request_fields_withhold_whole_domain(self):
        for key in ('min_sel','max_sel',*ENUMS,*UNKNOWN):
            for mode in ('missing','changed'):
                state=copy.deepcopy(self.state);payload=state['legal_action_space']['request_parameters']['discard_request']['payload']
                if mode=='missing':del payload[key]
                else:payload[key]=True if key in ('min_sel','max_sel') else 'unsupported'
                self.unknown(self.discover(state))
        for key in ('min_sel','max_sel'):
            for value in (None,0,2,1.0):
                state=copy.deepcopy(self.state);state['legal_action_space']['request_parameters']['discard_request']['payload'][key]=value
                self.unknown(self.discover(state))
        for field in ('future_response','unfilteredIds','weights'):
            state=copy.deepcopy(self.state);state['legal_action_space']['request_parameters']['discard_request']['payload'][field]='PRIVATE_SENTINEL'
            r=self.discover(state);self.unknown(r);self.assertNotIn('PRIVATE_SENTINEL',json.dumps(r))

    def test_invisible_foreign_or_duplicate_own_hand_and_nonunique_offers_fail_closed(self):
        for mode in ('invisible','foreign','not_hand','duplicate_visible','duplicate_offer','missing_offer','bool_offer'):
            state=copy.deepcopy(self.state);offered=state['legal_action_space']['request_parameters']['discard_request']['payload']['offered_object_refs']
            obj=next(o for o in state['visible_objects'] if o['instance_id']==offered[0])
            if mode=='invisible':state['visible_objects'].remove(obj)
            elif mode=='foreign':obj['owner_seat']=3-state['binding']['self_seat']
            elif mode=='not_hand':obj['zone']='ZoneType_Graveyard'
            elif mode=='duplicate_visible':state['visible_objects'].append(copy.deepcopy(obj))
            elif mode=='duplicate_offer':offered[1]=offered[0]
            elif mode=='missing_offer':offered.pop()
            else:offered[0]=True
            self.unknown(self.discover(state))

    def test_cross_binding_versions_frontier_and_profiles_cannot_borrow_evidence(self):
        state=copy.deepcopy(self.state);state['binding']['request_id']=0
        state['legal_action_space']['request_parameters']['binding']['request_id']=0
        self.assertEqual(self.discover(state)['returned_candidates'],8)  # Protocol request IDs permit0; objects don't.
        for key in self.state['binding']:
            state=copy.deepcopy(self.state);value=state['binding'][key]
            state['binding'][key]='different' if type(value) is str else value+1
            self.unknown(self.discover(state))
        for value in (True,1.0):
            state=copy.deepcopy(self.state);state['legal_action_space']['request_parameters']['binding']['self_seat']=value
            self.unknown(self.discover(state))
        for mode in ('old_version','status','frontier','profile'):
            state=copy.deepcopy(self.state)
            if mode=='old_version':state['schema_version']='mtgaplayer.decision-state.v7'
            elif mode=='status':state['status']='state_observed_without_request'
            elif mode=='frontier':state['legal_action_space']['immediate_frontier']['projection']={}
            else:state['legal_action_space']['request_parameters']['profile']='reviewed_single_slot_public_targets'
            self.unknown(self.discover(state))

    def test_producer_uses_strict_physical_hand_membership_and_visibility_proof(self):
        reducer=RawReducer();reducer.seat=1
        refs=list(range(100,108));reducer.zones={1:{'zoneId':1,'type':'ZoneType_Hand','ownerSeatId':1,'objectInstanceIds':refs[:]}}
        reducer.objects={ref:{'instanceId':ref,'zoneId':1,'type':'GameObjectType_Card','ownerSeatId':1,'viewers':[1]} for ref in refs}
        visible=[{'instance_id':ref,'zone':'ZoneType_Hand','owner_seat':1} for ref in refs]
        message={'type':'GREMessageType_SelectNReq','systemSeatIds':[1],'msgId':10,'gameStateId':20,
            'prompt':{'promptId':1,'parameters':[{'parameterName':'synthetic','type':'ParameterType_Number','numberValue':7}]},
            'selectNReq':{'minSel':1,'maxSel':1,'ids':refs,'context':'SelectionContext_Discard','optionContext':'OptionContext_TurnBased',
                'idType':'IdType_InstanceId','listType':'SelectionListType_Dynamic','validationType':'SelectionValidationType_NonRepeatable'}}
        def produce(r,m=message):return project(m,visible,1,current_discard=True,current_hand_refs=r._reviewed_current_hand_refs())
        self.assertIsNotNone(produce(reducer));self.assertIsNone(project(message,visible,1))
        for mode in ('wrong_zone','foreign','boolean_owner','no_view','boolean_view','ability','duplicate_membership'):
            r=copy.deepcopy(reducer);obj=r.objects[100]
            if mode=='wrong_zone':obj['zoneId']=2
            elif mode=='foreign':obj['ownerSeatId']=2
            elif mode=='boolean_owner':obj['ownerSeatId']=True
            elif mode=='no_view':obj['viewers']=[]
            elif mode=='boolean_view':obj['viewers']=[True]
            elif mode=='ability':obj['type']='GameObjectType_Ability'
            else:r.zones[2]={'objectInstanceIds':[100]}
            self.assertIsNone(produce(r),mode)
        for key in ('minSel','maxSel','optionContext','validationType'):
            m=copy.deepcopy(message);del m['selectNReq'][key];self.assertIsNone(produce(reducer,m))
        m=copy.deepcopy(message);m['selectNReq']['minWeight']=0;self.assertIsNone(produce(reducer,m))
        # Synthetic reducer initialization isolates the existing digest ledger.
        reducer._include_request_parameters=True;reducer._include_current_discard=True
        reducer.match=reducer.room_match='synthetic';reducer.game=1;reducer.version=20
        reducer.room_seat=1;reducer.error=None;reducer.room_state='MatchGameRoomStateType_Playing'
        reducer.game_info={'stage':'GameStage_Play'}
        reducer._message(message,None)
        self.assertIsNotNone(reducer.request['_request_parameters'])
        changed=copy.deepcopy(message);changed['selectNReq']['minSel']=2
        reducer._message(changed,None)
        from mtgaplayer.response_evidence import _current_verified_raw_request
        self.assertTrue(reducer.conflict);self.assertIsNone(_current_verified_raw_request(reducer,message))
        self.assertFalse(reducer.document()['current']['valid'])

    def test_validator_drift_and_oversize_output_discard_all_candidates(self):
        from mtgaplayer import choice_validation,choice_candidates
        original=choice_validation.validate_proposed_choice
        for key,value in (('schema_version','unknown'),('validation_scope','other'),('read_only',1),
            ('complete_payment_verified',0),('input_sent',True),('quantity_rules_complete_verified',None),
            ('target_domain_complete_verified',True),('complete_target_legality_verified',True),
            ('target_selection_legality_verified',True)):
            def changed(*args,**kwargs):
                r=original(*args,**kwargs);r[key]=value;return r
            with patch.object(choice_validation,'validate_proposed_choice',side_effect=changed):self.unknown(self.discover())
        _,consumer,_,_,_,_=self.transport();ref=consumer.current_view()['current_snapshot_ref']
        def boolean_ref(*args,**kwargs):
            r=original(*args,**kwargs);r['source_snapshot_ref']['binding']['source_generation']=True;return r
        with patch.object(choice_validation,'validate_proposed_choice',side_effect=boolean_ref):self.unknown(self.discover(source_snapshot_ref=ref))
        bound=choice_candidates._bounded_json
        def small(value):
            bound(value)
            if type(value) is dict and value.get('schema_version')==DISCARD_VERSION:raise ValueError('synthetic_size_limit')
        with patch.object(choice_candidates,'_bounded_json',side_effect=small):self.unknown(self.discover())

    def test_history_expiry_stop_and_after_calculation_snapshot_check(self):
        _,consumer,_,_,_,_=self.transport(history=True);self.unknown(assess_current_known_candidates(consumer,version=4))
        pub,consumer,clock,_,_,_=self.transport();self.assertEqual(assess_current_known_candidates(consumer,version=4)['returned_candidates'],8)
        clock.advance(501);self.unknown(assess_current_known_candidates(consumer,version=4))
        pub,consumer,clock,_,_,_=self.transport()
        for event in pub.stop():self.assertTrue(consumer.accept_event(event))
        self.unknown(assess_current_known_candidates(consumer,version=4))
        from mtgaplayer import choice_candidates
        original=choice_candidates.enumerate_known_candidates
        _,consumer,clock,_,_,_=self.transport()
        def slow(*args,**kwargs):r=original(*args,**kwargs);clock.advance(501);return r
        with patch.object(choice_candidates,'enumerate_known_candidates',side_effect=slow):self.unknown(assess_current_known_candidates(consumer,version=4))

    def test_consumption_supersession_partial_reset_and_wrong_session_revoke_all_eight(self):
        for mode in ('consumed','replacement','partial','reset','session'):
            pub,consumer,_,doc,meta,_=self.transport();old=assess_current_known_candidates(consumer,version=4)['candidates']
            if mode=='session':
                event=copy.deepcopy(pub.observe(doc,meta)[-1]);event['session_id']='wrong'
                self.assertFalse(consumer.accept_event(event))
            else:
                if mode=='consumed':
                    state=copy.deepcopy(self.fixture['after_response']);state['source'].update(mode='watch',phase='append',stopped=False)
                    doc['decision_state']=state;meta=dict(meta,request_consumed=True,new_final_request=False)
                elif mode=='replacement':
                    def replace(value):
                        if type(value) is dict:return {k:(v+1 if k=='request_id' and type(v) is int else replace(v)) for k,v in value.items()}
                        if type(value) is list:return [replace(v) for v in value]
                        return value
                    doc['decision_state']=replace(doc['decision_state']);meta=dict(meta,new_final_request=False)
                else:
                    doc={'decision_state':None,'current':{},'source':{'phase':'append','partial_record':mode=='partial'}}
                    meta=dict(meta,source_reset=mode=='reset',continuity_error=True,new_final_request=False)
                for event in pub.observe(doc,meta):self.assertTrue(consumer.accept_event(event))
            self.unknown(assess_current_known_candidates(consumer,version=4))
            self.assertTrue(all(assess_current_choice(consumer,p)['known_constraints']=='insufficient_evidence' for p in old))

    def test_cli_explicit_v4_has_no_proposal_input_and_stops_naturally(self):
        pub,_,_,_,_,events=self.transport();events+=pub.stop()
        command=[sys.executable,'-m','mtgaplayer','consume-events','--known-choice-candidates','--known-choice-candidates-version','4']
        run=subprocess.run(command,input=''.join(json.dumps(e)+'\n' for e in events),capture_output=True,text=True,timeout=20)
        self.assertEqual(run.returncode,0,run.stderr);values=[json.loads(line) for line in run.stdout.splitlines()]
        self.assertTrue(any(v['known_choice_candidates']['returned_candidates']==8 for v in values))
        self.assertEqual(values[-1]['known_choice_candidates']['returned_candidates'],0)
        self.assertTrue(all(v['known_choice_candidates']['schema_version']==DISCARD_VERSION for v in values))
        self.assertTrue(all('choice_validation' not in v for v in values))

    def test_consumer_sidecar_recheck_never_downgrades_v4_on_expiration(self):
        from mtgaplayer import choice_candidates
        pub,_,clock,_,_,events=self.transport();events+=pub.stop();seen=[];output=[];advanced=False
        original=choice_candidates.assess_current_known_candidates
        def slow(c,*,version=2):
            nonlocal advanced
            seen.append(version);r=original(c,version=version)
            if r['returned_candidates'] and not advanced:clock.advance(501);advanced=True
            return r
        with patch.object(choice_candidates,'assess_current_known_candidates',side_effect=slow):
            consume_events(io.StringIO(''.join(json.dumps(e)+'\n' for e in events)),output.append,
                DecisionConsumer(10000,500,clock),known_choice_candidates=True,known_choice_candidates_version=4)
        self.assertGreaterEqual(len(seen),2);self.assertEqual(set(seen),{4})
        self.assertTrue(all(r['known_choice_candidates']['schema_version']==DISCARD_VERSION for r in output))
        self.assertEqual(output[-1]['known_choice_candidates']['returned_candidates'],0)

    def test_legacy_known_candidates_manual_target_profiles_and_advisor_unchanged(self):
        for state in (self.state,self.fixture['after_response']):
            self.assertEqual(enumerate_known_candidates(state),enumerate_known_candidates(state,version=2))
            self.assertEqual(enumerate_known_candidates(state,version=3)['returned_candidates'],0)
        for name,key in (('decision_state_activate_target_member_real_v7.json','before_response'),('current_selected_target_set_real_v5.json','before_submit')):
            fixture=json.loads((FIXTURES/name).read_text(encoding='utf-8'));state=fixture[key]
            self.assertEqual(enumerate_known_candidates(state,version=3)['returned_candidates'],1)
            self.unknown(self.discover(state));self.assertEqual(validate_proposed_choice(state,fixture['proposal'])['known_constraints'],'verified_known_constraints')


if __name__=='__main__':unittest.main()
