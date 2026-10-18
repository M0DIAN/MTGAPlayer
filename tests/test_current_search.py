"""Real portable request projections; all GRE wrappers/mutations are synthetic."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from mtgaplayer import current_search,semantic_search
from mtgaplayer.decision_consumer import EXECUTION
from mtgaplayer.shadow_history import _Evaluation,evaluate_shadow_history
from test_semantic_search import search_baseline,request,response,message,successor
from test_raw_log import state

ROOT=Path(__file__).resolve().parents[1]
FIXTURE=ROOT/'tests/fixtures/current_search_real_v1.json'


def wrap(m):return {'greToClientEvent':{'greToClientMessages':[m]}}


def rows_for(sample):
    """Invented auth/Full/request envelope, not original-current authentication."""
    rows=search_baseline();m=message(request())
    p=sample['request_projection'];count=p['items_to_search_count']
    m['searchReq'].update(itemsToSearch=list(range(801,801+count)),
        itemsSought=list(range(801,801+len(p['items_sought']))),maxFind=p['max_find'],
        allowFailToFind=p['allow_fail_to_find'])
    m['allowCancel']=p['allow_cancel']
    for zone in state(rows[2])['zones']:
        if zone['zoneId']==32:zone['objectInstanceIds']=list(range(801,801+count))
    return rows+[wrap(m)]


class CurrentSearchTests(unittest.TestCase):
    def setUp(self):self.fixture=json.loads(FIXTURE.read_text());self.samples=self.fixture['samples']

    def ready(self,sample=None,mutate=None,history=False):
        rows=rows_for(sample or self.samples[0])
        if mutate:mutate(rows)
        e=_Evaluation(current_search_evidence=history)
        for row in rows:e.apply(row)
        return e,message(rows[-1])

    def report(self,e,m,limit=64):
        return e.consumer.current_decision_options(limit=limit,current_search_context=(e.reducer,m))['current_search_evidence']

    def denied(self,r):
        self.assertEqual(r['status'],'insufficient_evidence');self.assertIsNone(r['request_binding'])
        self.assertIsNone(r['source_snapshot_ref']);self.assertEqual(r['offered_search_item_refs'],[])
        self.assertFalse(r['current_local_constraints_verified'])

    def safe(self,r):
        for k in EXECUTION:self.assertIs(r[k],False,k)
        for k in ('historical_response_used','complete_legality_verified','research_eligible'):self.assertIs(r[k],False,k)
        for k in ('min_find','fail_to_find_semantics','hidden_item_card_identity','complete_proposal_count'):self.assertIsNone(r[k])
        self.assertEqual(r['complete_proposals'],[])

    def test_two_retained_projections_keep_member_namespace_and_unknowns(self):
        self.assertEqual(self.fixture['origin'],'retained_scrubbed_real');self.assertFalse(self.fixture['raw_equivalent'])
        self.assertFalse(self.fixture['authentication_envelope_retained']);self.assertEqual(len(self.samples),2)
        counts=[]
        for sample in self.samples:
            semantic_search.check_request(sample['request_projection'],[sample['visible_source']],1)
            e,m=self.ready(sample);r=self.report(e,m);self.safe(r);counts.append((r['items_to_search_count'],r['offered_item_count']))
            self.assertEqual(r['status'],'observed');self.assertTrue(r['current_local_constraints_verified'])
            self.assertEqual(r['max_find'],1);self.assertEqual(r['source_object_type'],'GameObjectType_Ability')
            self.assertEqual([i['list_position'] for i in r['offered_search_item_refs']],list(range(r['offered_item_count'])))
            for row in r['offered_search_item_refs']:
                self.assertEqual(row['namespace'],current_search.NAMESPACE)
                self.assertEqual(row['visibility'],'request_identifier_only')
                self.assertEqual(row['request_binding'],r['request_binding']);self.assertEqual(row['source_snapshot_ref'],r['source_snapshot_ref'])
        self.assertEqual(counts,[(47,8),(45,7)])

    def test_side_context_does_not_change_default_options_policy_or_cache(self):
        e,m=self.ready();options=e.consumer.current_decision_options();policy=e.consumer.shadow_decision()
        enriched=e.consumer.current_decision_options(current_search_context=(e.reducer,m));r=enriched.pop('current_search_evidence')
        self.assertEqual(enriched,options);self.assertEqual(e.consumer.shadow_decision(),policy)
        self.assertNotEqual(policy['status'],'research_preference');self.assertEqual(e.consumer.current_decision_options(),options)
        r['offered_search_item_refs'][0]['search_item_ref']=999
        self.assertEqual(self.report(e,m)['offered_search_item_refs'][0]['search_item_ref'],1)

    def test_bounded_members_are_not_complete_candidates(self):
        e,m=self.ready();r=self.report(e,m,2);self.safe(r)
        self.assertEqual(r['offered_item_count'],8);self.assertEqual(r['returned_members'],2);self.assertTrue(r['truncated'])
        def one(rows):message(rows[-1])['searchReq']['itemsSought']=[801]
        e,m=self.ready(mutate=one);self.assertEqual(self.report(e,m)['returned_members'],1)
        self.assertNotEqual(e.consumer.shadow_decision()['status'],'research_preference')

    def test_numeric_collision_is_not_an_object_or_card_identity_join(self):
        def collide(rows):
            for o in state(rows[2])['gameObjects']:
                if o['instanceId']==705:o['instanceId']=1
            for z in state(rows[2])['zones']:
                if z['zoneId']==27:z['objectInstanceIds']=[1]
            message(rows[-1])['searchReq']['sourceId']=1
        e,m=self.ready(mutate=collide);r=self.report(e,m);self.safe(r)
        self.assertEqual(r['status'],'observed');self.assertEqual(r['source_object_ref'],r['offered_search_item_refs'][0]['search_item_ref'])
        self.assertEqual(r['item_namespace'],current_search.NAMESPACE)
        for forbidden in ('135792468','PRIVATE_PROMPT_SENTINEL','itemsToSearch','sourceId','itemsFound'):
            self.assertNotIn(forbidden,json.dumps(r))

    def test_typed_request_counts_domains_prompt_and_digest_fail_closed(self):
        changes=[]
        for field in ('sourceId','maxFind'):
            for value in (True,1.0):changes.append(lambda m,f=field,v=value:m['searchReq'].__setitem__(f,v))
        changes += [lambda m:m['searchReq'].__setitem__('minFind',1),lambda m:m['searchReq'].__setitem__('itemsSought',[801,801]),
            lambda m:m['searchReq'].__setitem__('itemsSought',[99999]),lambda m:m['searchReq'].__setitem__('itemsToSearch',[801,801]),
            lambda m:m['searchReq'].__setitem__('itemsSought',[True]),lambda m:m['searchReq'].__setitem__('itemsSought',[801.0]),
            lambda m:m['searchReq'].__setitem__('zonesToSearch',[32.0]),lambda m:m['searchReq'].__setitem__('allowFailToFind','AllowFailToFind_Other'),
            lambda m:m['prompt']['parameters'][0].__setitem__('numberValue',True),lambda m:m['prompt'].__setitem__('parameters',[]),
            lambda m:m.__setitem__('allowUndo',True),lambda m:m.__setitem__('systemSeatIds',[2]),lambda m:m.__setitem__('systemSeatIds',[True])]
        for change in changes:
            e,m=self.ready(mutate=lambda rows:change(message(rows[-1])));self.denied(self.report(e,m))
        e,m=self.ready();self.report(e,m)
        for key,value in (('msgId',991),('gameStateId',1.0),('systemSeatIds',[2])):
            bad=copy.deepcopy(m);bad[key]=value;self.denied(self.report(e,bad))
        bad=copy.deepcopy(m);bad['searchReq']['itemsSought'].reverse();self.denied(self.report(e,bad))

    def test_current_source_zone_identity_and_visibility_fail_closed(self):
        for mode in ('source_zone','source_private','source_owner','source_controller','duplicate_source','zone_owner','zone_id','zone_visibility','public_item'):
            e,m=self.ready();source=e.reducer.objects[705];zone=e.reducer.zones[32]
            if mode=='source_zone':e.reducer.zones[27]['type']='ZoneType_Battlefield'
            elif mode=='source_private':source['visibility']='Visibility_Private';source['viewers']=[1]
            elif mode=='source_owner':source['ownerSeatId']=2
            elif mode=='source_controller':source['controllerSeatId']=2
            elif mode=='duplicate_source':e.reducer.zones[27]['objectInstanceIds'].append(705)
            elif mode=='zone_owner':zone['ownerSeatId']=2
            elif mode=='zone_id':zone['zoneId']=True
            elif mode=='zone_visibility':zone['visibility']='Visibility_Public'
            else:
                e.reducer.objects[801]['zoneId']=28;e.reducer.objects[801]['visibility']='Visibility_Public'
                e.reducer.zones[28]['objectInstanceIds'].append(801)
            with self.subTest(mode=mode):self.denied(self.report(e,m))

    def test_wrong_seat_game_binding_and_foreign_reducer_cannot_lend_authority(self):
        for field,value in (('seat',2),('game',2),('match','unrelated')):
            e,m=self.ready();setattr(e.reducer,field,value);self.denied(self.report(e,m))
        e,m=self.ready()
        for bad in (True,[],(e.reducer,),[e.reducer,m]):
            with self.assertRaises(ValueError):e.consumer.current_decision_options(current_search_context=bad)
        self.denied(e.consumer.current_decision_options(current_search_context=(None,m))['current_search_evidence'])

    def test_consumption_replacement_and_old_replay_never_restore_members(self):
        e,m=self.ready();old=self.report(e,m);e.apply(response())
        self.denied(self.report(e,m));e.apply(wrap(copy.deepcopy(m)));self.denied(self.report(e,m))
        new=copy.deepcopy(m);new['msgId']=991;e.apply(wrap(new));now=self.report(e,new)
        self.assertEqual(now['status'],'observed');self.denied(self.report(e,m))
        self.assertNotEqual(old['request_binding'],now['request_binding']);self.assertNotEqual(old['source_snapshot_ref'],now['source_snapshot_ref'])
        self.assertEqual(old['offered_search_item_refs'][0]['search_item_ref'],now['offered_search_item_refs'][0]['search_item_ref'])

    def test_full_reset_gap_partial_cancel_undo_stop_expiry_and_recovery(self):
        for mode in ('full','reset','gap','partial','cancel','undo','broadcast','mixed','unsupported','stop','expiry','malformed_recover'):
            e,m=self.ready(history=True)
            if mode=='full':e.apply(rows_for(self.samples[0])[2])
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
            else:e.apply(None);e.apply(rows_for(self.samples[0])[2])
            with self.subTest(mode=mode):
                self.denied(self.report(e,m))
                if mode in ('stop','expiry'):e.reducer.apply(wrap(copy.deepcopy(m)))
                else:e.apply(wrap(copy.deepcopy(m)))
                self.denied(self.report(e,m))
                self.assertNotIn('_search_evidence_interrupted',json.dumps(e.reducer.document(include_decision_state=True)))

    def test_expiry_consumption_and_zone_mutation_during_calculation_discard_result(self):
        for mode in ('expiry','consume','zone','source_group','source_parent'):
            e,m=self.ready();original=semantic_search.project_request
            def late(*args,**kwargs):
                value=original(*args,**kwargs)
                if mode=='expiry':e.ordinal+=10**15
                elif mode=='consume':e.reducer.apply(response())
                elif mode=='zone':e.reducer.zones[32]['ownerSeatId']=2
                else:e.reducer.objects[705]['grpId' if mode=='source_group' else 'parentId']=123456
                return value
            with patch.object(semantic_search,'project_request',side_effect=late):self.denied(self.report(e,m))

    def test_typed_predecessor_and_identical_full_replay_do_not_repair_old_search(self):
        e,m=self.ready();e.apply(wrap({'type':'GREMessageType_GameStateMessage','systemSeatIds':[1],
            'gameStateMessage':{'type':'GameStateType_Diff','gameStateId':2,'prevGameStateId':1.0}}))
        m=copy.deepcopy(m);m['msgId']=991;m['gameStateId']=2;e.apply(wrap(m))
        self.denied(self.report(e,m))

    def test_history_optin_freezes_before_response_and_preserves_default_report(self):
        rows=rows_for(self.samples[0])+[response(),successor()]
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'synthetic.log';path.write_text(''.join(json.dumps(row)+'\n' for row in rows))
            default=evaluate_shadow_history(path);enriched=evaluate_shadow_history(path,current_search_evidence=True)
            evidence=enriched.pop('current_search_request_evidence')
            self.assertEqual(evidence['reviewed_current_search_requests'],1);self.assertEqual(evidence['offered_request_scoped_items'],8)
            self.assertEqual(evidence['strictly_paired_search_responses'],1);self.assertEqual(evidence['historical_selected_item_matched'],1)
            self.assertIsNone(evidence['complete_search_legality']);self.assertIsNone(evidence['reviewed_complete_search_proposals'])
            for report in (default,enriched):report.pop('timings_ms')
            self.assertEqual(default,enriched)
            for bad in (1,'yes',None):
                with self.assertRaises(ValueError):evaluate_shadow_history(path,current_search_evidence=bad)

    def test_interrupted_history_cannot_borrow_later_selection(self):
        e,m=self.ready(history=True);e.apply({'payload':{'type':'ClientMessageType_UndoReq'}});e.apply(wrap(m));e.apply(response())
        self.assertEqual(e.search_counts['historical_selected_item_matched'],0)
        self.assertEqual(e.search_counts['strictly_paired_search_responses'],1)
        e,m=self.ready(history=True);e.publish(partial=True);e.apply(response())
        self.assertEqual(e.search_counts['historical_selected_item_matched'],0)

    def test_cli_optin_has_safe_separate_statistics(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'synthetic.log';rows=rows_for(self.samples[0])+[response()]
            path.write_text(''.join(json.dumps(row)+'\n' for row in rows))
            result=subprocess.run([sys.executable,'-m','mtgaplayer','evaluate-shadow-history',str(path),
                '--current-search-evidence'],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            report=json.loads(result.stdout);evidence=report['current_search_request_evidence']
            self.assertEqual(evidence['reviewed_current_search_requests'],1)
            self.assertEqual(evidence['historical_selected_item_matched'],1)
            for forbidden in ('PRIVATE_PROMPT_SENTINEL','135792468',str(path),'itemsToSearch','itemsFound'):
                self.assertNotIn(forbidden,result.stdout)


if __name__=='__main__':unittest.main()
