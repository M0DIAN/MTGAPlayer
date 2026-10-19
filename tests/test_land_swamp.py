"""MP92 actual frozen semantic inputs and explicitly synthetic runtime controls.

The public projection is not a GRE log or authentication fixture. The separate
runtime tests change an MP87 fixture to exercise wiring/lifecycle, never to
claim a second real MP91 request or historical lease measurement.
"""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from mtgaplayer import land_development as land
from mtgaplayer.decision_consumer import EXECUTION
from mtgaplayer.rules_index import PreparedRulesIndex
from mtgaplayer.shadow_runtime import LocalShadowRuntime, safe_summary
from test_land_development import bootstrap, encoded, wrap, Clock

FIXTURES = Path(__file__).parent / 'fixtures'


def read(name):
    return json.loads((FIXTURES / name).read_text(encoding='utf8'))


def prepared():
    ref = read('land_swamp_reference_real.json')
    return PreparedRulesIndex(ref['metadata'], {int(k): v for k, v in ref['matches'].items()})


class LandSwampTests(unittest.TestCase):
    def setUp(self):
        self.real = read('land_swamp_current_real.json')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.serial = 0

    def frozen(self, options=None, reviewed=None, reference=None):
        return land._swamp_extension(self.real['current_options'] if options is None else options,
            self.real['reviewed_land_v1'] if reviewed is None else reviewed,
            prepared() if reference is None else reference)

    def denied(self, report):
        self.assertNotEqual(report['status'], 'research_preference')
        self.assertIsNone(report['preferred_option_key'])
        self.assertFalse(report['strategic_optimality_verified'])
        for key in EXECUTION:
            self.assertIs(report[key], False)

    def stream(self, *, policy=land.SWAMP_POLICY, prefix=True, card_id=106531, phase=None, **kwargs):
        # Invented Swamp transport over the old public Island test, explicitly
        # distinct from the real frozen MP91 policy inputs tested above.
        sample = copy.deepcopy(read('land_development_real.json')['cases'][1])
        play = next(r for r in sample['message']['actionsAvailableReq']['actions'] if r['actionType'] == 'ActionType_Play')
        play['grpId'] = card_id
        next(o for o in sample['initial']['objects'] if o['instanceId'] == play['instanceId'])['grpId'] = card_id
        if phase is not None:
            sample['initial']['turn_info']['phase'] = phase
        self.serial += 1
        path = Path(self.temp.name) / f'synthetic-route-{self.serial}.jsonl'
        prelude = ('\n'.join(read('target_effect_real.json')['resource_prelude']) + '\n').encode() if prefix else b''
        path.write_bytes(prelude + encoded(bootstrap(sample)))
        clock = Clock()
        runtime = LocalShadowRuntime(path, interval=0, samples=None, clock_ns=clock,
            observation_mode='controlled_stream_replay', research_policy=policy,
            prepared_rules=prepared(), **kwargs)
        gen = runtime.frames()
        self.addCleanup(runtime.close); self.addCleanup(gen.close)
        next(gen)
        with path.open('ab') as out:
            out.write(encoded([wrap(sample['message'])]))
        return runtime, gen, path, clock, next(gen), sample

    def test_actual_frozen_unique_swamp_has_one_deterministic_preference(self):
        self.assertEqual(self.real['origin'], 'retained_scrubbed_real_frozen_current_projection')
        self.assertFalse(self.real['raw_equivalent'])
        receipt = json.loads((FIXTURES.parents[1] / 'docs/evidence/mp92-owner.json').read_text(encoding='utf8'))
        for name, field in (('land_swamp_current_real.json', 'public_current_fixture_sha256_lf'),
                ('land_swamp_reference_real.json', 'public_reference_fixture_sha256_lf')):
            self.assertEqual(hashlib.sha256((FIXTURES / name).read_bytes().replace(b'\r\n', b'\n')).hexdigest(),
                receipt[field])
        before = copy.deepcopy(self.real)
        result = self.frozen()
        self.assertEqual(result, self.frozen())
        self.assertEqual(self.real, before)
        self.assertEqual(result['status'], 'research_preference')
        self.assertEqual(result['policy_version'], land.SWAMP_POLICY)
        self.assertEqual(result['source_identity']['card_id'], 106531)
        self.assertEqual(result['preferred_option_key'], {'kind': 'engine_action', 'source': 'decision_advisor', 'source_position': 6})
        self.assertEqual(result['coverage']['active_action_rows'], 12)
        self.assertEqual(result['coverage']['play_offers'], 1)
        self.assertEqual(result['land_profile_evidence']['reference']['subtypes'][0]['label'], 'Swamp')
        self.assertEqual(result['phase_evidence']['stack_availability'], 'unknown')
        self.assertIn('stack_emptiness_unknown_not_inferred', result['unresolved'])
        self.assertFalse(result['land_profile_evidence']['effective_mana_production_verified'])
        self.assertFalse(result['complete_legality_verified'])
        self.assertFalse(result['strategic_optimality_verified'])
        self.assertEqual(self.real['reviewed_land_v1']['reason'], 'static_land_identity_unverified')

    def test_only_exact_reviewed_island_and_swamp_profiles_are_admitted(self):
        refs = read('land_swamp_reference_real.json')['matches']
        self.assertTrue(land._ordinary(refs['96839']['card']))
        self.assertFalse(land._ordinary(refs['106531']['card']))
        self.assertTrue(land._ordinary_swamp(refs['106531']['card']))
        for ident in ('96828', '106533', '95062', '92359', '96839'):
            self.assertFalse(land._ordinary_swamp(refs[ident]['card']), ident)
        for field, value in (('AbilityIds', '123:456'), ('AdditionalFrameDetails', 'hybrid'),
                ('LinkedFaceType', 1), ('IsDigitalOnly', 1), ('RawFrameDetail', 'U'),
                ('Subtypes', '54,69'), ('SubtypeTextId', True)):
            card = copy.deepcopy(refs['106531']['card']); card['profile'][field] = value
            self.assertFalse(land._ordinary_swamp(card), field)
        card = copy.deepcopy(refs['106531']['card']); card['reverse_face_link_observed'] = True
        self.assertFalse(land._ordinary_swamp(card))

    def test_frozen_binding_inventory_visibility_and_phase_counterexamples(self):
        for mode in ('binding', 'ref', 'truncated', 'omitted', 'missing', 'duplicate', 'seat',
                'hidden', 'source', 'phase', 'step', 'stack', 'unreviewed'):
            options = copy.deepcopy(self.real['current_options'])
            reviewed = copy.deepcopy(self.real['reviewed_land_v1'])
            play = next(o for o in options['options'] if o['observation']['engine_action_type'] == 'ActionType_Play')
            if mode == 'binding': reviewed['request_binding']['request_id'] += 1
            elif mode == 'ref': reviewed['source_snapshot_ref']['sequence'] += 1
            elif mode == 'truncated': options['coverage']['truncated'] = True
            elif mode == 'omitted': options['coverage']['omitted_constructed_options'] = 1
            elif mode == 'missing': options['options'].remove(play)
            elif mode == 'duplicate': options['options'].append(copy.deepcopy(play))
            elif mode == 'seat': options['visible_state']['visible_objects'][0]['controller_seat'] = 2
            elif mode == 'hidden': options['visible_state']['visible_objects'][0]['zone'] = 'ZoneType_Library'
            elif mode == 'source': play['observation']['source_card_identity_agreement'] = False
            elif mode == 'phase': options['visible_state']['game']['turn']['phase'] = 'Phase_Main2'
            elif mode == 'step': options['visible_state']['game']['turn']['step'] = 'Step_Upkeep'
            elif mode == 'stack': options['visible_state']['game']['stack']['availability'] = 'observed_nonempty'
            else: play['observation']['unknown_parameter_fields_present'] = True
            with self.subTest(mode=mode), self.assertRaises((ValueError, KeyError)):
                self.frozen(options, reviewed)

    def test_missing_or_wrong_static_source_and_nonbasic_do_not_grant_preference(self):
        for mode in ('missing', 'hash', 'nonbasic'):
            ref = read('land_swamp_reference_real.json')
            if mode == 'missing': ref['matches'].pop('106531')
            elif mode == 'hash': ref['metadata']['source_sha256'] = '0' * 64
            else:
                ref['matches']['106531']['card']['profile']['AbilityIds'] = '123:456'
            reference = PreparedRulesIndex(ref['metadata'], {int(k): v for k, v in ref['matches'].items()})
            with self.subTest(mode=mode):
                if mode == 'hash':
                    with self.assertRaises(ValueError): self.frozen(reference=reference)
                else: self.denied(self.frozen(reference=reference))

    def test_multiple_play_and_prior_refusal_are_not_filtered_into_uniqueness(self):
        for reason in ('multiple_play_competitors', 'no_play_offered', 'active_action_structure_unreviewed'):
            reviewed = copy.deepcopy(self.real['reviewed_land_v1']); reviewed['reason'] = reason
            result = self.frozen(reviewed=reviewed)
            self.denied(result)
            self.assertEqual(result['reason'], reason)

    def test_runtime_explicit_opt_in_and_original_single_policy_remains_abstained(self):
        runtime, _, _, _, frame, _ = self.stream()
        result = frame['research_decision']
        self.assertEqual(result['status'], 'research_preference')
        self.assertEqual(result['policy_version'], land.SWAMP_POLICY)
        self.assertEqual(result['source_snapshot_ref'], frame['source_snapshot_ref'])
        self.assertEqual(frame['shadow_decision']['status'], 'abstain')
        self.assertNotIn('unified_research_decision', frame)
        summary = safe_summary(frame)
        self.assertEqual(summary['research_decision']['policy_version'], land.SWAMP_POLICY)
        self.assertEqual(summary['research_decision']['coverage']['ordinary_profile_candidates'], 1)
        self.assertNotIn('106531', json.dumps(summary))
        self.assertFalse(summary['input_sent'])
        original = runtime.consumer.current_decision_options
        with patch.object(runtime.consumer, 'current_decision_options', wraps=original) as current:
            result = land.assess_current_land_development(runtime.consumer, runtime._reducer,
                runtime._message, prepared(), policy_version=land.SWAMP_POLICY,
                completed_stamp=runtime._completed_stamp)
        self.assertEqual(result['status'], 'research_preference')
        self.assertEqual(current.call_count, 1)  # No second options computation for the extension.
        *_, old_frame, _ = self.stream(policy=land.POLICY)
        self.denied(old_frame['research_decision'])
        self.assertEqual(old_frame['research_decision']['reason'], 'ordinary_land_profile_unverified')

    def test_new_policy_requires_actual_source_resource_capability(self):
        *_, frame, _ = self.stream(prefix=False)
        self.denied(frame['research_decision'])
        self.assertEqual(frame['research_decision']['reason'], 'exact_build_resource_provenance_unverified')

    def test_current_request_lifecycle_never_restores_new_preference(self):
        for mode in ('consumed', 'replacement', 'lease', 'partial', 'reset', 'gap', 'cancel', 'undo', 'stop'):
            runtime, gen, path, clock, frame, sample = self.stream()
            self.assertEqual(frame['research_decision']['status'], 'research_preference')
            if mode == 'lease': clock.now += 5_000_000_001
            elif mode == 'stop': runtime.close()
            else:
                if mode == 'consumed': data = encoded([sample['response']])
                elif mode == 'replacement':
                    msg = copy.deepcopy(sample['message']); msg['msgId'] += 1
                    msg['actionsAvailableReq'] = {'actions': [{'actionType': 'ActionType_Pass'}]}
                    data = encoded([wrap(msg)])
                elif mode == 'partial': data = b'{"synthetic_incomplete":'
                elif mode == 'reset': data = encoded(bootstrap(sample))
                elif mode == 'gap':
                    data = encoded([wrap({'type': 'GREMessageType_GameStateMessage', 'systemSeatIds': [1],
                        'gameStateMessage': {'type': 'GameStateType_Diff', 'gameStateId': 99, 'prevGameStateId': 98}})])
                else: data = encoded([{'payload': {'type':
                    'ClientMessageType_UndoReq' if mode == 'undo' else 'ClientMessageType_CancelActionReq'}}])
                with path.open('wb' if mode == 'reset' else 'ab') as out: out.write(data)
                frame = next(gen)
            with self.subTest(mode=mode):
                self.denied(runtime.current_frame()['research_decision'])
                if mode == 'consumed':
                    with path.open('ab') as out: out.write(encoded([wrap(sample['message'])]))
                    self.denied(next(gen)['research_decision'])

    def test_raw_or_lease_change_during_lookup_discards_computed_swamp_result(self):
        for mode in ('raw', 'lease'):
            runtime, _, _, clock, frame, _ = self.stream()
            original = PreparedRulesIndex.lookup
            def changing(instance, *args, **kwargs):
                value = original(instance, *args, **kwargs)
                if mode == 'raw': runtime._reducer.accepted_digest = bytes(32)
                else: clock.now += 5_000_000_001
                return value
            with patch.object(PreparedRulesIndex, 'lookup', changing):
                self.denied(runtime.current_frame()['research_decision'])

    def test_new_frozen_calculation_performs_no_resource_io(self):
        reference = prepared()
        with (patch('mtgaplayer.rules_index.sqlite3.connect', side_effect=AssertionError('IO')),
              patch('mtgaplayer.rules_index._file_sha256', side_effect=AssertionError('IO'))):
            self.assertEqual(self.frozen(reference=reference)['status'], 'research_preference')

    def test_derived_options_cannot_disagree_with_the_same_callback_state(self):
        # Synthetic corruption of an internal derived report, not evidence of
        # a reachable Consumer defect or an MP91 game failure.
        for mode in ('card', 'phase', 'during_lookup'):
            runtime, _, _, _, _, _ = self.stream(card_id=96828 if mode == 'card' else 106531,
                phase='Phase_Main2' if mode == 'phase' else None)
            options = runtime.consumer.current_decision_options()
            play = next(o for o in options['options'] if o['observation']['engine_action_type'] == 'ActionType_Play')
            source = next(o for o in options['visible_state']['visible_objects']
                if o['instance_id'] == play['observation']['visible_object_id'])
            if mode == 'card': source['card_id'] = 106531
            elif mode == 'phase': options['visible_state']['game']['turn']['phase'] = 'Phase_Main1'
            lookup = PreparedRulesIndex.lookup
            calls = 0
            def changed(instance, *args, **kwargs):
                nonlocal calls
                result = lookup(instance, *args, **kwargs); calls += 1
                if mode == 'during_lookup' and calls == 2:
                    source['card_id'] = 96828
                return result
            with (self.subTest(mode=mode), patch.object(runtime.consumer, 'current_decision_options', return_value=options),
                  patch.object(PreparedRulesIndex, 'lookup', changed)):
                report = land.assess_current_land_development(runtime.consumer, runtime._reducer,
                    runtime._message, prepared(), policy_version=land.SWAMP_POLICY,
                    completed_stamp=runtime._completed_stamp)
                self.denied(report)


if __name__ == '__main__':
    unittest.main()
