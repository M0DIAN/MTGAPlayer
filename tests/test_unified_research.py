"""MP90 real retained fields with synthetic transport and adversarial controls.

The existing public MP87/89 projections remain the positive field evidence.
Authentication/Full transport, request replacements, injected policy reports and
all mutations below are synthetic controls, not additional real MTGA samples.
The owner separately authenticates/replays the original 42-opportunity archive.
"""
import copy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from mtgaplayer import land_development as land, target_effect as target
from mtgaplayer.decision_consumer import EXECUTION
from mtgaplayer.raw_log import RawFollower, RawReducer
from mtgaplayer.rules_index import PreparedRulesIndex
from mtgaplayer.shadow_runtime import LocalShadowRuntime, safe_summary
from mtgaplayer.shadow_decision import POLICY as SHADOW_POLICY
from mtgaplayer.unified_research import POLICY, combine_current_research
from test_combat_frontier import baseline
from test_raw_log import state as raw_state


FIXTURES = Path(__file__).parent / 'fixtures'


def encoded(rows):
    return ''.join(json.dumps(row, separators=(',', ':')) + '\n' for row in rows).encode()


def wrap(message):
    return {'greToClientEvent': {'greToClientMessages': [copy.deepcopy(message)]}}


def bootstrap(sample):
    rows = baseline()
    initial = sample['initial']
    raw_state(rows[2]).update(gameStateId=initial['state_id'],
        gameObjects=copy.deepcopy(initial['objects']), zones=copy.deepcopy(initial['zones']),
        players=copy.deepcopy(initial['players']), turnInfo=copy.deepcopy(initial['turn_info']))
    return rows


class Clock:
    def __init__(self):
        self.now = 1_000_000_000

    def __call__(self):
        return self.now


class UnifiedResearchTests(unittest.TestCase):
    def setUp(self):
        self.land_fixture = self.read('land_development_real.json')
        self.target_fixture = self.read('target_effect_real.json')
        self.land_sample = self.land_fixture['cases'][1]
        self.target_sample = next(row for row in self.target_fixture['cases'] if row['case'] == 'target-4')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.serial = 0

    @staticmethod
    def read(name):
        return json.loads((FIXTURES / name).read_text(encoding='utf8'))

    def prepared(self, name, mutate=None):
        value = self.read('land_static_reference_real.json' if name == 'land'
            else 'target_effect_reference_real.json')
        if mutate is not None:
            mutate(value)
        return PreparedRulesIndex(value['metadata'], {int(k): v for k, v in value['matches'].items()})

    def references(self):
        return {name: self.prepared(name) for name in ('land', 'target_effect')}

    def prelude(self):
        return ('\n'.join(self.target_fixture['resource_prelude']) + '\n').encode()

    def stream(self, sample=None, *, references=None, policy=POLICY, prelude=None, **kwargs):
        sample = copy.deepcopy(self.target_sample if sample is None else sample)
        self.serial += 1
        path = Path(self.tmp.name) / f'mp90-projected-{self.serial}.jsonl'
        path.write_bytes((self.prelude() if prelude is None else prelude) + encoded(bootstrap(sample)))
        clock = Clock()
        settings = {'research_policy': policy}
        if policy == POLICY:
            settings['prepared_references'] = self.references() if references is None else references
        elif policy in (land.POLICY, target.POLICY):
            settings['prepared_rules'] = self.prepared('land' if policy == land.POLICY else 'target_effect')
        runtime = LocalShadowRuntime(path, interval=0, samples=None, clock_ns=clock,
            observation_mode='controlled_stream_replay', **settings, **kwargs)
        gen = runtime.frames()
        self.addCleanup(runtime.close)
        self.addCleanup(gen.close)
        history = next(gen)
        frame = self.append(gen, path, [wrap(sample['message'])])
        return runtime, gen, path, clock, frame, history

    def append(self, gen, path, rows):
        with path.open('ab') as out:
            out.write(encoded(rows))
        return next(gen)

    def response(self, sample):
        message = sample['message']
        return {'payload': {'type': 'ClientMessageType_SelectTargetsResp',
            'respId': message['msgId'], 'gameStateId': message['gameStateId'],
            'selectTargetsResp': {'target': {'targetIdx': 1,
                'targets': [{'targetInstanceId': 2, 'legalAction': 'SelectAction_Select',
                    'highlight': 'HighlightType_Hot'}]}}}}

    def safe(self, report):
        self.assertTrue(report['read_only'])
        for key in EXECUTION:
            self.assertIs(report[key], False, key)
        self.assertIs(report['strategic_optimality_verified'], False)

    def denied(self, report):
        self.safe(report)
        self.assertNotEqual(report['status'], 'research_preference')
        self.assertIsNone(report['preferred_option_key'])

    def revoked(self, frame):
        self.assertNotEqual(frame['time_scope'], 'current_at_completed_poll')
        self.assertIsNone(frame['request_binding'])
        self.assertIsNone(frame['shadow_preference'])
        self.denied(frame['unified_research_decision'])
        self.assertEqual(frame['unified_research_decision']['status'], 'expired')
        self.assertIsNone(frame['unified_research_decision']['request_binding'])

    def combine(self, frame, shadow=None, research=None, target_evidence=None):
        return combine_current_research(frame['current_options'],
            frame['shadow_decision'] if shadow is None else shadow,
            frame.get('research_decision') if research is None else research,
            frame['local_evidence'].get('current_target_evidence') if target_evidence is None else target_evidence)

    def test_real_land_and_target_routing_keeps_original_detailed_results_and_same_binding(self):
        cases = ((self.land_sample, land.POLICY), (self.target_sample, target.POLICY))
        for sample, expected_policy in cases:
            with self.subTest(policy=expected_policy):
                _, _, _, _, frame, history = self.stream(sample)
                self.revoked(history)
                final = frame['unified_research_decision']; self.safe(final)
                self.assertEqual(final['status'], 'research_preference')
                self.assertEqual(final['policy_version'], POLICY)
                self.assertEqual(final['selected_policy'], expected_policy)
                self.assertEqual(final['preferred_option_key'], frame['research_decision']['preferred_option_key'])
                self.assertEqual(final['request_binding'], frame['request_binding'])
                self.assertEqual(final['source_snapshot_ref'], frame['source_snapshot_ref'])
                _, _, _, _, old, _ = self.stream(sample, policy=expected_policy)
                for key in ('current_options', 'shadow_decision', 'local_evidence', 'research_decision'):
                    # Snapshot stream identities are per runtime, while all
                    # authenticated request/candidate semantics are preserved.
                    self.assertEqual(self.normalized(frame[key]), self.normalized(old[key]))

    @staticmethod
    def normalized(value):
        if type(value) is dict:
            return {k: UnifiedResearchTests.normalized(v) for k, v in value.items()
                if k not in ('stream_id', 'source_snapshot_ref', 'source_version')}
        if type(value) is list:
            return [UnifiedResearchTests.normalized(v) for v in value]
        return value

    def test_real_target_projection_routes_all_fourteen_without_changing_mp89_or_mp66(self):
        routed = {'research_preference': 0, 'abstain': 0, 'unsupported': 0}
        unified = dict(routed)
        for sample in self.target_fixture['cases']:
            with self.subTest(case=sample['case']):
                runtime, _, _, _, frame, _ = self.stream(sample)
                detailed = frame['research_decision']
                self.assertEqual(detailed['policy_version'], target.POLICY)
                routed[detailed['status']] += 1
                result = frame['unified_research_decision']; self.safe(result)
                unified[result['status']] += 1
                self.assertEqual(frame['shadow_decision'], runtime.consumer.shadow_decision())
                if sample['case'] == 'target-1':
                    self.assertEqual(detailed['status'], 'unsupported')
                    self.assertEqual(result['selected_policy'], SHADOW_POLICY)
                    self.assertEqual(result['evidence_level'], frame['shadow_decision']['evidence_level'])
                    self.assertEqual(result['validation_scope'], frame['shadow_decision']['validation_scope'])
                    self.assertEqual(result['preferred_option_key'], frame['shadow_decision']['preferred_option_key'])
        self.assertEqual(routed, {'research_preference': 9, 'abstain': 4, 'unsupported': 1})
        self.assertEqual(unified, {'research_preference': 10, 'abstain': 4, 'unsupported': 0})

    def test_same_runtime_uses_one_follower_reducer_and_only_applicable_policy(self):
        with (patch('mtgaplayer.cli.RawFollower', wraps=RawFollower) as follower,
              patch('mtgaplayer.cli.RawReducer', wraps=RawReducer) as reducer,
              patch('mtgaplayer.target_effect.assess_current_target_effect', wraps=target.assess_current_target_effect) as targets,
              patch('mtgaplayer.land_development.assess_current_land_development', wraps=land.assess_current_land_development) as lands):
            runtime, gen, path, _, frame, _ = self.stream()
            owner = (runtime.consumer, runtime.publisher, runtime._reducer, runtime._watch)
            self.assertEqual(targets.call_count, 1)
            self.assertEqual(lands.call_count, 0)
            # Synthetic replacement tests dispatch, not a new positive land case.
            message = {'type': 'GREMessageType_ActionsAvailableReq', 'systemSeatIds': [1],
                'msgId': self.target_sample['message']['msgId'] + 100,
                'gameStateId': self.target_sample['message']['gameStateId'],
                'actionsAvailableReq': {'actions': [{'actionType': 'ActionType_Pass'}]}}
            fresh = self.append(gen, path, [self.response(self.target_sample), wrap(message)])
            self.assertEqual(fresh['request_binding']['request_type'], message['type'])
            self.assertEqual(lands.call_count, 1)
            self.assertEqual(targets.call_count, 1)
            self.assertEqual(follower.call_count, 1)
            self.assertEqual(reducer.call_count, 1)
            self.assertEqual((runtime.consumer, runtime.publisher, runtime._reducer, runtime._watch), owner)
            for call in (targets.call_args, lands.call_args):
                self.assertIs(call.args[0], runtime.consumer)
                self.assertIs(call.args[1], runtime._reducer)
            message = {'type': 'GREMessageType_MulliganReq', 'systemSeatIds': [1],
                'msgId': message['msgId'] + 1, 'gameStateId': message['gameStateId']}
            other = self.append(gen, path, [wrap(message)])
            self.assertEqual(other['shadow_decision']['status'], 'unsupported')
            self.assertEqual(other['unified_research_decision']['status'], 'unsupported')
            self.assertEqual((targets.call_count, lands.call_count), (1, 1))

    def test_missing_swapped_or_wrong_version_references_cannot_borrow_other_scope(self):
        for sample, name in ((self.land_sample, 'land'), (self.target_sample, 'target_effect')):
            other = 'target_effect' if name == 'land' else 'land'
            for mode in ('missing', 'swapped', 'wrong_version', 'wrong_hash'):
                with self.subTest(request=name, mode=mode):
                    refs = self.references()
                    if mode == 'missing':
                        refs.pop(name)
                    elif mode == 'swapped':
                        refs[name] = self.prepared(other)
                    else:
                        refs[name] = self.prepared(name, lambda value: value['metadata'].update(
                            {'source_version': 'Data=0;GRP=0'} if mode == 'wrong_version'
                            else {'source_sha256': '0' * 64}))
                    *_, frame, _ = self.stream(sample, references=refs)
                    self.denied(frame['research_decision'])
                    self.denied(frame['unified_research_decision'])

    def test_unknown_build_resource_blocks_new_research_without_changing_legacy_land_api(self):
        changed = self.prelude().replace(b'1329972', b'1329973')
        for sample in (self.land_sample, self.target_sample):
            with self.subTest(request=sample['message']['type']):
                *_, frame, _ = self.stream(sample, prelude=changed)
                self.denied(frame['unified_research_decision'])
        *_, legacy, _ = self.stream(self.land_sample, policy=land.POLICY, prelude=changed)
        self.assertEqual(legacy['research_decision']['status'], 'research_preference')

    def test_constructor_separates_reference_namespaces_and_preserves_legacy_parameters(self):
        path = Path(self.tmp.name) / 'unopened.jsonl'
        bad = [
            {'research_policy': POLICY, 'prepared_references': {'unknown': self.prepared('land')}},
            {'research_policy': POLICY, 'prepared_references': {'land': object()}},
            {'research_policy': POLICY, 'prepared_references': [],},
            {'research_policy': POLICY, 'prepared_references': self.references(), 'prepared_rules': self.prepared('land')},
            {'research_policy': land.POLICY, 'prepared_references': self.references()},
            {'research_policy': target.POLICY, 'prepared_references': self.references()},
            {'research_policy': None, 'prepared_references': {}},
        ]
        for arguments in bad:
            with self.subTest(arguments=tuple(arguments)):
                with self.assertRaises(ValueError):
                    LocalShadowRuntime(path, **arguments)

    def test_competing_current_candidates_abstain_instead_of_strategy_priority(self):
        *_, frame, _ = self.stream(self.land_sample)
        research = frame['research_decision']
        alternative = next(row for row in frame['current_options']['options']
            if row['option_key'] != research['preferred_option_key'])
        shadow = copy.deepcopy(frame['shadow_decision'])
        shadow.update(status='research_preference', reason='synthetic_conflicting_policy_control',
            preferred_option_key=copy.deepcopy(alternative['option_key']),
            evidence_level=alternative['evidence_level'], validation_scope=alternative['validation_scope'])
        result = self.combine(frame, shadow=shadow)
        self.denied(result)
        self.assertEqual(result['reason'], 'research_policy_conflict')
        self.assertIsNone(result['selected_policy'])

    def test_same_candidate_agreement_needs_full_current_identity_and_cannot_promote_evidence(self):
        *_, frame, _ = self.stream(self.land_sample)
        detailed = frame['research_decision']
        chosen = next(row for row in frame['current_options']['options']
            if row['option_key'] == detailed['preferred_option_key'])
        # Fault-injected agreement checks the aggregator only. It does not
        # claim MP66 would prefer this real complex ActionsAvailable request.
        shadow = copy.deepcopy(frame['shadow_decision'])
        shadow.update(status='research_preference', reason='synthetic_agreement_control',
            preferred_option_key=copy.deepcopy(chosen['option_key']),
            evidence_level=chosen['evidence_level'], validation_scope=chosen['validation_scope'])
        result = self.combine(frame, shadow=shadow)
        self.safe(result)
        self.assertEqual(result['status'], 'research_preference')
        self.assertEqual(result['preferred_option_key'], chosen['option_key'])
        self.assertEqual(set(result['contributing_policies']), {land.POLICY, SHADOW_POLICY})
        self.assertEqual(result['evidence_level'], chosen['evidence_level'])
        shadow['evidence_level'] = 'complete_legality_verified'
        with self.assertRaisesRegex(ValueError, 'current_candidate_unverified'):
            self.combine(frame, shadow=shadow)

    def test_global_expired_specialist_cannot_fall_back_to_still_frozen_base_preference(self):
        sample = next(row for row in self.target_fixture['cases'] if row['case'] == 'target-1')
        runtime, _, _, _, frame, _ = self.stream(sample)
        self.assertEqual(frame['shadow_decision']['status'], 'research_preference')
        original = target.assess_current_target_effect
        def expired(*args, **kwargs):
            result = original(*args, **kwargs)
            result.update(status='expired', reason='current_snapshot_expired_or_changed',
                request_binding=None, source_snapshot_ref=None, preferred_option_key=None)
            return result
        with patch('mtgaplayer.target_effect.assess_current_target_effect', side_effect=expired):
            self.revoked(runtime.current_frame())

    def test_identical_option_key_cannot_cross_engine_and_target_proposal_namespaces(self):
        *_, frame, _ = self.stream()
        shadow = copy.deepcopy(frame['shadow_decision'])
        # An injected MP66 report cannot claim MP84's local proposal just by
        # copying its option key, even under the same current request/ref.
        shadow.update(status='research_preference', preferred_option_key=copy.deepcopy(
            frame['research_decision']['preferred_option_key']))
        with self.assertRaisesRegex(ValueError, 'current_candidate_unverified'):
            self.combine(frame, shadow=shadow)
        evidence = copy.deepcopy(frame['local_evidence']['current_target_evidence'])
        chosen = next(row for row in evidence['local_proposals']
            if row['option_key'] == frame['research_decision']['preferred_option_key'])
        chosen['request_binding']['request_id'] += 1
        with self.assertRaisesRegex(ValueError, 'current_candidate_unverified'):
            self.combine(frame, target_evidence=evidence)

    def test_global_report_binding_or_state_change_discards_entire_unified_frame(self):
        for mode in ('binding', 'ref', 'digest', 'lease', 'resource', 'stop'):
            with self.subTest(mode=mode):
                runtime, _, _, clock, _, _ = self.stream(max_observation_age_ns=500_000_000,
                    max_event_silence_ns=500_000_000)
                original = target.assess_current_target_effect
                def changed(*args, **kwargs):
                    result = original(*args, **kwargs)
                    if mode == 'binding':
                        result['request_binding']['request_id'] += 1
                    elif mode == 'ref':
                        result['source_snapshot_ref']['sequence'] += 1
                    elif mode == 'digest':
                        runtime._reducer.accepted_digest = bytes(32)
                    elif mode == 'lease':
                        clock.now += 500_000_001
                    elif mode == 'resource':
                        runtime._reducer._target_resource_context = None
                    else:
                        runtime.close()
                    return result
                with patch('mtgaplayer.target_effect.assess_current_target_effect', side_effect=changed):
                    self.revoked(runtime.current_frame())

    def test_consumed_partial_full_gap_cancel_and_undo_never_restore_old_results(self):
        for mode in ('consumed', 'partial', 'full', 'gap', 'cancel', 'undo'):
            with self.subTest(mode=mode):
                runtime, gen, path, _, original, _ = self.stream()
                frozen = copy.deepcopy(original['unified_research_decision'])
                if mode == 'consumed':
                    frame = self.append(gen, path, [self.response(self.target_sample)])
                elif mode == 'partial':
                    with path.open('ab') as out:
                        out.write(b'{"synthetic_partial":')
                    frame = next(gen)
                elif mode == 'full':
                    full = bootstrap(self.target_sample)[2]
                    raw_state(full)['gameStateId'] += 1
                    frame = self.append(gen, path, [full])
                elif mode == 'gap':
                    frame = self.append(gen, path, [wrap({'type': 'GREMessageType_GameStateMessage',
                        'systemSeatIds': [1], 'gameStateMessage': {'type': 'GameStateType_Diff',
                            'gameStateId': 998, 'prevGameStateId': 997}})])
                else:
                    frame = self.append(gen, path, [{'payload': {'type':
                        'ClientMessageType_CancelActionReq' if mode == 'cancel' else 'ClientMessageType_UndoReq'}}])
                self.revoked(frame)
                if mode == 'partial':
                    with path.open('ab') as out:
                        out.write(b'1}\n')
                    self.revoked(next(gen))
                self.revoked(self.append(gen, path, [wrap(self.target_sample['message'])]))
                self.revoked(runtime.current_frame())
                self.assertEqual(original['unified_research_decision'], frozen)

    def test_same_poll_transient_preference_is_not_a_current_opportunity(self):
        runtime, gen, path, _, _, _ = self.stream()
        transient = copy.deepcopy(self.target_sample['message'])
        transient['msgId'] += 1
        response = self.response(self.target_sample)
        response['payload']['respId'] = transient['msgId']
        final = {'type': 'GREMessageType_MulliganReq', 'systemSeatIds': [1],
            'msgId': transient['msgId'] + 1, 'gameStateId': transient['gameStateId']}
        frame = self.append(gen, path, [wrap(transient), response, wrap(final)])
        self.assertEqual(frame['poll_accepted_requests'], 2)
        self.assertEqual(frame['poll_consumed_requests'], 1)
        self.assertEqual(frame['unified_research_decision']['request_binding']['request_id'], final['msgId'])
        self.assertEqual(frame['unified_research_decision']['status'], 'unsupported')
        self.assertIsNone(frame['unified_research_decision']['preferred_option_key'])

    def test_lease_expiry_stop_and_foreign_owner_revoke_without_cache_fallback(self):
        for mode in ('lease', 'stop', 'foreign_owner'):
            with self.subTest(mode=mode):
                runtime, _, _, clock, frame, _ = self.stream(max_observation_age_ns=500_000_000,
                    max_event_silence_ns=500_000_000)
                self.assertEqual(frame['unified_research_decision']['status'], 'research_preference')
                if mode == 'lease':
                    clock.now += 500_000_001
                    self.revoked(runtime.current_frame())
                elif mode == 'stop':
                    runtime.close(); self.revoked(runtime.current_frame())
                else:
                    reports = []
                    worker = threading.Thread(target=lambda: reports.append(runtime.current_frame()))
                    worker.start(); worker.join(3)
                    self.assertFalse(worker.is_alive())
                    self.revoked(reports[0])
                    self.assertEqual(reports[0]['reason'], 'owner_thread_required')

    def test_optin_default_compatibility_and_no_hot_path_sqlite_or_source_read(self):
        for sample in (self.land_sample, self.target_sample):
            with self.subTest(request=sample['message']['type']):
                _, _, _, _, default, _ = self.stream(sample, policy=None)
                runtime, _, _, _, unified, _ = self.stream(sample)
                self.assertNotIn('unified_research_decision', default)
                self.assertNotIn('unified_research_decision', safe_summary(default))
                for key in ('current_options', 'shadow_decision', 'local_evidence'):
                    self.assertEqual(self.normalized(default[key]), self.normalized(unified[key]))
                with (patch('mtgaplayer.rules_index.sqlite3.connect', side_effect=AssertionError('unexpected SQLite')),
                      patch('mtgaplayer.rules_index._file_sha256', side_effect=AssertionError('unexpected source read'))):
                    current = runtime.current_frame()
                self.assertEqual(current['unified_research_decision'], unified['unified_research_decision'])

    def test_safe_summary_does_not_export_current_keys_or_reference_payloads(self):
        *_, frame, _ = self.stream()
        frame['unified_research_decision']['private_path'] = 'PATH_SENTINEL'
        frame['unified_research_decision']['request_binding']['account'] = 'ACCOUNT_SENTINEL'
        frame['research_decision']['effect_source']['private_payload'] = 'RAW_SENTINEL'
        public = json.dumps(safe_summary(frame))
        for private in ('PATH_SENTINEL', 'ACCOUNT_SENTINEL', 'RAW_SENTINEL', 'fixture-local', 'fixture-match'):
            self.assertNotIn(private, public)
        self.assertFalse(json.loads(public)['input_sent'])


if __name__ == '__main__':
    unittest.main()
