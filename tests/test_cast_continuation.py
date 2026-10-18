"""Retained scrubbed-real Cast trace; all mutations/clocks/transport are synthetic.

The source is the existing public fixture, not authenticated private log bytes.
Initial proofs use only prefixes, before parsing the next real response.
"""
import copy
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from mtgaplayer import cast_continuation as continuation
from mtgaplayer.choice_candidates import enumerate_known_candidates
from mtgaplayer.choice_continuation import StageObserver
from mtgaplayer.cli import replay, watch
from mtgaplayer.decision_consumer import DecisionConsumer, EXECUTION, _state, consume_events
from mtgaplayer.decision_publisher import DecisionPublisher
from mtgaplayer.raw_log import RawReducer
from test_decision_publisher import ManualClock

FIXTURE = Path(__file__).parent / 'fixtures/player_log_single_target.jsonl'
GOOD = 'continuation_relationship_consistent'


class CastContinuationTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / 'source.jsonl'
        self.lines = FIXTURE.read_bytes().replace(b'\r\n', b'\n').splitlines(keepends=True)

    def rows(self, cutoff=106):
        return [json.loads(line) for line in self.lines[:cutoff]]

    def document(self, cutoff=106, *, rows=None, version=15):
        self.path.write_bytes(b''.join(self.lines[:cutoff]) if rows is None else
            ''.join(json.dumps(row) + '\n' for row in rows).encode('utf-8'))
        return replay(self.path, format='player-log', decision_state=True, decision_state_version=version,
                      current_cast_continuation=version == 15)

    def report(self, rows):
        return self.document(rows=rows)['current_cast_continuation']

    def positive(self, result):
        self.assertEqual(result['status'], GOOD)
        for key in ('historical_selected_parent_observed', 'current_child_request_verified',
                    'engine_offered', 'known_constraints_verified'):
            self.assertIs(result[key], True, key)
        self.assertEqual(len(result['candidates']), 4)
        self.denials(result)

    def denials(self, result):
        self.assertIs(result['read_only'], True)
        for key in (*continuation.DENIALS, *EXECUTION): self.assertIs(result[key], False, key)

    def absent(self, result):
        self.assertEqual(result['status'], 'insufficient_evidence')
        self.assertEqual(result['candidates'], [])
        self.assertIs(result['known_constraints_verified'], False)
        self.denials(result)

    def transport(self, state=None, *, history=False):
        # Invented local clock/session/append observation, not new gameplay.
        state = copy.deepcopy(state or self.document()['decision_state'])
        clock = ManualClock(); publisher = DecisionPublisher(clock_ns=clock,
            session_id='synthetic-mp64', state_version=15)
        state['source'].update(mode='watch', phase='history' if history else 'append', stopped=False)
        document = {'decision_state': state, 'source': {'phase': state['source']['phase'], 'partial_record': False}}
        metadata = {'poll_started_ns': clock(), 'poll_completed_ns': clock(), 'poll_read_ns': 0,
            'reducer_apply_ns': 0, 'decision_state_assembly_ns': 0, 'request_changed': True, 'new_final_request': True}
        events = publisher.observe(document, metadata)
        consumer = DecisionConsumer(10000, 500, clock)
        for event in events: self.assertTrue(consumer.accept_event(event))
        return publisher, consumer, clock, events

    def test_retained_source_fingerprints_parent_freeze_then_first_child(self):
        data = b''.join(self.lines)
        self.assertEqual((len(self.lines), len(data)), (113, 68174))
        self.assertEqual(hashlib.sha256(data).hexdigest(), '723b6c4ba89a02874044afb1006ad7cf1507997cbc55436b6dc5ee75067a5b81')
        prefix = b''.join(self.lines[:103]); self.assertEqual(len(prefix), 60858)
        self.assertEqual(hashlib.sha256(prefix).hexdigest(), '1616b632532286f5437c4675c814a25a6a902b40e0de67c19308b37cafaf0c9d')
        parent = self.document(103)['decision_state']; frozen = copy.deepcopy(parent)
        self.assertEqual(parent['binding']['request_id'], 10100)
        report = enumerate_known_candidates(parent, version=5)
        self.assertEqual(report['engine_active_action_rows'], 8)
        self.assertEqual(report['returned_candidates'], 8)
        self.assertEqual(report['target_quantities'], {'minimum': None, 'maximum': None, 'selected_count': None})
        self.assertIsNone(parent[continuation.FIELD])
        child = self.document()['decision_state']; self.positive(continuation.evaluate_continuation(child))
        self.assertEqual(parent, frozen)
        proof = child[continuation.FIELD]; p = proof['parent']
        self.assertEqual((p['list_position'], p['active_action_count'], p['inactive_action_count']), (3, 8, 2))
        self.assertEqual(p['action']['identifier_refs'], {'instanceId': 1255, 'grpId': 97320, 'facetId': 294})
        self.assertIs(p['current'], False)
        self.assertEqual(proof['transfer']['stack_object_ref'], 1264)
        self.assertEqual(child['binding']['request_id'], 10102)
        self.assertIsNone(child['choice_continuation'])
        self.assertTrue(any(m['instance_id'] == 1264 and m['object_type'] == 'GameObjectType_Card'
                            for m in child['game']['stack']['members']))

    def test_actual_child_freeze_then_select_revision_terminal_and_no_revival(self):
        child = self.document(); frozen = copy.deepcopy(child)
        self.positive(child['current_cast_continuation'])
        for cutoff in (104, 105, 107, 108, 109, 110, 111, 112, 113):
            with self.subTest(cutoff=cutoff):
                doc = self.document(cutoff); self.absent(doc['current_cast_continuation'])
                if cutoff in (104, 107, 110, 111, 112, 113):
                    self.assertIsNone(doc['decision_state']['binding']['request_id'])
                if cutoff == 109:
                    state = doc['decision_state']; self.assertEqual(state['binding']['request_id'], 10104)
                    t = state['legal_action_space']['request_parameters']['targets']
                    self.assertEqual((t['min_targets'], t['max_targets'], t['selected_count']), (1, 1, 1))
                    self.assertEqual(t['entries'], [{'object_ref': 1262, 'legal_action': 'SelectAction_Unselect'}])
        self.assertEqual(child, frozen)

    def test_four_existing_singleton_validations_keep_current_child_binding(self):
        state = self.document()['decision_state']; result = continuation.evaluate_continuation(state)
        from mtgaplayer.choice_validation import validate_proposed_choice
        self.assertEqual([c['proposed_final_target_set']['object_refs'] for c in result['candidates']], [[1243], [1247], [1257], [1262]])
        for proposal in result['candidates']:
            self.assertEqual(proposal['request_identity'], state['binding'])
            self.assertEqual(validate_proposed_choice(state, proposal)['known_constraints'], 'verified_known_constraints')
        for refs in ([], [999999], [1243, 1247], [1243, 1243]):
            bad = copy.deepcopy(result['candidates'][0]); bad['proposed_final_target_set']['object_refs'] = refs
            self.assertEqual(validate_proposed_choice(state, bad)['known_constraints'], 'violated_known_constraints')

    def test_actual_trace_single_watch_publisher_consumer_and_jsonl_adapter(self):
        self.path.write_bytes(b''.join(self.lines[:102]))
        clock = ManualClock(); publisher = DecisionPublisher(clock_ns=clock, session_id='synthetic-watch-mp64', state_version=15)
        consumer = DecisionConsumer(10000, 500, clock); metadata = {}; events = []
        stream = watch(self.path, interval=0, samples=10, decision_state_version=15,
            _clock_ns=clock, _poll_observer=lambda facts: metadata.update(facts))
        stale_refs = []
        for index, cutoff in enumerate((102, 103, 104, 105, 106, 107, 109, 110, 113, 113)):
            if index:
                self.path.write_bytes(b''.join(self.lines[:cutoff]))
            document = next(stream)
            batch = publisher.observe(document, metadata); events.extend(batch)
            for event in batch: self.assertTrue(consumer.accept_event(event))
            report = continuation.assess_current_continuation(consumer)
            if cutoff == 106:
                self.positive(report); ref = copy.deepcopy(report['source_snapshot_ref']); stale_refs.append(ref)
                self.assertTrue(all(c['source_snapshot_ref'] == ref for c in report['candidates']))
            else:
                self.absent(report)
                if cutoff > 106:
                    self.assertTrue(all(consumer.current_view()['current_snapshot_ref'] != ref for ref in stale_refs))
            if cutoff in (104, 107, 110): self.assertIsNone(consumer.current_view()['decision_state']['binding']['request_id'])
        events.extend(publisher.stop('sample_limit'))
        emitted = []; data = ''.join(json.dumps(e) + '\n' for e in events).encode('utf-8')
        code = consume_events(io.BytesIO(data), emitted.append, DecisionConsumer(10000, 500, clock), current_cast_continuation=True)
        self.assertEqual(code, 0)
        self.assertTrue(any(row['current_cast_continuation']['status'] == GOOD for row in emitted))
        self.absent(emitted[-1]['current_cast_continuation'])

    def test_synthetic_response_identity_and_full_row_ambiguity_refusals(self):
        for mode in ('id', 'state', 'row', 'same_value_float', 'duplicate_response', 'duplicate_offer', 'identity_alias', 'unchosen_cast'):
            with self.subTest(mode=mode):
                rows = self.rows(); response = rows[103]['payload']; actions = rows[102]['greToClientEvent']['greToClientMessages'][0]['actionsAvailableReq']['actions']
                if mode == 'id': response['respId'] += 1
                elif mode == 'state': response['gameStateId'] -= 1
                elif mode == 'row': response['performActionResp']['actions'][0]['shouldStop'] = False
                elif mode == 'same_value_float': response['performActionResp']['actions'][0]['facetId'] = 294.0
                elif mode == 'duplicate_response': rows.insert(104, copy.deepcopy(rows[103]))
                elif mode == 'duplicate_offer': actions.append(copy.deepcopy(actions[3]))
                elif mode == 'identity_alias':
                    other = copy.deepcopy(actions[3]); other['shouldStop'] = False; actions.append(other)
                else: response['performActionResp']['actions'] = [copy.deepcopy(actions[1])]
                self.absent(self.report(rows))

    def test_synthetic_transfer_controls_are_not_just_target_validator_failures(self):
        for mode in ('missing_oid', 'missing_transfer', 'duplicate_oid', 'old_id', 'wrong_category', 'wrong_source_zone', 'card_identity', 'ability_kind', 'preexisting_stack_object'):
            with self.subTest(mode=mode):
                rows = self.rows(); gs = rows[104]['greToClientEvent']['greToClientMessages'][0]['gameStateMessage']
                if mode == 'missing_oid': gs['annotations'].pop(0)
                elif mode == 'missing_transfer': gs['annotations'].pop(1)
                elif mode == 'duplicate_oid': gs['annotations'].append(copy.deepcopy(gs['annotations'][0]))
                elif mode == 'old_id': gs['annotations'][0]['details'][0]['valueInt32'] = [1066]
                elif mode == 'wrong_category': gs['annotations'][1]['details'][2]['valueString'] = ['Resolve']
                elif mode == 'wrong_source_zone': gs['annotations'][1]['details'][0]['valueInt32'] = [108]
                elif mode == 'card_identity': gs['gameObjects'][1]['grpId'] += 1
                elif mode == 'ability_kind': gs['gameObjects'][1]['type'] = 'GameObjectType_Ability'
                else:
                    prior = rows[101]['greToClientEvent']['greToClientMessages'][0]['gameStateMessage']
                    prior.setdefault('gameObjects', []).append({'instanceId':1264,'type':'GameObjectType_Card','zoneId':108,'visibility':'Visibility_Private','ownerSeatId':2,'controllerSeatId':2})
                doc = self.document(rows=rows)
                self.assertIsNone(doc['error'])
                self.assertEqual(len(enumerate_known_candidates(doc['decision_state'], version=2)['candidates']), 4)
                self.absent(doc['current_cast_continuation'])

    def test_synthetic_child_members_order_source_count_and_recipient(self):
        for mode in ('order', 'missing', 'foreign', 'duplicate', 'source', 'slot', 'selected', 'bounds', 'recipient', 'float_slot'):
            with self.subTest(mode=mode):
                rows = self.rows(); message = rows[105]['greToClientEvent']['greToClientMessages'][0]
                slot = message['selectTargetsReq']['targets'][0]
                if mode == 'order': slot['targets'].reverse()
                elif mode == 'missing': slot['targets'].pop()
                elif mode == 'foreign': slot['targets'][0]['targetInstanceId'] = 999999
                elif mode == 'duplicate': slot['targets'][0] = copy.deepcopy(slot['targets'][1])
                elif mode == 'source': message['selectTargetsReq']['sourceId'] = 1255
                elif mode == 'slot': slot['targetIdx'] = 2
                elif mode == 'selected': slot['selectedTargets'] = 0
                elif mode == 'bounds': slot['maxTargets'] = 2
                elif mode == 'recipient': message['systemSeatIds'] = [1]
                else: slot['targetIdx'] = 1.0
                doc = self.document(rows=rows); self.absent(doc['current_cast_continuation'])
                if mode in ('order', 'missing', 'slot', 'selected', 'bounds'):
                    self.assertIsNone(doc['error']); self.assertIsNotNone(doc['decision_state'])

    def test_synthetic_mixed_record_cannot_rearm_in_later_callbacks(self):
        for at in (103, 104, 105):
            for extra in ('payload', 'authenticateResponse', 'matchGameRoomStateChangedEvent'):
                with self.subTest(at=at, extra=extra):
                    rows = self.rows()
                    if extra == 'payload': rows[at][extra] = {'type':'ClientMessageType_UIMessage'}
                    else: rows[at][extra] = copy.deepcopy(rows[0 if extra == 'authenticateResponse' else 1][extra])
                    self.absent(self.report(rows))

    def test_synthetic_retransmission_cancel_undo_full_gap_and_partial(self):
        rows = self.rows()
        for record in (rows[102], rows[103], rows[104], rows[105]):
            index = next(i for i, r in enumerate(rows) if r is record)
            with self.subTest(duplicate_record=index+1):
                mutated = copy.deepcopy(rows); mutated.insert(index+1, copy.deepcopy(record)); self.absent(self.report(mutated))
        for typ in ('CancelActionReq', 'UndoReq', 'UnsupportedReq'):
            mutated = copy.deepcopy(rows); mutated.insert(105, {'payload':{'type':'ClientMessageType_'+typ}})
            self.absent(self.report(mutated))
        bad = copy.deepcopy(rows); bad[104]['greToClientEvent']['greToClientMessages'][0]['gameStateMessage']['prevGameStateId'] = 99
        self.absent(self.report(bad))
        self.document(); self.path.write_bytes(self.path.read_bytes()+b'{"payload":')
        self.absent(replay(self.path,format='player-log',decision_state_version=15,current_cast_continuation=True)['current_cast_continuation'])
        self.path.write_bytes(b''.join(self.lines[3:106])); self.absent(replay(self.path,format='player-log',decision_state_version=15,current_cast_continuation=True)['current_cast_continuation'])

    def test_synthetic_reset_and_pending_bound(self):
        r = RawReducer(include_request_parameters=True, include_cast_target_members=True, include_state_messages=True)
        stage = StageObserver(r, include_cast=True); r.observer = stage.observe; r.reset(1); stage.reset()
        for row in self.rows()[:104]: stage.prepare(row); r.apply(row); stage.after_apply()
        self.assertIsNotNone(stage.cast.pending)
        for _ in range(65): stage.prepare({}); r.apply({}); stage.after_apply()
        self.assertIsNone(stage.cast.pending)
        stage.reset(); r.reset(2)
        for row in self.rows(): stage.prepare(row); r.apply(row); stage.after_apply()
        self.assertIsNotNone(stage.cast.active)
        stage.reset(); self.assertIsNone(stage.cast.active); self.assertNotIn(continuation.PRIVATE, r.request)

    def test_synthetic_accepted_full_recovery_with_valid_four_targets_has_no_lineage(self):
        rows = self.rows(); r = RawReducer(); r.reset(1)
        for row in rows[:105]: r.apply(row)
        full = {'type':'GameStateType_Full','gameStateId':101,'gameInfo':copy.deepcopy(r.game_info),
            'gameObjects':list(copy.deepcopy(r.objects).values()),'zones':list(copy.deepcopy(r.zones).values()),
            'players':list(copy.deepcopy(r.players).values()),'turnInfo':copy.deepcopy(r.turn)}
        rows[104]['greToClientEvent']['greToClientMessages'][0]['gameStateMessage'] = full
        doc = self.document(rows=rows)
        self.assertIsNone(doc['error']); self.assertEqual(doc['decision_state']['binding']['request_id'],10102)
        self.assertEqual(enumerate_known_candidates(doc['decision_state'],version=2)['returned_candidates'],4)
        self.absent(doc['current_cast_continuation'])

    def test_synthetic_partial_pending_poll_then_completion_cannot_restore_lineage(self):
        self.path.write_bytes(b''.join(self.lines[:104]))
        stream = watch(self.path,interval=0,samples=4,decision_state_version=15)
        next(stream)
        with self.path.open('ab') as out: out.write(self.lines[104][:20])
        partial = next(stream); self.assertEqual(partial['error'],'partial_raw_record_waiting')
        with self.path.open('ab') as out: out.write(self.lines[104][20:]+self.lines[105])
        completed = next(stream)
        self.assertIsNone(completed['error']); self.assertEqual(completed['decision_state']['binding']['request_id'],10102)
        self.assertEqual(enumerate_known_candidates(completed['decision_state'],version=2)['returned_candidates'],4)
        self.absent(continuation.evaluate_continuation(completed['decision_state']))
        next(stream)

    def test_synthetic_portable_forgery_rejected_without_mutation(self):
        state = self.document()['decision_state']; original = copy.deepcopy(state)
        for path, value in ((('binding','source_generation'),True), (('parent','binding','match'),'other'),
            (('parent','current'),True), (('parent','list_position'),8), (('parent','active_action_count'),True),
            (('transfer','stack_object_ref'),1255), (('transfer','observed_state_id'),100),
            (('child_message','msgId'),10100), (('child_message','systemSeatIds'),[1])):
            bad = copy.deepcopy(state); cursor = bad[continuation.FIELD]
            for key in path[:-1]: cursor = cursor[key]
            cursor[path[-1]] = value
            with self.subTest(path=path):
                self.absent(continuation.evaluate_continuation(bad))
                with self.assertRaises(ValueError): _state(bad,bad['binding'])
        self.assertEqual(state,original)

    def test_synthetic_current_ref_lease_history_stop_and_race(self):
        publisher,consumer,clock,_ = self.transport(); result = continuation.assess_current_continuation(consumer); self.positive(result)
        old = result['source_snapshot_ref']; clock.advance(600)
        self.absent(continuation.assess_current_continuation(consumer)); self.assertNotEqual(consumer.current_view()['current_snapshot_ref'],old)
        _,consumer,_,_ = self.transport(history=True); self.absent(continuation.assess_current_continuation(consumer))
        publisher,consumer,_,_ = self.transport()
        for event in publisher.stop('sample_limit'): consumer.accept_event(event)
        self.absent(continuation.assess_current_continuation(consumer))
        _,consumer,clock,_ = self.transport(); evaluate = continuation.evaluate_continuation
        def slow(*args,**kwargs):
            value = evaluate(*args,**kwargs); clock.advance(600); return value
        with patch.object(continuation,'evaluate_continuation',slow): self.absent(continuation.assess_current_continuation(consumer))
        state = self.document()['decision_state']; wrong = copy.deepcopy(old); wrong['binding']['request_id'] = 10100
        self.absent(continuation.evaluate_continuation(state,source_snapshot_ref=wrong))

    def test_cli_explicit_version_and_old_contract_isolation(self):
        self.document()
        run = subprocess.run([sys.executable,'-m','mtgaplayer','replay',str(self.path),'--format','player-log',
            '--decision-state-version','15','--current-cast-continuation'],capture_output=True,text=True,encoding='utf-8',timeout=8)
        self.assertEqual(run.returncode,0,run.stderr); self.positive(json.loads(run.stdout)['current_cast_continuation'])
        for version in (1,5,11,12,13,14):
            doc = self.document(version=version); self.assertNotIn(continuation.FIELD,doc['decision_state']); self.assertNotIn('current_cast_continuation',doc)
        with self.assertRaises(ValueError): replay(self.path,format='player-log',decision_state_version=13,current_cast_continuation=True)
        with self.assertRaises(ValueError): consume_events(io.BytesIO(),lambda _:None,current_cast_continuation=1)
        with self.assertRaises(ValueError): replay(self.path,format='player-log',decision_state_version=14,current_cast_continuation=True)
