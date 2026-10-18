"""Retained real prefixes and explicitly synthetic comparison counterexamples."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from mtgaplayer.shadow_history import evaluate_shadow_history, _Evaluation
from mtgaplayer.raw_log import RawFramer
from mtgaplayer.decision_consumer import EXECUTION
from test_action_frontier import frames
from test_decision_state import action_message
from test_response_evidence import reply
from test_decision_advisor import PASS, PLAY

FIXTURES=Path(__file__).parent/'fixtures'


class ShadowHistoryTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        self.path=Path(folder.name)/'private-path-do-not-export.Player.log'

    def run_rows(self, rows, callback=None, tail=b'', **kwargs):
        self.path.write_bytes(''.join(json.dumps(r)+'\n' for r in rows).encode()+tail)
        return evaluate_shadow_history(self.path,_on_freeze=callback,**kwargs)

    def simple(self, chosen=PLAY, actions=None):
        rows=frames();request=action_message(rows[-1])
        # A labeled synthetic one-request case: keep real state continuity,
        # excluding the unrelated earlier Mulligan request/response pair.
        for entry in rows[:-1]:
            entry.pop('payload',None)
            gre=entry.get('greToClientEvent')
            if gre is not None:
                gre['greToClientMessages']=[m for m in gre['greToClientMessages'] if not m.get('type','').endswith('Req')]
        request['actionsAvailableReq']={'actions':copy.deepcopy(actions or [PASS,PLAY])}
        response=reply(request['msgId'],request['gameStateId'],{'actions':[copy.deepcopy(chosen)]})
        return rows+[response]

    def assert_units(self, report):
        for counts in (*report['by_request_type'].values(),report['totals']):
            self.assertEqual(counts['observed_requests'],counts['evaluable_requests']+counts['unsupported']+counts['invalid_or_incomplete'])
            self.assertEqual(counts['evaluable_requests'],counts['research_preferences']+counts['abstentions'])
            self.assertLessEqual(counts['expired_or_consumed'],counts['observed_requests'])
        choices=report['historical_comparison']
        self.assertEqual(choices['historical_choices_observed'],choices['comparable_policy_preferences']+choices['uncomparable'])
        self.assertEqual(choices['comparable_policy_preferences'],choices['historical_agreements']+choices['historical_disagreements'])
        self.assertLessEqual(choices['comparable_policy_preferences'],choices['historical_choices_uniquely_matched'])
        for key in EXECUTION:self.assertIs(report[key],False,key)
        self.assertEqual(report['mode'],'historical_simulation');self.assertIs(report['live_decision_opportunity'],False)

    def test_real_cast_freezes103_before104_and_keeps_position2_separate(self):
        # Open exactly prefix103 before opening or parsing any future row.
        with (FIXTURES/'player_log_single_target.jsonl').open('rb') as source:
            prefix=[json.loads(line) for _,line in zip(range(103),source)]
        frozen=[];first=self.run_rows(prefix,lambda *x:frozen.append(x))
        self.assertEqual(len(frozen),1);ordinal,request,options,decision=copy.deepcopy(frozen[0])
        self.assertEqual(ordinal,103);self.assertEqual(request['id'],10100)
        self.assertEqual(decision['status'],'abstain');self.assertIsNone(decision['preferred_option_key'])
        self.assertEqual(options['options'][2]['list_position'],2)
        self.assertEqual(options['options'][3]['list_position'],3)
        self.assertEqual(len(options['options'][2]['observation']['current_multi_slot_cast']['slots']),2)
        self.assertIsNone(options['options'][2]['proposal'])
        lines=(FIXTURES/'player_log_single_target.jsonl').read_text(encoding='utf8').splitlines()
        later=[];full=self.run_rows([json.loads(line) for line in lines],lambda *x:later.append(x))
        self.assertEqual(later[0],frozen[0])
        self.assertEqual([x[0] for x in later],[103,106,109])
        self.assertTrue(all(x[3]['status']=='abstain' for x in later))
        self.assertEqual(len(later[1][2]['options']),4);self.assertEqual(len(later[2][2]['options']),0)
        self.assertEqual(full['totals'],{'observed_requests':3,'evaluable_requests':3,'research_preferences':0,
            'abstentions':3,'unsupported':0,'invalid_or_incomplete':0,'expired_or_consumed':3})
        choices=full['historical_comparison'];self.assertEqual(choices['historical_choices_observed'],3)
        self.assertEqual(choices['historical_choices_uniquely_matched'],2)
        self.assertEqual(choices['comparable_policy_preferences'],0);self.assertEqual(choices['uncomparable'],3)
        self.assertEqual(full['historical_choice_units']['member_update_not_final_set'],1)
        self.assertEqual(sum(sum(v.values()) for v in full['abstention_reasons'].values()),3)
        self.assertIsNone(full['rates']['agreement_over_comparable'])
        self.assert_units(full);self.assertEqual(first['totals']['research_preferences'],0)

    def test_synthetic_simple_agreement_and_disagreement_are_not_correctness(self):
        for chosen,agree in ((PLAY,True),(PASS,False)):
            report=self.run_rows(self.simple(chosen));self.assert_units(report)
            self.assertEqual(report['totals']['research_preferences'],1)
            choices=report['historical_comparison'];self.assertEqual(choices['historical_choices_uniquely_matched'],1)
            self.assertEqual(choices['comparable_policy_preferences'],1)
            self.assertEqual(choices['historical_agreements'],int(agree))
            self.assertEqual(choices['historical_disagreements'],int(not agree))
            self.assertTrue(report['agreement_is_not_correctness_win_rate_or_legality'])

    def test_future_response_cannot_change_preference_or_supply_missing_choice(self):
        rows=self.simple();frozen=[];self.run_rows(rows[:-1],lambda *x:frozen.append(x))
        rows[-1]['payload']['performActionResp']['actions']=[PASS]
        with_future=[];self.run_rows(rows,lambda *x:with_future.append(x))
        self.assertEqual(with_future,frozen)
        rows[-1]['payload'].pop('performActionResp')
        report=self.run_rows(rows);self.assertEqual(report['historical_comparison']['comparable_policy_preferences'],0)
        self.assertEqual(report['historical_comparison']['historical_choices_observed'],1)

    def test_retransmission_consumption_wrong_binding_and_wrong_response_type(self):
        rows=self.simple()
        retransmit={'greToClientEvent':{'greToClientMessages':[copy.deepcopy(action_message(rows[-2]))]}}
        for changed in (rows+[copy.deepcopy(rows[-1])], rows[:-1]+[retransmit,rows[-1]],
                        rows+[retransmit]):
            report=self.run_rows(changed);self.assertEqual(report['totals']['observed_requests'],1)
            self.assertEqual(report['historical_comparison']['comparable_policy_preferences'],1)
        for field,value in (('respId',999),('gameStateId',999),('type','ClientMessageType_SelectNResp')):
            changed=copy.deepcopy(rows);changed[-1]['payload'][field]=value
            report=self.run_rows(changed);self.assertEqual(report['historical_comparison']['historical_choices_observed'],0)

    def test_multi_request_record_is_frozen_at_each_message_before_replacement(self):
        rows=self.simple()[:-1];first=action_message(rows[-1]);second=copy.deepcopy(first);second['msgId']+=1000
        messages=rows[-1]['greToClientEvent']['greToClientMessages']
        rows[-1]['greToClientEvent']['greToClientMessages']=[m for m in messages if m is not first]+[first,second]
        frozen=[];report=self.run_rows(rows,lambda *x:frozen.append(x));self.assert_units(report)
        self.assertEqual(len(frozen),2);self.assertNotEqual(frozen[0][1]['id'],frozen[1][1]['id'])
        self.assertTrue(all(r[3]['status']=='research_preference' for r in frozen))
        # Same record is not itself evidence of a later client choice.
        self.assertEqual(report['historical_comparison']['historical_choices_observed'],0)

    def test_mixed_envelope_and_ambiguous_play_cannot_enter_comparison(self):
        rows=self.simple();rows[-1]['greToClientEvent']={'greToClientMessages':[]}
        self.assertEqual(self.run_rows(rows)['historical_comparison']['comparable_policy_preferences'],0)
        report=self.run_rows(self.simple(actions=[PASS,PLAY,PLAY]))
        self.assertEqual(report['totals']['research_preferences'],0)
        self.assertEqual(report['historical_comparison']['historical_choices_uniquely_matched'],0)

    def test_partial_malformed_and_record_limit_keep_prefix_boundary_explicit(self):
        rows=self.simple()
        partial=self.run_rows(rows[:-1],tail=b'{"payload":')
        self.assertFalse(partial['source']['complete']);self.assertTrue(partial['source']['partial_record'])
        self.assertEqual(partial['totals']['research_preferences'],1)
        self.assertEqual(partial['historical_comparison']['historical_choices_observed'],0)
        limited=self.run_rows(rows,max_records=len(rows)-1)
        self.assertTrue(limited['source']['record_limit_reached']);self.assertFalse(limited['source']['complete'])
        self.assertEqual(limited['historical_comparison']['historical_choices_observed'],0)
        malformed=self.run_rows(rows[:-1],tail=b'{bad}\n'+json.dumps(rows[-1]).encode())
        self.assertEqual(malformed['source']['framing_errors'],1)
        self.assertEqual(malformed['historical_comparison']['comparable_policy_preferences'],0)

    def test_private_values_paths_and_unknown_request_names_never_escape(self):
        rows=self.simple();marker='DO_NOT_EXPORT_PRIVATE_identity_ABCDEFG'
        rows[0]['authenticateResponse']['privateSentinel']=marker
        rows[-1]['payload']['privateSentinel']=marker
        report=self.run_rows(rows);encoded=json.dumps(report)
        self.assertNotIn(marker,encoded);self.assertNotIn(str(self.path),encoded)
        self.assertNotIn('private-path-do-not-export',encoded)
        for forbidden in ('request_binding','source_snapshot_ref','option_key','visible_objects','clientId','selectedIds'):
            self.assertNotIn('"'+forbidden+'"',encoded)
        self.assert_units(report)

    def test_determinism_default_policy_unchanged_and_bounded_timing_nulls(self):
        rows=self.simple();a=self.run_rows(rows);b=self.run_rows(rows)
        a.pop('timings_ms');b.pop('timings_ms');self.assertEqual(a,b)
        empty=self.run_rows([])
        self.assertIsNone(empty['rates']['research_preference_over_observed'])
        self.assertIsNone(empty['timings_ms']['current_decision_options']['p50_ms'])
        for bounds in ({'max_records':0},{'max_history_bytes':True},{'max_history_bytes':1}):
            with self.assertRaises(ValueError):self.run_rows(rows,**bounds)

    def test_cli_explicit_safe_report_and_safe_errors(self):
        self.run_rows(self.simple())
        run=subprocess.run([sys.executable,'-m','mtgaplayer','evaluate-shadow-history',str(self.path)],capture_output=True,encoding='utf8')
        self.assertEqual(run.returncode,0,run.stderr);self.assert_units(json.loads(run.stdout))
        missing=subprocess.run([sys.executable,'-m','mtgaplayer','evaluate-shadow-history',str(self.path)+'-missing'],capture_output=True,encoding='utf8')
        self.assertEqual(missing.returncode,1);self.assertNotIn(str(self.path),missing.stdout)

    def test_non_string_response_types_remain_bounded_diagnostics(self):
        for typ in (None,1,{},[],True):
            report=self.run_rows(self.simple()[:-1]+[{'payload':{'type':typ}}])
            self.assertEqual(report['historical_comparison']['historical_choices_observed'],0)
            self.assert_units(report)
        partial=self.run_rows([],tail=b'{')
        self.assertFalse(partial['source']['complete'])
        self.assertEqual(partial['totals']['observed_requests'],0)

    def test_growing_source_cannot_extend_the_frozen_read_budget(self):
        rows=self.simple()[:-1]
        self.path.write_text(''.join(json.dumps(r)+'\n' for r in rows),encoding='utf8')
        initial=self.path.read_bytes()
        def append(*args):
            with self.path.open('ab') as out:out.write(b'\n'*262144)
        report=evaluate_shadow_history(self.path,max_history_bytes=len(initial),_on_freeze=append)
        self.assertEqual(report['source']['bytes_read'],len(initial))
        self.assertFalse(report['source']['stable_during_read'])
        self.assertFalse(report['source']['complete'])

    def test_structure_abstention_does_not_erase_observed_action_categories(self):
        rows=self.simple();action_message(rows[-2])['actionsAvailableReq']['unknownField']='PRIVATE'
        report=self.run_rows(rows)
        self.assertEqual(report['totals']['research_preferences'],0)
        self.assertEqual(report['action_categories']['ActionType_Play']['requests_containing_category'],1)
        self.assertEqual(report['action_categories']['ActionType_Pass']['requests_containing_category'],1)
        self.assertEqual(report['abstention_reasons']['actions_available'],{'request_fields_not_fully_interpreted':1})

    def test_missing_or_unsupported_inventory_is_unknown_not_a_crash(self):
        for body in (None,{'actions':None},{'actions':[None]},{'actions':[PASS]*257}):
            rows=self.simple()[:-1];message=action_message(rows[-1])
            if body is None:message.pop('actionsAvailableReq')
            else:message['actionsAvailableReq']=body
            report=self.run_rows(rows);self.assert_units(report)
            self.assertEqual(report['totals']['observed_requests'],1)
            self.assertEqual(report['totals']['research_preferences'],0)
            self.assertIsNone(report['unknown_full_legal_action_count'])


if __name__=='__main__':unittest.main()
