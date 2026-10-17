"""Real request-only projection; all raw mutations below are synthetic controls."""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mtgaplayer.action_target_menus import CURRENT_PROFILE,CURRENT_SCOPE,CURRENT_VERSION
from mtgaplayer.cli import replay,watch_decision_events
from mtgaplayer.choice_validation import validate_proposed_choice,assess_current_choice,load_proposal
from mtgaplayer.choice_candidates import enumerate_known_candidates
from mtgaplayer.decision_consumer import DecisionConsumer,EXECUTION,_state
from mtgaplayer.raw_log import RawReducer
from mtgaplayer.response_evidence import _current_verified_raw_request
from test_decision_publisher import ManualClock,poll_events,append
from test_action_frontier import save

ROOT=Path(__file__).resolve().parents[1]
FIXTURE=ROOT/'tests/fixtures/decision_state_activate_target_member_real_v7.json'
RAW=ROOT/'tests/fixtures/player_log_activate_generic_two.jsonl'


class ActivateTargetMemberTests(unittest.TestCase):
    def setUp(self):
        self.real=json.loads(FIXTURE.read_text())
        self.state=self.real['before_response'];self.proposal=self.real['proposal']
        self.rows=[json.loads(s) for s in RAW.read_text().splitlines()]
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.path=Path(tmp.name)/'synthetic.log'

    def evidence(self,state=None):
        return (state or self.state)['legal_action_space']['request_parameters']

    def result(self,state=None,proposal=None):
        return validate_proposed_choice(state or self.state,proposal or self.proposal)

    def unknown(self,result,reason=None):
        self.assertEqual(result['known_constraints'],'insufficient_evidence')
        if reason:self.assertIn(reason,result['reasons'])
        self.assertTrue(all(result[k] is False for k in EXECUTION))

    def raw(self,rows=None,version=7):
        save(self.path,rows or self.rows[:5])
        return replay(self.path,format='player-log',decision_state_version=version)

    def targets(self,rows):
        return rows[4]['greToClientEvent']['greToClientMessages'][0]['actionsAvailableReq']['actions'][2]['targets'][0]['targets']

    def for_row(self,state,position=2):
        row=self.evidence(state)['rows'][position];menu=row['target_menu']
        return {'request_identity':copy.deepcopy(state['binding']),'list_position':position,
            'proposed_activate_target_member':{'identifier_refs':copy.deepcopy(row['identifier_refs']),
                'target_idx':menu['target_idx'],'object_ref':menu['offered_visible_target_refs'][0]}}

    def test_real_request_only_member_has_no_quantity_or_execution_authority(self):
        e=self.evidence();self.assertEqual(e['schema_version'],CURRENT_VERSION)
        self.assertEqual(e['profile'],CURRENT_PROFILE)
        self.assertEqual(len(e['rows']),17)
        self.assertEqual([r['list_position'] for r in e['rows'] if r['target_menu'] is not None],[6])
        result=self.result();self.assertEqual(result['validation_scope'],CURRENT_SCOPE)
        self.assertEqual(result['known_constraints'],'verified_known_constraints')
        self.assertEqual(result['known_checks']['target_quantity'],'insufficient_evidence')
        for k in ('target_minimum','target_maximum','target_selection_count'):self.assertIsNone(result[k])
        for k in ('target_domain_complete_verified','target_selection_legality_verified',
                  'target_set_combinations_enumerated','complete_costs_verified','complete_payment_verified',
                  'global_target_legality_verified','historical_response_used',*EXECUTION):
            self.assertIs(result[k],False,k)
        candidates=enumerate_known_candidates(self.state)
        self.assertEqual(candidates['status'],'insufficient_evidence')
        self.assertEqual(candidates['reason'],'target_member_proposal_required')
        self.assertEqual(candidates['candidates'],[])

    def test_real_response_and_result_do_not_supply_old_or_alternative_proposal(self):
        for k in ('after_response','after_result'):
            self.unknown(self.result(self.real[k]))
        for position in range(17):
            if position==6:continue
            p=copy.deepcopy(self.proposal);p['list_position']=position
            self.unknown(self.result(proposal=p))
        history=json.loads((FIXTURE.parent/'semantic_activate_targets_real_v10.json').read_text())
        self.assertEqual(history['samples'][0]['request']['payload']['selected_position'],6)
        # Historical suffix is not a supported current proposal/state field.
        state=copy.deepcopy(self.state);self.evidence(state)['historical_suffix']=history['samples'][0]['trace']
        self.unknown(self.result(state),'proposal_or_state_invalid')

    def test_wrong_binding_and_exact_action_identity_cannot_be_borrowed(self):
        for key in ('match','game','self_seat','source_generation','game_state_id','request_id','request_type'):
            p=copy.deepcopy(self.proposal);v=p['request_identity'][key]
            p['request_identity'][key]=('different' if isinstance(v,str) else 2 if key=='self_seat' else v+1)
            self.unknown(self.result(proposal=p))
        for key in self.proposal['proposed_activate_target_member']['identifier_refs']:
            p=copy.deepcopy(self.proposal);p['proposed_activate_target_member']['identifier_refs'][key]+=1
            self.unknown(self.result(proposal=p),'proposal_binding_invalid')

    def test_literal_slot_and_membership_violations_are_scoped_not_global_illegality(self):
        for key in ('target_idx','object_ref'):
            p=copy.deepcopy(self.proposal);p['proposed_activate_target_member'][key]+=999999
            result=self.result(proposal=p)
            self.assertEqual(result['known_constraints'],'violated_known_constraints')
            self.assertFalse(result['global_target_legality_verified'])
            self.assertFalse(result['target_selection_legality_verified'])
        p=copy.deepcopy(self.proposal);p['proposed_activate_target_member']['object_ref']=True
        self.unknown(self.result(proposal=p),'proposal_or_state_invalid')

    def test_only_reviewed_string_highlight_is_discarded(self):
        rows=copy.deepcopy(self.rows[:5])
        for candidate in self.targets(rows):candidate['highlight']='PRIVATE_PRESENTATION_SENTINEL'
        d=self.raw(rows);state=d['decision_state'];e=self.evidence(state)
        self.assertIsNotNone(e['rows'][2]['target_menu'])
        self.assertEqual(self.result(state,self.for_row(state))['known_constraints'],'verified_known_constraints')
        self.assertNotIn('PRIVATE_PRESENTATION_SENTINEL',json.dumps(state))
        legacy=replay(self.path,format='player-log',observed_action_target_menus=True)
        self.assertNotIn(2,[r['list_position'] for r in legacy['observed_action_target_menus']['menus']])
        for bad in (True,1,None,{},[],1.0):
            mutated=copy.deepcopy(rows);self.targets(mutated)[0]['highlight']=bad
            self.assertIsNone(self.evidence(self.raw(mutated)['decision_state'])['rows'][2]['target_menu'])
        mutated=copy.deepcopy(rows);self.targets(mutated)[0]['extra']='PRIVATE_SENTINEL'
        state=self.raw(mutated)['decision_state']
        self.assertIsNone(self.evidence(state)['rows'][2]['target_menu'])
        self.assertNotIn('PRIVATE_SENTINEL',json.dumps(state))

    def test_duplicate_hidden_crossed_refs_and_unreviewed_quantity_withhold_menu(self):
        for mode in ('duplicate_target','hidden','duplicate_action','slot_extra','slot_bool','crossed_zone'):
            rows=copy.deepcopy(self.rows[:5]);targets=self.targets(rows)
            actions=rows[4]['greToClientEvent']['greToClientMessages'][0]['actionsAvailableReq']['actions']
            if mode=='duplicate_target':targets.append(copy.deepcopy(targets[0]))
            elif mode=='hidden':targets[0]['targetInstanceId']=987654321
            elif mode=='duplicate_action':actions.append(copy.deepcopy(actions[2]))
            elif mode=='slot_extra':actions[2]['targets'][0]['minTargets']=1
            elif mode=='slot_bool':actions[2]['targets'][0]['targetIdx']=True
            else:
                objects=rows[2]['greToClientEvent']['greToClientMessages'][0]['gameStateMessage']['gameObjects']
                target=next(o for o in objects if o['instanceId']==targets[0]['targetInstanceId'])
                target['zoneId']=999999
            state=self.raw(rows)['decision_state']
            if state is not None and self.evidence(state) is not None:
                self.assertIsNone(self.evidence(state)['rows'][2]['target_menu'],mode)
            else:self.assertTrue(mode=='crossed_zone')

    def test_current_public_source_owner_controller_and_ability_list_gates(self):
        baseline=self.raw()['decision_state'];original_proposal=self.for_row(baseline)
        for mode in ('owner','controller','missing_pair','duplicate_pair','contradicted_pair','private_source'):
            rows=copy.deepcopy(self.rows[:5])
            actions=rows[4]['greToClientEvent']['greToClientMessages'][0]['actionsAvailableReq']['actions']
            objects=rows[2]['greToClientEvent']['greToClientMessages'][0]['gameStateMessage']['gameObjects']
            source=next(o for o in objects if o['instanceId']==actions[2]['instanceId'])
            if mode=='owner':source['ownerSeatId']=2
            elif mode=='controller':source['controllerSeatId']=2
            elif mode=='private_source':source['visibility']='Visibility_Private'
            elif mode=='missing_pair':source.pop('uniqueAbilities')
            elif mode=='contradicted_pair':
                next(p for p in source['uniqueAbilities'] if p['id']==actions[2]['uniqueAbilityId'])['grpId']+=999
            else:source['uniqueAbilities'].append(copy.deepcopy(next(p for p in source['uniqueAbilities'] if p['id']==actions[2]['uniqueAbilityId'])))
            doc=self.raw(rows);state=doc['decision_state']
            if state is None:
                self.assertFalse(doc['current']['valid']);continue
            if self.evidence(state) is None or self.evidence(state)['rows'][2]['target_menu'] is None:
                self.unknown(self.result(state,original_proposal));continue
            result=self.result(state,self.for_row(state))
            if mode=='contradicted_pair':self.assertEqual(result['known_constraints'],'violated_known_constraints')
            else:self.unknown(result)

    def test_consumer_rejects_crossed_version_metadata_duplicates_and_frontier_identity(self):
        for mutate in (
            lambda s:s.update(schema_version='mtgaplayer.decision-state.v6'),
            lambda s:self.evidence(s).update(schema_version='mtgaplayer.request-parameters.v3'),
            lambda s:self.evidence(s).update(historical_response_used=True),
            lambda s:self.evidence(s)['binding'].update(request_id=999),
            lambda s:self.evidence(s)['binding'].update(self_seat=True),
            lambda s:self.evidence(s)['binding'].update(source_generation=True),
            lambda s:self.evidence(s)['binding'].update(game=True),
            lambda s:s['visible_objects'].append(copy.deepcopy(s['visible_objects'][0])),
            lambda s:self.evidence(s)['public_battlefield_refs'].append(self.evidence(s)['public_battlefield_refs'][0]),
            lambda s:self.evidence(s)['rows'][6]['target_menu'].update(selection_count=1),
            lambda s:self.evidence(s)['rows'][6]['target_menu']['offered_visible_target_refs'].append(999999),
            lambda s:self.evidence(s)['rows'][6]['identifier_refs'].update(uniqueAbilityId=999),
            lambda s:self.evidence(s)['rows'][6]['target_menu'].update(source_visible_object_ref=999),
            lambda s:self.evidence(s)['rows'][6]['target_menu'].update(source_visible_object_ref=True),
            lambda s:s['execution'].update(execution_ready=True),
            lambda s:next(o for o in s['visible_objects'] if o['instance_id']==self.proposal['proposed_activate_target_member']['identifier_refs']['instanceId']).update(card_id=999999),
        ):
            state=copy.deepcopy(self.state);mutate(state)
            self.unknown(self.result(state),'proposal_or_state_invalid')

    def test_raw_digest_wrong_seat_and_same_header_conflict_fail_closed(self):
        reducer=RawReducer(include_request_parameters=True,include_targeted_activate=True);reducer.reset(1)
        for r in self.rows[:5]:reducer.apply(r)
        msg=self.rows[4]['greToClientEvent']['greToClientMessages'][0]
        self.assertIsNotNone(_current_verified_raw_request(reducer,msg))
        for mode in ('digest','seat','state'):
            altered=copy.deepcopy(msg)
            if mode=='digest':altered['actionsAvailableReq']['actions'][2]['targets'][0]['targets'][0]['targetInstanceId']+=1
            elif mode=='seat':altered['systemSeatIds']=[2]
            else:altered['gameStateId']+=1
            self.assertIsNone(_current_verified_raw_request(reducer,altered))
        conflict=copy.deepcopy(self.rows[:5]);extra=copy.deepcopy(conflict[4]);self.targets(conflict)[0]['highlight']='new'
        self.assertIsNone(self.raw(conflict+[extra])['decision_state'])

    def test_existing_graph_slot_and_offer_count_must_agree_without_quantity_inference(self):
        for mode in ('slot','count'):
            state=copy.deepcopy(self.state);proposal=copy.deepcopy(self.proposal)
            menu=self.evidence(state)['rows'][6]['target_menu']
            if mode=='slot':
                menu['target_idx']+=1;proposal['proposed_activate_target_member']['target_idx']+=1
            else:
                extra=next(r for r in self.evidence(state)['public_battlefield_refs'] if r not in menu['offered_visible_target_refs'])
                menu['offered_visible_target_refs'].append(extra);menu['offered_visible_target_count']+=1
                proposal['proposed_activate_target_member']['object_ref']=extra
            self.unknown(self.result(state,proposal),'proposal_or_state_invalid')

    def test_boolean_source_cannot_impersonate_integer_one(self):
        source=self.proposal['proposed_activate_target_member']['identifier_refs']['instanceId']
        def remap(value):
            if type(value) is int and value==source:return 1
            if isinstance(value,dict):return {k:remap(v) for k,v in value.items()}
            if isinstance(value,list):return [remap(v) for v in value]
            return value
        state=remap(self.state);proposal=remap(self.proposal)
        self.assertEqual(self.result(state,proposal)['known_constraints'],'verified_known_constraints')
        self.evidence(state)['rows'][6]['target_menu']['source_visible_object_ref']=True
        self.unknown(self.result(state,proposal),'proposal_or_state_invalid')

    def test_current_consumer_response_replacement_partial_gap_and_stop_revoke(self):
        for mode in ('response','replacement','partial','gap','stop'):
            save(self.path,self.rows[:4]);clock=ManualClock()
            stream=watch_decision_events(self.path,interval=0,samples=4,clock_ns=clock,decision_state_version=7)
            consumer=DecisionConsumer(clock_ns=clock)
            for event in poll_events(stream):self.assertTrue(consumer.accept_event(event))
            append(self.path,[self.rows[4]])
            for event in poll_events(stream):self.assertTrue(consumer.accept_event(event))
            state=consumer.current_view()['decision_state'];p=self.for_row(state)
            self.assertEqual(assess_current_choice(consumer,p)['known_constraints'],'verified_known_constraints')
            if mode=='response':append(self.path,[self.rows[5]])
            elif mode=='replacement':
                replacement=copy.deepcopy(self.rows[4]);replacement['greToClientEvent']['greToClientMessages'][0]['msgId']+=100
                append(self.path,[replacement])
            elif mode=='partial':
                with self.path.open('ab') as out:out.write(b'{"greToClientEvent":')
            elif mode=='gap':
                gap=copy.deepcopy(self.rows[6]);gap['greToClientEvent']['greToClientMessages'][0]['gameStateMessage']['prevGameStateId']+=100
                append(self.path,[gap])
            else:consumer.close()
            if mode!='stop':
                for event in poll_events(stream):self.assertTrue(consumer.accept_event(event))
            self.unknown(assess_current_choice(consumer,p))
            stream.close()

    def test_history_expiry_and_post_check_lease_refusal(self):
        save(self.path,self.rows[:5]);clock=ManualClock()
        stream=watch_decision_events(self.path,interval=0,samples=3,clock_ns=clock,decision_state_version=7)
        self.addCleanup(stream.close)
        events=poll_events(stream);consumer=DecisionConsumer(clock_ns=clock)
        for event in events:self.assertTrue(consumer.accept_event(event))
        p=self.for_row(consumer.current_view()['decision_state'])
        self.unknown(assess_current_choice(consumer,p),'current_request_not_observed')
        event=copy.deepcopy(next(e for e in events if e['event_type']=='snapshot'))
        event['phase']=event['decision_state']['source']['phase']='append';event['new_request_observed']=True
        for slow in (False,True):
            consumer=DecisionConsumer(10000,500,clock);self.assertTrue(consumer.accept_event(event))
            if not slow:
                clock.advance(501);self.unknown(assess_current_choice(consumer,p))
            else:
                original=validate_proposed_choice
                def delayed(*args,**kwargs):
                    result=original(*args,**kwargs);clock.advance(501);return result
                with patch('mtgaplayer.choice_validation.validate_proposed_choice',side_effect=delayed):
                    self.unknown(assess_current_choice(consumer,p),'current_snapshot_expired_or_changed')

    def test_loader_keeps_finite_contradictions_but_rejects_response_and_scalar_types(self):
        self.path.write_text(json.dumps(self.proposal));self.assertEqual(load_proposal(self.path),self.proposal)
        for field,value in (('object_ref',True),('target_idx',0),('object_refs',[])):
            p=copy.deepcopy(self.proposal);p['proposed_activate_target_member'][field]=value
            self.path.write_text(json.dumps(p))
            with self.assertRaises(ValueError):load_proposal(self.path)
        p=copy.deepcopy(self.proposal);p['future_response']={};self.path.write_text(json.dumps(p))
        with self.assertRaises(ValueError):load_proposal(self.path)

    def test_cli_opt_in_and_legacy_outputs_unchanged(self):
        self.raw();cmd=[sys.executable,'-m','mtgaplayer']
        output=subprocess.run([*cmd,'replay',str(self.path),'--format','player-log','--decision-state-version','7'],capture_output=True,text=True,timeout=20)
        self.assertEqual(output.returncode,0,output.stderr)
        self.assertEqual(self.evidence(json.loads(output.stdout)['decision_state'])['profile'],CURRENT_PROFILE)
        watch=subprocess.run([*cmd,'watch',str(self.path),'--decision-events','--decision-state-version','7','--samples','1'],capture_output=True,text=True,timeout=20)
        self.assertEqual(watch.returncode,0,watch.stderr)
        consumer=DecisionConsumer()
        for line in watch.stdout.splitlines():self.assertTrue(consumer.accept_event(json.loads(line)))
        self.assertEqual(consumer.current_view()['consumer_status'],'CLOSED')
        for version in range(1,7):
            save(self.path,self.rows[:5])
            state=replay(self.path,format='player-log',decision_state=True,decision_state_version=version)['decision_state']
            if version>=5:
                self.assertNotEqual(self.evidence(state)['profile'],CURRENT_PROFILE)
        self.assertNotIn('decision_state',replay(self.path,format='player-log'))

    def test_formal_v7_local_urns_and_strict_member_shape(self):
        docs={}
        for version in (5,6,7):
            for kind in ('state','event'):
                doc=json.loads((ROOT/f'schemas/decision-{kind}.v{version}.schema.json').read_text());docs[doc['$id']]=doc
        def walk(value):
            if isinstance(value,dict):
                yield value
                for v in value.values():yield from walk(v)
            elif isinstance(value,list):
                for v in value:yield from walk(v)
        for kind in ('state','event'):
            doc=docs[f'urn:mtgaplayer:decision-{kind}:v7']
            for node in walk(doc):
                if '$ref' not in node:continue
                urn,_,pointer=node['$ref'].partition('#');target=docs[urn] if urn else doc
                for part in pointer.strip('/').split('/') if pointer else []:
                    target=target[int(part)] if isinstance(target,list) else target[part]
        schema=docs['urn:mtgaplayer:decision-state:v7']
        self.assertEqual(set(schema['required']),set(self.state))
        self.assertEqual(set(schema['$defs']['currentTargetParameters']['required']),set(self.evidence()))
        self.assertFalse(schema['$defs']['currentTargetMenu']['additionalProperties'])
        for key in ('before_response','after_response','after_result'):_state(self.real[key],self.real[key]['binding'])


if __name__=='__main__':unittest.main()
