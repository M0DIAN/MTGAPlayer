"""Actual retained current request evidence and bounded synthetic controls."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from mtgaplayer.cli import replay, watch_decision_events
from mtgaplayer.choice_validation import validate_proposed_choice
from mtgaplayer.choice_candidates import (enumerate_known_candidates,
    assess_current_known_candidates, MAX_CANDIDATES)
from mtgaplayer.decision_consumer import DecisionConsumer, EXECUTION
from test_decision_publisher import ManualClock, poll_events
from test_semantic_effect_cost import baseline, save, request, response

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT/'tests/fixtures/player_log_single_target.jsonl'
COST = ROOT/'tests/fixtures/decision_state_effect_cost_real_v6.json'


class KnownChoiceCandidatesTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.path=Path(temp.name)/'choice.log'
        self.rows=[json.loads(row) for row in TARGET.read_text().splitlines()]
        self.write(self.rows[:106])
        self.target=replay(self.path,format='player-log',decision_state_version=5)['decision_state']
        self.cost=json.loads(COST.read_text())

    def write(self,rows):
        self.path.write_text(''.join(json.dumps(row)+'\n' for row in rows))

    def assert_readonly(self,r):
        self.assertTrue(r['read_only'])
        self.assertTrue(all(r[k] is False for k in EXECUTION))
        for k in ('full_action_domain_complete','global_restrictions_verified',
                  'complete_payment_verified','complete_legality_verified',
                  'server_acceptance_verified','historical_response_used'):
            self.assertFalse(r[k],k)

    def test_real_target_four_known_singletons_are_not_complete_legality(self):
        r=enumerate_known_candidates(self.target)
        self.assertEqual(r['status'],'reviewed_constraint_candidates_observed')
        self.assertEqual((r['candidate_total_for_reviewed_constraints'],
                          r['returned_candidates'],r['truncated']),(4,4,False))
        offered=self.target['legal_action_space']['request_parameters']['targets']['entries']
        self.assertEqual([p['proposed_final_target_set']['object_refs'] for p in r['candidates']],
                         [[row['object_ref']] for row in offered])
        self.assertTrue(all(validate_proposed_choice(self.target,p)['known_constraints'] ==
                            'verified_known_constraints' for p in r['candidates']))
        self.assertTrue(r['exhaustive_for_reviewed_constraints'])
        self.assert_readonly(r)

    def test_real_cost_sixteen_known_singletons_without_payment_proof(self):
        r=enumerate_known_candidates(self.cost)
        offered=self.cost['legal_action_space']['request_parameters']['cost_selection']['offered_object_refs']
        self.assertEqual((r['candidate_total_for_reviewed_constraints'],
                          r['returned_candidates']),(16,16))
        self.assertEqual([p['proposed_cost_selection']['selected_object_refs'][0]
                          for p in r['candidates']], offered)
        self.assertTrue(all(validate_proposed_choice(self.cost,p)['known_constraints'] ==
                            'verified_known_constraints' for p in r['candidates']))
        self.assert_readonly(r)

    def test_truncation_is_explicit_with_fixed_limit(self):
        for state,total in ((self.target,4),(self.cost,16)):
            r=enumerate_known_candidates(state,limit=2)
            self.assertEqual((r['candidate_total_for_reviewed_constraints'],
                              r['returned_candidates']),(total,2))
            self.assertTrue(r['truncated'])
            self.assertFalse(r['exhaustive_for_reviewed_constraints'])
            self.assert_readonly(r)
        for invalid in (0,True,MAX_CANDIDATES+1,1.5):
            with self.assertRaises(ValueError):
                enumerate_known_candidates(self.target,limit=invalid)

    def test_represented_unselect_domain_never_borrows_prior_target_set(self):
        self.write(self.rows[:109])
        state=replay(self.path,format='player-log',decision_state_version=5)['decision_state']
        r=enumerate_known_candidates(state)
        self.assertEqual(r['status'],'insufficient_evidence')
        self.assertEqual(r['reason'],'complete_current_select_domain_not_observed')
        self.assertEqual(r['candidates'],[])

    def test_unknown_bounds_and_invalid_request_never_gain_candidates(self):
        for field in ('entries','min_targets','max_targets'):
            state=copy.deepcopy(self.target)
            state['legal_action_space']['request_parameters']['targets'][field]=None
            self.assertEqual(enumerate_known_candidates(state)['candidates'],[])
        bad=copy.deepcopy(self.cost)
        bad['legal_action_space']['request_parameters']['historical_response_used']=True
        self.assertEqual(enumerate_known_candidates(bad)['candidates'],[])
        bad=copy.deepcopy(self.target);bad['binding']['request_id']+=1
        self.assertEqual(enumerate_known_candidates(bad)['candidates'],[])

    def test_current_lease_and_actual_response_revoke_live_candidates(self):
        save(self.path,baseline())
        stream=watch_decision_events(self.path,interval=0,samples=4,clock_ns=ManualClock(),
                                     session_id='mp47',decision_state_version=6)
        self.addCleanup(stream.close)
        history=poll_events(stream)
        with self.path.open('a') as out:out.write(json.dumps(request())+'\n')
        current=poll_events(stream)
        consumer=DecisionConsumer()
        for event in history+current:
            self.assertTrue(consumer.accept_event(event))
        r=assess_current_known_candidates(consumer)
        self.assertEqual(r['returned_candidates'],16)
        ref=r['source_snapshot_ref'];self.assertIsNotNone(ref)
        self.assertTrue(all(row['source_snapshot_ref']==ref for row in r['candidates']))
        self.assert_readonly(r)
        with self.path.open('a') as out:out.write(json.dumps(response())+'\n')
        for event in poll_events(stream):self.assertTrue(consumer.accept_event(event))
        revoked=assess_current_known_candidates(consumer)
        self.assertEqual(revoked['candidates'],[])
        self.assertIsNone(revoked['source_snapshot_ref'])

    def test_cli_optin_without_default_changes(self):
        args=[sys.executable,'-m','mtgaplayer','replay',str(self.path),'--format',
              'player-log','--decision-state-version','5']
        self.write(self.rows[:106])
        normal=subprocess.run(args,capture_output=True,text=True,timeout=15)
        extra=subprocess.run([*args,'--known-choice-candidates'],capture_output=True,text=True,timeout=15)
        self.assertEqual(normal.returncode,0,normal.stderr)
        self.assertEqual(extra.returncode,0,extra.stderr)
        a,b=json.loads(normal.stdout),json.loads(extra.stdout)
        self.assertEqual(a,{k:v for k,v in b.items() if k!='known_choice_candidates'})
        self.assertEqual(b['known_choice_candidates']['returned_candidates'],4)
        rejected=subprocess.run([sys.executable,'-m','mtgaplayer','replay',str(self.path),
            '--format','player-log','--known-choice-candidates'],capture_output=True,text=True,timeout=15)
        self.assertNotEqual(rejected.returncode,0)

    def test_exhaustive_reviewed_constraints_not_all_game_legal_actions(self):
        r=enumerate_known_candidates(self.cost)
        self.assertTrue(r['exhaustive_for_reviewed_constraints'])
        self.assertFalse(r['full_action_domain_complete'])
        self.assertFalse(r['complete_legality_verified'])
        self.assertFalse(r['server_acceptance_verified'])
