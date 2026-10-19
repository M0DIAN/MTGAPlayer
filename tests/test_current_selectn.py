"""Five real request projections; synthetic authentication and counterexamples.

The fixture is not an authenticated raw log. Bootstrap/enclosing records below
are invented transport controls, and changed requests never establish new real
MTGA capability evidence. No private source or game resources are read.
"""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from mtgaplayer import current_selectn as selectn
from mtgaplayer.decision_consumer import EXECUTION
from mtgaplayer.shadow_history import _Evaluation
from mtgaplayer.shadow_runtime import LocalShadowRuntime, safe_summary
from test_combat_frontier import baseline
from test_decision_publisher import ManualClock, append
from test_raw_log import state
from test_semantic_search import message


FIXTURE = Path(__file__).parent / 'fixtures' / 'current_selectn_triggered_real_v1.json'


def samples():
    return json.loads(FIXTURE.read_text(encoding='utf-8'))['samples']


def wrap(value):
    return {'greToClientEvent': {'greToClientMessages': [value]}}


def rows_for(sample=None):
    """Real aliased request, explicitly synthetic auth/room/Full envelope."""
    sample = samples()[0] if sample is None else sample
    return baseline() + [wrap(copy.deepcopy(sample['aliased_request']))]


class CurrentSelectNTests(unittest.TestCase):
    def ready(self, sample=None, change=None, bootstrap=None):
        rows = rows_for(sample)
        if bootstrap is not None:
            bootstrap(rows)
        if change is not None:
            change(message(rows[-1]))
        evaluation = _Evaluation()
        for row in rows:
            evaluation.apply(row)
        return evaluation, message(rows[-1])

    def report(self, evaluation, request, limit=64):
        return evaluation.consumer.current_decision_options(limit=limit,
            current_selectn_context=(evaluation.reducer, request))['current_selectn_evidence']

    def safe(self, report):
        self.assertIs(report['read_only'], True)
        for name in EXECUTION:
            self.assertIs(report[name], False, name)
        self.assertIs(report['historical_response_used'], False)
        self.assertIs(report['research_eligible'], False)
        self.assertEqual(report['reviewed_visible_members'], [])
        self.assertEqual(report['reviewed_visible_member_count'], 0)
        self.assertEqual(report['reviewed_local_proposals'], [])
        self.assertIsNone(report['complete_proposal_count'])
        self.assertIsNone(report['complete_legal_actions'])
        for name in ('source_object_ref', 'weight_constraints', 'current_selected_literals'):
            self.assertIsNone(report[name], name)
        self.assertIn('complete_combination_constraints_unknown', report['unknown_combination_constraints'])
        for member in report['engine_offered_members']:
            self.assertEqual(member['namespace'], selectn.NAMESPACE)
            for name in ('object_ref', 'card_id', 'zone'):
                self.assertIsNone(member[name], name)
            self.assertEqual(member['request_binding'], report['request_binding'])
            self.assertEqual(member['source_snapshot_ref'], report['source_snapshot_ref'])

    def denied(self, report):
        self.safe(report)
        self.assertEqual(report['status'], 'insufficient_evidence')
        self.assertIsNone(report['request_binding'])
        self.assertIsNone(report['source_snapshot_ref'])
        self.assertEqual(report['engine_offered_members'], [])
        self.assertEqual(report['unresolved_member_references'], [])
        self.assertIsNone(report['engine_offered_member_count'])
        self.assertIsNone(report['observed_quantity_bounds'])
        self.assertFalse(report['current_local_constraints_verified'])

    def test_five_real_projections_keep_members_bounds_and_missing_semantics_separate(self):
        fixture = json.loads(FIXTURE.read_text(encoding='utf-8'))
        self.assertEqual(fixture['origin'], 'retained_scrubbed_real')
        for name in ('raw_equivalent', 'authentication_envelope_retained', 'future_response_used_for_request'):
            self.assertIs(fixture[name], False, name)
        self.assertEqual(fixture['original_source_sha256'],
            '1d75cd1b65ac868da1e9e0025032c7380317fcbf8669016a00fcb536e44a73ac')
        self.assertEqual([sample['member_count'] for sample in fixture['samples']], [2, 3, 3, 6, 10])
        for sample in fixture['samples']:
            with self.subTest(case=sample['case']):
                evaluation, request = self.ready(sample)
                before = copy.deepcopy(request)
                report = self.report(evaluation, request)
                self.safe(report)
                count = sample['member_count']
                self.assertEqual(report['status'], 'observed')
                self.assertEqual(report['profile'], selectn.PROFILE)
                self.assertEqual(report['engine_offered_member_count'], count)
                self.assertEqual(report['unresolved_member_count'], count)
                self.assertEqual(report['returned_members'], count)
                self.assertEqual(report['omitted_members'], 0)
                self.assertFalse(report['truncated'])
                self.assertTrue(report['reviewed_quantity_bounds'])
                self.assertTrue(report['current_local_constraints_verified'])
                self.assertEqual(report['observed_quantity_bounds'], {'minimum': 1, 'maximum': count,
                    'basis': 'explicit_current_minSel_maxSel_only'})
                self.assertEqual([row['member_ref'] for row in report['engine_offered_members']], list(range(1, count + 1)))
                self.assertEqual([row['list_position'] for row in report['engine_offered_members']], list(range(count)))
                self.assertEqual(report['engine_offered_members'], report['unresolved_member_references'])
                self.assertEqual(request, before)
                self.assertFalse(evaluation.reducer.request['supported'])
                self.assertEqual(evaluation.reducer.request['candidates'], [])

    def test_default_options_policy_and_warm_cache_remain_identical_and_detached(self):
        evaluation, request = self.ready()
        default = evaluation.consumer.current_decision_options()
        policy = evaluation.consumer.shadow_decision()
        self.assertEqual(evaluation.consumer.current_decision_options(), default)
        enriched = evaluation.consumer.current_decision_options(current_selectn_context=(evaluation.reducer, request))
        report = enriched.pop('current_selectn_evidence')
        self.assertEqual(enriched, default)
        self.assertEqual(evaluation.consumer.shadow_decision(), policy)
        self.assertIsNone(policy['preferred_option_key'])
        self.assertNotEqual(policy['status'], 'research_preference')
        report['engine_offered_members'][0]['request_binding']['request_id'] = 7
        report['unresolved_member_references'].clear()
        again = self.report(evaluation, request)
        self.assertEqual(len(again['unresolved_member_references']), 2)
        self.assertEqual(again['engine_offered_members'][0]['request_binding'], again['request_binding'])
        wrong = copy.deepcopy(request)
        wrong['selectNReq']['ids'].reverse()
        self.denied(self.report(evaluation, wrong))
        self.assertEqual(evaluation.consumer.current_decision_options(), default)
        self.assertNotIn('current_selectn_evidence', evaluation.consumer.current_decision_options())
        self.assertEqual(evaluation.consumer.shadow_decision(), policy)

    def test_truncation_preserves_original_domain_and_quantity_denominators(self):
        evaluation, request = self.ready(samples()[-1])
        report = self.report(evaluation, request, 3)
        self.safe(report)
        self.assertEqual(report['engine_offered_member_count'], 10)
        self.assertEqual(report['unresolved_member_count'], 10)
        self.assertEqual(report['observed_quantity_bounds']['maximum'], 10)
        self.assertEqual(report['returned_members'], 3)
        self.assertEqual(report['omitted_members'], 7)
        self.assertTrue(report['truncated'])
        self.assertEqual([member['list_position'] for member in report['engine_offered_members']], [0, 1, 2])
        self.assertEqual(len(self.report(evaluation, request)['engine_offered_members']), 10)

    def test_unreviewed_fields_enums_and_prompt_shapes_are_rejected(self):
        mutations = [
            ('missing_minimum', lambda m: m['selectNReq'].pop('minSel')),
            ('missing_ids', lambda m: m['selectNReq'].pop('ids')),
            ('cancel', lambda m: m.update(allowCancel='AllowCancel_No')),
            ('undo', lambda m: m.update(allowUndo=False)),
            ('source', lambda m: m['selectNReq'].update(sourceId=701)),
            ('weight', lambda m: m['selectNReq'].update(minWeight=0)),
            ('unfiltered', lambda m: m['selectNReq'].update(unfilteredIds=list(m['selectNReq']['ids']))),
            ('option_structure', lambda m: m['selectNReq'].update(options=[{'optionId': 701}])),
            ('context', lambda m: m['selectNReq'].update(context='SelectionContext_Resolution')),
            ('option_context', lambda m: m['selectNReq'].update(optionContext='OptionContext_Resolution')),
            ('id_namespace', lambda m: m['selectNReq'].update(idType='IdType_CardId')),
            ('list_type', lambda m: m['selectNReq'].update(listType='SelectionListType_Static')),
            ('repeatable', lambda m: m['selectNReq'].update(validationType='SelectionValidationType_Repeatable')),
            ('prompt_parameters', lambda m: m['prompt'].update(parameters=[])),
            ('prompt_bool', lambda m: m['prompt'].update(promptId=True)),
            ('prompt_float', lambda m: m['prompt'].update(promptId=1.0)),
            ('prompt_missing', lambda m: m.pop('prompt')),
        ]
        for label, mutate in mutations:
            with self.subTest(counterexample=label):
                evaluation, request = self.ready(change=mutate)
                self.denied(self.report(evaluation, request))

    def test_noninteger_duplicate_and_inconsistent_quantities_fail_closed(self):
        mutations = []
        for value in (True, 1001.0, 0, -1, 2**32, '1001', {'optionId': 1001}):
            mutations.append(('member_' + repr(value),
                lambda m, value=value: m['selectNReq']['ids'].__setitem__(0, value)))
        mutations.extend([
            ('duplicate', lambda m: m['selectNReq'].update(ids=[1001, 1001])),
            ('empty', lambda m: m['selectNReq'].update(ids=[], maxSel=0)),
            ('singleton', lambda m: m['selectNReq'].update(ids=[1001], maxSel=1)),
            ('over_budget', lambda m: m['selectNReq'].update(ids=list(range(2001, 2066)), maxSel=65)),
        ])
        for field, value in (('minSel', True), ('minSel', 1.0), ('minSel', 0), ('minSel', 2),
                ('minSel', 3), ('maxSel', True), ('maxSel', 2.0), ('maxSel', 0), ('maxSel', 1), ('maxSel', 3)):
            mutations.append((field + '_' + repr(value),
                lambda m, field=field, value=value: m['selectNReq'].__setitem__(field, value)))
        for label, mutate in mutations:
            with self.subTest(counterexample=label):
                evaluation, request = self.ready(change=mutate)
                self.denied(self.report(evaluation, request))

    def test_synthetic_hidden_identity_and_numeric_namespace_collisions_do_not_enrich(self):
        def add_object(rows, ident, zone, kind='GameObjectType_Card', card_id=42424242):
            snapshot = state(rows[2])
            snapshot['gameObjects'].append({'instanceId': ident, 'grpId': card_id, 'type': kind,
                'zoneId': zone, 'ownerSeatId': 1, 'controllerSeatId': 1,
                'visibility': 'Visibility_Public' if zone == 28 else 'Visibility_Private', 'viewers': [1]})
            next(z for z in snapshot['zones'] if z['zoneId'] == zone)['objectInstanceIds'].append(ident)

        # These invented enclosing objects challenge identity joins; the real
        # request shape is unchanged and they are not positive object evidence.
        for kind in ('GameObjectType_Card', 'GameObjectType_Ability'):
            with self.subTest(hidden_kind=kind):
                evaluation, request = self.ready(bootstrap=lambda rows: add_object(rows, 1001, 32, kind))
                report = self.report(evaluation, request)
                self.assertEqual(report['status'], 'observed')
                self.safe(report)
                self.assertNotIn('42424242', json.dumps(report))
                self.assertNotIn('1001', json.dumps(report))
        # Alias 1 equals a visible object ID, while its card ID equals a raw
        # offered reference. Neither equality creates an object/card mapping.
        evaluation, request = self.ready(bootstrap=lambda rows: add_object(rows, 1, 28, card_id=1001))
        report = self.report(evaluation, request)
        self.assertEqual(report['status'], 'observed')
        self.assertEqual(report['engine_offered_members'][0]['member_ref'], 1)
        self.safe(report)
        self.assertNotIn('1001', json.dumps(report))
        # A genuinely visible object with the same raw reference is a different,
        # unreviewed profile and must not silently borrow the opaque treatment.
        evaluation, request = self.ready(bootstrap=lambda rows: add_object(rows, 1001, 28))
        self.denied(self.report(evaluation, request))

    def test_wrong_current_digest_binding_and_invalid_context_never_borrow_cached_members(self):
        evaluation, request = self.ready()
        self.assertEqual(self.report(evaluation, request)['status'], 'observed')
        for field, value in (('msgId', 991), ('gameStateId', 2), ('gameStateId', 1.0),
                ('systemSeatIds', [2]), ('systemSeatIds', [True])):
            with self.subTest(field=field, value=value):
                changed = copy.deepcopy(request)
                changed[field] = value
                self.denied(self.report(evaluation, changed))
        for field, value in (('seat', 2), ('game', 2), ('match', 'synthetic-other-match')):
            with self.subTest(binding=field):
                evaluation, request = self.ready()
                setattr(evaluation.reducer, field, value)
                self.denied(self.report(evaluation, request))
        evaluation, request = self.ready()
        for invalid in (True, [], (evaluation.reducer,), [evaluation.reducer, request]):
            with self.assertRaises(ValueError):
                evaluation.consumer.current_decision_options(current_selectn_context=invalid)
        self.denied(evaluation.consumer.current_decision_options(
            current_selectn_context=(None, request))['current_selectn_evidence'])

    def test_later_synthetic_response_cannot_fill_or_revive_frozen_request_evidence(self):
        evaluation, request = self.ready()
        frozen = self.report(evaluation, request)
        retained = copy.deepcopy(frozen)
        # This invented response is solely a consumption/future-leak control.
        evaluation.apply({'payload': {'type': 'ClientMessageType_SelectNResp',
            'respId': request['msgId'], 'gameStateId': request['gameStateId'],
            'selectNResp': {'ids': request['selectNReq']['ids'][:1]}}})
        self.denied(self.report(evaluation, request))
        evaluation.apply(wrap(copy.deepcopy(request)))
        self.denied(self.report(evaluation, request))
        self.assertEqual(frozen, retained)
        self.safe(frozen)
        self.assertIsNone(frozen['current_selected_literals'])
        self.assertEqual(frozen['reviewed_local_proposals'], [])

    def test_runtime_dispatch_uses_same_sidecar_and_preserves_complete_default_reports(self):
        for sample in samples():
            with self.subTest(case=sample['case']), tempfile.TemporaryDirectory() as directory:
                rows = rows_for(sample)
                path = Path(directory) / 'synthetic-selectn-stream.log'
                path.write_bytes(b'')
                append(path, rows[:-1])
                runtime = LocalShadowRuntime(path, interval=0, samples=4,
                    clock_ns=ManualClock(), observation_mode='controlled_stream_replay')
                stream = runtime.frames()
                try:
                    self.assertEqual(next(stream)['time_scope'], 'observed_in_history')
                    append(path, rows[-1:])
                    frame = next(stream)
                    self.assertEqual(frame['time_scope'], 'current_at_completed_poll', frame['reason'])
                    self.assertEqual(frame['request_type'], selectn.REQUEST)
                    self.assertEqual(frame['current_options'], runtime.consumer.current_decision_options())
                    self.assertEqual(frame['shadow_decision'], runtime.consumer.shadow_decision())
                    enriched = runtime.consumer.current_decision_options(
                        current_selectn_context=(runtime._reducer, message(rows[-1])))
                    report = enriched.pop('current_selectn_evidence')
                    self.assertEqual(report, frame['local_evidence']['current_selectn_evidence'])
                    self.assertEqual(enriched, frame['current_options'])
                    self.assertEqual(report['status'], 'observed')
                    self.assertEqual(report['engine_offered_member_count'], sample['member_count'])
                    self.safe(report)
                    self.assertIsNone(frame['shadow_preference'])
                    self.assertEqual(frame['shadow_policy_status'], 'abstain')
                    self.assertEqual(frame['abstention_reason'], 'combination_or_tactical_basis_unverified')
                    summary = safe_summary(frame)
                    counts = summary['local_evidence']['current_selectn_evidence']['counts']
                    self.assertEqual(counts['engine_offered_member_count'], sample['member_count'])
                    self.assertEqual(counts['unresolved_member_count'], sample['member_count'])
                    for forbidden in ('member_ref', 'request_binding', 'source_snapshot_ref', '123456789', '1001'):
                        self.assertNotIn(forbidden, json.dumps(summary))
                finally:
                    runtime.close()
                    stream.close()


if __name__ == '__main__':
    unittest.main()
