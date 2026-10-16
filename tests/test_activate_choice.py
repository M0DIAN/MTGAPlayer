"""Real pre-response Activate prefix; mutations are synthetic controls."""
import copy
import json
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import unittest

from mtgaplayer.cli import replay
from mtgaplayer.choice_validation import validate_proposed_choice
from mtgaplayer.decision_consumer import EXECUTION
from mtgaplayer.semantic_activate import PROFILE, REQUEST_VERSION
from mtgaplayer.semantic_samples import collect_samples, replay_samples, SampleError

FIXTURE = Path(__file__).parent/'fixtures/player_log_activate_generic_two.jsonl'
ROOT = Path(__file__).resolve().parents[1]


class ActivateChoiceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name); self.path = self.root/'activate.log'
        self.rows = [json.loads(r) for r in FIXTURE.read_text().splitlines()]
        self.state = self.prefix(self.rows)
        self.proposal = self.propose(self.state)

    def write(self, rows):
        self.path.write_text(''.join(json.dumps(r)+'\n' for r in rows))

    def prefix(self, rows):
        self.write(rows[:5])
        return replay(self.path, format='player-log', decision_state_version=5)['decision_state']

    def evidence(self, state=None):
        return (state or self.state)['legal_action_space']['request_parameters']

    def propose(self, state, position=3):
        return {'request_identity': copy.deepcopy(state['binding']), 'list_position': position,
                'proposed_action': copy.deepcopy(self.evidence(state)['rows'][position]['literal_action'])}

    def result(self, state=None, proposal=None):
        return validate_proposed_choice(state or self.state, proposal or self.proposal)

    def assert_unknown(self, result, reason=None):
        self.assertEqual(result['known_constraints'], 'insufficient_evidence')
        if reason: self.assertIn(reason, result['reasons'])
        self.assertTrue(all(result[k] is False for k in EXECUTION))

    def source(self, rows):
        source = self.proposal['proposed_action']['identifier_refs']['instanceId']
        return next(o for o in rows[2]['greToClientEvent']['greToClientMessages'][0]['gameStateMessage']['gameObjects']
                    if o['instanceId'] == source)

    def actions(self, rows):
        return rows[4]['greToClientEvent']['greToClientMessages'][0]['actionsAvailableReq']['actions']

    def test_real_prefix_full_denominator_and_no_response_eligibility(self):
        evidence = self.evidence(); result = self.result()
        self.assertEqual((evidence['schema_version'], evidence['profile']), (REQUEST_VERSION, PROFILE))
        self.assertEqual(len(evidence['rows']), 20)
        self.assertEqual([r['list_position'] for r in evidence['rows'] if
                          r['action_type']=='ActionType_Activate' and r['literal_action'] is not None], [1,3])
        self.assertEqual(result['known_constraints'], 'verified_known_constraints')
        self.assertTrue(all(v=='verified_known_constraints' for v in result['known_checks'].values()))
        self.assertFalse(result['complete_costs_verified']); self.assertEqual(result['additional_costs'],'unknown')
        self.assertEqual(result['future_parameters'],'unknown')
        self.assertTrue(all(result[k] is False for k in EXECUTION))
        self.assertNotIn('uniqueAbilities',json.dumps(evidence))
        for index in (2,4,5,6,7,8):
            self.assertIsNone(evidence['rows'][index]['literal_action'])
            self.assertIn('targets',evidence['rows'][index]['parameter_shapes'])
        # Another real no-target row passes the same local checks before any
        # response. Its counterfactual result cannot use this trace's suffix.
        self.assertEqual(self.result(proposal=self.propose(self.state,1))['known_constraints'],
                         'verified_known_constraints')
        self.assertFalse(evidence['historical_response_used'])

    def test_opaque_target_values_never_enter_current_parameters(self):
        rows=copy.deepcopy(self.rows)
        self.actions(rows)[2]['targets'][0]['targets'][0]['secret']='PRIVATE_SENTINEL'
        state=self.prefix(rows)
        self.assertNotIn('PRIVATE_SENTINEL',json.dumps(state))
        self.assertEqual(self.result(state,self.propose(state))['known_constraints'],'verified_known_constraints')
        self.assertEqual(len(self.evidence(state)['rows']),20)

    def test_missing_duplicate_and_conflicting_current_ability_pairs(self):
        for mode in ('missing','empty','duplicate','conflict'):
            with self.subTest(mode=mode):
                rows=copy.deepcopy(self.rows);source=self.source(rows)
                pair=next(p for p in source['uniqueAbilities'] if
                          p['id']==self.proposal['proposed_action']['identifier_refs']['uniqueAbilityId'])
                if mode=='missing':source.pop('uniqueAbilities')
                elif mode=='empty':source['uniqueAbilities']=[]
                elif mode=='duplicate':source['uniqueAbilities'].append(copy.deepcopy(pair))
                else:pair['grpId']+=999
                state=self.prefix(rows);result=self.result(state,self.propose(state))
                if mode=='conflict':
                    self.assertEqual(result['known_constraints'],'violated_known_constraints')
                    self.assertIn('current_source_ability_group_contradicted',result['reasons'])
                else:self.assert_unknown(result,'current_source_unique_ability_pair_not_observed')

    def test_replaced_source_does_not_inherit_old_unique_ability_list(self):
        rows=copy.deepcopy(self.rows);replacement=copy.deepcopy(self.source(rows));replacement.pop('uniqueAbilities')
        rows[3]['greToClientEvent']['greToClientMessages'][0]['gameStateMessage']['gameObjects'].append(replacement)
        state=self.prefix(rows)
        self.assert_unknown(self.result(state,self.propose(state)), 'current_source_unique_ability_pair_not_observed')

    def test_missing_parameters_and_nonunique_mana_relations_remain_unknown(self):
        for mode in ('cost','tap','mana_missing','mana_duplicate','mana_parameter'):
            with self.subTest(mode=mode):
                rows=copy.deepcopy(self.rows);actions=self.actions(rows)
                if mode=='cost':actions[3].pop('manaCost')
                elif mode=='tap':actions[3].pop('autoTapSolution')
                elif mode=='mana_missing':actions[11]['abilityGrpId']+=999
                elif mode=='mana_duplicate':actions.append(copy.deepcopy(actions[11]))
                else:actions[11].pop('manaPaymentOptions')
                state=self.prefix(rows);self.assert_unknown(self.result(state,self.propose(state)))

    def test_distinct_sources_must_not_reuse_one_predictive_mana_unit(self):
        # Real Generic2 request supplies two different source/unit pairs.
        # Only the second unit ID is synthetically made equal to the first;
        # its source action is changed too, preserving the offered-option join.
        actions = self.actions(self.rows)
        taps = actions[3]['autoTapSolution']['autoTapActions']
        self.assertNotEqual(taps[0]['instanceId'], taps[1]['instanceId'])
        first = taps[0]['manaPaymentOption']['mana'][0]['manaId']
        self.assertNotEqual(first, taps[1]['manaPaymentOption']['mana'][0]['manaId'])
        rows = copy.deepcopy(self.rows)
        actions = self.actions(rows)
        second = actions[3]['autoTapSolution']['autoTapActions'][1]
        second['manaPaymentOption']['mana'][0]['manaId'] = first
        matched = [row for row in actions if row['actionType'] == 'ActionType_Activate_Mana'
                   and row['instanceId'] == second['instanceId']
                   and row['abilityGrpId'] == second['abilityGrpId']]
        self.assertEqual(len(matched), 1)
        matched[0]['manaPaymentOptions'][0]['mana'][0]['manaId'] = first
        state = self.prefix(rows)
        proposal = self.propose(state)
        self.assertIsNotNone(proposal['proposed_action'])
        result = self.result(state, proposal)
        self.assert_unknown(result, 'distinct_mana_units_not_observed')
        self.assertFalse(result['complete_costs_verified'])

    def test_cost_and_internal_payment_contradictions_are_not_alternative_routes(self):
        for mode in ('cost_group','payment_group','offered_option'):
            rows=copy.deepcopy(self.rows);actions=self.actions(rows)
            if mode=='cost_group':actions[3]['manaCost'][0]['abilityGrpId']+=999
            elif mode=='payment_group':
                actions[3]['autoTapSolution']['autoTapActions'][0]['manaPaymentOption']['mana'][0]['abilityGrpId']+=999
            else:actions[11]['manaPaymentOptions'][0]['mana'][0]['count']=2
            state=self.prefix(rows)
            self.assertEqual(self.result(state,self.propose(state))['known_constraints'],'violated_known_constraints')
        proposed=copy.deepcopy(self.proposal)
        proposed['proposed_action']['parameters']['autoTapSolution']['autoTapActions'][0]['manaPaymentOption']['mana'][0]['count']=2
        self.assert_unknown(self.result(proposal=proposed),'alternative_payment_path_not_supported')

    def test_binding_and_facet_identity_and_source_scope(self):
        for key in ('request_id','game_state_id','source_generation'):
            proposed=copy.deepcopy(self.proposal);proposed['request_identity'][key]+=1
            self.assert_unknown(self.result(proposal=proposed),'proposal_binding_invalid')
        for key in ('instanceId','uniqueAbilityId','abilityGrpId','facetId'):
            proposed=copy.deepcopy(self.proposal);proposed['proposed_action']['identifier_refs'][key]+=999
            self.assert_unknown(self.result(proposal=proposed),'proposal_binding_invalid')
        proposed=copy.deepcopy(self.proposal);proposed['list_position']=1
        self.assert_unknown(self.result(proposal=proposed),'proposal_binding_invalid')
        # Facet is opaque offered identity, not an inferred card-group value.
        rows=copy.deepcopy(self.rows);self.actions(rows)[3]['facetId']+=123
        state=self.prefix(rows)
        self.assertEqual(self.result(state,self.propose(state))['known_constraints'],'verified_known_constraints')
        rows=copy.deepcopy(self.rows);self.source(rows)['controllerSeatId']=2
        state=self.prefix(rows)
        self.assert_unknown(self.result(state,self.propose(state)),'activate_source_not_verified')

    def test_cross_projection_mismatch_and_fabricated_literal_do_not_validate(self):
        for mode in ('count','shape','identity','opaque_literal','binding_status'):
            state=copy.deepcopy(self.state);evidence=self.evidence(state)
            if mode=='count':evidence['rows'].pop()
            elif mode=='shape':evidence['rows'][2]['parameter_shapes']['targets']['element_count']+=1
            elif mode=='identity':evidence['rows'][2]['identifier_refs']['abilityGrpId']+=1
            elif mode=='opaque_literal':evidence['rows'][2]['literal_action']=copy.deepcopy(self.proposal['proposed_action'])
            else:evidence['rows'][3]['ability_binding']='invented'
            self.assert_unknown(self.result(state),'proposal_or_state_invalid')

    def test_actual_historical_chain_and_portable_certificate_boundaries(self):
        self.write(self.rows);document=collect_samples(self.path,schema_version=5,origin='retained_scrubbed_real')
        report=replay_samples(document);e=report['samples'][0]['activate_evidence']
        for key in ('activation_submission_observed','matching_source_group_stack_ability_observed',
                    'payment_sources_to_ability_observed','payment_sources_tapped_observed',
                    'matching_ability_resolution_observed','matching_ability_deleted_observed'):
            self.assertTrue(e[key],key)
        self.assertFalse(e['public_stack_empty_verified'])
        self.assertFalse(e['unique_ability_continuation_verified']);self.assertFalse(e['complete_costs_verified'])
        sample=document['samples'][0]
        sources=[t['instanceId'] for t in sample['response']['payload']['action']['parameters']['autoTapSolution']['autoTapActions']]
        before={o['object_ref']:o for o in sample['before']['objects']}
        self.assertEqual([before[s]['tapped'] for s in sources],[None,None])
        self.assertEqual(len(sample['trace']['states']),3)
        for mode in ('successor','group','source','public_group','borrow_suffix'):
            altered=copy.deepcopy(document);s=altered['samples'][0]
            if mode=='successor':s['successor']['snapshot']['players'][0]['life']+=1
            elif mode=='group':s['trace']['states'][0]['facts'][0]['ability_grp_ref']+=999
            elif mode=='source':s['trace']['states'][0]['facts'][0]['source_object_ref']+=999
            elif mode=='public_group':
                ability=s['trace']['states'][0]['facts'][0]['ability_object_ref']
                obj=next(o for o in s['trace']['states'][0]['snapshot']['objects'] if o['object_ref']==ability)
                obj['card_id']=999
                s['successor']['snapshot']=copy.deepcopy(s['trace']['states'][0]['snapshot'])
            else:s['response']['payload']['action']=copy.deepcopy(s['request']['payload']['rows'][1]['literal_action'])
            with self.assertRaises(SampleError):replay_samples(altered)

    def test_missing_or_ambiguous_public_parent_group_binding_is_not_inferred(self):
        for mode in ('parent','group','ambiguous'):
            rows=copy.deepcopy(self.rows)
            gs=rows[6]['greToClientEvent']['greToClientMessages'][0]['gameStateMessage']
            ability=next(o for o in gs['gameObjects'] if o.get('type')=='GameObjectType_Ability')
            if mode=='parent':ability['parentId']+=999
            elif mode=='group':ability['grpId']+=999
            else:
                other=copy.deepcopy(ability);other['instanceId']+=999
                gs['gameObjects'].append(other)
                zone=next(z for z in gs['zones'] if z['zoneId']==ability['zoneId'])
                zone['objectInstanceIds'].append(other['instanceId'])
            self.write(rows);report=replay_samples(collect_samples(self.path,schema_version=5))
            e=report['samples'][0]['activate_evidence']
            self.assertFalse(e['matching_source_group_stack_ability_observed'])
            self.assertFalse(e['matching_ability_resolution_observed'])

    def test_schema5_cli_round_trip_in_another_process_and_old_versions_unchanged(self):
        self.write(self.rows);output=self.root/'episode.json'
        run=subprocess.run([sys.executable,'-m','mtgaplayer','export-semantic-samples',str(self.path),
            '--schema-version','5','--output',str(output)],capture_output=True,text=True,timeout=10)
        self.assertEqual(run.returncode,0,run.stderr)
        run=subprocess.run([sys.executable,'-m','mtgaplayer','replay-semantic-samples',str(output)],
                           capture_output=True,text=True,timeout=10)
        self.assertEqual(run.returncode,0,run.stderr)
        self.assertTrue(json.loads(run.stdout)['samples'][0]['activate_evidence']['matching_ability_resolution_observed'])
        self.write(self.rows[:5])
        for version in (1,2,3,4):
            state=replay(self.path,format='player-log',decision_state_version=version,decision_state=True)['decision_state']
            self.assertNotIn('request_parameters',state['legal_action_space'])
        schema=json.loads((ROOT/'schemas/decision-state.v5.schema.json').read_text())
        self.assertIn('partialActivateRow',schema['$defs'])

    def test_actual_dual_cli_prefix_verdict_response_revocation_and_new_request(self):
        proposal=self.root/'proposal.json';proposal.write_text(json.dumps(self.proposal))
        self.write(self.rows[:4])
        producer=subprocess.Popen([sys.executable,'-m','mtgaplayer','watch',str(self.path),
            '--decision-events','--decision-state-version','5','--interval','.025','--samples','120'],
            stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        consumer=subprocess.Popen([sys.executable,'-m','mtgaplayer','consume-events','--validate-choice',str(proposal)],
            stdin=producer.stdout,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        producer.stdout.close();lines=queue.Queue()
        def read():
            for line in consumer.stdout:lines.put(json.loads(line))
            lines.put(None)
        reader=threading.Thread(target=read,daemon=True);reader.start()
        def until(predicate):
            for _ in range(60):
                row=lines.get(timeout=8);self.assertIsNotNone(row)
                if predicate(row):return row
            self.fail('expected diagnostic not observed')
        def append(rows):
            with self.path.open('a') as stream:stream.write(''.join(json.dumps(r)+'\n' for r in rows))
        try:
            until(lambda r:r['consumer_status']=='OBSERVING')
            append(self.rows[4:5])
            verdict=until(lambda r:r['choice_validation']['known_constraints']=='verified_known_constraints')
            self.assertEqual(len(self.path.read_text().splitlines()),5)
            self.assertEqual(verdict['choice_validation']['additional_costs'],'unknown')
            append(self.rows[5:6])
            revoked=until(lambda r:r['consumer_status']=='INVALIDATED');self.assert_unknown(revoked['choice_validation'])
            append(self.rows[6:])
            while True:
                row=lines.get(timeout=8)
                if row is None:break
                self.assert_unknown(row['choice_validation'])
            self.assertEqual(consumer.wait(timeout=5),0,consumer.stderr.read())
            self.assertEqual(producer.wait(timeout=5),0,producer.stderr.read())
            report=replay_samples(collect_samples(self.path,schema_version=5))
            self.assertTrue(report['samples'][0]['activate_evidence']['matching_ability_resolution_observed'])
        finally:
            for process in (consumer,producer):
                if process.poll() is None:process.kill()
                process.wait(timeout=5)
                for pipe in (process.stdin,process.stdout,process.stderr):
                    if pipe is not None:pipe.close()
            reader.join(2)
