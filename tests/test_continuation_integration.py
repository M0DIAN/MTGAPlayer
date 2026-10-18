"""Parallel v14/v15 profiles; public evidence, synthetic cross-path controls."""
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from mtgaplayer import choice_continuation as first, target_revision as revision, cast_continuation as cast
from mtgaplayer.cli import replay, watch
from mtgaplayer.decision_consumer import DecisionConsumer, EXECUTION, _state, consume_events
from mtgaplayer.decision_publisher import DecisionPublisher, EVENT_VERSIONS
from mtgaplayer.decision_state import SCHEMA_VERSIONS
from mtgaplayer.raw_log import RawReducer
import test_target_revision as revision_tests
import test_cast_continuation as cast_tests
from test_decision_publisher import ManualClock


class ContinuationIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.equip = revision_tests.TargetRevisionTests('test_synthetic_complete_chain_two_stages_and_terminal_revocation')
        self.equip.setUp()
        self.spell = cast_tests.CastContinuationTests('test_four_existing_singleton_validations_keep_current_child_binding')
        self.spell.setUp(); self.addCleanup(self.spell.doCleanups)

    def producer(self):
        r = RawReducer(include_state_messages=True, include_request_parameters=True,
            include_targeted_activate=True, include_current_discard=True, include_target_payment_relation=True,
            include_cast_target_members=True, include_cast_activate_associations=True)
        stage = first.StageObserver(r, include_revision=True, include_cast=True)
        r.observer = stage.observe; r.reset(1); stage.reset()
        return r, stage

    def apply(self, r, stage, rows):
        for row in rows: stage.prepare(row); r.apply(row); stage.after_apply()

    def transport(self, state, session='synthetic-integration'):
        state = copy.deepcopy(state); state['source'].update(mode='watch',phase='append',stopped=False)
        clock = ManualClock(); pub = DecisionPublisher(clock_ns=clock,session_id=session,
            state_version=int(state['schema_version'].rsplit('v',1)[1]))
        meta = {'poll_started_ns':clock(),'poll_completed_ns':clock(),'poll_read_ns':0,'reducer_apply_ns':0,
            'decision_state_assembly_ns':0,'request_changed':True,'new_final_request':True}
        events = pub.observe({'decision_state':state,'source':{'phase':'append','partial_record':False}},meta)
        c = DecisionConsumer(10000,500,clock)
        for e in events: self.assertTrue(c.accept_event(e))
        return pub,c,clock,events

    def test_both_observers_keep_actual_cast_and_equip_states_separate(self):
        r,stage = self.producer(); rows = self.spell.rows(110)
        self.apply(r,stage,rows[:106]); self.assertIsNotNone(stage.cast.active)
        self.assertIsNone(stage.active); self.assertIsNone(stage.revision.active); self.assertIsNone(stage.revision.pending)
        self.apply(r,stage,rows[106:]); self.assertIsNone(r.request); self.assertIsNone(stage.cast.active)
        r.reset(2); stage.reset()
        rows = self.equip.synthetic_records(terminal=True)
        self.apply(r,stage,rows[:5]); self.assertIsNotNone(stage.active); self.assertIsNone(stage.cast.active)
        self.apply(r,stage,rows[5:7]); self.assertIsNotNone(stage.revision.active)
        self.assertIsNone(stage.active); self.assertIsNone(stage.cast.active); self.assertIsNone(stage.cast.pending)
        self.apply(r,stage,rows[7:]); self.assertIsNone(r.request); self.assertIsNone(stage.revision.active)
        self.assertTrue(stage.revision.client_submit_observed)

    def test_first_only_clear_does_not_destroy_sibling_pending_but_reset_does(self):
        r,stage = self.producer(); self.apply(r,stage,self.spell.rows(104))
        saved = copy.deepcopy(stage.cast.pending); self.assertIsNotNone(saved)
        stage._clear(); self.assertEqual(stage.cast.pending,saved)
        stage.reset(); self.assertIsNone(stage.cast.pending); self.assertIsNone(stage.revision.pending)
        r.reset(2); stage.reset(); self.apply(r,stage,self.equip.synthetic_records()[:6])
        saved = copy.deepcopy(stage.revision.pending); self.assertIsNotNone(saved)
        stage._clear(); self.assertEqual(stage.revision.pending,saved)
        stage.reset(); self.assertIsNone(stage.revision.pending); self.assertIsNone(stage.cast.pending)

    def test_cast_cannot_borrow_actual_equip_selection_for_revision(self):
        r,stage = self.producer(); rows = self.spell.rows(109)
        self.apply(r,stage,rows[:106]); self.assertIsNotNone(stage.cast.active)
        self.apply(r,stage,rows[106:])
        self.assertEqual(r.request['id'],10104)
        self.assertIsNone(stage.revision.active); self.assertIsNone(stage.active); self.assertIsNone(stage.cast.active)
        self.assertNotIn(revision.PRIVATE,r.request)
        # A new Full/auth episode without the corresponding actual Cast response
        # cannot inherit the previous episode's consumed parent or transfer.
        r.reset(2); stage.reset(); self.apply(r,stage,self.spell.rows(103))
        self.apply(r,stage,self.spell.rows(106)[104:])
        self.assertIsNone(stage.cast.active); self.assertNotIn(cast.PRIVATE,r.request)

    def test_stack_card_and_ability_type_swaps_withhold_cross_path_proof(self):
        r,stage = self.producer(); rows = self.spell.rows()
        rows[104]['greToClientEvent']['greToClientMessages'][0]['gameStateMessage']['gameObjects'][1]['type']='GameObjectType_Ability'
        self.apply(r,stage,rows); self.assertIsNone(r.error)
        self.assertIsNone(stage.cast.active); self.assertIsNone(stage.active); self.assertIsNone(stage.revision.active)
        r.reset(2); stage.reset(); rows = self.equip.synthetic_records()
        rows[4]['greToClientEvent']['greToClientMessages'][0]['gameStateMessage']['gameObjects'][0]['type']='GameObjectType_Card'
        self.apply(r,stage,rows)
        self.assertIsNone(stage.active); self.assertIsNone(stage.revision.active); self.assertIsNone(stage.cast.active)

    def test_revision_duplicate_diff_rejected_with_otherwise_valid_current_request(self):
        rows = self.equip.synthetic_records(); combined = rows.pop()['greToClientEvent']['greToClientMessages']
        diff={'greToClientEvent':{'greToClientMessages':[combined[0]]}}
        child={'greToClientEvent':{'greToClientMessages':[combined[1]]}}
        r,stage=self.producer(); self.apply(r,stage,rows+[copy.deepcopy(diff),copy.deepcopy(diff),child])
        self.assertIsNone(r.error); self.assertEqual(r.request['id'],3)
        self.assertIsNone(stage.revision.active); self.assertNotIn(revision.PRIVATE,r.request)
        control,observer=self.producer(); self.apply(control,observer,rows+[diff,child])
        self.assertIsNotNone(observer.revision.active)

    def test_revision_pending_partial_poll_cannot_revive_on_completion(self):
        rows=self.equip.synthetic_records()
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'synthetic.jsonl'
            path.write_text(''.join(json.dumps(r)+'\n' for r in rows[:6]),encoding='utf-8')
            stream=watch(path,interval=0,samples=4,decision_state_version=14)
            before=next(stream); self.assertIsNone(before['decision_state']['binding']['request_id'])
            tail=(json.dumps(rows[6])+'\n').encode()
            with path.open('ab') as out:out.write(tail[:20])
            partial=next(stream); self.assertEqual(partial['error'],'partial_raw_record_waiting')
            with path.open('ab') as out:out.write(tail[20:])
            after=next(stream)
            self.assertIsNone(after['error']); self.assertEqual(after['decision_state']['binding']['request_id'],3)
            self.assertIsNone(after['decision_state'][revision.FIELD]); self.assertFalse(revision.evaluate_revision(after['decision_state'])['current_revised_child_verified'])
            next(stream)

    def test_revision_typed_predecessor_refuses_same_value_float(self):
        rows=self.equip.synthetic_records()
        rows[6]['greToClientEvent']['greToClientMessages'][0]['gameStateMessage']['prevGameStateId']=11.0
        r,stage=self.producer(); self.apply(r,stage,rows)
        self.assertIsNone(r.error); self.assertEqual(r.request['id'],3)
        self.assertIsNone(stage.revision.active); self.assertNotIn(revision.PRIVATE,r.request)
        control,observer=self.producer(); self.apply(control,observer,self.equip.synthetic_records())
        self.assertIsNotNone(observer.revision.active)

    def test_revision_first_predecessor_typed_without_changing_old_observer(self):
        rows=self.equip.synthetic_records()
        rows[4]['greToClientEvent']['greToClientMessages'][0]['gameStateMessage']['prevGameStateId']=10.0
        r,stage=self.producer(); self.apply(r,stage,rows[:5])
        self.assertIsNone(r.error); self.assertEqual(r.request['id'],2)
        self.assertIsNone(stage.active); self.assertNotIn(first.PRIVATE,r.request)
        self.apply(r,stage,rows[5:])
        self.assertEqual(r.request['id'],3); self.assertIsNone(stage.revision.active)
        self.assertNotIn(revision.PRIVATE,r.request)
        old,_=self.producer(); old_stage=first.StageObserver(old)
        old.observer=old_stage.observe; old_stage.reset()
        self.apply(old,old_stage,rows[:5])
        self.assertIsNone(old.error); self.assertIsNotNone(old_stage.active)
        control,observer=self.producer(); self.apply(control,observer,self.equip.synthetic_records())
        self.assertIsNotNone(observer.revision.active)

    def test_all_registered_versions_keep_exact_parallel_field_sets(self):
        self.assertEqual(set(SCHEMA_VERSIONS),set(range(1,16)))
        self.assertEqual(set(EVENT_VERSIONS),set(range(1,16)))
        for version in range(1,16):
            with self.subTest(version=version):
                state=self.spell.document(version=version)['decision_state']; _state(state,state['binding'])
                self.assertEqual(revision.FIELD in state,version==14)
                self.assertEqual(cast.FIELD in state,version==15)
                self.transport(state)
        with self.assertRaises(ValueError):replay(self.spell.path,format='player-log',decision_state_version=15,current_target_revision=True)
        with self.assertRaises(ValueError):replay(self.spell.path,format='player-log',decision_state_version=14,current_cast_continuation=True)

    def test_cross_version_state_event_and_subscription_are_quarantined(self):
        states=[self.equip.state,self.spell.document()['decision_state']]
        events=[]
        for state in states:events.append(next(e for e in self.transport(state)[3] if e['event_type']=='snapshot'))
        for index,event in enumerate(events):
            wrong=copy.deepcopy(event); wrong['schema_version']=events[1-index]['schema_version']
            consumer=DecisionConsumer(10000,500,ManualClock()); self.assertFalse(consumer.accept_event(wrong))
        for left,right in (events,events[::-1]):
            consumer=DecisionConsumer(10000,500,ManualClock()); self.assertTrue(consumer.accept_event(left))
            wrong=copy.deepcopy(right); wrong['sequence']=2; wrong['snapshot_ref']['sequence']=2
            self.assertFalse(consumer.accept_event(wrong)); self.assertEqual(consumer.current_view()['consumer_status'],'PROTOCOL_ERROR')
            self.assertFalse(revision.assess_current_revision(consumer)['current_revised_child_verified'])
            self.assertEqual(cast.assess_current_continuation(consumer)['candidates'],[])

    def test_nullable_fields_cannot_be_missing_or_cross_injected(self):
        for state,own,other in ((self.equip.state,revision.FIELD,cast.FIELD),(self.spell.document()['decision_state'],cast.FIELD,revision.FIELD)):
            for change in ('missing','extra','borrowed'):
                bad=copy.deepcopy(state)
                if change=='missing':bad.pop(own)
                elif change=='extra':bad[other]=None
                else:
                    bad[own]=copy.deepcopy(self.equip.state[revision.FIELD] if own==cast.FIELD else self.spell.document()['decision_state'][cast.FIELD])
                with self.subTest(own=own,change=change):
                    with self.assertRaises(ValueError):_state(bad,bad['binding'])

    def test_both_consumer_sidecars_recheck_ref_after_later_assessment(self):
        states=[self.equip.state,self.spell.document()['decision_state']]
        for state in states:
            pub,c,clock,events=self.transport(state)
            data=''.join(json.dumps(e)+'\n' for e in events+pub.stop()).encode()
            output=[]; status=consume_events(io.BytesIO(data),output.append,DecisionConsumer(10000,500,clock),
                current_target_revision=True,current_cast_continuation=True)
            self.assertEqual(status,0)
            self.assertTrue(all(k in row for row in output for k in ('current_target_revision','current_cast_continuation')))
            self.assertTrue(all(row[k] is False for row in output for k in EXECUTION))
            self.assertFalse(output[-1]['current_target_revision']['current_revised_child_verified'])
            self.assertEqual(output[-1]['current_cast_continuation']['candidates'],[])
        # Revision runs before Cast. A later assessment can expire an earlier
        # revision result; the shared final sidecar recheck must withhold it.
        pub,c,clock,events=self.transport(self.equip.state)
        original=cast.assess_current_continuation
        def later(consumer):
            result=original(consumer);clock.advance(600);return result
        output=[]
        with patch.object(cast,'assess_current_continuation',later):
            consume_events(io.BytesIO(''.join(json.dumps(e)+'\n' for e in events+pub.stop()).encode()),output.append,
                DecisionConsumer(10000,500,clock),current_target_revision=True,current_cast_continuation=True)
        self.assertTrue(all(not row['current_target_revision']['current_revised_child_verified'] for row in output))
