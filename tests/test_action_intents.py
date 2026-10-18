"""Existing real evidence; mutations, clocks and transports are synthetic."""
import copy
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from mtgaplayer import action_intents as intents, decision_options
from mtgaplayer.cli import watch_decision_events
from mtgaplayer.decision_consumer import DecisionConsumer, EXECUTION, consume_events
from mtgaplayer.shadow_history import evaluate_shadow_history
import test_decision_options as helpers
import test_multi_slot_cast as multi_helpers
from test_decision_publisher import ManualClock, poll_events

FIXTURES = Path(__file__).parent/'fixtures'


class ActionIntentTests(unittest.TestCase):
    def setUp(self):
        # Fetch only the genuine parent prefix before any successor is opened.
        self.multi = multi_helpers.MultiSlotCastTests()
        self.multi.setUp(); self.addCleanup(self.multi.doCleanups)
        self.parent = self.multi.document()['decision_state']
        self.helper = helpers.DecisionOptionsTests()

    def current(self, state=None, **kwargs):
        return self.helper.transport(state or self.parent, **kwargs)

    def report(self, state=None):
        c,*_ = self.current(state)
        return c, c.current_decision_options(include_complex_intents=True)

    def safe(self, report):
        view = report['complex_action_intents']
        self.assertIsNone(view['coverage']['full_legal_complex_actions'])
        for item in (view, *view['intents']):
            for flag in (*EXECUTION, 'complete_legality_verified'):
                self.assertIs(item[flag], False, flag)
            self.assertTrue(item['read_only'])
        for item in view['intents']:
            self.assertEqual(item['request_binding'], report['request_binding'])
            self.assertEqual(item['source_snapshot_ref'], report['source_snapshot_ref'])
            for flag in ('complete_action_proposal_verified','target_combination_legality_verified',
                         'payment_legality_verified','response_encoding_verified','execution_ready'):
                self.assertIs(item[flag],False,flag)

    def test_real_prefix103_keeps_positions_slots_and_shared_predictive_route_separate(self):
        c,r = self.report(); self.safe(r)
        rows = {i['list_position']:i for i in r['complex_action_intents']['intents']}
        self.assertEqual(list(rows),[0,1,2,3,4])
        self.assertEqual(r['complex_action_intents']['coverage']['finite_stage_intent_rows'],2)
        a,b = rows[1],rows[3]
        self.assertEqual(len(a['reviewed_target_members']),4)
        self.assertEqual(a['predictive_payment_witnesses'],b['predictive_payment_witnesses'])
        self.assertNotEqual(a['action_key'],b['action_key'])
        self.assertEqual(b['predictive_payment_witnesses'][0]['list_position'],5)
        self.assertIsNone(b['predictive_payment_witnesses'][0]['current_tapped_literal'])
        self.assertEqual(b['observed_mana_cost'],[{'color':['ManaColor_Blue'],'count':1}])
        self.assertEqual(rows[2]['target_slots'],[
            {'slot_position':0,'target_idx':2,'provided_object_refs':[1243],'minimum':None,'maximum':None,'selected_count':None},
            {'slot_position':1,'target_idx':1,'provided_object_refs':[1243],'minimum':None,'maximum':None,'selected_count':None}])
        self.assertFalse(rows[2]['finite_stage_intent_structure_verified'])
        self.assertFalse(rows[2]['auto_tap_solution_observed'])
        self.assertEqual(rows[2]['predictive_payment_witnesses'],[])
        self.assertTrue(all(i['successor_stage_status']=='unknown_not_yet_observed' for i in rows.values()))
        self.assertEqual(c.shadow_decision()['status'],'abstain')

    def test_real_activate_parent_joins_original_row_two_sources_without_untap_inference(self):
        state=json.loads((FIXTURES/'activate_target_payment_real_v9.json').read_text())['before_response']
        c,r=self.report(state);self.safe(r)
        item=next(i for i in r['complex_action_intents']['intents'] if i['list_position']==6)
        self.assertEqual(item['action_type'],'ActionType_Activate')
        self.assertTrue(item['finite_stage_intent_structure_verified'])
        self.assertEqual([w['list_position'] for w in item['predictive_payment_witnesses']],[12,14])
        self.assertTrue(all(w['current_tapped_literal'] is None for w in item['predictive_payment_witnesses']))
        self.assertEqual(len(item['reviewed_target_members']),1)
        self.assertEqual(c.shadow_decision()['status'],'abstain')

    def test_equip_portable_stages_use_own_proposals_and_noncurrent_parent(self):
        states=json.loads((FIXTURES/'current_target_revision_real_v14.json').read_text())
        for name,state in states.items():
            c,r=self.report(state);self.safe(r);items=r['complex_action_intents']['intents']
            if name.endswith('consumed'):
                self.assertEqual(items,[])
            elif name in ('first_child','revised_child'):
                self.assertEqual(len(items),1);item=items[0]
                self.assertFalse(item['historical_parent']['current'])
                self.assertEqual(item['historical_parent']['list_position'],6)
                self.assertNotEqual(item['historical_parent']['binding'],r['request_binding'])
                kind='final_target_set' if name=='first_child' else 'current_selected_literal_probe'
                self.assertEqual(item['current_proposals'][0]['kind'],kind)
                if name=='revised_child':
                    self.assertEqual(item['target_constraints']['selected_count'],1)
                    self.assertFalse(item['complete_action_proposal_verified'])

    def test_cast_watch_chain_revokes_consumed_parent_and_never_borrows_revised_domain(self):
        # Parent proof is already frozen by setUp; only now read successors.
        lines=(FIXTURES/'player_log_single_target.jsonl').read_bytes().splitlines(keepends=True)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'source';path.write_bytes(b''.join(lines[:102]))
            clock=ManualClock();stream=watch_decision_events(path,interval=0,samples=9,
                decision_state_version=15,current_multi_slot_cast=True,clock_ns=clock,session_id='synthetic-intents')
            self.addCleanup(stream.close);c=DecisionConsumer(10000,10000,clock)
            for e in poll_events(stream):self.assertTrue(c.accept_event(e))
            previous=102;parent=None
            for cutoff in (103,104,105,106,107,109,110):
                with path.open('ab') as out:out.write(b''.join(lines[previous:cutoff]))
                previous=cutoff
                for e in poll_events(stream):self.assertTrue(c.accept_event(e))
                r=c.current_decision_options(include_complex_intents=True);self.safe(r)
                items=r['complex_action_intents']['intents']
                if cutoff==103:parent=copy.deepcopy(items)
                elif cutoff==106:
                    self.assertEqual(len(items),1)
                    self.assertEqual(items[0]['historical_parent']['list_position'],3)
                    self.assertFalse(items[0]['historical_parent']['current'])
                    self.assertEqual(len(items[0]['current_proposals']),4)
                    self.assertEqual(items[0]['target_constraints']['min_targets'],1)
                else:self.assertEqual(items,[])
            self.assertTrue(all(i['successor_stage_status']=='unknown_not_yet_observed' for i in parent))
            self.assertIsNone(parent[3]['target_slots'][0]['minimum'])

    def test_default_cache_and_policy_unchanged_optin_does_not_generate_again(self):
        c,*_=self.current()
        with patch.object(decision_options,'enumerate_known_candidates',wraps=decision_options.enumerate_known_candidates) as generate:
            plain=c.current_decision_options();policy=c.shadow_decision()
            enriched=c.current_decision_options(include_complex_intents=True)
            payload=copy.deepcopy(enriched);payload.pop('complex_action_intents')
            self.assertEqual(plain,payload);self.assertEqual(c.shadow_decision(),policy)
            enriched['complex_action_intents']['intents'][1]['predictive_payment_witnesses'][0]['list_position']=99
            again=c.current_decision_options(include_complex_intents=True)
            self.assertEqual(again['complex_action_intents']['intents'][1]['predictive_payment_witnesses'][0]['list_position'],5)
            self.assertEqual(generate.call_count,1)

    def test_incomplete_budget_cannot_regain_evidence_from_retained_probes(self):
        c,*_=self.current();r=c.current_decision_options(limit=2,include_complex_intents=True);self.safe(r)
        self.assertTrue(r['coverage']['truncated'])
        self.assertEqual(r['complex_action_intents']['coverage']['observed_complex_action_rows'],5)
        self.assertGreater(r['complex_action_intents']['coverage']['omitted_parent_rows'],0)
        self.assertFalse(any(i['finite_stage_intent_structure_verified'] for i in r['complex_action_intents']['intents']))

    def test_foreign_probe_key_target_identity_and_payment_cannot_be_joined(self):
        c,*_=self.current();base=c.current_decision_options();state=c.current_view()['decision_state']
        original=c._decision_options_cache[2]
        for mutation in ('position','bool_position','source','member','mana_source','mana_ability','predictive'):
            retained=copy.deepcopy(original);item=retained[0]
            if mutation=='position':item['action_key']['list_position']=3
            elif mutation=='bool_position':item['action_key']['list_position']=True
            elif mutation=='source':item['proposal']['proposed_cast_target_member']['identifier_refs']['instanceId']=1255
            elif mutation=='member':item['proposal']['proposed_cast_target_member']['object_ref']=999999
            elif mutation=='mana_source':item['payment_witness']['identifier_refs']['instanceId']=999999
            elif mutation=='mana_ability':item['payment_witness']['identifier_refs']['abilityGrpId']=999999
            else:item['payment_witness']['predictive_payment']['instanceId']=999999
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):intents.assemble(state,base,retained)

    def test_activate_foreign_relation_or_swapped_payment_sources_rejected(self):
        state=json.loads((FIXTURES/'activate_target_payment_real_v9.json').read_text())['before_response']
        c,*_=self.current(state);base=c.current_decision_options();state=c.current_view()['decision_state']
        for mutation in ('source','slot','swap'):
            changed=copy.deepcopy(base);relation=next(o for o in changed['options'] if o['kind']=='activate_target_payment_association')['observation']
            if mutation=='source':relation['action_identifier_refs']['instanceId']=999999
            elif mutation=='slot':relation['target_member']['target_idx']+=1
            else:relation['mana_row_witnesses'].reverse()
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):intents.assemble(state,changed,[])

    def test_expiry_stop_and_close_during_assembly_withhold_result(self):
        original=intents.assemble
        for revoke in ('expire','stop','close'):
            c,pub,clock,_=self.current()
            def during(*args):
                value=original(*args)
                if revoke=='expire':clock.advance(600)
                elif revoke=='close':c.close()
                else:
                    for event in pub.stop():self.assertTrue(c.accept_event(event))
                return value
            with patch.object(intents,'assemble',during):r=c.current_decision_options(include_complex_intents=True)
            self.assertEqual(r['complex_action_intents']['intents'],[])
            self.assertEqual(r['options'],[]);self.assertIsNone(c._decision_options_cache)

    def test_history_and_wrong_seat_never_expose_old_intents(self):
        c,*_=self.current(history=True)
        self.assertEqual(c.current_decision_options(include_complex_intents=True)['complex_action_intents']['intents'],[])
        s=copy.deepcopy(self.parent);s['binding']['self_seat']=1
        # The existing Publisher rejects this identity before any Consumer view.
        with self.assertRaises(ValueError):self.current(s)

    def test_partial_response_revokes_parent_and_cannot_repair_lineage_from_future(self):
        lines=(FIXTURES/'player_log_single_target.jsonl').read_bytes().splitlines(keepends=True)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'source';path.write_bytes(b''.join(lines[:102]))
            clock=ManualClock();stream=watch_decision_events(path,interval=0,samples=4,
                decision_state_version=15,clock_ns=clock,session_id='synthetic-partial-intent')
            self.addCleanup(stream.close);c=DecisionConsumer(10000,10000,clock)
            def poll():
                for e in poll_events(stream):self.assertTrue(c.accept_event(e))
                return c.current_decision_options(include_complex_intents=True)['complex_action_intents']['intents']
            self.assertEqual(poll(),[])
            with path.open('ab') as out:out.write(lines[102])
            self.assertTrue(poll())
            half=len(lines[103])//2
            with path.open('ab') as out:out.write(lines[103][:half])
            self.assertEqual(poll(),[])
            with path.open('ab') as out:out.write(lines[103][half:]+b''.join(lines[104:106]))
            self.assertEqual(poll(),[])

    def test_history_optin_preserves_default_results_and_request_row_denominators(self):
        prefix=[]
        with (FIXTURES/'player_log_single_target.jsonl').open('rb') as source:
            prefix=[line for _,line in zip(range(103),source)]
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'private-name';path.write_bytes(b''.join(prefix))
            a=evaluate_shadow_history(path);frozen=[]
            b=evaluate_shadow_history(path,complex_action_intents=True,_on_freeze=lambda *args:frozen.append(args))
            for key in a:
                if key not in ('timings_ms',):self.assertEqual(a[key],b[key],key)
            counts=b['complex_action_intent_coverage']
            self.assertEqual(counts['observed_complex_action_rows'],5)
            self.assertEqual(counts['reviewed_target_rows'],2)
            self.assertEqual(counts['finite_stage_intent_rows'],2)
            self.assertIsNone(counts['full_legal_complex_actions'])
            self.assertEqual(frozen[0][0],103);self.assertEqual(frozen[0][3]['status'],'abstain')
            self.assertNotIn(str(path),json.dumps(b))

    def test_optional_assembly_failure_cannot_rewrite_historical_policy_statistics(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'prefix';path.write_bytes(b''.join(self.multi.lines))
            original=evaluate_shadow_history(path)
            with patch.object(intents,'assemble',side_effect=ValueError('synthetic-output-failure')):
                failed=evaluate_shadow_history(path,complex_action_intents=True)
            for key in original:
                if key not in ('timings_ms',):self.assertEqual(original[key],failed[key],key)
            self.assertEqual(failed['complex_action_intent_coverage']['observed_complex_action_rows'],5)
            self.assertEqual(failed['complex_action_intent_coverage']['intent_evidence_unavailable_requests'],1)
            self.assertEqual(failed['complex_action_intent_coverage']['finite_stage_intent_rows'],0)

    def test_cli_requires_explicit_current_options_and_preserves_policy(self):
        c,pub,_,events=self.current();data=''.join(json.dumps(e)+'\n' for e in events+pub.stop()).encode()
        for enabled in (False,True):
            args=[sys.executable,'-m','mtgaplayer','consume-events','--current-decision-options','--shadow-decision']
            if enabled:args.append('--complex-action-intents')
            run=subprocess.run(args,input=data,capture_output=True,timeout=30)
            self.assertEqual(run.returncode,0,run.stderr)
            rows=[json.loads(line) for line in run.stdout.splitlines()]
            self.assertTrue(all(('complex_action_intents' in r['current_decision_options'])==enabled for r in rows))
        with self.assertRaises(ValueError):consume_events(io.BytesIO(data),lambda x:None,c,complex_action_intents=True)
        for invalid in (1,None,'true'):
            with self.assertRaises(ValueError):c.current_decision_options(include_complex_intents=invalid)


if __name__=='__main__':unittest.main()
