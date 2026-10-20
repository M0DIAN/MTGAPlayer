"""Retained real initial attacker menus; all mutations explicitly synthetic."""
import copy
import json
import threading
import unittest
from unittest.mock import patch

import test_current_blockers as helpers
from mtgaplayer.current_attackers import SCOPE
from mtgaplayer.decision_consumer import EXECUTION
from mtgaplayer.semantic_combat import check_request


class CurrentAttackerTests(unittest.TestCase):
    def setUp(self):
        # Reuse the MP101 production Runtime prefix/append test transport.
        self.helper = helpers.CurrentBlockerTests()
        self.helper.setUp(); self.addCleanup(self.helper.doCleanups)

    def ready(self, name='blockers', line=8, mutate=None):
        return self.helper.ready(name, line, mutate)

    def report(self, runtime, **kwargs):
        return runtime.consumer.current_attacker_configurations(runtime._reducer, runtime._message,
            completed_stamp=runtime._completed_stamp, **kwargs)

    message = staticmethod(helpers.CurrentBlockerTests.message)

    def append(self, stream, path, rows): return self.helper.append(stream, path, rows)

    def assert_no_authority(self, result):
        self.assertIsNone(result['minimum_attack_count'])
        self.assertIsNone(result['complete_legal_actions'])
        self.assertFalse(result['zero_attack_configuration_assessed'])
        for value in (result, *result['candidates']):
            for field in ('research_eligible', 'nonselection_legality_verified',
                    'mandatory_attack_requirements_verified', 'complete_legality_verified',
                    'legal_choice_verified', 'strategic_optimality_verified',
                    'server_acceptance_verified', 'response_encoding_verified', *EXECUTION):
                self.assertIs(value[field], False, field)

    def test_real_initial_menus_generate_nonempty_complete_rows_without_skip_legality(self):
        for name, line, expected in (('blockers',8,7), ('unselect',308,3)):
            with self.subTest(retained=name):
                runtime,_,_,rows,frame,_ = self.ready(name,line)
                self.assertEqual(frame['time_scope'],'current_at_completed_poll')
                before = copy.deepcopy(runtime.consumer.current_decision_options())
                result = self.report(runtime); raw = self.message(rows)['declareAttackersReq']['attackers']
                self.assertEqual(result['status'],'observed')
                self.assertEqual(result['candidate_total_for_reviewed_profile'],expected)
                self.assertEqual(result['returned_candidates'],expected)
                self.assertEqual(result['attacker_row_count'],len(raw))
                self.assertEqual(result['offered_recipient_memberships'],len(raw))
                self.assertIs(result['can_submit_attackers_literal'],True)
                self.assertFalse(result['historical_response_used']);self.assertFalse(result['truncated'])
                self.assert_no_authority(result); configurations=set()
                for option in result['candidates']:
                    self.assertEqual(option['option_key']['kind'],'reviewed_attacker_configuration')
                    self.assertEqual(option['request_binding'],frame['request_binding'])
                    self.assertEqual(option['source_snapshot_ref'],frame['source_snapshot_ref'])
                    self.assertEqual(option['local_validation'],{'status':'verified_known_constraints','scope':SCOPE})
                    config=option['proposal']['attacker_configuration']
                    self.assertEqual(len(config),len(raw));self.assertTrue(any(r['selected'] for r in config))
                    configurations.add(tuple(r['selected'] for r in config))
                    for i,row in enumerate(config):
                        self.assertEqual(row['row_position'],i)
                        self.assertEqual(row['attacker_object_ref'],raw[i]['attackerInstanceId'])
                        if not row['selected']:self.assertIsNone(row['selected_recipient'])
                        else:
                            recipient=row['selected_recipient']
                            self.assertEqual(recipient['namespace'],'player_system_seat')
                            self.assertIn({'type':recipient['type'],'playerSystemSeatId':recipient['seat']},
                                raw[i]['legalDamageRecipients'])
                self.assertEqual(len(configurations),expected)
                self.assertEqual(runtime.consumer.current_decision_options(),before)
                result['candidates'].clear();self.assertEqual(self.report(runtime)['returned_candidates'],expected)

    def test_synthetic_full_row_qualified_recipient_and_unknown_field_counterexamples(self):
        def body(rows):return self.message(rows)['declareAttackersReq']
        def both(rows, change):
            for key in ('attackers','qualifiedAttackers'): change(body(rows)[key])
        mutations={
            'qualified_missing':lambda r:body(r)['qualifiedAttackers'].pop(),
            'qualified_reordered':lambda r:body(r)['qualifiedAttackers'].reverse(),
            'row_reordered_only':lambda r:body(r)['attackers'].reverse(),
            'duplicate':lambda r:both(r,lambda a:a.append(copy.deepcopy(a[0]))),
            'wrong_player':lambda r:both(r,lambda a:a[0]['legalDamageRecipients'][0].update(playerSystemSeatId=1)),
            'bool_seat':lambda r:both(r,lambda a:a[0]['legalDamageRecipients'][0].update(playerSystemSeatId=True)),
            'object_recipient':lambda r:both(r,lambda a:a[0].update(legalDamageRecipients=[{'type':'DamageRecType_Planeswalker','planeswalkerInstanceId':1}])),
            'missing_recipient':lambda r:both(r,lambda a:a[0].pop('legalDamageRecipients')),
            'empty_recipient':lambda r:both(r,lambda a:a[0].update(legalDamageRecipients=[])),
            'duplicate_recipient':lambda r:both(r,lambda a:a[0]['legalDamageRecipients'].append(copy.deepcopy(a[0]['legalDamageRecipients'][0]))),
            'bool_source':lambda r:both(r,lambda a:a[0].update(attackerInstanceId=True)),
            'unknown_body':lambda r:body(r).update(unreviewed=True),
            'unknown_row':lambda r:body(r)['attackers'][0].update(unreviewed=True),
            'submit_false':lambda r:body(r).update(canSubmitAttackers=False),
            'unknown_cost':lambda r:body(r).update(manaCost=[{'count':1}]),
            'selected_field':lambda r:body(r)['attackers'][0].update(selectedDamageRecipient=copy.deepcopy(body(r)['attackers'][0]['legalDamageRecipients'][0])),
        }
        for label, mutate in mutations.items():
            with self.subTest(synthetic=label):
                runtime,*_=self.ready(mutate=mutate)
                self.assertEqual(self.report(runtime)['candidates'],[])

    def test_synthetic_public_battlefield_identity_and_source_counterexamples(self):
        def bad(rows, change):
            ident=self.message(rows)['declareAttackersReq']['attackers'][0]['attackerInstanceId']
            for record in rows:
                for msg in record.get('greToClientEvent',{}).get('greToClientMessages',[]):
                    for obj in msg.get('gameStateMessage',{}).get('gameObjects',[]):
                        if obj.get('instanceId')==ident:obj.update(change)
        for change in ({'controllerSeatId':2},{'visibility':'Visibility_Hidden'},
                {'type':'GameObjectType_Ability'},{'zoneId':999999}):
            with self.subTest(synthetic=change):
                runtime,*_=self.ready(mutate=lambda r:bad(r,change))
                self.assertEqual(self.report(runtime)['candidates'],[])

    def test_real_revised_requests_cannot_borrow_initial_domain_and_submit_consumes(self):
        for line in (311,314):
            runtime,*_=self.ready('unselect',line)
            self.assertEqual(self.report(runtime)['candidates'],[])
        runtime,stream,path,rows,_,_=self.ready()
        before=copy.deepcopy(self.report(runtime))
        with (helpers.FIXTURES/'player_log_combat_blockers.jsonl').open() as source:
            records=[json.loads(line) for _,line in zip(range(9),source)]
        self.append(stream,path,[records[8]])
        self.assertIsNone(runtime._reducer.request)
        self.assertEqual(self.report(runtime)['candidates'],[])
        self.assertEqual(before['returned_candidates'],7)  # frozen observation only
        self.append(stream,path,[rows[-1]])
        self.assertEqual(self.report(runtime)['candidates'],[])

    def test_cancel_undo_full_gap_partial_stop_and_lease_revoke(self):
        for kind in ('Cancel','Undo','Full','gap','partial','stop','lease','replace'):
            with self.subTest(interruption=kind):
                runtime,stream,path,rows,_,clock=self.ready()
                self.assertEqual(self.report(runtime)['status'],'observed')
                if kind in ('Cancel','Undo'):
                    self.append(stream,path,[{'payload':{'type':f'ClientMessageType_{kind}Req'}}])
                    self.assertTrue(runtime._reducer.request['_attacker_evidence_interrupted'])
                    self.append(stream,path,[rows[-1]])
                elif kind in ('Full','gap'):
                    gs=copy.deepcopy(rows[2]['greToClientEvent']['greToClientMessages'][0])
                    if kind=='gap':gs['gameStateMessage'].update(type='GameStateType_Diff',gameStateId=9999,prevGameStateId=9997)
                    self.append(stream,path,[{'greToClientEvent':{'greToClientMessages':[gs]}}])
                elif kind=='partial':
                    with path.open('ab') as out:out.write(b'{"incomplete":')
                    next(stream)
                elif kind=='stop':runtime.close()
                elif kind=='lease':clock.now+=100_000_000_000
                else:
                    newer=copy.deepcopy(rows[-1]);self.message([newer])['msgId']+=100000
                    old_stamp=copy.deepcopy(runtime._completed_stamp);old_message=copy.deepcopy(runtime._message)
                    self.append(stream,path,[newer])
                    result=runtime.consumer.current_attacker_configurations(runtime._reducer,old_message,completed_stamp=old_stamp)
                    self.assertEqual(result['candidates'],[])
                    continue
                self.assertEqual(self.report(runtime)['candidates'],[])

    def test_current_owner_completed_poll_limit_and_raw_change_during_calculation(self):
        runtime,_,_,rows,_,_=self.ready()
        self.assertEqual(runtime.consumer.current_attacker_configurations(runtime._reducer,runtime._message)['reason'],
            'completed_poll_context_required')
        results=[];worker=threading.Thread(target=lambda:results.append(self.report(runtime)))
        worker.start();worker.join();self.assertEqual(results[0]['reason'],'owner_thread_required')
        report=self.report(runtime,limit=2)
        self.assertEqual(report['returned_candidates'],2);self.assertEqual(report['candidate_total_for_reviewed_profile'],7)
        self.assertTrue(report['truncated']);self.assert_no_authority(report)
        for bad in (0,65,True):
            with self.assertRaises(ValueError):self.report(runtime,limit=bad)
        ident=self.message(rows)['declareAttackersReq']['attackers'][0]['attackerInstanceId']
        def changes(*args):
            runtime._reducer.objects[ident]['type']='GameObjectType_Ability'
            return check_request(*args)
        with patch('mtgaplayer.current_attackers.check_request',side_effect=changes):
            self.assertEqual(self.report(runtime)['candidates'],[])


if __name__=='__main__':unittest.main()
