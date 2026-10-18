"""Existing scrubbed real chains; synthetic transport/clocks/negative controls."""
import copy
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from mtgaplayer import decision_options as options
from mtgaplayer.cli import replay, watch_decision_events
from mtgaplayer.decision_consumer import DecisionConsumer, EXECUTION, consume_events
from mtgaplayer.decision_publisher import DecisionPublisher
import test_cast_continuation as cast_helpers
import test_decision_advisor as advisor_helpers
from test_decision_input import rows as selectn_rows
from test_combat_frontier import baseline, request, ATTACK, BLOCK
from test_decision_publisher import ManualClock, poll_events

FIXTURES = Path(__file__).parent/'fixtures'


class DecisionOptionsTests(unittest.TestCase):
    def setUp(self):
        self.cast = cast_helpers.CastContinuationTests('test_retained_source_fingerprints_parent_freeze_then_first_child')
        self.cast.setUp(); self.addCleanup(self.cast.doCleanups)

    def transport(self, state, history=False):
        state = copy.deepcopy(state); state['source'].update(mode='watch',phase='history' if history else 'append',stopped=False)
        clock = ManualClock(); pub = DecisionPublisher(clock_ns=clock,session_id='synthetic-options',
            state_version=int(state['schema_version'].rsplit('v',1)[1]))
        meta = {'poll_started_ns':clock(),'poll_completed_ns':clock(),'poll_read_ns':0,'reducer_apply_ns':0,
            'decision_state_assembly_ns':0,'request_changed':True,'new_final_request':True}
        events = pub.observe({'decision_state':state,'source':{'phase':state['source']['phase'],'partial_record':False}},meta)
        consumer = DecisionConsumer(10000,500,clock)
        for event in events:self.assertTrue(consumer.accept_event(event))
        return consumer,pub,clock,events

    def safe(self, report):
        self.assertEqual(report['schema_version'],options.VERSION)
        self.assertIsNone(report['coverage']['unknown_count'])
        for value in [report,*report['options']]:
            self.assertTrue(value['read_only'])
            for name in EXECUTION:self.assertIs(value[name],False,name)
        for option in report['options']:
            self.assertEqual(option['request_binding'],report['request_binding'])
            self.assertEqual(option['source_snapshot_ref'],report['source_snapshot_ref'])

    def test_cast_actual_watch_chain_preserves_parent_denominator_and_child_scope(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'existing.jsonl';path.write_bytes(b''.join(self.cast.lines[:102]))
            clock=ManualClock();stream=watch_decision_events(path,interval=0,samples=9,
                decision_state_version=15,clock_ns=clock,session_id='real-format-options')
            self.addCleanup(stream.close);consumer=DecisionConsumer(10000,10000,clock)
            for event in poll_events(stream):self.assertTrue(consumer.accept_event(event))
            self.assertEqual(consumer.current_decision_options()['options'],[])
            previous=102;child_ref=None
            for cutoff in (103,104,105,106,107,109,110):
                with path.open('ab') as out:out.write(b''.join(self.cast.lines[previous:cutoff]))
                previous=cutoff
                for event in poll_events(stream):self.assertTrue(consumer.accept_event(event))
                report=consumer.current_decision_options();self.safe(report)
                if cutoff==103:
                    self.assertEqual(report['coverage']['engine_offered_count'],8)
                    rows=[o for o in report['options'] if o['kind']=='engine_action']
                    probes=[o for o in report['options'] if o['kind']=='parent_cast_member_probe']
                    self.assertEqual([o['list_position'] for o in rows],list(range(8)))
                    self.assertEqual(len(probes),8)
                    self.assertEqual(len({o['list_position'] for o in probes}),2)
                elif cutoff==106:
                    self.assertEqual(len(report['options']),4)
                    self.assertTrue(all(o['kind']=='final_target_set' and o['evidence_level']=='known_constraints_verified' for o in report['options']))
                    self.assertEqual(report['continuation_context']['field'],'cast_choice_continuation')
                    self.assertEqual(report['request_binding']['request_id'],10102);child_ref=report['source_snapshot_ref']
                elif cutoff==109:
                    self.assertEqual(report['request_binding']['request_id'],10104)
                    self.assertNotEqual(report['source_snapshot_ref'],child_ref)
                    self.assertEqual(report['request_observation']['target_literals']['selected_count'],1)
                    self.assertEqual(report['options'],[])
                    self.assertEqual(report['coverage']['sources'][-1]['coverage']['probe_coverage']['unknown'],1)
                else:self.assertEqual(report['options'],[])
            for event in poll_events(stream):self.assertTrue(consumer.accept_event(event))
            self.assertEqual(consumer.current_decision_options()['options'],[])

    def test_equip_portable_stages_keep_own_selected_literal_and_parent_history(self):
        states=json.loads((FIXTURES/'current_target_revision_real_v14.json').read_text(encoding='utf8'))
        for name,state in states.items():
            with self.subTest(name=name):
                consumer,_,_,_=self.transport(state);report=consumer.current_decision_options();self.safe(report)
                if name=='before_parent':self.assertEqual(report['coverage']['engine_offered_count'],17)
                elif name in ('first_child','revised_child'):
                    self.assertEqual(len(report['options']),1)
                    expected='final_target_set' if name=='first_child' else 'current_selected_literal_probe'
                    self.assertEqual(report['options'][0]['kind'],expected)
                    self.assertEqual(report['continuation_context']['current_request_binding'],state['binding'])
                    self.assertFalse(report['continuation_context']['historical_parent_current'])
                    if name=='revised_child':
                        self.assertEqual(report['options'][0]['proposal']['proposed_current_selected_target_set']['object_refs'],[10024])
                        self.assertEqual(report['request_observation']['target_literals']['selected_count'],1)
                elif state['binding']['request_id'] is None:self.assertEqual(report['options'],[])
                else:
                    self.assertTrue(all(o['request_binding']==state['binding'] for o in report['options']))
                    self.assertIsNone(report['continuation_context'])

    def test_selectn_discard_and_combat_keep_distinct_unknown_combination_domains(self):
        helper=advisor_helpers.DecisionAdvisorTests('test_select_n_reports_options_and_unknown_minimum')
        helper.setUp();self.addCleanup(helper.doCleanups)
        c=helper.current(rows=selectn_rows());r=c.current_decision_options();self.safe(r)
        self.assertEqual(r['coverage']['engine_offered_count'],4)
        self.assertEqual([o['observation']['offered_instance_id'] for o in r['options']],[175,176,178,179])
        self.assertTrue(all(o['evidence_level']=='engine_offered' for o in r['options']))
        for typ in (ATTACK,BLOCK):
            c=helper.current(rows=baseline()+[request(typ)]);r=c.current_decision_options();self.safe(r)
            self.assertEqual(r['coverage']['engine_offered_count'],1)
            self.assertEqual(r['options'][0]['observation']['candidate_instance_id'],701)
            self.assertEqual(r['coverage']['reviewed_candidate_count'],0)
        discard=json.loads((FIXTURES/'current_discard_real_v8.json').read_text(encoding='utf8'))['before_response']
        c,_,_,_=self.transport(discard);r=c.current_decision_options();self.safe(r)
        self.assertEqual(r['coverage']['engine_offered_count'],8)
        self.assertEqual(len(r['options']),8)
        self.assertTrue(all(o['kind']=='discard_selection_probe' for o in r['options']))

    def test_state15_retains_v13_equip_context_without_v14_revision_fields(self):
        states=json.loads((FIXTURES/'current_target_revision_real_v14.json').read_text(encoding='utf8'))
        for name in ('first_child','revised_child'):
            state=copy.deepcopy(states[name])
            state['schema_version']='mtgaplayer.decision-state.v15'
            state.pop('revised_choice_continuation');state['cast_choice_continuation']=None
            c,_,_,_=self.transport(state);r=c.current_decision_options();self.safe(r)
            self.assertEqual(len(r['options']),1)
            if name=='first_child':
                self.assertEqual(r['continuation_context']['field'],'choice_continuation')
                self.assertEqual(r['continuation_context']['current_request_binding'],state['binding'])
                self.assertFalse(r['continuation_context']['historical_parent_current'])
            else:
                self.assertIsNone(r['continuation_context'])
                self.assertEqual(r['options'][0]['kind'],'current_selected_literal_probe')

    def test_existing_v9_activate_relation_keeps_independent_scope(self):
        state=json.loads((FIXTURES/'activate_target_payment_real_v9.json').read_text(encoding='utf8'))['before_response']
        c,_,_,_=self.transport(state);r=c.current_decision_options();self.safe(r)
        self.assertEqual(r['coverage']['engine_offered_count'],17)
        relations=[o for o in r['options'] if o['kind']=='activate_target_payment_association']
        self.assertEqual(len(relations),1)
        self.assertEqual(relations[0]['evidence_level'],'known_constraints_verified')
        self.assertEqual(relations[0]['sources'],['known_candidates_v6.activate_payment'])
        self.assertIsNone(relations[0]['proposal'])
        self.assertTrue(relations[0]['validation_scope'])

    def test_existing_cast_activate_row_checks_merge_into_original_positions(self):
        for filename,cutoff,count,verified in (('player_log_cast_generic_one.jsonl',14,6,1),('player_log_activate_generic_two.jsonl',5,20,2)):
            self.cast.path.write_bytes(b''.join((FIXTURES/filename).read_bytes().splitlines(keepends=True)[:cutoff]))
            state=replay(self.cast.path,format='player-log',decision_state_version=5)['decision_state']
            c,_,_,_=self.transport(state);r=c.current_decision_options();self.safe(r)
            self.assertEqual(r['coverage']['engine_offered_count'],count)
            self.assertEqual(len(r['options']),count)
            self.assertEqual(r['coverage']['reviewed_candidate_count'],verified)

    def test_limits_preserve_denominators_and_omissions_without_false_zero(self):
        c,_,_,_=self.transport(self.cast.document(103)['decision_state'])
        r=c.current_decision_options(limit=2);self.safe(r)
        self.assertEqual(r['coverage']['engine_offered_count'],8)
        self.assertEqual(len(r['options']),2);self.assertTrue(r['coverage']['truncated'])
        self.assertGreater(r['coverage']['omitted_constructed_options'],0)
        for limit in (0,65,True,2.0):
            with self.assertRaises(ValueError):c.current_decision_options(limit=limit)

    def test_unsupported_rows_and_contradictions_never_gain_verified_proposals(self):
        helper=advisor_helpers.DecisionAdvisorTests('test_select_n_reports_options_and_unknown_minimum')
        helper.setUp();self.addCleanup(helper.doCleanups)
        c=helper.current([{'actionType':'ActionType_NotReviewedYet'}]);r=c.current_decision_options();self.safe(r)
        self.assertEqual(r['coverage']['engine_offered_count'],1)
        self.assertEqual(r['options'][0]['evidence_level'],'unsupported')
        self.assertFalse(r['options'][0]['research_eligible'])
        rows=[json.loads(line) for line in (FIXTURES/'player_log_activate_generic_two.jsonl').read_text().splitlines()]
        action=rows[4]['greToClientEvent']['greToClientMessages'][0]['actionsAvailableReq']['actions'][3]
        objects=rows[2]['greToClientEvent']['greToClientMessages'][0]['gameStateMessage']['gameObjects']
        obj=next(o for o in objects if o['instanceId']==action['instanceId'])
        next(p for p in obj['uniqueAbilities'] if p['id']==action['uniqueAbilityId'])['grpId']+=999
        self.cast.path.write_text(''.join(json.dumps(row)+'\n' for row in rows[:5]))
        state=replay(self.cast.path,format='player-log',decision_state_version=5)['decision_state']
        c,_,_,_=self.transport(state);r=c.current_decision_options();self.safe(r)
        self.assertEqual(r['coverage']['engine_offered_count'],20)
        self.assertEqual([o['list_position'] for o in r['options'] if o['proposal']],[1])
        self.assertTrue(any(u['evidence_level']=='violated_known_constraints' and u['count']==1 for u in r['unresolved']))

    def test_same_snapshot_computed_once_and_returned_data_cannot_poison_cache(self):
        c,_,_,_=self.transport(self.cast.document()['decision_state'])
        with patch.object(options,'enumerate_known_candidates',wraps=options.enumerate_known_candidates) as generate:
            first=c.current_decision_options();first['options'][0]['request_binding']['request_id']=999
            second=c.current_decision_options();self.assertEqual(generate.call_count,1)
            self.assertEqual(second['request_binding']['request_id'],10102)
            self.assertEqual(second['options'][0]['request_binding'],second['request_binding'])

    def test_expiry_during_generation_and_after_cache_hit_never_returns_old_options(self):
        for during in (False,True):
            c,_,clock,_=self.transport(self.cast.document()['decision_state'])
            if during:
                original=options._build
                def slow(*args):
                    value=original(*args);clock.advance(600);return value
                with patch.object(options,'_build',slow):r=c.current_decision_options()
            else:
                self.assertEqual(len(c.current_decision_options()['options']),4);clock.advance(600)
                r=c.current_decision_options()
            self.assertEqual(r['status'],'expired');self.assertEqual(r['options'],[])
            self.assertIsNone(c._decision_options_cache)

    def test_history_close_and_cross_version_streams_cannot_restore_candidates(self):
        state=self.cast.document()['decision_state'];c,_,_,_=self.transport(state,history=True)
        self.assertEqual(c.current_decision_options()['options'],[])
        c,pub,_,_=self.transport(state);self.assertEqual(len(c.current_decision_options()['options']),4)
        for event in pub.stop():self.assertTrue(c.accept_event(event))
        self.assertEqual(c.current_decision_options()['options'],[]);self.assertIsNone(c._decision_options_cache)
        c,_,_,_=self.transport(state)
        equip=json.loads((FIXTURES/'current_target_revision_real_v14.json').read_text())['revised_child']
        _,_,_,events=self.transport(equip);wrong=copy.deepcopy(next(e for e in events if e['event_type']=='snapshot'))
        wrong['sequence']=c.current_view()['last_sequence']+1;wrong['snapshot_ref']['sequence']=wrong['sequence']
        self.assertFalse(c.accept_event(wrong));self.assertEqual(c.current_decision_options()['options'],[])

    def test_cli_optin_and_final_shared_sidecar_recheck(self):
        c,pub,clock,events=self.transport(self.cast.document()['decision_state'])
        data=''.join(json.dumps(e)+'\n' for e in events+pub.stop()).encode()
        for enabled in (False,True):
            run=subprocess.run([sys.executable,'-m','mtgaplayer','consume-events',*(['--current-decision-options'] if enabled else [])],
                input=data,capture_output=True,timeout=30)
            self.assertEqual(run.returncode,0,run.stderr)
            rows=[json.loads(line) for line in run.stdout.splitlines()]
            self.assertTrue(all(('current_decision_options' in row)==enabled for row in rows))
            if enabled:self.assertTrue(any(row['current_decision_options']['options'] for row in rows))
        output=[];original=DecisionConsumer.current_view;calls=[0]
        def later(consumer):
            calls[0]+=1
            if calls[0]==3:clock.advance(600)
            return original(consumer)
        with patch.object(DecisionConsumer,'current_view',later):
            consume_events(io.BytesIO(data),output.append,DecisionConsumer(10000,500,clock),current_decision_options=True)
        self.assertTrue(all(not row['current_decision_options']['options'] for row in output))


if __name__=='__main__':unittest.main()
