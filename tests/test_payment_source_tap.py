"""Real portable evidence plus explicitly synthetic source/transport controls."""
import copy
import io
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from mtgaplayer.payment_source_tap import TapObserver, FIELD, GOOD, VERSION, evaluate_witness, assess_current_witness
from mtgaplayer.activate_target_payment import evaluate_relation
from mtgaplayer.raw_log import RawReducer
from mtgaplayer.cli import _project_decision_state, replay
from mtgaplayer.decision_consumer import DecisionConsumer, EXECUTION, consume_events, _state
from mtgaplayer.decision_publisher import DecisionPublisher
from test_decision_publisher import ManualClock

FIXTURE = Path(__file__).parent/'fixtures/payment_source_untap_real_v10.json'


class PaymentSourceTapTests(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads(FIXTURE.read_text(encoding='utf-8'))
        self.state = self.fixture['before_response']

    def no_witness(self, result):
        self.assertEqual(result['schema_version'], VERSION)
        self.assertFalse(result['untapped_pre_request_witness_verified'])
        self.assertLess(result['verified_source_count'], 2)
        self.assertTrue(all(result[k] is False for k in EXECUTION))

    def transport(self, history=False):
        clock = ManualClock(); pub = DecisionPublisher(clock_ns=clock, session_id='synthetic-untap', state_version=10)
        state = copy.deepcopy(self.state)
        state['source'].update(mode='watch', phase='history' if history else 'append', stopped=False)
        doc = {'decision_state': state, 'source': {'phase': state['source']['phase'], 'partial_record': False}}
        meta = {'poll_started_ns': clock(), 'poll_completed_ns': clock(), 'poll_read_ns': 0, 'reducer_apply_ns': 0,
                'decision_state_assembly_ns': 0, 'request_changed': True, 'new_final_request': True}
        events = pub.observe(doc, meta); consumer = DecisionConsumer(10000, 500, clock)
        for event in events: self.assertTrue(consumer.accept_event(event))
        return pub, consumer, clock, doc, meta, events

    def synthetic_source(self, mode=None):
        """Small invented board/envelopes; literals taken from the public fixture."""
        from mtgaplayer.semantic_activate import raw_action
        params = self.state['legal_action_space']['request_parameters']
        records = params['target_actions']+params['mana_actions']
        actions = [raw_action(r['action']) for r in records]
        target = actions[0]['targets'][0]['targets'][0]['targetInstanceId']
        objects = []
        for action in actions:
            ids = action
            objects.append({'instanceId': ids['instanceId'], 'grpId': ids['grpId'], 'type': 'GameObjectType_Card',
                'zoneId': 11, 'ownerSeatId': 1, 'controllerSeatId': 1, 'visibility': 'Visibility_Public',
                'uniqueAbilities': [{'id': ids['uniqueAbilityId'], 'grpId': ids['abilityGrpId']}]})
        objects.append({'instanceId': target, 'grpId': 20077, 'type': 'GameObjectType_Card', 'zoneId': 11,
                        'ownerSeatId': 1, 'controllerSeatId': 1, 'visibility': 'Visibility_Public'})
        full = {'type': 'GameStateType_Full', 'gameStateId': 10,
            'gameInfo': {'matchID': 'synthetic-untap-source', 'gameNumber': 1, 'stage': 'GameStage_Play'},
            'players': [{'systemSeatNumber': i, 'lifeTotal': 20} for i in (1, 2)], 'gameObjects': objects,
            'zones': [{'zoneId': 11, 'type': 'ZoneType_Battlefield', 'visibility': 'Visibility_Public',
                       'objectInstanceIds': [o['instanceId'] for o in objects]},
                      {'zoneId': 12, 'type': 'ZoneType_Stack', 'visibility': 'Visibility_Public', 'objectInstanceIds': []},
                      {'zoneId': 13, 'type': 'ZoneType_Hand', 'ownerSeatId': 1, 'objectInstanceIds': []}]}
        sources = [a['instanceId'] for a in actions[1:]]
        def annotation(ref, value, ident):
            return {'id': ident, 'type': ['AnnotationType_TappedUntappedPermanent'], 'affectedIds': [ref],
                    'details': [{'key': 'tapped', 'type': 'KeyValuePairValueType_int32', 'valueInt32': [value]}]}
        tapped = {'type': 'GameStateType_Diff', 'gameStateId': 11, 'prevGameStateId': 10,
                  'gameObjects': [dict(o, isTapped=True) for o in objects if o['instanceId'] in sources],
                  'annotations': [annotation(ref, 1, i+1) for i, ref in enumerate(sources)]}
        untapped = {'type': 'GameStateType_Diff', 'gameStateId': 12, 'prevGameStateId': 11,
                    'gameObjects': [copy.deepcopy(o) for o in objects if o['instanceId'] in sources],
                    'annotations': [annotation(ref, 0, i+3) for i, ref in enumerate(sources)]}
        final = {'type': 'GameStateType_Diff', 'gameStateId': 13, 'prevGameStateId': 12}
        if mode == 'true_conflict': untapped['gameObjects'][0]['isTapped'] = True
        elif mode == 'duplicate': untapped['annotations'].append(copy.deepcopy(untapped['annotations'][0]))
        elif mode == 'malformed': untapped['annotations'][0]['details'].append(copy.deepcopy(untapped['annotations'][0]['details'][0]))
        elif mode == 'boolean': untapped['annotations'][0]['details'][0]['valueInt32'] = [False]
        elif mode == 'ambiguous_type': untapped['annotations'][0]['type'].append('AnnotationType_Other')
        elif mode == 'unrelated': untapped['annotations'] = [annotation(target, 0, 3)]
        elif mode == 'missing_tap_pair': tapped['annotations'] = []
        elif mode == 'replacement': final['gameObjects'] = [copy.deepcopy(untapped['gameObjects'][0])]
        elif mode == 'later_tap':
            final['gameObjects'] = [dict(untapped['gameObjects'][0], isTapped=True)]
            final['annotations'] = [annotation(sources[0], 1, 5)]
        elif mode == 'migration':
            final['annotations'] = [{'id': 5, 'type': ['AnnotationType_ObjectIdChanged'], 'affectedIds': [sources[0]],
                'details': [{'key': k, 'type': 'KeyValuePairValueType_int32', 'valueInt32': [v]}
                            for k, v in (('orig_id', sources[0]), ('new_id', 99999))]}]
        elif mode == 'affector':
            final['annotations'] = [{'id': 5, 'type': ['AnnotationType_Other'], 'affectorId': sources[0], 'affectedIds': [target]}]
        elif mode == 'full': final = dict(copy.deepcopy(full), gameStateId=13)
        elif mode == 'reused_annotation': untapped['annotations'][0]['id'] = tapped['annotations'][0]['id']
        elif mode == 'missing_endpoint':
            final['annotations'] = [annotation(sources[0], 1, 5)]
            del final['annotations'][0]['affectedIds']
        request = {'type': 'GREMessageType_ActionsAvailableReq', 'systemSeatIds': [1], 'msgId': 1,
                   'gameStateId': 13, 'actionsAvailableReq': {'actions': actions}}
        reducer = RawReducer(include_state_messages=True, include_request_parameters=True,
                             include_targeted_activate=True, include_target_payment_relation=True)
        reducer.reset(1)
        observer = TapObserver(reducer); reducer.observer = observer.observe
        for record in ({'authenticateResponse': {'clientId': 'synthetic-a'}},
                       {'matchGameRoomStateChangedEvent': {'gameRoomInfo': {'stateType':'MatchGameRoomStateType_Playing',
                        'gameRoomConfig': {'matchId':'synthetic-untap-source', 'reservedPlayers':[
                         {'userId':'synthetic-a','systemSeatId':1}, {'userId':'synthetic-b','systemSeatId':2}]}}}}):
            observer.prepare(record); reducer.apply(record)
        for gs in (() if mode == 'missing_full' else (full,)) + (tapped, untapped, final):
            messages = [{'type': 'GREMessageType_GameStateMessage', 'systemSeatIds': [1], 'gameStateMessage': gs}]
            if gs is final: messages.append(request)
            record = {'greToClientEvent': {'greToClientMessages': messages}}
            observer.prepare(record); reducer.apply(record)
        doc = reducer.document(include_frontier_rows=True, include_decision_state=True)
        doc['source'] = {'format': 'player-log-gre-v1', 'generation': 1, 'byte_offset': None,
                         'partial_record': False, 'mode': 'offline', 'input_sent': False, 'executor_connected': False}
        _project_decision_state(reducer, doc, None, False, 10)
        return reducer, observer, doc['decision_state'], request

    def test_real_two_source_event_evidence_is_distinct_from_tap_literal_and_payability(self):
        before = copy.deepcopy(self.state); result = evaluate_witness(self.state)
        self.assertTrue(result['untapped_pre_request_witness_verified']); self.assertEqual(result['verified_source_count'], 2)
        self.assertEqual([s['mana_action_position'] for s in result['source_witnesses']], [12, 14])
        self.assertTrue(all(s['witness_grade'] == GOOD for s in result['source_witnesses']))
        self.assertEqual([(s['untap']['record'], s['untap']['message']) for s in result['source_witnesses']], [(1375, 5)]*2)
        self.assertEqual(self.state[FIELD]['checked_through']['record'], 1402)
        self.assertEqual(self.state[FIELD]['checked_through']['message'], 0)
        self.assertEqual(self.state[FIELD]['request_location']['message'], 1)
        self.assertEqual(self.state, before)
        for key in ('overall_payability_verified','complete_costs_verified','complete_payment_verified',
                    'target_quantity_verified','target_domain_complete_verified','rules_effect_verified',
                    'historical_response_used','raw_source_reauthenticated',*EXECUTION): self.assertIs(result[key], False, key)
        association = evaluate_relation(self.state)
        self.assertFalse(association['payment_source_untapped_verified']); self.assertEqual(association['returned_relations'], 1)
        self.assertEqual([s['current_tapped_literal'] for s in association['relations'][0]['mana_row_witnesses']], [None, None])
        self.no_witness(evaluate_witness(self.fixture['after_response']))

    def test_synthetic_source_observes_fresh_zero_with_missing_literal_without_inventing_false(self):
        reducer, observer, state, _ = self.synthetic_source()
        result = evaluate_witness(state); self.assertEqual(result['verified_source_count'], 2)
        self.assertFalse(observer.quarantined)
        for source in state[FIELD]['sources']:
            self.assertNotIn('isTapped', reducer.objects[source['identifier_refs']['instanceId']])

    def test_source_replacement_later_same_record_tap_and_unresolved_migration_invalidate_independently(self):
        for mode in ('replacement', 'later_tap', 'migration', 'affector', 'full'):
            _, _, state, _ = self.synthetic_source(mode)
            result = evaluate_witness(state); self.no_witness(result)
            self.assertEqual(evaluate_relation(state)['returned_relations'], 1)
            if mode != 'full': self.assertEqual(result['verified_source_count'], 1)

    def test_duplicate_ambiguous_malformed_boolean_and_unrelated_untaps_fail_closed(self):
        for mode in ('true_conflict','duplicate','malformed','boolean','ambiguous_type','unrelated',
                     'missing_tap_pair','missing_full','reused_annotation','missing_endpoint'):
            _, _, state, _ = self.synthetic_source(mode)
            self.no_witness(evaluate_witness(state))

    def test_own_public_scope_and_identity_discontinuity_cannot_reuse_an_anchor(self):
        for field, value in (('owner_seat',2),('controller_seat',2),('zone','ZoneType_Graveyard'),('tapped',True)):
            state = copy.deepcopy(self.state); ref = state[FIELD]['sources'][0]['identifier_refs']['instanceId']
            next(o for o in state['visible_objects'] if o['instance_id'] == ref)[field] = value
            self.no_witness(evaluate_witness(state))
        state = copy.deepcopy(self.state); state[FIELD]['sources'][0]['identifier_refs']['uniqueAbilityId'] += 1
        self.no_witness(evaluate_witness(state))

    def test_portable_binding_order_cross_row_and_unbounded_text_rejections(self):
        for mode in ('binding','position','swapped','request_time','untap_time','state_id','boolean','reason','old_version'):
            state = copy.deepcopy(self.state); p = state[FIELD]
            if mode == 'binding': p['binding']['request_id'] += 1
            elif mode == 'position': p['sources'][0]['mana_action_position'] += 1
            elif mode == 'swapped': p['sources'].reverse()
            elif mode == 'request_time': p['checked_through'] = copy.deepcopy(p['request_location'])
            elif mode == 'untap_time': p['sources'][0]['untap']['record'] = 1403
            elif mode == 'state_id': p['checked_through']['state_id'] += 1
            elif mode == 'boolean': p['sources'][0]['tap_pair']['state_id'] = True
            elif mode == 'reason': p['sources'][0]['reason'] = 'PRIVATE_SENTINEL'
            else: state['schema_version'] = 'mtgaplayer.decision-state.v9'
            result = evaluate_witness(state); self.no_witness(result); self.assertNotIn('PRIVATE_SENTINEL', json.dumps(result))

    def test_retransmission_does_not_refresh_event_or_request_location_and_new_state_revokes_request(self):
        reducer, observer, state, request = self.synthetic_source(); before = copy.deepcopy(state[FIELD])
        record = {'greToClientEvent': {'greToClientMessages': [copy.deepcopy(request)]}}
        observer.prepare(record); reducer.apply(record)
        self.assertEqual(reducer.request['_payment_source_tap_provenance'], before)
        observer.observe('continuity_error', {'reason': 'synthetic_gap'})
        observer.prepare(record); reducer.apply(record)
        self.assertNotIn('_payment_source_tap_provenance', reducer.request)
        observer.reset(); self.assertFalse(observer.sources); self.assertIsNone(observer.frozen)

    def test_contract_drift_and_typed_ref_reject_without_lending_old_relation_authority(self):
        from mtgaplayer import activate_target_payment
        original = activate_target_payment.evaluate_relation
        fields = ('mana_payment_verified','payment_completed_verified','target_quantity_completeness_verified',
                  'complete_target_legality_verified','global_restrictions_verified','untapped_pre_request_witness_verified')
        for key, value in [('schema_version','wrong'),('scope','wrong'),('diagnostics_only',1),
                           ('returned_relations',True),('complete_legality_verified',True),*[(f, True) for f in fields]]:
            def drift(*args, **kwargs):
                result = original(*args, **kwargs); result[key] = value; return result
            with patch.object(activate_target_payment, 'evaluate_relation', side_effect=drift): self.no_witness(evaluate_witness(self.state))
        for mode in ('action_id','mana_id','mana_flag','row_status','float_position','float_target'):
            def drift_row(*args, **kwargs):
                result = original(*args, **kwargs); row = result['relations'][0]
                if mode == 'action_id': row['action_identifier_refs']['uniqueAbilityId'] += 1
                elif mode == 'mana_id': row['mana_row_witnesses'][0]['identifier_refs']['instanceId'] += 1
                elif mode == 'mana_flag': row['mana_row_witnesses'][0]['flags']['isBatchable'] = False
                elif mode == 'row_status': row['relation_status'] = 'insufficient_evidence'
                elif mode == 'float_position': row['mana_row_witnesses'][0]['list_position'] = 12.0
                else: row['target_member']['target_idx'] = float(row['target_member']['target_idx'])
                return result
            with patch.object(activate_target_payment, 'evaluate_relation', side_effect=drift_row): self.no_witness(evaluate_witness(self.state))
        _, consumer, _, _, _, _ = self.transport(); ref = consumer.current_view()['current_snapshot_ref']
        def bad_ref(*args, **kwargs):
            result = original(*args, **kwargs); result['source_snapshot_ref']['binding']['source_generation'] = True; return result
        with patch.object(activate_target_payment, 'evaluate_relation', side_effect=bad_ref):
            self.no_witness(evaluate_witness(self.state, source_snapshot_ref=ref))

    def test_history_stop_expiry_and_post_calculation_lease_recheck(self):
        _, consumer, _, _, _, _ = self.transport(history=True); self.no_witness(assess_current_witness(consumer))
        pub, consumer, clock, _, _, _ = self.transport(); self.assertEqual(assess_current_witness(consumer)['verified_source_count'], 2)
        clock.advance(501); self.no_witness(assess_current_witness(consumer))
        pub, consumer, _, _, _, _ = self.transport()
        for event in pub.stop(): self.assertTrue(consumer.accept_event(event))
        self.no_witness(assess_current_witness(consumer))
        from mtgaplayer import payment_source_tap
        _, consumer, clock, _, _, _ = self.transport(); original = evaluate_witness
        def slow(*args, **kwargs):
            result = original(*args, **kwargs); clock.advance(501); return result
        with patch.object(payment_source_tap, 'evaluate_witness', side_effect=slow): self.no_witness(assess_current_witness(consumer))

    def test_consumption_replacement_partial_reset_session_and_gap_revoke_both(self):
        for mode in ('consumed','replacement','partial','reset','session','gap'):
            pub, consumer, _, doc, meta, _ = self.transport()
            if mode in ('session','gap'):
                event = copy.deepcopy(pub.observe(doc, meta)[-1])
                if mode == 'session': event['session_id'] = 'wrong'
                else: event['sequence'] += 1
                self.assertFalse(consumer.accept_event(event))
            else:
                if mode == 'consumed':
                    state = copy.deepcopy(self.fixture['after_response']); state['source'].update(mode='watch',phase='append',stopped=False)
                    doc['decision_state'] = state; meta = dict(meta, request_consumed=True, new_final_request=False)
                elif mode == 'replacement':
                    def replace(value):
                        if type(value) is dict: return {k:(v+1 if k=='request_id' and type(v) is int else replace(v)) for k,v in value.items()}
                        if type(value) is list: return [replace(v) for v in value]
                        return value
                    doc['decision_state'] = replace(doc['decision_state']); meta = dict(meta,new_final_request=False)
                else:
                    doc = {'decision_state': None, 'current': {}, 'source': {'phase':'append','partial_record':mode=='partial'}}
                    meta = dict(meta, source_reset=mode=='reset', continuity_error=True, new_final_request=False)
                for event in pub.observe(doc, meta): consumer.accept_event(event)
            self.no_witness(assess_current_witness(consumer))

    def test_last_sidecar_expiration_rechecks_untap_and_association_before_output(self):
        from mtgaplayer import payment_source_tap
        pub, _, clock, _, _, events = self.transport(); events += pub.stop(); original = assess_current_witness; advanced = False
        def slow(consumer):
            nonlocal advanced
            result = original(consumer)
            if result['verified_source_count'] == 2 and not advanced: clock.advance(501); advanced = True
            return result
        output = []
        with patch.object(payment_source_tap,'assess_current_witness',side_effect=slow):
            code = consume_events(io.StringIO(''.join(json.dumps(e)+'\n' for e in events)), output.append,
                DecisionConsumer(10000,500,clock), activate_target_payment_relation=True, payment_source_untap_witness=True)
        self.assertEqual(code, 1)
        self.assertTrue(all(v['payment_source_untap_witness']['verified_source_count']==0 for v in output))
        self.assertTrue(all(v['activate_target_payment_relation']['returned_relations']==0 for v in output))

    def test_actual_consumer_cli_is_opt_in_and_stops_without_manual_proposal(self):
        pub, _, _, _, _, events = self.transport(); events += pub.stop()
        run = subprocess.run([sys.executable,'-m','mtgaplayer','consume-events','--payment-source-untap-witness'],
            input=''.join(json.dumps(e)+'\n' for e in events), capture_output=True, text=True, timeout=20)
        self.assertEqual(run.returncode, 0, run.stderr); values = [json.loads(x) for x in run.stdout.splitlines()]
        self.assertTrue(any(v['payment_source_untap_witness']['verified_source_count']==2 for v in values))
        self.no_witness(values[-1]['payment_source_untap_witness'])
        self.assertTrue(all('choice_validation' not in v and 'known_choice_candidates' not in v for v in values))
        for version in (1,9):
            with self.assertRaises(ValueError): replay(FIXTURE,format='player-log',decision_state_version=version,payment_source_untap_witness=True)
        for value in (None,0,1,'true'):
            with self.assertRaises(ValueError): consume_events(io.StringIO(''),lambda v:None,payment_source_untap_witness=value)

    def test_state9_relation_and_default_consumer_outputs_keep_their_old_values(self):
        shadow = copy.deepcopy(self.state); shadow.pop(FIELD); shadow['schema_version']='mtgaplayer.decision-state.v9'
        self.assertEqual(evaluate_relation(shadow), evaluate_relation(self.state))
        pub, _, _, _, _, events = self.transport(); events += pub.stop(); output=[]
        self.assertEqual(consume_events(io.StringIO(''.join(json.dumps(e)+'\n' for e in events)), output.append),0)
        self.assertTrue(all('payment_source_untap_witness' not in v for v in output))


if __name__=='__main__': unittest.main()
