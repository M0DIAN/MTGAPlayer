"""MP19 Phase 2: counted projected observations and privacy-safe attribution.

Standalone aggregation tests run without game assets. A repo-only integration
case exercises the actual watch → consumer → advisor path when available.
"""
import copy
import importlib.util
import io
import json
from pathlib import Path
import tempfile
from contextlib import redirect_stderr
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / 'scripts' / 'inspect_advisor_coverage.py'
SPEC = importlib.util.spec_from_file_location('mp19_coverage_for_tests', MODULE)
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)

PRIVATE = 'PRIVATE_MATCH_SENTINEL_48391'
EXECUTION = {k: False for k in mod.AUTHORITY_KEYS}


def fake_state(req=1, typ='GREMessageType_ActionsAvailableReq', label='first'):
    return {'schema_version': 'mtgaplayer.decision-state.v1', '_synthetic': {
        'label': label,
        'binding': {'source_generation': 1, 'match': PRIVATE, 'game': 1,
                    'self_seat': 1, 'game_state_id': 3,
                    'request_id': req, 'request_type': typ},
    }}


def row(kind, position, *, interpreted=True, evidence=None, link='not_applicable'):
    return {'engine_action_type': kind, 'list_position': position,
            'structurally_interpreted': interpreted, 'source_link_status': link,
            'evidence_quality': evidence if evidence is not None else [
                'ENGINE_OFFERED', 'STRUCTURE_INTERPRETED' if interpreted else 'UNSUPPORTED_STRUCTURE',
                'RESPONSE_UNVERIFIED'], 'strategic_utility': None,
            'unresolved_parameters': ['masked-no-export-value']}


def fake_advice(state):
    if state.get('_synthetic') is None or state['_synthetic'].get('label') == 'invalid':
        return {'schema_version': 'mtgaplayer.decision-advice.v1', 'read_only': True,
                'execution': dict(EXECUTION), 'historical_research_only': True,
                'assessment_status': 'abstain', 'abstention_reason': 'invalid_decision_state',
                'request_identity': None, 'candidate_coverage': {'inventory_integrity_verified': False},
                'candidate_assessments': []}
    x = state['_synthetic']
    binding = x['binding']
    typ = binding['request_type']
    if binding['request_id'] is None:
        reason, candidates, integrity = 'current_request_not_provided', [], False
    elif x['label'] == 'bad_inventory':
        reason, candidates, integrity = 'candidate_inventory_invalid', [], False
    elif typ == 'GREMessageType_ActionsAvailableReq':
        categories = {
            'first': [row('ActionType_Pass', 0)],
            'two_play': [row('ActionType_Pass', 0), row('ActionType_Play', 1, link='visible_unique'),
                         row('ActionType_Play', 2, link='visible_unique')],
            'simple_play': [row('ActionType_Pass', 0), row('ActionType_Play', 1, link='visible_unique')],
            'complex': [row('ActionType_Cast', 0, evidence=['ENGINE_OFFERED', 'STRUCTURE_INTERPRETED',
                         'PARAMETERS_PARTIAL', 'COMBINATION_UNKNOWN', 'RESPONSE_UNVERIFIED']),
                        row('ActionType_FloatMana', 1, interpreted=False)],
            'empty': [],
        }
        candidates = categories.get(x['label'], categories['first'])
        integrity = True
        reason = 'historical_research_only'
    elif typ == 'GREMessageType_SelectNReq':
        candidates, integrity, reason = [], True, 'select_n_strategy_unsupported'
    elif typ in ('GREMessageType_DeclareAttackersReq', 'GREMessageType_DeclareBlockersReq'):
        candidates = [{'reference_verified': True, 'engine_listed_attacker_references': [
            {'public_reference_verified': True}, {'public_reference_verified': False}],
            'strategic_utility': None},
            {'reference_verified': False, 'engine_listed_attacker_references': None,
             'strategic_utility': None}]
        integrity, reason = True, 'combat_strategy_unsupported'
    else:
        candidates, integrity, reason = [], False, 'unsupported_request_type'
    return {'schema_version': 'mtgaplayer.decision-advice.v1', 'read_only': True,
            'execution': dict(EXECUTION), 'historical_research_only': True,
            'assessment_status': 'abstain', 'assessment_scope': 'historical_research_only',
            'policy_version': 'evidence_only.v1', 'abstention_reason': reason,
            'request_identity': binding,
            'candidate_coverage': {'inventory_integrity_verified': integrity,
                 'offered_count': len(candidates) if integrity else None},
            'candidate_assessments': candidates,
            'request_summary': {'max_sel_raw': 3, 'min_sel': None} if typ == 'GREMessageType_SelectNReq' else None,
            'unresolved': ['strategic_utility_unknown']}


def collector():
    return mod.CoverageAccumulator(assessor=fake_advice)


def values(*items):
    return io.BytesIO(''.join(json.dumps(x) + '\n' for x in items).encode())


class CoverageTests(unittest.TestCase):
    def test_source_and_request_denominators_are_separate(self):
        a = collector()
        a.add_projected(fake_state())
        a.add_projected(fake_state(2, label='simple_play'))
        a.add_projected(fake_state(3, label='complex'))
        c = a.summary()['counts']
        self.assertEqual(c['input_records'], 3)
        self.assertEqual(c['request_groups_analyzed'], 3)
        self.assertEqual(c['active_actions_with_verified_inventory'], 5)
        self.assertEqual(c['structurally_interpreted_active_actions'], 4)
        self.assertEqual(c['action_request_groups'], 3)

    def test_duplicate_snapshot_is_not_another_request(self):
        a = collector()
        original = fake_state()
        a.add_projected(original)
        a.add_projected(copy.deepcopy(original))
        result = a.summary()
        self.assertEqual(result['counts']['duplicate_record_count'], 1)
        self.assertEqual(result['counts']['request_groups_analyzed'], 1)
        self.assertEqual(result['counts']['active_actions_with_verified_inventory'], 1)

    def test_conflicting_same_identity_quarantines_entire_group(self):
        a = collector()
        a.add_projected(fake_state())
        a.add_projected(fake_state(label='complex'))
        counts = a.summary()['counts']
        self.assertEqual(counts['conflicting_request_identity_groups'], 1)
        self.assertEqual(counts['request_groups_analyzed'], 0)
        self.assertEqual(counts['active_actions_with_verified_inventory'], 0)

    def test_distinct_state_version_is_distinct_request(self):
        a = collector()
        first, second = fake_state(), fake_state()
        second['_synthetic']['binding']['game_state_id'] = 4
        a.add_projected(first)
        a.add_projected(second)
        self.assertEqual(a.summary()['counts']['request_groups_analyzed'], 2)

    def test_absent_current_request_is_valid_but_not_offered_zero(self):
        a = collector()
        a.add_projected(fake_state(req=None))
        counts = a.summary()['counts']
        self.assertEqual(counts['valid_state_record_count'], 1)
        self.assertEqual(counts['valid_state_without_request_records'], 1)
        self.assertEqual(counts['request_groups_analyzed'], 0)
        self.assertIsNone(a.summary()['rates']['inventory_valid_rate']['value'])

    def test_malformed_null_and_invalid_not_silently_discarded(self):
        a = collector()
        a.add_projected({'decision_state': None})
        a.add_projected(fake_state(label='invalid'))
        a.add_projected({'some': 'unknown'})
        a.add_malformed()
        c = a.summary()['counts']
        self.assertEqual((c['input_records'], c['missing_state_count'],
                          c['invalid_state_count'], c['malformed_record_count']), (4, 1, 1, 2))

    def test_action_types_do_not_deduplicate_equal_names(self):
        a = collector()
        a.add_projected(fake_state(label='two_play'))
        report = a.summary()
        self.assertEqual(report['action_type_counts']['Play'], 2)
        self.assertEqual(report['action_type_counts']['Pass'], 1)
        self.assertEqual(report['counts']['active_actions_with_verified_inventory'], 3)

    def test_floatmana_and_complex_are_counted_not_filtered(self):
        a = collector()
        a.add_projected(fake_state(label='complex'))
        report = a.summary()
        self.assertEqual(report['action_type_counts']['FloatMana'], 1)
        self.assertEqual(report['action_type_counts']['Cast'], 1)
        self.assertEqual(report['rates']['unsupported_candidate_rate']['numerator'], 1)
        self.assertEqual(report['candidate_gap_counts']['COMPLEX_PARAMETERS_UNKNOWN'], 1)

    def test_conflicting_inventory_is_unknown_not_zero(self):
        a = collector()
        a.add_projected(fake_state(label='bad_inventory'))
        report = a.summary()
        self.assertEqual(report['counts']['unknown_action_inventory_groups'], 1)
        self.assertEqual(report['counts']['active_actions_with_verified_inventory'], 0)
        self.assertIsNone(report['rates']['structurally_interpreted_rate']['value'])
        self.assertEqual(report['request_gap_counts']['CANDIDATE_INVENTORY_INVALID'], 1)

    def test_selectn_denominator_stays_separate_from_action_rows(self):
        a = collector()
        a.add_projected(fake_state(2, 'GREMessageType_SelectNReq'))
        c = a.summary()['counts']
        self.assertEqual(c['action_request_groups'], 0)
        self.assertEqual(c['other_request_select_n_offered_references'], 0)
        self.assertEqual(a.summary()['request_gap_counts']['SELECT_N_MINIMUM_UNKNOWN'], 1)

    def test_combat_candidate_vs_verified_public_links(self):
        a = collector()
        a.add_projected(fake_state(2, 'GREMessageType_DeclareBlockersReq'))
        r = a.summary()
        self.assertEqual(r['counts']['other_request_combat_offered_references'], 2)
        self.assertEqual(r['counts']['other_request_combat_verified_public_references'], 1)
        self.assertEqual(r['counts']['other_request_combat_unresolved_links'], 2)
        self.assertEqual(r['request_gap_counts']['COMBAT_COMBINATIONS_UNKNOWN'], 1)

    def test_multiple_gaps_cooccur_without_single_cause_attribution(self):
        a = collector()
        a.add_projected(fake_state(label='complex'))
        r = a.summary()
        self.assertEqual(r['request_gap_counts']['COMPLEX_PARAMETERS_UNKNOWN'], 1)
        self.assertEqual(r['request_gap_counts']['RESPONSE_ENCODING_UNKNOWN'], 1)
        co = {(x['a'], x['b']) for x in r['request_gap_cooccurrence']}
        self.assertIn(tuple(sorted(('RESPONSE_ENCODING_UNKNOWN', 'COMPLEX_PARAMETERS_UNKNOWN'))), co)

    def test_historical_default_abstention_not_strategy_failure(self):
        a = collector()
        a.add_projected(fake_state(label='simple_play'))
        report = a.summary()
        self.assertEqual(report['abstention_category_counts'], {'HISTORICAL_RESEARCH_ONLY': 1})
        self.assertEqual(report['rates']['experimental_preference_rate']['denominator'], 0)
        self.assertIsNone(report['rates']['experimental_preference_rate']['value'])

    def test_private_request_identity_and_freeform_strings_never_exported(self):
        a = collector()
        data = fake_state()
        data['_synthetic']['payload'] = 'SECRET_CARD_IGNORED_19879'
        a.add_projected(data)
        rendered = json.dumps(a.summary())
        self.assertNotIn(PRIVATE, rendered)
        self.assertNotIn('SECRET_CARD_', rendered)
        self.assertNotIn('masked-no-export-value', rendered)

    def test_empty_evidence_rates_are_null(self):
        report = collector().summary()
        for item in report['rates'].values():
            self.assertEqual(item['denominator'], 0)
            self.assertIsNone(item['value'])

    def test_analysis_is_deterministic_across_record_order(self):
        data = [fake_state(1), fake_state(2, label='complex'),
                fake_state(3, 'GREMessageType_DeclareAttackersReq')]
        def run(items):
            a = collector()
            for x in items:
                a.add_projected(x)
            return a.summary()
        self.assertEqual(run(data), run(data[::-1]))

    def test_invalid_authority_elevation_is_excluded(self):
        def elevated(state):
            result = fake_advice(state)
            result['execution']['input_sent'] = True
            return result
        a = mod.CoverageAccumulator(assessor=elevated)
        a.add_projected(fake_state())
        self.assertEqual(a.summary()['counts']['invalid_state_count'], 1)

    def test_strict_json_rejects_duplicate_keys_and_nan(self):
        a = mod.inspect_stream(io.BytesIO(b'{"decision_state":null,"decision_state":{}}\nNaN\n'),
                               assessor=fake_advice)
        r = a.summary()
        self.assertEqual(r['counts']['malformed_record_count'], 2)
        self.assertEqual(r['counts']['input_records'], 2)

    def test_input_limits_do_not_truncate_silently(self):
        with self.assertRaisesRegex(ValueError, 'input_bytes_limit_exceeded'):
            mod.inspect_stream(io.BytesIO(b'"' + b'A' * (mod.MAX_LINE_BYTES + 1) + b'"\n'),
                               assessor=fake_advice)
        with self.assertRaisesRegex(ValueError, 'input_record_limit_exceeded'):
            mod.inspect_stream(io.BytesIO(b'null\n' * (mod.MAX_RECORDS + 1)),
                               assessor=fake_advice)

    def test_projected_jsonl_wrapper_and_direct_document(self):
        state1 = fake_state(1)
        state2 = fake_state(2)
        result = mod.inspect_stream(values({'decision_state': state1}, state2), assessor=fake_advice)
        self.assertEqual(result.summary()['counts']['unique_historical_requests'], 2)

    def test_synthetic_coverage_never_masquerades_as_live(self):
        a = collector()
        a.add_projected(fake_state())
        r = a.summary()
        self.assertEqual(r['qualification'], 'SYNTHETIC_COVERAGE_ONLY')
        self.assertEqual(r['priority_verdict'], 'PRIORITY_EVIDENCE_INSUFFICIENT')
        self.assertFalse(r['live_or_server_coverage_qualified'])
        self.assertTrue(r['read_only'])
        self.assertTrue(all(v is False for v in r['execution'].values()))

    def test_raw_player_log_path_rejected_before_open(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'Player.log'
            path.write_text('DO_NOT_OPEN', encoding='utf-8')
            with redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as result:
                    mod.main(['--input', str(path), '--output', str(Path(temp) / 'result.json')])
            self.assertNotEqual(result.exception.code, 0)
            self.assertFalse((Path(temp) / 'result.json').exists())

    def test_actual_projected_replay_uses_real_advisor_when_repository_available(self):
        if not (ROOT / 'src/mtgaplayer/decision_advisor.py').is_file():
            self.skipTest('sandbox package lacks the actual MTGAPlayer checkout')
        from mtgaplayer.cli import replay
        fixture = ROOT / 'tests/fixtures/player_log_selectn.jsonl'
        document = replay(fixture, format='player-log', decision_state=True)
        source = io.BytesIO((json.dumps(document) + '\n').encode('utf-8'))
        aggregate = mod.inspect_stream(source)  # no fake assessor
        report = aggregate.summary()
        self.assertEqual(report['counts']['input_records'], 1)
        self.assertEqual(report['counts']['malformed_record_count'], 0)
        self.assertEqual(report['counts']['invalid_state_count'] +
                         report['counts']['valid_state_record_count'] +
                         report['counts']['missing_state_count'], 1)
        self.assertFalse(report['live_or_server_coverage_qualified'])
        self.assertTrue(all(value is False for value in report['execution'].values()))

    def test_current_consumer_real_chain_when_repository_available(self):
        """Executed in the actual repo suite; not a fabricated ConsumerView."""
        if not (ROOT / 'src/mtgaplayer/decision_advisor.py').is_file():
            self.skipTest('sandbox package lacks the actual MTGAPlayer checkout')
        # Inside the repository these imports are MANDATORY; an import failure
        # is a real failure, not a reason to weaken/skip the test.
        from test_decision_advisor import DecisionAdvisorTests, PASS, PLAY
        from mtgaplayer.decision_advisor import SIMPLE_TYPE_POLICY
        t = DecisionAdvisorTests(methodName='test_actual_chain_unique_play_is_opt_in_research_only')
        t.setUp()
        try:
            consumer = t.current([PASS, PLAY])  # real watch_decision_events → Consumer
            a = mod.CoverageAccumulator()
            a.add_current_consumer(consumer, policy_version=SIMPLE_TYPE_POLICY)
            r = a.summary()
            self.assertEqual(r['counts']['unique_ephemeral_current_consumer_requests'], 1)
            rate = r['rates']['experimental_preference_rate']
            self.assertEqual((rate['numerator'], rate['denominator'], rate['value']), (1, 1, 1.0))
            self.assertEqual(rate['sample_kind'], 'in_process_consumer_current_not_server_verified')
            self.assertFalse(r['live_or_server_coverage_qualified'])
        finally:
            t.doCleanups()


if __name__ == '__main__':
    unittest.main()
