"""Public real snapshots; synthetic bootstrap, mutations and transport controls.

No owner raw log, private projection/helper, game resource or native input is
accessed. Invented Full/auth/GRE records are plumbing tests, not real evidence.
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

from mtgaplayer import choice_continuation as first, target_revision as revision
from mtgaplayer.choice_candidates import enumerate_known_candidates
from mtgaplayer.cli import replay, watch, watch_decision_events
from mtgaplayer.decision_consumer import DecisionConsumer, EXECUTION, _state, consume_events
from mtgaplayer.decision_publisher import DecisionPublisher
from mtgaplayer.raw_log import RawReducer
import test_choice_continuation as first_tests
from test_decision_publisher import ManualClock, append, poll_events


FIXTURE = Path(__file__).parent / 'fixtures/current_target_revision_real_v14.json'


class TargetRevisionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads(FIXTURE.read_text(encoding='utf-8'))
        self.state = self.fixture['revised_child']

    def report(self, state=None, **kwargs):
        return revision.evaluate_revision(self.state if state is None else state, **kwargs)

    def denials(self, result):
        self.assertEqual(result['schema_version'], revision.VERSION)
        self.assertIs(result['read_only'], True)
        for key in (*revision.DENIALS, *EXECUTION): self.assertIs(result[key], False, key)

    def positive(self, result):
        self.assertEqual(result['status'], 'current_revision_relationship_consistent')
        for key in revision.FACTS: self.assertIs(result[key], True, key)
        self.assertEqual(result['request_local_selected_set_status'], 'verified_known_constraints')
        self.denials(result)

    def absent(self, result):
        self.assertEqual(result['status'], 'insufficient_evidence')
        for key in revision.FACTS: self.assertIs(result[key], False, key)
        self.assertIsNone(result['continuation'])
        self.denials(result)

    def synthetic_records(self, terminal=False):
        """Reuse public first-stage literals, then invent a finite revision chain."""
        maker = first_tests.ChoiceContinuationTests('test_synthetic_producer_continuous_chain_and_response_consumption')
        maker.fixture = self.fixture; maker.state = self.fixture['first_child']
        records = maker.synthetic_records()
        context = self.state[revision.FIELD]; target_id = context['selected_target_identity']['object_ref']
        full = records[2]['greToClientEvent']['greToClientMessages'][0]['gameStateMessage']
        target = next(o for o in full['gameObjects'] if o['instanceId'] == target_id)
        # The old bootstrap made unknown objects Card skeletons. This explicitly
        # synthetic Token has an opaque raw group, never a catalog card ID.
        target.update(type='GameObjectType_Token', grpId=777777)
        selected = copy.deepcopy(context['selection_update']['target'])
        records.append({'payload': {'type': 'ClientMessageType_SelectTargetsResp', 'respId': 2,
            'gameStateId': 11, 'selectTargetsResp': {'target': selected}}})
        binding = copy.deepcopy(context['binding']); binding.update(request_id=3, game_state_id=12)
        request = first._raw_child(context['revised_observation'], binding)
        records.append({'greToClientEvent': {'greToClientMessages': [
            {'type': 'GREMessageType_GameStateMessage', 'systemSeatIds': [1], 'gameStateMessage': {
                'type': 'GameStateType_Diff', 'gameStateId': 12, 'prevGameStateId': 11}}, request]}})
        if terminal:
            records.append({'payload': {'type': 'ClientMessageType_SubmitTargetsReq', 'respId': 3, 'gameStateId': 12}})
        return records

    def replay_records(self, records):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'synthetic-revision.jsonl'
            path.write_text(''.join(json.dumps(r)+'\n' for r in records), encoding='utf-8')
            return replay(path, format='player-log', decision_state_version=14,
                          current_choice_continuation=True, current_target_revision=True)

    def producer(self, records):
        reducer = RawReducer(include_state_messages=True, include_request_parameters=True,
            include_targeted_activate=True, include_current_discard=True, include_target_payment_relation=True,
            include_cast_target_members=True, include_cast_activate_associations=True)
        stage = first.StageObserver(reducer, include_revision=True)
        reducer.observer = stage.observe; reducer.reset(1); stage.reset()
        for row in records: stage.prepare(row); reducer.apply(row); stage.after_apply()
        return reducer, stage

    def transport(self, history=False):
        clock = ManualClock(); publisher = DecisionPublisher(clock_ns=clock, session_id='synthetic-mp63', state_version=14)
        state = copy.deepcopy(self.state)
        state['source'].update(mode='watch', phase='history' if history else 'append', stopped=False)
        document = {'decision_state': state, 'source': {'phase': state['source']['phase'], 'partial_record': False}}
        metadata = {'poll_started_ns': clock(), 'poll_completed_ns': clock(), 'poll_read_ns': 0,
            'reducer_apply_ns': 0, 'decision_state_assembly_ns': 0, 'request_changed': True, 'new_final_request': True}
        events = publisher.observe(document, metadata); consumer = DecisionConsumer(10000, 500, clock)
        for event in events: self.assertTrue(consumer.accept_event(event))
        return publisher, consumer, clock, document, metadata, events

    def test_real_portable_eight_snapshots_fingerprint_and_old_stage_separation(self):
        raw = FIXTURE.read_bytes().replace(b'\r\n', b'\n')
        self.assertEqual(len(raw), 450519)
        self.assertEqual(hashlib.sha256(raw).hexdigest(), '9332ebafad8d09ad17a08f19d2a1f5f783aa5a3d58f808cd1c7bc3df4ee1ac2c')
        self.assertEqual(len(self.fixture), 8)
        for name, state in self.fixture.items():
            with self.subTest(snapshot=name):
                original = copy.deepcopy(state); _state(state, state['binding'])
                if name == 'revised_child': self.positive(self.report(state))
                else: self.absent(self.report(state))
                self.assertEqual(state, original)
        self.assertTrue(first.evaluate_continuation(self.fixture['first_child'])['continuation_relationship_consistent'])
        self.assertFalse(first.evaluate_continuation(self.state)['continuation_relationship_consistent'])
        self.assertIsNone(self.state[first.FIELD])
        self.assertEqual(enumerate_known_candidates(self.state, version=3)['probe_coverage']['verified'], 1)
        c = self.state[revision.FIELD]
        self.assertLess(c['first_child']['stack_ability']['created_state_id'], c['binding']['game_state_id'])

    def test_portable_strict_context_bindings_and_unknown_fields(self):
        cases = [
            (('binding', 'source_generation'), True), (('intervening_diff_count',), True),
            (('intervening_diff_count',), 2), (('first_child', 'parent', 'current'), True),
            (('first_child', 'stack_ability', 'created_state_id'), self.state['binding']['game_state_id']),
            (('selection_update', 'request_binding', 'request_id'), self.state['binding']['request_id']),
            (('selection_update', 'request_binding', 'game'), 2),
            (('selection_update', 'response_type'), 'ClientMessageType_SubmitTargetsReq'),
            (('selection_update', 'target', 'targetIdx'), True),
            (('selection_update', 'target', 'targets', 0, 'targetInstanceId'), 1),
            (('selection_update', 'target', 'targets', 0, 'legalAction'), 'SelectAction_Unselect'),
            (('selection_update', 'target', 'targets', 0, 'highlight'), False),
            (('selected_target_identity', 'card_ref'), 777777),
            (('selected_target_identity', 'object_ref'), 1), (('selected_target_identity', 'zone_ref'), 0),
            (('selected_target_identity', 'owner_seat'), 2), (('selected_target_identity', 'controller_seat'), 2)]
        for path, value in cases:
            with self.subTest(path=path):
                state = copy.deepcopy(self.state); target = state[revision.FIELD]
                for key in path[:-1]: target = target[key]
                target[path[-1]] = value
                with self.assertRaises(ValueError): _state(state, state['binding'])
                self.absent(self.report(state))
        for path in ((), ('selection_update',), ('selection_update', 'target'), ('selected_target_identity',),
                     ('revised_observation',), ('revised_observation', 'field_presence')):
            state = copy.deepcopy(self.state); target = state[revision.FIELD]
            for key in path: target = target[key]
            target['unreviewed'] = 0; self.absent(self.report(state))

    def test_portable_revised_counts_domain_and_namespace_are_request_local(self):
        for mode in ('min', 'max', 'selected', 'presence', 'select', 'multiple', 'targeting_group', 'source', 'top_group'):
            with self.subTest(mode=mode):
                state = copy.deepcopy(self.state); o = state[revision.FIELD]['revised_observation']; c = o['constraints']
                if mode in ('min', 'max'): c[mode+'_targets'] = 0
                elif mode == 'selected': c['selected_count'] = 0
                elif mode == 'presence': o['field_presence']['selectedTargets'] = False
                elif mode == 'select': c['entries'][0]['legal_action'] = 'SelectAction_Select'; o['target_entries'][0]['legalAction'] = 'SelectAction_Select'
                elif mode == 'multiple': c['entries'] *= 2; o['target_entries'] *= 2
                elif mode == 'targeting_group': c['targeting_ability_grp_ref'] += 1
                elif mode == 'source': c['source_object_ref'] += 1
                else: c['ability_grp_ref'] += 1
                state['legal_action_space']['request_parameters']['targets'] = copy.deepcopy(c)
                self.absent(self.report(state))
        c = self.state[revision.FIELD]
        self.assertNotEqual(c['revised_observation']['constraints']['targeting_ability_grp_ref'],
                            c['revised_observation']['constraints']['ability_grp_ref'])

    def test_token_unknown_catalog_and_producer_only_identity_limits(self):
        identity = self.state[revision.FIELD]['selected_target_identity']
        self.assertEqual(identity['object_type'], 'GameObjectType_Token'); self.assertIsNone(identity['card_ref'])
        state = copy.deepcopy(self.state); state[revision.FIELD]['selected_target_identity']['object_type'] = 'GameObjectType_Card'
        self.absent(self.report(state))
        # Portable visible objects have no raw BF zone ID. A different positive
        # attested zone number is structurally admissible, never reauthenticated.
        state = copy.deepcopy(self.state); state[revision.FIELD]['selected_target_identity']['zone_ref'] += 100
        result = self.report(state); self.positive(result); self.assertFalse(result['raw_source_reauthenticated'])

    def test_synthetic_complete_chain_two_stages_and_terminal_revocation(self):
        rows = self.synthetic_records()
        first_doc = self.replay_records(rows[:5]); self.assertTrue(first_doc['current_choice_continuation']['continuation_relationship_consistent'])
        self.absent(first_doc['current_target_revision'])
        self.absent(self.replay_records(rows[:6])['current_target_revision'])
        self.positive(self.replay_records(rows)['current_target_revision'])
        doc = self.replay_records(self.synthetic_records(terminal=True)); self.absent(doc['current_target_revision'])
        self.assertIsNone(doc['decision_state']['binding']['request_id'])
        self.assertEqual(enumerate_known_candidates(doc['decision_state'], version=3)['probe_coverage']['verified'], 0)

    def test_synthetic_strict_response_headers_slot_member_action_and_highlight(self):
        for mode in ('id', 'state', 'type', 'slot', 'bool_slot', 'member', 'unselect', 'highlight', 'extra', 'multi', 'wrapper'):
            with self.subTest(mode=mode):
                rows = self.synthetic_records(); p = rows[5]['payload']; target = p['selectTargetsResp']['target']
                if mode == 'id': p['respId'] = 99
                elif mode == 'state': p['gameStateId'] = 10
                elif mode == 'type': p['type'] = 'ClientMessageType_PerformActionResp'
                elif mode == 'slot': target['targetIdx'] += 1
                elif mode == 'bool_slot': target['targetIdx'] = True
                elif mode == 'member': target['targets'][0]['targetInstanceId'] += 1
                elif mode == 'unselect': target['targets'][0]['legalAction'] = 'SelectAction_Unselect'
                elif mode == 'highlight': target['targets'][0]['highlight'] = {'bad': 'shape'}
                elif mode == 'extra': target['targets'][0]['extra'] = 1
                elif mode == 'multi': target['targets'] *= 2
                else: p['selectTargetsResp']['extra'] = 1
                self.absent(self.replay_records(rows)['current_target_revision'])

    def test_synthetic_optional_response_highlight_is_preserved_absent(self):
        rows = self.synthetic_records(); del rows[5]['payload']['selectTargetsResp']['target']['targets'][0]['highlight']
        result = self.replay_records(rows)['current_target_revision']; self.positive(result)
        self.assertNotIn('highlight', result['continuation']['selection_update']['target']['targets'][0])

    def test_synthetic_revised_request_must_match_independent_namespace_and_selected_literal(self):
        for mode in ('source', 'group', 'targeting_group', 'slot', 'player', 'member', 'min', 'max', 'selected', 'select', 'extra'):
            with self.subTest(mode=mode):
                rows = self.synthetic_records(); msg = rows[6]['greToClientEvent']['greToClientMessages'][1]
                body = msg['selectTargetsReq']; slot = body['targets'][0]
                if mode == 'source': body['sourceId'] += 1
                elif mode == 'group': body['abilityGrpId'] += 1
                elif mode == 'targeting_group': slot['targetingAbilityGrpId'] += 1
                elif mode == 'slot': slot['targetIdx'] += 1
                elif mode == 'player': slot['targetingPlayer'] = 2
                elif mode == 'member': slot['targets'][0]['targetInstanceId'] += 1
                elif mode in ('min', 'max'): slot[mode+'Targets'] = 0
                elif mode == 'selected': del slot['selectedTargets']
                elif mode == 'select': slot['targets'][0]['legalAction'] = 'SelectAction_Select'
                else: slot['extra'] = 1
                self.absent(self.replay_records(rows)['current_target_revision'])

    def test_synthetic_raw_signatures_reject_storage_type_group_and_zone_changes(self):
        for mode in ('float_group', 'group', 'source_group', 'source_zone_visibility', 'target_private', 'ability_parent', 'float_parent_id'):
            with self.subTest(mode=mode):
                rows = self.synthetic_records(); full = rows[2]['greToClientEvent']['greToClientMessages'][0]['gameStateMessage']
                diff = rows[6]['greToClientEvent']['greToClientMessages'][0]['gameStateMessage']
                target_id = self.state[revision.FIELD]['selected_target_identity']['object_ref']
                source_id = self.state[revision.FIELD]['first_child']['stack_ability']['parent_object_ref']
                if mode == 'source_zone_visibility':
                    zone = copy.deepcopy(next(z for z in full['zones'] if z['zoneId'] == 11)); zone['visibility'] = 'Visibility_Private'; diff['zones'] = [zone]
                elif mode in ('ability_parent', 'float_parent_id'):
                    value = copy.deepcopy(rows[4]['greToClientEvent']['greToClientMessages'][0]['gameStateMessage']['gameObjects'][0])
                    value['parentId'] = float(value['parentId']) if mode == 'float_parent_id' else value['parentId'] + 1
                    diff['gameObjects'] = [value]
                else:
                    ident = source_id if mode == 'source_group' else target_id
                    value = copy.deepcopy(next(o for o in full['gameObjects'] if o['instanceId'] == ident))
                    if mode == 'float_group': value['grpId'] = float(value['grpId'])
                    elif mode == 'target_private': value['visibility'] = 'Visibility_Private'
                    else: value['grpId'] += 1
                    diff['gameObjects'] = [value]
                document = self.replay_records(rows)
                self.absent(document['current_target_revision'])
                if mode == 'float_parent_id':
                    self.assertIs(document['current']['valid'], True)
                    self.assertEqual(enumerate_known_candidates(document['decision_state'], version=3)['probe_coverage']['verified'], 1)
                    reducer, _ = self.producer(rows)
                    self.assertIsNone(reducer.error)

    def test_synthetic_nested_signature_is_deep_frozen(self):
        rows = self.synthetic_records(); reducer, stage = self.producer(rows[:5])
        stage.prepare(rows[5]); saved = stage.revision.prepared
        self.assertIsNotNone(saved)
        source = self.state[revision.FIELD]['first_child']['stack_ability']['parent_object_ref']
        original = copy.deepcopy(saved['signatures'][source])
        reducer.objects[source]['uniqueAbilities'][0]['grpId'] += 1
        self.assertEqual(saved['signatures'][source], original)
        reducer.apply(rows[5]); stage.after_apply()
        stage.prepare(rows[6]); reducer.apply(rows[6]); stage.after_apply()
        self.assertIsNone(stage.revision.active)

    def test_synthetic_duplicate_gap_full_reset_and_pending_limit(self):
        for mode in ('duplicate_response', 'duplicate_request', 'gap', 'full'):
            with self.subTest(mode=mode):
                rows = self.synthetic_records()
                if mode == 'duplicate_response': rows.insert(6, copy.deepcopy(rows[5]))
                elif mode == 'duplicate_request': rows.append({'greToClientEvent': {'greToClientMessages': [copy.deepcopy(rows[6]['greToClientEvent']['greToClientMessages'][1])]}})
                elif mode == 'gap': rows[6]['greToClientEvent']['greToClientMessages'][0]['gameStateMessage']['prevGameStateId'] = 10
                else:
                    full = copy.deepcopy(rows[2]['greToClientEvent']['greToClientMessages'][0]['gameStateMessage'])
                    full.update(type='GameStateType_Full', gameStateId=12)
                    full.pop('prevGameStateId', None)
                    creation = rows[4]['greToClientEvent']['greToClientMessages'][0]['gameStateMessage']
                    full['gameObjects'] += copy.deepcopy(creation['gameObjects'])
                    stack = next(z for z in full['zones'] if z['zoneId'] == 12)
                    stack['objectInstanceIds'] = copy.deepcopy(creation['zones'][0]['objectInstanceIds'])
                    rows[6]['greToClientEvent']['greToClientMessages'][0]['gameStateMessage'] = full
                document = self.replay_records(rows)
                self.absent(document['current_target_revision'])
                if mode == 'full':
                    self.assertIs(document['current']['valid'], True)
                    self.assertEqual(document['decision_state']['binding']['game_state_id'], 12)
                    self.assertEqual(enumerate_known_candidates(document['decision_state'], version=3)['probe_coverage']['verified'], 1)
                    reducer, _ = self.producer(rows)
                    self.assertIsNone(reducer.error)
                    self.assertEqual((reducer.accepted_kind, reducer.version), ('full', 12))
        rows = self.synthetic_records(); reducer, stage = self.producer(rows[:6]); self.assertIsNotNone(stage.revision.pending)
        stage.reset(); self.assertIsNone(stage.revision.pending)
        stage.prepare(rows[6]); reducer.apply(rows[6]); stage.after_apply(); self.assertIsNone(stage.revision.active)
        rows[6:6] = [{'payload': {'type': 'ClientMessageType_UIMessage'}} for _ in range(65)]
        self.absent(self.replay_records(rows)['current_target_revision'])

    def test_synthetic_mixed_first_child_record_cannot_recache_and_advance(self):
        for mode in ('auth', 'room', 'ui'):
            with self.subTest(mode=mode):
                rows = self.synthetic_records()
                if mode == 'auth': rows[4]['authenticateResponse'] = copy.deepcopy(rows[0]['authenticateResponse'])
                elif mode == 'room': rows[4]['matchGameRoomStateChangedEvent'] = copy.deepcopy(rows[1]['matchGameRoomStateChangedEvent'])
                else: rows[4]['payload'] = {'type': 'ClientMessageType_UIMessage'}
                self.absent(self.replay_records(rows)['current_target_revision'])

    def test_synthetic_mixed_response_malformed_payload_cancel_and_broadcast_revoke(self):
        for mode in ('mixed_response', 'null_payload', 'cancel', 'undo', 'broadcast'):
            with self.subTest(mode=mode):
                rows = self.synthetic_records()
                if mode == 'mixed_response': rows[5]['greToClientEvent'] = rows.pop(6)['greToClientEvent']
                elif mode == 'null_payload': rows.insert(5, {'payload': None})
                elif mode in ('cancel', 'undo'):
                    rows.insert(5, {'payload': {'type': 'ClientMessageType_CancelActionReq' if mode == 'cancel' else 'ClientMessageType_UndoReq'}})
                else:
                    broadcast = copy.deepcopy(rows[4]['greToClientEvent']['greToClientMessages'][1]); broadcast['systemSeatIds'] = [1, 2]
                    rows.insert(5, {'greToClientEvent': {'greToClientMessages': [broadcast]}})
                self.absent(self.replay_records(rows)['current_target_revision'])

    def test_synthetic_telemetry_preserves_pending_and_current_but_no_fresh_proof(self):
        rows = self.synthetic_records(); ui = {'payload': {'type': 'ClientMessageType_UIMessage'}}
        rows.insert(6, copy.deepcopy(ui)); rows.append(copy.deepcopy(ui))
        self.positive(self.replay_records(rows)['current_target_revision'])

    def test_synthetic_terminal_extra_fields_do_not_change_legacy_candidate_meaning(self):
        rows = self.synthetic_records(terminal=True); rows[-1]['payload']['extra'] = {'targets': []}
        document = self.replay_records(rows); self.absent(document['current_target_revision'])
        self.assertEqual(document['decision_state']['binding']['request_id'], 3)
        self.assertEqual(enumerate_known_candidates(document['decision_state'], version=3)['probe_coverage']['verified'], 1)
        reducer, stage = self.producer(self.synthetic_records(terminal=True))
        self.assertIsNone(reducer.request); self.assertTrue(stage.revision.client_submit_observed)
        self.assertIsNone(stage.revision.active)

    def test_no_request_stopped_old_version_and_malformed_refs_abstain(self):
        state = copy.deepcopy(self.fixture['revised_child_consumed']); _state(state, state['binding'])
        state[revision.FIELD] = copy.deepcopy(self.state[revision.FIELD])
        with self.assertRaises(ValueError): _state(state, state['binding'])
        self.absent(self.report(state))
        state = copy.deepcopy(self.state); state['source']['stopped'] = True; self.absent(self.report(state))
        state = copy.deepcopy(self.state); state['schema_version'] = 'mtgaplayer.decision-state.v13'
        with self.assertRaises(ValueError): _state(state, state['binding'])
        self.absent(self.report(state))
        for ref in ({'not': 'a snapshot ref'}, {'session_id': 'x', 'sequence': 1, 'binding': self.fixture['first_child']['binding']}):
            result = self.report(source_snapshot_ref=ref); self.absent(result); self.assertIsNone(result['source_snapshot_ref'])

    def test_consumer_current_ref_history_lease_close_partial_and_race(self):
        _, consumer, clock, _, _, _ = self.transport(); self.positive(revision.assess_current_revision(consumer))
        clock.advance(501); self.absent(revision.assess_current_revision(consumer))
        _, consumer, _, _, _, _ = self.transport(history=True); self.absent(revision.assess_current_revision(consumer))
        _, consumer, _, _, _, events = self.transport(); consumer.close()
        self.absent(revision.assess_current_revision(consumer)); self.assertFalse(consumer.accept_event(events[0]))
        publisher, consumer, _, document, metadata, _ = self.transport()
        document['decision_state'] = None; document['source']['partial_record'] = True
        for event in publisher.observe(document, metadata): self.assertTrue(consumer.accept_event(event))
        self.absent(revision.assess_current_revision(consumer))
        _, consumer, clock, _, _, _ = self.transport(); original = revision.evaluate_revision
        def late(*args, **kwargs):
            result = original(*args, **kwargs); clock.advance(501); return result
        with patch.object(revision, 'evaluate_revision', side_effect=late): self.absent(revision.assess_current_revision(consumer))
        self.absent(revision.assess_current_revision(consumer.current_view()))

    def test_synthetic_stream_owner_thread_and_final_output_recheck(self):
        publisher, _, clock, _, _, events = self.transport(); events += publisher.stop()
        output = []; threads = []; owner = threading.get_ident(); original = revision.evaluate_revision
        def record(*args, **kwargs):
            threads.append(threading.get_ident()); return original(*args, **kwargs)
        with patch.object(revision, 'evaluate_revision', side_effect=record):
            self.assertEqual(consume_events(io.StringIO(''.join(json.dumps(e)+'\n' for e in events)), output.append,
                DecisionConsumer(10000, 500, clock), current_target_revision=True), 0)
        self.assertTrue(threads); self.assertEqual(set(threads), {owner})
        self.assertTrue(any(o['current_target_revision']['current_revised_child_verified'] for o in output))
        self.absent(output[-1]['current_target_revision'])
        publisher, _, clock, _, _, events = self.transport(); events += publisher.stop(); output = []
        original_assess = revision.assess_current_revision
        def expire(*args, **kwargs):
            result = original_assess(*args, **kwargs)
            if result['current_revised_child_verified']: clock.advance(501)
            return result
        with patch.object(revision, 'assess_current_revision', side_effect=expire):
            consume_events(io.StringIO(''.join(json.dumps(e)+'\n' for e in events)), output.append,
                DecisionConsumer(10000, 500, clock), current_target_revision=True)
        self.assertTrue(output)
        for row in output: self.absent(row['current_target_revision'])

    def test_synthetic_watch_publisher_consumer_rebinds_each_current_stage(self):
        rows = self.synthetic_records(terminal=True)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'synthetic-watch.jsonl'
            path.write_text(''.join(json.dumps(r)+'\n' for r in rows[:3]), encoding='utf-8')
            clock = ManualClock(); consumer = DecisionConsumer(10000, 500, clock)
            stream = watch_decision_events(path, interval=0, samples=5, decision_state_version=14,
                                          clock_ns=clock, session_id='synthetic-watch-mp63')
            self.addCleanup(stream.close)
            for event in poll_events(stream): self.assertTrue(consumer.accept_event(event))
            self.absent(revision.assess_current_revision(consumer))
            refs = []
            for suffix, positive in ((rows[3:5], False), (rows[5:6], False), (rows[6:7], True), (rows[7:8], False)):
                append(path, suffix)
                for event in poll_events(stream): self.assertTrue(consumer.accept_event(event))
                result = revision.assess_current_revision(consumer)
                if positive: self.positive(result)
                else: self.absent(result)
                view = consumer.current_view()
                if view['current_snapshot_ref'] is not None: refs.append(copy.deepcopy(view['current_snapshot_ref']))
            self.assertNotEqual(refs[0]['binding']['request_id'], refs[-2]['binding']['request_id'])
            self.assertIsNone(consumer.current_view()['decision_state']['binding']['request_id'])

    def test_revision_duplicate_diff_cannot_revive_pending(self):
        rows = self.synthetic_records(); combined = rows.pop()['greToClientEvent']['greToClientMessages']
        diff = {'greToClientEvent': {'greToClientMessages': [combined[0]]}}
        child = {'greToClientEvent': {'greToClientMessages': [combined[1]]}}
        reducer, stage = self.producer(rows + [copy.deepcopy(diff), copy.deepcopy(diff), child])
        self.assertIsNone(reducer.error); self.assertEqual(reducer.request['id'], 3)
        self.assertIsNone(stage.revision.active); self.assertNotIn(revision.PRIVATE, reducer.request)
        _, control = self.producer(rows + [diff, child])
        self.assertIsNotNone(control.revision.active)

    def test_revision_pending_partial_poll_cannot_revive_on_completion(self):
        rows = self.synthetic_records()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'synthetic-partial.jsonl'
            path.write_text(''.join(json.dumps(r)+'\n' for r in rows[:6]), encoding='utf-8')
            stream = watch(path, interval=0, samples=4, decision_state_version=14)
            self.addCleanup(stream.close)
            self.assertIsNone(next(stream)['decision_state']['binding']['request_id'])
            tail = (json.dumps(rows[6])+'\n').encode()
            with path.open('ab') as out: out.write(tail[:20])
            self.assertEqual(next(stream)['error'], 'partial_raw_record_waiting')
            with path.open('ab') as out: out.write(tail[20:])
            after = next(stream)
            self.assertIsNone(after['error']); self.assertEqual(after['decision_state']['binding']['request_id'], 3)
            self.assertIsNone(after['decision_state'][revision.FIELD])
            self.absent(revision.evaluate_revision(after['decision_state']))
            next(stream)

    def test_revision_typed_predecessor_refuses_same_value_float(self):
        rows = self.synthetic_records()
        rows[6]['greToClientEvent']['greToClientMessages'][0]['gameStateMessage']['prevGameStateId'] = 11.0
        reducer, stage = self.producer(rows)
        self.assertIsNone(reducer.error); self.assertEqual(reducer.request['id'], 3)
        self.assertIsNone(stage.revision.active); self.assertNotIn(revision.PRIVATE, reducer.request)
        _, control = self.producer(self.synthetic_records())
        self.assertIsNotNone(control.revision.active)

    def test_revision_first_predecessor_typed_without_changing_old_observer(self):
        rows = self.synthetic_records()
        rows[4]['greToClientEvent']['greToClientMessages'][0]['gameStateMessage']['prevGameStateId'] = 10.0
        reducer, stage = self.producer(rows[:5])
        self.assertIsNone(reducer.error); self.assertEqual(reducer.request['id'], 2)
        self.assertIsNone(stage.active); self.assertNotIn(first.PRIVATE, reducer.request)
        for row in rows[5:]: stage.prepare(row); reducer.apply(row); stage.after_apply()
        self.assertEqual(reducer.request['id'], 3); self.assertIsNone(stage.revision.active)
        self.assertNotIn(revision.PRIVATE, reducer.request)
        old, _ = self.producer([]); old_stage = first.StageObserver(old)
        old.observer = old_stage.observe; old_stage.reset()
        for row in rows[:5]: old_stage.prepare(row); old.apply(row); old_stage.after_apply()
        self.assertIsNone(old.error); self.assertIsNotNone(old_stage.active)
        _, control = self.producer(self.synthetic_records())
        self.assertIsNotNone(control.revision.active)

    def test_synthetic_replay_cli_opt_in_and_old_version_gate(self):
        rows = self.synthetic_records()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'synthetic-cli.jsonl'; path.write_text(''.join(json.dumps(r)+'\n' for r in rows), encoding='utf-8')
            result = subprocess.run([sys.executable, '-m', 'mtgaplayer', 'replay', str(path), '--format', 'player-log',
                '--decision-state-version', '14', '--current-choice-continuation', '--current-target-revision'],
                capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr); self.positive(json.loads(result.stdout)['current_target_revision'])
            with self.assertRaisesRegex(ValueError, 'current_target_revision_requires_player_log_state14'):
                replay(path, format='player-log', decision_state_version=13, current_target_revision=True)
            self.assertNotIn('current_target_revision', replay(path, format='player-log'))


if __name__ == '__main__':
    unittest.main()
