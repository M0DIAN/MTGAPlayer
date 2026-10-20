"""MP101 retained real projections; every mutation below is synthetic."""
import copy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from mtgaplayer.current_blockers import SCOPE
from mtgaplayer.decision_consumer import EXECUTION
from mtgaplayer.semantic_combat import check_request
from mtgaplayer.shadow_runtime import LocalShadowRuntime

FIXTURES = Path(__file__).parent / 'fixtures'


class Clock:
    def __init__(self): self.now = 1_000_000
    def __call__(self): self.now += 1; return self.now


class CurrentBlockerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup); self.count = 0

    def ready(self, name='blockers', line=33, mutate=None):
        # Both files are retained aliases, not new raw-source authentication.
        # Read only through the first request before constructing its result.
        with (FIXTURES / f'player_log_combat_{name}.jsonl').open('rb') as source:
            prefix = [source.readline() for _ in range(line)]
        rows = [json.loads(raw) for raw in prefix]
        if mutate:
            mutate(rows)
            prefix = [(json.dumps(row)+'\n').encode() for row in rows]
        self.count += 1; path = Path(self.tmp.name) / f'projection-{self.count}.jsonl'
        path.write_bytes(b''.join(prefix[:-1])); clock = Clock()
        runtime = LocalShadowRuntime(path, interval=0, clock_ns=clock,
            observation_mode='controlled_stream_replay')
        frames = runtime.frames(); next(frames)
        self.addCleanup(runtime.close); self.addCleanup(frames.close)
        with path.open('ab') as out: out.write(prefix[-1])
        frame = next(frames)
        return runtime, frames, path, rows, frame, clock

    def report(self, runtime, **kwargs):
        return runtime.consumer.current_blocker_assignments(runtime._reducer, runtime._message,
            completed_stamp=runtime._completed_stamp, **kwargs)

    @staticmethod
    def message(rows): return rows[-1]['greToClientEvent']['greToClientMessages'][0]

    def append(self, stream, path, rows):
        with path.open('ab') as out:
            for row in rows: out.write((json.dumps(row)+'\n').encode())
        return next(stream)

    def assert_no_authority(self, result):
        self.assertIs(result['research_eligible'], False)
        self.assertIsNone(result['minimum_block_count'])
        self.assertIsNone(result['all_blockers_required_by_rules'])
        self.assertIsNone(result['complete_legal_actions'])
        self.assertFalse(result['no_block_configuration_assessed'])
        for value in (result, *result['candidates']):
            for field in ('complete_legality_verified', 'legal_choice_verified', 'strategic_optimality_verified',
                          'server_acceptance_verified', 'response_encoding_verified', *EXECUTION):
                self.assertIs(value[field], False, field)

    def test_two_real_initial_full_menus_generate_whole_row_subset_not_global_legality(self):
        for name, line, count in (('blockers',33,27), ('unselect',259,9)):
            with self.subTest(retained=name):
                runtime, _, _, rows, frame, _ = self.ready(name, line)
                self.assertEqual(frame['time_scope'], 'current_at_completed_poll')
                baseline = copy.deepcopy(runtime.consumer.current_decision_options())
                result = self.report(runtime); raw = self.message(rows)['declareBlockersReq']['blockers']
                self.assertEqual(result['status'], 'observed')
                self.assertEqual(result['candidate_total_for_reviewed_profile'], count)
                self.assertEqual(result['returned_candidates'], count)
                self.assertEqual(result['blocker_row_count'], len(raw))
                self.assertFalse(result['truncated']); self.assert_no_authority(result)
                self.assertEqual(runtime.consumer.current_decision_options(), baseline)
                shared = 0
                for option in result['candidates']:
                    assignment = option['proposal']['blocker_assignments']
                    self.assertEqual(option['request_binding'], frame['request_binding'])
                    self.assertEqual(option['source_snapshot_ref'], frame['source_snapshot_ref'])
                    self.assertEqual(option['local_validation'], {'status':'verified_known_constraints','scope':SCOPE})
                    self.assertEqual(len(assignment), len(raw))
                    for index, item in enumerate(assignment):
                        self.assertEqual(item['row_position'], index)
                        self.assertEqual(item['blocker_object_ref'], raw[index]['blockerInstanceId'])
                        self.assertIn(item['attacker_object_ref'], raw[index]['attackerInstanceIds'])
                    shared += len({i['attacker_object_ref'] for i in assignment}) == 1
                self.assertEqual(shared, 3)  # independently offered shared attackers are retained
                result['candidates'].clear()
                self.assertEqual(self.report(runtime)['returned_candidates'], count)

    def test_current_rows_do_not_borrow_edges_or_domains_from_other_rows_or_history(self):
        def narrow(rows):
            bs = self.message(rows)['declareBlockersReq']['blockers']
            bs[0]['attackerInstanceIds'] = bs[0]['attackerInstanceIds'][:1]
            bs[1]['attackerInstanceIds'] = bs[1]['attackerInstanceIds'][1:]
        runtime, _, _, rows, _, _ = self.ready(mutate=narrow)
        result = self.report(runtime); self.assertEqual(result['returned_candidates'], 6)
        for option in result['candidates']:
            for i, row in enumerate(option['proposal']['blocker_assignments']):
                self.assertIn(row['attacker_object_ref'], self.message(rows)['declareBlockersReq']['blockers'][i]['attackerInstanceIds'])
        for name,line in (('blockers',36),('blockers',39),('blockers',42),('unselect',262),('unselect',265)):
            with self.subTest(selected_only=line, source=name):
                later, *_ = self.ready(name,line)
                report = self.report(later)
                self.assertEqual(report['status'],'insufficient_evidence')
                self.assertEqual(report['candidates'],[])
                self.assertIsNone(report['candidate_total_for_reviewed_profile'])

    def test_synthetic_shape_capacity_and_row_presence_counterexamples(self):
        def blockers(rows): return self.message(rows)['declareBlockersReq']['blockers']
        mutations = {
            'max_two':lambda r:blockers(r)[0].update(maxAttackers=2),
            'max_bool':lambda r:blockers(r)[0].update(maxAttackers=True),
            'missing_offer':lambda r:blockers(r)[0].pop('attackerInstanceIds'),
            'empty_offer':lambda r:blockers(r)[0].update(attackerInstanceIds=[]),
            'duplicate_blocker':lambda r:blockers(r).append(copy.deepcopy(blockers(r)[0])),
            'duplicate_edge':lambda r:blockers(r)[0]['attackerInstanceIds'].append(blockers(r)[0]['attackerInstanceIds'][0]),
            'selected_extra':lambda r:blockers(r)[0].update(selectedAttackerInstanceIds=[*blockers(r)[0]['attackerInstanceIds'][:2]]),
            'unknown_cost':lambda r:self.message(r)['declareBlockersReq'].update(manaCost=[{'count':1}]),
        }
        for label, mutation in mutations.items():
            with self.subTest(synthetic=label):
                runtime,*_ = self.ready(mutate=mutation)
                self.assertEqual(self.report(runtime)['candidates'],[])

    def test_synthetic_public_identity_role_and_zone_counterexamples(self):
        def bad_entity(rows, role, change):
            menu = self.message(rows)['declareBlockersReq']['blockers'][0]
            ident = menu['blockerInstanceId'] if role=='blocker' else menu['attackerInstanceIds'][0]
            for record in rows:
                for msg in record.get('greToClientEvent',{}).get('greToClientMessages',[]):
                    for obj in msg.get('gameStateMessage',{}).get('gameObjects',[]):
                        if obj.get('instanceId')==ident: obj.update(change)
        for role, change in (('blocker',{'controllerSeatId':2}),('attacker',{'controllerSeatId':1}),
                ('blocker',{'visibility':'Visibility_Hidden'}),('attacker',{'visibility':'Visibility_Hidden'}),
                ('blocker',{'type':'GameObjectType_Ability'})):
            with self.subTest(synthetic_role=role, change=change):
                runtime,*_ = self.ready(mutate=lambda rows:bad_entity(rows,role,change))
                self.assertEqual(self.report(runtime)['candidates'],[])

    def test_actual_increment_consumption_and_old_request_cannot_restore_assignments(self):
        runtime, stream, path, rows, _, _ = self.ready()
        self.assertEqual(self.report(runtime)['returned_candidates'],27)
        with (FIXTURES/'player_log_combat_blockers.jsonl').open() as source:
            records=[json.loads(line) for _,line in zip(range(34),source)]
        self.append(stream,path,[records[33]])
        self.assertIsNone(runtime._reducer.request)
        self.assertEqual(self.report(runtime)['candidates'],[])
        self.append(stream,path,[rows[-1]])
        self.assertEqual(self.report(runtime)['candidates'],[])

    def test_cancel_undo_full_gap_partial_stop_and_lease_revoke(self):
        for kind in ('Cancel','Undo','Full','gap','partial','stop','lease'):
            with self.subTest(interruption=kind):
                runtime,stream,path,rows,frame,clock = self.ready()
                self.assertEqual(self.report(runtime)['status'],'observed')
                if kind in ('Cancel','Undo'):
                    self.append(stream,path,[{'payload':{'type':f'ClientMessageType_{kind}Req'}}])
                    self.assertTrue(runtime._reducer.request['_blocker_evidence_interrupted'])
                    self.append(stream,path,[rows[-1]])
                elif kind in ('Full','gap'):
                    gs=copy.deepcopy(rows[2]['greToClientEvent']['greToClientMessages'][0])
                    if kind=='gap':
                        gs['gameStateMessage'].update(type='GameStateType_Diff',gameStateId=9999,prevGameStateId=9997)
                    self.append(stream,path,[{'greToClientEvent':{'greToClientMessages':[gs]}}])
                elif kind=='partial':
                    with path.open('ab') as out:out.write(b'{"incomplete":')
                    next(stream)
                elif kind=='stop':runtime.close()
                else:clock.now+=100_000_000_000
                self.assertEqual(self.report(runtime)['candidates'],[])

    def test_owner_completed_poll_limit_and_computation_race(self):
        runtime,_,_,rows,_,clock=self.ready()
        self.assertEqual(runtime.consumer.current_blocker_assignments(runtime._reducer,runtime._message)['reason'],
            'completed_poll_context_required')
        results=[]
        worker=threading.Thread(target=lambda:results.append(self.report(runtime)));worker.start();worker.join()
        self.assertEqual(results[0]['reason'],'owner_thread_required')
        report=self.report(runtime,limit=2)
        self.assertEqual(report['returned_candidates'],2);self.assertEqual(report['candidate_total_for_reviewed_profile'],27)
        self.assertTrue(report['truncated']);self.assert_no_authority(report)
        for bad in (0,65,True):
            with self.assertRaises(ValueError):self.report(runtime,limit=bad)
        def expires(*args):
            clock.now+=100_000_000_000
            return check_request(*args)
        with patch('mtgaplayer.current_blockers.check_request',side_effect=expires):
            self.assertEqual(self.report(runtime)['candidates'],[])


if __name__=='__main__':unittest.main()
