"""Labeled synthetic timelines reuse sanitized real protocol envelopes/state.

These tests establish the offline classification contract, not a new live run.
The private real eight-marker replay is retained only under ignored artifacts.
"""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from mtgaplayer.observation_timeline import analyze_timeline, analyze_snapshot
from mtgaplayer import semantic_samples
from test_response_evidence import source_rows, action_request, reply, save

PASS = {'actionType': 'ActionType_Pass'}
CAST = {'actionType': 'ActionType_Cast', 'instanceId': 161, 'grpId': 987654,
        'facetId': 0, 'shouldStop': False}


def marker(kind='pass_priority', begin=2_100_000_000, end=3_100_000_000):
    return [{'event_id': 'before', 'event_type': kind, 'phase': 'before', 'monotonic_ns': begin,
             'note': 'PRIVATE_NOTE_SENTINEL'},
            {'event_id': 'after', 'event_type': kind, 'phase': 'after', 'monotonic_ns': end}]


def wrapped(batches):
    records, journal = [], []
    for poll_id, entries in enumerate(batches, 1):
        collected = {'monotonic_ns': poll_id * 1_000_000_000}
        for index, entry in enumerate(entries):
            records.append({'record_id': len(records) + 1, 'record_index_in_poll': index,
                'poll_id': poll_id, 'collected': collected,
                'source': {'generation': 1}, 'entry': copy.deepcopy(entry)})
        journal.append({'event': 'poll_complete', 'poll_id': poll_id, 'reset': poll_id == 1,
            'source': {'generation': 1}, 'partial_record': False, 'framing_errors': 0,
            'log_acquired': collected, 'poll_started': {'monotonic_ns': (poll_id - 1) * 1_000_000_000},
            'poll_completed': collected})
    return records, journal


def case(offered=None, selected=None, tail=()):
    return wrapped([source_rows()[:9], [action_request(offered or [PASS])],
                    [reply(details={'actions': [selected or PASS]})], *(tail or [[]])])


def next_request(msg_id, state_id):
    request = copy.deepcopy(action_request([PASS], msg_id=msg_id)['greToClientEvent']['greToClientMessages'][-1])
    request['gameStateId'] = state_id
    return request


def state(state_id, previous, phase):
    return {'type': 'GREMessageType_GameStateMessage', 'systemSeatIds': [1],
        'gameStateMessage': {'type': 'GameStateType_Diff', 'gameStateId': state_id,
            'prevGameStateId': previous, 'turnInfo': {'turnNumber': 12, 'activePlayer': 1,
                'decisionPlayer': 1, 'priorityPlayer': 1, 'phase': phase,
                'step': 'Step_BeginCombat' if phase == 'Phase_Combat' else 'Step_None'}}}


class ObservationTimelineTests(unittest.TestCase):
    def analyze(self, records, journal, markers=None, **options):
        return analyze_timeline(records, marker() if markers is None else markers,
                                poll_journal=journal, **options)

    def test_unique_protocol_candidate_is_not_marker_causality_or_server_acceptance(self):
        records, journal = case()
        frozen = copy.deepcopy((records, journal))
        report = self.analyze(records, journal)
        group = report['marker_associations'][0]
        self.assertEqual(group['classification'], 'protocol_supported_unique')
        self.assertEqual(group['candidate_response_record_ids'], [len(records)])
        pair = report['protocol_pairs'][-1]
        self.assertTrue(pair['exact_request_response_pair'])
        self.assertTrue(pair['raw_request_content_authenticated'])
        self.assertEqual(pair['choice_identity'], 'unique')
        self.assertIsNotNone(pair['request_source']['gre_message_index'])
        self.assertIsNone(pair['response_source']['gre_message_index'])
        self.assertEqual(pair['confirmation'], 'client_submission_only')
        self.assertFalse(group['marker_action_causality_verified'])
        self.assertFalse(report['server_acceptance_verified'])
        self.assertEqual((records, journal), frozen)
        self.assertNotIn('PRIVATE_NOTE_SENTINEL', json.dumps(report))

    def test_multiple_offered_pass_identities_remain_multiple_with_one_response(self):
        records, journal = case([PASS, PASS])
        report = self.analyze(records, journal)
        self.assertEqual(report['protocol_pairs'][-1]['choice_identity'], 'multiple')
        self.assertEqual(report['marker_associations'][0]['classification'], 'multiple_candidates')
        self.assertEqual(report['marker_associations'][0]['candidate_count'], 1)

    def test_three_pass_contexts_are_shown_without_selecting_nearest(self):
        initial = action_request([PASS])
        initial['greToClientEvent']['greToClientMessages'][-2]['gameStateMessage']['turnInfo'] = {
            'turnNumber': 12, 'activePlayer': 1, 'decisionPlayer': 1, 'priorityPlayer': 1,
            'phase': 'Phase_Main1', 'step': 'Step_None'}
        records, journal = wrapped([source_rows()[:9], [initial], [reply(details={'actions': [PASS]})],
            [{'greToClientEvent': {'greToClientMessages': [state(24,23,'Phase_Combat'), next_request(38,24)]}}],
            [reply(38,24,{'actions': [PASS]})],
            [{'greToClientEvent': {'greToClientMessages': [state(25,24,'Phase_Main2'), next_request(39,25)]}}],
            [reply(39,25,{'actions': [PASS]})], []])
        report = self.analyze(records, journal, marker(begin=2_900_000_000, end=7_010_000_000))
        group = report['marker_associations'][0]
        self.assertEqual(group['classification'], 'multiple_candidates')
        self.assertEqual(group['candidate_count'], 3)
        pairs = [pair for pair in report['protocol_pairs'] if pair['action_type'] == 'ActionType_Pass']
        self.assertEqual([pair['request_context']['phase'] for pair in pairs],
                         ['Phase_Main1','Phase_Combat','Phase_Main2'])
        self.assertEqual([pair['request_source']['gre_message_index'] for pair in pairs][-2:], [1,1])
        self.assertEqual(group['candidate_response_record_ids'], [pair['response_source']['record_id'] for pair in pairs])
        self.assertFalse(group['marker_action_causality_verified'])

    def test_unsupported_selected_shape_is_temporal_only_and_not_unique(self):
        records, journal = case(selected={'actionType': 'ActionType_Pass', 'unknown': True})
        report = self.analyze(records, journal)
        self.assertEqual(report['protocol_pairs'][-1]['choice_identity'], 'incomplete_or_unsupported')
        self.assertEqual(report['marker_associations'][0]['classification'], 'temporal_only')
        self.assertEqual(report['marker_associations'][0]['candidate_count'], 0)

    def test_no_observation_does_not_claim_temporal_association(self):
        records, journal = wrapped([source_rows()[:9], [action_request([PASS])], []])
        report = self.analyze(records, journal)
        group = report['marker_associations'][0]
        self.assertEqual(group['temporal_protocol_pairs'], [])
        self.assertEqual(group['classification'], 'unreliable')
        self.assertIn('no_temporal_protocol_observation', group['integrity_reasons'])

    def test_marker_interval_outside_frozen_poll_coverage_is_not_unique(self):
        for outside in ('before','after'):
            with self.subTest(outside=outside):
                records, journal = case()
                if outside == 'before':
                    journal[0]['poll_started']['monotonic_ns'] = 1_000_000_000
                    marks = marker(begin=500_000_000,end=3_100_000_000)
                else:
                    marks = marker(end=4_100_000_000)
                report = self.analyze(records, journal, marks)
                group = report['marker_associations'][0]
                self.assertEqual(group['classification'], 'unreliable')
                self.assertIn('marker_interval_not_fully_observed', group['integrity_reasons'])

    def test_partial_null_reset_missing_poll_and_generation_changes_are_unreliable(self):
        for fault in ('partial','null','reset','missing_poll','generation'):
            with self.subTest(fault=fault):
                records, journal = case()
                if fault == 'partial':
                    journal[-1]['partial_record'] = True
                elif fault == 'null':
                    records[-1]['entry'] = None
                elif fault == 'reset':
                    journal[-1]['reset'] = True
                elif fault == 'missing_poll':
                    journal.pop(1)
                else:
                    records[-1]['source']['generation'] = 2
                    journal[-1]['source']['generation'] = 2
                    journal[-1]['reset'] = True
                report = self.analyze(records, journal)
                self.assertEqual(report['marker_associations'][0]['classification'], 'unreliable')
                self.assertFalse(report['marker_associations'][0]['marker_action_causality_verified'])

    def test_recordless_partial_poll_is_unreliable_without_any_candidate(self):
        records, journal = case(tail=[[]])
        journal[-1]['partial_record'] = True
        report = self.analyze(records, journal, marker(begin=3_100_000_000,end=4_100_000_000))
        self.assertEqual(report['marker_associations'][0]['classification'], 'unreliable')
        self.assertIn('partial_or_unknown_source_tail', report['marker_associations'][0]['integrity_reasons'])

    def test_marker_missing_pair_wrong_order_duplicate_or_invalid_clock_stays_unreliable(self):
        variants = [marker()[:1], marker()[1:], list(reversed(marker())), marker(begin=4_000_000_000,end=2_000_000_000),
                    [marker()[0], {**marker()[1], 'event_id': 'before'}],
                    [{**marker()[0], 'monotonic_ns': None}, marker()[1]]]
        for markers in variants:
            with self.subTest(markers=markers):
                records, journal = case()
                result = self.analyze(records, journal, markers)
                self.assertTrue(all(group['classification'] == 'unreliable' for group in result['marker_associations']))

    def test_unknown_or_nonstring_marker_type_is_unreliable_and_not_echoed(self):
        for invalid in ('PRIVATE_MARKER_TYPE_SENTINEL', {'private': 'value'}, None):
            with self.subTest(invalid=invalid):
                records, journal = case()
                marks = [{**row, 'event_type': invalid} for row in marker()]
                result = self.analyze(records, journal, marks)
                group = result['marker_associations'][0]
                self.assertEqual(group['classification'], 'unreliable')
                self.assertIsNone(group['marker_type'])
                self.assertIn('unsupported_marker_type', group['integrity_reasons'])
                self.assertNotIn('PRIVATE_MARKER_TYPE_SENTINEL', json.dumps(result))

    def test_cast_submission_and_continuous_state_are_not_resolution_and_missing_targets_unknown(self):
        diff = {'greToClientEvent': {'greToClientMessages': [state(24,23,'Phase_Main1')]}}
        records, journal = case([CAST], CAST, tail=[[diff]])
        (ROOT / '.tmp').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / '.tmp') as temporary:
            source = Path(temporary) / 'synthetic-source.jsonl'
            save(source, [row['entry'] for row in records])
            report = self.analyze(records, journal, marker('cast_targeted'), semantic_source=source)
        pair = report['protocol_pairs'][-1]
        self.assertEqual(pair['targets_field'], 'missing')
        self.assertFalse(pair['targeted_or_targetless_spell_verified'])
        self.assertEqual(pair['continuous_successor']['status'], 'continuous_state_observed')
        self.assertFalse(pair['continuous_successor']['gameplay_effect_verified'])
        self.assertEqual(report['semantic_export']['status'], 'verified_existing_export')
        evidence = pair['semantic_trace']['cast_evidence']
        self.assertTrue(evidence['cast_submission_observed'])
        self.assertFalse(evidence['cast_on_stack_observed'])
        self.assertFalse(evidence['resolution_to_battlefield_observed'])
        self.assertFalse(report['marker_associations'][0]['targeted_vs_targetless_verified'])

    def test_semantic_source_mismatch_withholds_trace_instead_of_joining_by_time(self):
        records, journal = case([CAST], CAST)
        (ROOT / '.tmp').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / '.tmp') as temporary:
            source = Path(temporary) / 'different-source.jsonl'
            save(source, [row['entry'] for row in records[:-1]])
            report = self.analyze(records, journal, marker('cast_no_target'), semantic_source=source)
        self.assertEqual(report['semantic_export']['status'], 'withheld')
        self.assertIsNone(report['protocol_pairs'][-1]['semantic_trace'])

    def test_semantic_source_replaced_between_equal_value_check_and_export_withholds_trace(self):
        records, journal = case([CAST], CAST)
        (ROOT / '.tmp').mkdir(exist_ok=True)
        original_export = semantic_samples.collect_samples
        with tempfile.TemporaryDirectory(dir=ROOT / '.tmp') as temporary:
            source = Path(temporary) / 'source.jsonl'
            entries = [row['entry'] for row in records]
            save(source, entries)
            replacement = copy.deepcopy(entries)
            # Same action type and supported sample count; different identity.
            request = replacement[-2]['greToClientEvent']['greToClientMessages'][-1]
            request['actionsAvailableReq']['actions'][0]['instanceId'] = 163
            replacement[-1]['payload']['performActionResp']['actions'][0]['instanceId'] = 163
            def changed(path, **options):
                save(path, replacement)
                return original_export(path, **options)
            with patch.object(semantic_samples, 'collect_samples', side_effect=changed):
                result = self.analyze(records, journal, marker('cast_no_target'), semantic_source=source)
            self.assertEqual([json.loads(line) for line in source.read_text().splitlines()], entries)
        self.assertEqual(result['semantic_export']['status'], 'withheld')
        self.assertEqual(result['semantic_export']['reason'], 'semantic_source_changed_across_reads')
        self.assertIsNone(result['protocol_pairs'][-1]['semantic_trace'])

    def test_missing_priority_stays_unknown_and_missing_previous_poll_is_unreliable(self):
        records, journal = case()
        for message in records[-2]['entry']['greToClientEvent']['greToClientMessages']:
            if 'gameStateMessage' in message:
                message['gameStateMessage'].get('turnInfo', {}).pop('priorityPlayer', None)
        result = self.analyze(records, journal)
        self.assertIsNone(result['protocol_pairs'][-1]['request_context']['own_priority_player'])
        # Both request and response fall in poll3. Missing poll2 must still make
        # its expanded detection interval unreliable, not uniquely associated.
        records[-2]['poll_id'] = 3
        records[-2]['collected'] = copy.deepcopy(records[-1]['collected'])
        journal.pop(1)
        result = self.analyze(records, journal)
        self.assertEqual(result['marker_associations'][0]['classification'], 'unreliable')
        self.assertIn('missing_or_unordered_poll_journal_interval', result['marker_associations'][0]['integrity_reasons'])

    def test_source_timestamps_never_measure_network_delay_or_replace_capture_clock(self):
        records, journal = case()
        before = self.analyze(records, journal)
        for row in records:
            row['entry']['timestamp'] = '99999999999999999999'
        after = self.analyze(records, journal)
        self.assertEqual(before['marker_associations'], after['marker_associations'])
        self.assertIsNone(after['network_delay_seconds'])
        self.assertIn('unknown', after['source_timestamp_clock'])

    def test_original_sanitized_envelope_without_choice_fields_is_not_selected_action_proof(self):
        records, journal = wrapped([source_rows()[:9], source_rows()[9:11], source_rows()[11:12], []])
        report = self.analyze(records, journal)
        self.assertTrue(report['protocol_pairs'][-1]['exact_request_response_pair'])
        self.assertEqual(report['protocol_pairs'][-1]['choice_identity'], 'incomplete_or_unsupported')
        self.assertEqual(report['marker_associations'][0]['classification'], 'temporal_only')

    def test_snapshot_hash_mismatch_is_unreliable_and_evidence_is_not_modified(self):
        records, journal = case()
        (ROOT / '.tmp').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / '.tmp') as temporary:
            path = Path(temporary)
            files = {}
            for name, data in (('raw_records.jsonl',records),('poll_journal.jsonl',journal),('action_markers.jsonl',marker())):
                content = ''.join(json.dumps(row)+'\n' for row in data).encode()
                (path / name).write_bytes(content)
                files[name] = {'sha256': hashlib.sha256(content).hexdigest()}
            files['raw_records.jsonl']['sha256'] = '0' * 64
            (path / 'manifest.json').write_text(json.dumps({'files': files}), encoding='utf-8')
            original = {item.name: item.read_bytes() for item in path.iterdir()}
            result = analyze_snapshot(path)
            self.assertEqual(result['marker_associations'][0]['classification'], 'unreliable')
            self.assertEqual({item.name: item.read_bytes() for item in path.iterdir()}, original)


if __name__ == '__main__':
    unittest.main()
