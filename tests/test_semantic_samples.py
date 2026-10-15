"""Value-preserving episodes: real SelectN, explicitly synthetic action bodies."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from mtgaplayer.semantic_samples import (collect_samples, export_samples, replay_samples,
    load_and_replay, SampleError, MAX_BYTES)
from test_response_evidence import action_request, reply, source_rows, save
from test_decision_advisor import PASS, PLAY


def prefix():
    # Synthetic episodes reuse real state rows, excluding the historical
    # Mulligan response so their counts describe only the injected pairs.
    return [row for row in source_rows()[:9] if 'payload' not in row]


def next_request(actions, msg_id=38):
    # action_request includes the original Diff7..23 prefix. Replaying that
    # prefix after state23 is a real continuity break, not a next request.
    messages = action_request(actions, msg_id=msg_id)['greToClientEvent']['greToClientMessages']
    return {'greToClientEvent': {'greToClientMessages': [messages[-1]]}}


class SemanticSampleTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path, self.output = self.root/'source.jsonl', self.root/'episode.json'

    def real(self):
        fixture = Path(__file__).parent/'fixtures'
        self.path.write_text((fixture/'player_log_selectn.jsonl').read_text() +
            (fixture/'player_log_selectn_response.jsonl').read_text(), encoding='utf-8')

    def synthetic(self, actions=None, chosen=None, tail=()):
        actions = [PASS, PLAY] if actions is None else actions
        chosen = actions[-1] if chosen is None else chosen
        rows = prefix() + [action_request(copy.deepcopy(actions)),
            reply(details={'actions':[copy.deepcopy(chosen)]}), *copy.deepcopy(tail)]
        save(self.path, rows)

    def cli(self, *arguments):
        result = subprocess.run([sys.executable,'-m','mtgaplayer',*map(str,arguments)],
            capture_output=True,text=True,timeout=10)
        return result, json.loads(result.stdout)

    def diff(self, version=24, previous=23):
        return {'greToClientEvent':{'greToClientMessages':[{
            'type':'GREMessageType_GameStateMessage','systemSeatIds':[1],
            'gameStateMessage':{'type':'GameStateType_Diff','gameStateId':version,
                                'prevGameStateId':previous}}]}}

    def test_real_selectn_export_and_portable_cli_replay_preserve_specific_choice(self):
        self.real()
        run, summary = self.cli('export-semantic-samples',self.path,'--output',self.output,
                                '--origin','retained_scrubbed_real')
        self.assertEqual(run.returncode,0,run.stderr)
        self.assertEqual(summary['counts']['exported'],1)
        self.assertGreater(summary['counts']['unsupported_pairs'],0)  # real actions bodies were removed
        doc=json.loads(self.output.read_text())
        sample=doc['samples'][0]
        req=sample['request']['payload']; chosen=sample['response']['payload']['selected_object_refs']
        self.assertEqual((len(req['offered_object_refs']),req['max_sel'],req['min_sel']),(4,2,None))
        self.assertEqual(chosen,[req['offered_object_refs'][0],req['offered_object_refs'][3]])
        visible={o['object_ref'] for o in sample['before']['objects']}
        self.assertTrue(set(req['offered_object_refs']).isdisjoint(visible))  # opaque request references
        self.assertEqual(sample['successor']['status'],'not_observed')  # actual fixture has no later state
        second, replay=self.cli('replay-semantic-samples',self.output)
        self.assertEqual(second.returncode,0,second.stderr)
        self.assertEqual(replay['samples'][0]['selected_option_positions'],[0,3])
        self.assertFalse(replay['raw_source_auth_revalidated'])
        self.assertFalse(doc['projection']['raw_equivalent'])
        self.assertIn('prompt_payloads',doc['projection']['omitted_categories'])
        self.assertTrue(all(v is False for v in doc['execution'].values()))
        text=self.output.read_text()
        for secret in ('fixture-match','fixture-user','HIDDEN_SENTINEL','authenticateResponse','"prompt":','timestamp',str(self.path)):
            self.assertNotIn(secret,text)

    def test_synthetic_action_identities_flags_and_exact_empty_parameter_shapes(self):
        for kind in ('ActionType_Play','ActionType_Cast','ActionType_Activate','ActionType_Activate_Mana'):
            chosen=copy.deepcopy(PLAY)
            chosen['actionType']=kind
            if kind != 'ActionType_Play':
                chosen.update(manaCost=[],targets=[],manaSelections=[],manaPaymentOptions=[],
                    autoTapSolution={'autoTapActions':[]},isBatchable=False)
            if kind in ('ActionType_Activate','ActionType_Activate_Mana'):
                chosen.update(abilityGrpId=0,uniqueAbilityId=0)
            self.synthetic([PASS,chosen],tail=[self.diff()])
            doc=collect_samples(self.path,origin='synthetic')
            self.assertEqual(doc['counts']['exported'],1)
            sample=doc['samples'][0]
            selected=sample['response']['payload']['action']
            self.assertIs(selected['flags']['shouldStop'],False)
            self.assertIn('facetId',selected['identifier_refs'])
            self.assertEqual(selected,sample['request']['payload']['actions'][1])
            self.assertEqual(sample['successor']['status'],'continuous_state_observed')
            self.assertEqual(replay_samples(doc)['samples'][0]['selected_action_position'],1)
        self.synthetic([PASS],chosen=PASS)
        self.assertEqual(replay_samples(collect_samples(self.path))['samples'][0]['selected_action_position'],0)

    def test_nonempty_or_unknown_nested_values_are_whole_unsupported_and_private(self):
        base=dict(PLAY,actionType='ActionType_Cast')
        variants=[]
        for key in ('targets','manaCost','manaSelections','manaPaymentOptions'):
            variants.append(dict(base,**{key:[{'PRIVATE_KEY':'PRIVATE_VALUE'}]}))
        variants.extend((dict(base,autoTapSolution={'autoTapActions':[],'PRIVATE_KEY':'PRIVATE_VALUE'}),
            dict(base,autoTapSolution={}),dict(base,PRIVATE_KEY='PRIVATE_VALUE'),
            dict(base,facetId=True),dict(base,shouldStop=0),dict(base,actionType='PRIVATE_VALUE')))
        for chosen in variants:
            self.synthetic([PASS,chosen],chosen=PASS)
            doc=collect_samples(self.path)
            self.assertEqual(doc['counts']['exported'],0)
            self.assertEqual(doc['counts']['unsupported_pairs'],1)
            self.assertNotIn('PRIVATE',json.dumps(doc))
        self.synthetic()
        rows=[json.loads(line) for line in self.path.read_text().splitlines()]
        rows[-1]['payload']['performActionResp']['PRIVATE_KEY']='PRIVATE_VALUE'
        save(self.path,rows)
        self.assertEqual(collect_samples(self.path)['counts']['exported'],0)

    def test_pair_gate_supersession_conflict_broadcast_and_record_ordering(self):
        for seats in ([2],[1,2],[True],[1.0]):
            save(self.path,prefix()+[action_request([PASS],recipient=seats),reply(details={'actions':[PASS]})])
            self.assertEqual(collect_samples(self.path)['counts']['exported'],0)
        for state_id,request_id in ((22,37),(23,999)):
            save(self.path,prefix()+[action_request([PASS]),
                 reply(request_id,state_id,{'actions':[PASS]})])
            self.assertEqual(collect_samples(self.path)['counts']['exported'],0)
        first=action_request([PASS]); conflict=next_request([PLAY],msg_id=37)
        save(self.path,prefix()+[first,conflict,reply(details={'actions':[PASS]})])
        self.assertEqual(collect_samples(self.path)['counts']['exported'],0)
        replacement=next_request([PASS],msg_id=38)
        save(self.path,prefix()+[first,replacement,reply(details={'actions':[PASS]})])
        self.assertEqual(collect_samples(self.path)['counts']['exported'],0)
        self.synthetic()
        with self.path.open('a') as stream: stream.write(json.dumps(reply(details={'actions':[PLAY]}))+'\n')
        self.assertEqual(collect_samples(self.path)['counts']['exported'],1)
        self.synthetic()
        rows=[json.loads(line) for line in self.path.read_text().splitlines()]
        rows[-1].update(self.diff())
        save(self.path,rows)
        self.assertEqual(collect_samples(self.path)['unsupported_reasons'],[{'reason':'mixed_record_ordering','count':1}])

    def test_successor_scope_interrupt_full_and_next_request_are_not_success(self):
        for tail,status in (([self.diff()],'continuous_state_observed'),
            ([self.diff(25,999)],'interrupted'),
            ([next_request([PASS])],'next_request_observed')):
            self.synthetic(tail=tail)
            self.assertEqual(collect_samples(self.path)['samples'][0]['successor']['status'],status)
        # A genuine Full reconstruction is a new baseline, not continuous outcome evidence.
        full=copy.deepcopy(source_rows()[2])
        gs=next(m['gameStateMessage'] for m in full['greToClientEvent']['greToClientMessages'] if 'gameStateMessage' in m)
        gs['gameStateId']=24
        self.synthetic(tail=[full])
        self.assertEqual(collect_samples(self.path)['samples'][0]['successor']['status'],'full_baseline_not_continuous')
        room=copy.deepcopy(source_rows()[1])
        room['matchGameRoomStateChangedEvent']['gameRoomInfo']['gameRoomConfig']['matchId']='new-match'
        self.synthetic(tail=[room])
        self.assertEqual(collect_samples(self.path)['samples'][0]['successor']['status'],'interrupted')

    def test_file_bounds_no_overwrite_atomic_race_and_source_change(self):
        self.synthetic()
        before=self.path.read_bytes()
        export_samples(self.path,self.output)
        artifact=self.output.read_bytes()
        with self.assertRaisesRegex(SampleError,'output_already_exists'):
            export_samples(self.path,self.output)
        self.assertEqual(self.output.read_bytes(),artifact)
        with self.assertRaises(ValueError): collect_samples(self.path,max_history_bytes=1)
        with self.path.open('a') as stream: stream.write('{"partial":')
        run,error=self.cli('export-semantic-samples',self.path,'--output',self.root/'incomplete.json')
        self.assertEqual(run.returncode,1)
        self.assertEqual(error['error'],'source_framing_incomplete')
        self.assertFalse((self.root/'incomplete.json').exists())
        self.path.write_bytes(before)
        original_poll=__import__('mtgaplayer.raw_log',fromlist=['RawFollower']).RawFollower.poll
        def changed(follower):
            result=original_poll(follower)
            with self.path.open('a') as stream: stream.write(' ')
            return result
        with patch('mtgaplayer.semantic_samples.RawFollower.poll',new=changed):
            with self.assertRaisesRegex(SampleError,'source_changed'): collect_samples(self.path)
        self.path.write_bytes(before)
        with patch('mtgaplayer.semantic_samples.os.link',side_effect=FileExistsError):
            with self.assertRaises(FileExistsError): export_samples(self.path,self.root/'race.json')
        self.assertEqual(list(self.root.glob('.semantic-sample-*')),[])
        self.assertEqual(self.path.read_bytes(),before)

    def test_portable_contract_rejects_forged_choices_types_authority_and_size(self):
        self.real(); original=collect_samples(self.path)
        for mutate in (
            lambda d:d['samples'][0]['response']['payload'].update(selected_object_refs=[True]),
            lambda d:d['samples'][0]['response']['payload'].update(selected_object_refs=[999999]),
            lambda d:d['samples'][0]['provenance'].update(private_auth_revalidated_by_replay=True),
            lambda d:d['execution'].update(input_sent=True),
            lambda d:d['samples'].__setitem__(0,None),
            lambda d:d['counts'].update(exported=True),
        ):
            bad=copy.deepcopy(original); mutate(bad)
            with self.assertRaises(SampleError): replay_samples(bad)
        self.output.write_text('{"schema_version":1,"schema_version":2}')
        with self.assertRaises(SampleError): load_and_replay(self.output)
        self.output.write_bytes(b' '*(MAX_BYTES+1))
        with self.assertRaises(SampleError): load_and_replay(self.output)

    def test_sample_limit_omissions_and_identifier_namespaces_are_explicit(self):
        rows=prefix()
        for ident in (37,38):
            frame=action_request([PASS,PLAY]) if ident == 37 else next_request([PASS,PLAY],msg_id=ident)
            rows.extend([frame,reply(ident,23,{'actions':[PLAY]})])
        save(self.path,rows)
        doc=collect_samples(self.path,max_samples=1)
        self.assertEqual(doc['counts'],{'matched_pairs':2,'exported':1,'sample_limit_omissions':1,'unsupported_pairs':0})
        self.assertEqual(replay_samples(doc)['samples'][0]['selected_action_position'],1)
        self.assertEqual(doc['samples'][0]['successor']['status'],'next_request_observed')
