"""Two retained real projections; all envelopes and mutations are synthetic controls."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from mtgaplayer import current_cost_stage as cost
from mtgaplayer.decision_consumer import EXECUTION
from mtgaplayer.shadow_history import _Evaluation, evaluate_shadow_history
from test_current_cost_stage import FIXTURE, controls, rows_for, wrap


def payment_unit(message):
    return message['payCostsReq']['autoTapActionsReq']['autoTapSolutions'][0]['autoTapActions'][0]['manaPaymentOption']['mana'][0]


def change_output(message, **changes):
    """Keep MP72's structural join intact, isolating the new finite check."""
    payment_unit(message).update(changes)
    message['payCostsReq']['paymentActions']['actions'][1]['manaPaymentOptions'][0]['mana'][0].update(changes)


class ManaRequirementMatchTests(unittest.TestCase):
    def setUp(self):
        self.samples=json.loads(FIXTURE.read_text(encoding='utf8'))['samples']

    def ready(self, sample=None, mutate=None):
        sample=sample or self.samples[0];e=_Evaluation()
        for row in rows_for(sample):e.apply(row)
        message=controls(sample)
        if mutate:mutate(message)
        e.apply(wrap(message));return e,message

    def report(self, e, message):
        return cost.assess_current_cost_stage(e.consumer,e.reducer,message,mana_requirement_match=True)

    def denied(self, report):
        match=report['mana_requirement_match']
        self.assertNotEqual(match['status'],cost.MATCHED)
        self.assertIsNot(match['color_count_consistency'],True)
        for key in EXECUTION:self.assertIs(report[key],False);self.assertIs(match[key],False)
        for key in ('source_readiness_verified','complete_payment_verified','complete_legality_verified',
                    'full_action_legality_verified','ability_catalog_verified','all_payment_routes_verified'):
            self.assertIs(match[key],False)

    def test_two_real_current_projections_keep_separate_identity_and_order(self):
        bindings=[]
        for i,sample in enumerate(self.samples):
            e,message=self.ready(sample)
            # Synthetic request identities remain distinct; original private
            # request authentication belongs to the separate owner receipt.
            if i:
                message=controls(sample,991);e.apply(wrap(message))
            report=self.report(e,message);match=report['mana_requirement_match']
            self.assertEqual(match['status'],cost.MATCHED)
            self.assertEqual(match['requirement_amounts'],[{'color':['ManaColor_Black'],'count':1}])
            self.assertEqual(match['predictive_amounts'],[{'color':'ManaColor_Black','count':1}])
            self.assertEqual(match['predictive_solution_position'],0)
            self.assertEqual(match['matched_payment_action_positions'],[1])
            self.assertEqual([r['list_position'] for r in report['payment_actions']],list(range(10)))
            self.assertEqual(match['current_request_binding'],report['current_request_binding'])
            self.assertEqual(match['source_snapshot_ref'],report['source_snapshot_ref'])
            self.assertTrue(match['source_identity_consistency']);self.assertTrue(match['ability_identity_consistency'])
            self.assertTrue(match['source_readiness_unknown']);self.assertTrue(match['complete_payment_unknown'])
            self.assertFalse(match['source_readiness_verified']);self.assertFalse(match['complete_payment_verified'])
            self.assertFalse(match['full_action_legality_verified']);self.assertFalse(match['ability_catalog_verified'])
            self.assertNotEqual(report['mana_requirements'][0]['associated_object_ref'],match['payment_source_ref'])
            self.assertEqual(report['mana_requirements'][0]['associated_object_rule_role'],'unknown')
            self.assertIsNone(next(o for o in e.consumer.current_view()['decision_state']['visible_objects']
                if o['instance_id']==match['payment_source_ref'])['tapped'])
            for key in EXECUTION:self.assertIs(match[key],False)
            bindings.append(match['current_request_binding'])
        self.assertNotEqual(bindings[0],bindings[1])

    def test_default_cost_options_and_shadow_complete_returns_unchanged(self):
        for sample in self.samples:
            e,message=self.ready(sample)
            before=cost.assess_current_cost_stage(e.consumer,e.reducer,message)
            options=e.consumer.current_decision_options();policy=e.consumer.shadow_decision()
            enriched=self.report(e,message);enriched.pop('mana_requirement_match')
            self.assertEqual(enriched,before)
            self.assertEqual(e.consumer.current_decision_options(),options)
            self.assertEqual(e.consumer.shadow_decision(),policy)
            self.assertEqual(policy['reason'],'request_strategy_unsupported')
            changed=self.report(e,message);changed['mana_requirement_match']['requirement_amounts'].clear()
            self.assertEqual(self.report(e,message)['mana_requirement_match']['status'],cost.MATCHED)

    def test_old_structural_acceptance_does_not_prove_requirement_color_or_count(self):
        for changes in ({'color':['ManaColor_Red']},{'count':2}):
            for sample in self.samples:
                def mutate(m):m['payCostsReq']['manaCost'][0].update(changes)
                e,message=self.ready(sample,mutate)
                self.assertEqual(cost.assess_current_cost_stage(e.consumer,e.reducer,message)['status'],'observed')
                report=self.report(e,message);self.denied(report)
                self.assertEqual(report['mana_requirement_match']['status'],'violated_known_constraints')
                self.assertFalse(report['mana_requirement_match']['color_count_consistency'])

    def test_wrong_predictive_color_insufficient_and_excess_amount_are_not_offsets(self):
        for changes in ({'color':'ManaColor_Red'},{'count':2}):
            e,message=self.ready(mutate=lambda m:change_output(m,**changes))
            report=self.report(e,message);self.denied(report)
            self.assertEqual(report['mana_requirement_match']['reason'],'predictive_color_or_count_contradicted')
            self.assertFalse(report['mana_requirement_match']['all_payment_routes_verified'])

    def test_generic_mixed_and_multiple_requirement_or_solution_shapes_stay_unknown(self):
        def duplicate_requirement(m):m['payCostsReq']['manaCost'].append(copy.deepcopy(m['payCostsReq']['manaCost'][0]))
        def duplicate_solution(m):m['payCostsReq']['autoTapActionsReq']['autoTapSolutions']*=2
        mutations=(lambda m:m['payCostsReq']['manaCost'][0].update(color=['ManaColor_Generic']),
            lambda m:m['payCostsReq']['manaCost'][0].update(color=['ManaColor_Black','ManaColor_Red']),
            duplicate_requirement,duplicate_solution)
        for mutate in mutations:
            e,message=self.ready(mutate=mutate);report=self.report(e,message);self.denied(report)
            self.assertEqual(report['mana_requirement_match']['status'],'insufficient_evidence')

    def test_duplicate_sources_and_distinct_multi_source_routes_are_not_summed(self):
        for position in (None,0,3):
            def mutate(m):
                taps=m['payCostsReq']['autoTapActionsReq']['autoTapSolutions'][0]['autoTapActions']
                if position is None:taps.append(copy.deepcopy(taps[0]))
                else:
                    row=m['payCostsReq']['paymentActions']['actions'][position]
                    taps.append({'instanceId':row['instanceId'],'abilityGrpId':row['abilityGrpId'],
                        'manaPaymentOption':copy.deepcopy(row['manaPaymentOptions'][0])})
            e,message=self.ready(mutate=mutate);report=self.report(e,message);self.denied(report)
            self.assertEqual(len(report['mana_requirement_match']['matched_payment_action_positions']),2)
            self.assertEqual(report['mana_requirement_match']['status'],'insufficient_evidence')
        def duplicate_unit(m):
            d=m['payCostsReq']['autoTapActionsReq']['autoTapSolutions'][0]['autoTapActions'][0]
            d['manaPaymentOption']['mana']*=2
            m['payCostsReq']['paymentActions']['actions'][1]['manaPaymentOptions'][0]['mana']*=2
        e,message=self.ready(mutate=duplicate_unit);self.denied(self.report(e,message))

    def test_empty_solution_or_unit_does_not_claim_observed_predictive_output(self):
        for mode in ('empty_descriptors','empty_units'):
            def mutate(m):
                taps=m['payCostsReq']['autoTapActionsReq']['autoTapSolutions'][0]['autoTapActions']
                if mode=='empty_descriptors':taps.clear()
                else:
                    taps[0]['manaPaymentOption']['mana'].clear()
                    m['payCostsReq']['paymentActions']['actions'][1]['manaPaymentOptions'][0]['mana'].clear()
            e,message=self.ready(mutate=mutate);report=self.report(e,message);self.denied(report)
            self.assertEqual(report['status'],'observed')
            self.assertEqual(len(report['predictive_auto_tap_solutions']),1)
            self.assertFalse(report['mana_requirement_match']['predictive_output_observed'])
            self.assertEqual(report['mana_requirement_match']['predictive_amounts'],[])
            old=cost.assess_current_cost_stage(e.consumer,e.reducer,message)
            report.pop('mana_requirement_match');self.assertEqual(old,report)

    def test_descriptor_unit_source_and_ability_must_match_same_current_action(self):
        for changes in ({'srcInstanceId':1003},{'srcInstanceId':1001},{'abilityGrpId':999}):
            e,message=self.ready(mutate=lambda m:change_output(m,**changes))
            old=cost.assess_current_cost_stage(e.consumer,e.reducer,message)
            self.assertEqual(old['status'],'observed')
            report=self.report(e,message);self.denied(report)
            self.assertEqual(report['mana_requirement_match']['reason'],'predictive_source_or_ability_identity_contradicted')
        for field,value in (('instanceId',1003),('abilityGrpId',999)):
            def mutate(m):m['payCostsReq']['paymentActions']['actions'][1][field]=value
            e,message=self.ready(mutate=mutate);self.denied(self.report(e,message))

    def test_typed_quantities_descriptors_and_current_bindings_fail_closed(self):
        for value in (True,1.0,0):
            for where in ('requirement','unit','mana_id','ability','request','state','seat'):
                def mutate(m):
                    if where=='requirement':m['payCostsReq']['manaCost'][0]['count']=value
                    elif where=='unit':change_output(m,count=value)
                    elif where=='mana_id':change_output(m,manaId=value)
                    elif where=='ability':change_output(m,abilityGrpId=value)
                    # Existing protocol request IDs allow zero; use a negative
                    # ID for that boundary rather than invent a positive-only rule.
                    elif where=='request':m['msgId']=-1 if value==0 else value
                    elif where=='state':m['gameStateId']=value
                    else:m['systemSeatIds']=[value]
                e,message=self.ready(mutate=mutate)
                with self.subTest(where=where,value=value):self.denied(self.report(e,message))

    def test_current_source_zone_visibility_catalog_and_owner_counterexamples(self):
        for mode in ('zone','private','duplicate_member','catalog','controller','ability_card'):
            e,message=self.ready();source=e.reducer.objects[1002]
            if mode=='zone':e.reducer.zones[source['zoneId']]['type']='ZoneType_Hand'
            elif mode=='private':source['visibility']='Visibility_Private'
            elif mode=='duplicate_member':e.reducer.zones[source['zoneId']]['objectInstanceIds'].append(1002)
            elif mode=='catalog':source['grpId']+=1
            elif mode=='controller':source['controllerSeatId']=2
            else:source['type']='GameObjectType_Ability'
            with self.subTest(mode=mode):self.denied(self.report(e,message))

    def test_mutated_message_and_foreign_request_cannot_borrow_prediction(self):
        e,message=self.ready()
        for key,value in (('msgId',991),('gameStateId',2),('systemSeatIds',[2])):
            bad=copy.deepcopy(message);bad[key]=value;self.denied(self.report(e,bad))
        bad=copy.deepcopy(message);bad['payCostsReq']['manaCost'][0]['count']=2
        self.denied(self.report(e,bad))
        replacement=controls(self.samples[1],991);e.apply(wrap(replacement))
        self.denied(self.report(e,message))
        self.assertEqual(self.report(e,replacement)['mana_requirement_match']['status'],cost.MATCHED)

    def test_consumed_and_retransmitted_request_cannot_use_future_submission(self):
        e,message=self.ready();frozen=copy.deepcopy(self.report(e,message))
        response={'payload':{'type':'ClientMessageType_PerformAutoTapActionsResp','respId':990,
            'gameStateId':1,'performAutoTapActionsResp':{'index':0}}}
        e.apply(response);self.denied(self.report(e,message))
        e.apply(wrap(message));self.denied(self.report(e,message))
        self.assertEqual(frozen['mana_requirement_match']['status'],cost.MATCHED)
        self.assertFalse(frozen['mana_requirement_match']['historical_response_used'])

    def test_cancel_undo_full_broadcast_and_mixed_replays_interrupt_only_new_proof(self):
        for mode in ('cancel','undo','full','broadcast','mixed','unsupported'):
            e,message=self.ready()
            if mode=='full':e.apply(rows_for(self.samples[0])[2])
            elif mode=='broadcast':
                other=copy.deepcopy(message);other['systemSeatIds']=[1,2];e.apply(wrap(other))
            elif mode=='mixed':e.apply({**wrap(message),'payload':{'type':'ClientMessageType_UIMessage'}})
            else:e.apply({'payload':{'type':{'cancel':'ClientMessageType_CancelActionReq',
                'undo':'ClientMessageType_UndoActionReq','unsupported':'ClientMessageType_UnknownReq'}[mode]}})
            with self.subTest(mode=mode):
                self.denied(self.report(e,message))
                old=cost.assess_current_cost_stage(e.consumer,e.reducer,message)
                self.assertEqual(old['status'],'observed')
                enriched=self.report(e,message);enriched.pop('mana_requirement_match');self.assertEqual(enriched,old)
                self.assertNotIn('_cost_evidence_interrupted',json.dumps(e.reducer.document(include_decision_state=True)))
                e.apply(wrap(message));self.denied(self.report(e,message))
        e,message=self.ready();e.reducer.observer=None
        other=copy.deepcopy(message);other['systemSeatIds']=[1,2]
        e.reducer.apply(wrap(other));self.denied(self.report(e,message))

    def test_partial_gap_reset_conflict_stop_and_float_predecessor_revoke(self):
        for mode in ('partial','gap','reset','conflict','stop','float'):
            e,message=self.ready()
            if mode=='partial':e.publish(partial=True)
            elif mode=='reset':e.reducer.reset(2)
            elif mode=='conflict':e.reducer.conflict=True
            elif mode=='stop':
                for event in e.publisher.stop('sample_limit'):e.consumer.accept_event(event)
            else:
                e.apply(wrap({'type':'GREMessageType_GameStateMessage','systemSeatIds':[1],
                    'gameStateMessage':{'type':'GameStateType_Diff','gameStateId':2,
                        'prevGameStateId':1.0 if mode=='float' else 0}}))
                if mode=='float':
                    message=controls(self.samples[0],991);message['gameStateId']=2;e.apply(wrap(message))
            with self.subTest(mode=mode):self.denied(self.report(e,message))

    def test_expiry_consumption_and_interruption_during_new_calculation_discard(self):
        for mode in ('expire','consume','cancel','object_change'):
            e,message=self.ready();original=cost._review_mana_requirement
            def change(*args):
                result=original(*args)
                if mode=='expire':e.ordinal+=10**15
                elif mode=='consume':e.reducer.apply({'payload':{'type':'ClientMessageType_PerformAutoTapActionsResp',
                    'respId':990,'gameStateId':1}})
                elif mode=='cancel':e.reducer.apply({'payload':{'type':'ClientMessageType_CancelActionReq'}})
                else:e.reducer.objects[1002]['grpId']+=1
                return result
            with patch.object(cost,'_review_mana_requirement',side_effect=change):self.denied(self.report(e,message))

    def test_history_optin_units_default_compatibility_and_private_values_omitted(self):
        rows=rows_for(self.samples[0])+[wrap(controls(self.samples[0]))]
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'PRIVATE_PATH.log';path.write_text(''.join(json.dumps(r)+'\n' for r in rows),encoding='utf8')
            a=evaluate_shadow_history(path,current_cost_stages=True)
            b=evaluate_shadow_history(path,current_cost_stages=True,mana_requirement_match=True)
            report=b.pop('mana_requirement_consistency')
            a.pop('timings_ms');b.pop('timings_ms');self.assertEqual(a,b)
            self.assertEqual(report['authenticated_requests'],1);self.assertEqual(report['reviewed_amount_matches'],1)
            self.assertEqual(report['reviewed_contradictions'],0);self.assertEqual(report['unsupported_combination_shapes'],0)
            self.assertIsNone(report['source_readiness_verified']);self.assertIsNone(report['complete_payment_verified'])
            self.assertEqual(a['current_cost_stage_evidence']['historically_paired_cost_responses'],0)
            for flags,code in ((['--mana-requirement-match'],1),(['--current-cost-stages','--mana-requirement-match'],0)):
                result=subprocess.run([sys.executable,'-m','mtgaplayer','evaluate-shadow-history',str(path),*flags],capture_output=True,text=True)
                self.assertEqual(result.returncode,code,result.stdout+result.stderr)
                if code==0:
                    self.assertEqual(json.loads(result.stdout)['mana_requirement_consistency'],report)
                    for secret in ('PRIVATE_PATH','PRIVATE_SENTINEL','srcInstanceId','associated_object_ref'):
                        self.assertNotIn(secret,result.stdout)
        for kwargs in ({'mana_requirement_match':True},{'current_cost_stages':True,'mana_requirement_match':1}):
            with self.assertRaises(ValueError):evaluate_shadow_history(FIXTURE,**kwargs)
        e,message=self.ready()
        with self.assertRaises(ValueError):cost.assess_current_cost_stage(e.consumer,e.reducer,message,mana_requirement_match=1)

    def test_stronger_continuity_refusal_preserves_old_history_shape_and_counts(self):
        rows=rows_for(self.samples[0])
        rows.append(wrap({'type':'GREMessageType_GameStateMessage','systemSeatIds':[1],
            'gameStateMessage':{'type':'GameStateType_Diff','gameStateId':2,'prevGameStateId':1.0}}))
        message=controls(self.samples[0]);message['gameStateId']=2;rows.append(wrap(message))
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'synthetic-float-predecessor.log'
            path.write_text(''.join(json.dumps(r)+'\n' for r in rows),encoding='utf8')
            old=evaluate_shadow_history(path,current_cost_stages=True)
            new=evaluate_shadow_history(path,current_cost_stages=True,mana_requirement_match=True)
            report=new.pop('mana_requirement_consistency')
            old.pop('timings_ms');new.pop('timings_ms');self.assertEqual(old,new)
            self.assertEqual(report['reviewed_mana_requests'],1)
            self.assertEqual(report['observed_mana_requirements'],1)
            self.assertEqual(report['observed_predictive_solutions'],1)
            self.assertEqual(report['unreviewed_identity_or_continuity'],1)
            self.assertEqual(report['unreviewed_cost_stage_requests'],0)
            self.assertEqual(report['unsupported_combination_shapes'],0)
            self.assertEqual(report['reviewed_amount_matches'],0)


if __name__=='__main__':unittest.main()
