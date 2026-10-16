"""Pre-response tests use the committed real Cast slice, never private logs."""
import copy
import io
import json
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from mtgaplayer.cli import replay, watch_decision_events
from mtgaplayer.choice_validation import (validate_proposed_choice, assess_current_choice,
    load_proposal, MAX_PROPOSAL_BYTES)
from mtgaplayer.decision_consumer import DecisionConsumer, EXECUTION, consume_events
from mtgaplayer.semantic_samples import collect_samples, replay_samples
from test_decision_publisher import ManualClock, poll_events
from test_decision_consumer import encoded

FIXTURE = Path(__file__).parent/'fixtures'/'player_log_cast_generic_one.jsonl'
ROOT = Path(__file__).resolve().parents[1]


class ChoiceValidationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name); self.path = self.root/'cast.log'
        self.rows = FIXTURE.read_bytes().splitlines(keepends=True)
        self.path.write_bytes(b''.join(self.rows[:14]))
        self.state = replay(self.path, format='player-log', decision_state_version=5)['decision_state']
        self.proposal = {'request_identity': self.state['binding'], 'list_position': 1,
            'proposed_action': copy.deepcopy(self.evidence()['actions'][1])}

    def evidence(self, state=None):
        return (state or self.state)['legal_action_space']['request_parameters']

    def result(self, state=None, proposal=None):
        return validate_proposed_choice(state or self.state, proposal or self.proposal)

    def assert_unknown(self, result, reason=None):
        self.assertEqual(result['known_constraints'], 'insufficient_evidence')
        if reason: self.assertIn(reason, result['reasons'])
        self.assertTrue(all(result[k] is False for k in EXECUTION))

    def append(self, rows):
        with self.path.open('ab') as out: out.write(b''.join(rows))

    def snapshot(self):
        self.path.write_bytes(b''.join(self.rows[:13]))
        stream = watch_decision_events(self.path, interval=0, samples=4,
            clock_ns=ManualClock(), session_id='pre-response', decision_state_version=5)
        self.addCleanup(stream.close)
        history = poll_events(stream)
        self.append(self.rows[13:14])
        events = poll_events(stream)
        return next(e for e in events if e['event_type']=='snapshot'), history

    def test_real_prefix_checks_concrete_proposal_and_inherits_stats_stack_turn(self):
        r = self.result()
        self.assertEqual(r['known_constraints'], 'verified_known_constraints')
        self.assertTrue(all(r[k] is False for k in EXECUTION))
        self.assertIsNone(r['source_snapshot_ref'])  # pure offline research
        self.assertEqual(len(self.evidence()['actions']), 6)
        older = replay(self.path, format='player-log', decision_state_version=4)['decision_state']
        self.assertEqual(self.state['game'], older['game'])
        self.assertEqual(self.state['visible_objects'], older['visible_objects'])
        self.assertFalse(self.evidence()['historical_response_used'])
        for version in (1,2,3,4):
            document = replay(self.path, format='player-log', decision_state_version=version, decision_state=True)
            self.assertNotIn('request_parameters', document['decision_state']['legal_action_space'])
            self.assertNotIn('_request_parameters', json.dumps(document))
        self.assertNotIn('_request_parameters', json.dumps(replay(self.path, format='player-log')))

    def test_proposal_flags_do_not_become_game_rules_and_alternative_payment_is_unknown(self):
        changed=copy.deepcopy(self.proposal)
        changed['proposed_action']['flags']['shouldStop']=False
        self.assertEqual(self.result(proposal=changed)['known_constraints'], 'verified_known_constraints')
        changed['proposed_action']['parameters']['autoTapSolution']['autoTapActions'][0]['manaPaymentOption']['mana'][0]['count']=2
        self.assert_unknown(self.result(proposal=changed), 'alternative_payment_path_not_supported')

    def test_missing_empty_payment_and_wrong_binding_remain_distinct_unknowns(self):
        for field in ('manaCost','autoTapSolution'):
            state=copy.deepcopy(self.state);chosen=copy.deepcopy(self.proposal)
            self.evidence(state)['actions'][1]['parameters'].pop(field)
            state['legal_action_space']['immediate_frontier']['projection']['templates'][1]['observed_parameter_shapes'].pop(field)
            self.assert_unknown(self.result(state), 'required_mana_parameters_not_observed')
            chosen['proposed_action']['parameters'].pop(field)
            chosen['proposed_action']['observed_empty_parameters'].append(field)
            self.assert_unknown(self.result(proposal=chosen), 'alternative_payment_path_not_supported')
        for key in ('request_id','game_state_id','source_generation'):
            proposed=copy.deepcopy(self.proposal);proposed['request_identity'][key]+=1
            self.assert_unknown(self.result(proposal=proposed), 'proposal_binding_invalid')
        proposed=copy.deepcopy(self.proposal);proposed['list_position']=255
        self.assert_unknown(self.result(proposal=proposed), 'proposal_binding_invalid')

    def test_observed_internal_contradiction_is_violated_not_alternative_route(self):
        state=copy.deepcopy(self.state)
        chosen=copy.deepcopy(self.proposal)
        # Both the offered and proposed payment literally contradict their own
        # visible source/ability pair. This is a known relation, not a rules guess.
        for action in (self.evidence(state)['actions'][1], chosen['proposed_action']):
            action['parameters']['autoTapSolution']['autoTapActions'][0]['manaPaymentOption']['mana'][0]['abilityGrpId']+=1
        self.assertEqual(self.result(state,chosen)['known_constraints'], 'violated_known_constraints')
        state=copy.deepcopy(self.state)
        self.evidence(state)['actions'][3]['parameters']['manaPaymentOptions'][0]['mana'][0]['count']=2
        self.assertEqual(self.result(state)['known_constraints'], 'violated_known_constraints')

    def test_invisible_or_ambiguous_sources_reject_whole_evidence_without_leaking_values(self):
        rows=[json.loads(r) for r in self.rows[:14]]
        message=next(m for m in rows[13]['greToClientEvent']['greToClientMessages'] if 'actionsAvailableReq' in m)
        original=copy.deepcopy(message['actionsAvailableReq']['actions'])
        for mutate in (
            lambda a:a[0].update(instanceId=999999,grpId=999998),
            lambda a:a[1]['autoTapSolution']['autoTapActions'][0].update(instanceId=999999),
            lambda a:a[0].update(targets=[{'targetInstanceId':999999,'secret':'PRIVATE_SENTINEL'}]),
        ):
            message['actionsAvailableReq']['actions']=copy.deepcopy(original)
            mutate(message['actionsAvailableReq']['actions'])
            self.path.write_text(''.join(json.dumps(r)+'\n' for r in rows))
            document=replay(self.path,format='player-log',decision_state_version=5)
            self.assertIsNone(self.evidence(document['decision_state']))
            self.assertNotIn('PRIVATE_SENTINEL',json.dumps(document))
        state=copy.deepcopy(self.state);state['visible_objects'].append(copy.deepcopy(state['visible_objects'][0]))
        self.assert_unknown(self.result(state), 'proposal_or_state_invalid')

    def test_current_wrapper_rejects_history_wrong_snapshot_and_expiry_during_check(self):
        event,history=self.snapshot();clock=ManualClock(100)
        consumer=DecisionConsumer(10_000,500,clock)
        for row in history:self.assertTrue(consumer.accept_event(row))
        self.assert_unknown(assess_current_choice(consumer,self.proposal),'current_request_not_observed')
        consumer=DecisionConsumer(10_000,500,clock)
        event['sequence']=event['snapshot_ref']['sequence']=1
        self.assertTrue(consumer.accept_event(event))
        result=assess_current_choice(consumer,self.proposal)
        self.assertEqual(result['known_constraints'],'verified_known_constraints')
        self.assertEqual(result['source_snapshot_ref'],event['snapshot_ref'])
        proposed=copy.deepcopy(self.proposal);proposed['source_snapshot_ref']=copy.deepcopy(event['snapshot_ref'])
        proposed['source_snapshot_ref']['sequence']+=1
        self.assert_unknown(assess_current_choice(consumer,proposed),'proposal_binding_invalid')
        original=validate_proposed_choice
        def slow(*args,**kwargs):
            r=original(*args,**kwargs);clock.advance(501);return r
        with patch('mtgaplayer.choice_validation.validate_proposed_choice',side_effect=slow):
            result=assess_current_choice(consumer,self.proposal)
        self.assert_unknown(result,'current_snapshot_expired_or_changed')
        self.assertIsNone(result['source_snapshot_ref'])

    def test_diagnostic_rechecks_all_sidecars_after_later_work_expires_choice(self):
        event,_=self.snapshot();event['sequence']=event['snapshot_ref']['sequence']=1
        clock=ManualClock(100);consumer=DecisionConsumer(10_000,500,clock);out=[]
        original=assess_current_choice
        def slow(*args,**kwargs):
            r=original(*args,**kwargs);clock.advance(501);return r
        with patch('mtgaplayer.choice_validation.assess_current_choice',side_effect=slow):
            code=consume_events(io.StringIO(encoded([event])),out.append,consumer,choice_proposal=self.proposal)
        self.assertEqual(code,1)
        self.assertTrue(out)
        self.assertTrue(all(r['choice_validation']['known_constraints']=='insufficient_evidence' for r in out))

    def test_consumer_rejects_malformed_evidence_and_crossed_versions(self):
        event,_=self.snapshot();event['sequence']=event['snapshot_ref']['sequence']=1
        for mutate in (
            lambda e:e['decision_state']['legal_action_space']['request_parameters'].update(historical_response_used=True),
            lambda e:e['decision_state']['legal_action_space']['request_parameters']['binding'].update(request_id=999),
            lambda e:e['decision_state']['legal_action_space']['request_parameters']['actions'][0]['parameters'].update(secret='PRIVATE_SENTINEL'),
            lambda e:e.update(schema_version='mtgaplayer.decision-event.v4'),
            lambda e:e['decision_state']['legal_action_space']['immediate_frontier']['projection'].update(engine_active_action_count=5),
            lambda e:e['decision_state']['legal_action_space']['choice_graph']['action_nodes'][3]['action_identity']['raw_identifiers'].update(ability_grp_id=999),
        ):
            changed=copy.deepcopy(event);mutate(changed)
            consumer=DecisionConsumer()
            self.assertFalse(consumer.accept_event(changed))
            self.assertEqual(consumer.current_view()['consumer_status'],'PROTOCOL_ERROR')

    def test_loader_is_bounded_strict_and_cli_loads_before_starting_subscription(self):
        path=self.root/'proposal.json';path.write_text(json.dumps(self.proposal))
        self.assertEqual(load_proposal(path),self.proposal)
        for raw in ('{"request_identity":{},"request_identity":{}}', 'NaN', 'x'*(MAX_PROPOSAL_BYTES+1)):
            path.write_text(raw)
            with self.assertRaisesRegex(ValueError,'choice_proposal_unavailable_or_invalid'):load_proposal(path)
        run=subprocess.run([sys.executable,'-m','mtgaplayer','consume-events','--validate-choice',str(path)],
            input='',capture_output=True,text=True,timeout=5)
        self.assertEqual(run.returncode,2);self.assertEqual(run.stdout,'')
        self.assertIn('choice_proposal_unavailable_or_invalid',run.stderr)

    def test_formal_v5_contracts(self):
        state=json.loads((ROOT/'schemas/decision-state.v5.schema.json').read_text())
        event=json.loads((ROOT/'schemas/decision-event.v5.schema.json').read_text())
        self.assertEqual(state['$id'],'urn:mtgaplayer:decision-state:v5')
        self.assertEqual(event['$id'],'urn:mtgaplayer:decision-event:v5')
        self.assertIn('request_parameters',state['properties']['legal_action_space']['required'])
        self.assertFalse(state['$defs']['requestParameters']['additionalProperties'])
        self.assertEqual(event['properties']['decision_state']['allOf'][0]['$ref'],'urn:mtgaplayer:decision-state:v5')

    def test_actual_watch_consumer_pipe_verdict_before_response_then_revoke_and_history(self):
        proposal_path=self.root/'proposal.json';proposal_path.write_text(json.dumps(self.proposal))
        self.path.write_bytes(b''.join(self.rows[:13]))
        producer=subprocess.Popen([sys.executable,'-m','mtgaplayer','watch',str(self.path),
            '--decision-events','--decision-state-version','5','--interval','.025','--samples','120'],
            stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        consumer=subprocess.Popen([sys.executable,'-m','mtgaplayer','consume-events',
            '--validate-choice',str(proposal_path)],stdin=producer.stdout,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        producer.stdout.close();lines=queue.Queue()
        def read():
            for line in consumer.stdout:lines.put(json.loads(line))
            lines.put(None)
        reader=threading.Thread(target=read,daemon=True);reader.start()
        def until(predicate):
            for _ in range(50):
                row=lines.get(timeout=8)
                self.assertIsNotNone(row)
                if predicate(row):return row
            self.fail('expected diagnostic not observed')
        try:
            until(lambda r:r['consumer_status']=='OBSERVING')
            self.append(self.rows[13:14])
            verdict=until(lambda r:r['choice_validation']['known_constraints']=='verified_known_constraints')
            self.assertEqual(len(self.path.read_bytes().splitlines()),14)
            self.assertIsNotNone(verdict['choice_validation']['source_snapshot_ref'])
            self.append(self.rows[14:15])
            revoked=until(lambda r:r['consumer_status']=='INVALIDATED')
            self.assert_unknown(revoked['choice_validation'])
            self.append(self.rows[15:])
            while True:
                row=lines.get(timeout=8)
                if row is None:break
                self.assert_unknown(row['choice_validation'])
            self.assertEqual(consumer.wait(timeout=5),0,consumer.stderr.read())
            self.assertEqual(producer.wait(timeout=5),0,producer.stderr.read())
            # The suffix corroborates only the actual historical choice, on
            # the existing historical path; it never enters the prior verdict.
            report=replay_samples(collect_samples(self.path,schema_version=2))
            self.assertTrue(report['samples'][0]['cast_evidence']['complete_observed_interaction'])
        finally:
            for process in (consumer,producer):
                if process.poll() is None:process.kill()
                process.wait(timeout=5)
                for pipe in (process.stdin,process.stdout,process.stderr):
                    if pipe is not None:pipe.close()
            reader.join(2)
