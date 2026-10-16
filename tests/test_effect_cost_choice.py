"""Real projected request-only state; raw/lifecycle mutations are synthetic controls."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from mtgaplayer.choice_validation import validate_proposed_choice, assess_current_choice, load_proposal
from mtgaplayer.cli import replay, watch_decision_events
from mtgaplayer.decision_consumer import DecisionConsumer, EXECUTION, _state
from mtgaplayer.request_parameters import EFFECT_COST_VERSION
from mtgaplayer.semantic_effect_cost import PROFILE
from mtgaplayer.semantic_samples import replay_samples
from test_decision_publisher import ManualClock, poll_events
from test_semantic_effect_cost import baseline, save, request, response, message

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT/'tests/fixtures/decision_state_effect_cost_real_v6.json'


class EffectCostChoiceTests(unittest.TestCase):
    def setUp(self):
        self.state = json.loads(FIXTURE.read_text(encoding='utf-8'))
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'controls.jsonl'

    def evidence(self, state=None):
        return (state or self.state)['legal_action_space']['request_parameters']

    def proposal(self, state=None, selected=None):
        state = state or self.state
        if selected is None:
            selected = [self.evidence(state)['cost_selection']['offered_object_refs'][0]]
        return {'request_identity': copy.deepcopy(state['binding']),
                'proposed_cost_selection': {'selected_object_refs': selected}}

    def result(self, state=None, selected=None):
        state = state or self.state
        return validate_proposed_choice(state, self.proposal(state, selected))

    def assert_unknown(self, result, reason=None):
        self.assertEqual(result['known_constraints'], 'insufficient_evidence')
        if reason:
            self.assertIn(reason, result['reasons'])
        self.assertTrue(all(result[key] is False for key in EXECUTION))

    def test_real_request_only_domain_and_known_subset_do_not_need_historical_response(self):
        evidence = self.evidence()
        self.assertEqual(evidence['schema_version'], EFFECT_COST_VERSION)
        self.assertEqual(evidence['profile'], PROFILE)
        self.assertFalse(evidence['historical_response_used'])
        domain = evidence['cost_selection']['offered_object_refs']
        self.assertEqual(len(domain), 16)
        for ref in domain:
            result = self.result(selected=[ref])
            self.assertEqual(result['known_constraints'], 'verified_known_constraints')
            self.assertEqual(result['validation_scope'], 'offered_visible_single_nonmana_selection_consistency')
            self.assertFalse(result['complete_costs_verified'])
            self.assertFalse(result['payment_completed_verified'])
            self.assertFalse(result['rules_effect_verified'])
            self.assertEqual(result['future_parameters'], 'unknown')
            self.assertIsNone(result['source_snapshot_ref'])
            self.assertTrue(all(result[key] is False for key in EXECUTION))
        self.assertIsNone(self.state['legal_action_space']['choice_graph'])
        self.assertEqual(self.state['legal_action_space']['immediate_frontier'],
            {'kind': None, 'availability': 'not_applicable', 'completeness': 'unknown', 'projection': None})
        self.assertIn('complete_payment_unknown', self.state['unresolved'])
        self.assertEqual(set(evidence), {'schema_version', 'profile', 'binding',
            'cost_selection', 'historical_response_used'})

    def test_historical_choice_is_separate_and_does_not_prove_other_outcomes(self):
        history = json.loads((FIXTURE.parent/'semantic_effect_cost_real_v7.json').read_text(encoding='utf-8'))
        report = replay_samples(history)['samples'][0]
        self.assertEqual(report['selected_option_positions'], [1])
        domain = self.evidence()['cost_selection']['offered_object_refs']
        # Both use only request-time facts. No historical outcome enters either result.
        for position in (0, 1):
            self.assertEqual(self.result(selected=[domain[position]])['known_constraints'], 'verified_known_constraints')
            self.assertFalse(self.result(selected=[domain[position]])['payment_completed_verified'])

    def test_quantity_repeat_and_membership_contradictions_are_known_violations(self):
        domain = self.evidence()['cost_selection']['offered_object_refs']
        for selected in ([], domain[:2], [domain[0], domain[0]], [999999]):
            with self.subTest(selected=selected):
                self.assertEqual(self.result(selected=selected)['known_constraints'], 'violated_known_constraints')
        for selected in ([True], [1.0], None):
            proposed = self.proposal(); proposed['proposed_cost_selection']['selected_object_refs'] = selected
            self.assert_unknown(validate_proposed_choice(self.state, proposed), 'proposal_or_state_invalid')

    def test_binding_and_visibility_are_evidence_gates_not_rules_verdicts(self):
        proposed = self.proposal(); proposed['request_identity']['request_id'] += 1
        self.assert_unknown(validate_proposed_choice(self.state, proposed), 'proposal_binding_invalid')
        for key, value in (('owner_seat', 2), ('controller_seat', 2), ('zone', 'ZoneType_Hand')):
            state = copy.deepcopy(self.state)
            first = self.evidence(state)['cost_selection']['offered_object_refs'][0]
            next(obj for obj in state['visible_objects'] if obj['instance_id'] == first)[key] = value
            self.assert_unknown(self.result(state), 'proposal_or_state_invalid')
        state = copy.deepcopy(self.state)
        state['visible_objects'].append(copy.deepcopy(state['visible_objects'][0]))
        self.assert_unknown(self.result(state), 'proposal_or_state_invalid')

    def test_raw_projection_preserves_legacy_v5_and_rejects_unsupported_whole_cost_shape(self):
        save(self.path, baseline()+[request()])
        state = replay(self.path, format='player-log', decision_state_version=6)['decision_state']
        self.assertEqual(self.evidence(state)['cost_selection']['offered_object_refs'], [701])
        self.assertEqual(self.result(state)['known_constraints'], 'verified_known_constraints')
        legacy = replay(self.path, format='player-log', decision_state_version=5)['decision_state']
        self.assertIsNone(self.evidence(legacy))
        self.assertEqual(state['game'], legacy['game'])
        self.assertEqual(state['visible_objects'], legacy['visible_objects'])
        for mutate in (
            lambda m: m['payCostsReq'].update(paymentActions={'PRIVATE_SENTINEL': []}),
            lambda m: m['payCostsReq']['effectCostReq']['costSelection'].update(weights=[2]),
            lambda m: m['payCostsReq']['effectCostReq']['costSelection'].update(ids=[704]),
        ):
            req = request(); mutate(message(req)); save(self.path, baseline()+[req])
            state = replay(self.path, format='player-log', decision_state_version=6)['decision_state']
            self.assertIsNone(self.evidence(state))
            self.assert_unknown(self.result(state, [701]), 'reviewed_request_parameters_not_observed')
            self.assertNotIn('PRIVATE_SENTINEL', json.dumps(state))

    def test_crossed_versions_and_elevated_or_future_evidence_cannot_enter_consumer(self):
        for mutate in (
            lambda s: s.update(schema_version='mtgaplayer.decision-state.v5'),
            lambda s: self.evidence(s).update(schema_version='mtgaplayer.request-parameters.v2'),
            lambda s: self.evidence(s).update(historical_response_used=True),
            lambda s: self.evidence(s)['cost_selection'].update(future_result=True),
            lambda s: s['execution'].update(execution_ready=True),
        ):
            state = copy.deepcopy(self.state); mutate(state)
            self.assert_unknown(self.result(state), 'proposal_or_state_invalid')

    def test_existing_current_consumer_revokes_cost_on_response_without_last_valid_fallback(self):
        save(self.path, baseline())
        stream = watch_decision_events(self.path, interval=0, samples=4,
            clock_ns=ManualClock(), session_id='cost-current', decision_state_version=6)
        self.addCleanup(stream.close)
        history = poll_events(stream)
        with self.path.open('a', encoding='utf-8') as out: out.write(json.dumps(request())+'\n')
        events = poll_events(stream)
        consumer = DecisionConsumer()
        for event in history+events:
            self.assertTrue(consumer.accept_event(event))
        state = consumer.current_view()['decision_state']
        proposal = self.proposal(state)
        self.assertEqual(assess_current_choice(consumer, proposal)['known_constraints'], 'verified_known_constraints')
        with self.path.open('a', encoding='utf-8') as out: out.write(json.dumps(response())+'\n')
        for event in poll_events(stream):
            self.assertTrue(consumer.accept_event(event))
        self.assert_unknown(assess_current_choice(consumer, proposal), 'current_request_not_observed')

    def test_existing_lease_recheck_and_history_gate_apply_to_cost_profile(self):
        save(self.path, baseline()+[request()])
        stream = watch_decision_events(self.path, interval=0, samples=2,
            clock_ns=ManualClock(), session_id='cost-expiry', decision_state_version=6)
        self.addCleanup(stream.close)
        event = next(e for e in poll_events(stream) if e['event_type'] == 'snapshot')
        clock = ManualClock(100); consumer = DecisionConsumer(10000, 500, clock)
        self.assertTrue(consumer.accept_event(event))
        proposal = self.proposal(event['decision_state'])
        self.assert_unknown(assess_current_choice(consumer, proposal), 'current_request_not_observed')
        event['phase'] = event['decision_state']['source']['phase'] = 'append'
        event['new_request_observed'] = True
        event['sequence'] = event['snapshot_ref']['sequence'] = 1
        consumer = DecisionConsumer(10000, 500, clock)
        self.assertTrue(consumer.accept_event(event))
        original = validate_proposed_choice
        def slow(*args, **kwargs):
            result = original(*args, **kwargs); clock.advance(501); return result
        with patch('mtgaplayer.choice_validation.validate_proposed_choice', side_effect=slow):
            self.assert_unknown(assess_current_choice(consumer, proposal), 'current_snapshot_expired_or_changed')

    def test_cost_loader_accepts_only_structural_contract_and_keeps_contradictions(self):
        for selected in ([], [999999]):
            proposal = self.proposal(selected=selected)
            self.path.write_text(json.dumps(proposal), encoding='utf-8')
            self.assertEqual(load_proposal(self.path), proposal)
        proposal = self.proposal(); proposal['proposed_cost_selection']['selected_object_refs'] = [True]
        self.path.write_text(json.dumps(proposal), encoding='utf-8')
        with self.assertRaises(ValueError): load_proposal(self.path)

    def test_v6_formal_contracts_reuse_local_v5_and_strict_cost_fields(self):
        state = json.loads((ROOT/'schemas/decision-state.v6.schema.json').read_text(encoding='utf-8'))
        event = json.loads((ROOT/'schemas/decision-event.v6.schema.json').read_text(encoding='utf-8'))
        old = json.loads((ROOT/'schemas/decision-state.v5.schema.json').read_text(encoding='utf-8'))
        self.assertEqual(set(state['required']), set(self.state))
        selection = state['$defs']['effectCostSelection']
        self.assertEqual(set(selection['required']), set(self.evidence()['cost_selection']))
        self.assertFalse(selection['additionalProperties'])
        docs = {doc['$id']: doc for doc in (state, event, old)}
        def walk(node):
            if isinstance(node, dict):
                yield node
                for value in node.values(): yield from walk(value)
            elif isinstance(node, list):
                for value in node: yield from walk(value)
        for doc in (state, event):
            for node in walk(doc):
                if '$ref' not in node: continue
                urn, _, pointer = node['$ref'].partition('#')
                target = docs[urn] if urn else doc
                for part in pointer.strip('/').split('/') if pointer else []:
                    target = target[int(part)] if isinstance(target, list) else target[part]
        _state(self.state, self.state['binding'])
