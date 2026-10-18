"""Retained real request projections; invented auth/wrappers and counterexamples."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from mtgaplayer import current_group as group
from mtgaplayer.decision_consumer import EXECUTION
from mtgaplayer.shadow_history import _Evaluation,evaluate_shadow_history
from test_semantic_search import search_baseline,message
from test_raw_log import state

ROOT=Path(__file__).resolve().parents[1]
FIXTURE=ROOT/'tests/fixtures/current_group_real_v1.json'


def wrap(m):return {'greToClientEvent':{'greToClientMessages':[m]}}


def rows_for(sample=None):
    """Synthetic bootstrap/envelope, never an original authenticated raw sample."""
    sample=sample or json.loads(FIXTURE.read_text())['samples'][0]
    return search_baseline()+[wrap({'type':group.REQUEST,'systemSeatIds':[1],'msgId':990,'gameStateId':1,
        'prompt':{'promptId':123456789,'parameters':[{'parameterName':'PRIVATE_PROMPT_SENTINEL',
            'type':'ParameterType_Number','numberValue':987654321}]},'allowCancel':'AllowCancel_No',
        'groupReq':{'instanceIds':[801,802],'groupSpecs':copy.deepcopy(sample['specs']),
            'groupType':sample['group_type'],'context':sample['context'],'sourceId':705}})]


def response(ids_top=None,ids_bottom=(801,802)):
    groups=[{'zoneType':'ZoneType_Library','subZoneType':'SubZoneType_Top'},
        {'zoneType':'ZoneType_Library','subZoneType':'SubZoneType_Bottom'}]
    for row,ids in zip(groups,(ids_top,ids_bottom)):
        if ids is not None:row['ids']=list(ids)
    return {'payload':{'type':group.RESPONSE,'respId':990,'gameStateId':1,
        'groupResp':{'groups':groups,'groupType':'GroupType_Ordered'}}}


class CurrentGroupTests(unittest.TestCase):
    def ready(self,mutate=None,history=False):
        rows=rows_for()
        if mutate:mutate(rows)
        e=_Evaluation(current_group_evidence=history)
        for row in rows:e.apply(row)
        return e,message(rows[-1])

    def report(self,e,m,limit=64):
        return e.consumer.current_decision_options(limit=limit,current_group_context=(e.reducer,m))['current_group_evidence']

    def denied(self,r):
        self.assertEqual(r['status'],'insufficient_evidence');self.assertIsNone(r['request_binding'])
        self.assertIsNone(r['source_snapshot_ref']);self.assertEqual(r['unresolved_item_references'],[])
        self.assertFalse(r['current_local_constraints_verified'])

    def safe(self,r):
        for key in EXECUTION:self.assertIs(r[key],False,key)
        self.assertFalse(r['historical_response_used']);self.assertFalse(r['research_eligible'])
        self.assertIsNone(r['prompt_number_semantics']);self.assertNotIn('prompt_numbers',r)
        self.assertIsNone(r['complete_legal_choices']);self.assertEqual(r['complete_proposals'],[])
        self.assertEqual(r['reviewed_visible_items'],[])
        for row in r['unresolved_item_references']:
            for key in ('object_ref','card_id','zone'):self.assertIsNone(row[key])
            self.assertEqual(row['namespace'],group.NAMESPACE)

    def test_real_projection_provenance_and_current_unknown_identity_slice(self):
        fixture=json.loads(FIXTURE.read_text());self.assertEqual(fixture['origin'],'retained_scrubbed_real')
        self.assertFalse(fixture['raw_equivalent']);self.assertFalse(fixture['authentication_envelope_retained'])
        self.assertFalse(fixture['future_response_used_for_request']);self.assertEqual(len(fixture['samples']),3)
        for sample in fixture['samples']:
            e=_Evaluation()
            for row in rows_for(sample):e.apply(row)
            r=self.report(e,message(row));self.safe(r);self.assertEqual(r['status'],'observed')
            self.assertEqual(r['observed_item_count'],2);self.assertEqual(r['unresolved_item_count'],2)
            self.assertEqual(r['reviewed_member_count'],0);self.assertTrue(r['reviewed_count_bounds'])
            self.assertEqual([s['lower_bound'] for s in r['observed_group_specs']],[None,None])
            self.assertEqual([s['upper_bound'] for s in r['observed_group_specs']],[2,2])
            for member in r['unresolved_item_references']:
                self.assertEqual(member['request_binding'],r['request_binding']);self.assertEqual(member['source_snapshot_ref'],r['source_snapshot_ref'])

    def test_default_options_policy_and_cache_are_unchanged_and_detached(self):
        e,m=self.ready();before=e.consumer.current_decision_options();policy=e.consumer.shadow_decision()
        enriched=e.consumer.current_decision_options(current_group_context=(e.reducer,m));r=enriched.pop('current_group_evidence')
        self.assertEqual(enriched,before);self.assertEqual(e.consumer.shadow_decision(),policy)
        self.assertNotEqual(policy['status'],'research_preference');r['unresolved_item_references'].clear()
        self.assertEqual(len(self.report(e,m)['unresolved_item_references']),2)
        self.assertEqual(e.consumer.current_decision_options(),before)

    def test_limit_namespace_and_nonexistent_hidden_ids_do_not_create_proposals(self):
        e,m=self.ready();r=self.report(e,m,1);self.safe(r)
        self.assertTrue(r['truncated']);self.assertEqual(r['unresolved_item_count'],2);self.assertEqual(r['returned_members'],1)
        e,m=self.ready(mutate=lambda rows:message(rows[-1])['groupReq'].__setitem__('instanceIds',[99001,99002]))
        self.assertEqual(self.report(e,m)['status'],'observed');self.safe(self.report(e,m))
        def collide(rows):
            for o in state(rows[2])['gameObjects']:
                if o['instanceId']==705:o['instanceId']=1
            for z in state(rows[2])['zones']:
                if z['zoneId']==27:z['objectInstanceIds']=[1]
            message(rows[-1])['groupReq']['sourceId']=1
        e,m=self.ready(mutate=collide);r=self.report(e,m);self.safe(r)
        self.assertEqual(r['source_object_ref'],r['unresolved_item_references'][0]['group_item_ref'])

    def test_wrong_types_bounds_duplicates_enums_and_extra_fields_fail_closed(self):
        changes=[lambda m:m['groupReq'].__setitem__('instanceIds',[801,801]),
            lambda m:m['groupReq'].__setitem__('instanceIds',[True,802]),lambda m:m['groupReq'].__setitem__('instanceIds',[801.0,802]),
            lambda m:m['groupReq'].__setitem__('instanceIds',[0,802]),lambda m:m['groupReq'].__setitem__('instanceIds',[2**32,802]),
            lambda m:m['groupReq'].__setitem__('instanceIds',[801]),lambda m:m['groupReq'].__setitem__('groupType','GroupType_Arbitrary'),
            lambda m:m['groupReq'].__setitem__('context','GroupingContext_Surveil'),lambda m:m['groupReq'].__setitem__('sourceId',True),
            lambda m:m['groupReq'].__setitem__('sourceId',705.0),lambda m:m['groupReq'].__delitem__('sourceId'),
            lambda m:m['groupReq']['groupSpecs'].reverse(),lambda m:m['groupReq']['groupSpecs'].pop(),
            lambda m:m['groupReq']['groupSpecs'][0].__setitem__('upperBound',True),
            lambda m:m['groupReq']['groupSpecs'][0].__setitem__('upperBound',2.0),
            lambda m:m['groupReq']['groupSpecs'][0].__setitem__('upperBound',1),
            lambda m:m['groupReq']['groupSpecs'][0].__setitem__('lowerBound',0),
            lambda m:m['groupReq']['groupSpecs'][0].__setitem__('zoneType','ZoneType_Battlefield'),
            lambda m:m['prompt']['parameters'][0].__setitem__('numberValue',True),lambda m:m['prompt'].__setitem__('parameters',[]),
            lambda m:m['prompt']['parameters'][0].__setitem__('numberValue',2**31),
            lambda m:m['prompt']['parameters'][0].__setitem__('numberValue',1.0),
            lambda m:m.__setitem__('allowCancel','AllowCancel_Abort'),lambda m:m.__setitem__('allowUndo',True)]
        for change in changes:
            e,m=self.ready(mutate=lambda rows:change(message(rows[-1])));self.denied(self.report(e,m))

    def test_wrong_current_digest_seat_game_and_context_are_rejected(self):
        e,m=self.ready()
        for key,value in (('msgId',991),('gameStateId',1.0),('systemSeatIds',[2]),('systemSeatIds',[True])):
            bad=copy.deepcopy(m);bad[key]=value;self.denied(self.report(e,bad))
        bad=copy.deepcopy(m);bad['groupReq']['instanceIds'].reverse();self.denied(self.report(e,bad))
        for key,value in (('seat',2),('game',2),('match','another')):
            e,m=self.ready();setattr(e.reducer,key,value);self.denied(self.report(e,m))
        e,m=self.ready()
        for bad in (True,[],(e.reducer,),[e.reducer,m]):
            with self.assertRaises(ValueError):e.consumer.current_decision_options(current_group_context=bad)
        self.denied(e.consumer.current_decision_options(current_group_context=(None,m))['current_group_evidence'])

    def test_source_and_visible_member_profiles_cannot_borrow_hidden_identity(self):
        for mode in ('source_zone','source_private','source_owner','source_controller','source_card','duplicate_source','visible_member'):
            e,m=self.ready();source=e.reducer.objects[705]
            if mode=='source_zone':e.reducer.zones[27]['type']='ZoneType_Battlefield'
            elif mode=='source_private':source['visibility']='Visibility_Private';source['viewers']=[1]
            elif mode=='source_owner':source['ownerSeatId']=2
            elif mode=='source_controller':source['controllerSeatId']=2
            elif mode=='source_card':source['type']='GameObjectType_Card'
            elif mode=='duplicate_source':e.reducer.zones[27]['objectInstanceIds'].append(705)
            else:
                e.reducer.objects[801]['zoneId']=28;e.reducer.objects[801]['visibility']='Visibility_Public'
                e.reducer.zones[28]['objectInstanceIds'].append(801)
            with self.subTest(mode=mode):self.denied(self.report(e,m))

    def test_inflight_source_identity_raw_mutation_consume_visibility_and_expiry_revoke(self):
        for mode in ('grp','parent','raw','consume','visible','expiry'):
            e,m=self.ready();original=group.project_request
            def late(*args,**kwargs):
                value=original(*args,**kwargs)
                if mode in ('grp','parent'):e.reducer.objects[705]['grpId' if mode=='grp' else 'parentId']=123456
                elif mode=='raw':m['groupReq']['instanceIds'].reverse()
                elif mode=='consume':e.reducer.apply(response())
                elif mode=='expiry':e.ordinal+=10**15
                else:
                    e.reducer.objects[801]['zoneId']=28;e.reducer.objects[801]['visibility']='Visibility_Public'
                    e.reducer.zones[28]['objectInstanceIds'].append(801)
                return value
            with patch.object(group,'project_request',side_effect=late):self.denied(self.report(e,m))

    def test_full_reset_gap_partial_cancel_undo_stop_expiry_and_retransmission(self):
        for mode in ('full','reset','gap','partial','cancel','undo','unsupported','broadcast','mixed','stop','expiry','malformed_recover'):
            e,m=self.ready(history=True)
            if mode=='full':e.apply(rows_for()[2])
            elif mode=='reset':e.reducer.reset(2)
            elif mode=='gap':e.apply(wrap({'type':'GREMessageType_GameStateMessage','systemSeatIds':[1],
                'gameStateMessage':{'type':'GameStateType_Diff','gameStateId':2,'prevGameStateId':99}}))
            elif mode=='partial':e.publish(partial=True)
            elif mode in ('cancel','undo','unsupported'):e.apply({'payload':{'type':{'cancel':'ClientMessageType_CancelActionReq',
                'undo':'ClientMessageType_UndoReq','unsupported':'ClientMessageType_UnreviewedRequest'}[mode]}})
            elif mode=='broadcast':
                bad=copy.deepcopy(m);bad['systemSeatIds']=[1,2];e.apply(wrap(bad))
            elif mode=='mixed':
                bad=wrap(copy.deepcopy(m));bad['payload']={'type':'ClientMessageType_UIMessage'};e.apply(bad)
            elif mode=='stop':
                for event in e.publisher.stop('sample_limit'):self.assertTrue(e.consumer.accept_event(event))
            elif mode=='expiry':e.ordinal+=10**15
            else:e.apply(None);e.apply(rows_for()[2])
            with self.subTest(mode=mode):
                self.denied(self.report(e,m))
                if mode in ('stop','expiry'):e.reducer.apply(wrap(copy.deepcopy(m)))
                else:e.apply(wrap(copy.deepcopy(m)))
                self.denied(self.report(e,m));self.assertNotIn('_group_evidence_interrupted',json.dumps(e.reducer.document(include_decision_state=True)))

    def test_typed_predecessor_consumed_and_superseded_requests_never_return(self):
        e,m=self.ready();old=self.report(e,m);e.apply(response());self.denied(self.report(e,m))
        e.apply(wrap(m));self.denied(self.report(e,m));new=copy.deepcopy(m);new['msgId']=991;e.apply(wrap(new))
        now=self.report(e,new);self.assertEqual(now['status'],'observed');self.assertNotEqual(old['request_binding'],now['request_binding'])
        self.denied(self.report(e,m));e.apply(wrap(m));self.denied(self.report(e,m))
        e,m=self.ready();e.apply(wrap({'type':'GREMessageType_GameStateMessage','systemSeatIds':[1],
            'gameStateMessage':{'type':'GameStateType_Diff','gameStateId':2,'prevGameStateId':1.0}}))
        m=copy.deepcopy(m);m.update(msgId=991,gameStateId=2);e.apply(wrap(m));self.denied(self.report(e,m))

    def test_response_local_membership_omitted_ids_and_bounds_are_separate(self):
        frozen={'specs':[{'zone_type':'ZoneType_Library','sub_zone_type':s,'upper_bound':2} for s in ('SubZoneType_Top','SubZoneType_Bottom')],
            'items':{801:1,802:2}}
        r=group.review_response(response()['payload'],frozen)
        self.assertEqual(r,{'explicit_submitted_members':2,'groups_with_unobserved_ids':1})
        self.assertEqual(group.review_response(response(())['payload'],frozen)['groups_with_unobserved_ids'],0)
        for top,bottom in (([801],[801]),([],[999]),([],[True]),([],[801.0]),([],[801,802,803])):
            with self.assertRaises(ValueError):group.review_response(response(top,bottom)['payload'],frozen)
        for mutate in (lambda p:p['groupResp'].__setitem__('groupType','GroupType_Arbitrary'),
            lambda p:p['groupResp']['groups'].reverse(),lambda p:p['groupResp']['groups'][0].__setitem__('groupId',0)):
            payload=response()['payload'];mutate(payload)
            with self.assertRaises(ValueError):group.review_response(payload,frozen)

    def test_history_freeze_future_isolation_and_default_complete_report(self):
        rows=rows_for()+[response()]
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'synthetic.log';path.write_text(''.join(json.dumps(row)+'\n' for row in rows))
            default=evaluate_shadow_history(path);enriched=evaluate_shadow_history(path,current_group_evidence=True)
            c=enriched.pop('current_group_request_evidence');self.assertEqual(c['real_current_requests'],1)
            self.assertEqual(c['supported_current_requests'],1);self.assertEqual(c['reviewed_members'],0);self.assertEqual(c['unknown_members'],2)
            self.assertEqual(c['strictly_paired_responses'],1);self.assertEqual(c['reviewed_response_local_constraints'],1)
            self.assertEqual(c['groups_with_unobserved_member_lists'],1);self.assertIsNone(c['complete_legal_choices'])
            for r in (default,enriched):r.pop('timings_ms')
            self.assertEqual(default,enriched)
            for bad in (1,'yes',None):
                with self.assertRaises(ValueError):evaluate_shadow_history(path,current_group_evidence=bad)
        e,m=self.ready(history=True);before=self.report(e,m);e.apply(response())
        self.safe(before);self.assertEqual(before['observed_group_specs'][0]['lower_bound'],None);self.denied(self.report(e,m))

    def test_interrupted_partial_wrong_response_and_eof_do_not_claim_submission(self):
        for mode in ('cancel','partial','wrong_type','wrong_id','wrong_state','eof'):
            e,m=self.ready(history=True)
            if mode=='cancel':e.apply({'payload':{'type':'ClientMessageType_UndoReq'}});e.apply(wrap(m))
            elif mode=='partial':e.publish(partial=True)
            payload=response()
            if mode=='wrong_type':payload['payload']['type']='ClientMessageType_MulliganResp'
            elif mode=='wrong_id':payload['payload']['respId']=991
            elif mode=='wrong_state':payload['payload']['gameStateId']=2
            if mode!='eof':e.apply(payload)
            self.assertEqual(e.group_counts['reviewed_response_local_constraints'],0)
            self.assertEqual(e.group_counts['strictly_paired_responses'],1 if mode in ('cancel','partial') else 0)

    def test_cli_optin_safe_aggregate_and_search_observer_remains_separate(self):
        e,m=self.ready();options=e.consumer.current_decision_options(current_search_context=(e.reducer,m),current_group_context=(e.reducer,m))
        self.assertEqual(options['current_group_evidence']['status'],'observed')
        self.assertEqual(options['current_search_evidence']['status'],'insufficient_evidence')
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'synthetic.log';path.write_text(''.join(json.dumps(row)+'\n' for row in rows_for()+[response()]))
            proc=subprocess.run([sys.executable,'-m','mtgaplayer','evaluate-shadow-history',str(path),'--current-group-evidence'],capture_output=True,text=True)
            self.assertEqual(proc.returncode,0,proc.stderr);report=json.loads(proc.stdout)
            self.assertEqual(report['current_group_request_evidence']['supported_current_requests'],1)
            for forbidden in ('PRIVATE_PROMPT_SENTINEL','135792468',str(path),'instanceIds','groupSpecs'):
                self.assertNotIn(forbidden,proc.stdout)


if __name__=='__main__':unittest.main()
