"""MP93 routing/arbitration controls over retained public projections.

Swamp transport and all fault injections are synthetic, not a second real
MP91 positive. The owner separately replays the authenticated original bytes.
"""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from mtgaplayer import land_development as land, target_effect as target
from mtgaplayer.raw_log import RawFollower, RawReducer
from mtgaplayer.shadow_runtime import LocalShadowRuntime, safe_summary
from mtgaplayer.unified_research import POLICY, V2_POLICY, combine_current_research
import test_unified_research as old
from test_land_swamp import prepared as swamp_reference


def normalized(value):
    """Retain versions, binding and evidence; omit random ref transport only."""
    if type(value) is list:
        return [normalized(v) for v in value]
    if type(value) is dict:
        return {k: ({'binding': normalized(v['binding'])}
            if k in ('source_snapshot_ref', 'current_snapshot_ref') and type(v) is dict
            else normalized(v)) for k, v in value.items()}
    return value


class UnifiedV2Tests(unittest.TestCase):
    # Share fixture/transport helpers, without inheriting or rerunning v1 tests.
    setUp = old.UnifiedResearchTests.setUp
    read = staticmethod(old.UnifiedResearchTests.read)
    prepared = old.UnifiedResearchTests.prepared
    prelude = old.UnifiedResearchTests.prelude
    append = old.UnifiedResearchTests.append
    response = old.UnifiedResearchTests.response
    safe = old.UnifiedResearchTests.safe
    denied = old.UnifiedResearchTests.denied
    revoked = old.UnifiedResearchTests.revoked

    def references(self):
        return {'land': swamp_reference(), 'target_effect': self.prepared('target_effect')}

    def stream(self, sample=None, *, policy=V2_POLICY, references=None, prelude=None, **kwargs):
        sample = copy.deepcopy(self.target_sample if sample is None else sample)
        self.serial += 1
        path = Path(self.tmp.name) / f'mp93-synthetic-transport-{self.serial}.jsonl'
        path.write_bytes((self.prelude() if prelude is None else prelude) + old.encoded(old.bootstrap(sample)))
        clock = old.Clock()
        settings = {'research_policy': policy}
        if policy in (POLICY, V2_POLICY):
            settings['prepared_references'] = self.references() if references is None else references
        elif policy is not None:
            settings['prepared_rules'] = (swamp_reference() if policy in (land.POLICY, land.SWAMP_POLICY)
                else self.prepared('target_effect'))
        runtime = LocalShadowRuntime(path, interval=0, samples=None, clock_ns=clock,
            observation_mode='controlled_stream_replay', **settings, **kwargs)
        gen = runtime.frames()
        self.addCleanup(runtime.close); self.addCleanup(gen.close)
        history = next(gen)
        frame = self.append(gen, path, [old.wrap(sample['message'])])
        return runtime, gen, path, clock, frame, history

    def swamp(self):
        sample = copy.deepcopy(self.land_sample)
        play = next(r for r in sample['message']['actionsAvailableReq']['actions']
            if r['actionType'] == 'ActionType_Play')
        play['grpId'] = 106531
        next(o for o in sample['initial']['objects'] if o['instanceId'] == play['instanceId'])['grpId'] = 106531
        return sample

    def combine(self, frame, shadow=None, research=None, target_evidence=None):
        return combine_current_research(frame['current_options'],
            frame['shadow_decision'] if shadow is None else shadow,
            frame.get('research_decision') if research is None else research,
            frame['local_evidence'].get('current_target_evidence') if target_evidence is None else target_evidence,
            policy_version=V2_POLICY)

    def test_swamp_v2_is_explicit_and_default_arbiter_does_not_upgrade(self):
        sample = self.swamp()
        *_, frame, history = self.stream(sample)
        self.revoked(history)
        self.assertEqual(history['unified_research_decision']['policy_version'], V2_POLICY)
        final = frame['unified_research_decision']; self.safe(final)
        self.assertEqual(final['status'], 'research_preference')
        self.assertEqual(final['selected_policy'], land.SWAMP_POLICY)
        self.assertEqual(final['preferred_option_key'], frame['research_decision']['preferred_option_key'])
        *_, legacy, _ = self.stream(sample, policy=POLICY)
        self.assertEqual(legacy['research_decision']['policy_version'], land.POLICY)
        self.denied(legacy['unified_research_decision'])
        for candidate, report, version in ((frame, frame['research_decision'], POLICY),
                (legacy, legacy['research_decision'], V2_POLICY)):
            with self.subTest(version=version), self.assertRaisesRegex(ValueError, 'current_policy_binding_invalid'):
                combine_current_research(candidate['current_options'], candidate['shadow_decision'], report,
                    policy_version=version)
        with self.assertRaisesRegex(ValueError, 'current_policy_binding_invalid'):
            combine_current_research(frame['current_options'], frame['shadow_decision'], frame['research_decision'])
        for version in ('unified_research.v3', True, None):
            with self.subTest(version=version), self.assertRaisesRegex(ValueError, 'current_policy_binding_invalid'):
                combine_current_research(frame['current_options'], frame['shadow_decision'], policy_version=version)

    def test_actual_dispatch_uses_same_owner_and_existing_land_v2_assessor(self):
        with (patch('mtgaplayer.cli.RawFollower', wraps=RawFollower) as follower,
              patch('mtgaplayer.cli.RawReducer', wraps=RawReducer) as reducer,
              patch('mtgaplayer.target_effect.assess_current_target_effect', wraps=target.assess_current_target_effect) as targets,
              patch('mtgaplayer.land_development.assess_current_land_development', wraps=land.assess_current_land_development) as lands):
            runtime, gen, path, _, _, _ = self.stream()
            owner = (runtime.consumer, runtime.publisher, runtime._reducer, runtime._watch)
            message = {'type': 'GREMessageType_ActionsAvailableReq', 'systemSeatIds': [1],
                'msgId': self.target_sample['message']['msgId'] + 100,
                'gameStateId': self.target_sample['message']['gameStateId'],
                'actionsAvailableReq': {'actions': [{'actionType': 'ActionType_Pass'}]}}
            frame = self.append(gen, path, [self.response(self.target_sample), old.wrap(message)])
            self.assertEqual(frame['research_decision']['policy_version'], land.SWAMP_POLICY)
            self.assertEqual(lands.call_args.kwargs['policy_version'], land.SWAMP_POLICY)
            self.assertIs(lands.call_args.args[0], runtime.consumer)
            self.assertIs(lands.call_args.args[1], runtime._reducer)
            self.assertIs(lands.call_args.args[3], runtime.prepared_references['land'])
            message.update(type='GREMessageType_MulliganReq', msgId=message['msgId'] + 1)
            message.pop('actionsAvailableReq')
            other = self.append(gen, path, [old.wrap(message)])
            self.assertEqual(other['unified_research_decision']['status'], 'unsupported')
            self.assertEqual((targets.call_count, lands.call_count), (1, 1))
            self.assertEqual((follower.call_count, reducer.call_count), (1, 1))
            self.assertEqual(owner, (runtime.consumer, runtime.publisher, runtime._reducer, runtime._watch))

    def test_all_retained_target_reports_and_weak_mp66_evidence_remain_identical(self):
        counts = {'research_preference': 0, 'abstain': 0, 'unsupported': 0}
        for sample in self.target_fixture['cases']:
            with self.subTest(case=sample['case']):
                *_, current, _ = self.stream(sample)
                *_, previous, _ = self.stream(sample, policy=POLICY)
                for field in ('current_options', 'shadow_decision', 'research_decision', 'local_evidence'):
                    self.assertEqual(normalized(current[field]), normalized(previous[field]))
                final = copy.deepcopy(current['unified_research_decision'])
                counts[final['status']] += 1
                final['policy_version'] = POLICY
                self.assertEqual(normalized(final), normalized(previous['unified_research_decision']))
                if sample['case'] == 'target-1':
                    self.assertEqual(final['selected_policy'], current['shadow_decision']['policy_version'])
                    self.assertEqual(final['evidence_level'], current['shadow_decision']['evidence_level'])
        self.assertEqual(counts, {'research_preference': 10, 'abstain': 4, 'unsupported': 0})

    # These direct v1 adversarial controls run through the new explicit mode.
    test_v2_conflicting_candidates_abstain = old.UnifiedResearchTests.test_competing_current_candidates_abstain_instead_of_strategy_priority
    test_v2_candidate_namespaces_remain_separate = old.UnifiedResearchTests.test_identical_option_key_cannot_cross_engine_and_target_proposal_namespaces
    test_v2_missing_or_wrong_references_fail_closed = old.UnifiedResearchTests.test_missing_swapped_or_wrong_version_references_cannot_borrow_other_scope
    test_v2_computation_mutations_revoke_every_report = old.UnifiedResearchTests.test_global_report_binding_or_state_change_discards_entire_unified_frame
    test_v2_consumption_partial_reset_gap_cancel_undo_do_not_revive = old.UnifiedResearchTests.test_consumed_partial_full_gap_cancel_and_undo_never_restore_old_results
    test_v2_expired_specialist_cannot_use_frozen_mp66 = old.UnifiedResearchTests.test_global_expired_specialist_cannot_fall_back_to_still_frozen_base_preference
    test_v2_lease_stop_foreign_owner_revoke = old.UnifiedResearchTests.test_lease_expiry_stop_and_foreign_owner_revoke_without_cache_fallback

    def test_v2_constructor_fallback_and_bounded_summary(self):
        path = Path(self.tmp.name) / 'unopened'
        for kwargs in ({'prepared_rules': swamp_reference()}, {'prepared_references': {'unknown': swamp_reference()}},
                {'prepared_references': {'land': object()}}):
            with self.subTest(kwargs=tuple(kwargs)), self.assertRaises(ValueError):
                LocalShadowRuntime(path, research_policy=V2_POLICY, **kwargs)
        runtime = LocalShadowRuntime(path, research_policy=V2_POLICY)
        self.addCleanup(runtime.close)
        self.revoked(runtime.current_frame())
        self.assertEqual(runtime.current_frame()['unified_research_decision']['policy_version'], V2_POLICY)
        runtime, _, _, _, frame, _ = self.stream(self.swamp())
        with (patch('mtgaplayer.rules_index.sqlite3.connect', side_effect=AssertionError('hot SQLite')),
              patch('mtgaplayer.rules_index._file_sha256', side_effect=AssertionError('hot source read'))):
            self.assertEqual(runtime.current_frame()['unified_research_decision'], frame['unified_research_decision'])
        summary = safe_summary(frame)
        self.assertEqual(summary['unified_research_decision']['policy_version'], V2_POLICY)
        self.assertEqual(summary['unified_research_decision']['selected_policy'], land.SWAMP_POLICY)
        self.assertTrue({'research_policy', 'unified_dispatch'} <= set(summary['timings_ns']))
        frame['unified_research_decision']['private_path'] = 'PATH_SENTINEL'
        frame['research_decision']['private_payload'] = 'RAW_SENTINEL'
        public = json.dumps(safe_summary(frame))
        for private in ('PATH_SENTINEL', 'RAW_SENTINEL', '106531', 'fixture-match'):
            self.assertNotIn(private, public)
        self.assertFalse(summary['input_sent'])


if __name__ == '__main__':
    unittest.main()
