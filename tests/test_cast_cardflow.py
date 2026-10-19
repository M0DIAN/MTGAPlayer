"""Real retained MP91 fields; invented transport and faults are synthetic only."""
import copy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from mtgaplayer import cast_cardflow as cast
from mtgaplayer.decision_consumer import EXECUTION
from mtgaplayer.rules_index import (PreparedRulesIndex, RulesIndexError, reviewed_cast_cardflow,
    prepare_mtga_cardflow_reference, TARGET_EFFECT_SHA256, TARGET_EFFECT_VERSIONS)
from mtgaplayer.shadow_runtime import LocalShadowRuntime, safe_summary
from mtgaplayer.unified_research import V2_POLICY, V3_POLICY, combine_current_research
from test_unified_research import bootstrap, encoded, wrap, Clock
from test_land_swamp import prepared as land_reference

FIXTURES = Path(__file__).parent/'fixtures'


class CastCardflowTests(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads((FIXTURES/'cast_cardflow_real.json').read_text())
        self.sample = copy.deepcopy(self.fixture['cases'][0])
        self.static = json.loads((FIXTURES/'cast_cardflow_reference_real.json').read_text())
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.serial = 0

    def prepared(self, mutate=None):
        value = copy.deepcopy(self.static)
        if mutate: mutate(value)
        return PreparedRulesIndex(value['metadata'], {int(k):v for k,v in value['matches'].items()})

    def stream(self, sample=None, *, policy=cast.POLICY, prepared=None, **kwargs):
        sample = copy.deepcopy(self.sample if sample is None else sample)
        self.serial += 1; path = Path(self.temp.name)/f'synthetic-transport-{self.serial}.log'
        target = json.loads((FIXTURES/'target_effect_real.json').read_text())
        path.write_bytes(('\n'.join(target['resource_prelude'])+'\n').encode()+encoded(bootstrap(sample)))
        clock = Clock(); settings = {'research_policy':policy}
        if policy == cast.POLICY:settings['prepared_rules'] = self.prepared() if prepared is None else prepared
        elif policy in (V2_POLICY,V3_POLICY):
            target_ref=json.loads((FIXTURES/'target_effect_reference_real.json').read_text())
            refs={'land':land_reference(),'target_effect':PreparedRulesIndex(target_ref['metadata'],
                {int(k):v for k,v in target_ref['matches'].items()})}
            if policy==V3_POLICY:refs['cast_cardflow']=self.prepared() if prepared is None else prepared
            settings['prepared_references']=refs
        runtime=LocalShadowRuntime(path,interval=0,clock_ns=clock,observation_mode='controlled_stream_replay',**settings,**kwargs)
        gen=runtime.frames();self.addCleanup(runtime.close);self.addCleanup(gen.close)
        history=next(gen);frame=self.append(gen,path,[wrap(sample['message'])])
        return runtime,gen,path,clock,frame,history

    @staticmethod
    def append(gen,path,rows):
        with path.open('ab') as out:out.write(encoded(rows))
        return next(gen)

    def report(self,runtime,prepared=None,message=None):
        return cast.assess_current_cast_cardflow(runtime.consumer,runtime._reducer,
            runtime._message if message is None else message,self.prepared() if prepared is None else prepared,
            completed_stamp=runtime._completed_stamp)

    def source(self,sample):
        raw=next(a for a in sample['message']['actionsAvailableReq']['actions'] if a.get('grpId')==96626)
        obj=next(o for o in sample['initial']['objects'] if o['instanceId']==raw['instanceId'])
        return raw,obj

    def denied(self,report):
        self.assertNotEqual(report['status'],'research_preference');self.assertIsNone(report['preferred_option_key'])

    def revoked(self,frame):
        self.assertNotEqual(frame['time_scope'],'current_at_completed_poll')
        for name in ('research_decision','unified_research_decision','cast_cardflow_decision'):
            if name in frame:self.denied(frame[name])

    def test_real_projection_has_goal_preference_and_retains_all_unranked_competitors(self):
        runtime,_,_,_,frame,history=self.stream()
        self.assertEqual(self.fixture['origin'],'retained_scrubbed_real');self.assertFalse(self.fixture['raw_equivalent'])
        self.revoked(history);self.assertEqual(frame['time_scope'],'current_at_completed_poll')
        report=frame['research_decision'];self.assertEqual(report['status'],'research_preference')
        self.assertEqual(report['selected_goal'],cast.GOAL);self.assertEqual(report['comparison_scope'],cast.SCOPE)
        self.assertEqual(report['coverage'],{'active_action_rows':11,'inactive_action_rows':1,'cast_offers':6,'reviewed_cardflow_casts':1})
        self.assertEqual(report['unranked_competitor_count'],10)
        self.assertEqual({c['action_type'] for c in report['unranked_competitors']},
            {'ActionType_Cast','ActionType_Activate_Mana','ActionType_Pass','ActionType_FloatMana'})
        self.assertTrue(all(c['goal_value'] is None for c in report['unranked_competitors']))
        self.assertTrue(all(c['utility'] is None for c in report['unresolved_competitor_values']))
        for key in (*cast.FALSE_CLAIMS,*EXECUTION):self.assertIs(report[key],False)
        self.assertEqual(report['effect_identity'],{'card_id':96626,'ability_id':190898})
        instruction=report['conditional_effect_evidence']['instruction']
        self.assertFalse(instruction['cast_direct_draw']);self.assertFalse(instruction['leaves_branch_counted_as_cast_benefit'])
        self.assertEqual(instruction['researched_branch'],'prospective_enters_only')
        self.assertEqual(self.report(runtime),report)

    def test_v3_uses_same_owner_and_old_v2_frame_components_remain_identical(self):
        with patch('mtgaplayer.cast_cardflow.assess_current_cast_cardflow',wraps=cast.assess_current_cast_cardflow) as calls:
            runtime,_,_,_,new,_=self.stream(policy=V3_POLICY)
            self.assertIs(calls.call_args.args[0],runtime.consumer);self.assertIs(calls.call_args.args[1],runtime._reducer)
        *_,old,_=self.stream(policy=V2_POLICY)
        from test_unified_research_v2 import normalized
        for key in ('current_options','shadow_decision','local_evidence','research_decision'):
            self.assertEqual(normalized(new[key]),normalized(old[key]))
        self.assertEqual(new['unified_research_decision']['selected_policy'],cast.POLICY)
        self.assertEqual(new['unified_research_decision']['status'],'research_preference')
        self.assertEqual(old['unified_research_decision']['status'],'abstain')

    def test_static_effect_version_and_distinct_activated_ability_are_not_interchangeable(self):
        runtime,*_=self.stream()
        changes=[lambda v:v['metadata'].update(source_sha256='0'*64),
            lambda v:v['metadata'].update(source_version_is_user_supplied=True),
            lambda v:v['matches']['96626']['card']['ability_definitions'][0]['row'].update(Id=190899),
            lambda v:v['matches']['96626']['card']['ability_definitions'][0]['row'].update(ModalChildIds='1'),
            lambda v:v['matches']['96626']['card']['profile'].update(OldSchoolManaText='oXoU'),
            lambda v:v['matches']['96626']['card']['ability_definitions'][0]['specific_text'].update(Loc='Draw two cards.'),
            lambda v:v['matches']['96626']['card']['conditional_instruction'].update(cast_direct_draw=True)]
        for mutate in changes:
            with self.subTest(change=changes.index(mutate)):self.denied(self.report(runtime,self.prepared(mutate)))
        card=self.static['matches']['96626']['card']
        self.assertEqual(reviewed_cast_cardflow(card)['ability_id'],190898)

    def test_offline_reference_scope_and_detached_definition_cannot_be_extended_by_caller(self):
        for ids,sha,versions in (([96626,90673],TARGET_EFFECT_SHA256,TARGET_EFFECT_VERSIONS),
                ([96626],'0'*64,TARGET_EFFECT_VERSIONS),([96626],TARGET_EFFECT_SHA256,{'Data':'next','GRP':'next'})):
            with self.subTest(ids=ids,sha=sha),self.assertRaises(RulesIndexError):
                prepare_mtga_cardflow_reference(Path(self.temp.name)/'not-opened',ids,
                    expected_sha256=sha,expected_source_version=versions)
        reference=self.prepared();metadata,found=reference.lookup([96626])
        found[96626]['card']['ability_definitions'][0]['row']['Id']=190899
        self.assertEqual(reviewed_cast_cardflow(reference.lookup([96626])[1][96626]['card'])['ability_id'],190898)

    def test_wrong_source_visibility_ability_cost_target_or_mode_never_produces_preference(self):
        changes=[lambda a,o:a.update(grpId=12345),lambda a,o:o.update(type='GameObjectType_Ability'),
            lambda a,o:o.update(visibility='Visibility_Hidden',viewers=[]),lambda a,o:o.update(controllerSeatId=2),
            lambda a,o:o.update(overlayGrpId=12345),lambda a,o:o.update(cardTypes=['CardType_Creature']),
            lambda a,o:o['uniqueAbilities'][0].update(grpId=190899),
            lambda a,o:a.update(manaCost=[{'color':['ManaColor_Generic'],'count':99}]),
            lambda a,o:a.update(targets=[]),lambda a,o:a.update(modes=[1]),lambda a,o:a.update(facetId=True)]
        for i,change in enumerate(changes):
            with self.subTest(change=i):
                sample=copy.deepcopy(self.sample);change(*self.source(sample))
                *_,frame,_=self.stream(sample)
                if frame['time_scope']=='current_at_completed_poll':self.denied(frame['research_decision'])
                else:self.revoked(frame)

    def test_multiple_same_goal_casts_abstain_without_position_or_id_tiebreak(self):
        sample=copy.deepcopy(self.sample);raw,obj=self.source(sample)
        sample['message']['actionsAvailableReq']['actions'].append(copy.deepcopy(raw))
        *_,frame,_=self.stream(sample)
        self.denied(frame['research_decision']);self.assertEqual(frame['research_decision']['reason'],'multiple_cardflow_casts')

    def test_known_phase_library_or_stack_contradiction_abstains(self):
        for mode in ('phase','priority','empty_library','nonempty_stack'):
            with self.subTest(mode=mode):
                sample=copy.deepcopy(self.sample)
                if mode=='phase':sample['initial']['turn_info']['phase']='Phase_Combat'
                elif mode=='priority':sample['initial']['turn_info']['priorityPlayer']=2
                elif mode=='empty_library':
                    next(z for z in sample['initial']['zones'] if z['type']=='ZoneType_Library' and z['ownerSeatId']==1)['objectInstanceIds']=[]
                else:
                    sample['initial']['zones'].append({'zoneId':8999,'type':'ZoneType_Stack','visibility':'Visibility_Public','objectInstanceIds':[8888]})
                    sample['initial']['objects'].append({'instanceId':8888,'grpId':12345,'type':'GameObjectType_Card',
                        'zoneId':8999,'ownerSeatId':2,'controllerSeatId':2,'visibility':'Visibility_Public'})
                *_,frame,_=self.stream(sample)
                if frame['time_scope']=='current_at_completed_poll':self.denied(frame['research_decision'])
                else:self.revoked(frame)

    def test_missing_inventory_wrong_binding_and_known_contradictions_are_not_ignored(self):
        for mode in ('drop','truncated','ref','seat','contradiction'):
            with self.subTest(mode=mode):
                runtime,*_=self.stream();options=runtime.consumer.current_decision_options()
                if mode=='drop':options['options'].pop()
                elif mode=='truncated':options['coverage']['truncated']=True
                elif mode=='ref':options['source_snapshot_ref']['sequence']+=1
                elif mode=='seat':options['request_binding']['self_seat']=2
                else:options['unresolved'].append({'evidence_level':'violated_known_constraints','reason':'synthetic_control'})
                with patch.object(runtime.consumer,'current_decision_options',return_value=options):self.denied(self.report(runtime))

    def test_lookup_mutation_of_raw_state_or_lease_revokes_result(self):
        for mode in ('digest','overlay','type','phase','lease','options'):
            with self.subTest(mode=mode):
                runtime,_,_,clock,frame,_=self.stream();original=PreparedRulesIndex.lookup
                source=frame['research_decision']['source_identity']['instance_id']
                def changed(prepared,*args,**kwargs):
                    value=original(prepared,*args,**kwargs)
                    if mode=='digest':runtime._reducer.accepted_digest=bytes(32)
                    elif mode=='overlay':runtime._reducer.objects[source]['overlayGrpId']=12345
                    elif mode=='type':runtime._reducer.objects[source]['cardTypes']=['CardType_Creature']
                    elif mode=='phase':runtime._reducer.turn['phase']='Phase_Combat'
                    elif mode=='lease':clock.now+=10_000_000_000
                    return value
                if mode=='options':
                    options=runtime.consumer.current_decision_options()
                    def mutate(prepared,*args,**kwargs):
                        value=original(prepared,*args,**kwargs);options['visible_state']['game']['turn']['phase']='Phase_Combat';return value
                    with patch.object(runtime.consumer,'current_decision_options',return_value=options),patch.object(PreparedRulesIndex,'lookup',mutate):
                        self.denied(self.report(runtime))
                else:
                    with patch.object(PreparedRulesIndex,'lookup',changed):self.denied(self.report(runtime))

    def test_consumption_partial_gap_full_cancel_undo_replacement_expiry_stop_and_owner(self):
        for mode in ('consume','partial','gap','full','cancel','undo','replace','expire','stop','owner'):
            with self.subTest(mode=mode):
                runtime,gen,path,clock,frame,_=self.stream(policy=V3_POLICY)
                message=copy.deepcopy(self.sample['message'])
                if mode=='consume':
                    response={'payload':{'type':'ClientMessageType_PerformActionResp','respId':500,'gameStateId':10,
                        'performActionResp':{'actions':[self.source(self.sample)[0]]}}}
                    self.revoked(self.append(gen,path,[response]));self.revoked(self.append(gen,path,[wrap(message)]))
                elif mode=='partial':
                    with path.open('ab') as out:out.write(b'{"greToClientEvent":')
                    self.revoked(next(gen))
                elif mode=='gap':
                    state={'type':'GameStateType_Diff','gameStateId':12,'prevGameStateId':11}
                    self.revoked(self.append(gen,path,[wrap({'type':'GREMessageType_GameStateMessage','gameStateMessage':state})]))
                elif mode=='full':
                    from test_raw_log import state
                    fresh=bootstrap(self.sample)[2];state(fresh)['gameStateId']=11
                    self.revoked(self.append(gen,path,[fresh]))
                elif mode in ('cancel','undo'):
                    self.revoked(self.append(gen,path,[{'payload':{'type':'ClientMessageType_CancelActionReq' if mode=='cancel' else 'ClientMessageType_UndoReq'}}]))
                    self.revoked(self.append(gen,path,[wrap(message)]))
                elif mode=='replace':
                    message['msgId']=501;message['actionsAvailableReq']['actions']=[{'actionType':'ActionType_Pass'}]
                    fresh=self.append(gen,path,[wrap(message)])
                    self.assertEqual(fresh['request_binding']['request_id'],501);self.denied(fresh['cast_cardflow_decision'])
                    same=self.append(gen,path,[wrap(self.sample['message'])]);self.assertEqual(same['request_binding']['request_id'],501)
                elif mode=='expire':clock.now+=10_000_000_000;self.revoked(runtime.current_frame())
                elif mode=='stop':runtime.close();self.revoked(runtime.current_frame())
                else:
                    answers=[];worker=threading.Thread(target=lambda:answers.append(runtime.current_frame()));worker.start();worker.join()
                    self.revoked(answers[0])

    def test_cast_permission_is_narrow_and_cannot_upgrade_other_ineligible_options(self):
        *_,frame,_=self.stream(policy=V3_POLICY)
        options=copy.deepcopy(frame['current_options']);report=copy.deepcopy(frame['cast_cardflow_decision'])
        candidate=next(o for o in options['options'] if o['option_key']==report['preferred_option_key'])
        candidate['research_eligible']=False
        result=combine_current_research(options,frame['shadow_decision'],frame['research_decision'],
            policy_version=V3_POLICY,cast_research=report)
        self.assertEqual(result['status'],'research_preference')
        for mode in ('other','effect','scope','flags','binding'):
            with self.subTest(mode=mode):
                changed=copy.deepcopy(report)
                if mode=='other':changed['preferred_option_key']=next(o['option_key'] for o in options['options'] if o['option_key']!=report['preferred_option_key'])
                elif mode=='effect':changed['effect_identity']['ability_id']=190899
                elif mode=='scope':changed['comparison_scope']='complete_action_pareto'
                elif mode=='flags':changed['payment_verified']=True
                else:changed['request_binding']['request_id']+=1
                with self.assertRaises(ValueError):combine_current_research(options,frame['shadow_decision'],frame['research_decision'],policy_version=V3_POLICY,cast_research=changed)
        with self.assertRaises(ValueError):combine_current_research(options,frame['shadow_decision'],policy_version=V2_POLICY,cast_research=report)
        shadow=copy.deepcopy(frame['shadow_decision']);shadow.update(status='research_preference',preferred_option_key=report['preferred_option_key'],
            evidence_level=candidate['evidence_level'],validation_scope=candidate['validation_scope'])
        with self.assertRaises(ValueError):combine_current_research(options,shadow,policy_version=V3_POLICY)

    def test_land_cast_goal_conflict_abstains_and_report_does_not_grant_input(self):
        # Synthetic competing Land report tests arbitration only. Actual MP91
        # opportunity42 is separately replayed by Owner, never invented here.
        *_,frame,_=self.stream(policy=V3_POLICY)
        land=copy.deepcopy(frame['research_decision']);other=next(o for o in frame['current_options']['options']
            if o['option_key']!=frame['cast_cardflow_decision']['preferred_option_key'])
        land.update(status='research_preference',preferred_option_key=other['option_key'],preference_basis='synthetic_land_conflict')
        result=combine_current_research(frame['current_options'],frame['shadow_decision'],land,policy_version=V3_POLICY,cast_research=frame['cast_cardflow_decision'])
        self.denied(result);self.assertEqual(result['reason'],'research_policy_conflict')

    def test_constructor_completed_poll_and_hot_path_privacy_boundaries(self):
        runtime,_,_,_,frame,_=self.stream(policy=V3_POLICY)
        with (patch('mtgaplayer.rules_index.sqlite3.connect',side_effect=AssertionError('hot SQLite')),
              patch('mtgaplayer.rules_index._file_sha256',side_effect=AssertionError('hot file'))):
            self.assertEqual(runtime.current_frame()['cast_cardflow_decision'],frame['cast_cardflow_decision'])
        self.denied(cast.assess_current_cast_cardflow(runtime.consumer,runtime._reducer,runtime._message,self.prepared()))
        for policy in (V2_POLICY,None):
            with self.assertRaises(ValueError):LocalShadowRuntime(Path(self.temp.name)/'never',research_policy=policy,prepared_references={'cast_cardflow':self.prepared()})
        frame['cast_cardflow_decision']['private_payload']='PRIVATE_SENTINEL'
        encoded_summary=json.dumps(safe_summary(frame))
        for value in ('PRIVATE_SENTINEL','96626','190898','instance_id'):self.assertNotIn(value,encoded_summary)
        self.assertEqual(safe_summary(frame)['cast_cardflow_decision']['policy_version'],cast.POLICY)


if __name__ == '__main__':unittest.main()
