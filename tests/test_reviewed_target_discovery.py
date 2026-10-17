"""Two existing real State positives; all mutations/transport are synthetic controls."""
import copy,io,json,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from mtgaplayer.choice_candidates import enumerate_known_candidates,assess_current_known_candidates,PROPOSAL_VERSION
from mtgaplayer.choice_validation import validate_proposed_choice
from mtgaplayer.decision_consumer import DecisionConsumer,EXECUTION,consume_events,_bounded_json
from mtgaplayer.decision_publisher import DecisionPublisher
from mtgaplayer.decision_advisor import assess_decision_state
from mtgaplayer.cli import replay
from test_decision_publisher import ManualClock

ROOT=Path(__file__).resolve().parents[1]
FIXTURES=ROOT/'tests/fixtures'


class ReviewedTargetDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.member=json.loads((FIXTURES/'decision_state_activate_target_member_real_v7.json').read_text())
        self.selected=json.loads((FIXTURES/'current_selected_target_set_real_v5.json').read_text())
        self.states=[self.member['before_response'],self.selected['before_submit']]
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.path=Path(tmp.name)/'source.log'

    def discover(self,state,**kwargs):return enumerate_known_candidates(state,version=3,**kwargs)
    def unknown(self,result):
        self.assertEqual(result['schema_version'],PROPOSAL_VERSION)
        self.assertEqual(result['returned_candidates'],0);self.assertEqual(result['candidates'],[])
        self.assertEqual(result['known_constraints'],'insufficient_evidence')
        self.assertTrue(all(result[k] is False for k in EXECUTION))
    def evidence(self,state):return state['legal_action_space']['request_parameters']
    def transport(self,state,history=False):
        clock=ManualClock();publisher=DecisionPublisher(clock_ns=clock,session_id='synthetic-discovery',state_version=int(state['schema_version'][-1]))
        state=copy.deepcopy(state);state['source'].update(mode='watch',phase='history' if history else 'append',stopped=False)
        document={'decision_state':state,'source':{'phase':state['source']['phase'],'partial_record':False}}
        metadata={'poll_started_ns':clock(),'poll_completed_ns':clock(),'poll_read_ns':0,
            'reducer_apply_ns':0,'decision_state_assembly_ns':0,'request_changed':True,'new_final_request':True}
        events=publisher.observe(document,metadata);consumer=DecisionConsumer(10000,500,clock)
        for event in events:self.assertTrue(consumer.accept_event(event))
        return publisher,consumer,clock,document,metadata,events

    def test_two_real_positives_produce_exact_existing_proposal_shapes(self):
        for state,fixture,kind in ((self.states[0],self.member,'target_member_probe'),(self.states[1],self.selected,'already_selected_literal_probe')):
            before=copy.deepcopy(state);r=self.discover(state)
            self.assertEqual(r['probe_kind'],kind);self.assertEqual(r['candidates'],[fixture['proposal']])
            self.assertEqual(r['request_binding'],state['binding'])
            self.assertEqual(r['known_constraints'],'verified_known_constraints')
            self.assertEqual(r['probe_coverage'],{'observed_probes':1,'examined':1,'verified':1,'unknown':0,
                'contradicted':0,'unexamined':0,'omitted_due_to_return_limit':0})
            self.assertEqual(validate_proposed_choice(state,r['candidates'][0])['known_constraints'],'verified_known_constraints')
            self.assertEqual(state,before)
            for key in ('full_action_domain_complete','global_restrictions_verified','target_domain_complete_verified',
                'target_selection_legality_verified','complete_costs_verified','complete_payment_verified','mana_payment_verified',
                'new_selectable_domain_used','target_set_enumeration_performed','historical_response_used',*EXECUTION):self.assertIs(r[key],False,key)
            self.assertIsNone(r['source_snapshot_ref'])

    def test_member_row_and_probe_denominators_and_unknown_quantity_are_separate(self):
        r=self.discover(self.states[0]);c=r['action_row_coverage']
        self.assertEqual([c[k] for k in ('engine_active_action_rows','verified_known_consistent_rows',
            'unknown_or_unreviewed_rows','contradicted_known_constraint_rows')],[17,1,16,0])
        self.assertEqual([row['list_position'] for row in c['row_statuses']],list(range(17)))
        self.assertEqual(c['row_statuses'][6]['source_ability_pair_status'],'verified_observed_pair')
        self.assertEqual(r['target_quantities'],{'minimum':None,'maximum':None,'selected_count':None,
            'basis':'not_observed_in_action_menu','quantity_rules_complete_verified':False})
        r=self.discover(self.states[1]);self.assertIsNone(r['action_row_coverage'])
        self.assertEqual([r['target_quantities'][k] for k in ('minimum','maximum','selected_count')],[1,1,1])
        self.assertFalse(r['target_quantities']['quantity_rules_complete_verified'])

    def test_v2_default_and_advisor_stay_exactly_unchanged(self):
        for state,reason in zip(self.states,('target_member_proposal_required','complete_current_select_domain_not_observed')):
            default=enumerate_known_candidates(state)
            self.assertEqual(default,enumerate_known_candidates(state,version=2))
            self.assertEqual(default['reason'],reason)
            advice=assess_decision_state(state)
            self.discover(state)
            self.assertEqual(assess_decision_state(state),advice)
            self.assertEqual(advice['assessment_status'],'abstain')

    def test_unsupported_pairs_remain_unknown_and_explicit_contradictions_are_scoped(self):
        for value in (None,'insufficient_evidence','observed_group_contradiction'):
            state=copy.deepcopy(self.states[0]);self.evidence(state)['rows'][6]['ability_binding']=value
            r=self.discover(state);self.unknown(r)
            self.assertEqual(r['action_row_coverage']['engine_active_action_rows'],17)
            if value=='observed_group_contradiction':
                self.assertEqual(r['action_row_coverage']['contradicted_known_constraint_rows'],1)
                self.assertEqual(r['probe_coverage']['contradicted'],1)
            else:self.assertEqual(r['action_row_coverage']['unknown_or_unreviewed_rows'],17)
        state=copy.deepcopy(self.states[0]);self.evidence(state)['rows'][6]['target_menu']=None
        r=self.discover(state);self.unknown(r);self.assertEqual(r['probe_coverage']['observed_probes'],0)

    def test_wrong_slot_member_source_ability_and_duplicate_public_reference_fail_closed(self):
        for mutate in (
            lambda s:self.evidence(s)['rows'][6]['target_menu'].update(target_idx=999),
            lambda s:self.evidence(s)['rows'][6]['target_menu']['offered_visible_target_refs'].append(999),
            lambda s:self.evidence(s)['rows'][6]['identifier_refs'].update(instanceId=999),
            lambda s:self.evidence(s)['rows'][6]['identifier_refs'].update(uniqueAbilityId=999),
            lambda s:s['visible_objects'].append(copy.deepcopy(s['visible_objects'][0])),
            lambda s:self.evidence(s)['public_battlefield_refs'].append(self.evidence(s)['public_battlefield_refs'][0]),
            lambda s:self.evidence(s)['rows'][6]['target_menu'].update(source_visible_object_ref=True),
        ):
            state=copy.deepcopy(self.states[0]);mutate(state);self.unknown(self.discover(state))
        for state in self.states:
            for key in ('request_id','game_state_id','source_generation','self_seat','match'):
                altered=copy.deepcopy(state);v=altered['binding'][key]
                altered['binding'][key]='wrong' if isinstance(v,str) else v+1
                self.unknown(self.discover(altered))

    def test_selected_unknown_quantity_select_entries_and_hidden_reference_never_enumerate(self):
        for key in ('min_targets','max_targets','selected_count'):
            for value in (None,0,2,True):
                state=copy.deepcopy(self.states[1]);self.evidence(state)['targets'][key]=value
                self.unknown(self.discover(state))
        for mode in ('select','duplicate','hidden','extra','not_ability'):
            state=copy.deepcopy(self.states[1]);t=self.evidence(state)['targets']
            if mode=='select':t['entries'][0]['legal_action']='SelectAction_Select'
            elif mode=='duplicate':t['entries'].append(copy.deepcopy(t['entries'][0]))
            elif mode=='hidden':state['visible_objects']=[o for o in state['visible_objects'] if o['instance_id']!=t['entries'][0]['object_ref']]
            elif mode=='extra':t['future_result']='PRIVATE_SENTINEL'
            else:next(o for o in state['game']['stack']['members'] if o['instance_id']==t['source_object_ref'])['object_type']='GameObjectType_Card'
            r=self.discover(state);self.unknown(r);self.assertNotIn('PRIVATE_SENTINEL',json.dumps(r))

    def expanded_member(self):
        state=copy.deepcopy(self.states[0]);menu=self.evidence(state)['rows'][6]['target_menu']
        extra=next(ref for ref in self.evidence(state)['public_battlefield_refs'] if ref not in menu['offered_visible_target_refs'])
        menu['offered_visible_target_refs'].append(extra);menu['offered_visible_target_count']+=1
        node=next(n for n in state['legal_action_space']['choice_graph']['action_nodes'] if n['action_key']['list_position']==6)
        next(c for c in node['constraints'] if c['parameter_category']=='targets')['observed_quantity_or_domain']['groups'][0]['target_count']+=1
        return state

    def test_return_limit_and_probe_budget_report_exact_different_counts(self):
        state=self.expanded_member();r=self.discover(state,limit=1)
        self.assertEqual(r['returned_candidates'],1);self.assertEqual(r['candidate_total_for_reviewed_constraints'],2)
        self.assertEqual(r['probe_coverage']['verified'],2);self.assertEqual(r['probe_coverage']['omitted_due_to_return_limit'],1)
        self.assertEqual(r['action_row_coverage']['verified_known_consistent_rows'],1);self.assertTrue(r['truncated'])
        with patch('mtgaplayer.choice_candidates.MAX_TARGET_PROBES',1):r=self.discover(state)
        self.assertEqual(r['probe_coverage']['unexamined'],1);self.assertIsNone(r['candidate_total_for_reviewed_constraints'])
        self.assertFalse(r['exhaustive_for_reviewed_constraints']);self.assertTrue(r['truncated'])
        self.assertLess(len(json.dumps(r).encode()),128*1024)
        # Synthetic coherent 5x64 menu: exercise the actual 256 budget and 64
        # return cap, including a whole unexamined row, without mocking limits.
        state=copy.deepcopy(self.states[0]);space=state['legal_action_space'];evidence=self.evidence(state)
        row=evidence['rows'][6];menu=row['target_menu']
        template=space['immediate_frontier']['projection']['templates'][6]
        node=next(n for n in space['choice_graph']['action_nodes'] if n['action_key']['list_position']==6)
        original=next(o for o in state['visible_objects'] if o['instance_id']==menu['offered_visible_target_refs'][0])
        refs=[original['instance_id']]
        for index in range(63):
            obj=copy.deepcopy(original);obj['instance_id']=200000+index
            state['visible_objects'].append(obj);evidence['public_battlefield_refs'].append(obj['instance_id']);refs.append(obj['instance_id'])
        menu.update(offered_visible_target_refs=refs,offered_visible_target_count=64)
        next(c for c in node['constraints'] if c['parameter_category']=='targets')['observed_quantity_or_domain']['groups'][0]['target_count']=64
        for index in range(4):
            position=len(evidence['rows']);added=copy.deepcopy(row)
            added['list_position']=added['target_menu']['list_position']=position
            added['identifier_refs']['uniqueAbilityId']=300000+index;evidence['rows'].append(added)
            frontier=copy.deepcopy(template);frontier['list_position']=frontier['action_key']['list_position']=position
            space['immediate_frontier']['projection']['templates'].append(frontier)
            graph=copy.deepcopy(node);graph['action_key']['list_position']=position
            graph['action_identity']['raw_identifiers']['unique_ability_id']=300000+index
            for constraint in graph['constraints']:constraint['action_key']['list_position']=position
            space['choice_graph']['action_nodes'].append(graph)
        space['immediate_frontier']['projection']['engine_active_action_count']=len(evidence['rows'])
        r=self.discover(state)
        self.assertEqual(r['probe_coverage'],{'observed_probes':320,'examined':256,'verified':256,'unknown':0,
            'contradicted':0,'unexamined':64,'omitted_due_to_return_limit':192})
        self.assertEqual(r['returned_candidates'],64);self.assertIsNone(r['candidate_total_for_reviewed_constraints'])
        self.assertTrue(r['truncated']);self.assertFalse(r['exhaustive_for_reviewed_constraints'])
        self.assertEqual(r['action_row_coverage']['row_statuses'][-1]['known_constraints'],'insufficient_evidence')

    def test_cross_profile_status_mixing_and_future_suffix_are_not_discovery_inputs(self):
        for state in self.states:
            for change in ('profile','status','future'):
                altered=copy.deepcopy(state)
                if change=='profile':self.evidence(altered)['profile']='reviewed_literal_mana_slice'
                elif change=='status':altered['status']='state_observed_without_request'
                else:self.evidence(altered)['historical_suffix']='PRIVATE_SENTINEL'
                r=self.discover(altered);self.unknown(r);self.assertNotIn('PRIVATE_SENTINEL',json.dumps(r))
        self.unknown(self.discover(self.member['after_response']))
        self.unknown(self.discover(self.selected['after_submit']))

    def test_validator_contract_drift_and_oversized_result_return_no_partial_proposals(self):
        from mtgaplayer import choice_validation
        original=choice_validation.validate_proposed_choice
        for state in self.states:
            for key,value in (('response_encoding_verified',True),('schema_version','unknown'),
                ('validation_scope','unreviewed_scope'),('complete_costs_verified',1),
                ('target_domain_complete_verified','true'),('all_payment_options_verified',None)):
                def elevated(*args,**kwargs):
                    r=original(*args,**kwargs);r[key]=value;return r
                with patch.object(choice_validation,'validate_proposed_choice',side_effect=elevated):
                    r=self.discover(state);self.unknown(r)
                    self.assertEqual(r['reason'],'choice_validator_contract_mismatch')
            def missing(*args,**kwargs):
                r=original(*args,**kwargs);del r['complete_payment_verified'];return r
            with patch.object(choice_validation,'validate_proposed_choice',side_effect=missing):self.unknown(self.discover(state))
        original_bound=_bounded_json
        def limited(value):
            original_bound(value)
            if isinstance(value,dict) and value.get('schema_version')==PROPOSAL_VERSION:raise ValueError('synthetic_output_limit')
        with patch('mtgaplayer.choice_candidates._bounded_json',side_effect=limited):self.unknown(self.discover(self.states[0]))
        with patch.object(choice_validation,'validate_proposed_choice',return_value=None):self.unknown(self.discover(self.states[0]))

    def test_live_history_stop_expiry_and_calculation_recheck(self):
        for state in self.states:
            _,consumer,_,_,_,_=self.transport(state,history=True);self.unknown(assess_current_known_candidates(consumer,version=3))
            publisher,consumer,clock,_,_,_=self.transport(state)
            result=assess_current_known_candidates(consumer,version=3)
            self.assertEqual(result['returned_candidates'],1)
            self.assertEqual(result['candidates'][0]['source_snapshot_ref'],result['source_snapshot_ref'])
            clock.advance(501);self.unknown(assess_current_known_candidates(consumer,version=3))
            publisher,consumer,clock,_,_,_=self.transport(state)
            for event in publisher.stop():self.assertTrue(consumer.accept_event(event))
            self.unknown(assess_current_known_candidates(consumer,version=3))
        from mtgaplayer import choice_candidates as candidates
        original=candidates.enumerate_known_candidates
        _,consumer,clock,_,_,_=self.transport(self.states[0])
        def slow(*args,**kwargs):
            result=original(*args,**kwargs);clock.advance(501);return result
        with patch.object(candidates,'enumerate_known_candidates',side_effect=slow):
            r=assess_current_known_candidates(consumer,version=3);self.unknown(r)
            self.assertEqual(r['reason'],'current_snapshot_expired_or_changed')

    def test_live_consumption_replacement_partial_gap_and_wrong_session_revoke_old(self):
        for before,after in ((self.states[0],self.member['after_response']),(self.states[1],self.selected['after_submit'])):
            for mode in ('consumed','replacement','partial','gap','session'):
                publisher,consumer,clock,doc,meta,_=self.transport(before)
                old=assess_current_known_candidates(consumer,version=3)['candidates'][0]
                if mode=='session':
                    event=copy.deepcopy(publisher.observe(doc,meta)[-1]);event['session_id']='different'
                    self.assertFalse(consumer.accept_event(event));self.unknown(assess_current_known_candidates(consumer,version=3));continue
                if mode=='consumed':
                    state=copy.deepcopy(after);state['source'].update(mode='watch',phase='append',stopped=False)
                    doc['decision_state']=state;meta=dict(meta,request_consumed=True,new_final_request=False)
                elif mode=='replacement':
                    def replace(value):
                        if isinstance(value,dict):
                            return {k:(v+1 if k=='request_id' and type(v) is int else replace(v)) for k,v in value.items()}
                        if isinstance(value,list):return [replace(v) for v in value]
                        return value
                    doc['decision_state']=replace(doc['decision_state'])
                    meta=dict(meta,new_final_request=False)
                else:
                    doc={'decision_state':None,'current':{},'source':{'phase':'append','partial_record':mode=='partial'}}
                    meta=dict(meta,continuity_error=mode=='gap',new_final_request=False)
                for event in publisher.observe(doc,meta):self.assertTrue(consumer.accept_event(event))
                self.unknown(assess_current_known_candidates(consumer,version=3))
                current=consumer.current_view()['decision_state']
                if current is not None:self.assertEqual(validate_proposed_choice(current,old)['known_constraints'],'insufficient_evidence')

    def test_consumer_sidecar_recheck_keeps_v3_on_expiration(self):
        from mtgaplayer import choice_candidates as candidates
        publisher,_,clock,_,_,events=self.transport(self.states[0]);events+=publisher.stop()
        consumer=DecisionConsumer(10000,500,clock);seen=[];output=[];advanced=False
        original=candidates.assess_current_known_candidates
        def slow(c,*,version=2):
            nonlocal advanced
            seen.append(version);r=original(c,version=version)
            if r['returned_candidates'] and not advanced:clock.advance(501);advanced=True
            return r
        with patch.object(candidates,'assess_current_known_candidates',side_effect=slow):
            consume_events(io.StringIO(''.join(json.dumps(e)+'\n' for e in events)),output.append,consumer,
                known_choice_candidates=True,known_choice_candidates_version=3)
        self.assertGreaterEqual(len(seen),2);self.assertEqual(set(seen),{3})
        self.assertTrue(output)
        for row in output:self.assertEqual(row['known_choice_candidates']['schema_version'],PROPOSAL_VERSION)
        self.assertEqual(output[-1]['known_choice_candidates']['returned_candidates'],0)

    def test_explicit_selector_validation_and_cli_discovery_without_proposal_file(self):
        for invalid in (1,6,True,3.0,'3'):
            with self.assertRaises(ValueError):enumerate_known_candidates(self.states[0],version=invalid)
        for limit in (0,65,True):
            with self.assertRaises(ValueError):self.discover(self.states[0],limit=limit)
        with self.assertRaises(ValueError):replay(self.path,known_choice_candidates_version=3)
        with self.assertRaises(ValueError):consume_events(io.StringIO(''),lambda x:None,known_choice_candidates_version=3)
        publisher,_,_,_,_,events=self.transport(self.states[1]);events+=publisher.stop()
        cmd=[sys.executable,'-m','mtgaplayer','consume-events','--known-choice-candidates','--known-choice-candidates-version','3']
        run=subprocess.run(cmd,input=''.join(json.dumps(e)+'\n' for e in events),capture_output=True,text=True,timeout=20)
        self.assertEqual(run.returncode,0,run.stderr)
        diagnostics=[json.loads(line) for line in run.stdout.splitlines()]
        self.assertTrue(all(row['known_choice_candidates']['schema_version']==PROPOSAL_VERSION for row in diagnostics))
        self.assertEqual(diagnostics[-1]['known_choice_candidates']['returned_candidates'],0)
        # Existing raw excerpt is only CLI wiring coverage, not a third MP55 real positive.
        rows=(FIXTURES/'player_log_activate_generic_two.jsonl').read_text().splitlines();self.path.write_text('\n'.join(rows[:5])+'\n')
        run=subprocess.run([sys.executable,'-m','mtgaplayer','replay',str(self.path),'--format','player-log',
            '--decision-state-version','7','--known-choice-candidates','--known-choice-candidates-version','3'],capture_output=True,text=True,timeout=20)
        self.assertEqual(run.returncode,0,run.stderr)
        self.assertEqual(json.loads(run.stdout)['known_choice_candidates']['schema_version'],PROPOSAL_VERSION)


if __name__=='__main__':unittest.main()
