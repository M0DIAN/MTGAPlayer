"""Real focused combat histories; mutations below are explicitly synthetic."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from mtgaplayer.raw_log import RawReducer
from mtgaplayer.response_evidence import _current_verified_request, _paired_combat_submit, _paired_response
from mtgaplayer.combat_frontier import CombatFrontierObserver
from mtgaplayer.semantic_samples import collect_samples, replay_samples, SampleError
from mtgaplayer.semantic_combat import check_request

FIXTURES=Path(__file__).parent/'fixtures'

class SemanticCombatTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.rows=self.load('blockers');self.path=self.root/'input.log'
    def tearDown(self):self.temp.cleanup()
    def load(self,name):return [json.loads(x) for x in (FIXTURES/f'player_log_combat_{name}.jsonl').read_text().splitlines()]
    def collect(self,rows=None,version=3):
        self.path.write_text(''.join(json.dumps(x)+'\n' for x in (self.rows if rows is None else rows)))
        return collect_samples(self.path,schema_version=version,max_samples=256,origin='retained_scrubbed_real')
    def last(self,document):return replay_samples(document)['samples'][-1]['combat_evidence']
    def ready(self,rows=None,line=43):
        rows=self.rows if rows is None else rows
        observer=CombatFrontierObserver();r=RawReducer(observer=lambda e,d:observer.observe(r,e,d));r.reset(1)
        for e in rows[:line-1]:r.apply(copy.deepcopy(e))
        self.assertIsNone(r.error);self.assertIsNotNone(_current_verified_request(r))
        return r,observer,copy.deepcopy(rows[line-1])
    def message(self,rows,line):return rows[line-1]['greToClientEvent']['greToClientMessages'][0]

    def test_real_complete_request_selection_and_first_public_result(self):
        d=self.collect();sample=d['samples'][-1];e=self.last(d)
        self.assertEqual(sample['request']['kind'],'declare_blockers')
        rows=sample['request']['payload']['blockers']
        self.assertEqual(len(rows),3)
        self.assertTrue(all(r['candidate_attacker_refs'] is None for r in rows))
        self.assertEqual(len(e['selected_configuration']),3)
        self.assertTrue(e['current_request_selection_preserved'])
        self.assertTrue(e['final_submission_observed']);self.assertTrue(e['selected_public_result_observed'])
        self.assertEqual(e['known_capacity_and_membership'],'insufficient_evidence')
        self.assertEqual(e['combat_cost'],'uninterpreted_single_empty_object')
        self.assertEqual(e['complete_combination_validation'],'insufficient_evidence')
        self.assertEqual(len(sample['trace']['states']),1)
        self.assertEqual(sample['trace']['states'][0]['snapshot'],sample['successor']['snapshot'])
        self.assertTrue(all(v is False for v in replay_samples(d)['execution'].values()))
        self.assertFalse(e['complete_legality_verified']);self.assertFalse(e['server_acceptance_verified'])
        # Prefix also includes a real zero-attacker submission: no vacuous confirmation.
        first=replay_samples(d)['samples'][0]['combat_evidence']
        self.assertEqual(first['selected_configuration'],[]);self.assertFalse(first['selected_public_result_observed'])

    def test_real_attack_unselection_not_last_increment_or_union(self):
        rows=self.load('unselect');d=self.collect(rows);s=d['samples'][-1];e=self.last(d)
        all_rows=s['request']['payload']['attackers']
        self.assertEqual(len(all_rows),2);self.assertEqual(len(e['selected_configuration']),1)
        self.assertEqual(e['selected_configuration'][0]['object_ref'],all_rows[0]['object_ref'])
        self.assertIsNone(all_rows[1]['selected_recipient'])
        self.assertTrue(e['selected_public_result_observed'])
        self.assertEqual(e['unobserved_participants'],'unknown')
        # First Diff302 still gives the local player priority; this is not a failure.
        self.assertEqual(s['trace']['states'][0]['snapshot']['turn']['decisionPlayer'],1)

    def test_exact_submit_consumes_once_revokes_frontier_and_never_revives(self):
        r,o,entry=self.ready();before=copy.deepcopy(_current_verified_request(r))
        self.assertIsNotNone(o.current)
        r.apply(entry)
        self.assertIsNone(r.request);self.assertIsNone(o.current)
        self.assertTrue(_paired_combat_submit(r,before,entry['payload']))
        self.assertFalse(_paired_response(r,before,entry['payload'],expected_type=entry['payload']['type']))
        self.assertEqual(r.submitted['confirmation'],'client_submission_only')
        submitted=copy.deepcopy(r.submitted);r.apply(entry);self.assertEqual(r.submitted,submitted)
        r.apply(copy.deepcopy(self.rows[41]));self.assertIsNone(r.request)
        d=self.collect(self.rows[:43]+[entry,copy.deepcopy(self.rows[41])]+self.rows[43:])
        self.assertEqual(sum(s['request']['kind']=='declare_blockers' for s in d['samples']),1)

    def test_submit_fixed_mapping_strict_ids_and_current_identity(self):
        for field,value in [('type','ClientMessageType_SubmitAttackersReq'),('type',{}),('type',[]),
                            ('type','ClientMessageType_AnythingReq'),('respId',True),('respId',10004.0),
                            ('gameStateId',True),('gameStateId',494.0),('gameStateId',493)]:
            with self.subTest(field=field,value=value):
                r,_,entry=self.ready();before=copy.deepcopy(_current_verified_request(r));entry['payload'][field]=value
                r.apply(entry);self.assertIsNotNone(r.request)
                self.assertFalse(_paired_combat_submit(r,before,entry['payload']))
        # Synthetic state/request1 makes True numerically equal; strict typing must still reject.
        for field in ('respId','gameStateId'):
            baseline=copy.deepcopy(self.rows[:3]);self.message(baseline,3)['gameStateMessage']['gameStateId']=1
            req=copy.deepcopy(self.rows[41]);m=self.message([req],1);m['msgId']=m['gameStateId']=1
            r=RawReducer();r.reset(1)
            for e in [*baseline,req]:r.apply(e)
            self.assertIsNone(r.error);self.assertIsNotNone(r.request)
            payload={'type':'ClientMessageType_SubmitBlockersReq','respId':1,'gameStateId':1};payload[field]=True
            r.apply({'payload':payload});self.assertIsNotNone(r.request)
        for change in ('generation','room_seat','superseded','consumed','continuity','binding','conflict','gap'):
            with self.subTest(change=change):
                r,_,entry=self.ready()
                if change=='generation':r.generation+=1
                elif change=='room_seat':r.room_seat=2
                elif change=='superseded':r.superseded.add(r.request['id'])
                elif change=='consumed':r.consumed.add((r.match,r.game,r.request['id']))
                elif change=='continuity':r.request['_continuity_verified']=False
                elif change=='binding':r.request['binding']['self_seat']=2
                elif change=='conflict':r.conflict=True
                else:r._invalidate('state_gap_or_missing_full')
                r.apply(entry);self.assertIsNotNone(r.request)
        r,_,entry=self.ready();entry['greToClientEvent']={'greToClientMessages':[]}
        r.apply(entry);self.assertIsNotNone(r.request)

    def test_unreviewed_cost_unknown_fields_nonplayer_and_false_submit_reject_pair(self):
        original=self.load('unselect')
        for change in ('unknown','cost','recipient','can_submit'):
            rows=copy.deepcopy(original);m=self.message(rows,314);body=m['declareAttackersReq']
            if change=='unknown':body['PRIVATE_FIELD']='PRIVATE_SENTINEL'
            elif change=='cost':body['manaCost']=[{'count':1,'PRIVATE_FIELD':'PRIVATE_SENTINEL'}]
            elif change=='recipient':body['attackers'][0]['selectedDamageRecipient']={'type':'DamageRecType_Planeswalker','planeswalkerInstanceId':1359}
            else:body['canSubmitAttackers']=False
            d=self.collect(rows)
            self.assertFalse(any(s['request']['kind']=='declare_attackers' for s in d['samples']))
            self.assertNotIn('PRIVATE_SENTINEL',json.dumps(d))
        rows=copy.deepcopy(self.rows);self.message(rows,42)['declareBlockersReq']['blockers'][0]['selectedAttackerInstanceIds']=[999999]
        d=self.collect(rows);self.assertFalse(any(s['request']['kind']=='declare_blockers' for s in d['samples']))
        self.assertNotIn('999999',json.dumps(d))
        rows=copy.deepcopy(self.rows);self.message(rows,42)['declareBlockersReq']['blockers'][0].pop('selectedAttackerInstanceIds')
        self.assertFalse(any(s['request']['kind']=='declare_blockers' for s in self.collect(rows)['samples']))

    def test_explicit_capacity_membership_and_unique_reference_controls(self):
        d=self.collect();s=d['samples'][-1];p=s['request']['payload'];snapshot=s['before'];seat=s['identity']['self_seat']
        positive=copy.deepcopy(s['request'])
        for row in positive['payload']['blockers']:row['candidate_attacker_refs']=list(row['selected_attacker_refs'])
        check_request(positive,snapshot,seat)
        for change in ('capacity','membership','duplicate','visibility'):
            bad=copy.deepcopy(positive);r=bad['payload']['blockers'][0]
            if change=='capacity':
                second=bad['payload']['blockers'][1]['selected_attacker_refs'][0]
                r['selected_attacker_refs'].append(second);r['candidate_attacker_refs'].append(second)
            elif change=='membership':r['candidate_attacker_refs']=[]
            elif change=='duplicate':bad['payload']['blockers'].append(copy.deepcopy(r))
            else:r['object_ref']=r['selected_attacker_refs'][0]
            with self.assertRaises(SampleError):check_request(bad,snapshot,seat)

    def test_missing_conflicting_extra_or_private_result_never_confirms(self):
        for role in ('blocker','attacker','opposing_attacker'):
            with self.subTest(conflicting_role=role):
                blocking=role!='attacker'
                rows=copy.deepcopy(self.rows if blocking else self.load('unselect'))
                line=44 if blocking else 316
                ident={'blocker':1025,'attacker':1352,'opposing_attacker':1003}[role]
                update=next(o for o in self.message(rows,line)['gameStateMessage']['gameObjects']
                            if o['instanceId']==ident)
                if role=='blocker':
                    update.update(attackState='AttackState_Attacking',attackInfo={'targetId':2})
                elif role=='opposing_attacker':
                    update['blockInfo']={'attackerIds':[1025]}
                else:
                    reducer,_,_=self.ready(rows,line=315)
                    opposing=next(o['id'] for o in reducer.document()['current']['objects']
                                  if o['zone']=='ZoneType_Battlefield' and o['controller']==2)
                    update.update(blockState='BlockState_Blocking',blockInfo={'attackerIds':[opposing]})
                self.assertFalse(self.last(self.collect(rows))['selected_public_result_observed'])
        rows=self.load('unselect')
        attacker=next(o for o in self.message(rows,316)['gameStateMessage']['gameObjects']
                      if o['instanceId']==1352)
        attacker['blockState']='BlockState_Blocked'  # A blocked attacker is not itself a blocker.
        self.assertTrue(self.last(self.collect(rows))['selected_public_result_observed'])
        annotated=copy.deepcopy(self.rows)
        self.message(annotated,44)['gameStateMessage']['annotations']=[{'PRIVATE_FIELD':'PRIVATE_SENTINEL'}]
        d=self.collect(annotated)
        self.assertEqual(d['samples'][-1]['trace']['states'][0]['omitted_annotations'],1)
        self.assertNotIn('PRIVATE_SENTINEL',json.dumps(d));self.assertTrue(self.last(d)['selected_public_result_observed'])
        original=self.collect()
        for change in ('missing','relationship','opposing_relation','state','extra'):
            d=copy.deepcopy(original);s=d['samples'][-1];state=s['trace']['states'][0];fs=state['facts']
            selected=s['request']['payload']['blockers'][0]['object_ref']
            f=next(f for f in fs if f['object_ref']==selected)
            if change=='missing':fs.remove(f)
            elif change=='relationship':f['attacker_refs']=[]
            elif change=='opposing_relation':next(x for x in fs if x['object_ref']==f['attacker_refs'][0])['block_state']='BlockState_Unblocked'
            elif change=='state':f['block_state']='BlockState_Declared'
            else:
                chosen={r['object_ref'] for r in s['request']['payload']['blockers']}
                own=next(o['object_ref'] for o in state['snapshot']['objects'] if o['zone']=='ZoneType_Battlefield' and o['controller']==1 and o['object_ref'] not in chosen)
                fs[:]=[x for x in fs if x['object_ref']!=own]
                fs.append({**copy.deepcopy(f),'object_ref':own})
            self.assertFalse(self.last(d)['selected_public_result_observed'])
        for bad_sample in (None, {'request':None}):
            d=copy.deepcopy(original);d['samples'][-1]=bad_sample
            with self.assertRaises(SampleError):replay_samples(d)
        d=copy.deepcopy(original);d['samples'][-1]['trace']['states'][0]['facts'][0]['object_ref']=999999
        with self.assertRaises(SampleError):replay_samples(d)
        d=copy.deepcopy(original);d['samples'][-1]['before']['objects'].append(copy.deepcopy(d['samples'][-1]['before']['objects'][0]))
        with self.assertRaises(SampleError):replay_samples(d)

    def test_eof_gap_full_and_missing_update_keep_result_unknown(self):
        for change in ('eof','gap','full','missing'):
            rows=copy.deepcopy(self.rows)
            if change=='eof':rows=rows[:43]
            else:
                gs=self.message(rows,44)['gameStateMessage']
                if change=='gap':gs['prevGameStateId']=9999
                elif change=='full':
                    full=copy.deepcopy(self.message(rows,3)['gameStateMessage']);full['gameStateId']=495
                    self.message(rows,44)['gameStateMessage']=full
                else:gs['gameObjects']=[]
            d=self.collect(rows);self.assertFalse(self.last(d)['selected_public_result_observed'])
        original=self.collect()
        for change in ('missing_trace','impossible_limit'):
            with self.subTest(forged_trace=change):
                d=copy.deepcopy(original);sample=d['samples'][-1]
                sample['trace'].update(status='eof',states=[])
                if change=='impossible_limit':
                    sample['trace']['status']='limit_reached'
                    sample['successor']={'status':'not_observed','snapshot':None,
                                         'request_kind':None,'request_ref':None}
                with self.assertRaises(SampleError):replay_samples(d)

    def test_v3_noncombat_inherits_v2_and_cli_privacy(self):
        cast=[json.loads(x) for x in (FIXTURES/'player_log_cast_generic_one.jsonl').read_text().splitlines()]
        a=self.collect(cast,2);b=self.collect(cast,3)
        self.assertEqual(a['samples'],b['samples'])
        self.assertEqual(replay_samples(a)['samples'],replay_samples(b)['samples'])
        self.collect();output=self.root/'export.json'
        run=subprocess.run([sys.executable,'-m','mtgaplayer','export-semantic-samples',str(self.path),'--output',str(output),'--schema-version','3','--max-samples','256'],capture_output=True,text=True,timeout=10)
        self.assertEqual(run.returncode,0,run.stdout+run.stderr)
        run=subprocess.run([sys.executable,'-m','mtgaplayer','replay-semantic-samples',str(output)],capture_output=True,text=True,timeout=10)
        self.assertEqual(run.returncode,0,run.stdout+run.stderr)
        text=output.read_text()
        for secret in ('fixture-combat','authenticateResponse','reservedPlayers','orderedBlockers','orderedAttackers','"prompt":',str(self.path)):
            self.assertNotIn(secret,text)
        self.assertEqual(self.collect(version=1)['schema_version'],'mtgaplayer.semantic-samples.v1')
