"""Real preSubmit State; raw/metadata mutations are synthetic structural controls."""
import copy,json,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from mtgaplayer.cli import replay,watch_decision_events
from mtgaplayer.choice_validation import validate_proposed_choice,assess_current_choice,load_proposal
from mtgaplayer.choice_candidates import enumerate_known_candidates
from mtgaplayer.decision_consumer import DecisionConsumer,EXECUTION
from mtgaplayer.raw_log import RawReducer
from mtgaplayer.response_evidence import _current_verified_raw_request
from mtgaplayer.semantic_targets import check_final_set,literal_selected,CURRENT_SELECTED_SCOPE
from test_decision_publisher import ManualClock,poll_events,append
from test_action_frontier import save

ROOT=Path(__file__).resolve().parents[1]
FIXTURE=ROOT/'tests/fixtures/current_selected_target_set_real_v5.json'


class CurrentSelectedTargetTests(unittest.TestCase):
    def setUp(self):
        self.real=json.loads(FIXTURE.read_text());self.state=self.real['before_submit'];self.proposal=self.real['proposal']
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.path=Path(tmp.name)/'synthetic.log'
        self.rows=[json.loads(s) for s in (FIXTURE.parent/'player_log_single_target.jsonl').read_text().splitlines()]
        # Existing real Cast fixture is NOT an Activate positive. Only this
        # synthetic raw control changes its source type to an explicit Ability.
        source=self.msg(self.rows)['selectTargetsReq']['sourceId']
        for record in self.rows:
            for msg in record.get('greToClientEvent',{}).get('greToClientMessages',[]):
                for obj in msg.get('gameStateMessage',{}).get('gameObjects',[]):
                    if obj['instanceId']==source:obj['type']='GameObjectType_Ability'

    def msg(self,rows):return rows[108]['greToClientEvent']['greToClientMessages'][0]
    def request(self,state=None):return (state or self.state)['legal_action_space']['request_parameters']['targets']
    def result(self,state=None,proposal=None):return validate_proposed_choice(state or self.state,proposal or self.proposal)
    def unknown(self,result,reason=None):
        self.assertEqual(result['known_constraints'],'insufficient_evidence')
        if reason:self.assertIn(reason,result['reasons'])
        self.assertTrue(all(result[k] is False for k in EXECUTION))
    def raw(self,rows=None,version=5):
        save(self.path,rows or self.rows[:109]);return replay(self.path,format='player-log',decision_state_version=version)
    def proposal_for(self,state):
        request=self.request(state)
        return {'request_identity':copy.deepcopy(state['binding']),'proposed_current_selected_target_set':{
            **{k:request[k] for k in ('source_object_ref','ability_grp_ref','targeting_ability_grp_ref','target_idx','targeting_player')},
            'object_refs':literal_selected(request)}}

    def test_real_current_selected_literal_is_explicit_and_read_only(self):
        r=self.result();self.assertEqual(r['known_constraints'],'verified_known_constraints')
        self.assertEqual(r['validation_scope'],CURRENT_SELECTED_SCOPE)
        self.assertTrue(r['current_selected_literal_verified'])
        for key in ('complete_target_legality_verified','target_domain_complete_verified',
            'target_quantity_completeness_verified','complete_costs_verified','complete_payment_verified',
            'mana_payment_verified','new_selectable_domain_used','target_set_enumeration_performed','historical_response_used',*EXECUTION):
            self.assertIs(r[key],False,key)
        self.assertEqual([self.request()[k] for k in ('min_targets','max_targets','selected_count')],[1,1,1])

    def test_legacy_unselect_semantics_and_candidates_stay_unknown(self):
        p=self.proposal['proposed_current_selected_target_set']
        old={k:p[k] for k in ('source_object_ref','target_idx','object_refs')}
        self.assertEqual(check_final_set(self.request(),old),('insufficient_evidence','complete_current_select_domain_not_observed'))
        self.unknown(self.result(proposal={'request_identity':self.state['binding'],'proposed_final_target_set':old}),
            'complete_current_select_domain_not_observed')
        candidates=enumerate_known_candidates(self.state)
        self.assertEqual(candidates['reason'],'complete_current_select_domain_not_observed')
        self.assertEqual(candidates['candidates'],[])

    def test_explicit_quantity_profile_does_not_fill_missing_or_other_counts(self):
        for key in ('min_targets','max_targets','selected_count'):
            for value in (None,0,2,True):
                state=copy.deepcopy(self.state);self.request(state)[key]=value
                self.unknown(self.result(state))
        for entries in (None,[],[{'object_ref':self.request()['entries'][0]['object_ref'],'legal_action':'SelectAction_Select'}]):
            state=copy.deepcopy(self.state);self.request(state)['entries']=entries
            self.unknown(self.result(state))

    def test_duplicate_excess_mixed_or_unforeseen_entries_do_not_certify(self):
        for mode in ('duplicate','excess','mixed','extra'):
            state=copy.deepcopy(self.state);request=self.request(state)
            if mode=='extra':request['entries'][0]['future_result']='PRIVATE_SENTINEL'
            else:
                extra=copy.deepcopy(request['entries'][0])
                if mode!='duplicate':extra['object_ref']=next(o['instance_id'] for o in state['visible_objects'] if o['zone']=='ZoneType_Battlefield' and o['instance_id']!=extra['object_ref'])
                if mode=='mixed':extra['legal_action']='SelectAction_Select'
                request['entries'].append(extra)
            self.unknown(self.result(state))

    def test_exact_set_and_source_group_slot_seat_bindings(self):
        member=self.proposal['proposed_current_selected_target_set']
        other=next(o['instance_id'] for o in self.state['visible_objects'] if o['zone']=='ZoneType_Battlefield' and o['instance_id'] not in member['object_refs'])
        for refs in ([],[other],member['object_refs']*2):
            p=copy.deepcopy(self.proposal);p['proposed_current_selected_target_set']['object_refs']=refs
            result=self.result(proposal=p);self.assertEqual(result['known_constraints'],'violated_known_constraints')
            self.assertFalse(result['complete_target_legality_verified'])
        for key in ('source_object_ref','ability_grp_ref','targeting_ability_grp_ref','target_idx','targeting_player'):
            p=copy.deepcopy(self.proposal);p['proposed_current_selected_target_set'][key]+=1
            self.unknown(self.result(proposal=p))
        for key in self.proposal['request_identity']:
            p=copy.deepcopy(self.proposal);v=p['request_identity'][key]
            p['request_identity'][key]='wrong' if isinstance(v,str) else v+1
            self.unknown(self.result(proposal=p))

    def test_strict_boolean_identities_and_nested_scope_cannot_impersonate_ints(self):
        for key in ('source_generation','game','self_seat','game_state_id','request_id'):
            state=copy.deepcopy(self.state);state['legal_action_space']['request_parameters']['binding'][key]=True
            self.unknown(self.result(state))
        for key in ('source_object_ref','ability_grp_ref','targeting_ability_grp_ref','target_idx','targeting_player'):
            p=copy.deepcopy(self.proposal);p['proposed_current_selected_target_set'][key]=True
            self.unknown(self.result(proposal=p))
        p=copy.deepcopy(self.proposal);p['proposed_current_selected_target_set']['object_refs']=[True]
        self.unknown(self.result(proposal=p))

    def test_public_stack_source_must_be_explicit_ability_and_target_current_bf(self):
        source=self.request()['source_object_ref'];target=self.request()['entries'][0]['object_ref']
        for typ in (None,'GameObjectType_Card','GameObjectType_Token'):
            state=copy.deepcopy(self.state)
            next(m for m in state['game']['stack']['members'] if m['instance_id']==source)['object_type']=typ
            self.unknown(self.result(state),'current_public_stack_ability_not_observed')
        state=copy.deepcopy(self.state);state['visible_objects']=[o for o in state['visible_objects'] if o['instance_id']!=target]
        self.unknown(self.result(state))
        state=copy.deepcopy(self.state);state['visible_objects'].append(copy.deepcopy(state['visible_objects'][0]))
        self.unknown(self.result(state))

    def test_raw_unreviewed_fields_hidden_target_and_conflicting_digest_withhold(self):
        for mode in ('extra','highlight','hidden','digest'):
            rows=copy.deepcopy(self.rows[:109]);msg=self.msg(rows)
            if mode=='extra':msg['selectTargetsReq']['targets'][0]['unknown']='PRIVATE_SENTINEL'
            elif mode=='highlight':msg['selectTargetsReq']['targets'][0]['targets'][0]['highlight']=True
            elif mode=='hidden':
                target=msg['selectTargetsReq']['targets'][0]['targets'][0]['targetInstanceId']
                for record in rows:
                    for m in record.get('greToClientEvent',{}).get('greToClientMessages',[]):
                        for obj in m.get('gameStateMessage',{}).get('gameObjects',[]):
                            if obj['instanceId']==target:obj['visibility']='Visibility_Private'
            else:
                changed=copy.deepcopy(rows[108]);changed['greToClientEvent']['greToClientMessages'][0]['selectTargetsReq']['targets'][0]['selectedTargets']=0
                rows.append(changed)
            doc=self.raw(rows)
            if mode=='digest':self.assertIsNone(doc['decision_state'])
            else:self.assertIsNone(doc['decision_state']['legal_action_space']['request_parameters'])
            self.assertNotIn('PRIVATE_SENTINEL',json.dumps(doc))
        reducer=RawReducer(include_request_parameters=True);reducer.reset(1)
        for record in self.rows[:109]:reducer.apply(record)
        msg=self.msg(self.rows);self.assertIsNotNone(_current_verified_raw_request(reducer,msg))
        for key in ('msgId','gameStateId'):
            changed=copy.deepcopy(msg);changed[key]+=1
            self.assertIsNone(_current_verified_raw_request(reducer,changed))

    def test_existing_state_versions_and_earlier_select_domain_remain_independent(self):
        for version in (5,6,7):
            state=self.raw(version=version)['decision_state'];p=self.proposal_for(state)
            self.assertEqual(self.result(state,p)['known_constraints'],'verified_known_constraints')
            earlier=self.raw(self.rows[:106],version)['decision_state']
            candidates=enumerate_known_candidates(earlier)
            self.assertEqual(candidates['returned_candidates'],4)
            self.unknown(self.result(earlier,p))

    def test_response_replacement_partial_gap_and_normal_stop_revoke_current(self):
        for mode in ('response','replacement','partial','gap','stop'):
            save(self.path,self.rows[:108]);clock=ManualClock()
            stream=watch_decision_events(self.path,interval=0,samples=5,clock_ns=clock,decision_state_version=5)
            consumer=DecisionConsumer(clock_ns=clock)
            for event in poll_events(stream):self.assertTrue(consumer.accept_event(event))
            append(self.path,[self.rows[108]])
            for event in poll_events(stream):self.assertTrue(consumer.accept_event(event))
            p=self.proposal_for(consumer.current_view()['decision_state'])
            self.assertEqual(assess_current_choice(consumer,p)['known_constraints'],'verified_known_constraints')
            if mode=='response':append(self.path,[self.rows[109]])
            elif mode=='replacement':
                replacement=copy.deepcopy(self.rows[108]);replacement['greToClientEvent']['greToClientMessages'][0]['msgId']+=100
                append(self.path,[replacement])
            elif mode=='partial':
                with self.path.open('ab') as out:out.write(b'{"greToClientEvent":')
            elif mode=='gap':
                gap=copy.deepcopy(self.rows[110]);gap['greToClientEvent']['greToClientMessages'][0]['gameStateMessage']['prevGameStateId']+=100
                append(self.path,[gap])
            else:
                for event in stream:self.assertTrue(consumer.accept_event(event))
            if mode!='stop':
                for event in poll_events(stream):self.assertTrue(consumer.accept_event(event))
            self.unknown(assess_current_choice(consumer,p));stream.close()

    def test_history_expiry_and_check_completion_recheck_do_not_keep_old_set(self):
        save(self.path,self.rows[:109]);clock=ManualClock()
        stream=watch_decision_events(self.path,interval=0,samples=3,clock_ns=clock,decision_state_version=5);self.addCleanup(stream.close)
        events=poll_events(stream);consumer=DecisionConsumer(clock_ns=clock)
        for event in events:self.assertTrue(consumer.accept_event(event))
        p=self.proposal_for(consumer.current_view()['decision_state'])
        self.unknown(assess_current_choice(consumer,p),'current_request_not_observed')
        event=copy.deepcopy(next(e for e in events if e['event_type']=='snapshot'))
        event['phase']=event['decision_state']['source']['phase']='append';event['new_request_observed']=True
        for slow in (False,True):
            consumer=DecisionConsumer(10000,500,clock);self.assertTrue(consumer.accept_event(event))
            if not slow:clock.advance(501);self.unknown(assess_current_choice(consumer,p))
            else:
                original=validate_proposed_choice
                def delayed(*args,**kwargs):
                    result=original(*args,**kwargs);clock.advance(501);return result
                with patch('mtgaplayer.choice_validation.validate_proposed_choice',side_effect=delayed):
                    self.unknown(assess_current_choice(consumer,p),'current_snapshot_expired_or_changed')

    def test_future_evidence_and_consumed_real_request_cannot_supply_current_set(self):
        self.unknown(self.result(self.real['after_submit']))
        history=json.loads((FIXTURE.parent/'semantic_activate_targets_real_v10.json').read_text())
        self.assertEqual(history['samples'][0]['targets'][1]['location'],{'record':1425,'message':1})
        for location in ('state','proposal'):
            state=copy.deepcopy(self.state);proposal=copy.deepcopy(self.proposal)
            (state['legal_action_space']['request_parameters'] if location=='state' else proposal)['future_result']=history['samples'][0]['trace']
            self.unknown(self.result(state,proposal))

    def test_cli_and_strict_loader_opt_in(self):
        self.path.write_text(json.dumps(self.proposal));self.assertEqual(load_proposal(self.path),self.proposal)
        malformed=copy.deepcopy(self.proposal);malformed['proposed_current_selected_target_set']['extra']=None
        self.path.write_text(json.dumps(malformed))
        with self.assertRaises(ValueError):load_proposal(self.path)
        self.raw();cmd=[sys.executable,'-m','mtgaplayer']
        run=subprocess.run([*cmd,'watch',str(self.path),'--decision-events','--decision-state-version','5','--samples','1'],capture_output=True,text=True,timeout=20)
        self.assertEqual(run.returncode,0,run.stderr)
        consumer=DecisionConsumer()
        for line in run.stdout.splitlines():self.assertTrue(consumer.accept_event(json.loads(line)))
        self.unknown(assess_current_choice(consumer,self.proposal))
        self.assertEqual(consumer.current_view()['consumer_status'],'CLOSED')


if __name__=='__main__':unittest.main()
