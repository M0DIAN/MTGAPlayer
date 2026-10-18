"""Real portable projections; reconstructed envelopes/lifecycle controls synthetic."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from mtgaplayer import current_cost_stage as cost
from mtgaplayer.shadow_history import _Evaluation, evaluate_shadow_history
from mtgaplayer.decision_consumer import EXECUTION
from test_combat_frontier import baseline, save
from test_raw_log import state as raw_state
from test_semantic_effect_cost import request as nonmana_request

FIXTURE=Path(__file__).parent/'fixtures/current_mana_cost_real_v1.json'


def raw_action(literal):
    result={'actionType':literal['action_type'],**literal['identifier_refs'],**literal['flags'],
        **copy.deepcopy(literal['parameters'])}
    for key in literal['observed_empty_parameters']:
        result[key]={'autoTapActions':[]} if key=='autoTapSolution' else []
    return result


def controls(sample, ident=990):
    """Synthetic enclosing message, not recovered/authenticated original bytes."""
    p=sample['projection']
    return {'type':'GREMessageType_PayCostsReq','systemSeatIds':[1],'msgId':ident,'gameStateId':1,
        'prompt':{'promptId':123,'parameters':[{'parameterName':'PRIVATE_SENTINEL',
            'type':'ParameterType_NonLocalizedString','stringValue':'PRIVATE_SENTINEL'}]},
        'allowCancel':'AllowCancel_Abort','allowUndo':True,'payCostsReq':{
            'manaCost':[{**r['amount'],'objectId':r['associated_object_ref']} for r in p['mana_requirements']],
            'paymentActions':{'actions':[raw_action(r['action']) for r in p['payment_actions']]},
            'paymentSelection':{'context':'SelectionContext_NonMana_Payment','optionContext':'OptionContext_Payment',
                'listType':'SelectionListType_Dynamic','idType':'IdType_InstanceId',
                'validationType':'SelectionValidationType_NonRepeatable','minWeight':-2147483648,'maxWeight':2147483647},
            'autoTapActionsReq':{'autoTapSolutions':[copy.deepcopy(r['solution']) for r in p['predictive_auto_tap_solutions']]}}}


def wrap(message):return {'greToClientEvent':{'greToClientMessages':[message]}}


def rows_for(sample):
    rows=baseline();gs=raw_state(rows[2]);stack=9000
    gs['zones'].append({'zoneId':stack,'type':'ZoneType_Stack','visibility':'Visibility_Public','objectInstanceIds':[]})
    gs['gameObjects']=[]
    for obj in sample['visible_objects']:
        gs['gameObjects'].append({'instanceId':obj['instance_id'],'grpId':obj['card_id'],
            'type':'GameObjectType_Card','zoneId':stack if obj['zone']=='ZoneType_Stack' else 28,
            'ownerSeatId':1 if obj['owner_seat']==sample['self_seat'] else 2,
            'controllerSeatId':1 if obj['controller_seat']==sample['self_seat'] else 2,'visibility':'Visibility_Public'})
    for zone in gs['zones']:
        zone['objectInstanceIds']=[o['instanceId'] for o in gs['gameObjects'] if o['zoneId']==zone['zoneId']]
    return rows


class CurrentCostStageTests(unittest.TestCase):
    def setUp(self):
        self.fixture=json.loads(FIXTURE.read_text(encoding='utf8'));self.sample=self.fixture['samples'][0]

    def ready(self):
        e=_Evaluation(current_cost_stages=True)
        for row in rows_for(self.sample):e.apply(row)
        msg=controls(self.sample);e.apply(wrap(msg));return e,msg

    def denied(self, report):
        self.assertEqual(report['status'],'insufficient_evidence')
        self.assertIsNone(report['current_request_binding']);self.assertEqual(report['local_candidates'],[])

    def safe(self, report):
        for key in EXECUTION:self.assertIs(report[key],False,key)
        self.assertFalse(report['complete_payment_verified']);self.assertFalse(report['explicit_parent_cost_link_verified'])
        self.assertFalse(report['historical_parent_current']);self.assertIsNone(report['historical_parent_context'])

    def test_real_portable_current_association_preserves_order_and_unknown_roles(self):
        self.assertFalse(self.fixture['raw_source_auth_revalidated_by_portable_replay'])
        for sample in self.fixture['samples']:
            message=controls(sample);message['systemSeatIds']=[sample['self_seat']]
            result=cost.project_mana_stage(message,sample['visible_objects'],sample['self_seat'])
            self.assertEqual(result,sample['projection'])
            self.assertEqual(cost.project_mana_stage(message,sample['visible_objects'],sample['self_seat']),result)
            self.assertEqual([r['list_position'] for r in result['payment_actions']],list(range(10)))
            self.assertEqual(len(result['predictive_auto_tap_solutions']),1)
            self.assertEqual(result['mana_requirements'][0]['associated_object_rule_role'],'unknown')

    def test_quantity_reference_identity_and_unknown_field_counterexamples(self):
        message=controls(self.sample)
        mutations=(
            lambda m:m['payCostsReq']['manaCost'][0].update(objectId=True),
            lambda m:m['payCostsReq']['manaCost'][0].update(objectId=1001.0),
            lambda m:m['payCostsReq']['manaCost'][0].update(objectId=999999),
            lambda m:m['payCostsReq']['manaCost'][0].update(count=True),
            lambda m:m['payCostsReq']['manaCost'][0].update(extra=True),
            lambda m:m['payCostsReq'].update(manaCost=[]),
            lambda m:m['payCostsReq']['paymentSelection'].update(minSel=0),
            lambda m:m['payCostsReq']['paymentActions']['actions'][0].update(grpId=999999),
            lambda m:m['payCostsReq']['paymentActions']['actions'][0].update(actionType='ActionType_Cast'),
            lambda m:m['payCostsReq']['autoTapActionsReq']['autoTapSolutions'][0]['autoTapActions'][0].update(abilityGrpId=999999),
        )
        for mutate in mutations:
            bad=copy.deepcopy(message);mutate(bad)
            with self.subTest(mutate=mutate),self.assertRaises(ValueError):
                cost.project_mana_stage(bad,self.sample['visible_objects'],1)
        for visible in ([],self.sample['visible_objects']+[self.sample['visible_objects'][0]]):
            with self.assertRaises(ValueError):cost.project_mana_stage(message,visible,1)

    def test_current_api_uses_existing_options_and_never_constructs_mana_choice(self):
        e,msg=self.ready();before=e.consumer.current_decision_options();policy=e.consumer.shadow_decision()
        result=cost.assess_current_cost_stage(e.consumer,e.reducer,msg);self.safe(result)
        self.assertEqual(result['status'],'observed');self.assertEqual(result['cost_request_profile'],cost.MANA_PROFILE)
        self.assertEqual(result['current_request_binding'],before['request_binding'])
        self.assertEqual(result['source_snapshot_ref'],before['source_snapshot_ref'])
        self.assertEqual(result['local_candidates'],[]);self.assertIsNone(result['local_candidate_coverage'])
        self.assertEqual(e.consumer.current_decision_options(),before);self.assertEqual(e.consumer.shadow_decision(),policy)
        self.assertEqual(policy['reason'],'request_strategy_unsupported')
        bad=copy.deepcopy(before);bad['execution_ready']=True
        with patch.object(e.consumer,'current_decision_options',return_value=bad):
            self.denied(cost.assess_current_cost_stage(e.consumer,e.reducer,msg))

    def test_consumption_retransmission_and_new_identity_do_not_restore_old_stage(self):
        e,msg=self.ready();old=cost.assess_current_cost_stage(e.consumer,e.reducer,msg)['source_snapshot_ref']
        e.apply({'payload':{'type':'ClientMessageType_PerformAutoTapActionsResp','respId':990,'gameStateId':1,
            'performAutoTapActionsResp':{'index':0}}})
        self.denied(cost.assess_current_cost_stage(e.consumer,e.reducer,msg))
        after=e.consumer.current_view()['current_snapshot_ref']
        self.assertNotEqual(after,old)
        self.assertIsNone(after['binding']['request_id'])
        e.apply(wrap(msg));self.denied(cost.assess_current_cost_stage(e.consumer,e.reducer,msg))
        fresh=controls(self.sample,991);e.apply(wrap(fresh))
        result=cost.assess_current_cost_stage(e.consumer,e.reducer,fresh)
        self.assertEqual(result['status'],'observed');self.assertNotEqual(result['source_snapshot_ref'],old)
        self.denied(cost.assess_current_cost_stage(e.consumer,e.reducer,msg))

    def test_wrong_current_message_scope_and_mutated_snapshot_are_rejected(self):
        e,msg=self.ready()
        for key,value in (('msgId',991),('gameStateId',True),('systemSeatIds',[2])):
            bad=copy.deepcopy(msg);bad[key]=value;self.denied(cost.assess_current_cost_stage(e.consumer,e.reducer,bad))
        # Reproduces an empty authoritative projection with nonempty Consumer
        # data, not an invented real request or valid payment.
        original=e.reducer.document
        def empty(*a,**k):
            d=original(*a,**k);d['current']['objects']=[];return d
        with patch.object(e.reducer,'document',side_effect=empty):
            self.assertEqual(cost.assess_current_cost_stage(e.consumer,e.reducer,msg)['reason'],
                'current_visible_projection_disagrees_with_reducer')

    def test_lease_or_raw_consumption_during_projection_discards_result(self):
        for expire in (True,False):
            e,msg=self.ready();original=cost.project_mana_stage
            def change(*args):
                result=original(*args)
                if expire:e.ordinal+=10**15
                else:e.reducer.apply({'payload':{'type':'ClientMessageType_PerformAutoTapActionsResp','respId':990,'gameStateId':1}})
                return result
            with patch.object(cost,'project_mana_stage',side_effect=change):
                self.denied(cost.assess_current_cost_stage(e.consumer,e.reducer,msg))

    def test_partial_reset_conflict_and_stop_withhold_stage(self):
        for event in ('partial','reset','conflict','stop'):
            e,msg=self.ready()
            if event=='partial':e.publish(partial=True)
            elif event=='reset':e.reducer.reset(2)
            elif event=='conflict':e.reducer.conflict=True
            else:
                for row in e.publisher.stop('sample_limit'):self.assertTrue(e.consumer.accept_event(row))
            with self.subTest(event=event):self.denied(cost.assess_current_cost_stage(e.consumer,e.reducer,msg))

    def test_existing_nonmana_sixteen_candidates_remain_current_and_separate(self):
        e=_Evaluation();rows=baseline();gs=raw_state(rows[2]);base=copy.deepcopy(gs['gameObjects'][0])
        gs['gameObjects']=[{**base,'instanceId':i} for i in range(701,717)]
        for z in gs['zones']:z['objectInstanceIds']=list(range(701,717)) if z['zoneId']==28 else []
        for r in rows:e.apply(r)
        wrapped=nonmana_request(tuple(range(701,717)));msg=wrapped['greToClientEvent']['greToClientMessages'][0]
        e.apply(wrapped);result=cost.assess_current_cost_stage(e.consumer,e.reducer,msg)
        self.assertEqual(result['status'],'observed');self.assertEqual(len(result['local_candidates']),16)
        self.assertEqual(result['mana_requirements'],[]);self.safe(result)
        bad=e.consumer.current_decision_options();bad['options'][0]['input_sent']=True
        with patch.object(e.consumer,'current_decision_options',return_value=bad):
            self.denied(cost.assess_current_cost_stage(e.consumer,e.reducer,msg))

    def test_history_optin_freeze_no_future_pairing_and_bounded_cli(self):
        rows=rows_for(self.sample)+[wrap(controls(self.sample))]
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'PRIVATE_PATH.Player.log';save(path,rows)
            a=evaluate_shadow_history(path);b=evaluate_shadow_history(path,current_cost_stages=True)
            for key in ('versions','timings_ms'):a.pop(key);b.pop(key)
            stats=b.pop('current_cost_stage_evidence');self.assertEqual(a,b)
            self.assertEqual(stats['reviewed_mana_payment_stage'],1);self.assertEqual(stats['historically_paired_cost_responses'],0)
            self.assertIsNone(stats['complete_payment_verified']);self.assertEqual(stats['observed_payment_action_rows'],10)
            rows.append({'payload':{'type':'ClientMessageType_PerformAutoTapActionsResp','respId':991,'gameStateId':1}})
            save(path,rows);wrong=evaluate_shadow_history(path,current_cost_stages=True)
            self.assertEqual(wrong['current_cost_stage_evidence']['historically_paired_cost_responses'],0)
            rows.append({'payload':{'type':'ClientMessageType_PerformAutoTapActionsResp','respId':990,'gameStateId':1}})
            save(path,rows);good=evaluate_shadow_history(path,current_cost_stages=True)
            self.assertEqual(good['current_cost_stage_evidence']['historically_paired_cost_responses'],1)
            self.assertEqual(good['current_cost_stage_evidence']['strictly_associated_parent_cost_stages'],0)
            run=subprocess.run([sys.executable,'-m','mtgaplayer','evaluate-shadow-history',str(path),
                '--current-cost-stages'],capture_output=True,text=True,timeout=20)
            self.assertEqual(run.returncode,0,run.stderr);output=json.loads(run.stdout)
            self.assertEqual(output['current_cost_stage_evidence'],good['current_cost_stage_evidence'])
            self.assertNotIn('PRIVATE_',run.stdout);self.assertNotIn(str(path),run.stdout)
        with self.assertRaises(ValueError):evaluate_shadow_history(FIXTURE,current_cost_stages=1)
