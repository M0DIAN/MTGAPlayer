"""MP89 retained real target/effect fields; synthetic transport and negatives.

The public projections and prepared reference are owner-reviewed real fields.
Synthetic authentication, Full/bootstrap and clocks do not authenticate private
archive or installed resource bytes. Every mutation is a counterexample, never
a synthetic MTGA positive or a policy training label.
"""
import copy
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch

from mtgaplayer import target_effect as effect
from mtgaplayer.decision_consumer import EXECUTION
from mtgaplayer.rules_index import (
    PreparedRulesIndex, RulesIndexError, prepare_mtga_target_effect_reference,
)
from mtgaplayer.shadow_runtime import LocalShadowRuntime, safe_summary
from mtgaplayer.target_build import current_build, current_resource
from test_combat_frontier import baseline
from test_raw_log import state as raw_state


FIXTURES = Path(__file__).parent / 'fixtures'
CURRENT = FIXTURES / 'target_effect_real.json'
STATIC = FIXTURES / 'target_effect_reference_real.json'


def encoded(rows):
    return ''.join(json.dumps(row, separators=(',', ':')) + '\n' for row in rows).encode()


def wrap(message):
    return {'greToClientEvent': {'greToClientMessages': [copy.deepcopy(message)]}}


def bootstrap(sample):
    """Invented transport over retained public/own-visible current state."""
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


class TargetEffectTests(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads(CURRENT.read_text(encoding='utf8'))
        self.samples = self.fixture['cases']
        self.sample = next(case for case in self.samples if case['case'] == 'target-4')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.serial = 0

    def prepared(self, mutate=None):
        """Exact detached factory result, not fabricated card or ability data."""
        reference = json.loads(STATIC.read_text(encoding='utf8'))
        if mutate is not None:
            mutate(reference)
        return PreparedRulesIndex(reference['metadata'],
            {int(key): value for key, value in reference['matches'].items()})

    def prelude(self):
        value = self.fixture['resource_prelude']
        return (value if isinstance(value, str) else '\n'.join(value) + '\n').encode()

    def stream(self, sample=None, prepared=None, prelude=None, enabled=True, **kwargs):
        sample = copy.deepcopy(self.sample if sample is None else sample)
        self.serial += 1
        path = Path(self.temp.name) / f'projected-{self.serial}.jsonl'
        path.write_bytes((self.prelude() if prelude is None else prelude) + encoded(bootstrap(sample)))
        clock = Clock()
        policy = {'research_policy': effect.POLICY,
            'prepared_rules': self.prepared() if prepared is None else prepared} if enabled else {}
        runtime = LocalShadowRuntime(path, interval=0, samples=None, clock_ns=clock,
            observation_mode='controlled_stream_replay', **policy, **kwargs)
        gen = runtime.frames()
        self.addCleanup(runtime.close); self.addCleanup(gen.close)
        history = next(gen)
        frame = self.append(gen, path, [wrap(sample['message'])])
        return runtime, gen, path, clock, frame, history

    def append(self, gen, path, rows):
        with path.open('ab') as out:
            out.write(encoded(rows))
        return next(gen)

    def report(self, runtime, prepared=None, message=None):
        return effect.assess_current_target_effect(runtime.consumer, runtime._reducer,
            runtime._message if message is None else message,
            self.prepared() if prepared is None else prepared,
            completed_stamp=runtime._completed_stamp)

    def safe(self, report):
        self.assertTrue(report['read_only'])
        for key in EXECUTION:
            self.assertIs(report[key], False, key)
        for key in ('strategic_optimality_verified', 'server_acceptance_verified'):
            self.assertIs(report[key], False, key)

    def denied(self, report):
        self.safe(report)
        self.assertNotEqual(report['status'], 'research_preference')
        self.assertIsNone(report['preferred_option_key'])

    def denied_frame(self, frame):
        report = frame.get('research_decision')
        if report is None:
            self.assertNotEqual(frame['time_scope'], 'current_at_completed_poll')
        else:
            self.denied(report)

    def source(self, sample):
        return next(obj for obj in sample['initial']['objects']
            if obj['instanceId'] == sample['message']['selectTargetsReq']['sourceId'])

    def slot(self, sample):
        return sample['message']['selectTargetsReq']['targets'][0]

    def consume(self, sample):
        # Invented negative transport over current endpoints; not historical
        # choice evidence and never used to establish a positive preference.
        message = sample['message']
        return {'payload': {'type': 'ClientMessageType_SelectTargetsResp',
            'gameStateId': message['gameStateId'], 'respId': message['msgId'],
            'selectTargetsResp': {'target': {'targetIdx': self.slot(sample)['targetIdx'],
                'targets': [{'targetInstanceId': 2, 'legalAction': 'SelectAction_Select',
                    'highlight': 'HighlightType_Hot'}]}}}}

    def test_all_real_current_domains_have_independent_effect_results_without_default_policy_changes(self):
        self.assertEqual(self.fixture['origin'], 'owner-authenticated real first-current visible-field projections')
        self.assertFalse(self.fixture['raw_equivalent'])
        self.assertEqual(len(self.samples), 14)
        counts = {'research_preference': 0, 'abstain': 0, 'unsupported': 0}
        domains = 0
        for sample in self.samples:
            with self.subTest(case=sample['case']):
                runtime, _, _, _, frame, history = self.stream(sample)
                self.denied_frame(history)
                self.assertEqual(frame['time_scope'], 'current_at_completed_poll')
                result = frame['research_decision']; self.safe(result)
                counts[result['status']] += 1
                old_options = runtime.consumer.current_decision_options()
                old_policy = runtime.consumer.shadow_decision()
                self.assertEqual(result, self.report(runtime))
                self.assertEqual(runtime.consumer.current_decision_options(), old_options)
                self.assertEqual(runtime.consumer.shadow_decision(), old_policy)
                self.assertEqual(frame['shadow_decision'], old_policy)
                report = frame['local_evidence']['current_target_evidence']
                if sample['case'] == 'target-1':
                    # This Card request already has a complete old final-set
                    # candidate. The sidecar must defer, preserving that API.
                    self.assertEqual(report['schema_version'], 'mtgaplayer.current-target-request.v1')
                    self.assertEqual(report['reason'], 'existing_profile_already_supported')
                    self.assertEqual(len(old_options['options']), 1)
                    self.assertEqual(old_options['options'][0]['kind'], 'final_target_set')
                    self.assertEqual(old_options['options'][0]['evidence_level'], 'known_constraints_verified')
                    self.assertEqual(old_options['coverage']['engine_offered_count'], 1)
                    self.assertFalse(old_options['coverage']['truncated'])
                    domains += 1
                else:
                    domains += report['complete_current_select_domain_verified']
                if result['status'] == 'research_preference':
                    options = report['local_proposals']
                    chosen = [row for row in options if row['option_key'] == result['preferred_option_key']]
                    self.assertEqual(len(chosen), 1)
                    self.assertEqual(result['request_binding'], frame['request_binding'])
                    self.assertEqual(result['source_snapshot_ref'], frame['source_snapshot_ref'])
                    referents = chosen[0]['proposal']['proposed_current_target_referent_set']['target_referents']
                    self.assertEqual(len(referents), 1)
                    self.assertEqual(referents[0]['player_seat'], 2)
        self.assertEqual(domains, 12)
        self.assertEqual(counts, {'research_preference': 9, 'abstain': 4, 'unsupported': 1})

    def test_frozen_preference_precedes_response_and_synthetic_consumption_cannot_be_reversed(self):
        runtime, gen, path, _, frame, _ = self.stream()
        result = frame['research_decision']; self.safe(result)
        self.assertEqual(result['status'], 'research_preference')
        self.assertEqual(result['policy_version'], effect.POLICY)
        frozen = copy.deepcopy(result)
        self.assertEqual(self.report(runtime), frozen)
        self.denied_frame(self.append(gen, path, [self.consume(self.sample)]))
        self.denied(self.report(runtime))
        self.denied_frame(self.append(gen, path, [wrap(self.sample['message'])]))
        self.denied(self.report(runtime))
        self.assertEqual(frame['research_decision'], frozen)

    def test_mixed_domains_keep_all_candidates_and_do_not_rank_uncompared_public_objects(self):
        for name in ('target-2', 'target-3'):
            with self.subTest(case=name):
                sample = next(row for row in self.samples if row['case'] == name)
                runtime, _, _, _, frame, _ = self.stream(sample)
                self.denied(frame['research_decision'])
                domain = frame['local_evidence']['current_target_evidence']
                self.assertTrue(domain['complete_current_select_domain_verified'])
                self.assertEqual(len(domain['local_proposals']), 3)
                self.assertEqual(len(domain['current_offered_members']), 3)
                self.assertEqual(self.report(runtime), frame['research_decision'])

    def test_synthetic_candidate_order_is_not_a_tiebreak_and_unknown_allegiance_abstains(self):
        # Metamorphic ordering check over a real domain, not a new MTGA sample.
        sample = copy.deepcopy(self.sample)
        self.slot(sample)['targets'].reverse()
        _, _, _, _, frame, _ = self.stream(sample)
        result = frame['research_decision']
        self.assertEqual(result['status'], 'research_preference')
        chosen = next(row for row in frame['local_evidence']['current_target_evidence']['local_proposals']
            if row['option_key'] == result['preferred_option_key'])
        member = chosen['proposal']['proposed_current_target_referent_set']['target_referents'][0]
        self.assertEqual(member['player_seat'], 2)
        for mode in ('same_team', 'unknown_team', 'bool_team'):
            with self.subTest(mode=mode):
                sample = copy.deepcopy(self.sample)
                player = sample['initial']['players'][1]
                if mode == 'same_team':
                    player['teamId'] = 1
                elif mode == 'unknown_team':
                    player.pop('teamId')
                else:
                    player['teamId'] = True
                *_, frame, _ = self.stream(sample)
                self.denied_frame(frame)

    def test_synthetic_source_namespace_and_specific_ability_contradictions_never_use_card_text_alone(self):
        mutations = {
            'card_instead_of_ability': lambda s: self.source(s).update(type='GameObjectType_Card'),
            'token': lambda s: self.source(s).update(type='GameObjectType_Token'),
            'hidden': lambda s: self.source(s).update(visibility='Visibility_Private', viewers=[]),
            'wrong_catalog': lambda s: self.source(s).update(objectSourceGrpId=90673),
            'same_card_different_ability': lambda s: self.source(s).update(grpId=172054),
            'request_ability': lambda s: s['message']['selectTargetsReq'].update(abilityGrpId=172054),
            'slot_ability': lambda s: self.slot(s).update(targetingAbilityGrpId=172054),
            'foreign_controller': lambda s: self.source(s).update(controllerSeatId=2),
            'source_missing': lambda s: s['initial']['objects'].remove(self.source(s)),
            'source_unknown': lambda s: s['message']['selectTargetsReq'].update(sourceId=999999),
            'source_duplicate': lambda s: s['initial']['objects'].append(copy.deepcopy(self.source(s))),
            'unknown_mode': lambda s: self.source(s).update(mode=1),
            'unknown_X': lambda s: self.source(s).update(xValue=2),
        }
        for name, mutate in mutations.items():
            with self.subTest(mutation=name):
                sample = copy.deepcopy(self.sample); mutate(sample)
                *_, frame, _ = self.stream(sample)
                self.denied_frame(frame)

    def test_synthetic_target_roles_domain_and_quantity_contradictions_abstain(self):
        mutations = {
            'unknown_target': lambda s: self.slot(s)['targets'][1].update(targetInstanceId=999999),
            'missing_target': lambda s: self.slot(s)['targets'].pop(),
            'duplicate_target_tie': lambda s: self.slot(s)['targets'].__setitem__(1,
                copy.deepcopy(self.slot(s)['targets'][0])),
            'minimum_unknown': lambda s: self.slot(s).pop('minTargets'),
            'many_targets': lambda s: self.slot(s).update(maxTargets=2),
            'wrong_slot': lambda s: self.slot(s).update(targetIdx=99),
            'wrong_targeting_player': lambda s: self.slot(s).update(targetingPlayer=2),
            'unknown_request_mode': lambda s: s['message']['selectTargetsReq'].update(mode=1),
            'unknown_request_X': lambda s: s['message']['selectTargetsReq'].update(xValue=2),
            'unknown_slot_constraint': lambda s: self.slot(s).update(extraCost=True),
        }
        for name, mutate in mutations.items():
            with self.subTest(mutation=name):
                sample = copy.deepcopy(self.sample); mutate(sample)
                *_, frame, _ = self.stream(sample)
                self.denied_frame(frame)

    def test_synthetic_player_object_collision_hidden_players_and_unreliable_life_abstain(self):
        for mode in ('object_collision', 'zone_collision', 'life_bool', 'life_missing',
                     'duplicate_player', 'foreign_seat'):
            with self.subTest(mode=mode):
                sample = copy.deepcopy(self.sample)
                if mode == 'object_collision':
                    sample['initial']['objects'].append({'instanceId': 2, 'grpId': 96854,
                        'type': 'GameObjectType_Card', 'zoneId': 9999,
                        'visibility': 'Visibility_Private', 'viewers': [],
                        'ownerSeatId': 2, 'controllerSeatId': 2})
                elif mode == 'zone_collision':
                    sample['initial']['zones'].append({'zoneId': 9999, 'type': 'ZoneType_Library',
                        'visibility': 'Visibility_Private', 'ownerSeatId': 2, 'objectInstanceIds': [2]})
                elif mode == 'life_bool':
                    sample['initial']['players'][1]['lifeTotal'] = True
                elif mode == 'life_missing':
                    sample['initial']['players'][1].pop('lifeTotal')
                elif mode == 'duplicate_player':
                    sample['initial']['players'].append(copy.deepcopy(sample['initial']['players'][1]))
                else:
                    sample['message']['systemSeatIds'] = [2]
                *_, frame, _ = self.stream(sample)
                self.denied_frame(frame)

    def test_synthetic_wrong_current_binding_raw_digest_and_scope_revoke(self):
        for field, value in (('msgId', 999999), ('gameStateId', 999999), ('systemSeatIds', [2])):
            with self.subTest(field=field):
                runtime, *_ = self.stream()
                message = copy.deepcopy(runtime._message); message[field] = value
                self.denied(self.report(runtime, message=message))
        for attribute, value in (('match', 'foreign-match'), ('game', 99), ('seat', 2),
                                 ('accepted_digest', bytes(32))):
            with self.subTest(attribute=attribute):
                runtime, *_ = self.stream()
                setattr(runtime._reducer, attribute, value)
                self.denied(self.report(runtime))

    def test_resource_provenance_requires_entire_ordered_exact_build_selection_not_header_only(self):
        lines = self.fixture['resource_prelude']
        pointer = next(row for row in lines if 'GET manifest pointer' in row)
        count = next(row for row in lines if 'Found 1 manifest metadata' in row)
        automatic = next(row for row in lines if 'Automatic|' in row)
        general = next(row for row in lines if 'General|Manifest_Audio_' in row)
        done = next(row for row in lines if 'Manifest download complete' in row)
        mutations = {
            'header_only': lines[:1],
            'missing_pointer': [row for row in lines if 'GET manifest pointer' not in row],
            'wrong_build': [row.replace('1329972', '1329973') for row in lines],
            'wrong_manifest': [row.replace('c98372b34219b5c4aa478e8bf296f5ee', '0' * 32) for row in lines],
            'missing_completion': [row for row in lines if row != done],
            'duplicate_pointer': lines[:2] + [pointer] + lines[2:],
            'out_of_order_selection': lines[:1] + [automatic, count, pointer, done],
            'multiple_metadata': [row.replace('Found 1 ', 'Found 2 ') for row in lines],
            'duplicate_known_general': lines[:3] + [general] + lines[3:],
            'unknown_general': [row.replace('47ac91270740b32d9181e19a86d537cd', '0' * 32) for row in lines],
            'misordered_known_general': [row for row in lines if row != general and row != done] + [general, done],
        }
        for name, changed in mutations.items():
            with self.subTest(mutation=name):
                runtime, _, _, _, frame, _ = self.stream(prelude=('\n'.join(changed) + '\n').encode())
                self.assertIsNone(current_resource(runtime._reducer))
                if name != 'wrong_build':
                    self.assertIsNotNone(current_build(runtime._reducer))
                self.denied(frame['research_decision'])
                self.denied(self.report(runtime))
        for line in (automatic.replace('c98372b34219b5c4aa478e8bf296f5ee', '0' * 32),
                     automatic.replace('Automatic|', 'Manual|'),
                     automatic.replace('Automatic|', 'UnknownKind|'), general):
            with self.subTest(late_selection=line.split(': ', 1)[1].split('|')[0]):
                runtime, gen, path, _, frame, _ = self.stream()
                self.assertIsNotNone(current_resource(runtime._reducer))
                self.assertEqual(frame['research_decision']['status'], 'research_preference')
                with path.open('ab') as out:
                    out.write((line + '\n').encode())
                self.denied_frame(next(gen))
                self.assertIsNone(current_resource(runtime._reducer))
                self.denied(self.report(runtime))

    def test_static_effect_identity_modes_and_specific_text_are_rechecked_not_trusted_by_card_id(self):
        def card(value):
            return value['matches']['96854']['card']
        mutations = {
            'missing_card': lambda v: v['matches'].pop('96854'),
            'ambiguous_card': lambda v: v['matches'].update({'96854': {'status': 'ambiguous', 'card': None}}),
            'different_card': lambda v: card(v).update(card_id=90673),
            'different_ability': lambda v: card(v)['ability_definitions'][0]['row'].update(Id=172054),
            'different_ability_text': lambda v: card(v)['ability_definitions'][0]['generic_text'].update(
                Loc='When CARDNAME leaves the battlefield, it deals 3 damage to any target.'),
            'specific_text_mismatch': lambda v: card(v)['specific_ability_texts'][0]['text'].update(
                Loc='Target player gains 2 life.'),
            'base_damage_mismatch': lambda v: card(v)['base_effect_instruction'].update(base_damage=3),
            'unknown_modal_child': lambda v: card(v)['ability_definitions'][0]['row'].update(ModalChildIds='1553'),
            'unparsed_definition': lambda v: card(v)['ability_definitions'][0]['row'].update(FullyParsed=0),
            'changed_profile': lambda v: card(v)['profile'].update(TextChangeData='unknown'),
            'unverified_source_hash': lambda v: v['metadata'].update(source_sha256='0' * 64),
            'wrong_version': lambda v: v['metadata'].update(source_version='Data=2026.64.0.281;GRP=281.0'),
            'supplied_version': lambda v: v['metadata'].update(source_version_is_user_supplied=True),
            'wrong_format': lambda v: v['metadata'].update(source_format='scryfall_card_json_array'),
        }
        for name, mutate in mutations.items():
            with self.subTest(mutation=name):
                runtime, *_ = self.stream()
                self.denied(self.report(runtime, self.prepared(mutate)))

    def test_reference_projection_preserves_native_specific_definitions_and_no_effective_damage_claim(self):
        value = json.loads(STATIC.read_text(encoding='utf8'))
        self.assertEqual(value['origin'], 'actual_production_factory_official_version_bound_subset')
        self.assertIn('does not authenticate original database bytes', value['source_authentication'])
        prepared = self.prepared()
        metadata, found = prepared.lookup([90673, 96854])
        self.assertEqual(metadata, value['metadata'])
        self.assertEqual(metadata['source_format'], 'mtga_official_sqlite_target_effect_metadata')
        self.assertFalse(metadata['source_version_is_user_supplied'])
        self.assertEqual(set(found), {90673, 96854})
        self.assertEqual(found[90673], value['matches']['90673'])
        self.assertEqual(found[96854], value['matches']['96854'])
        for card_id, ability_id, trigger in ((90673, 1553, 'enters'), (96854, 191026, 'leaves_battlefield')):
            card = found[card_id]['card']
            instruction = card['base_effect_instruction']
            self.assertEqual(instruction['ability_id'], ability_id)
            self.assertEqual(instruction['base_damage'], 2)
            self.assertEqual(instruction['trigger'], trigger)
            self.assertEqual(card['card_id'], card_id)
            self.assertFalse(card['effective_in_game'])
            self.assertFalse(card['complete_legality_verified'])
            self.assertNotIn('oracle_id', card)
            self.assertNotIn('layout', card)
        found[96854]['card']['base_effect_instruction']['base_damage'] = 99
        self.assertEqual(prepared.lookup([96854])[1][96854]['card']['base_effect_instruction']['base_damage'], 2)

    def test_candidate_domain_completeness_and_same_request_option_binding_cannot_be_bypassed(self):
        mutations = {
            'truncated': lambda r: r['coverage'].update(truncated=True),
            'omitted': lambda r: r['coverage'].update(omitted_constructed_options=1),
            'wrong_binding': lambda r: r['request_binding'].update(request_id=999999),
            'wrong_ref': lambda r: r['source_snapshot_ref'].update(sequence=999999),
            'unreviewed_domain': lambda r: r['current_target_evidence'].update(
                complete_current_select_domain_verified=False),
            'dropped_competitor': lambda r: r['current_target_evidence']['local_proposals'].pop(),
            'duplicate_option': lambda r: r['current_target_evidence']['local_proposals'].append(
                copy.deepcopy(r['current_target_evidence']['local_proposals'][0])),
        }
        for name, mutate in mutations.items():
            with self.subTest(mutation=name):
                runtime, *_ = self.stream()
                options = runtime.consumer.current_decision_options(
                    current_target_context=(runtime._reducer, runtime._message))
                mutate(options)
                with patch.object(runtime.consumer, 'current_decision_options', return_value=options):
                    self.denied(self.report(runtime))

    def test_synthetic_cancel_undo_replacement_and_retransmission_cannot_revive_old_preference(self):
        for mode in ('cancel', 'undo', 'replacement'):
            with self.subTest(mode=mode):
                runtime, gen, path, _, frame, _ = self.stream()
                self.assertEqual(frame['research_decision']['status'], 'research_preference')
                if mode == 'replacement':
                    message = copy.deepcopy(self.sample['message']); message['msgId'] += 100
                    fresh = self.append(gen, path, [wrap(message)])
                    self.assertEqual(fresh['request_binding']['request_id'], message['msgId'])
                    self.assertNotEqual(fresh['request_binding'], frame['request_binding'])
                    after_retransmit = self.append(gen, path, [wrap(self.sample['message'])])
                    self.assertEqual(after_retransmit['request_binding'], fresh['request_binding'])
                    self.assertNotEqual(after_retransmit['source_snapshot_ref'], frame['source_snapshot_ref'])
                    self.denied(self.report(runtime, message=self.sample['message']))
                else:
                    self.denied_frame(self.append(gen, path, [{'payload': {'type':
                        'ClientMessageType_CancelActionReq' if mode == 'cancel' else 'ClientMessageType_UndoReq'}}]))
                    self.denied_frame(self.append(gen, path, [wrap(self.sample['message'])]))
                    self.denied(self.report(runtime))

    def test_synthetic_partial_full_gap_or_file_replacement_revokes_entire_current_result(self):
        for mode in ('partial', 'full', 'gap', 'replacement'):
            with self.subTest(mode=mode):
                runtime, gen, path, _, frame, _ = self.stream()
                self.assertEqual(frame['research_decision']['status'], 'research_preference')
                if mode == 'partial':
                    with path.open('ab') as out:
                        out.write(b'{"synthetic_partial":')
                    self.denied_frame(next(gen))
                    with path.open('ab') as out:
                        out.write(b'1}\n')
                    self.denied_frame(next(gen))
                elif mode == 'full':
                    full = bootstrap(self.sample)[2]
                    raw_state(full)['gameStateId'] += 1
                    self.denied_frame(self.append(gen, path, [full]))
                elif mode == 'gap':
                    self.denied_frame(self.append(gen, path, [wrap({
                        'type': 'GREMessageType_GameStateMessage', 'systemSeatIds': [1],
                        'gameStateMessage': {'type': 'GameStateType_Diff',
                            'gameStateId': 998, 'prevGameStateId': 997}})]))
                else:
                    replacement = path.with_suffix('.replacement')
                    replacement.write_bytes(self.prelude() + encoded(bootstrap(self.sample) + [wrap(self.sample['message'])]))
                    replacement.replace(path)
                    self.denied_frame(next(gen))
                self.denied_frame(self.append(gen, path, [wrap(self.sample['message'])]))
                self.denied(self.report(runtime))

    def test_lease_stop_foreign_thread_and_missing_completed_poll_fail_closed(self):
        for mode in ('lease', 'stop', 'foreign_thread', 'missing_poll'):
            with self.subTest(mode=mode):
                runtime, _, _, clock, frame, _ = self.stream(max_observation_age_ns=500_000_000,
                    max_event_silence_ns=500_000_000)
                self.assertEqual(frame['research_decision']['status'], 'research_preference')
                if mode == 'lease':
                    clock.now += 500_000_001
                    self.denied(self.report(runtime)); self.denied_frame(runtime.current_frame())
                elif mode == 'stop':
                    runtime.close()
                    self.denied(self.report(runtime)); self.denied_frame(runtime.current_frame())
                elif mode == 'foreign_thread':
                    results = []
                    worker = threading.Thread(target=lambda: results.extend((self.report(runtime), runtime.current_frame())))
                    worker.start(); worker.join(3)
                    self.assertFalse(worker.is_alive())
                    self.denied(results[0]); self.denied_frame(results[1])
                else:
                    self.denied(effect.assess_current_target_effect(runtime.consumer, runtime._reducer,
                        runtime._message, self.prepared()))

    def test_state_or_lease_change_during_reference_lookup_discards_finished_calculation(self):
        for mode in ('lease', 'digest', 'source', 'life', 'resource', 'stop'):
            with self.subTest(mode=mode):
                runtime, _, _, clock, frame, _ = self.stream(max_observation_age_ns=500_000_000,
                    max_event_silence_ns=500_000_000)
                self.assertEqual(frame['research_decision']['status'], 'research_preference')
                prepared = self.prepared(); original = PreparedRulesIndex.lookup
                def changed(instance, *args, **kwargs):
                    result = original(instance, *args, **kwargs)
                    if mode == 'lease':
                        clock.now += 500_000_001
                    elif mode == 'digest':
                        runtime._reducer.accepted_digest = bytes(32)
                    elif mode == 'source':
                        runtime._reducer.objects[100]['objectSourceGrpId'] = 90673
                    elif mode == 'life':
                        runtime._reducer.players[2]['lifeTotal'] -= 1
                    elif mode == 'resource':
                        runtime._reducer._target_resource_context = None
                    else:
                        runtime.close()
                    return result
                with patch.object(PreparedRulesIndex, 'lookup', changed):
                    self.denied(self.report(runtime, prepared))
                self.denied_frame(runtime.current_frame())

    def test_offline_effect_factory_rejects_corrupt_native_definitions_after_hash_gate(self):
        reference = json.loads(STATIC.read_text(encoding='utf8'))
        original = reference['matches']['96854']['card']
        version = {'Data': '2026.64.0.280', 'GRP': '280.1327372'}
        expected_hash = reference['metadata']['source_sha256']
        integer_fields = {'GrpId', 'TitleId', 'TypeTextId', 'SubtypeTextId', 'LinkedFaceType',
            'IsToken', 'IsPrimaryCard', 'IsDigitalOnly', 'IsRebalanced', 'RebalancedCardGrpId',
            'DefunctRebalancedCardGrpId', 'Id', 'BaseId', 'BaseIdNumeral', 'FakeBaseIdNumeral',
            'TextId', 'Category', 'SubCategory', 'AbilityWord', 'NumericAid', 'RequiresConfirmation',
            'PaymentType', 'FullyParsed', 'IsIntrinsicAbility'}
        for mode in ('bad_schema', 'duplicate_ability', 'wrong_generic_text', 'wrong_specific_text',
                     'unverified_mode', 'wrong_version', 'duplicate_version', 'duplicate_localization'):
            with self.subTest(mode=mode):
                path = Path(self.temp.name) / f'synthetic-invalid-{mode}.sqlite'
                card = copy.deepcopy(original)
                if mode == 'unverified_mode':
                    card['ability_definitions'][0]['row']['ModalChildIds'] = '1553'
                if mode == 'wrong_generic_text':
                    card['ability_definitions'][0]['generic_text']['Loc'] = 'Deal X damage to any target.'
                if mode == 'wrong_specific_text':
                    card['specific_ability_texts'][0]['text']['Loc'] = 'Target player gains 2 life.'
                with closing(sqlite3.connect(path)) as db, db:
                    for table, row in (('Cards', card['profile']), ('Abilities', card['ability_definitions'][0]['row'])):
                        definitions = [name + (' INTEGER' if name in integer_fields else ' TEXT') for name in row]
                        if mode == 'bad_schema' and table == 'Abilities':
                            definitions[list(row).index('TextId')] = 'TextId TEXT'
                        db.execute('CREATE TABLE ' + table + ' (' + ','.join(definitions) + ')')
                    db.execute('INSERT INTO Cards VALUES (' + ','.join('?' for _ in card['profile']) + ')',
                        list(card['profile'].values()))
                    for definition in card['ability_definitions']:
                        row = definition['row']
                        db.execute('INSERT INTO Abilities VALUES (' + ','.join('?' for _ in row) + ')', list(row.values()))
                    if mode == 'duplicate_ability':
                        row = card['ability_definitions'][0]['row']
                        db.execute('INSERT INTO Abilities VALUES (' + ','.join('?' for _ in row) + ')', list(row.values()))
                    db.execute('CREATE TABLE Versions (Type TEXT, Version TEXT)')
                    db.executemany('INSERT INTO Versions VALUES (?,?)',
                        {**version, 'Data': '0'} .items() if mode == 'wrong_version' else version.items())
                    if mode == 'duplicate_version':
                        db.execute('INSERT INTO Versions VALUES (?,?)', ('Data', version['Data']))
                    db.execute('CREATE TABLE Localizations_enUS (LocId INTEGER, Formatted INTEGER, Loc TEXT)')
                    texts = [d['generic_text'] for d in card['ability_definitions']] + [
                        item['text'] for item in card['specific_ability_texts']]
                    for text in texts:
                        db.execute('INSERT INTO Localizations_enUS VALUES (?,?,?)',
                            (text['LocId'], text['Formatted'], text['Loc']))
                    if mode == 'duplicate_localization':
                        text = texts[0]
                        db.execute('INSERT INTO Localizations_enUS VALUES (?,?,?)',
                            (text['LocId'], text['Formatted'], text['Loc']))
                # Hash substitution is ONLY a negative control allowing deeper
                # schema/identity checks. No invented database is admitted as
                # an official positive or current game effect.
                with patch('mtgaplayer.rules_index._file_sha256', return_value=expected_hash):
                    with self.assertRaises(RulesIndexError):
                        prepare_mtga_target_effect_reference(path, [96854],
                            expected_sha256=expected_hash, expected_source_version=version)
        for arguments in ({'expected_sha256': '0' * 64, 'expected_source_version': version},
                          {'expected_sha256': expected_hash, 'expected_source_version': {**version, 'GRP': '0'}}):
            with self.assertRaises(RulesIndexError):
                prepare_mtga_target_effect_reference(Path(self.temp.name) / 'absent.sqlite', [96854], **arguments)

    def test_default_runtime_is_optin_and_prepared_policy_does_no_file_or_sqlite_reads(self):
        runtime, _, _, _, frame, _ = self.stream(enabled=False)
        self.assertNotIn('research_decision', frame)
        self.assertNotIn('research_decision', safe_summary(frame))
        runtime, _, _, _, frame, _ = self.stream()
        prepared = self.prepared()
        with (patch('mtgaplayer.rules_index.sqlite3.connect', side_effect=AssertionError('unexpected SQLite')),
              patch('mtgaplayer.rules_index._file_sha256', side_effect=AssertionError('unexpected source read'))):
            report = self.report(runtime, prepared)
        self.assertEqual(report['status'], 'research_preference')
        report['private_path'] = 'PATH_SENTINEL'
        report['effect_source']['private_account'] = 'ACCOUNT_SENTINEL'
        frame['research_decision'] = report
        public = json.dumps(safe_summary(frame))
        self.assertNotIn('PATH_SENTINEL', public)
        self.assertNotIn('ACCOUNT_SENTINEL', public)
        self.assertNotIn('fixture-local', public)


if __name__ == '__main__':
    unittest.main()
