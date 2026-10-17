"""One public real pre/post projection; mutations/transport/bootstrap are synthetic.

No private original log, DLL, account, network or native input is accessed.
Invented bootstrap envelopes exercise production plumbing, not new real evidence.
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

from mtgaplayer import cast_activate_associations as associations
from mtgaplayer import cast_target_members as cast
from mtgaplayer import activate_target_payment as activate
from mtgaplayer.choice_candidates import enumerate_known_candidates, assess_current_known_candidates
from mtgaplayer.choice_validation import validate_proposed_choice
from mtgaplayer.cli import replay
from mtgaplayer.decision_consumer import DecisionConsumer, EXECUTION, _state, consume_events
from mtgaplayer.decision_publisher import DecisionPublisher
from mtgaplayer.payment_source_tap import evaluate_witness
from mtgaplayer.semantic_activate import raw_action
from test_decision_publisher import ManualClock


FIXTURES = Path(__file__).parent / 'fixtures'
FIXTURE = FIXTURES / 'cast_activate_associations_real_v12.json'
DEFAULT_STATE = object()


class CastActivateAssociationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads(FIXTURE.read_text(encoding='utf-8'))
        self.state = self.fixture['before_response']

    def params(self, state=None):
        return (self.state if state is None else state)['legal_action_space']['request_parameters']

    def family(self, state, kind='cast_members'):
        return self.params(state)[kind]

    def literal(self, state, field='cast_actions', position=1, kind='cast_members'):
        return next(r['action'] for r in self.family(state, kind)[field] if r['list_position'] == position)

    def report(self, state=DEFAULT_STATE, **kwargs):
        return enumerate_known_candidates(self.state if state is DEFAULT_STATE else state, version=6, **kwargs)

    def counts(self, report, candidates, relations):
        self.assertEqual(report['schema_version'], associations.VERSION)
        self.assertEqual(report['returned_candidates'], candidates)
        self.assertEqual(report['returned_relations'], relations)
        self.assertEqual(report['cast_members']['returned_candidates'], candidates)
        self.assertEqual(report['activate_payment']['returned_relations'], relations)
        self.assertIs(report['families_jointly_executable'], False)
        self.assertIs(report['read_only'], True)
        for key in (*cast.DENIALS, *EXECUTION):
            self.assertIs(report[key], False, key)

    def transport(self, history=False):
        """Synthetic clock/session/append lifecycle around the public State12."""
        clock = ManualClock()
        pub = DecisionPublisher(clock_ns=clock, session_id='synthetic-mp61', state_version=12)
        state = copy.deepcopy(self.state)
        state['source'].update(mode='watch', phase='history' if history else 'append', stopped=False)
        doc = {'decision_state': state, 'source': {'phase': state['source']['phase'], 'partial_record': False}}
        meta = {'poll_started_ns': clock(), 'poll_completed_ns': clock(), 'poll_read_ns': 0,
                'reducer_apply_ns': 0, 'decision_state_assembly_ns': 0,
                'request_changed': True, 'new_final_request': True}
        events = pub.observe(doc, meta)
        consumer = DecisionConsumer(10000, 500, clock)
        for event in events:
            self.assertTrue(consumer.accept_event(event))
        return pub, consumer, clock, doc, meta, events

    def synthetic_bootstrap(self, mutate=None):
        """Invented auth/room/Full, with public literal rows at original positions.

        Unsupported rows have only invented identifier/flag skeletons. This is
        deliberately not a reconstruction or authentication of the raw source.
        """
        p = self.params()
        actions = [{'actionType': r['action_type'], **r['identifier_refs'], **r['flags']}
                   for r in p['cast_members']['rows']]
        records = (p['cast_members']['cast_actions'] + p['cast_members']['mana_actions'] +
                   p['activate_payment']['target_actions'] + p['activate_payment']['mana_actions'])
        pairs = {}
        for record in records:
            action = raw_action(record['action'])
            actions[record['list_position']] = action
            if 'uniqueAbilityId' in action:
                pair = {'id': action['uniqueAbilityId'], 'grpId': action['abilityGrpId']}
                if pair not in pairs.setdefault(action['instanceId'], []):
                    pairs[action['instanceId']].append(pair)
        objects = []
        for obj in self.state['visible_objects']:
            zone = 11 if obj['zone'] == 'ZoneType_Battlefield' else 13
            value = {'instanceId': obj['instance_id'], 'type': 'GameObjectType_Card', 'zoneId': zone,
                     'ownerSeatId': obj['owner_seat'], 'controllerSeatId': obj['controller_seat']}
            if obj['card_id'] is not None:
                value['grpId'] = obj['card_id']
            if zone == 11:
                value['visibility'] = 'Visibility_Public'
            else:
                value['visibility'] = 'Visibility_Private'
                value['viewers'] = [1]
            if obj['instance_id'] in pairs:
                value['uniqueAbilities'] = copy.deepcopy(pairs[obj['instance_id']])
            objects.append(value)
        if mutate:
            mutate(actions, objects)
        full = {'type': 'GameStateType_Full', 'gameStateId': 10,
                'gameInfo': {'matchID': 'synthetic-mp61-bootstrap', 'gameNumber': 1, 'stage': 'GameStage_Play'},
                'players': [{'systemSeatNumber': seat, 'lifeTotal': 20} for seat in (1, 2)],
                'gameObjects': objects,
                'zones': [{'zoneId': 11, 'type': 'ZoneType_Battlefield', 'visibility': 'Visibility_Public',
                           'objectInstanceIds': [o['instanceId'] for o in objects if o['zoneId'] == 11]},
                          {'zoneId': 12, 'type': 'ZoneType_Stack', 'visibility': 'Visibility_Public',
                           'objectInstanceIds': []},
                          {'zoneId': 13, 'type': 'ZoneType_Hand', 'ownerSeatId': 1, 'visibility': 'Visibility_Private', 'viewers': [1],
                           'objectInstanceIds': [o['instanceId'] for o in objects if o['zoneId'] == 13]}]}
        request = {'type': 'GREMessageType_ActionsAvailableReq', 'systemSeatIds': [1],
                   'msgId': 1, 'gameStateId': 10, 'prompt': copy.deepcopy(p['prompt']),
                   'actionsAvailableReq': {'actions': actions, 'inactiveActions': []}}
        return [{'authenticateResponse': {'clientId': 'synthetic-a'}},
                {'matchGameRoomStateChangedEvent': {'gameRoomInfo': {'stateType': 'MatchGameRoomStateType_Playing',
                 'gameRoomConfig': {'matchId': 'synthetic-mp61-bootstrap', 'reservedPlayers': [
                     {'userId': 'synthetic-a', 'systemSeatId': 1}, {'userId': 'synthetic-b', 'systemSeatId': 2}]}}}},
                {'greToClientEvent': {'greToClientMessages': [
                    {'type': 'GREMessageType_GameStateMessage', 'systemSeatIds': [1], 'gameStateMessage': full}, request]}}]

    def bootstrap_state(self, mutate=None, version=12):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'synthetic-public-literals.jsonl'
            path.write_text(''.join(json.dumps(r) + '\n' for r in self.synthetic_bootstrap(mutate)), encoding='utf-8')
            state = replay(path, format='player-log', decision_state_version=version)['decision_state']
            self.assertIsNotNone(state, 'synthetic bootstrap must produce a state before testing it')
            return state

    def test_real_portable_pre_post_and_authority_denials(self):
        data = FIXTURE.read_bytes().replace(b'\r\n', b'\n')
        self.assertEqual(len(data), 177319)
        self.assertEqual(hashlib.sha256(data).hexdigest(),
                         'e50afcd4ff6ab129139ebff5fcec6a0e63ffa51825a95a1617dcc7e7ebf984a4')
        before = copy.deepcopy(self.state)
        _state(self.state, self.state['binding'])
        result = self.report()
        self.counts(result, 6, 1)
        self.assertEqual((result['engine_active_action_rows'], result['inactive_action_rows']), (17, 5))
        self.assertEqual([c['proposal']['list_position'] for c in result['cast_members']['candidates']], [1]*3+[3]*3)
        self.assertEqual([c['payment_witness']['list_position'] for c in result['cast_members']['candidates']], [10]*6)
        self.assertTrue(all(c['payment_witness']['current_tapped_literal'] is None
                            for c in result['cast_members']['candidates']))
        relation = result['activate_payment']['relations'][0]
        self.assertEqual(relation['list_position'], 6)
        self.assertEqual([r['list_position'] for r in relation['mana_row_witnesses']], [12, 14])
        self.assertEqual(result['cast_members']['target_quantities'],
                         {'minimum': None, 'maximum': None, 'selected_count': None})
        self.assertEqual(result['cast_members']['payment_source_readiness'], 'unknown_not_evaluated')
        self.assertEqual(evaluate_witness(self.state)['verified_source_count'], 2)
        self.assertEqual(evaluate_witness(self.fixture['after_response'])['verified_source_count'], 0)
        self.counts(self.report(self.fixture['after_response']), 0, 0)
        self.assertEqual(self.state, before)

    def test_literal_prompt_highlights_retained_and_unsupported_cast_not_promoted(self):
        p = self.params()
        self.assertEqual(set(p['prompt']), {'promptId'})
        self.assertEqual([r['list_position'] for r in p['cast_members']['cast_actions']], [1, 3])
        self.assertEqual(p['cast_members']['rows'][2]['list_position'], 2)
        self.assertTrue(p['cast_members']['rows'][2]['other_fields_present'])
        for record in p['cast_members']['cast_actions']:
            self.assertTrue(all(type(t['highlight']) is str for t in record['action']['parameters']['targets'][0]['targets']))
        proposal = copy.deepcopy(self.report()['cast_members']['candidates'][0]['proposal'])
        proposal['list_position'] = 2
        self.assertNotEqual(validate_proposed_choice(self.state, proposal)['known_constraints'], cast.GOOD)
        for version in range(1, 12):
            state = copy.deepcopy(self.state)
            state['schema_version'] = f'mtgaplayer.decision-state.v{version}'
            with self.subTest(old_state=version), self.assertRaises(ValueError):
                _state(state, state['binding'])

    def test_per_family_unknown_preserves_other_family_and_denominator(self):
        state = copy.deepcopy(self.state)
        self.literal(state)['parameters']['manaCost'][0]['count'] = 2
        _state(state, state['binding'])
        result = self.report(state)
        self.counts(result, 3, 1)
        self.assertEqual(result['cast_members']['member_probes']['unknown'], 3)
        state = copy.deepcopy(self.state)
        self.literal(state, 'target_actions', 6, 'activate_payment')['parameters']['manaCost'][0]['count'] = 3
        _state(state, state['binding'])
        self.counts(self.report(state), 6, 0)
        self.assertEqual(self.report(state)['engine_active_action_rows'], 17)

    def test_cost_unit_color_count_source_group_and_option_selection_controls(self):
        for mode in ('cost_color', 'cost_count', 'unit_color', 'unit_count', 'unit_source', 'unit_group',
                     'option_unit', 'selection_color', 'selection_source', 'selection_count'):
            with self.subTest(mode=mode):
                state = copy.deepcopy(self.state)
                params = self.literal(state)['parameters']
                unit = params['autoTapSolution']['autoTapActions'][0]['manaPaymentOption']['mana'][0]
                mana = self.literal(state, 'mana_actions', 10)['parameters']
                if mode == 'cost_color': params['manaCost'][0]['color'] = ['ManaColor_Blue']
                elif mode == 'cost_count': params['manaCost'][0]['count'] = 2
                elif mode == 'unit_color': unit['color'] = 'ManaColor_Red'
                elif mode == 'unit_count': unit['count'] = 2
                elif mode == 'unit_source': unit['srcInstanceId'] += 1
                elif mode == 'unit_group': unit['abilityGrpId'] += 1
                elif mode == 'option_unit': mana['manaPaymentOptions'][0]['mana'][0]['manaId'] += 1
                elif mode == 'selection_color': mana['manaSelections'][0]['options'][0]['mana'][0]['color'] = 'ManaColor_Red'
                elif mode == 'selection_source': mana['manaSelections'][0]['instanceId'] += 1
                else: mana['manaSelections'][0]['options'][0]['mana'][0]['count'] = 2
                _state(state, state['binding'])
                self.counts(self.report(state), 0 if mode.startswith(('option', 'selection')) else 3, 1)

    def test_malformed_prompt_highlight_duplicates_and_unknown_fields_fail_closed(self):
        controls = []
        for value in ({}, {'promptId': 0}, {'promptId': True}, {'promptId': 2**32},
                      {'promptId': '1'}, {'promptId': 1, 'parameters': []}, {'promptId': 1, 'extra': 0}):
            controls.append(lambda s, value=value: self.params(s).update(prompt=value))
        controls += [lambda s: self.params(s).update(inactive_action_count=True),
                     lambda s: self.params(s).update(future='PRIVATE_SENTINEL'),
                     lambda s: self.literal(s)['parameters'].update(future='PRIVATE_SENTINEL'),
                     lambda s: self.literal(s)['parameters']['targets'][0]['targets'][0].pop('highlight'),
                     lambda s: self.literal(s)['parameters']['targets'][0]['targets'][0].update(highlight=1),
                     lambda s: self.literal(s)['parameters']['targets'][0]['targets'][0].update(highlight='x'*129),
                     lambda s: self.literal(s)['parameters']['targets'][0]['targets'].append(
                         copy.deepcopy(self.literal(s)['parameters']['targets'][0]['targets'][0])),
                     lambda s: self.family(s)['cast_actions'].append(copy.deepcopy(self.family(s)['cast_actions'][0])),
                     lambda s: s['visible_objects'].append(copy.deepcopy(s['visible_objects'][0]))]
        for index, mutate in enumerate(controls):
            with self.subTest(control=index):
                state = copy.deepcopy(self.state); mutate(state)
                with self.assertRaises(ValueError): _state(state, state['binding'])
                result = self.report(state); self.counts(result, 0, 0)
                self.assertNotIn('PRIVATE_SENTINEL', json.dumps(result))

    def test_source_target_visibility_membership_and_current_tap_controls(self):
        for kind in ('cast_source', 'mana_source', 'target'):
            for mode in ('missing', 'private', 'zone', 'foreign_controller', 'tapped'):
                with self.subTest(kind=kind, mode=mode):
                    state = copy.deepcopy(self.state); p = self.family(state)
                    action = self.literal(state)
                    ident = (action['identifier_refs']['instanceId'] if kind == 'cast_source' else
                             self.literal(state, 'mana_actions', 10)['identifier_refs']['instanceId'] if kind == 'mana_source' else
                             action['parameters']['targets'][0]['targets'][0]['targetInstanceId'])
                    obj = next(o for o in state['visible_objects'] if o['instance_id'] == ident)
                    if mode == 'missing': state['visible_objects'].remove(obj)
                    elif mode == 'private':
                        if kind == 'cast_source': p['cast_source_refs'].remove(ident)
                        else: p['public_battlefield_refs'].remove(ident)
                    elif mode == 'zone': obj['zone'] = 'ZoneType_Graveyard'
                    elif mode == 'foreign_controller': obj['controller_seat'] = 3-state['binding']['self_seat']
                    else: obj['tapped'] = True
                    result = self.report(state)
                    if mode == 'foreign_controller' and kind == 'target':
                        self.assertEqual(result['returned_candidates'], 6)
                    elif mode == 'tapped' and kind != 'mana_source':
                        # Source/target tapping alone is not a general rules solver.
                        self.counts(result, 6, 1)
                    else:
                        self.assertLess(result['returned_candidates'], 6)

    def test_binding_inventory_flags_graph_and_nested_family_mismatch_controls(self):
        for mode in ('outer_binding', 'cast_binding', 'activate_binding', 'cast_flags', 'activate_flags',
                     'rows_differ', 'graph_identity', 'graph_flags', 'graph_target_shape', 'history'):
            with self.subTest(mode=mode):
                state = copy.deepcopy(self.state); p = self.params(state)
                if mode.endswith('binding'):
                    value = p if mode == 'outer_binding' else p['cast_members' if mode == 'cast_binding' else 'activate_payment']
                    value['binding']['request_id'] += 1
                elif mode == 'cast_flags': self.literal(state)['flags']['shouldStop'] = 1
                elif mode == 'activate_flags': self.literal(state, 'target_actions', 6, 'activate_payment')['flags']['shouldStop'] = False
                elif mode == 'rows_differ': p['activate_payment']['rows'][0]['flags']['shouldStop'] = False
                elif mode == 'history': p['historical_response_used'] = True
                else:
                    node = state['legal_action_space']['choice_graph']['action_nodes'][1]
                    if mode == 'graph_identity': node['action_identity']['raw_identifiers']['instance_id'] = True
                    elif mode == 'graph_flags': node['action_identity']['raw_flags_observed_not_discriminators']['should_stop'] = False
                    else: next(c for c in node['constraints'] if c['parameter_category'] == 'targets')['observed_structure'] = {'kind': 'object'}
                with self.assertRaises(ValueError): _state(state, state['binding'])
                self.counts(self.report(state), 0, 0)

    def test_existing_blue_profile_falls_back_without_inventing_activate_relation(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'public-prefix103.jsonl'
            path.write_bytes(b''.join((FIXTURES/'player_log_single_target.jsonl').read_bytes().splitlines(keepends=True)[:103]))
            state = replay(path, format='player-log', decision_state_version=12)['decision_state']
        self.counts(self.report(state), 8, 0)
        self.assertEqual(self.report(state)['cast_members']['schema_version'], cast.VERSION)

    def test_synthetic_target_slot_integer_bound_matches_schema_and_proposal(self):
        for slot in (True, 0, -1, 2**53+7):
            with self.subTest(slot=slot):
                state = copy.deepcopy(self.state)
                self.literal(state)['parameters']['targets'][0]['targetIdx'] = slot
                node = next(n for n in state['legal_action_space']['choice_graph']['action_nodes']
                            if n['action_key']['list_position'] == 1)
                next(c for c in node['constraints'] if c['parameter_category'] == 'targets')[
                    'observed_quantity_or_domain']['groups'][0]['target_idx_raw'] = slot
                with self.assertRaises(ValueError): _state(state, state['binding'])
                def unsupported(actions, objects): actions[1]['targets'][0]['targetIdx'] = slot
                # An unsupported raw row must leave the other real-shaped Cast
                # and Activate available in this explicitly synthetic bootstrap.
                self.counts(self.report(self.bootstrap_state(unsupported)), 3, 1)

    def test_limits_are_explicit_and_do_not_erase_activate_family(self):
        result = self.report(limit=2); self.counts(result, 2, 1)
        probes = result['cast_members']['member_probes']
        self.assertEqual((probes['observed'], probes['verified'], probes['returned'], probes['omitted_due_to_return_limit']), (6, 6, 2, 4))
        self.assertTrue(result['cast_members']['truncated'])
        for limit in (0, 65, True, '2', 2.0):
            with self.subTest(limit=limit), self.assertRaises(ValueError): self.report(limit=limit)

    def test_synthetic_bootstrap_duplicate_options_and_ambiguous_cast_offer(self):
        self.counts(self.report(self.bootstrap_state()), 6, 1)
        for field in ('manaPaymentOptions', 'manaSelections'):
            def duplicate(actions, objects):
                actions[10][field].append(copy.deepcopy(actions[10][field][0]))
            with self.subTest(field=field):
                self.counts(self.report(self.bootstrap_state(duplicate)), 0, 1)
        def duplicate_cast(actions, objects): actions[0] = copy.deepcopy(actions[1])
        result = self.report(self.bootstrap_state(duplicate_cast))
        self.counts(result, 3, 1)
        self.assertEqual(result['cast_members']['member_probes']['unknown'], 6)

    def test_synthetic_probe_cap_is_256_independent_of_return_cap(self):
        def many(actions, objects):
            targets = []
            for i in range(64):
                ident = 2000000+i
                objects.append({'instanceId': ident, 'grpId': 3000000+i, 'type': 'GameObjectType_Card',
                                'zoneId': 11, 'ownerSeatId': 2, 'controllerSeatId': 2, 'visibility': 'Visibility_Public'})
                targets.append({'targetInstanceId': ident, 'highlight': 'synthetic-structural-control'})
            template = copy.deepcopy(actions[1])
            for pos in (0, 1, 2, 3, 4):
                ids = {k: actions[pos][k] for k in ('instanceId', 'grpId', 'facetId')}
                actions[pos] = {**copy.deepcopy(template), **ids}
                actions[pos]['targets'][0]['targets'] = copy.deepcopy(targets)
        result = self.report(self.bootstrap_state(many))
        self.counts(result, 64, 1)
        self.assertEqual(result['cast_members']['member_probes'],
                         dict(observed=320, examined=256, verified=256, unknown=0, contradicted=0,
                              unexamined=64, returned=64, omitted_due_to_return_limit=192))

    def test_choice_validator_good_scope_route_refs_and_authority_drift_rejected(self):
        original = validate_proposed_choice
        mutations = [lambda v: v.update(schema_version='unknown'), lambda v: v.update(validation_scope='wrong'),
                     lambda v: v.update(read_only=1), lambda v: v.update(input_sent=True),
                     lambda v: v.update(target_minimum=1), lambda v: v.update(payment_witness=None),
                     lambda v: v.update(extra=True), lambda v: v['payment_witness'].update(list_position=12),
                     lambda v: v['payment_witness']['identifier_refs'].update(instanceId=999),
                     lambda v: v['payment_witness']['flags'].update(isBatchable=1)]
        mutations += [lambda v, key=key: v.update({key: True}) for key in cast.DENIALS]
        for index, mutate in enumerate(mutations):
            def drift(*args, **kwargs):
                verdict = original(*args, **kwargs)
                if 'proposed_cast_target_member' in args[1]: mutate(verdict)
                return verdict
            with self.subTest(control=index), patch('mtgaplayer.choice_validation.validate_proposed_choice', side_effect=drift):
                self.assertEqual(self.report()['returned_candidates'], 0)
        state = copy.deepcopy(self.state); self.literal(state)['parameters']['manaCost'][0]['count'] = 2
        good = original(self.state, self.report()['cast_members']['candidates'][0]['proposal'])
        def forged(*args, **kwargs):
            if args[1].get('list_position') == 1: return copy.deepcopy(good)
            return original(*args, **kwargs)
        with patch('mtgaplayer.choice_validation.validate_proposed_choice', side_effect=forged):
            self.assertEqual(self.report(state)['returned_candidates'], 0)

    def test_aggregate_rejects_nested_report_contract_drift(self):
        good = self.report()
        for family, path in (('cast_members', 'mtgaplayer.cast_target_members.enumerate_members'),
                             ('activate_payment', 'mtgaplayer.activate_target_payment.evaluate_relation')):
            for mode in ('scope', 'binding', 'ref', 'input', 'count', 'status'):
                bad = copy.deepcopy(good[family])
                if mode == 'scope': bad['scope'] = 'wrong'
                elif mode == 'binding': bad['request_binding']['request_id'] += 1
                elif mode == 'ref': bad['source_snapshot_ref'] = {'unexpected': True}
                elif mode == 'input': bad['input_sent'] = True
                elif mode == 'count': bad['returned_candidates' if family == 'cast_members' else 'returned_relations'] += 1
                else: bad['status'] = 'arbitrary_good'
                with self.subTest(family=family, mode=mode), patch(path, return_value=bad):
                    self.counts(self.report(), 0, 0)

    def test_forged_good_activate_validator_cannot_replace_current_ability_binding(self):
        original = validate_proposed_choice
        for binding in ('insufficient_evidence', 'observed_group_contradiction'):
            state = copy.deepcopy(self.state)
            self.family(state, 'activate_payment')['rows'][6]['ability_binding'] = binding
            def forged(current, proposal, **kwargs):
                return original(self.state if 'proposed_activate_target_member' in proposal else current, proposal, **kwargs)
            with self.subTest(binding=binding), patch('mtgaplayer.choice_validation.validate_proposed_choice', side_effect=forged):
                self.assertEqual(self.report(state)['returned_relations'], 0)

    def test_synthetic_history_lease_close_stop_and_calculation_expiry(self):
        _, consumer, _, _, _, _ = self.transport(history=True)
        self.counts(assess_current_known_candidates(consumer, version=6), 0, 0)
        for mode in ('lease', 'close', 'stop'):
            pub, consumer, clock, _, _, _ = self.transport()
            self.counts(assess_current_known_candidates(consumer, version=6), 6, 1)
            if mode == 'lease': clock.advance(501)
            elif mode == 'close': consumer.close()
            else:
                for event in pub.stop(): self.assertTrue(consumer.accept_event(event))
            self.counts(assess_current_known_candidates(consumer, version=6), 0, 0)
        _, consumer, clock, _, _, _ = self.transport(); original = associations.enumerate_associations
        def slow(*args, **kwargs):
            result = original(*args, **kwargs); clock.advance(501); return result
        with patch.object(associations, 'enumerate_associations', side_effect=slow):
            self.counts(assess_current_known_candidates(consumer, version=6), 0, 0)

    def test_synthetic_consumed_poll_and_later_history_never_revive_old_ref(self):
        pub, consumer, _, doc, meta, _ = self.transport()
        ref = consumer.current_view()['current_snapshot_ref']
        after = copy.deepcopy(self.fixture['after_response'])
        after['source'].update(mode='watch', phase='append', stopped=False)
        doc['decision_state'] = after
        meta.update(request_consumed=True, new_final_request=False)
        for event in pub.observe(doc, meta): self.assertTrue(consumer.accept_event(event))
        self.counts(assess_current_known_candidates(consumer, version=6), 0, 0)
        self.assertNotEqual(consumer.current_view()['current_snapshot_ref'], ref)
        for _ in range(2):
            for event in pub.observe(doc, meta): self.assertTrue(consumer.accept_event(event))
            self.counts(assess_current_known_candidates(consumer, version=6), 0, 0)
        for control in ('session', 'sequence', 'binding'):
            pub, consumer, _, doc, meta, _ = self.transport()
            event = copy.deepcopy(pub.observe(doc, meta)[-1])
            if control == 'session': event['session_id'] = 'synthetic-wrong'
            elif control == 'sequence': event['sequence'] += 1
            else: event['current_snapshot_ref']['binding']['request_id'] += 1
            self.assertFalse(consumer.accept_event(event))
            self.counts(assess_current_known_candidates(consumer, version=6), 0, 0)

    def test_synthetic_snapshot_ref_typed_binding_and_validator_ref_drift(self):
        _, consumer, _, _, _, _ = self.transport(); ref = consumer.current_view()['current_snapshot_ref']
        for mode in ('binding', 'boolean', 'sequence'):
            bad = copy.deepcopy(ref)
            if mode == 'binding': bad['binding']['request_id'] += 1
            elif mode == 'boolean': bad['binding']['source_generation'] = True
            else: bad['sequence'] = 0
            self.counts(self.report(source_snapshot_ref=bad), 0, 0)
        original = validate_proposed_choice
        def drift(*args, **kwargs):
            verdict = original(*args, **kwargs)
            if 'proposed_cast_target_member' in args[1]: verdict['source_snapshot_ref']['binding']['source_generation'] = True
            return verdict
        with patch('mtgaplayer.choice_validation.validate_proposed_choice', side_effect=drift):
            self.assertEqual(self.report(source_snapshot_ref=ref)['returned_candidates'], 0)

    def test_synthetic_consumer_owner_thread_and_final_output_expiry(self):
        pub, _, clock, _, _, events = self.transport(); events += pub.stop()
        owner = threading.get_ident(); threads = []; output = []
        original = associations.enumerate_associations
        def observe(*args, **kwargs):
            threads.append(threading.get_ident()); return original(*args, **kwargs)
        with patch.object(associations, 'enumerate_associations', side_effect=observe):
            self.assertEqual(consume_events(io.StringIO(''.join(json.dumps(e)+'\n' for e in events)), output.append,
                DecisionConsumer(10000, 500, clock), known_choice_candidates=True, known_choice_candidates_version=6), 0)
        self.assertTrue(threads); self.assertEqual(set(threads), {owner})
        self.assertTrue(any(v['known_choice_candidates']['returned_candidates'] == 6 for v in output))
        self.counts(output[-1]['known_choice_candidates'], 0, 0)
        pub, _, clock, _, _, events = self.transport(); events += pub.stop(); output = []
        original_assess = assess_current_known_candidates
        def late(*args, **kwargs):
            result = original_assess(*args, **kwargs)
            if result['returned_candidates']: clock.advance(501)
            return result
        with patch('mtgaplayer.choice_candidates.assess_current_known_candidates', side_effect=late):
            consume_events(io.StringIO(''.join(json.dumps(e)+'\n' for e in events)), output.append,
                DecisionConsumer(10000, 500, clock), known_choice_candidates=True, known_choice_candidates_version=6)
        self.assertTrue(output)
        for value in output: self.counts(value['known_choice_candidates'], 0, 0)

    def test_aggregate_recomputes_child_coverage_instead_of_trusting_consistent_counts(self):
        good = self.report()
        members = copy.deepcopy(good['cast_members'])
        members['candidates'] = members['candidates'][:3]
        members.update(returned_candidates=3, candidate_total_for_reviewed_constraints=3,
                       exhaustive_for_reviewed_constraints=True, truncated=False)
        members['member_probes'].update(observed=3, examined=3, verified=3, unknown=0,
                                       contradicted=0, unexamined=0, returned=3,
                                       omitted_due_to_return_limit=0)
        # All child arithmetic agrees, but the real current menus still offer
        # six probes. The omitted Cast3 family cannot disappear from coverage.
        with patch.object(cast, 'enumerate_members', return_value=members):
            self.counts(self.report(), 0, 0)
        relation = copy.deepcopy(good['activate_payment'])
        coverage = relation['action_row_coverage']
        coverage['contradicted_known_relation_rows'] = 5
        coverage['unknown_or_unreviewed_rows'] -= 5
        # The total remains17; the unchanged per-row statuses contradict the
        # supplied five contradicted rows and must independently invalidate it.
        with patch.object(activate, 'evaluate_relation', return_value=relation):
            self.counts(self.report(), 0, 0)

    def test_malformed_ref_cannot_be_laundered_through_mocked_child_reports(self):
        bad_ref = {'not': 'a snapshot ref'}
        members = associations.unknown_cast('synthetic_bad_ref', bad_ref)
        relation = copy.deepcopy(self.report()['activate_payment'])
        relation['source_snapshot_ref'] = copy.deepcopy(bad_ref)
        with patch.object(cast, 'enumerate_members', return_value=members) as cast_mock, \
                patch.object(activate, 'evaluate_relation', return_value=relation) as relation_mock:
            result = self.report(source_snapshot_ref=bad_ref)
        self.counts(result, 0, 0)
        self.assertIsNone(result['source_snapshot_ref'])
        self.assertIsNone(result['cast_members']['source_snapshot_ref'])
        self.assertIsNone(result['activate_payment']['source_snapshot_ref'])
        self.assertNotIn('a snapshot ref', json.dumps(result))
        # The outer reference gate runs before either child is consulted.
        cast_mock.assert_not_called()
        relation_mock.assert_not_called()

    def test_direct_v12_activate_and_tap_reject_forged_good_current_ability_binding(self):
        original = validate_proposed_choice
        for binding in ('insufficient_evidence', 'observed_group_contradiction'):
            state = copy.deepcopy(self.state)
            self.family(state, 'activate_payment')['rows'][6]['ability_binding'] = binding
            _state(state, state['binding'])
            seen_activate = []
            def forged(current, proposal, **kwargs):
                if 'proposed_activate_target_member' in proposal:
                    verdict = original(self.state, proposal, **kwargs)
                    self.assertEqual(verdict['known_constraints'], cast.GOOD)
                    seen_activate.append(True)
                    return verdict
                return original(current, proposal, **kwargs)
            with self.subTest(binding=binding), \
                    patch('mtgaplayer.choice_validation.validate_proposed_choice', side_effect=forged):
                relation = activate.evaluate_relation(state)
                self.assertEqual(relation['returned_relations'], 0)
                self.assertEqual(relation['relations'], [])
                self.assertNotEqual(relation['status'], activate.CONSISTENT)
                witness = evaluate_witness(state)
                self.assertEqual(witness['verified_source_count'], 0)
                self.assertIs(witness['untapped_pre_request_witness_verified'], False)
                self.assertIs(witness['overall_payability_verified'], False)
            self.assertTrue(seen_activate, 'the direct validator must reach the synthetic forged-GOOD control')

    def test_cli_optin_producer_from_explicitly_synthetic_bootstrap(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'synthetic-public-literals.jsonl'
            path.write_text(''.join(json.dumps(r)+'\n' for r in self.synthetic_bootstrap()), encoding='utf-8')
            run = subprocess.run([sys.executable, '-m', 'mtgaplayer', 'replay', str(path), '--format', 'player-log',
                '--decision-state-version', '12', '--known-choice-candidates', '--known-choice-candidates-version', '6'],
                capture_output=True, text=True, timeout=20)
            self.assertEqual(run.returncode, 0, run.stderr)
            result = json.loads(run.stdout)
            self.counts(result['known_choice_candidates'], 6, 1)
            self.assertEqual(result['decision_state']['legal_action_space']['request_parameters']['profile'], associations.PROFILE)
            old = replay(path, format='player-log', decision_state_version=11)
            old_params = old['decision_state']['legal_action_space']['request_parameters']
            self.assertTrue(old_params is None or old_params.get('profile') != associations.PROFILE)


if __name__ == '__main__':
    unittest.main()
