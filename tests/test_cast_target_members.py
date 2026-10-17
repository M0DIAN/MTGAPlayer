"""Retained real prefix positives; every mutation/transport clock is synthetic."""
import copy
import hashlib
import io
import json
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from mtgaplayer.raw_log import RawFollower, RawReducer
from mtgaplayer.cli import _project_decision_state
from mtgaplayer.cli import watch
from mtgaplayer.cast_target_members import DENIALS, PROFILE, GOOD, VERSION
from mtgaplayer.choice_candidates import enumerate_known_candidates, assess_current_known_candidates
from mtgaplayer.choice_validation import validate_proposed_choice
from mtgaplayer.decision_consumer import DecisionConsumer, EXECUTION, _state, consume_events
from mtgaplayer.decision_publisher import DecisionPublisher
from test_decision_publisher import ManualClock

FIXTURE = Path(__file__).parent/'fixtures/player_log_single_target.jsonl'


class CastTargetMemberTests(unittest.TestCase):
    def setUp(self):
        follower = RawFollower(FIXTURE); _, self.records = follower.poll()
        self.assertEqual(len(self.records), 113)
        self.assertEqual(follower.framer.errors, 0); self.assertFalse(follower.framer.partial)

    def build(self, mutate=None, end=103):
        reducer = RawReducer(include_request_parameters=True, include_cast_target_members=True)
        reducer.reset(1)
        for row in self.records[:102]: reducer.apply(row)
        request = copy.deepcopy(self.records[102])
        if mutate: mutate(reducer, request['greToClientEvent']['greToClientMessages'][0]['actionsAvailableReq']['actions'])
        reducer.apply(request)
        for row in self.records[103:end]: reducer.apply(row)
        return reducer, self.project(reducer)

    def project(self, reducer):
        doc = reducer.document(include_frontier_rows=True, include_decision_state=True)
        doc['source'] = {'format': 'player-log-gre-v1', 'generation': 1, 'byte_offset': None,
            'partial_record': False, 'mode': 'offline', 'input_sent': False, 'executor_connected': False}
        _project_decision_state(reducer, doc, None, False, 11)
        return doc['decision_state']

    def report(self, state, **kwargs):
        return enumerate_known_candidates(state, version=5, **kwargs)

    def readonly(self, result):
        self.assertTrue(all(result[k] is False for k in (*DENIALS, *EXECUTION)))
        self.assertEqual(result['target_quantities'], dict(minimum=None, maximum=None, selected_count=None))
        self.assertEqual(result['payment_source_readiness'], 'unknown_not_evaluated')

    def test_real_prefix_authenticated_before_any_response(self):
        self.assertEqual(hashlib.sha256(FIXTURE.read_bytes().replace(b'\r\n', b'\n')).hexdigest(),
                         '723b6c4ba89a02874044afb1006ad7cf1507997cbc55436b6dc5ee75067a5b81')
        reducer, state = self.build(); before = copy.deepcopy(state); _state(state, state['binding'])
        self.assertIsNone(reducer.document()['first_error']); self.assertIsNone(reducer.document()['error'])
        self.assertEqual(state['binding']['request_id'], 10100); self.assertEqual(state['binding']['self_seat'], 2)
        result = self.report(state); self.assertEqual(state, before)
        self.assertEqual(result['schema_version'], VERSION); self.assertEqual(result['engine_active_action_rows'], 8)
        self.assertEqual(result['reviewed_cast_rows'], 2); self.assertEqual(result['unknown_or_unreviewed_action_rows'], 6)
        self.assertEqual(result['member_probes'], dict(observed=8, examined=8, verified=8, unknown=0,
            contradicted=0, unexamined=0, returned=8, omitted_due_to_return_limit=0))
        self.assertEqual([c['proposal']['list_position'] for c in result['candidates']], [1]*4+[3]*4)
        self.assertEqual([c['proposal']['proposed_cast_target_member']['object_ref'] for c in result['candidates']],
                         [1243, 1247, 1257, 1262]*2)
        self.assertTrue(all(c['payment_witness']['list_position'] == 5 for c in result['candidates']))
        self.assertTrue(all(c['payment_witness']['current_tapped_literal'] is None for c in result['candidates']))
        self.readonly(result)

    def test_discovery_limit_counts_probes_before_return_limit(self):
        _, state = self.build(); result = self.report(state, limit=3)
        self.assertEqual(result['returned_candidates'], 3); self.assertEqual(result['member_probes']['verified'], 8)
        self.assertEqual(result['member_probes']['omitted_due_to_return_limit'], 5); self.assertTrue(result['truncated'])

    def test_synthetic_member_identity_slot_flags_and_snapshot_controls(self):
        _, state = self.build(); proposal = self.report(state)['candidates'][0]['proposal']
        self.assertEqual(validate_proposed_choice(state, proposal)['known_constraints'], GOOD)
        for mutate in (lambda p: p.update(list_position=3), lambda p: p.update(list_position=2),
                       lambda p: p['proposed_cast_target_member']['identifier_refs'].update(facetId=999),
                       lambda p: p['proposed_cast_target_member']['flags'].update(shouldStop=False),
                       lambda p: p['proposed_cast_target_member'].update(target_idx=2),
                       lambda p: p['proposed_cast_target_member'].update(object_ref=1256),
                       lambda p: p['request_identity'].update(game=2),
                       lambda p: p['proposed_cast_target_member'].update(maxTargets=1)):
            with self.subTest(mutate=mutate):
                bad = copy.deepcopy(proposal); mutate(bad)
                self.assertNotEqual(validate_proposed_choice(state, bad)['known_constraints'], GOOD)

    def test_synthetic_cast_literal_controls_are_per_row(self):
        mutations = (
            lambda a: a[1]['manaCost'][0].update(color=['ManaColor_Generic']),
            lambda a: a[1]['manaCost'][0].update(color=['ManaColor_Red']),
            lambda a: a[1]['manaCost'][0].update(count=2),
            lambda a: a[1]['targets'].append(copy.deepcopy(a[1]['targets'][0])),
            lambda a: a[1]['targets'][0].update(maxTargets=1),
            lambda a: a[1]['targets'][0].update(targetIdx=0),
            lambda a: a[1]['targets'][0]['targets'][0].update(targetInstanceId=0),
            lambda a: a[1].update(modes=[1]),
            lambda a: a[1]['targets'][0]['targets'].append(copy.deepcopy(a[1]['targets'][0]['targets'][0])),
            lambda a: a[1]['targets'][0]['targets'][0].update(targetInstanceId=1066),
            lambda a: a[1]['autoTapSolution']['autoTapActions'][0]['manaPaymentOption']['mana'][0].update(manaId=999),
            lambda a: a[1]['autoTapSolution']['autoTapActions'][0]['manaPaymentOption']['mana'][0].update(srcInstanceId=1247),
            lambda a: a[1]['autoTapSolution']['autoTapActions'][0]['manaPaymentOption']['mana'][0].update(abilityGrpId=999),
            lambda a: a.append(copy.deepcopy(a[1])))
        for index, mutate in enumerate(mutations):
            with self.subTest(control=index):
                _, state = self.build(lambda r, a: mutate(a)); result = self.report(state)
                positions = [c['proposal']['list_position'] for c in result['candidates']]
                self.assertNotIn(1, positions); self.assertIn(3, positions)

    def test_synthetic_visibility_membership_and_source_controls(self):
        def source(ref, **changes):
            return lambda r, a: r.objects[ref].update(changes)
        controls = (source(1066, ownerSeatId=1), source(1066, controllerSeatId=1),
            source(1066, zoneId=106), source(1066, viewers=[]), source(1066, visibility='Visibility_Hidden'),
            source(1066, type='GameObjectType_Token'),
            source(1256, visibility='Visibility_Private'), source(1256, ownerSeatId=1),
            source(1256, controllerSeatId=1), source(1256, isTapped=True), source(1256, type='GameObjectType_Token'),
            source(1243, visibility='Visibility_Private'),
            lambda r, a: r.zones[113].update(viewers=[]),
            lambda r, a: r.zones[106]['objectInstanceIds'].append(1256))
        for index, mutate in enumerate(controls):
            with self.subTest(control=index):
                _, state = self.build(mutate); result = self.report(state)
                self.assertLess(result['returned_candidates'], 8)

    def test_synthetic_mana_option_unit_identity_and_inactive_controls(self):
        mutations = (
            lambda a: a[5]['manaPaymentOptions'].append(copy.deepcopy(a[5]['manaPaymentOptions'][0])),
            lambda a: a[5]['manaSelections'].append(copy.deepcopy(a[5]['manaSelections'][0])),
            lambda a: a[5]['manaSelections'][0]['options'][0]['mana'][0].update(color='ManaColor_Red'),
            lambda a: a[5].pop('manaSelections'),
            lambda a: a[5]['manaPaymentOptions'][0]['mana'][0].update(manaId=999),
            lambda a: a[5].update(abilityGrpId=999),
            lambda a: a[5].update(instanceId=1247),
            lambda a: a[5]['manaPaymentOptions'][0]['mana'][0].update(count=2),
            lambda a: a[5]['manaPaymentOptions'][0]['mana'][0].update(specs=[{'type': 'ManaSpecType_Unknown'}]),
            lambda a: a[5].update(unknownParameter=True),
            lambda a: a.append(copy.deepcopy(a[5])),
            lambda a: a.pop(5))
        for index, mutate in enumerate(mutations):
            with self.subTest(control=index):
                _, state = self.build(lambda r, a: mutate(a)); self.assertEqual(self.report(state)['returned_candidates'], 0)

    def transport(self):
        reducer, state = self.build(); clock = ManualClock(); pub = DecisionPublisher(clock_ns=clock,
            session_id='synthetic-cast-transport', state_version=11)
        state['source'].update(mode='watch', phase='append', stopped=False)
        doc = {'decision_state': state, 'source': {'phase': 'append', 'partial_record': False}}
        meta = {'poll_started_ns': clock(), 'poll_completed_ns': clock(), 'poll_read_ns': 0, 'reducer_apply_ns': 0,
                'decision_state_assembly_ns': 0, 'request_changed': True, 'new_final_request': True}
        consumer = DecisionConsumer(10000, 500, clock); events = pub.observe(doc, meta)
        for event in events: self.assertTrue(consumer.accept_event(event))
        return reducer, clock, pub, consumer, doc, meta, events

    def test_real_response_consumes_same_poll_and_no_suffix_revives_old_request(self):
        reducer, clock, pub, con, doc, meta, events = self.transport()
        self.assertEqual(assess_current_known_candidates(con, version=5)['returned_candidates'], 8)
        ref = con.current_view()['current_snapshot_ref']
        for record in self.records[103:]:
            reducer.apply(record); state = self.project(reducer)
            if state: state['source'].update(mode='watch', phase='append', stopped=False)
            doc['decision_state'] = state
            for event in pub.observe(doc, meta): con.accept_event(event)
            result = assess_current_known_candidates(con, version=5)
            self.assertEqual(result['returned_candidates'], 0)
            self.assertNotEqual(con.current_view()['current_snapshot_ref'], ref)

    def test_real_watch_append_response_poll_and_synthetic_partial_digest_gates(self):
        lines = FIXTURE.read_bytes().splitlines(keepends=True)
        for control in ('actual_response', 'partial', 'digest_conflict', 'gap', 'seat', 'reset'):
            with self.subTest(control=control), tempfile.TemporaryDirectory() as folder:
                path = Path(folder)/'retained.jsonl'; path.write_bytes(b''.join(lines[:102]))
                meta = []; clock = ManualClock()
                pub = DecisionPublisher(clock_ns=clock, session_id='synthetic-watch-cast', state_version=11)
                con = DecisionConsumer(10000, 500, clock)
                stream = watch(path, interval=0, samples=4, decision_state_version=11,
                               _poll_observer=meta.append, _clock_ns=clock)
                def poll():
                    doc = next(stream)
                    for event in pub.observe(doc, meta[-1]): self.assertTrue(con.accept_event(event))
                    return assess_current_known_candidates(con, version=5)
                self.assertEqual(poll()['returned_candidates'], 0)
                with path.open('ab') as out: out.write(lines[102])
                report = poll(); self.assertEqual(report['returned_candidates'], 8)
                ref = report['source_snapshot_ref']
                if control == 'actual_response': extra = lines[103]
                elif control == 'partial': extra = b'{"greToClientEvent":'
                elif control == 'digest_conflict':
                    row = copy.deepcopy(self.records[102]); row['greToClientEvent']['greToClientMessages'][0]['actionsAvailableReq']['actions'][1]['shouldStop'] = False
                    extra = (json.dumps(row)+'\n').encode()
                elif control == 'gap':
                    extra = (json.dumps({'greToClientEvent': {'greToClientMessages': [{'type': 'GREMessageType_GameStateMessage',
                        'systemSeatIds': [2], 'gameStateMessage': {'type': 'GameStateType_Diff', 'gameStateId': 102,
                        'prevGameStateId': 101}}]}})+'\n').encode()
                elif control == 'seat':
                    row = copy.deepcopy(self.records[1]); row['matchGameRoomStateChangedEvent']['gameRoomInfo']['gameRoomConfig']['reservedPlayers'].reverse()
                    for player in row['matchGameRoomStateChangedEvent']['gameRoomInfo']['gameRoomConfig']['reservedPlayers']:
                        player['systemSeatId'] = 3-player['systemSeatId']
                    extra = (json.dumps(row)+'\n').encode()
                else:
                    path.write_bytes(lines[0]); extra = b''
                with path.open('ab') as out: out.write(extra)
                self.assertEqual(poll()['returned_candidates'], 0)
                self.assertNotEqual(con.current_view()['current_snapshot_ref'], ref)
                stream.close()

    def test_synthetic_consumer_history_lease_transport_and_post_calculation_gates(self):
        from mtgaplayer.cast_target_members import enumerate_members
        _, clock, _, con, _, _, _ = self.transport()
        def expire(*args, **kwargs):
            result = enumerate_members(*args, **kwargs); clock.advance(501); return result
        with patch('mtgaplayer.cast_target_members.enumerate_members', side_effect=expire):
            self.assertEqual(assess_current_known_candidates(con, version=5)['returned_candidates'], 0)
        for method in ('close',):
            _, _, _, con, _, _, _ = self.transport()
            getattr(con, method)(); self.assertEqual(assess_current_known_candidates(con, version=5)['returned_candidates'], 0)

    def test_synthetic_consumer_final_sidecar_expiry_keeps_version_five(self):
        _, clock, _, con, _, _, events = self.transport()
        reports = []
        def slow(*args, **kwargs):
            result = assess_current_known_candidates(*args, **kwargs); clock.advance(501); return result
        with patch('mtgaplayer.choice_candidates.assess_current_known_candidates', side_effect=slow):
            consume_events(io.StringIO(''.join(json.dumps(e)+'\n' for e in events)), reports.append, con,
                known_choice_candidates=True, known_choice_candidates_version=5)
        self.assertTrue(reports)
        for report in reports:
            candidate = report['known_choice_candidates']
            self.assertEqual(candidate['schema_version'], VERSION)
            self.assertEqual(candidate['returned_candidates'], 0)
            self.assertTrue(all(candidate[k] is False for k in EXECUTION))

    def test_synthetic_contract_and_authority_drift_controls(self):
        _, state = self.build()
        for mutate in (lambda s: s.update(schema_version='mtgaplayer.decision-state.v10'),
                       lambda s: s['legal_action_space']['request_parameters'].update(historical_response_used=True),
                       lambda s: s['legal_action_space']['request_parameters']['cast_actions'][0]['action']['flags'].update(shouldStop=1),
                       lambda s: s['legal_action_space']['choice_graph']['action_nodes'][1]['action_identity']['raw_flags_observed_not_discriminators'].update(should_stop=False)):
            bad = copy.deepcopy(state); mutate(bad); self.assertEqual(self.report(bad)['returned_candidates'], 0)
        original = validate_proposed_choice
        def drift(*args, **kwargs):
            result = original(*args, **kwargs); result['overall_payability_verified'] = True; return result
        with patch('mtgaplayer.choice_validation.validate_proposed_choice', side_effect=drift):
            self.assertEqual(self.report(state)['returned_candidates'], 0)

    def test_synthetic_graph_typed_identity_structure_and_validator_witness_drift(self):
        _, state = self.build()
        nodes = state['legal_action_space']['choice_graph']['action_nodes']
        for node_index in (1, 3, 5):
            for field in nodes[node_index]['action_identity']['raw_identifiers']:
                bad = copy.deepcopy(state)
                ids = bad['legal_action_space']['choice_graph']['action_nodes'][node_index]['action_identity']['raw_identifiers']
                ids[field] = float(ids[field])
                self.assertEqual(self.report(bad)['returned_candidates'], 0)
        bad = copy.deepcopy(state)
        constraint = next(c for c in bad['legal_action_space']['choice_graph']['action_nodes'][1]['constraints']
                          if c['parameter_category'] == 'targets')
        constraint['observed_structure'] = {'kind': 'object'}
        self.assertEqual(self.report(bad)['returned_candidates'], 0)
        original = validate_proposed_choice
        for mutate in (lambda v: v.update(payment_witness=None),
                       lambda v: v['payment_witness'].update(list_position=4),
                       lambda v: v['payment_witness']['identifier_refs'].update(instanceId=999),
                       lambda v: v['payment_witness']['flags'].update(isBatchable=1),
                       lambda v: v['payment_witness'].update(input_sent=True),
                       lambda v: v.update(complete_target_legality_verified=True)):
            def drift(*args, **kwargs):
                result = original(*args, **kwargs); mutate(result); return result
            with patch('mtgaplayer.choice_validation.validate_proposed_choice', side_effect=drift):
                self.assertEqual(self.report(state)['returned_candidates'], 0)
        _, _, _, con, _, _, _ = self.transport()
        ref = con.current_view()['current_snapshot_ref']
        def drift_ref(*args, **kwargs):
            result = original(*args, **kwargs); result['source_snapshot_ref']['binding']['source_generation'] = True
            return result
        with patch('mtgaplayer.choice_validation.validate_proposed_choice', side_effect=drift_ref):
            self.assertEqual(self.report(state, source_snapshot_ref=ref)['returned_candidates'], 0)
        _, other_color = self.build(lambda r, a: a[1]['manaCost'][0].update(color=['ManaColor_Generic']))
        self.assertEqual(self.report(other_color)['returned_candidates'], 4)
        def promote_unknown(*args, **kwargs):
            result = original(*args, **kwargs); result['known_constraints'] = GOOD; return result
        with patch('mtgaplayer.choice_validation.validate_proposed_choice', side_effect=promote_unknown):
            self.assertEqual(self.report(other_color)['returned_candidates'], 0)


if __name__ == '__main__': unittest.main()
