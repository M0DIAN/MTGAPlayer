"""Decision-time target checks on a field-projected real Cast interaction."""
import copy
import json
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import unittest

from mtgaplayer.cli import replay
from mtgaplayer.choice_validation import validate_proposed_choice, load_proposal
from mtgaplayer.decision_consumer import EXECUTION
from mtgaplayer.raw_log import RawReducer
from mtgaplayer.semantic_samples import collect_samples, replay_samples, SampleError

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT/'tests/fixtures/player_log_single_target.jsonl'


class SingleTargetChoiceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name); self.path = self.root/'targets.log'
        self.rows = [json.loads(r) for r in FIXTURE.read_text().splitlines()]
        self.write(self.rows[:106])
        self.state = self.current()
        target = self.state['legal_action_space']['request_parameters']['targets']
        self.target = target
        self.proposal = {'request_identity': self.state['binding'], 'proposed_final_target_set': {
            'source_object_ref': target['source_object_ref'], 'target_idx': target['target_idx'],
            'object_refs': [target['entries'][3]['object_ref']]}}

    def write(self, rows):
        self.path.write_text(''.join(json.dumps(r)+'\n' for r in rows))

    def append(self, rows):
        with self.path.open('a') as out:out.write(''.join(json.dumps(r)+'\n' for r in rows))

    def current(self, version=5):
        return replay(self.path, format='player-log', decision_state=True, decision_state_version=version)['decision_state']

    def result(self, proposal=None, state=None):
        result = validate_proposed_choice(state or self.state, proposal or self.proposal)
        self.assertTrue(all(result[k] is False for k in EXECUTION))
        return result

    def body(self, rows, line=106):
        return rows[line-1]['greToClientEvent']['greToClientMessages'][0]['selectTargetsReq']['targets'][0]

    def test_real_prefix_final_set_known_constraints_before_any_response(self):
        self.assertEqual(len(self.path.read_text().splitlines()),106)
        self.assertIsNone(self.target['selected_count'])
        self.assertNotEqual(self.target['ability_grp_ref'], self.target['targeting_ability_grp_ref'])
        self.assertEqual((self.target['min_targets'],self.target['max_targets']),(1,1))
        self.assertEqual(len(self.target['entries']),4)
        for row in self.target['entries']:
            proposed=copy.deepcopy(self.proposal); proposed['proposed_final_target_set']['object_refs']=[row['object_ref']]
            result=self.result(proposed)
            self.assertEqual(result['known_constraints'],'verified_known_constraints')
            self.assertIn('incremental_ui_reachability_and_additional_constraints_unverified',result['reasons'])
        self.assertIsNone(self.state['legal_action_space']['choice_graph'])
        self.assertFalse(self.state['legal_action_space']['request_parameters']['historical_response_used'])

    def test_count_membership_duplicate_and_wrong_binding_are_distinct(self):
        for refs in ([],[999999],[r['object_ref'] for r in self.target['entries'][:2]],
                     [self.target['entries'][0]['object_ref']]*2):
            p=copy.deepcopy(self.proposal);p['proposed_final_target_set']['object_refs']=refs
            self.assertEqual(self.result(p)['known_constraints'],'violated_known_constraints')
        for mutate in (lambda p:p['request_identity'].update(request_id=999999),
            lambda p:p['proposed_final_target_set'].update(target_idx=2),
            lambda p:p['proposed_final_target_set'].update(source_object_ref=999999)):
            p=copy.deepcopy(self.proposal);mutate(p)
            self.assertEqual(self.result(p)['known_constraints'],'insufficient_evidence')

    def test_missing_domain_bounds_or_selected_count_never_fills_defaults(self):
        for field in ('targets','minTargets','maxTargets'):
            rows=copy.deepcopy(self.rows[:106]);self.body(rows).pop(field);self.write(rows)
            state=self.current();r=self.result(state=state)
            self.assertEqual(r['known_constraints'],'insufficient_evidence')
        self.assertIsNone(self.target['selected_count'])
        self.assertEqual(self.result()['known_constraints'],'verified_known_constraints')

    def test_increment_consumes_old_request_new_domain_incomplete_final_submit_consumes_new(self):
        for version in (1,2,3,4,5):
            self.write(self.rows[:107]);s=self.current(version)
            self.assertEqual(s['status'],'state_observed_without_request')
            self.write(self.rows[:109]);s=self.current(version)
            self.assertEqual(s['binding']['game_state_id'],102)
            if version==5:
                target=s['legal_action_space']['request_parameters']['targets']
                self.assertEqual(target['selected_count'],1)
                self.assertEqual(target['entries'][0]['legal_action'],'SelectAction_Unselect')
                proposed=copy.deepcopy(self.proposal);proposed['request_identity']=s['binding']
                result=self.result(proposed,state=s)
                self.assertEqual(result['known_constraints'],'insufficient_evidence')
                self.assertIn('complete_current_select_domain_not_observed',result['reasons'])
            else:self.assertNotIn('request_parameters',s['legal_action_space'])
            self.write(self.rows[:110]);s=self.current(version)
            self.assertEqual(s['status'],'state_observed_without_request')
            self.assertIsNone(s['binding']['request_id'])

    def test_terminal_requires_exact_current_pair_and_no_extra_or_mixed_payload(self):
        for change in ('wrong_id','wrong_state','wrong_type','extra_body','mixed','replaced'):
            reducer=RawReducer();reducer.reset(1)
            for row in self.rows[:109]:reducer.apply(row)
            terminal=copy.deepcopy(self.rows[109])
            if change=='wrong_id':terminal['payload']['respId']+=1
            if change=='wrong_state':terminal['payload']['gameStateId']-=1
            if change=='wrong_type':terminal['payload']['type']='ClientMessageType_SubmitAttackersReq'
            if change=='extra_body':terminal['payload']['selectTargetsResp']={}
            if change=='mixed':terminal['greToClientEvent']={'greToClientMessages':[]}
            if change=='replaced':
                replacement=copy.deepcopy(self.rows[108]);replacement['greToClientEvent']['greToClientMessages'][0]['msgId']+=100
                reducer.apply(replacement)
            ident=reducer.request['id'];reducer.apply(terminal)
            self.assertIsNotNone(reducer.request,change)
            self.assertEqual(reducer.request['id'],ident,change)
        reducer.apply(self.rows[109])  # old terminal cannot consume a replacement
        self.assertIsNotNone(reducer.request)

    def test_schema4_existing_export_replay_links_only_actual_choice_and_public_result(self):
        self.write(self.rows)
        artifact=collect_samples(self.path,schema_version=4,max_samples=256)
        self.assertEqual(artifact['counts']['exported'],3)
        reports=replay_samples(artifact)['samples']
        self.assertTrue(reports[0]['cast_evidence']['cast_on_stack_observed'])
        self.assertEqual(reports[0]['cast_evidence']['known_cost_and_predictive_payment'],'insufficient_evidence')
        self.assertTrue(reports[1]['target_evidence']['linked_cast_origin'])
        final=reports[2]['target_evidence']
        for key in ('linked_cast_origin','linked_previous_actual_selection','final_submission_observed',
                    'targets_submitted_annotation_observed','source_resolution_observed','actual_selected_public_departure_observed'):
            self.assertTrue(final[key],key)
        self.assertEqual(final['return_causation'],'unverified')
        self.assertFalse(final['complete_legality_verified'])
        # A different current proposal can satisfy local constraints, but the
        # unmodified suffix corroborates only the recorded player's selection.
        different=copy.deepcopy(self.proposal)
        different['proposed_final_target_set']['object_refs']=[self.target['entries'][0]['object_ref']]
        self.assertEqual(self.result(different)['known_constraints'],'verified_known_constraints')
        selected=artifact['samples'][2]['request']['payload']['entries'][0]['object_ref']
        self.assertEqual(final['literal_current_selected_refs'],[selected])
        self.assertEqual(selected,artifact['samples'][1]['response']['payload']['entries'][0]['object_ref'])
        output=self.root/'target-v4.json'
        run=subprocess.run([sys.executable,'-m','mtgaplayer','export-semantic-samples',str(self.path),
            '--schema-version','4','--output',str(output)],capture_output=True,text=True,timeout=8)
        self.assertEqual(run.returncode,0,run.stderr)
        run=subprocess.run([sys.executable,'-m','mtgaplayer','replay-semantic-samples',str(output)],capture_output=True,text=True,timeout=8)
        self.assertEqual(run.returncode,0,run.stderr)
        for version in (1,2,3):
            old=collect_samples(self.path,schema_version=version,max_samples=256)
            self.assertFalse(any(s['request']['kind']=='select_targets' for s in old['samples']))

    def test_portable_forgery_and_missing_current_selection(self):
        self.write(self.rows);artifact=collect_samples(self.path,schema_version=4,max_samples=256)
        for change in ('response_domain','trace_predecessor','source_domain'):
            bad=copy.deepcopy(artifact)
            if change=='response_domain':bad['samples'][1]['response']['payload']['entries'][0]['object_ref']=999999
            if change=='trace_predecessor':bad['samples'][2]['trace']['states'][0]['previous_state_ref']=999999
            if change=='source_domain':bad['samples'][1]['request']['payload']['source_object_ref']=999999
            with self.assertRaises(SampleError):replay_samples(bad)
        bad=copy.deepcopy(artifact);bad['samples'][2]['request']['payload']['selected_count']=None
        final=replay_samples(bad)['samples'][2]['target_evidence']
        self.assertIsNone(final['literal_current_selected_refs'])
        self.assertFalse(final['linked_previous_actual_selection'])
        self.assertFalse(final['actual_selected_public_departure_observed'])

    def test_unknown_or_nonpublic_targets_reject_whole_profile_without_leak(self):
        for mutate in (lambda slot:slot['targets'][0].update(targetInstanceId=999999),
            lambda slot:slot.update(secret='PRIVATE_SENTINEL'),
            lambda slot:slot['targets'].append(copy.deepcopy(slot['targets'][0]))):
            rows=copy.deepcopy(self.rows[:106]);mutate(self.body(rows));self.write(rows)
            state=self.current()
            self.assertIsNone(state['legal_action_space']['request_parameters'])
            self.assertNotIn('PRIVATE_SENTINEL',json.dumps(state))
        proposal_path=self.root/'proposal.json';proposal_path.write_text(json.dumps(self.proposal))
        self.assertEqual(load_proposal(proposal_path),self.proposal)
        schema=json.loads((ROOT/'schemas/decision-state.v5.schema.json').read_text())
        self.assertIn('targets',schema['$defs']['requestParameters']['properties'])
        self.assertFalse(schema['$defs']['singleSlotTargets']['additionalProperties'])

    def test_actual_watch_consumer_pipe_checks_before_response_then_revokes_and_rebinds(self):
        self.write(self.rows[:105]);proposal_path=self.root/'proposal.json';proposal_path.write_text(json.dumps(self.proposal))
        producer=subprocess.Popen([sys.executable,'-m','mtgaplayer','watch',str(self.path),
            '--decision-events','--decision-state-version','5','--interval','.025','--samples','120'],
            stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        consumer=subprocess.Popen([sys.executable,'-m','mtgaplayer','consume-events','--validate-choice',str(proposal_path)],
            stdin=producer.stdout,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        producer.stdout.close();lines=queue.Queue()
        def read():
            for line in consumer.stdout:lines.put(json.loads(line))
            lines.put(None)
        reader=threading.Thread(target=read,daemon=True);reader.start()
        def until(predicate):
            for _ in range(60):
                row=lines.get(timeout=8);self.assertIsNotNone(row)
                if predicate(row):return row
            self.fail('expected diagnostic not observed')
        try:
            until(lambda r:r['consumer_status']=='OBSERVING')
            self.append(self.rows[105:106])
            verdict=until(lambda r:r['choice_validation']['known_constraints']=='verified_known_constraints')
            self.assertEqual(len(self.path.read_text().splitlines()),106)
            self.assertIsNotNone(verdict['choice_validation']['source_snapshot_ref'])
            self.append(self.rows[106:107]);until(lambda r:r['consumer_status']=='INVALIDATED')
            self.append(self.rows[107:109])
            rebound=until(lambda r:r['consumer_status']=='OBSERVING')
            self.assertEqual(rebound['choice_validation']['known_constraints'],'insufficient_evidence')
            self.append(self.rows[109:110]);until(lambda r:r['consumer_status']=='INVALIDATED')
            self.append(self.rows[110:])
            while True:
                row=lines.get(timeout=8)
                if row is None:break
                self.assertEqual(row['choice_validation']['known_constraints'],'insufficient_evidence')
            self.assertEqual(consumer.wait(timeout=5),0,consumer.stderr.read())
            self.assertEqual(producer.wait(timeout=5),0,producer.stderr.read())
        finally:
            for process in (consumer,producer):
                if process.poll() is None:process.kill()
                process.wait(timeout=5)
                for pipe in (process.stdin,process.stdout,process.stderr):
                    if pipe is not None:pipe.close()
            reader.join(2)
