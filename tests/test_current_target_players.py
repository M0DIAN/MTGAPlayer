"""MP84 real field projections over explicitly synthetic authentication/state.

The version header is the reviewed literal, not authentication of private bytes
or an installed binary. Only the thirteen committed request projections provide
positive target shapes; every mutation below is a synthetic counterexample.
"""
import copy
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from mtgaplayer import current_target_request as target, semantic_targets
from mtgaplayer.decision_consumer import EXECUTION
from mtgaplayer.shadow_history import _Evaluation
from mtgaplayer.target_build import TargetBuildObserver, current_build
from test_current_target_request import rows_for as old_rows_for, wrap
from test_raw_log import state as raw_state


FIXTURE = Path(__file__).parent / 'fixtures/current_target_players_real.json'
HEADER = b'Version: 2026.64.0.14517 / 2026.64.0.14517.1329972 / \n'


def rows_for(sample):
    """Synthetic bootstrap, including omitted empty public Battlefield zone."""
    rows = old_rows_for(sample)
    gs = raw_state(rows[2])
    gs['players'] = copy.deepcopy(sample['players'])
    if not any(z['type'] == 'ZoneType_Battlefield' for z in gs['zones']):
        gs['zones'].append({'zoneId': 2900, 'type': 'ZoneType_Battlefield',
            'visibility': 'Visibility_Public', 'objectInstanceIds': []})
    return rows


def bind_build(reducer, header=HEADER):
    observer = TargetBuildObserver()
    observer.begin({'reset': True, 'generation': reducer.generation})
    observer.write(0, header)
    observer.end({'identity_prefix_sha256': hashlib.sha256(header).hexdigest(),
        'source_changed_during_poll': False})
    observer.bind(reducer)
    return observer


class CurrentTargetPlayerTests(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads(FIXTURE.read_text(encoding='utf8'))
        self.samples = self.fixture['cases']
        self.sample = self.samples[0]

    def ready(self, sample=None, build=True):
        sample = copy.deepcopy(self.sample if sample is None else sample)
        e = _Evaluation()
        for row in rows_for(sample):
            e.apply(row)
        if build:
            bind_build(e.reducer)
        return e, sample['message']

    def report(self, e, message, limit=64):
        return e.consumer.current_decision_options(limit=limit,
            current_target_context=(e.reducer, message))['current_target_evidence']

    def denied(self, report):
        self.assertEqual(report['status'], 'insufficient_evidence')
        self.assertIsNone(report['current_request_binding'])
        self.assertIsNone(report['source_snapshot_ref'])
        self.assertEqual(report['local_proposals'], [])

    def safe(self, report):
        for key in EXECUTION:
            self.assertIs(report[key], False, key)
        self.assertFalse(report['complete_target_legality_verified'])
        self.assertFalse(report['historical_response_used'])
        self.assertIsNone(report.get('complete_legal_actions'))
        self.assertIn('complete_target_combination_unknown', report['unknown'])

    def incomplete(self, report, unresolved):
        self.assertEqual(report['status'], 'observed')
        self.assertEqual(report['unresolved_memberships'], unresolved)
        self.assertFalse(report['complete_current_select_domain_verified'])
        self.assertEqual(report['local_proposals'], [])
        self.assertIsNone(report['candidate_total_for_reviewed_constraints'])
        self.safe(report)

    def test_thirteen_real_projections_have_twenty_four_player_memberships(self):
        self.assertEqual(hashlib.sha256(FIXTURE.read_bytes().replace(b'\r\n', b'\n')).hexdigest(),
            '04c8d04c64530ef4220bb2cee60f0d64446a41602bbed1d7608b11ba2a0b574c')
        self.assertEqual(self.fixture['origin'], 'retained_scrubbed_real')
        self.assertFalse(self.fixture['raw_equivalent'])
        self.assertEqual(len(self.samples), 13)
        players = domains = proposals = selected_only = visible = 0
        for sample in self.samples:
            with self.subTest(case=sample['case']):
                e, message = self.ready(sample)
                report = self.report(e, message)
                self.assertEqual(report['status'], 'observed')
                self.assertEqual(report['schema_version'], target.ROLE_VERSION)
                self.assertEqual(report['profile'], target.ROLE_PROFILE)
                self.assertEqual(report['version_mapping_evidence'], current_build(e.reducer))
                self.assertEqual(report['verified_player_memberships'], sample['expected_player_memberships'])
                self.assertEqual(report['complete_current_select_domain_verified'], sample['expected_complete_domain'])
                self.assertEqual(report['unresolved_memberships'], 0)
                raw = message['selectTargetsReq']['targets'][0]['targets']
                members = report['target_referents']
                self.assertEqual(len(members), len(raw))
                self.assertEqual([m['list_position'] for m in members], list(range(len(raw))))
                self.assertEqual([m['legal_action'] for m in members], [m['legalAction'] for m in raw])
                for original, member in zip(raw, members):
                    self.assertNotIn('highlight', member)
                    self.assertNotIn('object_ref', member)
                    if original['targetInstanceId'] in (1, 2):
                        self.assertEqual(member['target_referent_kind'], 'verified_player')
                        self.assertEqual(member['namespace'], 'version_verified_player_instance')
                        self.assertEqual(member['target_instance_ref'], original['targetInstanceId'])
                        self.assertEqual(member['player_seat'], original['targetInstanceId'])
                        for field in ('object_type', 'zone', 'public_object_ref'):
                            self.assertIsNone(member[field])
                    else:
                        self.assertEqual(member['target_referent_kind'], 'verified_public_object')
                        self.assertEqual(member['namespace'], 'public_game_object')
                        self.assertEqual(member['public_object_ref'], original['targetInstanceId'])
                        self.assertIsNone(member['player_seat'])
                for option in report['local_proposals']:
                    self.assertEqual(option['kind'], 'reviewed_role_target_set')
                    self.assertFalse(option['research_eligible'])
                    self.assertFalse(option['execution_ready'])
                    self.assertEqual(option['request_binding'], report['current_request_binding'])
                    self.assertEqual(option['source_snapshot_ref'], report['source_snapshot_ref'])
                    proposal = option['proposal']
                    self.assertEqual(proposal['request_identity'], report['current_request_binding'])
                    self.assertEqual(proposal['source_snapshot_ref'], report['source_snapshot_ref'])
                    final = proposal['proposed_current_target_referent_set']
                    self.assertNotIn('object_refs', final)
                    self.assertEqual(semantic_targets.check_referent_final_set(report['target_constraints'], final)[0],
                        'verified_known_constraints')
                    self.assertEqual(len(final['target_referents']), 1)
                if sample['expected_complete_domain']:
                    self.assertEqual(report['returned_proposals'], len(raw))
                    self.assertIsNone(report['current_selected_literal'])
                else:
                    selected_only += 1
                    self.assertEqual(report['current_selected_literal'], members)
                    self.assertEqual(report['current_offered_members'], [])
                    self.assertEqual(report['returned_proposals'], 0)
                    self.assertIsNone(report['candidate_total_for_reviewed_constraints'])
                self.safe(report)
                players += report['verified_player_memberships']
                visible += report['verified_public_object_memberships']
                domains += report['complete_current_select_domain_verified']
                proposals += report['returned_proposals']
        self.assertEqual((players, visible, domains, proposals, selected_only), (24, 2, 11, 24, 2))

    def test_no_build_and_mismatched_build_do_not_infer_player_roles(self):
        for header in (None, HEADER.replace(b'1329972', b'1329973')):
            for sample in self.samples:
                with self.subTest(case=sample['case'], wrong_build=header is not None):
                    e, message = self.ready(sample, build=False)
                    if header is not None:
                        bind_build(e.reducer, header)
                    self.assertIsNone(current_build(e.reducer))
                    self.denied(self.report(e, message))

    def test_default_options_policy_and_detached_sidecar_do_not_change(self):
        for sample in self.samples:
            e, message = self.ready(sample)
            options = e.consumer.current_decision_options()
            policy = e.consumer.shadow_decision()
            enriched = e.consumer.current_decision_options(current_target_context=(e.reducer, message))
            report = enriched.pop('current_target_evidence')
            self.assertEqual(enriched, options)
            self.assertEqual(e.consumer.current_decision_options(), options)
            self.assertEqual(e.consumer.shadow_decision(), policy)
            self.assertNotEqual(policy['status'], 'research_preference')
            report['target_referents'][0]['player_seat'] = 999
            self.assertNotEqual(self.report(e, message)['target_referents'][0]['player_seat'], 999)

    def test_synthetic_unknown_members_are_retained_without_domain_or_proposal(self):
        sample = copy.deepcopy(self.sample)
        slot = sample['message']['selectTargetsReq']['targets'][0]
        slot['targets'][1]['targetInstanceId'] = 919191
        e, message = self.ready(sample)
        report = self.report(e, message)
        self.incomplete(report, 1)
        self.assertEqual(report['verified_player_memberships'], 1)
        self.assertEqual(report['verified_public_object_memberships'], 1)
        self.assertEqual(len(report['target_referents']), 3)
        unknown = report['target_referents'][1]
        self.assertEqual(unknown['namespace'], 'unresolved_request_member')
        self.assertEqual(unknown['target_instance_ref'], 2)
        self.assertNotIn('919191', json.dumps(report))

    def test_synthetic_player_card_token_ability_and_hidden_collisions_stay_unknown(self):
        for kind, visibility in (('GameObjectType_Card', 'Visibility_Public'),
                                 ('GameObjectType_Token', 'Visibility_Public'),
                                 ('GameObjectType_Ability', 'Visibility_Public'),
                                 ('GameObjectType_Card', 'Visibility_Private')):
            with self.subTest(kind=kind, visibility=visibility):
                e, message = self.ready()
                e.reducer.objects[1] = {'instanceId': 1, 'grpId': 987654321,
                    'type': kind, 'zoneId': 123456, 'ownerSeatId': 2, 'controllerSeatId': 2,
                    'visibility': visibility, 'viewers': []}
                report = self.report(e, message)
                self.incomplete(report, 1)
                member = report['target_referents'][0]
                self.assertEqual(member['reason'], 'player_entity_collision')
                self.assertEqual(member['target_referent_kind'], 'unresolved')
                self.assertNotIn('987654321', json.dumps(report))

    def test_synthetic_zone_membership_collision_does_not_need_object_payload(self):
        for zone_type, visibility in (('ZoneType_Battlefield', 'Visibility_Public'),
                                      ('ZoneType_Library', 'Visibility_Private')):
            with self.subTest(zone_type=zone_type):
                e, message = self.ready()
                e.reducer.zones[123456] = {'zoneId': 123456, 'type': zone_type,
                    'visibility': visibility, 'ownerSeatId': 2, 'objectInstanceIds': [2]}
                report = self.report(e, message)
                self.incomplete(report, 1)
                self.assertEqual(report['target_referents'][1]['reason'], 'player_entity_collision')

    def test_synthetic_distinct_group_zone_and_ability_namespaces_are_not_entity_joins(self):
        e, message = self.ready()
        source = e.reducer.objects[100]
        source['uniqueAbilities'] = [{'id': 1, 'grpId': 2}]
        e.reducer.zones[1] = {'zoneId': 1, 'type': 'ZoneType_Library',
            'visibility': 'Visibility_Private', 'ownerSeatId': 2, 'objectInstanceIds': []}
        report = self.report(e, message)
        self.assertEqual(report['verified_player_memberships'], 2)
        self.assertEqual(report['unresolved_memberships'], 0)

    def test_synthetic_malformed_player_lists_never_create_player_domains(self):
        for mode in ('bool_key', 'bool_seat', 'wrong_seat', 'duplicate_seat', 'missing_player',
                     'extra_player', 'unknown_field', 'status_bool', 'life_bool', 'timer_bool',
                     'controller_float', 'mana_dict'):
            with self.subTest(mode=mode):
                e, message = self.ready()
                players = e.reducer.players
                if mode == 'bool_key':
                    players = {True: copy.deepcopy(players[1]), 2: copy.deepcopy(players[2])}
                elif mode == 'bool_seat': players[1]['systemSeatNumber'] = True
                elif mode == 'wrong_seat': players[1]['systemSeatNumber'] = 2
                elif mode == 'duplicate_seat': players[2]['systemSeatNumber'] = 1
                elif mode == 'missing_player': players.pop(2)
                elif mode == 'extra_player': players[3] = {'systemSeatNumber': 3}
                elif mode == 'unknown_field': players[1]['instanceId'] = 1
                elif mode == 'status_bool': players[1]['status'] = True
                elif mode == 'life_bool': players[1]['lifeTotal'] = True
                elif mode == 'timer_bool': players[1]['timerIds'] = [True]
                elif mode == 'controller_float': players[1]['controllerSeatId'] = 1.0
                elif mode == 'mana_dict': players[1]['manaPool'] = {}
                e.reducer.players = players
                report = self.report(e, message)
                self.incomplete(report, 2)
                self.assertEqual(report['verified_player_memberships'], 0)
                self.assertEqual(report['verified_public_object_memberships'], 1)

    def test_synthetic_duplicate_and_bool_player_rows_fail_at_raw_acceptance(self):
        for players in ([{'systemSeatNumber': 1}, {'systemSeatNumber': 1}],
                        [{'systemSeatNumber': True}, {'systemSeatNumber': 2}]):
            with self.subTest(players=players):
                sample = copy.deepcopy(self.sample)
                sample['players'] = players
                e, message = self.ready(sample)
                self.denied(self.report(e, message))

    def test_synthetic_wrong_source_slot_count_seat_types_and_duplicate_targets(self):
        modes = ('source_player_id', 'source_card', 'source_token', 'source_group', 'source_owner',
                 'source_hidden', 'source_zone', 'target_bool', 'target_float', 'target_duplicate',
                 'slot_bool', 'slot_duplicate', 'targeting_group', 'wrong_targeting_player',
                 'minimum_bool', 'maximum_float', 'minimum_zero', 'maximum_two', 'missing_minimum',
                 'missing_maximum', 'missing_prompt', 'unknown_field')
        for mode in modes:
            with self.subTest(mode=mode):
                sample = copy.deepcopy(self.sample)
                body = sample['message']['selectTargetsReq']; slot = body['targets'][0]
                source = sample['objects'][0]
                if mode == 'source_player_id':
                    source['instanceId'] = body['sourceId'] = 1
                    sample['zones'][0]['objectInstanceIds'] = [1]
                elif mode == 'source_card': source['type'] = 'GameObjectType_Card'
                elif mode == 'source_token': source['type'] = 'GameObjectType_Token'
                elif mode == 'source_group': source['grpId'] += 1
                elif mode == 'source_owner': source['ownerSeatId'] = 2
                elif mode == 'source_hidden': source['visibility'] = 'Visibility_Private'; source['viewers'] = []
                elif mode == 'source_zone': sample['zones'][0]['type'] = 'ZoneType_Exile'
                elif mode == 'target_bool': slot['targets'][0]['targetInstanceId'] = True
                elif mode == 'target_float': slot['targets'][0]['targetInstanceId'] = 1.0
                elif mode == 'target_duplicate': slot['targets'][1]['targetInstanceId'] = 1
                elif mode == 'slot_bool': slot['targetIdx'] = True
                elif mode == 'slot_duplicate': body['targets'] *= 2
                elif mode == 'targeting_group': slot['targetingAbilityGrpId'] += 1
                elif mode == 'wrong_targeting_player': slot['targetingPlayer'] = 2
                elif mode == 'minimum_bool': slot['minTargets'] = True
                elif mode == 'maximum_float': slot['maxTargets'] = 1.0
                elif mode == 'minimum_zero': slot['minTargets'] = 0
                elif mode == 'maximum_two': slot['maxTargets'] = 2
                elif mode == 'missing_minimum': slot.pop('minTargets')
                elif mode == 'missing_maximum': slot.pop('maxTargets')
                elif mode == 'missing_prompt': sample['message'].pop('prompt')
                else: slot['unknown'] = True
                e, message = self.ready(sample)
                self.denied(self.report(e, message))

    def test_synthetic_public_target_cannot_be_ability_hidden_or_wrong_zone(self):
        for mode in ('ability', 'hidden', 'zone', 'duplicate_zone', 'missing'):
            with self.subTest(mode=mode):
                e, message = self.ready()
                member = e.reducer.objects[101]
                if mode == 'ability': member['type'] = 'GameObjectType_Ability'
                elif mode == 'hidden': member['visibility'] = 'Visibility_Private'; member['viewers'] = []
                elif mode == 'zone': e.reducer.zones[member['zoneId']]['type'] = 'ZoneType_Exile'
                elif mode == 'duplicate_zone':
                    e.reducer.zones[9876] = {'zoneId': 9876, 'type': 'ZoneType_Battlefield',
                        'visibility': 'Visibility_Public', 'objectInstanceIds': [101]}
                else: e.reducer.objects.pop(101)
                report = self.report(e, message)
                # Visible projection changes are a whole-result contradiction;
                # same visible shape with a bad raw type is an unresolved role.
                if report['status'] == 'observed': self.incomplete(report, 1)
                else: self.denied(report)

    def test_synthetic_role_and_namespace_mutations_fail_local_membership_validation(self):
        e, message = self.ready()
        report = self.report(e, message); constraints = report['target_constraints']
        base = report['local_proposals'][0]['proposal']['proposed_current_target_referent_set']
        for field, value in (('target_referent_kind', 'verified_public_object'),
                             ('namespace', 'public_game_object'), ('player_seat', 2),
                             ('player_seat', True), ('target_instance_ref', 2),
                             ('target_instance_ref', True), ('object_type', 'GameObjectType_Card'),
                             ('zone', 'ZoneType_Battlefield'), ('public_object_ref', 1),
                             ('list_position', 1), ('list_position', False),
                             ('legal_action', semantic_targets.UNSELECT)):
            with self.subTest(field=field, value=value):
                proposed = copy.deepcopy(base); proposed['target_referents'][0][field] = value
                self.assertNotEqual(semantic_targets.check_referent_final_set(constraints, proposed)[0],
                    'verified_known_constraints')
        for field, value in (('source_object_ref', 1), ('source_object_ref', True),
                             ('target_idx', 2), ('target_idx', True), ('target_referents', []),
                             ('target_referents', base['target_referents'] * 2)):
            with self.subTest(proposal_field=field):
                proposed = copy.deepcopy(base); proposed[field] = value
                self.assertNotEqual(semantic_targets.check_referent_final_set(constraints, proposed)[0],
                    'verified_known_constraints')

    def test_synthetic_mixed_select_and_unselect_cannot_be_complete(self):
        sample = copy.deepcopy(self.sample)
        sample['message']['selectTargetsReq']['targets'][0]['targets'][0]['legalAction'] = semantic_targets.UNSELECT
        e, message = self.ready(sample); report = self.report(e, message)
        self.incomplete(report, 0)
        self.assertIsNone(report['current_selected_literal'])

    def test_truncated_domain_does_not_return_partial_complete_proposals(self):
        e, message = self.ready(); report = self.report(e, message, limit=1)
        self.assertTrue(report['truncated'])
        self.assertEqual(report['candidate_total_for_reviewed_constraints'], 3)
        self.assertEqual(report['returned_proposals'], 0)
        self.assertEqual(report['local_proposals'], [])
        self.safe(report)

    def test_synthetic_raw_request_mutations_and_wrong_binding_do_not_pass_cache(self):
        e, message = self.ready(); self.assertEqual(self.report(e, message)['status'], 'observed')
        for field, value in (('msgId', 501), ('gameStateId', 10.0), ('systemSeatIds', [2]),
                             ('allowCancel', 'AllowCancel_Abort')):
            with self.subTest(field=field):
                changed = copy.deepcopy(message); changed[field] = value
                self.denied(self.report(e, changed))
        for field, value in (('match', 'wrong-match'), ('game', 2), ('seat', 2)):
            with self.subTest(binding=field):
                prior = getattr(e.reducer, field); setattr(e.reducer, field, value)
                self.denied(self.report(e, message)); setattr(e.reducer, field, prior)
        self.assertEqual(self.report(e, message)['status'], 'observed')

    def test_synthetic_consumption_replacement_and_retransmission_do_not_restore_old_request(self):
        e, message = self.ready(); prior = self.report(e, message)['source_snapshot_ref']
        e.apply({'payload': {'type': 'ClientMessageType_SelectTargetsResp', 'respId': 500,
            'gameStateId': 10, 'selectTargetsResp': {'target': {'targetIdx': 1,
                'targets': [copy.deepcopy(message['selectTargetsReq']['targets'][0]['targets'][0])]}}}})
        self.denied(self.report(e, message))
        e.apply(wrap(copy.deepcopy(message))); self.denied(self.report(e, message))
        new = copy.deepcopy(message); new['msgId'] += 1; e.apply(wrap(new))
        self.denied(self.report(e, message))
        current = self.report(e, new)
        self.assertEqual(current['status'], 'observed')
        self.assertNotEqual(current['source_snapshot_ref'], prior)
        self.assertEqual(current['current_request_binding']['request_id'], new['msgId'])

    def test_synthetic_future_response_does_not_mutate_frozen_current_roles(self):
        e, message = self.ready()
        frozen = self.report(e, message)
        before = copy.deepcopy(frozen)
        self.assertFalse(frozen['historical_response_used'])
        e.apply({'payload': {'type': 'ClientMessageType_SelectTargetsResp', 'respId': 500,
            'gameStateId': 10, 'selectTargetsResp': {'target': {'targetIdx': 1,
                'targets': [copy.deepcopy(message['selectTargetsReq']['targets'][0]['targets'][1])]}}}})
        self.denied(self.report(e, message))
        self.assertEqual(frozen, before)
        self.assertEqual(frozen['returned_proposals'], 3)
        self.assertEqual(frozen['verified_player_memberships'], 2)

    def test_synthetic_partial_full_reset_gap_cancel_undo_stop_and_expiry(self):
        for mode in ('partial', 'full', 'reset', 'gap', 'cancel', 'undo', 'stop', 'expiry'):
            with self.subTest(mode=mode):
                e, message = self.ready()
                if mode == 'partial': e.publish(partial=True)
                elif mode == 'full': e.apply(rows_for(self.sample)[2])
                elif mode == 'reset': e.reducer.reset(2)
                elif mode == 'gap': e.apply(wrap({'type': 'GREMessageType_GameStateMessage', 'systemSeatIds': [1],
                    'gameStateMessage': {'type': 'GameStateType_Diff', 'gameStateId': 11, 'prevGameStateId': 9}}))
                elif mode in ('cancel', 'undo'):
                    e.apply({'payload': {'type': 'ClientMessageType_CancelActionReq' if mode == 'cancel' else 'ClientMessageType_UndoReq'}})
                elif mode == 'stop':
                    for event in e.publisher.stop('sample_limit'):
                        self.assertTrue(e.consumer.accept_event(event))
                else: e.ordinal += 10**15
                self.denied(self.report(e, message))
                if mode in ('cancel', 'undo'):
                    e.apply(wrap(copy.deepcopy(message))); self.denied(self.report(e, message))

    def test_synthetic_typed_predecessor_controls_new_request_after_diff(self):
        for predecessor in (10, 10.0, True):
            with self.subTest(predecessor=predecessor):
                e, message = self.ready()
                e.apply(wrap({'type': 'GREMessageType_GameStateMessage', 'systemSeatIds': [1],
                    'gameStateMessage': {'type': 'GameStateType_Diff', 'gameStateId': 11,
                        'prevGameStateId': predecessor}}))
                new = copy.deepcopy(message); new.update(msgId=501, gameStateId=11)
                e.apply(wrap(new))
                if type(predecessor) is int:
                    self.assertEqual(self.report(e, new)['status'], 'observed')
                else: self.denied(self.report(e, new))

    def test_synthetic_inflight_lease_digest_players_collisions_and_consumption_discard_result(self):
        from mtgaplayer import choice_candidates
        original = choice_candidates._bounded_target_sets
        for mode in ('expiry', 'digest', 'players', 'collision', 'consume', 'build'):
            with self.subTest(mode=mode):
                e, message = self.ready()
                def late(*args, **kwargs):
                    result = original(*args, **kwargs)
                    if mode == 'expiry': e.ordinal += 10**15
                    elif mode == 'digest': e.reducer.accepted_digest = b'changed-current-digest'
                    elif mode == 'players': e.reducer.players[1]['systemSeatNumber'] = 2
                    elif mode == 'collision': e.reducer.objects[1] = {'instanceId': 1}
                    elif mode == 'build': e.reducer._target_build_context = None
                    else: e.reducer.apply({'payload': {'type': 'ClientMessageType_SubmitTargetsReq',
                        'respId': 500, 'gameStateId': 10}})
                    return result
                with patch.object(choice_candidates, '_bounded_target_sets', side_effect=late):
                    self.denied(self.report(e, message))


if __name__ == '__main__':
    unittest.main()
