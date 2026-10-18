"""Real prefix103 observations; mutations/transport/clocks explicitly synthetic.

Never use the actual position3 response to establish position2 semantics.
"""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from mtgaplayer import multi_slot_cast as multi
from mtgaplayer.cli import replay, watch_decision_events
from mtgaplayer.decision_consumer import DecisionConsumer, EXECUTION, _state
from mtgaplayer.decision_publisher import DecisionPublisher
from mtgaplayer.choice_candidates import enumerate_known_candidates
from test_decision_publisher import ManualClock, poll_events

FIXTURE = Path(__file__).parent / 'fixtures/player_log_single_target.jsonl'


class MultiSlotCastTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / 'public.jsonl'
        # This open never fetches the future response, even while preparing tests.
        with FIXTURE.open('rb') as source:
            self.lines = [line.replace(b'\r\n', b'\n') for _, line in zip(range(103), source)]
        self.path.write_bytes(b''.join(self.lines))

    def document(self, rows=None, enabled=True, version=15):
        if rows is not None:
            self.path.write_text(''.join(json.dumps(row) + '\n' for row in rows), encoding='utf8')
        return replay(self.path, format='player-log', decision_state_version=version,
                      current_multi_slot_cast=enabled)

    def facts(self, state):
        space = state['legal_action_space']
        return multi.checked_observations(space['choice_graph'], space['immediate_frontier']['projection'],
                                           state['visible_objects'], state['binding'])

    def transport(self, state):
        state = copy.deepcopy(state); clock = ManualClock()
        state['source'].update(mode='watch', phase='append', stopped=False)
        publisher = DecisionPublisher(clock_ns=clock, session_id='synthetic-mp67', state_version=15)
        document = {'decision_state': state, 'source': {'phase':'append', 'partial_record':False}}
        metadata = {'poll_started_ns':clock(), 'poll_completed_ns':clock(), 'poll_read_ns':0,
            'reducer_apply_ns':0, 'decision_state_assembly_ns':0, 'request_changed':True, 'new_final_request':True}
        events = publisher.observe(document, metadata); consumer = DecisionConsumer(10000, 500, clock)
        for event in events:self.assertTrue(consumer.accept_event(event))
        return consumer, publisher, clock, events

    def test_real_prefix103_independent_slots_cost_identity_and_no_proposal(self):
        self.assertEqual(hashlib.sha256(b''.join(self.lines)).hexdigest(),
            '1616b632532286f5437c4675c814a25a6a902b40e0de67c19308b37cafaf0c9d')
        for version in (5, 11, 12, 14, 15):
            state = self.document(version=version)['decision_state']; _state(state, state['binding'])
            facts = self.facts(state); self.assertEqual(list(facts), [2]); value = facts[2]
            self.assertEqual(state['binding']['request_id'], 10100)
            self.assertEqual(value['action_literal']['identifier_refs'], {'instanceId':1245,'grpId':86855,'facetId':284})
            self.assertEqual(value['action_literal']['parameters']['manaCost'], [{'color':['ManaColor_Red'],'count':1}])
            self.assertEqual([(s['slot_position'],s['target_idx'],s['provided_object_refs']) for s in value['slots']],
                             [(0,2,[1243]),(1,1,[1243])])
            for slot in value['slots']:
                self.assertTrue(all(slot[k] is None for k in ('minimum','maximum','selected_count')))
            for key in multi.DENIALS:self.assertIs(value[key],False,key)
            self.assertEqual(value['payment_status'],'unknown')
            self.assertIs(value['auto_tap_solution_observed'],False)
            self.assertIsNone(next(o for o in state['visible_objects'] if o['instance_id']==1245)['card_id'])
        state=self.document()['decision_state']; c,_,_,_=self.transport(state)
        options=c.current_decision_options(); row=options['options'][2]
        self.assertEqual(options['coverage']['engine_offered_count'],8)
        self.assertEqual(options['coverage']['returned_options'],16)
        self.assertEqual(row['list_position'],2);self.assertEqual(row['kind'],'engine_action')
        self.assertIsNone(row['proposal']);self.assertNotEqual(row['evidence_level'],'known_constraints_verified')
        self.assertEqual(row['observation'][multi.FIELD],self.facts(state)[2])
        self.assertEqual(row['request_binding'],state['binding'])
        self.assertEqual(row['source_snapshot_ref'],options['source_snapshot_ref'])
        self.assertEqual(c.shadow_decision()['status'],'abstain')
        self.assertIsNone(c.shadow_decision()['preferred_option_key'])
        for flag in EXECUTION:self.assertIs(options[flag],False,flag)

    def test_opt_in_keeps_legacy_full_results_and_single_slot_validators(self):
        old=self.document(enabled=False); new=self.document()
        cleaned=copy.deepcopy(new)
        for node in cleaned['decision_state']['legal_action_space']['choice_graph']['action_nodes']:
            for constraint in node['constraints']:constraint.pop(multi.FIELD,None)
        self.assertEqual(cleaned,old)
        for version in (5,6):
            self.assertEqual(enumerate_known_candidates(old['decision_state'],version=version),
                             enumerate_known_candidates(new['decision_state'],version=version))
        self.assertNotIn('_multi_slot_cast',new['current']['request'])

    def test_raw_counterexamples_withhold_local_proof(self):
        rows=[json.loads(line) for line in self.lines]
        for mutate in (
            lambda a:a['targets'][0].update(targetIdx=1),
            lambda a:a['targets'][0].update(targetIdx=True),
            lambda a:a.update(instanceId=1243),
            lambda a:a['targets'][0]['targets'][0].update(targetInstanceId=999999),
            lambda a:a['targets'][0]['targets'][0].update(targetInstanceId=1245),
            lambda a:a['targets'].pop(),
            lambda a:a.update(autoTapSolution={'autoTapActions':[]}),
            lambda a:a['targets'][0]['targets'].append({'targetInstanceId':1243}),
            lambda a:a.update(actionType='ActionType_Activate')):
            changed=copy.deepcopy(rows); raw=changed[-1]['greToClientEvent']['greToClientMessages'][0]['actionsAvailableReq']['actions'][2]
            mutate(raw)
            with self.subTest(raw=raw):self.assertEqual(self.facts(self.document(changed)['decision_state']),{})

    def test_raw_unknown_or_conflicting_card_group_and_public_visibility(self):
        from mtgaplayer.raw_log import RawFollower, RawReducer
        from mtgaplayer.action_target_menus import public_battlefield_refs
        follower=RawFollower(self.path);r=RawReducer();reset,records=follower.poll();r.reset(follower.generation)
        for record in records:r.apply(record)
        raw=json.loads(self.lines[-1])['greToClientEvent']['greToClientMessages'][0]
        objects=r._current()['objects']
        visible=[{'instance_id':o['id'],'card_id':o['card_id'],'zone':o['zone'],
            'owner_seat':o['owner'],'controller_seat':o['controller']} for o in objects]
        public=public_battlefield_refs(r,objects)
        self.assertIn(2,multi.project(raw,visible,2,r._cast_source_refs(),public))
        bad=copy.deepcopy(visible);next(o for o in bad if o['instance_id']==1245)['card_id']=86856
        self.assertEqual(multi.project(raw,bad,2,r._cast_source_refs(),public),{})
        self.assertEqual(multi.project(raw,visible,2,r._cast_source_refs(),[x for x in public if x!=1243]),{})
        self.assertEqual(multi.project(raw,visible,1,r._cast_source_refs(),public),{})

    def test_consumer_rejects_misbinding_slot_member_payment_and_authority_claims(self):
        state=self.document()['decision_state']
        def evidence(s):
            return next(c[multi.FIELD] for n in s['legal_action_space']['choice_graph']['action_nodes']
                        for c in n['constraints'] if multi.FIELD in c)
        for mutate in (
            lambda s,e:e['action_literal']['parameters']['targets'].reverse(),
            lambda s,e:e['action_literal']['parameters']['targets'][0].update(targetIdx=1),
            lambda s,e:e['slots'].reverse(),
            lambda s,e:e['slots'][0].update(minimum=1),
            lambda s,e:e['slots'][0].update(provided_object_refs=[1240]),
            lambda s,e:e['action_literal']['identifier_refs'].update(instanceId=1066),
            lambda s,e:e['action_literal']['identifier_refs'].update(grpId=86856),
            lambda s,e:e['action_key']['request_identity'].update(request_id=10101),
            lambda s,e:e['action_key']['request_identity'].update(self_seat=1),
            lambda s,e:e.update(payment_status='free'),
            lambda s,e:e.update(auto_tap_solution_observed=True),
            lambda s,e:e.update(complete_legality_verified=True),
            lambda s,e:e.update(target_combination_verified=True),
            lambda s,e:e.update(complete_legality_verified=0),
            lambda s,e:e.update(schema_version='mtgaplayer.current-multi-slot-cast.v2'),
            lambda s,e:s['visible_objects'].remove(next(o for o in s['visible_objects'] if o['instance_id']==1243))):
            bad=copy.deepcopy(state);mutate(bad,evidence(bad))
            with self.subTest(mutate=mutate):
                with self.assertRaises((ValueError,KeyError,TypeError)):_state(bad,bad['binding'])

    def test_raw_slot_order_is_preserved_but_retransmission_cannot_change_it(self):
        rows=[json.loads(line) for line in self.lines]; changed=copy.deepcopy(rows[-1])
        changed['greToClientEvent']['greToClientMessages'][0]['actionsAvailableReq']['actions'][2]['targets'].reverse()
        first=self.document(rows[:-1]+[changed])['decision_state']
        self.assertEqual([s['target_idx'] for s in self.facts(first)[2]['slots']],[1,2])
        same=self.document(rows+[copy.deepcopy(rows[-1])])['decision_state']
        self.assertIn(2,self.facts(same))
        conflict=self.document(rows+[changed])
        self.assertIsNone(conflict['decision_state']);self.assertEqual(conflict['error'],'conflicting_request_identity')

    def test_current_consumer_lease_stop_and_computation_invalidation(self):
        from unittest.mock import patch
        from mtgaplayer import decision_options
        state=self.document()['decision_state']; c,p,clock,_=self.transport(state)
        offered=c.current_decision_options();self.assertEqual(offered,c.current_decision_options())
        offered['options'][2]['observation'][multi.FIELD]['slots'].clear()
        self.assertEqual(len(c.current_decision_options()['options'][2]['observation'][multi.FIELD]['slots']),2)
        clock.advance(501);self.assertEqual(c.current_decision_options()['status'],'expired')
        self.assertEqual(c.shadow_decision()['status'],'expired')
        c,p,clock,_=self.transport(state)
        for event in p.stop('sample_limit'):self.assertTrue(c.accept_event(event))
        self.assertEqual(c.current_decision_options()['options'],[])
        c,_,clock,_=self.transport(state);original=decision_options._build
        def expires(*a,**kw):
            result=original(*a,**kw);clock.advance(501);return result
        with patch.object(decision_options,'_build',side_effect=expires):
            self.assertEqual(c.current_decision_options()['options'],[])

    def test_real_position3_lifecycle_never_promotes_position2_or_borrows_child_domain(self):
        frozen=copy.deepcopy(self.facts(self.document()['decision_state']))
        # Only now open future real rows for regression/lifecycle, not pos2 proof.
        lines=FIXTURE.read_bytes().replace(b'\r\n',b'\n').splitlines(keepends=True)
        self.path.write_bytes(b''.join(lines[:102]));clock=ManualClock();c=DecisionConsumer(10000,10000,clock)
        stream=watch_decision_events(self.path,interval=0,samples=8,decision_state_version=15,
            current_multi_slot_cast=True,clock_ns=clock,session_id='synthetic-mp67-watch')
        self.addCleanup(stream.close)
        for event in poll_events(stream):self.assertTrue(c.accept_event(event))
        previous=102
        for cutoff in (103,104,105,106,107,109,110):
            with self.path.open('ab') as out:out.write(b''.join(lines[previous:cutoff]))
            previous=cutoff
            for event in poll_events(stream):self.assertTrue(c.accept_event(event))
            options=c.current_decision_options();shadow=c.shadow_decision()
            self.assertNotEqual(shadow['status'],'research_preference')
            if cutoff==103:self.assertEqual(options['options'][2]['observation'][multi.FIELD],frozen[2])
            else:self.assertFalse(any(multi.FIELD in (o.get('observation') or {}) for o in options['options']))
            if cutoff in (104,105,107,110):self.assertEqual(options['options'],[])
            if cutoff==106:self.assertEqual(options['coverage']['returned_options'],4)
            if cutoff==109:self.assertEqual(options['coverage']['returned_options'],0)

    def test_all_current_revocations_discard_computed_slot_observation(self):
        from unittest.mock import patch
        from mtgaplayer import decision_options
        state=self.document()['decision_state']
        for reason in ('request_consumed','request_replaced','state_advanced','source_partial',
                       'source_reset','identity_changed','session_stopped'):
            with self.subTest(reason=reason):
                c,p,_,_=self.transport(state);invalidate=p.stop()[0]
                invalidate.update(reason=reason,subscription_active=reason!='session_stopped')
                original=decision_options._build
                def changed(*args,**kwargs):
                    result=original(*args,**kwargs)
                    self.assertIn(multi.FIELD,result['options'][2]['observation'])
                    self.assertTrue(c.accept_event(invalidate));return result
                with patch.object(decision_options,'_build',changed):
                    self.assertEqual(c.current_decision_options()['options'],[])
                self.assertEqual(c.current_decision_options()['options'],[])
                self.assertEqual(c.shadow_decision()['status'],'expired')

    def test_partial_poll_retransmit_and_consumed_request_never_restore_facts(self):
        self.path.write_bytes(b''.join(self.lines[:102]));clock=ManualClock();c=DecisionConsumer(10000,10000,clock)
        stream=watch_decision_events(self.path,interval=0,samples=5,decision_state_version=15,
            current_multi_slot_cast=True,clock_ns=clock,session_id='synthetic-mp67-partial')
        self.addCleanup(stream.close)
        for event in poll_events(stream):self.assertTrue(c.accept_event(event))
        with self.path.open('ab') as out:out.write(self.lines[-1])
        for event in poll_events(stream):self.assertTrue(c.accept_event(event))
        self.assertIn(multi.FIELD,c.current_decision_options()['options'][2]['observation'])
        with self.path.open('ab') as out:out.write(self.lines[-1][:10])
        for event in poll_events(stream):self.assertTrue(c.accept_event(event))
        self.assertEqual(c.current_decision_options()['options'],[])
        with self.path.open('ab') as out:out.write(self.lines[-1][10:])
        for event in poll_events(stream):self.assertTrue(c.accept_event(event))
        self.assertEqual(c.current_decision_options()['options'],[])
        # Actual response consumes the whole request, irrespective of chosen position.
        with FIXTURE.open('rb') as f: response=[line for _,line in zip(range(104),f)][-1]
        self.path.write_bytes(b''.join(self.lines)+response+self.lines[-1])
        state=self.document()['decision_state']
        self.assertIsNone(state['binding']['request_id']);self.assertEqual(self.facts(state),{})

    def test_cli_explicit_opt_in_and_invalid_versions(self):
        command=[sys.executable,'-m','mtgaplayer','replay',str(self.path),'--format','player-log',
            '--decision-state-version','15','--current-multi-slot-cast']
        run=subprocess.run(command,capture_output=True,text=True,check=True)
        self.assertIn(2,self.facts(json.loads(run.stdout)['decision_state']))
        run=subprocess.run(command[:3]+['watch',str(self.path),'--decision-events','--decision-state-version','15',
            '--current-multi-slot-cast','--samples','1','--interval','0.001'],capture_output=True,text=True,check=True)
        events=[json.loads(line) for line in run.stdout.splitlines()]
        self.assertTrue(any(e['event_type']=='snapshot' and self.facts(e['decision_state']) for e in events))
        for version in (1,4):
            with self.assertRaises(ValueError):self.document(version=version)
        with self.assertRaises(ValueError):
            replay(self.path,current_multi_slot_cast=True,decision_state_version=15)
