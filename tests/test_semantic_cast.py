"""Real retained generic-one Cast and discriminating synthetic mutations."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from mtgaplayer.raw_log import RawFollower, RawReducer
from mtgaplayer.semantic_samples import collect_samples, replay_samples, SampleError

FIXTURE=Path(__file__).parent/'fixtures'/'player_log_cast_generic_one.jsonl'


class SemanticCastTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name);self.path=self.root/'source.jsonl'
        self.rows=[json.loads(line) for line in FIXTURE.read_text().splitlines()]

    def save(self):
        self.path.write_text(''.join(json.dumps(row)+'\n' for row in self.rows),encoding='utf-8')

    def collect(self):
        self.save()
        return collect_samples(self.path,schema_version=2,origin='retained_scrubbed_real')

    def request(self):
        return next(m for row in self.rows for m in row.get('greToClientEvent',{}).get('greToClientMessages',[])
                    if 'actionsAvailableReq' in m)

    def response(self):
        return next(row['payload'] for row in self.rows if 'performActionResp' in row.get('payload',{}))

    def state(self, version):
        return next(m['gameStateMessage'] for row in self.rows for m in row.get('greToClientEvent',{}).get('greToClientMessages',[])
                    if m.get('gameStateMessage',{}).get('gameStateId')==version)

    def evidence(self, document=None):
        d=self.collect() if document is None else document
        return replay_samples(d)['samples'][0]['cast_evidence']

    def test_real_complete_cast_preserves_all_six_actions_and_specific_payment(self):
        d=self.collect();s=d['samples'][0];report=replay_samples(d)
        self.assertEqual(d['counts']['exported'],1)
        self.assertEqual(report['samples'][0]['selected_action_position'],1)
        actions=s['request']['payload']['actions']
        self.assertEqual(len(actions),6)
        self.assertEqual([a['action_type'] for a in actions],['ActionType_Cast']*3+['ActionType_Activate_Mana','ActionType_Pass','ActionType_FloatMana'])
        self.assertEqual(actions[1],s['response']['payload']['action'])
        self.assertEqual(actions[1]['parameters']['manaCost'],[{'color':['ManaColor_Generic'],'count':1}])
        self.assertNotIn('autoTapSolution',actions[0]['parameters'])  # absent, not an illegality claim
        tap=actions[1]['parameters']['autoTapSolution']['autoTapActions'][0]
        self.assertEqual(tap['manaPaymentOption'],actions[3]['parameters']['manaPaymentOptions'][0])
        self.assertEqual(tap['manaPaymentOption']['mana'][0]['specs'],[{'type':'ManaSpecType_Predictive'}])
        self.assertEqual(s['response']['payload']['auto_pass_priority'],'AutoPassPriority_Yes')
        self.assertEqual(len(s['trace']['states']),3)
        self.assertEqual(s['trace']['status'],'eof')
        self.assertEqual(s['successor']['snapshot'],s['trace']['states'][0]['snapshot'])
        e=self.evidence(d)
        self.assertEqual(e['known_cost_and_predictive_payment'],'verified_known_constraints')
        for key in ('cast_submission_observed','cast_on_stack_observed','resolution_to_battlefield_observed','complete_observed_interaction'):self.assertIs(e[key],True)
        self.assertTrue(all(value is False for value in report['execution'].values()))
        self.assertFalse(report['raw_source_auth_revalidated'])
        self.assertFalse(report['complete_legality_verified'])
        # Existing raw reducer rebuilds the actual state prefix, no synthetic Full.
        f=RawFollower(FIXTURE);_,rows=f.poll();r=RawReducer();r.reset(f.generation)
        for row in rows:r.apply(row)
        self.assertIsNone(r.error);self.assertEqual(r.version,12)
        visible=r.document()['current']['objects']
        self.assertTrue(any(o['card_id']==97989 and o['zone']=='ZoneType_Battlefield' for o in visible))

    def test_raw_state_messages_require_explicit_observer_opt_in(self):
        for enabled in (False, True):
            events=[]
            r=RawReducer(observer=lambda e,d:events.append(d) if e=='state_accepted' else None,
                         include_state_messages=enabled)
            r.reset(1)
            for row in self.rows:r.apply(copy.deepcopy(row))
            self.assertIsNone(r.error)
            self.assertTrue(events)
            self.assertTrue(all(('message' in d) is enabled for d in events))
            if enabled:
                self.assertEqual([d['message']['gameStateId'] for d in events],list(range(1,13)))

    def test_cli_opt_in_and_default_v1_and_fixture_privacy(self):
        self.save();out=self.root/'v2.json'
        run=subprocess.run([sys.executable,'-m','mtgaplayer','export-semantic-samples',str(self.path),'--output',str(out),'--schema-version','2'],capture_output=True,text=True,timeout=10)
        self.assertEqual(run.returncode,0,run.stderr)
        replay=subprocess.run([sys.executable,'-m','mtgaplayer','replay-semantic-samples',str(out)],capture_output=True,text=True,timeout=10)
        self.assertEqual(replay.returncode,0,replay.stderr)
        self.assertEqual(json.loads(replay.stdout)['samples'][0]['selected_action_position'],1)
        default=collect_samples(self.path)
        self.assertEqual(default['schema_version'],'mtgaplayer.semantic-samples.v1')
        self.assertEqual(default['counts']['exported'],0)
        for row in self.rows:
            for m in row.get('greToClientEvent',{}).get('greToClientMessages',[]):
                for o in m.get('gameStateMessage',{}).get('gameObjects',[]):
                    self.assertNotIn('name',o);self.assertNotIn('overlayGrpId',o)
                    if o.get('ownerSeatId')==2 and o.get('visibility')!='Visibility_Public':self.assertNotIn('grpId',o)
        text=out.read_text()
        for secret in ('fixture-mp34','authenticateResponse','reservedPlayers','"prompt":','timestamp',str(self.path)):self.assertNotIn(secret,text)

    def test_unknown_nested_payload_rejects_whole_pair_without_value_leakage(self):
        original=copy.deepcopy(self.rows)
        for mutate in (
            lambda a:a['autoTapSolution'].update(secret='PRIVATE_SENTINEL'),
            lambda a:a['autoTapSolution']['autoTapActions'][0]['manaPaymentOption']['mana'][0].update(secret='PRIVATE_SENTINEL'),
            lambda a:a.update(targets=[{'targetInstanceId':123,'secret':'PRIVATE_SENTINEL'}]),
            lambda a:a['manaCost'][0].update(count=True),
            lambda a:a['autoTapSolution']['autoTapActions'][0]['manaPaymentOption']['mana'][0].update(specs=[{'type':'PRIVATE_SENTINEL'}]),
        ):
            self.rows=copy.deepcopy(original);mutate(self.request()['actionsAvailableReq']['actions'][1])
            d=self.collect();self.assertEqual(d['counts']['exported'],0)
            self.assertNotIn('PRIVATE_SENTINEL',json.dumps(d))

    def test_unknown_missing_payment_and_inconsistent_payment_are_different(self):
        original=copy.deepcopy(self.rows)
        self.request()['actionsAvailableReq']['actions'][1].pop('autoTapSolution')
        self.response()['performActionResp']['actions'][0].pop('autoTapSolution')
        self.assertEqual(self.evidence()['known_cost_and_predictive_payment'],'insufficient_evidence')
        self.rows=copy.deepcopy(original)
        self.response()['performActionResp']['actions'][0]['autoTapSolution']['autoTapActions'][0]['manaPaymentOption']['mana'][0]['count']=2
        self.assertEqual(self.evidence()['known_cost_and_predictive_payment'],'violated_known_constraints')
        self.rows=copy.deepcopy(original)
        self.response()['performActionResp']['autoPassPriority']='AutoPassPriority_Unsupported'
        self.assertEqual(self.collect()['counts']['exported'],0)

    def test_wrong_pair_and_state_gap_do_not_claim_complete_interaction(self):
        original=copy.deepcopy(self.rows)
        self.response()['respId']+=1
        self.assertEqual(self.collect()['counts']['exported'],0)
        self.rows=copy.deepcopy(original);self.state(12)['prevGameStateId']=9999
        e=self.evidence()
        self.assertTrue(e['cast_on_stack_observed']);self.assertFalse(e['resolution_to_battlefield_observed'])
        self.assertFalse(e['complete_observed_interaction'])
        self.rows=copy.deepcopy(original)
        self.rows.append({'greToClientEvent':{'greToClientMessages':[{'type':'GREMessageType_GameStateMessage','systemSeatIds':[1],
            'gameStateMessage':{'type':'GameStateType_Diff','gameStateId':99,'prevGameStateId':9999}}]}})
        d=self.collect();e=self.evidence(d)
        self.assertEqual(d['samples'][0]['trace']['status'],'interrupted')
        self.assertTrue(e['cast_on_stack_observed']);self.assertTrue(e['resolution_to_battlefield_observed'])
        self.assertFalse(e['complete_observed_interaction'])

    def test_id_migration_resolution_and_trace_bounds_are_independent(self):
        original=copy.deepcopy(self.rows)
        self.state(10)['annotations']=[a for a in self.state(10)['annotations'] if a['type']!=['AnnotationType_ObjectIdChanged']]
        self.assertFalse(self.evidence()['cast_on_stack_observed'])
        self.rows=copy.deepcopy(original)
        self.state(12)['annotations']=[a for a in self.state(12)['annotations'] if a['type']!=['AnnotationType_ResolutionComplete']]
        e=self.evidence();self.assertTrue(e['cast_on_stack_observed']);self.assertFalse(e['resolution_to_battlefield_observed'])
        self.rows=copy.deepcopy(original)
        with patch('mtgaplayer.semantic_cast.TRACE_LIMIT',2):
            d=self.collect();e=self.evidence(d)
        self.assertEqual(d['samples'][0]['trace']['status'],'limit_reached')
        self.assertTrue(d['samples'][0]['trace']['truncated']);self.assertTrue(e['cast_on_stack_observed'])
        self.assertFalse(e['complete_observed_interaction'])
        self.rows=copy.deepcopy(original)
        room=copy.deepcopy(self.rows[1]);room['matchGameRoomStateChangedEvent']['gameRoomInfo']['gameRoomConfig']['matchId']='different-match'
        self.rows.append(room)
        d=self.collect();self.assertEqual(d['samples'][0]['trace']['status'],'interrupted')
        self.assertFalse(self.evidence(d)['complete_observed_interaction'])

    def test_payment_confirmation_requires_same_public_source_and_tap_observation(self):
        original=copy.deepcopy(self.rows)
        for mutation in ('delete_paid','wrong_source','untapped'):
            self.rows=copy.deepcopy(original);gs=self.state(10)
            if mutation=='delete_paid':
                gs['annotations']=[a for a in gs['annotations'] if a['type']!=['AnnotationType_ManaPaid']]
            elif mutation=='wrong_source':
                paid=next(a for a in gs['annotations'] if a['type']==['AnnotationType_ManaPaid'])
                paid['affectorId']=self.response()['performActionResp']['actions'][0]['instanceId']
            else:
                payment=self.response()['performActionResp']['actions'][0]['autoTapSolution']['autoTapActions'][0]['instanceId']
                next(o for o in gs['gameObjects'] if o['instanceId']==payment)['isTapped']=False
            e=self.evidence()
            self.assertEqual(e['known_cost_and_predictive_payment'],'verified_known_constraints')
            self.assertTrue(e['cast_on_stack_observed']);self.assertTrue(e['resolution_to_battlefield_observed'])
            self.assertFalse(e['payment_path_observed']);self.assertFalse(e['complete_observed_interaction'])

    def test_predictive_mana_aliases_are_request_scoped_and_trace_next_request_bound(self):
        request=copy.deepcopy(self.request());response=copy.deepcopy(self.response())
        request.update(msgId=100,gameStateId=12);response.update(respId=100,gameStateId=12)
        self.rows.extend([{'greToClientEvent':{'greToClientMessages':[request]}},{'payload':response}])
        d=self.collect();self.assertEqual(len(d['samples']),2)
        first,second=d['samples']
        a,b=(s['response']['payload']['action'] for s in (first,second))
        am=a['parameters']['autoTapSolution']['autoTapActions'][0]
        bm=b['parameters']['autoTapSolution']['autoTapActions'][0]
        self.assertEqual(am['instanceId'],bm['instanceId'])
        self.assertEqual(am['abilityGrpId'],bm['abilityGrpId'])
        self.assertNotEqual(am['manaPaymentOption']['mana'][0]['manaId'],bm['manaPaymentOption']['mana'][0]['manaId'])
        self.assertEqual(first['trace']['next_request_ref'],second['identity']['request_ref'])
        bad=copy.deepcopy(d)
        bad['samples'][0]['successor']['snapshot']['turn']['turnNumber']+=1
        with self.assertRaises(SampleError):replay_samples(bad)

    def test_unreviewed_annotation_and_portable_forgery_do_not_create_facts(self):
        self.state(10)['annotations'][0]['secret']='PRIVATE_SENTINEL'
        d=self.collect()
        self.assertNotIn('PRIVATE_SENTINEL',json.dumps(d));self.assertFalse(self.evidence(d)['complete_observed_interaction'])
        self.rows=[json.loads(line) for line in FIXTURE.read_text().splitlines()]
        original=self.collect()
        for mutate in (
            lambda s:s['trace']['states'][0].update(previous_state_ref=99999),
            lambda s:s['trace']['states'][0]['facts'][0].update(original_object_ref=99999),
            lambda s:s['trace']['states'][0]['facts'][1].update(destination_zone='ZoneType_Graveyard'),
            lambda s:s['response']['payload']['action']['parameters'].update(secret='PRIVATE_SENTINEL'),
            lambda s:s['trace'].update(truncated=True),
        ):
            bad=copy.deepcopy(original);mutate(bad['samples'][0])
            with self.assertRaises(SampleError):replay_samples(bad)


if __name__=='__main__':unittest.main()
