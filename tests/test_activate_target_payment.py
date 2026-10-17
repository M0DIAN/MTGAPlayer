"""One real portable request; all mutations and transport controls are synthetic."""
import copy
import io
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from mtgaplayer.activate_target_payment import evaluate_relation, assess_current_relation, VERSION, CONSISTENT
from mtgaplayer.decision_consumer import DecisionConsumer, EXECUTION, consume_events, _state
from mtgaplayer.decision_publisher import DecisionPublisher
from mtgaplayer.choice_candidates import enumerate_known_candidates
from mtgaplayer.decision_advisor import assess_decision_state
from test_decision_publisher import ManualClock

FIXTURE = Path(__file__).parent / 'fixtures/activate_target_payment_real_v9.json'


class TargetPaymentTests(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads(FIXTURE.read_text(encoding='utf-8'))
        self.state = self.fixture['before_response']

    def params(self, state):
        return state['legal_action_space']['request_parameters']

    def no_relation(self, result):
        self.assertEqual(result['schema_version'], VERSION)
        self.assertEqual(result['returned_relations'], 0)
        self.assertEqual(result['relations'], [])
        self.assertEqual(result['status'], 'insufficient_evidence')
        self.assertTrue(result['diagnostics_only'])
        self.assertTrue(all(result[k] is False for k in EXECUTION))

    def transport(self, history=False):
        clock = ManualClock()
        pub = DecisionPublisher(clock_ns=clock, session_id='synthetic-joint', state_version=9)
        state = copy.deepcopy(self.state)
        state['source'].update(mode='watch', phase='history' if history else 'append', stopped=False)
        doc = {'decision_state': state, 'source': {'phase': state['source']['phase'], 'partial_record': False}}
        meta = {'poll_started_ns': clock(), 'poll_completed_ns': clock(), 'poll_read_ns': 0, 'reducer_apply_ns': 0,
                'decision_state_assembly_ns': 0, 'request_changed': True, 'new_final_request': True}
        events = pub.observe(doc, meta)
        consumer = DecisionConsumer(10000, 500, clock)
        for event in events:
            self.assertTrue(consumer.accept_event(event))
        return pub, consumer, clock, doc, meta, events

    def test_real_same_request_rows_join_without_payability_or_post_response(self):
        original = copy.deepcopy(self.state)
        result = evaluate_relation(self.state)
        self.assertEqual(result['status'], CONSISTENT)
        self.assertEqual(result['returned_relations'], 1)
        relation = result['relations'][0]
        self.assertEqual(relation['list_position'], 6)
        self.assertEqual([r['list_position'] for r in relation['mana_row_witnesses']], [12, 14])
        self.assertEqual([r['current_tapped_literal'] for r in relation['mana_row_witnesses']], [None, None])
        self.assertEqual(result['action_row_coverage']['engine_active_action_rows'], 17)
        self.assertEqual(result['action_row_coverage']['consistent_relation_rows'], 1)
        self.assertEqual(result['action_row_coverage']['unknown_or_unreviewed_rows'], 16)
        for key in ('payment_source_untapped_verified', 'overall_payability_verified', 'complete_costs_verified',
                    'complete_payment_verified', 'full_action_domain_complete', 'target_quantity_verified',
                    'target_domain_complete_verified', 'target_selection_legality_verified', 'rules_effect_verified',
                    'historical_response_used', 'raw_source_reauthenticated', *EXECUTION):
            self.assertIs(result[key], False, key)
        self.assertEqual(result['payment_source_readiness'], 'unknown_not_evaluated')
        self.assertIsNone(result['source_snapshot_ref'])
        self.assertEqual(self.state, original)
        self.no_relation(evaluate_relation(self.fixture['after_response']))
        self.assertNotIn('candidates', result)
        self.assertNotIn('proposal', result)
        self.assertEqual(assess_decision_state(self.state)['assessment_status'], 'abstain')

    def test_tap_readiness_is_separate_from_predictive_association(self):
        for tapped in (None, True, False):
            state = copy.deepcopy(self.state)
            for record in self.params(state)['mana_actions']:
                ident = record['action']['identifier_refs']['instanceId']
                next(o for o in state['visible_objects'] if o['instance_id'] == ident)['tapped'] = tapped
            result = evaluate_relation(state)
            self.assertEqual(result['returned_relations'], 1)
            self.assertFalse(result['payment_source_untapped_verified'])
            self.assertFalse(result['overall_payability_verified'])
            self.assertEqual(result['payment_source_readiness'], 'unknown_not_evaluated')

    def test_graph_requires_typed_full_identifiers_and_all_observed_flags(self):
        for position, field, group in ((6, 'shouldStop', 'target_actions'), (12, 'isBatchable', 'mana_actions')):
            state = copy.deepcopy(self.state); p = self.params(state)
            p['rows'][position]['flags'][field] = False
            next(r for r in p[group] if r['list_position'] == position)['action']['flags'][field] = False
            with self.assertRaises(ValueError): _state(state, state['binding'])
            self.no_relation(evaluate_relation(state))
        for mode in ('float', 'boolean', 'missing_flag'):
            state = copy.deepcopy(self.state)
            identity = next(n for n in state['legal_action_space']['choice_graph']['action_nodes']
                            if n['action_key']['list_position'] == 6)['action_identity']
            if mode == 'float': identity['raw_identifiers']['instance_id'] = float(identity['raw_identifiers']['instance_id'])
            elif mode == 'boolean': identity['raw_identifiers']['instance_id'] = True
            else: identity['raw_flags_observed_not_discriminators'] = {}
            self.no_relation(evaluate_relation(state))

    def test_target_identity_slot_member_pair_and_row_cannot_be_borrowed(self):
        for mode in ('position', 'identifier', 'slot', 'member', 'pair', 'duplicate', 'extra'):
            state = copy.deepcopy(self.state); p = self.params(state); r = p['target_actions'][0]
            if mode == 'position': r['list_position'] = 5
            elif mode == 'identifier': r['action']['identifier_refs']['uniqueAbilityId'] += 1
            elif mode == 'slot': r['action']['parameters']['targets'][0]['targetIdx'] += 1
            elif mode == 'member': r['action']['parameters']['targets'][0]['targets'][0]['targetInstanceId'] += 1
            elif mode == 'pair':
                p['rows'][6]['ability_binding'] = 'insufficient_evidence'
                _state(state, state['binding'])
            elif mode == 'duplicate': p['target_actions'].append(copy.deepcopy(r))
            else: r['action']['parameters']['future'] = 'PRIVATE_SENTINEL'
            result = evaluate_relation(state); self.no_relation(result)
            self.assertNotIn('PRIVATE_SENTINEL', json.dumps(result))

    def test_predictive_cost_source_units_option_selection_and_pair_controls(self):
        for mode in ('cost_count', 'cost_color', 'cost_group', 'duplicate_source', 'duplicate_unit', 'unit_source',
                     'unit_group', 'unit_color', 'unit_count', 'spec', 'option', 'selection', 'unknown_pair', 'missing_row'):
            with self.subTest(mode=mode):
                state = copy.deepcopy(self.state); p = self.params(state)
                params = p['target_actions'][0]['action']['parameters']; taps = params['autoTapSolution']['autoTapActions']
                unit = taps[0]['manaPaymentOption']['mana'][0]
                if mode == 'cost_count': params['manaCost'][0]['count'] = 3
                elif mode == 'cost_color': params['manaCost'][0]['color'] = ['ManaColor_White']
                elif mode == 'cost_group': params['manaCost'][0]['abilityGrpId'] += 1
                elif mode == 'duplicate_source': taps[1] = copy.deepcopy(taps[0])
                elif mode == 'duplicate_unit': taps[1]['manaPaymentOption']['mana'][0]['manaId'] = unit['manaId']
                elif mode == 'unit_source': unit['srcInstanceId'] += 1
                elif mode == 'unit_group': unit['abilityGrpId'] += 1
                elif mode == 'unit_color': unit['color'] = 'ManaColor_Red'
                elif mode == 'unit_count': unit['count'] = 2
                elif mode == 'spec': unit['specs'][0]['type'] = 'unsupported'
                elif mode == 'option': p['mana_actions'][0]['action']['parameters']['manaPaymentOptions'][0]['mana'][0]['manaId'] += 1
                elif mode == 'selection': p['mana_actions'][0]['action']['parameters']['manaSelections'][0]['options'][0]['mana'][0]['color'] = 'ManaColor_Red'
                elif mode == 'unknown_pair': p['mana_actions'][0]['ability_binding'] = 'insufficient_evidence'
                else: p['mana_actions'].pop()
                self.no_relation(evaluate_relation(state))

    def test_sources_and_target_require_own_unique_current_public_battlefield_objects(self):
        p = self.params(self.state)
        ids = [r['action']['identifier_refs']['instanceId'] for r in p['mana_actions']]
        ids.append(p['target_actions'][0]['action']['parameters']['targets'][0]['targets'][0]['targetInstanceId'])
        for ident in ids:
            for mode in ('missing', 'duplicate', 'foreign_owner', 'foreign_controller', 'boolean_owner', 'not_public', 'zone'):
                state = copy.deepcopy(self.state)
                obj = next(o for o in state['visible_objects'] if o['instance_id'] == ident)
                if mode == 'missing': state['visible_objects'].remove(obj)
                elif mode == 'duplicate': state['visible_objects'].append(copy.deepcopy(obj))
                elif mode == 'foreign_owner': obj['owner_seat'] = 3-state['binding']['self_seat']
                elif mode == 'foreign_controller': obj['controller_seat'] = 3-state['binding']['self_seat']
                elif mode == 'boolean_owner': obj['owner_seat'] = True
                elif mode == 'not_public': self.params(state)['public_battlefield_refs'].remove(ident)
                else: obj['zone'] = 'ZoneType_Graveyard'
                self.no_relation(evaluate_relation(state))

    def test_coherent_reused_unit_duplicate_options_selections_and_ambiguous_mana_row(self):
        from mtgaplayer.raw_log import _frontier_row
        from mtgaplayer.semantic_activate import raw_action
        for mode in ('unit', 'options', 'selections', 'ambiguous'):
            state = copy.deepcopy(self.state); p = self.params(state)
            target = p['target_actions'][0]['action']; mana = p['mana_actions']
            if mode == 'unit':
                taps = target['parameters']['autoTapSolution']['autoTapActions']
                ident = taps[0]['manaPaymentOption']['mana'][0]['manaId']
                taps[1]['manaPaymentOption']['mana'][0]['manaId'] = ident
                mana[1]['action']['parameters']['manaPaymentOptions'][0]['mana'][0]['manaId'] = ident
            elif mode in ('options', 'selections'):
                field = 'manaPaymentOptions' if mode == 'options' else 'manaSelections'
                params = mana[0]['action']['parameters']; params[field].append(copy.deepcopy(params[field][0]))
                shapes = _frontier_row(12, 'ActionType_Activate_Mana', raw_action(mana[0]['action']))['known_parameter_shapes']
                p['rows'][12]['parameter_shapes'] = shapes
                state['legal_action_space']['immediate_frontier']['projection']['templates'][12]['observed_parameter_shapes'] = copy.deepcopy(shapes)
            else:
                p['rows'][13] = copy.deepcopy(p['rows'][12]); p['rows'][13]['list_position'] = 13
                graph = state['legal_action_space']['choice_graph']
                node12 = next(n for n in graph['action_nodes'] if n['action_key']['list_position'] == 12)
                node13 = next(n for n in graph['action_nodes'] if n['action_key']['list_position'] == 13)
                node13['action_identity'] = copy.deepcopy(node12['action_identity'])
                template = state['legal_action_space']['immediate_frontier']['projection']['templates'][13]
                template['visible_object_id'] = mana[0]['action']['identifier_refs']['instanceId']
            _state(state, state['binding'])  # Reach relation checks with a valid envelope.
            self.no_relation(evaluate_relation(state))

    def test_projection_keeps_targets_and_requires_exact_current_source_pairs(self):
        from mtgaplayer.request_parameters import project
        from mtgaplayer.semantic_activate import raw_action
        from mtgaplayer.activate_target_payment import PROFILE
        p = self.params(self.state); records = p['target_actions']+p['mana_actions']
        raw = [raw_action(r['action']) for r in records]
        raw[0]['targets'][0]['targets'][0]['highlight'] = 'presentation only'
        message = {'type': 'GREMessageType_ActionsAvailableReq', 'systemSeatIds': [1], 'msgId': 1,
                   'gameStateId': 1, 'actionsAvailableReq': {'actions': raw}}
        visible = copy.deepcopy(self.state['visible_objects']); abilities = {}
        for record in records:
            ids = record['action']['identifier_refs']
            next(o for o in visible if o['instance_id'] == ids['instanceId'])['card_id'] = ids['grpId']
            abilities[ids['instanceId']] = [{'id': ids['uniqueAbilityId'], 'grpId': ids['abilityGrpId']}]
        result = project(message, visible, 1, abilities, targeted_activate=True,
                         public_battlefield_refs=p['public_battlefield_refs'], target_payment_relation=True)
        self.assertEqual(result['profile'], PROFILE)
        self.assertEqual(len(result['target_actions']), 1); self.assertEqual(len(result['mana_actions']), 2)
        self.assertIn('targets', result['target_actions'][0]['action']['parameters'])
        self.assertNotIn('highlight', json.dumps(result['target_actions']))
        changed = copy.deepcopy(message); changed['actionsAvailableReq']['actions'][0]['futureCost'] = [1]
        other = project(changed, visible, 1, abilities, targeted_activate=True,
                        public_battlefield_refs=p['public_battlefield_refs'], target_payment_relation=True)
        self.assertEqual(other['target_actions'], [])

    def test_cross_binding_version_status_and_historical_fields_fail_closed(self):
        for key in self.state['binding']:
            state = copy.deepcopy(self.state); value = state['binding'][key]
            state['binding'][key] = 'different' if type(value) is str else value+1
            self.no_relation(evaluate_relation(state))
        for mode in ('version', 'history', 'status', 'profile', 'empty'):
            state = copy.deepcopy(self.state)
            if mode == 'version': state['schema_version'] = 'mtgaplayer.decision-state.v8'
            elif mode == 'history': self.params(state)['historical_response_used'] = True
            elif mode == 'status': state['status'] = 'state_observed_without_request'
            elif mode == 'profile': self.params(state)['profile'] = 'unknown'
            else: self.params(state)['target_actions'] = []
            self.no_relation(evaluate_relation(state))

    def test_validator_drift_including_optional_deny_fields_and_oversize_is_rejected(self):
        from mtgaplayer import choice_validation, decision_consumer
        original = choice_validation.validate_proposed_choice
        fields = ('mana_payment_verified', 'rules_effect_verified', 'overall_payability_verified',
                  'payment_source_untapped_verified', 'complete_target_legality_verified', 'full_action_domain_complete',
                  'global_restrictions_verified', 'target_quantity_completeness_verified', 'payment_completed_verified')
        for key, value in [('schema_version', 'unknown'), ('validation_scope', 'wrong'), ('read_only', 1),
                           ('complete_payment_verified', 0), ('input_sent', True), *[(k, True) for k in fields]]:
            def changed(*args, **kwargs):
                result = original(*args, **kwargs); result[key] = value; return result
            with patch.object(choice_validation, 'validate_proposed_choice', side_effect=changed):
                self.no_relation(evaluate_relation(self.state))
        _, consumer, _, _, _, _ = self.transport(); ref = consumer.current_view()['current_snapshot_ref']
        def boolean_ref(*args, **kwargs):
            result = original(*args, **kwargs); result['source_snapshot_ref']['binding']['source_generation'] = True; return result
        with patch.object(choice_validation, 'validate_proposed_choice', side_effect=boolean_ref):
            self.no_relation(evaluate_relation(self.state, source_snapshot_ref=ref))
        bound = decision_consumer._bounded_json
        def small(value):
            bound(value)
            if type(value) is dict and value.get('schema_version') == VERSION: raise ValueError('synthetic_size_limit')
        with patch.object(decision_consumer, '_bounded_json', side_effect=small): self.no_relation(evaluate_relation(self.state))

    def test_history_expiry_stop_and_expiry_during_calculation_revoke_relation(self):
        _, consumer, _, _, _, _ = self.transport(history=True); self.no_relation(assess_current_relation(consumer))
        pub, consumer, clock, _, _, _ = self.transport()
        self.assertEqual(assess_current_relation(consumer)['returned_relations'], 1)
        clock.advance(501); self.no_relation(assess_current_relation(consumer))
        pub, consumer, _, _, _, _ = self.transport()
        for event in pub.stop(): self.assertTrue(consumer.accept_event(event))
        self.no_relation(assess_current_relation(consumer))
        from mtgaplayer import activate_target_payment
        _, consumer, clock, _, _, _ = self.transport(); original = evaluate_relation
        def slow(*args, **kwargs):
            result = original(*args, **kwargs); clock.advance(501); return result
        with patch.object(activate_target_payment, 'evaluate_relation', side_effect=slow): self.no_relation(assess_current_relation(consumer))

    def test_consumption_supersession_partial_reset_gap_wrong_session_revoke_relation(self):
        for mode in ('consumed', 'replacement', 'partial', 'reset', 'gap', 'session'):
            pub, consumer, _, doc, meta, _ = self.transport()
            if mode in ('session', 'gap'):
                event = copy.deepcopy(pub.observe(doc, meta)[-1])
                if mode == 'session': event['session_id'] = 'wrong'
                else: event['sequence'] += 1
                self.assertFalse(consumer.accept_event(event))
            else:
                if mode == 'consumed':
                    state = copy.deepcopy(self.fixture['after_response']); state['source'].update(mode='watch', phase='append', stopped=False)
                    doc['decision_state'] = state; meta = dict(meta, request_consumed=True, new_final_request=False)
                elif mode == 'replacement':
                    def replace(value):
                        if type(value) is dict: return {k: (v+1 if k == 'request_id' and type(v) is int else replace(v)) for k, v in value.items()}
                        if type(value) is list: return [replace(v) for v in value]
                        return value
                    doc['decision_state'] = replace(doc['decision_state']); meta = dict(meta, new_final_request=False)
                else:
                    doc = {'decision_state': None, 'current': {}, 'source': {'phase': 'append', 'partial_record': mode == 'partial'}}
                    meta = dict(meta, source_reset=mode == 'reset', continuity_error=True, new_final_request=False)
                for event in pub.observe(doc, meta): self.assertTrue(consumer.accept_event(event))
            self.no_relation(assess_current_relation(consumer))

    def test_consumer_rechecks_after_all_sidecars_and_preserves_diagnostic_schema(self):
        from mtgaplayer import activate_target_payment
        pub, _, clock, _, _, events = self.transport(); events += pub.stop()
        original = activate_target_payment.assess_current_relation; advanced = False; seen = []
        def slow(consumer):
            nonlocal advanced
            result = original(consumer); seen.append(result['schema_version'])
            if result['returned_relations'] and not advanced: clock.advance(501); advanced = True
            return result
        output = []
        with patch.object(activate_target_payment, 'assess_current_relation', side_effect=slow):
            code = consume_events(io.StringIO(''.join(json.dumps(e)+'\n' for e in events)), output.append,
                                  DecisionConsumer(10000, 500, clock), activate_target_payment_relation=True)
        # Expiry terminates the consumer as stale before the queued stop event.
        self.assertEqual(code, 1); self.assertGreaterEqual(len(seen), 2); self.assertEqual(set(seen), {VERSION})
        self.assertTrue(all(v['activate_target_payment_relation']['returned_relations'] == 0 for v in output))

    def test_cli_is_explicit_diagnostic_has_no_candidate_or_manual_input_and_stops(self):
        pub, _, _, _, _, events = self.transport(); events += pub.stop()
        run = subprocess.run([sys.executable, '-m', 'mtgaplayer', 'consume-events', '--activate-target-payment-relation'],
                             input=''.join(json.dumps(e)+'\n' for e in events), capture_output=True, text=True, timeout=20)
        self.assertEqual(run.returncode, 0, run.stderr)
        values = [json.loads(line) for line in run.stdout.splitlines()]
        self.assertTrue(any(v['activate_target_payment_relation']['returned_relations'] == 1 for v in values))
        self.no_relation(values[-1]['activate_target_payment_relation'])
        self.assertTrue(all(v['activate_target_payment_relation']['schema_version'] == VERSION for v in values))
        self.assertTrue(all('choice_validation' not in v and 'known_choice_candidates' not in v for v in values))
        from mtgaplayer.cli import replay
        for version in (1, 8):
            with self.assertRaises(ValueError): replay(FIXTURE, format='player-log', decision_state_version=version, activate_target_payment_relation=True)

    def test_candidate_contract_stays_v2_v3_v4_and_defaults_are_unchanged(self):
        for version in (2, 3, 4):
            result = enumerate_known_candidates(self.state, version=version)
            self.assertEqual(result['returned_candidates'], 0)
        with self.assertRaises(ValueError): enumerate_known_candidates(self.state, version=5)
        pub, _, _, _, _, events = self.transport(); events += pub.stop(); output = []
        self.assertEqual(consume_events(io.StringIO(''.join(json.dumps(e)+'\n' for e in events)), output.append), 0)
        self.assertTrue(all('activate_target_payment_relation' not in v for v in output))


if __name__ == '__main__': unittest.main()
