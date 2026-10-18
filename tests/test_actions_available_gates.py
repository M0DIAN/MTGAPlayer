"""Real Cast prefix and explicitly synthetic field/competition counterexamples."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from mtgaplayer.shadow_history import evaluate_shadow_history, _Evaluation
import test_shadow_history as history_tests
from test_decision_state import action_message
from test_decision_advisor import PASS, PLAY


class ActionsAvailableGateTests(unittest.TestCase):
    setUp = history_tests.ShadowHistoryTests.setUp
    run_rows = history_tests.ShadowHistoryTests.run_rows
    simple = history_tests.ShadowHistoryTests.simple

    def report(self, rows, **kwargs):
        return self.run_rows(rows, actions_available_gates=True, **kwargs)

    def strip(self, report):
        result=copy.deepcopy(report);result.pop('timings_ms')
        result.pop('actions_available_gate_analysis',None)
        return result

    def test_real_cast103_freeze_before_future_and_independent_member_domains(self):
        with (history_tests.FIXTURES/'player_log_single_target.jsonl').open('rb') as source:
            prefix=[json.loads(line) for _,line in zip(range(103),source)]
        frozen=[];before=self.report(prefix,callback=lambda *x:frozen.append(x))
        gates=before['actions_available_gate_analysis']
        self.assertEqual(gates['actions_available_observed'],1)
        self.assertEqual(gates['primary_refusal_distribution'],{'complex_or_unsupported_candidates':1})
        self.assertEqual(gates['unknown_request_field_presence']['unknown_request_fields_present']['false'],1)
        self.assertEqual(gates['complex_action_presence']['ActionType_Cast']['true'],1)
        self.assertEqual(gates['structurally_unreviewed_requests']['true'],1)
        self.assertEqual(gates['reviewed_candidate_coverage']['requests_with_local_kind.parent_cast_member_probe'],1)
        self.assertIsNone(gates['reviewed_candidate_coverage']['complete_legal_candidate_count'])
        opts=frozen[0][2]['options'];self.assertEqual(len(opts),16)
        self.assertEqual([opts[i]['list_position'] for i in (2,3)],[2,3])
        self.assertEqual(len(opts[2]['observation']['current_multi_slot_cast']['slots']),2)
        self.assertIsNone(opts[2]['proposal']);self.assertIsNone(frozen[0][3]['preferred_option_key'])
        later=[json.loads(line) for line in (history_tests.FIXTURES/'player_log_single_target.jsonl').read_text(encoding='utf8').splitlines()]
        full=[];after=self.report(later,callback=lambda *x:full.append(x))
        self.assertEqual(full[0],frozen[0]);self.assertEqual(after['actions_available_gate_analysis'],gates)
        self.assertEqual([n for n,*_ in full],[103,106,109])
        self.assertEqual([len(x[2]['options']) for x in full],[16,4,0])
        self.assertTrue(all(x[3]['status']=='abstain' for x in full))

    def test_default_full_return_unchanged_and_opt_in_does_not_change_policy(self):
        for rows in (self.simple(),self.simple(actions=[PASS,PLAY,PLAY])):
            a=self.run_rows(rows);b=self.report(rows)
            self.assertNotIn('actions_available_gate_analysis',a)
            self.assertNotIn('actions_available_gate_analysis',a['timings_ms'])
            self.assertEqual(self.strip(a),self.strip(b))
            self.assertEqual(b['timings_ms']['actions_available_gate_analysis']['sample_count'],1)
        for flag in (None,1,'yes'):
            with self.assertRaises(ValueError):self.run_rows([],actions_available_gates=flag)

    def test_prompt_shape_is_reviewed_but_never_clears_refusal(self):
        rows=self.simple();action_message(rows[-2])['prompt']={'promptId':123}
        result=self.report(rows);g=result['actions_available_gate_analysis']
        self.assertEqual(result['totals']['research_preferences'],0)
        self.assertEqual(g['primary_refusal_distribution'],{'request_fields_not_fully_interpreted':1})
        self.assertEqual(g['field_semantics_reviewed']['prompt_structure']['reviewed_nonzero_uint32_parameters_absent_shape'],1)
        self.assertEqual(g['field_semantics_still_unknown']['prompt_routing_or_request_meaning'],1)
        self.assertFalse(g['field_semantics_still_unknown']['display_only_classification_proven'])
        self.assertEqual(g['static_counterfactual_after_field_gate'],{'research_preference_under_static_assumptions':1})
        self.assertFalse(g['default_policy_changed'])

    def test_prompt_type_range_parameters_and_unknown_key_counterexamples(self):
        for prompt in ({'promptId':True},{'promptId':1.0},{'promptId':'1'},{'promptId':0},
                       {'promptId':2**32},{'promptId':1,'parameters':[]},{'promptId':1,'PRIVATE_NAME':'SECRET'},
                       None,[],1):
            rows=self.simple();action_message(rows[-2])['prompt']=prompt
            r=self.report(rows);g=r['actions_available_gate_analysis']
            self.assertEqual(g['field_semantics_reviewed']['prompt_structure']['unreviewed_shape'],1)
            self.assertEqual(r['totals']['research_preferences'],0)
            self.assertNotIn('PRIVATE_NAME',json.dumps(g));self.assertNotIn('SECRET',json.dumps(g))

    def test_payload_message_unknown_names_are_redacted_without_false_semantics(self):
        rows=self.simple();message=action_message(rows[-2])
        message['PRIVATE_ENVELOPE']='PRIVATE_VALUE';message['actionsAvailableReq']['PRIVATE_PAYLOAD']={'secret':'secret'}
        g=self.report(rows)['actions_available_gate_analysis'];encoded=json.dumps(g)
        for forbidden in ('PRIVATE_ENVELOPE','PRIVATE_PAYLOAD','PRIVATE_VALUE','secret',str(self.path)):
            self.assertNotIn(forbidden,encoded)
        self.assertEqual(g['unknown_request_field_presence']['other_payload_fields_present']['true'],1)
        self.assertEqual(g['unknown_request_field_presence']['other_message_fields_present']['true'],1)
        self.assertEqual(g['unreviewed_field_name_requests'],{'message':1,'payload':1})

    def test_cast_competes_with_unique_play_even_if_field_gate_were_cleared(self):
        rows=[json.loads(line) for line in (history_tests.FIXTURES/'player_log_single_target.jsonl').read_text(encoding='utf8').splitlines()[:103]]
        request=rows[-1]['greToClientEvent']['greToClientMessages'][-1]
        source=request['actionsAvailableReq']['actions'][3]
        request['actionsAvailableReq']['actions'].append({'actionType':'ActionType_Play','shouldStop':True,
            **{key:source[key] for key in ('instanceId','grpId','facetId')}})
        request['prompt']={'promptId':123}
        result=self.report(rows);g=result['actions_available_gate_analysis']
        self.assertEqual(g['static_counterfactual_after_field_gate'],{'complex_or_unsupported_candidates':1})
        self.assertEqual(g['overlapping_gate_counts']['complex_cast_or_activate']['true'],1)
        self.assertEqual(result['totals']['research_preferences'],0)

    def test_missing_inventory_is_unknown_not_zero_or_no_legal_actions(self):
        rows=self.simple()[:-1];action_message(rows[-1])['actionsAvailableReq']={'actions':None}
        g=self.report(rows)['actions_available_gate_analysis']
        self.assertEqual(g['actions_available_observed'],1)
        self.assertEqual(g['complex_action_presence']['ActionType_Cast'],{'true':0,'false':0,'unknown':1})
        self.assertEqual(g['overlapping_gate_counts']['structurally_unreviewed']['unknown'],1)
        self.assertIsNone(g['reviewed_candidate_coverage']['complete_legal_candidate_count'])

    def test_retransmission_consumption_partial_and_wrong_seat_keep_same_denominator(self):
        rows=self.simple();retransmit=copy.deepcopy(rows[-2])
        counts=[]
        for records in (rows,rows+[retransmit],rows[:-1]+[retransmit,rows[-1]]):
            r=self.report(records);counts.append(r['actions_available_gate_analysis'])
        self.assertEqual(counts[0],counts[1]);self.assertEqual(counts[0],counts[2])
        partial=self.report(rows[:-1],tail=b'{')
        self.assertFalse(partial['source']['complete'])
        self.assertEqual(partial['actions_available_gate_analysis']['actions_available_observed'],1)
        wrong=self.simple()[:-1];action_message(wrong[-1])['systemSeatIds']=[2]
        self.assertEqual(self.report(wrong)['actions_available_gate_analysis']['actions_available_observed'],0)

    def test_consumption_revokes_options_and_diagnostics_do_not_resurrect_them(self):
        rows=[json.loads(line) for line in (history_tests.FIXTURES/'player_log_single_target.jsonl').read_text(encoding='utf8').splitlines()]
        cutoffs={};original=_Evaluation.apply
        def apply(evaluation,record):
            original(evaluation,record)
            if evaluation.ordinal in (104,105,107,110):
                cutoffs[evaluation.ordinal]=evaluation.consumer.current_decision_options()['options']
        with patch.object(_Evaluation,'apply',apply):self.report(rows)
        self.assertEqual(cutoffs,{104:[],105:[],107:[],110:[]})

    def test_cli_opt_in_only_and_empty_input_null_domain(self):
        self.run_rows(self.simple())
        command=[sys.executable,'-m','mtgaplayer','evaluate-shadow-history',str(self.path)]
        a=subprocess.run(command,capture_output=True,encoding='utf8');b=subprocess.run(command+['--actions-available-gates'],capture_output=True,encoding='utf8')
        self.assertEqual((a.returncode,b.returncode),(0,0))
        self.assertNotIn('actions_available_gate_analysis',json.loads(a.stdout))
        self.assertEqual(json.loads(b.stdout)['actions_available_gate_analysis']['actions_available_observed'],1)
        g=self.report([])['actions_available_gate_analysis']
        self.assertEqual(g['actions_available_observed'],0)
        self.assertIsNone(g['reviewed_candidate_coverage']['legal_domain_complete'])


if __name__=='__main__':unittest.main()
