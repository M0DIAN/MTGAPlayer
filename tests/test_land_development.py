"""MP87 retained real current fields; synthetic transport and counterexamples.

The public snapshots preserve two actual current requests and exact static
reference projections.  Synthetic authentication/Full/bootstrap and clocks do
not reauthenticate private archive or installed SQLite bytes.  Every changed
request, source, reference or lifecycle below is a negative control.
"""
import copy
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch

from mtgaplayer import land_development as land
from mtgaplayer.decision_consumer import EXECUTION
from mtgaplayer.rules_index import PreparedRulesIndex, RulesIndexError, prepare_mtga_land_reference
from mtgaplayer.shadow_runtime import LocalShadowRuntime, safe_summary
from test_combat_frontier import baseline
from test_raw_log import state as raw_state


FIXTURES = Path(__file__).parent / 'fixtures'
CURRENT = FIXTURES / 'land_development_real.json'
STATIC = FIXTURES / 'land_static_reference_real.json'


def encoded(rows):
    return ''.join(json.dumps(row, separators=(',', ':')) + '\n' for row in rows).encode()


def wrap(message):
    return {'greToClientEvent': {'greToClientMessages': [copy.deepcopy(message)]}}


def bootstrap(sample):
    """Invented authentication/Full transport over actual visible endpoints."""
    rows = baseline()
    gs = raw_state(rows[2]); initial = sample['initial']
    gs.update(gameStateId=initial['state_id'],
        gameObjects=copy.deepcopy(initial['objects']), zones=copy.deepcopy(initial['zones']),
        players=copy.deepcopy(initial['players']), turnInfo=copy.deepcopy(initial['turn_info']))
    return rows


class Clock:
    def __init__(self):
        self.now = 1_000_000_000

    def __call__(self):
        return self.now


class LandDevelopmentTests(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads(CURRENT.read_text(encoding='utf8'))
        self.samples = self.fixture['cases']
        self.sample = self.samples[1]
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.serial = 0

    def prepared(self, mutate=None):
        """Exact production-factory projection, not a fabricated static card."""
        reference = json.loads(STATIC.read_text(encoding='utf8'))
        if mutate is not None:
            mutate(reference)
        return PreparedRulesIndex(reference['metadata'],
            {int(key): value for key, value in reference['matches'].items()})

    def stream(self, sample=None, prepared=None, **kwargs):
        sample = copy.deepcopy(self.sample if sample is None else sample)
        self.serial += 1
        path = Path(self.temp.name) / f'projected-{self.serial}.jsonl'
        path.write_bytes(encoded(bootstrap(sample)))
        clock = Clock()
        runtime = LocalShadowRuntime(path, interval=0, samples=None, clock_ns=clock,
            observation_mode='controlled_stream_replay', research_policy=land.POLICY,
            prepared_rules=self.prepared() if prepared is None else prepared, **kwargs)
        gen = runtime.frames()
        self.addCleanup(runtime.close)
        self.addCleanup(gen.close)
        history = next(gen)
        with path.open('ab') as out:
            out.write(encoded([wrap(sample['message'])]))
        frame = next(gen)
        return runtime, gen, path, clock, frame, history

    def append(self, gen, path, rows):
        with path.open('ab') as out:
            out.write(encoded(rows))
        return next(gen)

    def report(self, runtime, prepared=None):
        return land.assess_current_land_development(runtime.consumer, runtime._reducer,
            runtime._message, self.prepared() if prepared is None else prepared,
            completed_stamp=runtime._completed_stamp)

    def safe(self, report):
        self.assertTrue(report['read_only'])
        for key in EXECUTION:
            self.assertIs(report[key], False, key)
        for key in ('strategic_optimality_verified', 'payment_verified'):
            self.assertIs(report[key], False, key)

    def denied(self, report):
        self.safe(report)
        self.assertNotEqual(report['status'], 'research_preference')
        self.assertIsNone(report['preferred_option_key'])

    def denied_frame(self, frame):
        report = frame.get('research_decision')
        if report is None:
            self.assertNotEqual(frame['time_scope'], 'current_at_completed_poll')
            self.assertIsNone(frame['shadow_preference'])
        else:
            self.denied(report)

    def play(self, sample):
        return next(row for row in sample['message']['actionsAvailableReq']['actions']
            if row['actionType'] == 'ActionType_Play')

    def source(self, sample):
        return next(obj for obj in sample['initial']['objects']
            if obj['instanceId'] == self.play(sample)['instanceId'])

    def test_retained_unique_land_prefers_while_default_complex_policy_stays_abstained(self):
        self.assertEqual(hashlib.sha256(CURRENT.read_bytes().replace(b'\r\n', b'\n')).hexdigest(),
            '918c78dc531dc44329d1726eb0bdcca76877f698e37ffaadf858cba78dc99dd0')
        self.assertEqual(self.fixture['origin'], 'retained_scrubbed_real')
        self.assertFalse(self.fixture['raw_equivalent'])
        runtime, gen, path, clock, frame, history = self.stream()
        self.denied_frame(history)
        self.assertEqual(frame['time_scope'], 'current_at_completed_poll')
        options = copy.deepcopy(frame['current_options'])
        policy = copy.deepcopy(frame['shadow_decision'])
        result = frame['research_decision']; self.safe(result)
        self.assertEqual(result['status'], 'research_preference')
        self.assertEqual(result['policy_version'], land.POLICY)
        self.assertEqual(result['preference_basis'], 'verified_land_development_heuristic')
        self.assertEqual(result['request_binding'], options['request_binding'])
        self.assertEqual(result['source_snapshot_ref'], options['source_snapshot_ref'])
        rows = [row for row in options['options'] if row['kind'] == 'engine_action']
        offered = next(row for row in rows if row['list_position'] == 6)
        self.assertEqual(result['preferred_option_key'], offered['option_key'])
        self.assertEqual(result['coverage']['active_action_rows'], 16)
        self.assertEqual(result['coverage']['play_offers'], 1)
        self.assertEqual(result['coverage']['verified_play_sources'], 1)
        self.assertEqual(result['coverage']['verified_static_land_candidates'], 1)
        self.assertEqual(result['coverage']['ordinary_profile_candidates'], 1)
        self.assertEqual(policy['status'], 'abstain')
        self.assertEqual(policy['reason'], self.sample['expected']['default_reason'])
        self.assertTrue(any(row['observation'].get('engine_action_type') == 'ActionType_Cast'
            for row in rows))
        self.assertEqual(runtime.consumer.current_decision_options(), options)
        self.assertEqual(runtime.consumer.shadow_decision(), policy)
        self.assertEqual(self.report(runtime), result)
        frozen = copy.deepcopy(result)
        self.assertEqual(self.report(runtime), result)
        frame_after_response = self.append(gen, path, [self.sample['response']])
        self.denied_frame(frame_after_response)
        self.denied(self.report(runtime))
        self.assertEqual(result, frozen)  # historical data grants no new currentness

    def test_retained_multiple_play_inventory_is_not_ranked_by_basic_type_or_historical_choice(self):
        runtime, gen, path, _, frame, _ = self.stream(self.samples[0])
        result = frame['research_decision']; self.denied(result)
        self.assertEqual(result['status'], 'abstain')
        self.assertEqual(result['coverage']['active_action_rows'], 8)
        self.assertEqual(result['coverage']['play_offers'], 3)
        before = copy.deepcopy(result)
        self.denied_frame(self.append(gen, path, [self.samples[0]['response']]))
        self.denied(self.report(runtime))
        self.assertEqual(before, result)

    def test_synthetic_source_role_zone_card_and_visibility_contradictions_abstain(self):
        mutations = {
            'token': lambda s: self.source(s).update(type='GameObjectType_Token'),
            'ability': lambda s: self.source(s).update(type='GameObjectType_Ability'),
            'foreign_owner': lambda s: self.source(s).update(ownerSeatId=2),
            'foreign_controller': lambda s: self.source(s).update(controllerSeatId=2),
            'hidden': lambda s: self.source(s).update(visibility='Visibility_Hidden', viewers=[]),
            'wrong_zone': lambda s: self.source(s).update(zoneId=2001),
            'missing_zone': lambda s: self.source(s).update(zoneId=999999),
            'source_group_mismatch': lambda s: self.source(s).update(grpId=95062),
            'source_absent': lambda s: s['initial']['objects'].remove(self.source(s)),
            'unknown_card': lambda s: (self.source(s).update(grpId=999999),
                self.play(s).update(grpId=999999)),
            'source_id_mismatch': lambda s: self.play(s).update(instanceId=999999),
            'wrong_source_group': lambda s: self.play(s).update(grpId=95062),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                sample = copy.deepcopy(self.sample); mutate(sample)
                *_, frame, _ = self.stream(sample)
                self.denied_frame(frame)

    def test_synthetic_unreviewed_play_or_request_parameters_are_not_ignored(self):
        mutations = {
            'play_unknown': lambda s: self.play(s).update(unreviewedMode=1),
            'play_targets': lambda s: self.play(s).update(targets=[]),
            'play_mana': lambda s: self.play(s).update(manaCost=[]),
            'play_auto_tap': lambda s: self.play(s).update(autoTapSolution={'autoTapActions': []}),
            'play_missing_facet': lambda s: self.play(s).pop('facetId'),
            'play_bool_facet': lambda s: self.play(s).update(facetId=True),
            'play_unknown_group_type': lambda s: self.play(s).update(grpId='96839'),
            'play_unknown_stop_type': lambda s: self.play(s).update(shouldStop=1),
            'request_unknown': lambda s: s['message'].update(unreviewedField=1),
            'payload_unknown': lambda s: s['message']['actionsAvailableReq'].update(unreviewedField=1),
            'prompt_parameter': lambda s: s['message']['prompt'].update(parameters=[{'value': 1}]),
            'unknown_competitor_field': lambda s: s['message']['actionsAvailableReq']['actions'][0].update(unreviewedMode=1),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                sample = copy.deepcopy(self.sample); mutate(sample)
                *_, frame, _ = self.stream(sample)
                self.denied_frame(frame)

    def test_synthetic_phase_turn_priority_and_recipient_contradictions_abstain(self):
        mutations = []
        for key in ('activePlayer', 'priorityPlayer', 'decisionPlayer'):
            mutations.extend((f'{key}-{value}', lambda s, k=key, v=value:
                s['initial']['turn_info'].update({k: v})) for value in (2, True, None))
            mutations.append((f'{key}-missing', lambda s, k=key: s['initial']['turn_info'].pop(k)))
        mutations.extend((f'phase-{phase}', lambda s, p=phase:
            s['initial']['turn_info'].update(phase=p)) for phase in
            ('Phase_Main2', 'Phase_Combat', 'Phase_Beginning', None))
        mutations.extend((f'turn-{number}', lambda s, n=number:
            s['initial']['turn_info'].update(turnNumber=n)) for number in (None, True, 0, -1))
        mutations.extend([
            ('foreign_seat', lambda s: s['message'].update(systemSeatIds=[2])),
            ('wrong_state', lambda s: s['message'].update(gameStateId=99)),
            ('bool_request', lambda s: s['message'].update(msgId=True)),
            ('unknown_step', lambda s: s['initial']['turn_info'].update(step='Step_Upkeep'))])
        for label, mutate in mutations:
            with self.subTest(label=label):
                sample = copy.deepcopy(self.sample); mutate(sample)
                *_, frame, _ = self.stream(sample)
                self.denied_frame(frame)

    def test_native_static_projection_preserves_exact_identity_and_no_dynamic_authority(self):
        self.assertEqual(hashlib.sha256(STATIC.read_bytes().replace(b'\r\n', b'\n')).hexdigest(),
            'fc04dbe48ac90d1003d2c21205de6dec2c6d00d43337c0f3bfbbf19a57352ae3')
        value = json.loads(STATIC.read_text(encoding='utf8'))
        self.assertFalse(value['raw_equivalent'])
        self.assertEqual(value['metadata']['source_format'], 'mtga_official_sqlite_card_metadata')
        self.assertFalse(value['metadata']['source_version_is_user_supplied'])
        prepared = self.prepared()
        metadata, found = prepared.lookup([96839])
        self.assertEqual(metadata, value['metadata'])
        self.assertEqual(found[96839], value['matches']['96839'])
        card = found[96839]['card']
        self.assertEqual(card['card_id'], 96839)
        self.assertEqual(card['type_line'], 'Basic Land')
        self.assertIsNone(card['current_face'])
        self.assertFalse(card['effective_in_game'])
        self.assertFalse(card['rules_verified'])
        self.assertNotIn('oracle_id', card)
        self.assertNotIn('layout', card)
        found[96839]['card']['card_id'] = 999999
        self.assertEqual(prepared.lookup([96839])[1][96839]['card']['card_id'], 96839)

    def test_synthetic_static_identity_and_ordinary_profile_gaps_abstain(self):
        def card(value):
            return value['matches']['96839']['card']
        mutations = {
            'not_in_reference': lambda v: v['matches'].pop('96839'),
            'ambiguous_catalog_id': lambda v: v['matches'].update({'96839': {'status': 'ambiguous', 'card': None}}),
            'card_id_mismatch': lambda v: card(v).update(card_id=95062),
            'non_land': lambda v: card(v).update(type_line='Creature', card_types=[
                {'value': 2, 'loc_id': 12, 'label': 'Creature'}]),
            'type_label_conflict': lambda v: card(v)['card_types'][0].update(label='Creature'),
            'type_id_conflict': lambda v: card(v)['card_types'][0].update(value=2),
            'non_basic': lambda v: card(v).update(supertypes=[]),
            'reverse_link': lambda v: card(v).update(reverse_face_link_observed=True),
            'linked_face': lambda v: card(v)['profile'].update(LinkedFaceType=1),
            'linked_face_ids': lambda v: card(v)['profile'].update(LinkedFaceGrpIds='95062'),
            'linked_ability_card': lambda v: card(v)['profile'].update(LinkedAbilityTemplateCardGrpIds='95062'),
            'explicit_ability': lambda v: card(v)['profile'].update(AbilityIds='123:456'),
            'hidden_ability': lambda v: card(v)['profile'].update(HiddenAbilityIds='123:456'),
            'hybrid_frame': lambda v: card(v)['profile'].update(AdditionalFrameDetails='hybrid'),
            'extra_frame': lambda v: card(v)['profile'].update(ExtraFrameDetails='unreviewed'),
            'text_change': lambda v: card(v)['profile'].update(TextChangeData='unreviewed'),
            'mana_text': lambda v: card(v)['profile'].update(OldSchoolManaText='{U}'),
            'non_primary': lambda v: card(v)['profile'].update(IsPrimaryCard=0),
            'digital_only': lambda v: card(v)['profile'].update(IsDigitalOnly=1),
            'rebalanced': lambda v: card(v)['profile'].update(IsRebalanced=1),
            'token_profile': lambda v: card(v)['profile'].update(IsToken=1),
            'missing_profile_field': lambda v: card(v)['profile'].pop('LinkedFaceType'),
            'invalid_profile_field_type': lambda v: card(v)['profile'].update(IsToken=False),
            'schema': lambda v: v['metadata'].update(schema_version='mtgaplayer.static-rules-index.v1'),
            'source_format': lambda v: v['metadata'].update(source_format='scryfall_card_json_array'),
            'invalid_source_version': lambda v: v['metadata'].update(source_version='not-a-verified-version'),
            'invalid_source_hash': lambda v: v['metadata'].update(source_sha256='not-a-sha256'),
            'user_supplied_version': lambda v: v['metadata'].update(source_version_is_user_supplied=True),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                runtime, *_ = self.stream()
                self.denied(self.report(runtime, self.prepared(mutate)))

    def test_current_consumer_and_native_prepared_reference_are_required(self):
        runtime, *_ = self.stream()
        self.denied(self.report(runtime, False))
        self.denied(land.assess_current_land_development(runtime.consumer.current_view(),
            runtime._reducer, runtime._message, self.prepared(),
            completed_stamp=runtime._completed_stamp))
        self.denied(land.assess_current_land_development(runtime.consumer, runtime._reducer,
            runtime._message, self.prepared()))
        result = land.assess_current_land_development(runtime.consumer, runtime._reducer,
            runtime._message, self.prepared(), policy_version='unreviewed.v1',
            completed_stamp=runtime._completed_stamp)
        self.denied(result)
        self.assertEqual(result['status'], 'unsupported')

    def test_original_request_message_and_raw_digest_cannot_be_rebound_to_foreign_current(self):
        for field, value in (('msgId', 777), ('gameStateId', 777), ('systemSeatIds', [2])):
            with self.subTest(field=field):
                runtime, *_ = self.stream()
                message = copy.deepcopy(runtime._message)
                message[field] = value
                self.denied(land.assess_current_land_development(runtime.consumer,
                    runtime._reducer, message, self.prepared(), completed_stamp=runtime._completed_stamp))
        runtime, *_ = self.stream()
        runtime._reducer.accepted_digest = hashlib.sha256(
            runtime._reducer.accepted_digest + b'synthetic-unaccepted-change').digest()
        self.denied(self.report(runtime))
        for attribute, value in (('match', 'foreign-match'), ('game', 99), ('seat', 2)):
            with self.subTest(attribute=attribute):
                runtime, *_ = self.stream()
                setattr(runtime._reducer, attribute, value)
                self.denied(self.report(runtime))
        runtime, *_ = self.stream()
        runtime._message['actionsAvailableReq']['actions'][6]['shouldStop'] = False
        self.denied(self.report(runtime))

    def test_duplicate_visible_source_identity_or_explicit_nonempty_stack_abstains(self):
        runtime, *_ = self.stream()
        view = runtime.consumer.current_view()
        visible = view['decision_state']['visible_objects']
        visible.append(copy.deepcopy(next(obj for obj in visible if obj['instance_id'] == 315)))
        with patch.object(runtime.consumer, 'current_view', return_value=view):
            self.denied(self.report(runtime))
        sample = copy.deepcopy(self.sample)
        stacked = next(obj for obj in sample['initial']['objects'] if obj['instanceId'] == 300)
        stacked['zoneId'] = 2000
        stacked['visibility'] = 'Visibility_Public'
        next(zone for zone in sample['initial']['zones'] if zone['zoneId'] == 2000)[
            'objectInstanceIds'] = [300]
        next(zone for zone in sample['initial']['zones'] if zone['zoneId'] == 2002)[
            'objectInstanceIds'].remove(300)
        *_, frame, _ = self.stream(sample)
        self.denied_frame(frame)

    def test_option_inventory_binding_and_completeness_are_not_repaired_by_static_rules(self):
        mutations = {
            'truncated': lambda r: r['coverage'].update(truncated=True),
            'omitted': lambda r: r['coverage'].update(omitted_constructed_options=1),
            'wrong_binding': lambda r: r['request_binding'].update(request_id=999999),
            'wrong_ref': lambda r: r['source_snapshot_ref'].update(sequence=999999),
            'missing_play': lambda r: r['options'].__setitem__(slice(None), [
                row for row in r['options'] if not (row['kind'] == 'engine_action' and row['list_position'] == 6)]),
            'duplicate_play': lambda r: r['options'].append(copy.deepcopy(next(
                row for row in r['options'] if row['kind'] == 'engine_action' and row['list_position'] == 6))),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                runtime, *_ = self.stream()
                options = runtime.consumer.current_decision_options()
                mutate(options)
                with patch.object(runtime.consumer, 'current_decision_options', return_value=options):
                    self.denied(self.report(runtime))

    def test_consumption_retransmission_and_replacement_never_restore_prior_preference(self):
        for mode in ('consumed', 'replaced'):
            with self.subTest(mode=mode):
                runtime, gen, path, _, frame, _ = self.stream()
                self.assertEqual(frame['research_decision']['status'], 'research_preference')
                frozen = copy.deepcopy(frame['research_decision'])
                if mode == 'consumed':
                    self.denied_frame(self.append(gen, path, [self.sample['response']]))
                else:
                    replacement = copy.deepcopy(self.sample['message'])
                    replacement['msgId'] = 777
                    replacement['actionsAvailableReq'] = {'actions': [{'actionType': 'ActionType_Pass'}]}
                    self.denied_frame(self.append(gen, path, [wrap(replacement)]))
                self.denied_frame(self.append(gen, path, [wrap(self.sample['message'])]))
                self.denied(self.report(runtime))
                self.assertEqual(frozen, frame['research_decision'])

    def test_partial_completion_and_source_replacement_cannot_renew_old_request(self):
        for mode in ('partial', 'replacement', 'full', 'diff_gap'):
            with self.subTest(mode=mode):
                runtime, gen, path, _, frame, _ = self.stream()
                self.assertEqual(frame['research_decision']['status'], 'research_preference')
                if mode == 'partial':
                    with path.open('ab') as out:
                        out.write(b'{"synthetic_incomplete":')
                    self.denied_frame(next(gen))
                    with path.open('ab') as out:
                        out.write(b'1}\n')
                    self.denied_frame(next(gen))
                elif mode == 'replacement':
                    replacement = path.with_suffix('.replacement')
                    replacement.write_bytes(encoded(bootstrap(self.sample) + [wrap(self.sample['message'])]))
                    replacement.replace(path)
                    self.denied_frame(next(gen))
                elif mode == 'full':
                    new_full = bootstrap(self.sample)[2]
                    raw_state(new_full)['gameStateId'] += 1
                    self.denied_frame(self.append(gen, path, [new_full]))
                else:
                    bad_diff = {'type': 'GREMessageType_GameStateMessage', 'systemSeatIds': [1],
                        'gameStateMessage': {'type': 'GameStateType_Diff', 'gameStateId': 13,
                            'prevGameStateId': 12}}
                    self.denied_frame(self.append(gen, path, [wrap(bad_diff)]))
                self.denied_frame(self.append(gen, path, [wrap(self.sample['message'])]))
                self.denied(self.report(runtime))

    def test_lease_expiry_and_stop_discard_prior_results_without_policy_cache(self):
        for mode in ('lease', 'stop'):
            with self.subTest(mode=mode):
                runtime, _, _, clock, frame, _ = self.stream(max_observation_age_ns=500_000_000,
                    max_event_silence_ns=500_000_000)
                frozen = copy.deepcopy(frame['research_decision'])
                self.assertEqual(frozen['status'], 'research_preference')
                if mode == 'lease':
                    clock.now += 500_000_001
                else:
                    runtime.close()
                self.denied_frame(runtime.current_frame())
                self.denied(self.report(runtime))
                self.denied_frame(runtime.current_frame())
                self.assertEqual(frozen, frame['research_decision'])

    def test_lease_or_raw_mutation_during_prepared_lookup_revokes_finished_preference(self):
        for mode in ('lease', 'digest', 'source', 'stop'):
            with self.subTest(mode=mode):
                runtime, _, _, clock, frame, _ = self.stream(max_observation_age_ns=500_000_000,
                    max_event_silence_ns=500_000_000)
                self.assertEqual(frame['research_decision']['status'], 'research_preference')
                prepared = self.prepared()
                original = PreparedRulesIndex.lookup
                def changed(instance, *args, **kwargs):
                    result = original(instance, *args, **kwargs)
                    if mode == 'lease':
                        clock.now += 500_000_001
                    elif mode == 'digest':
                        runtime._reducer.accepted_digest = bytes(32)
                    elif mode == 'source':
                        runtime._reducer.objects[315]['grpId'] = 95062
                    else:
                        runtime.close()
                    return result
                with patch.object(PreparedRulesIndex, 'lookup', changed):
                    self.denied(self.report(runtime, prepared))
                self.denied_frame(runtime.current_frame())

    def test_owner_thread_enforcement_and_safe_summary_do_not_disclose_current_identity(self):
        runtime, _, _, _, frame, _ = self.stream()
        self.assertEqual(frame['research_decision']['status'], 'research_preference')
        output = []
        def foreign():
            output.extend((self.report(runtime), runtime.current_frame()))
        worker = threading.Thread(target=foreign)
        worker.start(); worker.join(3)
        self.assertFalse(worker.is_alive())
        self.denied(output[0])
        self.denied_frame(output[1])
        self.assertEqual(output[1]['reason'], 'owner_thread_required')
        frame['research_decision']['source_identity']['account'] = 'ACCOUNT_SENTINEL'
        frame['research_decision']['private_path'] = 'PATH_SENTINEL'
        summary = safe_summary(frame)
        text = json.dumps(summary)
        for value in ('ACCOUNT_SENTINEL', 'PATH_SENTINEL', 'fixture-match', 'fixture-local'):
            self.assertNotIn(value, text)
        self.assertFalse(summary['input_sent'])

    def test_default_runtime_does_not_enable_land_policy_and_prepared_calculation_does_no_io(self):
        path = Path(self.temp.name) / 'default-real-projection.jsonl'
        path.write_bytes(encoded(bootstrap(self.sample)))
        runtime = LocalShadowRuntime(path, interval=0, samples=None, clock_ns=Clock(),
            observation_mode='controlled_stream_replay')
        gen = runtime.frames(); self.addCleanup(runtime.close); self.addCleanup(gen.close)
        next(gen)
        frame = self.append(gen, path, [wrap(self.sample['message'])])
        self.assertNotIn('research_decision', frame)
        self.assertNotIn('research_decision', safe_summary(frame))
        self.assertEqual(frame['shadow_decision']['status'], 'abstain')
        runtime, *_ = self.stream()
        prepared = self.prepared()
        with (patch('mtgaplayer.rules_index.sqlite3.connect', side_effect=AssertionError('unexpected SQLite')),
              patch('mtgaplayer.rules_index._file_sha256', side_effect=AssertionError('unexpected source read'))):
            result = self.report(runtime, prepared)
        self.assertEqual(result['status'], 'research_preference')

    def test_offline_factory_rejects_synthetic_source_hash_version_schema_and_type_corruption(self):
        # This DB is an invented transport over the reviewed static projection.
        # It is never accepted as a positive official source or game sample.
        original = json.loads(STATIC.read_text(encoding='utf8'))['matches']['96839']['card']
        integer = {'GrpId', 'TypeTextId', 'SubtypeTextId', 'LinkedFaceType', 'IsToken',
            'IsPrimaryCard', 'IsDigitalOnly', 'IsRebalanced', 'RebalancedCardGrpId',
            'DefunctRebalancedCardGrpId'}
        versions = {'Data': '2026.64.0.280', 'GRP': '280.1327372'}
        for mode in ('wrong_hash', 'wrong_version', 'wrong_schema', 'wrong_flag_type',
                     'duplicate_version', 'duplicate_enum', 'duplicate_localization'):
            with self.subTest(mode=mode):
                path = Path(self.temp.name) / f'invented-invalid-{mode}.sqlite'
                profile = copy.deepcopy(original['profile'])
                if mode == 'wrong_flag_type':
                    profile['IsPrimaryCard'] = 'not-a-boolean'
                columns = ['GrpId', *profile]
                with closing(sqlite3.connect(path)) as db, db:
                    definitions = [name + (' INTEGER' if name in integer else ' TEXT') for name in columns]
                    if mode == 'wrong_schema':
                        definitions[columns.index('IsPrimaryCard')] = 'IsPrimaryCard TEXT'
                    db.execute('CREATE TABLE Cards (' + ','.join(definitions) + ')')
                    db.execute('INSERT INTO Cards VALUES (' + ','.join('?' for _ in columns) + ')',
                        [96839, *profile.values()])
                    db.execute('CREATE TABLE Versions (Type TEXT, Version TEXT)')
                    db.executemany('INSERT INTO Versions VALUES (?,?)', versions.items())
                    db.execute('CREATE TABLE Enums (Type TEXT, Value INTEGER, LocId INTEGER)')
                    db.execute('CREATE TABLE Localizations_enUS (LocId INTEGER, Formatted INTEGER, Loc TEXT)')
                    for kind, terms in (('CardType', original['card_types']),
                                        ('SuperType', original['supertypes']), ('SubType', original['subtypes'])):
                        for term in terms:
                            db.execute('INSERT INTO Enums VALUES (?,?,?)', (kind, term['value'], term['loc_id']))
                            db.execute('INSERT INTO Localizations_enUS VALUES (?,1,?)', (term['loc_id'], term['label']))
                    db.execute('INSERT INTO Localizations_enUS VALUES (?,1,?)',
                        (profile['TypeTextId'], original['type_line']))
                    if mode == 'duplicate_version':
                        db.execute('INSERT INTO Versions VALUES (?,?)', ('Data', versions['Data']))
                    if mode == 'duplicate_enum':
                        db.execute('INSERT INTO Enums VALUES (?,?,?)', ('CardType', 5, 11))
                    if mode == 'duplicate_localization':
                        db.execute('INSERT INTO Localizations_enUS VALUES (11,1,?)', ('Land',))
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                with self.assertRaises(RulesIndexError):
                    prepare_mtga_land_reference(path, [96839],
                        expected_sha256='0' * 64 if mode == 'wrong_hash' else digest,
                        expected_source_version={**versions, 'Data': '0'} if mode == 'wrong_version' else versions)


if __name__ == '__main__':
    unittest.main()
