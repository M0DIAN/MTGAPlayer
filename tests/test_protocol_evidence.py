"""Retained real prefix; mutations and transport clocks are synthetic."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from mtgaplayer import actions_available_gates as gates
from mtgaplayer.decision_consumer import EXECUTION
from mtgaplayer.shadow_history import _Evaluation
import test_shadow_history as history
from test_decision_state import action_message
from test_decision_advisor import PASS, PLAY


class ProtocolEvidenceTests(unittest.TestCase):
    setUp=history.ShadowHistoryTests.setUp
    run_rows=history.ShadowHistoryTests.run_rows
    simple=history.ShadowHistoryTests.simple

    def prefix(self):
        with (history.FIXTURES/'player_log_single_target.jsonl').open('rb') as source:
            return [json.loads(line) for _,line in zip(range(103),source)]

    def inspect(self, rows, **kwargs):
        observed=[];args=[];original=gates._protocol_observation
        def observe(*a):
            value=original(*a);observed.append(copy.deepcopy(value));args.append(copy.deepcopy(a));return value
        with patch.object(gates,'_protocol_observation',observe):
            r=self.run_rows(rows,actions_available_gates=True,protocol_evidence=True,**kwargs)
        return r,observed,args

    def summary(self,r):return r['actions_available_gate_analysis']['protocol_evidence']

    def test_real103_freeze_bound_bare_float_and_finite_exclusions_without_future(self):
        rows=self.prefix();before,observed,_=self.inspect(rows);o=observed[0];s=self.summary(before)
        self.assertEqual(o['request_binding']['request_id'],10100)
        self.assertEqual(o['request_binding']['game_state_id'],100)
        self.assertEqual(o['request_binding']['self_seat'],2)
        self.assertEqual(o['active_action_rows'],8);self.assertEqual(len(o['float_mana_rows']),1)
        row=o['float_mana_rows'][0];self.assertEqual(row['list_position'],7)
        self.assertTrue(row['strict_bare_literal_verified']);self.assertEqual(row['provided_fields'],['actionType'])
        self.assertEqual(row['source_reference_status'],'not_supplied')
        self.assertEqual(len(row['absent_source_fields']),5);self.assertIsNone(row['source_applicability'])
        self.assertEqual(o['reviewed_routes'],dict.fromkeys(gates.ROUTES,False))
        self.assertIsNone(o['cannot_take_action_inputs']['resolving_card_present'])
        self.assertTrue(o['general_prompt_semantics_unknown']);self.assertIsNone(o['final_route'])
        self.assertFalse(o['runtime_route_observed'])
        for v in (o,row,s):
            for flag in EXECUTION:self.assertIs(v[flag],False)
            self.assertFalse(v['complete_legality_verified'])
        later=[json.loads(line) for line in (history.FIXTURES/'player_log_single_target.jsonl').read_text().splitlines()]
        after,next_observed,_=self.inspect(later)
        self.assertEqual(next_observed[0],o);self.assertEqual(self.summary(after),s)
        self.assertEqual(before['totals']['research_preferences'],0)

    def test_duplicate_floats_are_independent_positions_with_cast_and_mana(self):
        rows=self.prefix();m=action_message(rows[-1]);m['actionsAvailableReq']['actions'].append({'actionType':'ActionType_FloatMana'})
        r,observed,_=self.inspect(rows);o=observed[0];s=self.summary(r)
        self.assertEqual([x['list_position'] for x in o['float_mana_rows']],[7,8])
        self.assertEqual(o['active_action_rows'],9)
        self.assertEqual(s['float_mana_affected_requests'],1);self.assertEqual(s['float_mana_offered_rows'],2)
        self.assertEqual(s['float_mana_strict_bare_literals'],2)
        self.assertTrue(all(x['source_applicability'] is None for x in o['float_mana_rows']))
        self.assertEqual(r['totals']['research_preferences'],0)

    def test_extra_fields_and_typed_source_literals_are_not_bare_or_borrowed(self):
        for extra in ({'instanceId':True},{'instanceId':1243},{'instanceId':1243.0},
                      {'abilityGrpId':30000},{'grpId':'private-value'},{'shouldStop':True},
                      {'manaCost':[]},{'PRIVATE_NAME':'PRIVATE_VALUE'}):
            rows=self.prefix();action_message(rows[-1])['actionsAvailableReq']['actions'][7].update(extra)
            r,observed,_=self.inspect(rows);row=observed[0]['float_mana_rows'][0];s=self.summary(r)
            self.assertFalse(row['strict_bare_literal_verified']);self.assertIsNone(row['source_applicability'])
            self.assertFalse(row['payment_legality_verified']);self.assertEqual(s['float_mana_other_observed_shapes'],1)
            self.assertEqual(s['float_mana_rows_with_explicit_source_fields'],int(bool(set(extra)&set(row['provided_source_fields']))))
            for text in ('PRIVATE_NAME','PRIVATE_VALUE','private-value'):self.assertNotIn(text,json.dumps(s))

    def test_malformed_action_type_remains_unclassified_not_interpreted_float(self):
        for value in (True,1,1.0,None,[],{}):
            rows=self.prefix();action_message(rows[-1])['actionsAvailableReq']['actions'][7]['actionType']=value
            r,observed,_=self.inspect(rows);s=self.summary(r)
            self.assertEqual(s['float_mana_strict_bare_literals'],0);self.assertEqual(s['unclassified_action_rows'],1)
            self.assertIsNone(observed[0]['reviewed_routes']['opening_hand'])

    def test_prompt_shape_parameters_and_invalid_ids_do_not_clear_policy(self):
        for prompt,verified in (({'promptId':123},True),({'promptId':1134,'parameters':[]},False),
                ({'promptId':True},False),({'promptId':1.0},False),({'promptId':0},False),
                ({'promptId':2**32},False),({'promptId':1134,'PRIVATE_NAME':'PRIVATE_VALUE'},False)):
            rows=self.prefix();action_message(rows[-1])['prompt']=prompt
            r,observed,_=self.inspect(rows);o=observed[0]
            self.assertEqual(o['prompt_structure_verified'],verified)
            self.assertIs(o['reviewed_routes']['cannot_take_action'],False) # 8 active rows, independent of prompt
            self.assertIsNone(o['final_route']);self.assertEqual(r['totals']['research_preferences'],0)
            self.assertNotIn('PRIVATE_NAME',json.dumps(o));self.assertNotIn('PRIVATE_VALUE',json.dumps(o))

    def test_synthetic_special_predicate_eligibility_is_not_actual_route(self):
        for prompt,cancel,expected in ((1134,'AllowCancel_No',True),(123,'AllowCancel_No',None),
                                       (1134,None,None),(1134,'AllowCancel_Abort',False)):
            rows=self.simple(actions=[PASS])[:-1];m=action_message(rows[-1])
            m['actionsAvailableReq']['inactiveActions']=[PLAY];m['prompt']={'promptId':prompt}
            if cancel is not None:m['allowCancel']=cancel
            r,observed,_=self.inspect(rows);o=observed[0]
            self.assertIs(o['reviewed_routes']['cannot_take_action'],expected)
            self.assertIsNone(o['cannot_take_action_inputs']['resolving_card_present'])
            self.assertIsNone(o['final_route']);self.assertFalse(o['runtime_route_observed'])
            self.assertEqual(r['totals']['research_preferences'],0)

    def test_opening_hand_presence_does_not_establish_final_route(self):
        rows=self.simple(actions=[{'actionType':'ActionType_OpeningHandAction'}])[:-1]
        r,observed,_=self.inspect(rows);self.assertTrue(observed[0]['reviewed_routes']['opening_hand'])
        self.assertIsNone(observed[0]['final_route']);self.assertEqual(r['totals']['research_preferences'],0)

    def test_wrong_binding_seat_types_ref_and_inventory_fail_closed(self):
        _,_,saved=self.inspect(self.prefix());a=saved[0]
        for mode in ('id','bool_id','float_state','seat','bool_seat','ref','binding','current','continuity','position','count'):
            changed=copy.deepcopy(a);message,request,options,decision,state,ref,rows=changed
            if mode=='id':message['msgId']+=1
            elif mode=='bool_id':message['msgId']=True
            elif mode=='float_state':message['gameStateId']=float(message['gameStateId'])
            elif mode=='seat':message['systemSeatIds']=[1]
            elif mode=='bool_seat':message['systemSeatIds']=[True]
            elif mode=='ref':ref['sequence']+=1
            elif mode=='binding':request['binding']['game']+=1
            elif mode=='current':request['current']=False
            elif mode=='continuity':request['_continuity_verified']=False
            elif mode=='position':rows[7]['list_position']=True
            else:rows.pop()
            with self.subTest(mode=mode):
                o=gates._protocol_observation(*changed)
                self.assertEqual(o['status'],'insufficient_evidence');self.assertIsNone(o['float_mana_rows'])
        # Equal numeric values with different JSON types must also be rejected.
        synthetic=self.simple()[:-1];action_message(synthetic[-1])['msgId']=1
        _,seen,saved=self.inspect(synthetic);self.assertEqual(seen[0]['request_binding']['request_id'],1)
        for value in (True,1.0):
            changed=copy.deepcopy(saved[0]);changed[0]['msgId']=value
            self.assertEqual(gates._protocol_observation(*changed)['status'],'insufficient_evidence')

    def test_missing_inventory_has_null_row_totals(self):
        rows=self.simple()[:-1];action_message(rows[-1])['actionsAvailableReq']={'actions':None}
        r,_,_=self.inspect(rows);s=self.summary(r)
        self.assertEqual(s['evidence_unavailable_requests'],1)
        self.assertIsNone(s['float_mana_offered_rows']);self.assertIsNone(s['float_mana_source_applicability_verified_rows'])
        self.assertIsNone(s['float_mana_affected_requests']);self.assertIsNone(s['unclassified_action_rows'])
        self.assertTrue(all(v=={'excluded':0,'eligible':0,'unknown':1} for v in s['reviewed_route_predicates'].values()))

    def test_retransmission_consumption_replacement_and_partial_do_not_revive_requests(self):
        rows=self.simple();retransmit=copy.deepcopy(rows[-2])
        a=self.inspect(rows)[0];b=self.inspect(rows+[retransmit])[0]
        self.assertEqual(self.summary(a),self.summary(b))
        c=self.inspect(rows[:-1]+[retransmit,rows[-1]])[0]
        self.assertEqual(self.summary(a),self.summary(c))
        partial=self.inspect(rows[:-1],tail=b'{')[0]
        self.assertFalse(partial['source']['complete'])
        wrong=self.simple()[:-1];action_message(wrong[-1])['systemSeatIds']=[2]
        self.assertEqual(self.summary(self.inspect(wrong)[0])['actions_available_requests'],0)
        cutoffs={};original=_Evaluation.apply
        def apply(e,record):
            original(e,record)
            if e.ordinal in (104,105,107,110):
                cutoffs[e.ordinal]=e.consumer.current_decision_options(include_complex_intents=True)['complex_action_intents']['intents']
        full=[json.loads(line) for line in (history.FIXTURES/'player_log_single_target.jsonl').read_text().splitlines()]
        with patch.object(_Evaluation,'apply',apply):self.inspect(full)
        self.assertEqual(cutoffs,{104:[],105:[],107:[],110:[]})

    def test_default_and_existing_optins_are_identical_without_new_report(self):
        for rows in (self.simple(),self.prefix()):
            a=self.run_rows(rows,actions_available_gates=True,complex_action_intents=True)
            b=self.inspect(rows,complex_action_intents=True)[0]
            b['actions_available_gate_analysis'].pop('protocol_evidence');a.pop('timings_ms');b.pop('timings_ms')
            self.assertEqual(a,b)

    def test_cli_optin_requires_gates_and_exports_only_aggregates(self):
        self.run_rows(self.prefix());cmd=[sys.executable,'-m','mtgaplayer','evaluate-shadow-history',str(self.path)]
        bad=subprocess.run(cmd+['--protocol-evidence'],capture_output=True,timeout=30)
        self.assertNotEqual(bad.returncode,0)
        run=subprocess.run(cmd+['--actions-available-gates','--protocol-evidence'],capture_output=True,timeout=30)
        self.assertEqual(run.returncode,0,run.stderr);r=json.loads(run.stdout);s=self.summary(r)
        self.assertEqual(s['float_mana_strict_bare_literals'],1)
        for name in ('request_binding','source_snapshot_ref','provided_fields',str(self.path)):self.assertNotIn(name,json.dumps(s))
        for flag in (1,None,'true'):
            with self.assertRaises(ValueError):self.run_rows([],actions_available_gates=True,protocol_evidence=flag)


if __name__=='__main__':unittest.main()
