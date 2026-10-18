"""Public retained samples with explicitly synthetic enclosing/stream controls.

No private original bytes are read or authenticated by this test. Search, Group,
Target and Cost bootstrap helpers reconstruct envelopes over portable projections;
the Cast prefix is an existing committed scrubbed real-format fixture.
"""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from mtgaplayer.current_cost_stage import assess_current_cost_stage, MANA_PROFILE
from mtgaplayer.decision_consumer import EXECUTION
from mtgaplayer.shadow_runtime import LocalShadowRuntime
from test_combat_frontier import baseline, request as combat_request, ATTACK, BLOCK
from test_current_cost_stage import controls as cost_request, rows_for as cost_rows
from test_current_group import rows_for as group_rows, response as group_response
from test_current_search import rows_for as search_rows
from test_current_target_request import rows_for as target_rows
from test_decision_input import rows as selectn_rows
from test_decision_publisher import ManualClock, append
from test_semantic_search import message, response as search_response


FIXTURES = Path(__file__).parent / 'fixtures'


class ShadowRuntimeFamilyTests(unittest.TestCase):
    def start(self, rows=None, raw=None):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / 'synthetic-stream.log'
        path.write_bytes(raw if raw is not None else b'')
        if rows is not None:
            append(path, rows)
        runtime = LocalShadowRuntime(path, interval=0, samples=50,
            clock_ns=ManualClock(), observation_mode='controlled_stream_replay')
        stream = runtime.frames()
        self.addCleanup(stream.close)
        self.addCleanup(runtime.close)
        first = next(stream)
        self.assertEqual(first['time_scope'], 'observed_in_history')
        self.assertIsNone(first['shadow_preference'])
        return runtime, stream, path

    def current(self, rows):
        runtime, stream, path = self.start(rows=rows[:-1])
        append(path, rows[-1:])
        frame = next(stream)
        self.assert_current(runtime, frame)
        return runtime, stream, path, frame

    def assert_current(self, runtime, frame):
        self.assertEqual(frame['time_scope'], 'current_at_completed_poll', frame['reason'])
        self.assertEqual(frame['observation_mode'], 'controlled_stream_replay')
        self.assertEqual(frame['request_binding'], frame['source_snapshot_ref']['binding'])
        self.assertEqual(frame['current_options'], runtime.consumer.current_decision_options())
        self.assertEqual(frame['shadow_decision'], runtime.consumer.shadow_decision())
        self.assertEqual(frame['shadow_policy_status'], frame['shadow_decision']['status'])
        self.assertEqual(frame['shadow_preference'], frame['shadow_decision']['preferred_option_key'])
        self.assertIsNone(frame['complete_legal_choices'])
        for report in (frame, frame['current_options'], frame['shadow_decision'], *frame['local_evidence'].values()):
            self.assertTrue(report['read_only'])
            for key in EXECUTION:
                self.assertIs(report[key], False, key)
        self.assertEqual(runtime.current_frame()['current_options'], frame['current_options'])

    def assert_independent_sidecar(self, runtime, frame, key, **kwargs):
        before = runtime.consumer.current_decision_options()
        policy = runtime.consumer.shadow_decision()
        independent = runtime.consumer.current_decision_options(**kwargs)
        self.assertEqual(independent.pop(key), frame['local_evidence'][key])
        self.assertEqual(independent, before)
        self.assertEqual(runtime.consumer.current_decision_options(), before)
        self.assertEqual(runtime.consumer.shadow_decision(), policy)

    def test_cast103_intents_keep_multi_slots_and_original_default_policy(self):
        lines = (FIXTURES / 'player_log_single_target.jsonl').read_bytes().splitlines(keepends=True)
        runtime, stream, path = self.start(raw=b''.join(lines[:102]))
        with path.open('ab') as output:
            output.write(lines[102])
        frame = next(stream)
        self.assert_current(runtime, frame)
        self.assertEqual(frame['request_type'], 'GREMessageType_ActionsAvailableReq')
        self.assert_independent_sidecar(runtime, frame, 'complex_action_intents', include_complex_intents=True)
        intents = {item['list_position']: item for item in frame['local_evidence']['complex_action_intents']['intents']}
        self.assertEqual(list(intents), [0, 1, 2, 3, 4])
        self.assertEqual([slot['target_idx'] for slot in intents[2]['target_slots']], [2, 1])
        self.assertNotEqual(intents[2]['action_key'], intents[3]['action_key'])
        self.assertFalse(intents[2]['complete_action_proposal_verified'])
        self.assertEqual(frame['shadow_policy_status'], 'abstain')

    def test_current_target_slices_reuse_original_interface_without_policy_upgrade(self):
        samples = json.loads((FIXTURES / 'current_target_no_cancel_real.json').read_text(encoding='utf-8'))['cases']
        for sample in samples:
            with self.subTest(proposals=len(sample['message']['selectTargetsReq']['targets'][0]['targets'])):
                runtime, _, _, frame = self.current(target_rows(sample))
                self.assertEqual(frame['request_type'], 'GREMessageType_SelectTargetsReq')
                key = 'current_target_evidence'
                self.assert_independent_sidecar(runtime, frame, key,
                    current_target_context=(runtime._reducer, runtime._message))
                local = frame['local_evidence'][key]
                self.assertEqual(local['status'], 'observed')
                self.assertGreater(local['returned_proposals'], 0)
                self.assertFalse(local['complete_target_legality_verified'])
                self.assertNotEqual(frame['shadow_policy_status'], 'research_preference')

    def test_current_mana_cost_reuses_same_stage_and_preserves_unknown_payment(self):
        samples = json.loads((FIXTURES / 'current_mana_cost_real_v1.json').read_text(encoding='utf-8'))['samples']
        for sample in samples:
            with self.subTest(sample=sample.get('source_record')):
                rows = cost_rows(sample) + [{'greToClientEvent': {'greToClientMessages': [cost_request(sample)]}}]
                runtime, _, _, frame = self.current(rows)
                stage = frame['local_evidence']['current_cost_stage']
                self.assertEqual(stage, assess_current_cost_stage(runtime.consumer, runtime._reducer,
                    runtime._message, mana_requirement_match=True))
                self.assertEqual(stage['status'], 'observed')
                self.assertEqual(stage['cost_request_profile'], MANA_PROFILE)
                self.assertFalse(stage['complete_payment_verified'])
                self.assertEqual(stage['local_candidates'], [])
                self.assertEqual(frame['shadow_policy_status'], 'unsupported')
                self.assertIsNone(frame['shadow_preference'])

    def test_two_search_slices_keep_member_denominators_separate_from_actions(self):
        samples = json.loads((FIXTURES / 'current_search_real_v1.json').read_text(encoding='utf-8'))['samples']
        sizes = []
        for sample in samples:
            runtime, _, _, frame = self.current(search_rows(sample))
            self.assert_independent_sidecar(runtime, frame, 'current_search_evidence',
                current_search_context=(runtime._reducer, runtime._message))
            local = frame['local_evidence']['current_search_evidence']
            self.assertEqual(local['status'], 'observed')
            sizes.append(local['returned_members'])
            self.assertIsNone(frame['engine_offered_coverage']['engine_offered_count'])
            self.assertIsNone(local['complete_proposal_count'])
            self.assertIsNone(local['min_find'])
            self.assertEqual(local['complete_proposals'], [])
            self.assertEqual(frame['shadow_policy_status'], 'unsupported')
        self.assertEqual(sizes, [8, 7])

    def test_three_group_slices_keep_unknown_identities_and_no_complete_proposals(self):
        samples = json.loads((FIXTURES / 'current_group_real_v1.json').read_text(encoding='utf-8'))['samples']
        self.assertEqual(len(samples), 3)
        for sample in samples:
            runtime, _, _, frame = self.current(group_rows(sample))
            self.assert_independent_sidecar(runtime, frame, 'current_group_evidence',
                current_group_context=(runtime._reducer, runtime._message))
            local = frame['local_evidence']['current_group_evidence']
            self.assertEqual(local['status'], 'observed')
            self.assertEqual(local['unresolved_item_count'], 2)
            self.assertEqual(local['reviewed_member_count'], 0)
            self.assertTrue(all(item['card_id'] is None for item in local['unresolved_item_references']))
            self.assertEqual(local['complete_proposals'], [])
            self.assertIsNone(local['complete_legal_choices'])
            self.assertEqual(frame['shadow_policy_status'], 'unsupported')

    def test_selectn_uses_original_candidates_and_abstains(self):
        rows = selectn_rows()
        index = next(i for i, row in enumerate(rows) if any(
            item.get('type') == 'GREMessageType_SelectNReq' for item in
            row.get('greToClientEvent', {}).get('greToClientMessages', [])))
        _, _, _, frame = self.current(rows[:index + 1])
        self.assertEqual(frame['request_type'], 'GREMessageType_SelectNReq')
        self.assertEqual(frame['engine_offered_coverage']['engine_offered_unit'], 'offered_member')
        self.assertEqual(frame['local_evidence'], {})
        self.assertEqual(frame['shadow_policy_status'], 'abstain')
        self.assertEqual(frame['abstention_reason'], 'combination_or_tactical_basis_unverified')

    def test_combat_request_families_reuse_existing_candidates_and_unknown_combinations(self):
        for typ, unit in ((ATTACK, 'attacker_candidate'), (BLOCK, 'blocker_candidate')):
            with self.subTest(typ=typ):
                _, _, _, frame = self.current(baseline() + [combat_request(typ)])
                self.assertEqual(frame['request_type'], typ)
                self.assertEqual(frame['engine_offered_coverage']['engine_offered_unit'], unit)
                self.assertEqual(frame['local_evidence'], {})
                self.assertEqual(frame['shadow_policy_status'], 'abstain')
                self.assertIsNone(frame['shadow_preference'])

    def test_mulligan_and_unknown_request_are_explicitly_unsupported(self):
        for name in ('Mulligan', 'SyntheticUnknownFamily'):
            with self.subTest(name=name):
                request = {'type': f'GREMessageType_{name}Req', 'systemSeatIds': [1],
                    'msgId': 990, 'gameStateId': 1}
                _, _, _, frame = self.current(baseline() + [
                    {'greToClientEvent': {'greToClientMessages': [request]}}])
                self.assertEqual(frame['request_support'], 'unsupported')
                self.assertEqual(frame['shadow_policy_status'], 'unsupported')
                self.assertEqual(frame['abstention_reason'], 'request_strategy_unsupported')
                self.assertIsNone(frame['engine_offered_coverage']['engine_offered_count'])
                self.assertIsNone(frame['complete_legal_choices'])
                self.assertEqual(frame['current_options']['options'], [])

    def test_two_requests_in_one_poll_output_only_final_group_and_never_search(self):
        sample = json.loads((FIXTURES / 'current_search_real_v1.json').read_text(encoding='utf-8'))['samples'][0]
        search = search_rows(sample)
        group = group_rows()[-1]
        message(group)['msgId'] = 991
        runtime, stream, path = self.start(rows=search[:-1])
        append(path, [search[-1], group])
        frame = next(stream)
        self.assert_current(runtime, frame)
        self.assertEqual(frame['poll_accepted_requests'], 2)
        self.assertEqual(frame['request_binding']['request_id'], 991)
        self.assertEqual(frame['request_type'], 'GREMessageType_GroupReq')
        self.assertEqual(set(frame['local_evidence']), {'current_group_evidence'})
        self.assertNotIn('current_search_evidence', frame['current_options'])
        old = copy.deepcopy(frame)
        response = group_response()
        response['payload']['respId'] = 991
        append(path, [response])
        consumed = next(stream)
        self.assertEqual(consumed['time_scope'], 'expired_or_revoked')
        self.assertIsNone(consumed['current_options'])
        self.assertIsNone(runtime.current_frame()['shadow_preference'])
        self.assertEqual(old['request_binding']['request_id'], 991)
        self.assertIsNotNone(old['source_snapshot_ref'])

    def test_request_consumed_within_same_poll_never_outputs_current_or_cached_sidecar(self):
        sample = json.loads((FIXTURES / 'current_search_real_v1.json').read_text(encoding='utf-8'))['samples'][0]
        for rows, response in ((search_rows(sample), search_response()), (group_rows(), group_response())):
            with self.subTest(request_type=message(rows[-1])['type']):
                runtime, stream, path = self.start(rows=rows[:-1])
                append(path, [rows[-1], response])
                frame = next(stream)
                self.assertEqual(frame['poll_accepted_requests'], 1)
                self.assertEqual(frame['poll_consumed_requests'], 1)
                self.assertEqual(frame['time_scope'], 'expired_or_revoked')
                self.assertIsNone(frame['request_binding'])
                self.assertIsNone(frame['current_options'])
                self.assertEqual(frame['local_evidence'], {})
                self.assertIsNone(runtime.current_frame()['shadow_preference'])


if __name__ == '__main__':
    unittest.main()
