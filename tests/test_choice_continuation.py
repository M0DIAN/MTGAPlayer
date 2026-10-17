"""Real portable states; every mutation, bootstrap and transport is synthetic.

No private original log, game binary, account, desktop or network is accessed.
Invented auth/Full and continuous GRE records exercise production plumbing only.
"""
import copy
import hashlib
import io
import json
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from mtgaplayer import choice_continuation as continuation
from mtgaplayer.choice_candidates import enumerate_known_candidates
from mtgaplayer.cli import replay
from mtgaplayer.decision_consumer import DecisionConsumer, EXECUTION, _state, consume_events
from mtgaplayer.decision_publisher import DecisionPublisher
from mtgaplayer.raw_log import RawReducer
import test_cast_activate_associations as public_bootstrap
from test_decision_publisher import ManualClock


FIXTURE = Path(__file__).parent / 'fixtures/current_choice_continuation_real_v13.json'


class ChoiceContinuationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads(FIXTURE.read_text(encoding='utf-8'))
        self.state = self.fixture['first_child']

    def absent(self, report):
        self.assertEqual(report['schema_version'], continuation.VERSION)
        self.assertEqual(report['status'], 'insufficient_evidence')
        for key in ('historical_selected_parent_observed', 'current_child_request_verified',
                    'continuation_relationship_consistent'):
            self.assertIs(report[key], False, key)
        self.denials(report)

    def denials(self, report):
        self.assertIs(report['read_only'], True)
        for key in (*continuation.DENIALS, *EXECUTION):
            self.assertIs(report[key], False, key)

    def positive(self, report):
        self.assertEqual(report['status'], 'continuation_relationship_consistent')
        for key in ('historical_selected_parent_observed', 'current_child_request_verified',
                    'continuation_relationship_consistent'):
            self.assertIs(report[key], True, key)
        self.assertEqual(report['request_local_membership_count_status'], 'verified_known_constraints')
        self.denials(report)

    def transport(self, history=False):
        """Synthetic session, clock and append events around a real public state."""
        clock = ManualClock()
        publisher = DecisionPublisher(clock_ns=clock, session_id='synthetic-mp62', state_version=13)
        state = copy.deepcopy(self.state)
        state['source'].update(mode='watch', phase='history' if history else 'append', stopped=False)
        document = {'decision_state': state,
                    'source': {'phase': state['source']['phase'], 'partial_record': False}}
        metadata = {'poll_started_ns': clock(), 'poll_completed_ns': clock(), 'poll_read_ns': 0,
                    'reducer_apply_ns': 0, 'decision_state_assembly_ns': 0,
                    'request_changed': True, 'new_final_request': True}
        events = publisher.observe(document, metadata)
        consumer = DecisionConsumer(10000, 500, clock)
        for event in events:
            self.assertTrue(consumer.accept_event(event))
        return publisher, consumer, clock, document, metadata, events

    def synthetic_records(self):
        """Invented source envelopes plus the portable parent's literal offers.

        Reuse the existing public bootstrap. Its invented state/request/zone IDs
        and creation annotation are controls, not a new real raw-log fixture.
        """
        maker = public_bootstrap.CastActivateAssociationTests(
            'test_real_portable_pre_post_and_authority_denials')
        maker.state = copy.deepcopy(self.fixture['before_parent'])
        records = maker.synthetic_bootstrap()
        request = records[-1]['greToClientEvent']['greToClientMessages'][1]
        selected = copy.deepcopy(request['actionsAvailableReq']['actions'][6])
        records.append({'payload': {'type': 'ClientMessageType_PerformActionResp', 'respId': 1,
            'gameStateId': 10, 'performActionResp': {'actions': [selected],
                                                  'autoPassPriority': 'AutoPassPriority_Yes'}}})
        certificate = self.state['choice_continuation']
        ability = certificate['stack_ability']['object_ref']
        raw_ability = {'instanceId': ability, 'type': 'GameObjectType_Ability', 'zoneId': 12,
            'visibility': 'Visibility_Public', 'ownerSeatId': 1, 'controllerSeatId': 1,
            'parentId': selected['instanceId'], 'grpId': selected['abilityGrpId']}
        diff = {'type': 'GameStateType_Diff', 'gameStateId': 11, 'prevGameStateId': 10,
            'gameObjects': [raw_ability],
            'zones': [{'zoneId': 12, 'type': 'ZoneType_Stack', 'visibility': 'Visibility_Public',
                       'objectInstanceIds': [ability]}],
            'annotations': [{'id': 901, 'affectorId': selected['instanceId'], 'affectedIds': [ability],
                'type': ['AnnotationType_AbilityInstanceCreated'],
                'details': [{'key': 'source_zone', 'type': 'KeyValuePairValueType_int32', 'valueInt32': [11]}]}]}
        binding = copy.deepcopy(certificate['binding']); binding.update(request_id=2, game_state_id=11)
        child = continuation._raw_child(certificate['child_observation'], binding)
        records.append({'greToClientEvent': {'greToClientMessages': [
            {'type': 'GREMessageType_GameStateMessage', 'systemSeatIds': [1], 'gameStateMessage': diff}, child]}})
        return records

    def replay_records(self, records, **options):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'synthetic-mp62.jsonl'
            path.write_text(''.join(json.dumps(row) + '\n' for row in records), encoding='utf-8')
            return replay(path, format='player-log', decision_state_version=13,
                          current_choice_continuation=True, **options)

    def producer(self, records):
        reducer = RawReducer(include_state_messages=True, include_request_parameters=True,
            include_targeted_activate=True, include_current_discard=True,
            include_target_payment_relation=True, include_cast_target_members=True,
            include_cast_activate_associations=True)
        stage = continuation.StageObserver(reducer)
        reducer.observer = stage.observe
        reducer.reset(1); stage.reset()
        for record in records:
            stage.prepare(record); reducer.apply(record); stage.after_apply()
        return reducer, stage

    def test_real_portable_fingerprint_eight_snapshots_and_baseline_reuse(self):
        data = FIXTURE.read_bytes().replace(b'\r\n', b'\n')
        self.assertEqual(len(data), 444810)
        self.assertEqual(hashlib.sha256(data).hexdigest(),
                         '122a5382b936e404309d158e6098b32ab3bb04cfc1727cb294666846c89ed109')
        self.assertEqual(len(self.fixture), 8)
        for name, state in self.fixture.items():
            with self.subTest(snapshot=name):
                original = copy.deepcopy(state)
                _state(state, state['binding'])
                report = continuation.evaluate_continuation(state)
                if name == 'first_child': self.positive(report)
                else: self.absent(report)
                self.assertEqual(state, original)
        before = enumerate_known_candidates(self.fixture['before_parent'], version=6)
        after = enumerate_known_candidates(self.fixture['parent_consumed'], version=6)
        self.assertEqual((before['returned_candidates'], before['returned_relations']), (6, 1))
        self.assertEqual((after['returned_candidates'], after['returned_relations']), (0, 0))
        self.assertEqual(enumerate_known_candidates(self.state, version=2)['returned_candidates'], 1)

    def test_portable_context_rejects_strict_identity_and_shape_mutations(self):
        cases = [
            (('binding', 'source_generation'), True),
            (('parent', 'binding', 'match'), 'other-match'),
            (('parent', 'binding', 'request_type'), 'GREMessageType_SelectTargetsReq'),
            (('parent', 'binding', 'game_state_id'), self.state['binding']['game_state_id']),
            (('parent', 'binding', 'request_id'), self.state['binding']['request_id']),
            (('parent', 'current'), True), (('parent', 'list_position'), 17),
            (('parent', 'active_action_count'), True), (('parent', 'flags', 'shouldStop'), 1),
            (('parent', 'identifier_refs', 'grpId'), 1),
            (('parent', 'response_type'), 'ClientMessageType_SelectTargetsResp'),
            (('parent', 'auto_pass_priority'), 'AutoPassPriority_No'),
            (('parent', 'source_zone_ref'), False),
            (('stack_ability', 'parent_object_ref'), 1), (('stack_ability', 'ability_grp_ref'), 1),
            (('stack_ability', 'zone_ref'), 1), (('stack_ability', 'created_state_id'), 1),
            (('stack_ability', 'controller_seat'), 2),
            (('child_observation', 'constraints', 'target_idx'), 1),
            (('child_observation', 'constraints', 'targeting_ability_grp_ref'), 1),
            (('child_observation', 'field_presence', 'selectedTargets'), True),
            (('child_observation', 'field_presence', 'allowUndo'), False),
            (('child_observation', 'envelope_prompt', 'promptId'), 0),
            (('child_observation', 'slot_prompt', 'parameters', 0, 'numberValue'), True),
            (('child_observation', 'target_entries', 0, 'highlight'), 1),
            (('child_observation', 'target_entries', 0, 'targetInstanceId'), 1),
        ]
        for path, value in cases:
            with self.subTest(path=path):
                state = copy.deepcopy(self.state); target = state['choice_continuation']
                for key in path[:-1]: target = target[key]
                target[path[-1]] = value
                with self.assertRaises(ValueError): _state(state, state['binding'])
                self.absent(continuation.evaluate_continuation(state))
        for path in ((), ('parent',), ('parent', 'binding'), ('stack_ability',),
                     ('child_observation',), ('child_observation', 'field_presence'),
                     ('child_observation', 'slot_prompt', 'parameters', 0)):
            with self.subTest(extra_at=path):
                state = copy.deepcopy(self.state); target = state['choice_continuation']
                for key in path: target = target[key]
                target['unreviewed'] = 1
                self.absent(continuation.evaluate_continuation(state))

    def test_finite_child_shape_does_not_borrow_old_target_capability(self):
        for mode in ('missing_min', 'missing_max', 'selected_zero', 'unselect', 'two_members'):
            with self.subTest(mode=mode):
                state = copy.deepcopy(self.state); observation = state['choice_continuation']['child_observation']
                constraints = observation['constraints']
                if mode.startswith('missing_'):
                    field = 'min' if mode == 'missing_min' else 'max'
                    constraints[field + '_targets'] = None
                    observation['field_presence'][field + 'Targets'] = False
                elif mode == 'selected_zero':
                    constraints['selected_count'] = 0; observation['field_presence']['selectedTargets'] = True
                elif mode == 'unselect':
                    constraints['entries'][0]['legal_action'] = 'SelectAction_Unselect'
                    observation['target_entries'][0]['legalAction'] = 'SelectAction_Unselect'
                else:
                    constraints['entries'] *= 2; observation['target_entries'] *= 2
                state['legal_action_space']['request_parameters']['targets'] = copy.deepcopy(constraints)
                self.absent(continuation.evaluate_continuation(state))

    def test_prompt_int32_and_highlight_are_observations_not_counts(self):
        self.assertNotEqual(self.state['choice_continuation']['stack_ability']['ability_grp_ref'],
            self.state['choice_continuation']['child_observation']['constraints']['targeting_ability_grp_ref'])
        for value in (-(2**31), 2**31-1, 120001):
            state = copy.deepcopy(self.state)
            state['choice_continuation']['child_observation']['slot_prompt']['parameters'][0]['numberValue'] = value
            self.positive(continuation.evaluate_continuation(state))
        for value in (-(2**31)-1, 2**31, True, None, '1'):
            state = copy.deepcopy(self.state)
            state['choice_continuation']['child_observation']['slot_prompt']['parameters'][0]['numberValue'] = value
            self.absent(continuation.evaluate_continuation(state))
        state = copy.deepcopy(self.state)
        del state['choice_continuation']['child_observation']['target_entries'][0]['highlight']
        self.positive(continuation.evaluate_continuation(state))

    def test_visibility_stack_type_and_source_ownership_cannot_be_inferred(self):
        for mode in ('source_owner', 'source_zone', 'ability_controller', 'ability_type', 'unknown_stack'):
            state = copy.deepcopy(self.state); c = state['choice_continuation']; objects = state['visible_objects']
            source = next(o for o in objects if o['instance_id'] == c['stack_ability']['parent_object_ref'])
            ability = next(o for o in objects if o['instance_id'] == c['stack_ability']['object_ref'])
            if mode == 'source_owner': source['owner_seat'] = 2
            elif mode == 'source_zone': source['zone'] = 'ZoneType_Graveyard'
            elif mode == 'ability_controller': ability['controller_seat'] = 2
            elif mode == 'ability_type': state['game']['stack']['members'][0]['object_type'] = 'GameObjectType_Card'
            else: state['game']['stack'] = {'availability': 'unknown', 'zone_id': None, 'members': None,
                                          'order_basis': 'literal_gre_zone_objectInstanceIds'}
            self.absent(continuation.evaluate_continuation(state))

    def test_no_request_old_versions_stopped_and_malformed_refs_are_not_current(self):
        state = copy.deepcopy(self.state); state['status'] = 'state_observed_without_request'
        with self.assertRaises(ValueError): _state(state, state['binding'])
        self.absent(continuation.evaluate_continuation(state))
        state = copy.deepcopy(self.state); state['source']['stopped'] = True
        self.absent(continuation.evaluate_continuation(state))
        for version in range(1, 13):
            state = copy.deepcopy(self.state); state['schema_version'] = f'mtgaplayer.decision-state.v{version}'
            with self.assertRaises(ValueError): _state(state, state['binding'])
            self.absent(continuation.evaluate_continuation(state))
        for ref in ({'not': 'a snapshot ref'}, {'session_id': 'x', 'sequence': 1, 'binding': self.fixture['before_parent']['binding']}):
            report = continuation.evaluate_continuation(self.state, source_snapshot_ref=ref)
            self.absent(report); self.assertIsNone(report['source_snapshot_ref'])

    def test_synthetic_producer_continuous_chain_and_response_consumption(self):
        records = self.synthetic_records()
        document = self.replay_records(records)
        self.positive(document['current_choice_continuation'])
        self.assertEqual(document['decision_state']['choice_continuation']['parent']['list_position'], 6)
        self.assertFalse(document['decision_state']['choice_continuation']['parent']['current'])
        child = records[-1]['greToClientEvent']['greToClientMessages'][1]
        records.append({'payload': {'type': 'ClientMessageType_SelectTargetsResp', 'respId': 2,
            'gameStateId': 11, 'selectTargetsResp': {'target': copy.deepcopy(child['selectTargetsReq']['targets'][0])}}})
        document = self.replay_records(records)
        self.absent(document['current_choice_continuation'])
        self.assertIsNone(document['decision_state']['choice_continuation'])
        self.assertIsNone(document['decision_state']['binding']['request_id'])

    def test_synthetic_producer_public_creation_identity_and_annotation_controls(self):
        for mode in ('group', 'parent', 'private', 'private_zone', 'wrong_zone', 'multiple', 'annotation', 'source_zone'):
            with self.subTest(mode=mode):
                records = self.synthetic_records(); messages = records[-1]['greToClientEvent']['greToClientMessages']
                diff = messages[0]['gameStateMessage']; ability = diff['gameObjects'][0]
                if mode == 'group': ability['grpId'] += 1
                elif mode == 'parent': ability['parentId'] += 1
                elif mode == 'private': ability['visibility'] = 'Visibility_Private'
                elif mode == 'private_zone': diff['zones'][0]['visibility'] = 'Visibility_Private'
                elif mode == 'wrong_zone': diff['zones'][0]['type'] = 'ZoneType_Graveyard'
                elif mode == 'multiple':
                    other = copy.deepcopy(ability); other['instanceId'] += 100
                    diff['gameObjects'].append(other); diff['zones'][0]['objectInstanceIds'].append(other['instanceId'])
                elif mode == 'annotation': diff['annotations'] = []
                else: diff['annotations'][0]['details'][0]['valueInt32'] = [13]
                self.absent(self.replay_records(records)['current_choice_continuation'])

    def test_synthetic_private_existing_ability_and_other_battlefield_zone_are_not_creation_proof(self):
        for mode in ('existing_private_id', 'other_source_zone'):
            with self.subTest(mode=mode):
                records = self.synthetic_records()
                full = records[2]['greToClientEvent']['greToClientMessages'][0]['gameStateMessage']
                diff = records[4]['greToClientEvent']['greToClientMessages'][0]['gameStateMessage']
                if mode == 'existing_private_id':
                    old = copy.deepcopy(diff['gameObjects'][0])
                    old.update(zoneId=14, visibility='Visibility_Private', ownerSeatId=2, controllerSeatId=2)
                    full['gameObjects'].append(old)
                    full['zones'].append({'zoneId': 14, 'type': 'ZoneType_Exile',
                        'visibility': 'Visibility_Private', 'objectInstanceIds': [old['instanceId']]})
                    diff['zones'].append({'zoneId': 14, 'type': 'ZoneType_Exile',
                        'visibility': 'Visibility_Private', 'objectInstanceIds': []})
                else:
                    full['zones'].append({'zoneId': 14, 'type': 'ZoneType_Battlefield',
                        'visibility': 'Visibility_Public', 'objectInstanceIds': []})
                    diff['annotations'][0]['details'][0]['valueInt32'] = [14]
                self.absent(self.replay_records(records)['current_choice_continuation'])

    def test_synthetic_producer_response_duplicate_and_discontinuity_controls(self):
        for mode in ('response_id', 'response_state', 'response_type', 'response_row', 'duplicate', 'mixed',
                     'duplicate_offer', 'gap', 'full', 'wrong_child_source', 'wrong_child_group', 'wrong_recipient'):
            with self.subTest(mode=mode):
                records = self.synthetic_records(); payload = records[3]['payload']
                messages = records[4]['greToClientEvent']['greToClientMessages']
                if mode == 'response_id': payload['respId'] = 99
                elif mode == 'response_state': payload['gameStateId'] = 9
                elif mode == 'response_type': payload['type'] = 'ClientMessageType_SelectTargetsResp'
                elif mode == 'response_row': payload['performActionResp']['actions'][0]['shouldStop'] = False
                elif mode == 'duplicate': records.insert(4, copy.deepcopy(records[3]))
                elif mode == 'mixed': records[3]['greToClientEvent'] = records.pop(4)['greToClientEvent']
                elif mode == 'duplicate_offer':
                    actions = records[2]['greToClientEvent']['greToClientMessages'][1]['actionsAvailableReq']['actions']
                    actions.append(copy.deepcopy(actions[6]))
                elif mode == 'gap': messages[0]['gameStateMessage']['prevGameStateId'] = 9
                elif mode == 'full': messages[0]['gameStateMessage']['type'] = 'GameStateType_Full'
                elif mode == 'wrong_child_source': messages[1]['selectTargetsReq']['sourceId'] += 1
                elif mode == 'wrong_child_group': messages[1]['selectTargetsReq']['abilityGrpId'] += 1
                else: messages[1]['systemSeatIds'] = [2]
                self.absent(self.replay_records(records)['current_choice_continuation'])

    def test_synthetic_broadcast_cancel_and_undo_never_rearm_on_retransmission(self):
        for mode in ('broadcast', 'cancel', 'undo', 'other_payload'):
            with self.subTest(mode=mode):
                records = self.synthetic_records(); child = copy.deepcopy(records[-1]['greToClientEvent']['greToClientMessages'][1])
                if mode == 'broadcast':
                    revoked = copy.deepcopy(child); revoked['systemSeatIds'] = [1, 2]
                    records.append({'greToClientEvent': {'greToClientMessages': [revoked]}})
                else:
                    typ = {'cancel': 'ClientMessageType_CancelActionReq', 'undo': 'ClientMessageType_UndoReq',
                           'other_payload': 'ClientMessageType_UnsupportedReq'}[mode]
                    records.append({'payload': {'type': typ}})
                records.append({'greToClientEvent': {'greToClientMessages': [child]}})
                self.absent(self.replay_records(records)['current_choice_continuation'])

    def test_synthetic_standalone_ui_telemetry_is_ignored_but_mixed_ui_revokes(self):
        records = self.synthetic_records()
        telemetry = {'payload': {'type': 'ClientMessageType_UIMessage'}}
        # UI telemetry before the response, while pending, and after the child
        # supplies no association proof and does not terminate these contexts.
        rows = records[:3] + [copy.deepcopy(telemetry)] + records[3:4] + [copy.deepcopy(telemetry)]
        rows += records[4:] + [copy.deepcopy(telemetry)]
        self.positive(self.replay_records(rows)['current_choice_continuation'])
        child = copy.deepcopy(records[-1]['greToClientEvent']['greToClientMessages'][1])
        mixed = copy.deepcopy(telemetry)
        mixed['greToClientEvent'] = {'greToClientMessages': [copy.deepcopy(child)]}
        rows += [mixed, {'greToClientEvent': {'greToClientMessages': [child]}}]
        self.absent(self.replay_records(rows)['current_choice_continuation'])

    def test_synthetic_reset_and_pending_age_bound_discard_lineage(self):
        reducer, stage = self.producer(self.synthetic_records())
        self.assertIsNotNone(reducer.request.get(continuation.PRIVATE))
        stage.reset()
        self.assertNotIn(continuation.PRIVATE, reducer.request)
        records = self.synthetic_records(); reducer, stage = self.producer(records[:4])
        self.assertIsNotNone(stage.pending)
        stage.reset(); reducer.reset(2)
        for record in records[:3] + records[4:]:
            stage.prepare(record); reducer.apply(record); stage.after_apply()
        self.assertIsNone(stage.active)
        reducer, stage = self.producer(records[:4])
        for _ in range(65): stage.prepare({}); reducer.apply({}); stage.after_apply()
        self.assertIsNone(stage.pending)
        stage.prepare(records[4]); reducer.apply(records[4]); stage.after_apply()
        self.assertIsNone(stage.active)

    def test_synthetic_revised_request_keeps_old_target_validation_without_lineage(self):
        records = self.synthetic_records(); first = copy.deepcopy(records[-1]['greToClientEvent']['greToClientMessages'][1])
        records.append({'payload': {'type': 'ClientMessageType_SelectTargetsResp', 'respId': 2, 'gameStateId': 11}})
        revised = copy.deepcopy(first); revised.update(msgId=3, gameStateId=12)
        slot = revised['selectTargetsReq']['targets'][0]; slot['selectedTargets'] = 1
        slot['targets'][0]['legalAction'] = 'SelectAction_Unselect'
        records.append({'greToClientEvent': {'greToClientMessages': [
            {'type': 'GREMessageType_GameStateMessage', 'systemSeatIds': [1], 'gameStateMessage': {
                'type': 'GameStateType_Diff', 'gameStateId': 12, 'prevGameStateId': 11}}, revised]}})
        document = self.replay_records(records)
        self.absent(document['current_choice_continuation'])
        result = enumerate_known_candidates(document['decision_state'], version=3)
        self.assertEqual(result['probe_coverage']['verified'], 1)
        records.append({'payload': {'type': 'ClientMessageType_SubmitTargetsReq', 'respId': 3, 'gameStateId': 12}})
        document = self.replay_records(records)
        self.absent(document['current_choice_continuation'])
        self.assertIsNone(document['decision_state']['binding']['request_id'])

    def test_synthetic_other_child_profiles_preserve_existing_target_capability(self):
        for mode in ('optional_target', 'explicit_selected_zero', 'already_unselect'):
            with self.subTest(mode=mode):
                records = self.synthetic_records()
                slot = records[-1]['greToClientEvent']['greToClientMessages'][1]['selectTargetsReq']['targets'][0]
                version, expected = 2, 1
                if mode == 'optional_target': slot['minTargets'] = 0; expected = 2
                elif mode == 'explicit_selected_zero': slot['selectedTargets'] = 0
                else:
                    slot['selectedTargets'] = 1
                    slot['targets'][0]['legalAction'] = 'SelectAction_Unselect'
                    version = 3
                document = self.replay_records(records)
                self.absent(document['current_choice_continuation'])
                state = document['decision_state']; self.assertIsNotNone(state)
                self.assertIsNone(state['choice_continuation'])
                self.assertEqual(state['legal_action_space']['request_parameters']['profile'],
                                 'reviewed_single_slot_public_targets')
                report = enumerate_known_candidates(state, version=version)
                if version == 2: self.assertEqual(report['returned_candidates'], expected)
                else: self.assertEqual(report['probe_coverage']['verified'], expected)

    def test_consumer_current_ref_lease_history_close_and_race_gates(self):
        _, consumer, clock, _, _, _ = self.transport()
        result = continuation.assess_current_continuation(consumer); self.positive(result)
        self.assertEqual(result['source_snapshot_ref'], consumer.current_view()['current_snapshot_ref'])
        clock.advance(501); self.absent(continuation.assess_current_continuation(consumer))
        _, consumer, _, _, _, _ = self.transport(history=True)
        self.absent(continuation.assess_current_continuation(consumer))
        _, consumer, _, _, _, events = self.transport()
        consumer.close(); self.absent(continuation.assess_current_continuation(consumer))
        self.assertFalse(consumer.accept_event(events[0])); self.absent(continuation.assess_current_continuation(consumer))
        _, consumer, clock, _, _, _ = self.transport()
        original = continuation.evaluate_continuation
        def expire(*args, **kwargs):
            result = original(*args, **kwargs); clock.advance(501); return result
        with patch.object(continuation, 'evaluate_continuation', side_effect=expire):
            self.absent(continuation.assess_current_continuation(consumer))
        self.absent(continuation.assess_current_continuation(consumer.current_view()))

    def test_consumer_rejects_without_request_context_and_partial_publication(self):
        publisher, consumer, clock, document, metadata, events = self.transport()
        # The borrowed context is the sole invalid addition to a real valid
        # no-request state, rather than merely leaving an inconsistent request ID.
        state = copy.deepcopy(self.fixture['first_child_consumed'])
        _state(state, state['binding'])
        state['choice_continuation'] = copy.deepcopy(self.state['choice_continuation'])
        state['source'].update(mode='watch', phase='append', stopped=False)
        invalid = copy.deepcopy(events[0]); invalid['decision_state'] = state
        invalid['binding'] = copy.deepcopy(state['binding'])
        invalid['snapshot_ref']['binding'] = copy.deepcopy(state['binding'])
        invalid.update(source_status='state_observed_without_request', new_request_observed=False)
        other = DecisionConsumer(10000, 500, clock)
        self.assertFalse(other.accept_event(invalid))
        self.absent(continuation.assess_current_continuation(other))
        document['decision_state'] = None; document['source']['partial_record'] = True
        for event in publisher.observe(document, metadata): self.assertTrue(consumer.accept_event(event))
        self.absent(continuation.assess_current_continuation(consumer))

    def test_synthetic_stream_assessment_runs_on_owner_and_rechecks_output(self):
        publisher, _, clock, _, _, events = self.transport(); events += publisher.stop()
        owner = threading.get_ident(); called = []; output = []; original = continuation.evaluate_continuation
        def observe(*args, **kwargs):
            called.append(threading.get_ident()); return original(*args, **kwargs)
        with patch.object(continuation, 'evaluate_continuation', side_effect=observe):
            self.assertEqual(consume_events(io.StringIO(''.join(json.dumps(e)+'\n' for e in events)), output.append,
                DecisionConsumer(10000, 500, clock), current_choice_continuation=True), 0)
        self.assertTrue(called); self.assertEqual(set(called), {owner})
        self.assertTrue(any(v['current_choice_continuation']['continuation_relationship_consistent'] for v in output))
        self.absent(output[-1]['current_choice_continuation'])
        publisher, _, clock, _, _, events = self.transport(); events += publisher.stop(); output = []
        original_assess = continuation.assess_current_continuation
        def late(*args, **kwargs):
            result = original_assess(*args, **kwargs)
            if result['continuation_relationship_consistent']: clock.advance(501)
            return result
        with patch.object(continuation, 'assess_current_continuation', side_effect=late):
            consume_events(io.StringIO(''.join(json.dumps(e)+'\n' for e in events)), output.append,
                DecisionConsumer(10000, 500, clock), current_choice_continuation=True)
        self.assertTrue(output)
        for value in output: self.absent(value['current_choice_continuation'])

    def test_synthetic_replay_cli_opt_in_and_old_default_gate(self):
        records = self.synthetic_records()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'synthetic-cli-only.jsonl'
            path.write_text(''.join(json.dumps(r)+'\n' for r in records), encoding='utf-8')
            result = subprocess.run([sys.executable, '-m', 'mtgaplayer', 'replay', str(path),
                '--format', 'player-log', '--decision-state-version', '13', '--current-choice-continuation'],
                capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.positive(json.loads(result.stdout)['current_choice_continuation'])
            with self.assertRaisesRegex(ValueError, 'current_choice_continuation_requires_player_log_state13'):
                replay(path, format='player-log', decision_state_version=12, current_choice_continuation=True)
            default = replay(path, format='player-log')
            self.assertNotIn('current_choice_continuation', default)
            self.assertNotIn('decision_state', default)


if __name__ == '__main__':
    unittest.main()
