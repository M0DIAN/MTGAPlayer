"""Retained real chains with labeled synthetic transport and counterexamples."""
import copy
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from mtgaplayer import shadow_decision as policy, decision_options
from mtgaplayer.cli import replay, watch_decision_events
from mtgaplayer.decision_consumer import DecisionConsumer, EXECUTION, consume_events
import test_decision_options as option_helpers
import test_decision_advisor as advisor_helpers
from test_decision_publisher import ManualClock, poll_events
from test_decision_input import rows as selectn_rows
from test_combat_frontier import baseline, request, ATTACK, BLOCK

FIXTURES=Path(__file__).parent/'fixtures'


class ShadowDecisionTests(unittest.TestCase):
    def setUp(self):
        self.helpers=option_helpers.DecisionOptionsTests('test_equip_portable_stages_keep_own_selected_literal_and_parent_history')
        self.helpers.setUp();self.addCleanup(self.helpers.doCleanups)
        self.equip=json.loads((FIXTURES/'current_target_revision_real_v14.json').read_text(encoding='utf8'))

    def current(self, name='first_child'):
        return self.helpers.transport(self.equip[name])

    def safe(self, result, preference=False):
        self.assertEqual(result['schema_version'],policy.VERSION)
        self.assertTrue(result['read_only'])
        for flag in EXECUTION:self.assertIs(result[flag],False,flag)
        if preference:
            self.assertEqual(result['status'],'research_preference')
            self.assertIsNotNone(result['preferred_option_key'])
            self.assertIn('complete_legality_unknown',result['unresolved'])
            self.assertIn('strategic_utility_unknown',result['unresolved'])
        else:
            self.assertNotEqual(result['status'],'research_preference')
            self.assertIsNone(result['preferred_option_key'])

    def test_equip_first_is_only_local_unique_preference_revised_is_not_submit_proof(self):
        for version in (14,15):
            for name,state in self.equip.items():
                with self.subTest(version=version,name=name):
                    state=copy.deepcopy(state)
                    if version==15:
                        state['schema_version']='mtgaplayer.decision-state.v15'
                        state.pop('revised_choice_continuation');state['cast_choice_continuation']=None
                    c,_,_,_=self.helpers.transport(state);r=c.shadow_decision()
                    self.safe(r,preference=name=='first_child')
                    if name=='first_child':
                        offered=c.current_decision_options()
                        self.assertEqual(r['preferred_option_key'],offered['options'][0]['option_key'])
                        self.assertEqual(r['request_binding'],offered['request_binding'])
                        self.assertEqual(r['source_snapshot_ref'],offered['source_snapshot_ref'])
                    elif name=='revised_child':
                        self.assertEqual(r['status'],'abstain')
                        self.assertEqual(r['reason'],'selected_literal_or_probe_is_not_a_final_proposal')

    def test_cast_real_incremental_chain_abstains_without_borrowing_later_choices(self):
        lines=(FIXTURES/'player_log_single_target.jsonl').read_bytes().splitlines(keepends=True)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'public.jsonl';path.write_bytes(b''.join(lines[:102]))
            clock=ManualClock();c=DecisionConsumer(10000,10000,clock)
            stream=watch_decision_events(path,interval=0,samples=9,decision_state_version=15,
                clock_ns=clock,session_id='shadow-real-cast')
            self.addCleanup(stream.close)
            for event in poll_events(stream):self.assertTrue(c.accept_event(event))
            self.safe(c.shadow_decision());previous=102;ref106=None
            for cutoff in (103,104,105,106,107,109,110):
                with path.open('ab') as out:out.write(b''.join(lines[previous:cutoff]))
                previous=cutoff
                for event in poll_events(stream):self.assertTrue(c.accept_event(event))
                r=c.shadow_decision();self.safe(r)
                self.assertEqual(r,c.shadow_decision())
                if cutoff in (103,106):
                    self.assertEqual(r['status'],'abstain')
                    self.assertEqual(r['candidate_coverage']['returned_options'],16 if cutoff==103 else 4)
                if cutoff==106:ref106=r['source_snapshot_ref']
                if cutoff==109:
                    self.assertNotEqual(r['source_snapshot_ref'],ref106)
                    self.assertEqual(r['candidate_coverage']['returned_options'],0)
                if cutoff in (104,105,107,110):self.assertEqual(r['status'],'expired')

    def test_unique_play_reuses_advisor_and_original_option_position(self):
        helper=advisor_helpers.DecisionAdvisorTests('test_actual_chain_unique_play_is_opt_in_research_only')
        helper.setUp();self.addCleanup(helper.doCleanups)
        for actions,position in (([advisor_helpers.PASS,advisor_helpers.PLAY],1),
                                 ([advisor_helpers.PLAY,advisor_helpers.PASS],0)):
            c=helper.current(actions)
            with patch.object(policy,'assess_current_decision',wraps=policy.assess_current_decision) as reuse:
                r=c.shadow_decision();self.safe(r,True)
                reuse.assert_called_once_with(c,policy_version=policy.SIMPLE_TYPE_POLICY)
            self.assertEqual(r['preferred_option_key']['source_position'],position)
            self.assertEqual(r['advisor_policy'],policy.SIMPLE_TYPE_POLICY)
            self.assertEqual(r['preference_basis'],'unverified_simple_type_heuristic')
        for actions in ([advisor_helpers.PLAY,advisor_helpers.PLAY],[advisor_helpers.PASS]):
            self.safe(helper.current(actions).shadow_decision())

    def test_selectn_discard_and_even_single_combat_member_abstain(self):
        helper=advisor_helpers.DecisionAdvisorTests('test_select_n_reports_options_and_unknown_minimum')
        helper.setUp();self.addCleanup(helper.doCleanups)
        for rows in (selectn_rows(),baseline()+[request(ATTACK)],baseline()+[request(BLOCK)]):
            r=helper.current(rows=rows).shadow_decision();self.safe(r)
            self.assertEqual(r['status'],'abstain')
            self.assertIsNone(r['candidate_coverage']['unknown_count'])
        state=json.loads((FIXTURES/'current_discard_real_v8.json').read_text(encoding='utf8'))['before_response']
        c,_,_,_=self.helpers.transport(state);r=c.shadow_decision();self.safe(r)
        self.assertEqual(r['status'],'abstain')
        self.assertEqual(r['candidate_coverage']['reviewed_candidate_count'],8)

    def test_one_verified_cast_or_activate_among_unknown_competitors_cannot_win(self):
        for filename,cutoff in (('player_log_cast_generic_one.jsonl',14),('player_log_activate_generic_two.jsonl',5)):
            self.helpers.cast.path.write_bytes(b''.join((FIXTURES/filename).read_bytes().splitlines(keepends=True)[:cutoff]))
            state=replay(self.helpers.cast.path,format='player-log',decision_state_version=5)['decision_state']
            c,_,_,_=self.helpers.transport(state);r=c.shadow_decision();self.safe(r)
            self.assertEqual(r['status'],'abstain')
        state=json.loads((FIXTURES/'activate_target_payment_real_v9.json').read_text(encoding='utf8'))['before_response']
        c,_,_,_=self.helpers.transport(state);r=c.shadow_decision();self.safe(r)
        self.assertEqual(r['status'],'abstain')
        self.assertEqual(r['candidate_coverage']['reviewed_candidate_count'],1)

    def test_hidden_competition_truncation_and_missing_total_refuse_uniqueness(self):
        for mutate in (
            lambda r:r['coverage'].update(truncated=True),
            lambda r:r['coverage'].update(omitted_constructed_options=1),
            lambda r:r['coverage']['sources'][0].update(truncated=True),
            lambda r:r['coverage']['sources'][0]['coverage'].update(candidate_total_for_reviewed_constraints=None),
            lambda r:r['coverage']['sources'][0]['coverage'].update(candidate_total_for_reviewed_constraints=2),
            lambda r:r['options'].append({**r['options'][0],'kind':'parent_activate_member_probe'})):
            c,_,_,_=self.current();r=c.current_decision_options();mutate(r)
            with patch.object(c,'current_decision_options',return_value=r):self.safe(c.shadow_decision())

    def test_same_input_determinism_and_cached_collection_does_not_retain_policy(self):
        c,_,_,_=self.current()
        with patch.object(decision_options,'enumerate_known_candidates',wraps=decision_options.enumerate_known_candidates) as generate:
            one=c.shadow_decision();two=c.shadow_decision()
            self.assertEqual(one,two);self.assertEqual(generate.call_count,1)
            one['preferred_option_key']['source_position']=999
            self.assertEqual(two,c.shadow_decision())

    def test_lease_expiry_during_options_policy_or_after_preference_revokes(self):
        for when in ('options','policy','after'):
            c,_,clock,_=self.current()
            if when=='after':
                self.safe(c.shadow_decision(),True);clock.advance(600);r=c.shadow_decision()
            else:
                owner,method=(decision_options,'_build') if when=='options' else (policy,'_decide')
                original=getattr(owner,method)
                def slow(*args,**kwargs):
                    result=original(*args,**kwargs);clock.advance(600);return result
                with patch.object(owner,method,slow):r=c.shadow_decision()
            self.safe(r);self.assertEqual(r['status'],'expired')

    def test_wrong_binding_history_stop_and_unsupported_policy_cannot_grant_preference(self):
        c,pub,_,_=self.current();r=c.current_decision_options();r['options'][0]['request_binding']['request_id']+=1
        with patch.object(c,'current_decision_options',return_value=r):self.safe(c.shadow_decision())
        self.safe(c.shadow_decision(),True)
        for event in pub.stop():self.assertTrue(c.accept_event(event))
        self.safe(c.shadow_decision());self.assertEqual(c.shadow_decision()['status'],'expired')
        c,_,_,_=self.helpers.transport(self.equip['first_child'],history=True);self.safe(c.shadow_decision())
        c,_,_,_=self.current();r=c.shadow_decision(policy_version='future-unknown')
        self.safe(r);self.assertEqual(r['status'],'unsupported')
        self.safe(policy.assess_current_shadow_decision(c.current_view()))

    def test_invalidation_during_policy_discards_already_computed_preference(self):
        # Synthetic protocol envelopes test each existing revocation cause;
        # they are not additional recorded game evidence.
        for reason in ('request_consumed','request_replaced','state_advanced',
                       'source_partial','source_reset','identity_changed','session_stopped'):
            with self.subTest(reason=reason):
                c,pub,_,_=self.current();invalidate=pub.stop()[0]
                self.assertEqual(invalidate['event_type'],'invalidate')
                invalidate['reason']=reason
                invalidate['subscription_active']=reason!='session_stopped'
                original=policy._decide
                def changed(*args,**kwargs):
                    old=original(*args,**kwargs)
                    self.assertEqual(old['status'],'research_preference')
                    self.assertTrue(c.accept_event(invalidate))
                    return old
                with patch.object(policy,'_decide',changed):r=c.shadow_decision()
                self.safe(r);self.assertEqual(r['status'],'expired')
                self.safe(c.shadow_decision())

    def test_cli_optin_and_final_shared_sidecar_gate_revoke_both_reports(self):
        c,pub,clock,events=self.current();data=''.join(json.dumps(e)+'\n' for e in events+pub.stop()).encode()
        for flags in ([],['--shadow-decision'],['--shadow-decision','--current-decision-options']):
            run=subprocess.run([sys.executable,'-m','mtgaplayer','consume-events',*flags],
                input=data,capture_output=True,timeout=30)
            self.assertEqual(run.returncode,0,run.stderr)
            rows=[json.loads(line) for line in run.stdout.splitlines()]
            self.assertTrue(all(('shadow_decision' in row)==bool(flags) for row in rows))
            if flags:self.assertTrue(any(row['shadow_decision']['status']=='research_preference' for row in rows))
        output=[];original=DecisionConsumer.shadow_decision
        def late(consumer,**kwargs):
            r=original(consumer,**kwargs);clock.advance(600);return r
        with patch.object(DecisionConsumer,'shadow_decision',late):
            consume_events(io.BytesIO(data),output.append,DecisionConsumer(10000,500,clock),
                current_decision_options=True,shadow_decision=True)
        self.assertTrue(all(row['shadow_decision']['preferred_option_key'] is None for row in output))
        self.assertTrue(all(not row['current_decision_options']['options'] for row in output))


if __name__=='__main__':unittest.main()
