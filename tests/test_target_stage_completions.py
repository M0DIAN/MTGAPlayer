"""Public real Cast prefixes; all mutations/bootstrap are synthetic counterproofs.

No owner raw bytes are opened. Synthetic Equip plumbing uses already public
snapshots and does not certify a new real GRE sequence.
"""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from mtgaplayer.shadow_history import _Evaluation, evaluate_shadow_history
from mtgaplayer.target_revision import PRIVATE
from mtgaplayer.target_stage_completions import TargetStageCompletions
import test_target_revision as revision_tests

FIXTURES = Path(__file__).parent / 'fixtures'


class TargetStageCompletionTests(unittest.TestCase):
    def real_rows(self, count=110):
        with (FIXTURES/'player_log_single_target.jsonl').open('rb') as stream:
            return [json.loads(line) for _, line in zip(range(count), stream)]

    def evaluate(self, rows, callback=None):
        evaluation = _Evaluation(callback, target_stage_completions=True)
        for row in rows: evaluation.apply(row)
        return evaluation

    def report(self, rows):
        return self.evaluate(rows).target_completions.report()

    def absent(self, rows):
        report = self.report(rows)
        self.assertEqual(report['historical_reviewed_target_sets_submitted'], 0)
        self.assertEqual(report['comparable_shadow_target_preferences'], 0)

    def equip_rows(self):
        maker = revision_tests.TargetRevisionTests('test_synthetic_terminal_extra_fields_do_not_change_legacy_candidate_meaning')
        maker.setUp()
        return maker.synthetic_records(terminal=True)

    def test_real_cast_freeze_before_future_and_terminal_only_after110(self):
        # Deliberately do not open107 until106 is frozen.
        rows = self.real_rows(106); frozen = []
        e = self.evaluate(rows, lambda *x: frozen.append(x))
        initial = copy.deepcopy(frozen[-1]); options = initial[2]; policy = initial[3]
        self.assertEqual(initial[0], 106); self.assertEqual(len(options['options']), 4)
        self.assertEqual(policy['status'], 'abstain')
        self.assertEqual(e.target_completions.report()['historical_reviewed_target_sets_submitted'], 0)
        later = self.real_rows(110)
        for index in range(106, 110):
            e.apply(later[index])
            count = e.target_completions.report()['historical_reviewed_target_sets_submitted']
            self.assertEqual(count, int(index == 109))
            self.assertEqual(frozen[1], initial)
            if index == 106:
                self.assertIsNone(e.reducer.request)
                self.assertEqual(e.consumer.shadow_decision()['status'], 'expired')
            if index == 108:
                self.assertEqual(e.reducer.request['id'], 10104)
                self.assertNotIn(PRIVATE, e.reducer.request)  # Card is never State14 Ability.
                self.assertEqual(e.consumer.shadow_decision()['status'], 'abstain')
                self.assertEqual(e.consumer.current_decision_options()['options'], [])
                self.assertEqual(e.stage.revision.completion_context['selected_object_refs'], [1262])
        report = e.target_completions.report()
        self.assertEqual(report['completed_source_types'], {'Card': 1})
        self.assertEqual(report['strictly_paired_selection_updates'], 1)
        self.assertEqual(report['verified_revised_stage_relationships'], 1)
        self.assertEqual(report['strictly_paired_terminal_submits'], 1)
        self.assertEqual(report['comparable_shadow_target_preferences'], 0)
        self.assertEqual(report['uncomparable_target_episodes'], 1)
        self.assertIsNone(e.reducer.request); self.assertIsNone(e.stage.revision.active)
        self.assertEqual(e.consumer.current_decision_options()['options'], [])
        self.assertEqual(e.consumer.shadow_decision()['status'], 'expired')

    def test_synthetic_equip_plumbing_freezes_unique_proposal_and_compares_final_set(self):
        frozen = []; e = self.evaluate(self.equip_rows(), lambda *x: frozen.append(x))
        report = e.target_completions.report()
        self.assertEqual(report['completed_source_types'], {'Ability': 1})
        self.assertEqual(report['comparable_shadow_target_preferences'], 1)
        self.assertEqual(report['historical_target_agreements'], 1)
        self.assertEqual(report['historical_target_disagreements'], 0)
        self.assertEqual([x[3]['status'] for x in frozen], ['abstain', 'research_preference', 'abstain'])
        self.assertIsNone(e.stage.revision.completion_context)

    def test_synthetic_response_counterproofs(self):
        for field, value in (('respId', 10104), ('respId', True), ('gameStateId', 102),
                             ('type', 'ClientMessageType_PerformActionResp')):
            with self.subTest(field=field, value=value):
                rows = self.real_rows(); rows[106]['payload'][field] = value; self.absent(rows)
        for mode in ('slot', 'duplicate', 'delete', 'replace', 'unselect', 'extra'):
            with self.subTest(mode=mode):
                rows = self.real_rows(); payload = rows[106]['payload']; target = payload['selectTargetsResp']['target']
                if mode == 'slot': target['targetIdx'] = 2
                elif mode == 'duplicate': target['targets'] *= 2
                elif mode == 'delete': target['targets'] = []
                elif mode == 'replace': target['targets'][0]['targetInstanceId'] = 1243
                elif mode == 'unselect': target['targets'][0]['legalAction'] = 'SelectAction_Unselect'
                else: payload['unreviewed'] = True
                self.absent(rows)

    def test_synthetic_revised_shape_counterproofs(self):
        for mode in ('slot', 'duplicate', 'delete', 'replace', 'mixed', 'quantity', 'source', 'seat'):
            with self.subTest(mode=mode):
                rows = self.real_rows(); message = rows[108]['greToClientEvent']['greToClientMessages'][0]
                target = message['selectTargetsReq']['targets'][0]
                if mode == 'slot': target['targetIdx'] = 2
                elif mode == 'duplicate': target['targets'] *= 2
                elif mode == 'delete': target['targets'] = []
                elif mode == 'replace': target['targets'][0]['targetInstanceId'] = 1243
                elif mode == 'mixed':
                    entry = copy.deepcopy(target['targets'][0]); entry['legalAction'] = 'SelectAction_Select'
                    target['targets'].append(entry)
                elif mode == 'quantity': target['selectedTargets'] = 2
                elif mode == 'source': message['selectTargetsReq']['sourceId'] = 1243
                else: message['systemSeatIds'] = [1]
                self.absent(rows)

    def test_synthetic_submit_header_and_identity_counterproofs(self):
        for field, value in (('respId', 10102), ('respId', 10104.0), ('gameStateId', 101),
                             ('gameStateId', True), ('targets', []), ('type', 'ClientMessageType_SelectTargetsResp')):
            with self.subTest(field=field, value=value):
                rows = self.real_rows(); rows[109]['payload'][field] = value; self.absent(rows)

    def test_synthetic_diff_gap_typed_predecessor_and_identity_counterproofs(self):
        for mode in ('prev', 'float', 'new_id', 'card_ability', 'target_identity', 'migration'):
            with self.subTest(mode=mode):
                rows = self.real_rows(); gs = rows[107]['greToClientEvent']['greToClientMessages'][0]['gameStateMessage']
                if mode == 'prev': gs['prevGameStateId'] = 100
                elif mode == 'float': gs['prevGameStateId'] = 101.0
                elif mode == 'new_id': gs['gameStateId'] = 103
                elif mode in ('card_ability', 'target_identity'):
                    # Contradictory synthetic updates; never new real positives.
                    ident = 1264 if mode == 'card_ability' else 1262
                    e = self.evaluate(rows[:107]); obj = copy.deepcopy(e.reducer.objects[ident])
                    obj['type' if mode == 'card_ability' else 'grpId'] = 'GameObjectType_Ability' if mode == 'card_ability' else 999999
                    gs.setdefault('gameObjects', []).append(obj)
                else:
                    gs.setdefault('annotations', []).append({'type': ['AnnotationType_ObjectIdChanged'],
                        'affectorId': 1264, 'affectedIds': [1264], 'details': [
                            {'key': 'orig_id', 'type': 'KeyValuePairValueType_int32', 'valueInt32': [1264]},
                            {'key': 'new_id', 'type': 'KeyValuePairValueType_int32', 'valueInt32': [9999]}]})
                self.absent(rows)

    def test_synthetic_duplicate_diff_separate_and_same_record(self):
        for batched in (False, True):
            with self.subTest(batched=batched):
                rows = self.real_rows()
                if batched:
                    messages = rows[107]['greToClientEvent']['greToClientMessages']; messages.append(copy.deepcopy(messages[0]))
                else: rows.insert(108, copy.deepcopy(rows[107]))
                self.absent(rows)
        e = self.evaluate(self.real_rows(107))
        e.stage.prepare({'greToClientEvent': {'greToClientMessages': [
            {'gameStateMessage': {'gameStateId': 10000+i}} for i in range(1000)]}})
        self.assertIsNone(e.stage.revision.pending)
        self.assertTrue(e.stage.revision.suppressed)

    def test_synthetic_full_reset_cancel_undo_and_scope_changes(self):
        for mode in ('full', 'cancel', 'undo', 'auth', 'room'):
            with self.subTest(mode=mode):
                rows = self.real_rows()
                if mode == 'full': rows[107]['greToClientEvent']['greToClientMessages'][0]['gameStateMessage']['type'] = 'GameStateType_Full'
                elif mode in ('cancel', 'undo'):
                    rows.insert(108, {'payload': {'type': 'ClientMessageType_CancelActionReq' if mode == 'cancel' else 'ClientMessageType_UndoReq'}})
                elif mode == 'auth': rows.insert(108, copy.deepcopy(rows[0]))
                else: rows.insert(108, {'matchGameRoomStateChangedEvent': {'gameRoomInfo': {'gameRoomConfig': {'matchId': 'synthetic-other-match'}}}})
                self.absent(rows)

    def test_synthetic_retransmitted_consumed_or_competing_stage(self):
        for index, position in ((105, 106), (105, 107), (108, 109), (105, 108), (105, 109)):
            with self.subTest(index=index, position=position):
                rows = self.real_rows(); rows.insert(position, copy.deepcopy(rows[index])); self.absent(rows)
        rows = self.equip_rows()
        first_request = copy.deepcopy(rows[4])
        rows.insert(len(rows)-1, first_request)
        self.absent(rows)

    def test_missing_terminal_and_unfinished_eof_are_uncomparable(self):
        for cutoff in (106, 107, 108, 109):
            with self.subTest(cutoff=cutoff): self.absent(self.real_rows(cutoff))
        report = self.report(self.real_rows(109))
        self.assertEqual(report['uncomparable_target_episodes'], 1)
        self.assertEqual(report['episodes_without_reviewed_terminal'], 1)

    def test_partial_revokes_context_and_old_refs_cannot_restore_decision(self):
        rows = self.real_rows(); e = self.evaluate(rows[:109]); old = e.consumer.current_view()['current_snapshot_ref']
        self.assertIsNotNone(e.stage.revision.completion_context)
        e.publish(partial=True)
        self.assertIsNone(e.stage.revision.completion_context)
        self.assertEqual(e.consumer.current_decision_options()['options'], [])
        e.apply(rows[109]); e.apply(rows[108])
        self.assertEqual(e.target_completions.report()['historical_reviewed_target_sets_submitted'], 0)
        self.assertNotEqual(e.consumer.current_view()['current_snapshot_ref'], old)
        self.assertEqual(e.consumer.shadow_decision()['status'], 'expired')

    def test_frozen_preference_identity_tampering_cannot_enter_comparison(self):
        e = self.evaluate(self.equip_rows()[:-1]); completion = e.stage.revision.completion_context
        self.assertTrue(TargetStageCompletions._comparable(completion['frozen_shadow'], completion, completion['first_request_binding']))
        for mode in ('binding', 'ref', 'option_key', 'kind', 'policy', 'authority', 'ordinal', 'proposal'):
            with self.subTest(mode=mode):
                bad = copy.deepcopy(completion); frozen = bad['frozen_shadow']
                if mode == 'binding': frozen['binding']['request_id'] = 999
                elif mode == 'ref': frozen['snapshot_ref']['sequence'] += 1
                elif mode == 'option_key': frozen['decision']['preferred_option_key'] = 'unrelated'
                elif mode == 'kind': frozen['selected_option']['kind'] = 'current_selected_literal_probe'
                elif mode == 'policy': frozen['decision']['policy_version'] = 'unknown'
                elif mode == 'authority': frozen['decision']['input_sent'] = True
                elif mode == 'ordinal': frozen['record_ordinal'] = bad['update_record']
                else: frozen['selected_option']['proposal']['proposed_final_target_set']['object_refs'] = []
                self.assertFalse(TargetStageCompletions._comparable(frozen, bad, bad['first_request_binding']))

    def test_report_separates_unknown_domain_from_absent_and_competing(self):
        report = self.report(self.real_rows())
        self.assertEqual(report['target_requests_observed'], 2)
        self.assertEqual(report['first_stage_select_requests'], 1)
        self.assertEqual(report['current_select_domain_absent_requests'], 1)
        self.assertEqual(report['current_select_domain_unknown_requests'], 0)
        self.assertEqual(report['current_selected_literal_requests'], 1)
        self.assertEqual(report['multiple_complete_proposal_requests'], 1)
        self.assertIsNone(report['unknown_unlinked_episode_count'])
        self.assertFalse(report['complete_target_legality_verified'])
        self.assertFalse(report['complete_action_legality_verified'])

    def test_optin_preserves_complete_default_returns_and_frozen_policy(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'private-not-exported.log'
            path.write_text(''.join(json.dumps(row)+'\n' for row in self.real_rows()), encoding='utf8')
            off = []; on = []
            a = evaluate_shadow_history(path, _on_freeze=lambda *x: off.append(x))
            b = evaluate_shadow_history(path, target_stage_completions=True, _on_freeze=lambda *x: on.append(x))
            self.assertEqual(off, on)
            self.assertNotIn('target_stage_completions', a)
            b.pop('target_stage_completions'); b['timings_ms'].pop('target_stage_completions')
            a.pop('timings_ms'); b.pop('timings_ms')
            self.assertEqual(a, b)
            for invalid in (None, 1, 'true'):
                with self.assertRaises(ValueError): evaluate_shadow_history(path, target_stage_completions=invalid)

    def test_cli_explicit_optin_exports_bounded_aggregate_only(self):
        result = subprocess.run([sys.executable, '-m', 'mtgaplayer', 'evaluate-shadow-history',
            str(FIXTURES/'player_log_single_target.jsonl'), '--target-stage-completions'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        report = json.loads(result.stdout); stages = report['target_stage_completions']
        self.assertEqual(stages['historical_reviewed_target_sets_submitted'], 1)
        output = json.dumps(stages)
        for sensitive in ('1262', '1264', '10102', '10104', str(FIXTURES.resolve())): self.assertNotIn(sensitive, output)
        self.assertIs(report['input_sent'], False); self.assertEqual(report['P10'], 'NOT_RUN')


if __name__ == '__main__': unittest.main()
