"""Research admission, with invented action bodies on retained real state."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from mtgaplayer.cli import replay, watch_decision_events
from mtgaplayer.decision_advisor import assess_current_decision, assess_decision_state, SIMPLE_TYPE_POLICY
from mtgaplayer.decision_consumer import DecisionConsumer
from test_action_frontier import frames, save
from test_decision_advisor import PASS, PLAY
from test_decision_consumer import encoded
from test_decision_publisher import ManualClock, append, poll_events
from test_decision_state import action_message


class RequestEvidenceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / 'invented-request.jsonl'

    def chain(self, mutate=lambda message: None, version=1):
        data = frames()
        message = action_message(data[-1])
        message['actionsAvailableReq'] = {'actions': [copy.deepcopy(PASS), copy.deepcopy(PLAY)]}
        mutate(message)
        save(self.path, data[:-1])
        stream = watch_decision_events(self.path, interval=0, samples=3,
            clock_ns=ManualClock(), session_id='request-evidence', decision_state_version=version)
        self.addCleanup(stream.close)
        events = poll_events(stream)
        append(self.path, [data[-1]])
        events += poll_events(stream)
        snapshot = next(e for e in events if e['event_type'] == 'snapshot' and e['new_request_observed'])
        return events + list(stream), snapshot

    def advice(self, snapshot):
        snapshot = copy.deepcopy(snapshot)
        snapshot['sequence'] = snapshot['snapshot_ref']['sequence'] = 1
        c = DecisionConsumer(clock_ns=ManualClock())
        accepted = c.accept_event(snapshot)
        return accepted, assess_current_decision(c, policy_version=SIMPLE_TYPE_POLICY)

    def test_request_unknowns_and_source_identity_through_actual_cli(self):
        for version in (1, 2):
            for where in ('none', 'payload', 'envelope', 'card_conflict'):
                def mutate(message):
                    if where == 'payload':
                        message['actionsAvailableReq']['PRIVATE_KEY'] = {'value': 'PRIVATE_VALUE'}
                    elif where == 'envelope':
                        message['PRIVATE_KEY'] = 'PRIVATE_VALUE'
                    elif where == 'card_conflict':
                        message['actionsAvailableReq']['actions'][1]['grpId'] = 99999
                events, snapshot = self.chain(mutate, version)
                state = snapshot['decision_state']
                projection = state['legal_action_space']['immediate_frontier']['projection']
                self.assertIs(projection['unknown_request_fields_present'], where in ('payload', 'envelope'))
                self.assertIs(projection['templates'][1]['source_card_identity_agreement'], where != 'card_conflict')
                run = subprocess.run([sys.executable, '-m', 'mtgaplayer', 'consume-events',
                    '--advice', '--advice-policy', SIMPLE_TYPE_POLICY], input=encoded(events),
                    capture_output=True, text=True, timeout=10)
                self.assertEqual(run.returncode, 0, run.stderr)
                reports = [json.loads(line)['decision_advice'] for line in run.stdout.splitlines()]
                current = next(a for a in reports if a['candidate_coverage']['assessed_count'] == 2)
                self.assertEqual(current['assessment_status'], 'research_preference' if where == 'none' else 'abstain')
                self.assertEqual(current['candidate_coverage']['offered_count'], 2)
                self.assertTrue(current['candidate_coverage']['inventory_integrity_verified'])
                self.assertEqual(current['candidate_assessments'][1]['highest_evidence_level'], 'LA2')
                self.assertEqual(current['source_snapshot_ref'], snapshot['snapshot_ref'])
                self.assertIsNone(reports[-1]['preferred_candidate'])
                self.assertNotIn('PRIVATE_', json.dumps(events) + run.stdout)

    def test_legacy_missing_or_unknown_markers_never_grant_preference(self):
        _, snapshot = self.chain()
        for field in ('unknown_request_fields_present', 'source_card_identity_agreement'):
            for mode in ('missing', 'null', 'false' if field.startswith('source') else 'true'):
                event = copy.deepcopy(snapshot)
                projection = event['decision_state']['legal_action_space']['immediate_frontier']['projection']
                owner = projection if field.startswith('unknown') else projection['templates'][1]
                if mode == 'missing':
                    owner.pop(field)
                else:
                    owner[field] = {'null': None, 'false': False, 'true': True}[mode]
                accepted, advice = self.advice(event)
                self.assertTrue(accepted)
                self.assertIsNone(advice['preferred_candidate'])
                self.assertEqual(advice['candidate_coverage']['assessed_count'], 2)
        # JSON numbers must never masquerade as boolean evidence.
        for field in ('unknown_request_fields_present', 'source_card_identity_agreement'):
            event = copy.deepcopy(snapshot)
            p = event['decision_state']['legal_action_space']['immediate_frontier']['projection']
            (p if field.startswith('unknown') else p['templates'][1])[field] = 0
            self.assertFalse(self.advice(event)[0])

    def test_instance_link_survives_conflict_and_ability_group_is_not_card_id(self):
        def mutate(message):
            actions = message['actionsAvailableReq']['actions']
            actions[1]['grpId'] = 99999
            actions.append({'actionType': 'ActionType_Activate_Mana', 'instanceId': 283, 'abilityGrpId': 7})
        _, snapshot = self.chain(mutate)
        p = snapshot['decision_state']['legal_action_space']['immediate_frontier']['projection']
        self.assertEqual(p['templates'][1]['visible_object_id'], 166)
        self.assertEqual(p['templates'][1]['source_link_status'], 'visible_unique')
        self.assertIs(p['templates'][1]['source_card_identity_agreement'], False)
        self.assertIsNone(p['templates'][2]['source_card_identity_agreement'])
        default = replay(self.path, format='player-log')
        self.assertNotIn('decision_state', default)
        self.assertNotIn('decision_input', default)

    def test_lease_still_revokes_research_and_source_evidence(self):
        _, snapshot = self.chain()
        snapshot['sequence'] = snapshot['snapshot_ref']['sequence'] = 1
        clock = ManualClock()
        c = DecisionConsumer(100, 100, clock)
        self.assertTrue(c.accept_event(snapshot))
        self.assertIsNotNone(assess_current_decision(c, policy_version=SIMPLE_TYPE_POLICY)['preferred_candidate'])
        clock.advance(101_000_000)
        advice = assess_current_decision(c, policy_version=SIMPLE_TYPE_POLICY)
        self.assertIsNone(advice['source_snapshot_ref'])
        self.assertEqual(advice['candidate_assessments'], [])

    def test_malformed_rows_revoke_existing_cache_without_raising(self):
        _, snapshot = self.chain()
        snapshot['sequence'] = snapshot['snapshot_ref']['sequence'] = 1
        for malformed in (None, 1, [], 'bad'):
            c = DecisionConsumer(clock_ns=ManualClock())
            self.assertTrue(c.accept_event(snapshot))
            bad = copy.deepcopy(snapshot)
            bad['sequence'] = bad['snapshot_ref']['sequence'] = 2
            bad['decision_state']['legal_action_space']['immediate_frontier']['projection']['templates'][0] = malformed
            self.assertFalse(c.accept_event(bad))
            view = c.current_view()
            self.assertEqual(view['consumer_status'], 'PROTOCOL_ERROR')
            self.assertIsNone(view['decision_state'])
            self.assertIsNone(view['current_snapshot_ref'])
            self.assertEqual(assess_decision_state(bad['decision_state'])['assessment_status'], 'abstain')
