"""MP85 retained real stage projections; bootstrap and mutations are synthetic.

No private archive, owner artifact, installed client or native input is opened.
The public projected updates are genuine finite evidence shapes, while the
authentication/Full wrappers below establish portable consistency only.
"""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from mtgaplayer.choice_continuation import StageObserver
from mtgaplayer.decision_consumer import EXECUTION
from mtgaplayer.shadow_history import _Evaluation
from mtgaplayer.shadow_runtime import LocalShadowRuntime
from test_current_target_players import FIXTURE as TARGET_FIXTURE, HEADER, bind_build, rows_for
from test_current_target_request import wrap
import test_target_stage_completions as legacy_stages


FIXTURE = Path(__file__).parent / 'fixtures/player_target_stages_real.json'


def encoded(rows):
    return ''.join(json.dumps(row, separators=(',', ':')) + '\n' for row in rows).encode()


class Clock:
    now = 1_000_000_000
    def __call__(self):
        return self.now


class PlayerTargetStageTests(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads(FIXTURE.read_text(encoding='utf8'))
        self.cases = self.fixture['cases']
        self.samples = {s['case']: s for s in json.loads(TARGET_FIXTURE.read_text(encoding='utf8'))['cases']}
        self.closed = [s for s in self.cases if s['expected_complete']]

    def ready(self, case=None, *, sample=None, build=True):
        case = copy.deepcopy(self.closed[0] if case is None else case)
        sample = copy.deepcopy(self.samples[case['initial_mp84_case']] if sample is None else sample)
        e = _Evaluation()
        # Reuse production prepare/apply/after_apply and Publisher/Consumer. The
        # existing offline evaluator is used only as a transport test harness;
        # the explicit freeze below models a completed poll, not its callback.
        stage = StageObserver(e.reducer, include_player_target_stages=True)
        e.stage = stage
        def observe(event, details):
            stage.observe(event, details)
            if event == 'request_accepted':
                e.freeze(details)
            elif event == 'request_ended':
                e.end(details['request'])
        e.reducer.observer = observe
        for row in rows_for(sample):
            e.apply(row)
        if build:
            bind_build(e.reducer)
        return e, case, sample['message']

    def evidence(self, e, message, *, limit=64):
        return e.consumer.current_decision_options(limit=limit,
            current_target_context=(e.reducer, message))['current_target_evidence']

    def freeze(self, e, message, evidence=None, policy=None):
        evidence = self.evidence(e, message) if evidence is None else evidence
        policy = e.consumer.shadow_decision() if policy is None else policy
        e.stage.revision.freeze_player_targets(e.consumer, message, evidence, policy)
        return copy.deepcopy(evidence)

    def report(self, e, *, last=False):
        return e.stage.revision.player_stage_report(include_last=last)

    def revised(self, e, case):
        for row in case['revision_records']:
            e.apply(copy.deepcopy(row))
        messages = case['revision_records'][-1]['greToClientEvent']['greToClientMessages']
        message = next(m for m in messages if m['type'] == 'GREMessageType_SelectTargetsReq')
        self.freeze(e, message)
        return message

    def run_case(self, case=None, *, terminal=True):
        e, case, message = self.ready(case)
        self.freeze(e, message)
        e.apply(copy.deepcopy(case['update_record']))
        if case['revision_records']:
            self.revised(e, case)
        if terminal and case['terminal_record'] is not None:
            e.apply(copy.deepcopy(case['terminal_record']))
        return e, case, message

    def safe(self, value):
        for key in EXECUTION:
            if key in value:
                self.assertIs(value[key], False, key)
        if 'complete_legality_verified' in value:
            self.assertIs(value['complete_legality_verified'], False)
        if 'server_acceptance_verified' in value:
            self.assertIs(value['server_acceptance_verified'], False)

    def test_real_projections_supply_eleven_updates_and_two_terminal_stages(self):
        self.assertEqual(hashlib.sha256(FIXTURE.read_bytes().replace(b'\r\n', b'\n')).hexdigest(),
            '3fb36caefd5ea18ccfa4a0ceb4036296f819241df26d4a7c060e65bbc0edc2a0')
        self.assertEqual(self.fixture['origin'], 'retained_scrubbed_real')
        self.assertFalse(self.fixture['raw_equivalent'])
        self.assertEqual(len(self.cases), 11)
        totals = {key: 0 for key in ('frozen_reviewed_domains', 'frozen_local_proposals',
            'strictly_paired_target_updates', 'historically_selected_player_targets',
            'independently_revised_selections', 'strictly_paired_terminal_submits',
            'fully_linked_historical_stages', 'unlinked_or_interrupted_stages')}
        for case in self.cases:
            with self.subTest(case=case['case']):
                e, actual, message = self.run_case(case)
                report = self.report(e, last=True)
                for key in totals:
                    totals[key] += report[key]
                self.assertEqual(report['strictly_paired_target_updates'], 1)
                self.assertEqual(report['historically_selected_player_targets'],
                    int(case['expected_selected_role'] == 'verified_player'))
                self.assertEqual(report['fully_linked_historical_stages'], int(case['expected_complete']))
                self.assertIsNone(report['historical_choice_agreements'])
                self.assertIsNone(report['historical_choice_disagreements'])
                self.assertEqual(report['historical_comparison_unavailable'], 1)
                self.safe(report)
                self.safe(report['last_historical_fact'])
                self.assertIsNone(e.reducer.request)
                self.assertEqual(e.consumer.current_decision_options()['options'], [])
                self.assertEqual(e.consumer.shadow_decision()['status'], 'expired')
        self.assertEqual(totals, {'frozen_reviewed_domains': 11, 'frozen_local_proposals': 24,
            'strictly_paired_target_updates': 11, 'historically_selected_player_targets': 10,
            'independently_revised_selections': 2, 'strictly_paired_terminal_submits': 2,
            'fully_linked_historical_stages': 2, 'unlinked_or_interrupted_stages': 9})

    def test_freeze_precedes_update_and_each_independent_terminal_boundary(self):
        for case in self.closed:
            e, case, message = self.ready(case)
            frozen = self.freeze(e, message)
            retained = copy.deepcopy(frozen)
            self.assertEqual(self.report(e)['strictly_paired_target_updates'], 0)
            self.assertEqual(self.report(e)['fully_linked_historical_stages'], 0)
            e.apply(copy.deepcopy(case['update_record']))
            self.assertEqual(self.report(e)['strictly_paired_target_updates'], 1)
            self.assertEqual(self.report(e)['independently_revised_selections'], 0)
            self.assertIsNone(e.reducer.request)
            revised_message = self.revised(e, case)
            selected = self.evidence(e, revised_message)
            self.assertFalse(selected['complete_current_select_domain_verified'])
            self.assertEqual(selected['local_proposals'], [])
            self.assertEqual(self.report(e)['independently_revised_selections'], 1)
            self.assertEqual(self.report(e)['fully_linked_historical_stages'], 0)
            e.apply(copy.deepcopy(case['terminal_record']))
            self.assertEqual(self.report(e)['fully_linked_historical_stages'], 1)
            self.assertEqual(frozen, retained)

    def test_default_candidates_and_policy_are_unchanged_by_freezing(self):
        e, case, message = self.ready()
        options, policy = e.consumer.current_decision_options(), e.consumer.shadow_decision()
        evidence = self.freeze(e, message)
        self.assertEqual(e.consumer.current_decision_options(), options)
        self.assertEqual(e.consumer.shadow_decision(), policy)
        self.assertEqual(policy['status'], 'abstain')
        self.assertTrue(all(o['research_eligible'] is False for o in evidence['local_proposals']))
        self.freeze(e, message)
        self.assertEqual(self.report(e)['frozen_reviewed_domains'], 1)
        self.assertEqual(self.report(e)['frozen_local_proposals'], evidence['returned_proposals'])

    def test_both_optins_preserve_full_legacy_card_and_ability_completion_reports(self):
        maker = legacy_stages.TargetStageCompletionTests(
            'test_real_cast_freeze_before_future_and_terminal_only_after110')
        # The Card sequence is the existing public real Cast fixture. Equip's
        # already-public bootstrap remains explicitly synthetic old plumbing.
        for source, rows in (('Card', maker.real_rows()), ('Ability', maker.equip_rows())):
            with self.subTest(legacy_source=source):
                baseline = maker.evaluate(rows)
                e = _Evaluation(target_stage_completions=True)
                stage = StageObserver(e.reducer, include_cast=True,
                    include_target_completions=True, include_player_target_stages=True)
                e.stage = stage
                def observe(event, details):
                    stage.observe(event, details)
                    if event == 'request_accepted': e.freeze(details)
                    elif event == 'request_ended': e.end(details['request'])
                e.reducer.observer = observe
                for row in rows: e.apply(copy.deepcopy(row))
                self.assertEqual(e.target_completions.report(), baseline.target_completions.report())
                self.assertEqual(e.target_completions.report()['completed_source_types'], {source: 1})
                self.assertEqual(e.target_completions.report()['historical_reviewed_target_sets_submitted'], 1)
                self.assertEqual(self.report(e)['frozen_reviewed_domains'], 0)
                self.assertEqual(self.report(e)['strictly_paired_target_updates'], 0)
                self.assertEqual(self.report(e)['fully_linked_historical_stages'], 0)

    def test_synthetic_wrong_response_identity_or_structure_withholds_update(self):
        variants = ('response_id', 'response_id_bool', 'state', 'state_float', 'type',
            'slot', 'slot_bool', 'outside_member', 'member_bool', 'unselect', 'duplicate',
            'empty', 'extra', 'nested_extra', 'mixed')
        for mode in variants:
            with self.subTest(mode=mode):
                e, case, message = self.ready()
                self.freeze(e, message)
                row = copy.deepcopy(case['update_record']); payload = row['payload']
                target = payload['selectTargetsResp']['target']; entry = target['targets'][0]
                if mode == 'response_id': payload['respId'] += 100
                elif mode == 'response_id_bool': payload['respId'] = True
                elif mode == 'state': payload['gameStateId'] += 1
                elif mode == 'state_float': payload['gameStateId'] = float(payload['gameStateId'])
                elif mode == 'type': payload['type'] = 'ClientMessageType_PerformActionResp'
                elif mode == 'slot': target['targetIdx'] += 1
                elif mode == 'slot_bool': target['targetIdx'] = True
                elif mode == 'outside_member': entry['targetInstanceId'] = 999999
                elif mode == 'member_bool': entry['targetInstanceId'] = True
                elif mode == 'unselect': entry['legalAction'] = 'SelectAction_Unselect'
                elif mode == 'duplicate': target['targets'] *= 2
                elif mode == 'empty': target['targets'] = []
                elif mode == 'extra': payload['unreviewed'] = True
                elif mode == 'nested_extra': entry['unreviewed'] = True
                else: row['greToClientEvent'] = {'greToClientMessages': []}
                e.apply(row)
                self.assertEqual(self.report(e)['strictly_paired_target_updates'], 0)
                self.assertEqual(self.report(e)['fully_linked_historical_stages'], 0)

    def test_synthetic_forged_frozen_sidecar_or_policy_is_rejected(self):
        for mode in ('request', 'snapshot', 'namespace', 'kind', 'player', 'proposal',
                     'option_key', 'count', 'policy_binding', 'policy_authority'):
            with self.subTest(mode=mode):
                e, case, message = self.ready()
                evidence = self.evidence(e, message); policy = e.consumer.shadow_decision()
                if mode == 'request': evidence['current_request_binding']['request_id'] += 1
                elif mode == 'snapshot': evidence['source_snapshot_ref']['sequence'] += 1
                elif mode in ('namespace', 'kind', 'player'):
                    field, value = {'namespace': ('namespace', 'public_game_object'),
                        'kind': ('target_referent_kind', 'verified_public_object'),
                        'player': ('player_seat', 2)}[mode]
                    evidence['target_referents'][0][field] = value
                elif mode == 'proposal': evidence['local_proposals'][0]['research_eligible'] = True
                elif mode == 'option_key': evidence['local_proposals'][0]['option_key'] = 'invented'
                elif mode == 'count': evidence['returned_proposals'] += 1
                elif mode == 'policy_binding': policy['request_binding']['request_id'] += 1
                else: policy['execution_ready'] = True
                self.freeze(e, message, evidence, policy)
                e.apply(copy.deepcopy(case['update_record']))
                self.assertEqual(self.report(e)['frozen_reviewed_domains'], 0)
                self.assertEqual(self.report(e)['strictly_paired_target_updates'], 0)

    def test_synthetic_version_collision_or_raw_identity_change_revokes_prior_freeze(self):
        for mode in ('version', 'collision', 'zone_collision', 'source_group', 'source_type',
                     'source_zone', 'players', 'match', 'game', 'seat', 'digest'):
            with self.subTest(mode=mode):
                e, case, message = self.ready()
                self.freeze(e, message)
                source = e.reducer.objects[message['selectTargetsReq']['sourceId']]
                if mode == 'version': e.reducer._target_build_context = None
                elif mode == 'collision':
                    e.reducer.objects[2] = {'instanceId': 2, 'type': 'GameObjectType_Card',
                        'visibility': 'Visibility_Private', 'zoneId': 9876}
                elif mode == 'zone_collision':
                    e.reducer.zones[9876] = {'zoneId': 9876, 'type': 'ZoneType_Hand',
                        'visibility': 'Visibility_Private', 'objectInstanceIds': [2]}
                elif mode == 'source_group': source['grpId'] += 1
                elif mode == 'source_type': source['type'] = 'GameObjectType_Card'
                elif mode == 'source_zone': e.reducer.zones[source['zoneId']]['type'] = 'ZoneType_Battlefield'
                elif mode == 'players': e.reducer.players[2]['systemSeatNumber'] = 1
                elif mode == 'match': e.reducer.match = 'synthetic-other-match'
                elif mode == 'game': e.reducer.game += 1
                elif mode == 'seat': e.reducer.seat = 2
                else: e.reducer.accepted_digest = b'changed'
                e.apply(copy.deepcopy(case['update_record']))
                self.assertEqual(self.report(e)['strictly_paired_target_updates'], 0)

    def test_synthetic_unknown_member_truncation_or_unselect_only_cannot_start(self):
        for mode in ('unknown', 'truncated', 'unselect', 'missing_version', 'wrong_version'):
            with self.subTest(mode=mode):
                case = self.closed[0]
                sample = copy.deepcopy(self.samples[case['initial_mp84_case']])
                if mode == 'unknown':
                    sample['message']['selectTargetsReq']['targets'][0]['targets'][0]['targetInstanceId'] = 999999
                elif mode == 'unselect':
                    sample = copy.deepcopy(next(s for s in self.samples.values() if not s['expected_complete_domain']))
                e, actual, message = self.ready(case, sample=sample, build=mode not in ('missing_version', 'wrong_version'))
                if mode == 'wrong_version': bind_build(e.reducer, HEADER.replace(b'1329972', b'1329973'))
                evidence = self.evidence(e, message, limit=1 if mode == 'truncated' else 64)
                self.freeze(e, message, evidence)
                self.assertEqual(self.report(e)['frozen_reviewed_domains'], 0)

    def test_synthetic_revised_identity_quantity_or_operation_withholds_completion(self):
        for mode in ('source', 'group', 'targeting_group', 'slot', 'target_player', 'target',
                     'count', 'selected', 'select', 'duplicate', 'seat', 'request_state'):
            with self.subTest(mode=mode):
                e, case, message = self.ready()
                self.freeze(e, message); e.apply(copy.deepcopy(case['update_record']))
                records = copy.deepcopy(case['revision_records'])
                revised = records[-1]['greToClientEvent']['greToClientMessages'][-1]
                body = revised['selectTargetsReq']; slot = body['targets'][0]
                if mode == 'source': body['sourceId'] += 1
                elif mode == 'group': body['abilityGrpId'] += 1
                elif mode == 'targeting_group': slot['targetingAbilityGrpId'] += 1
                elif mode == 'slot': slot['targetIdx'] += 1
                elif mode == 'target_player': slot['targetingPlayer'] = 2
                elif mode == 'target': slot['targets'][0]['targetInstanceId'] = 1
                elif mode == 'count': slot['maxTargets'] = 2
                elif mode == 'selected': slot['selectedTargets'] = 2
                elif mode == 'select': slot['targets'][0]['legalAction'] = 'SelectAction_Select'
                elif mode == 'duplicate': slot['targets'] *= 2
                elif mode == 'seat': revised['systemSeatIds'] = [2]
                else: revised['gameStateId'] += 1
                for row in records: e.apply(row)
                self.freeze(e, revised)
                e.apply(copy.deepcopy(case['terminal_record']))
                self.assertEqual(self.report(e)['strictly_paired_target_updates'], 1)
                self.assertEqual(self.report(e)['independently_revised_selections'], 0)
                self.assertEqual(self.report(e)['fully_linked_historical_stages'], 0)

    def test_synthetic_missing_or_unfrozen_revision_and_missing_terminal_remain_partial(self):
        for mode in ('no_revision', 'unfrozen_revision', 'no_terminal'):
            with self.subTest(mode=mode):
                e, case, message = self.ready()
                self.freeze(e, message); e.apply(copy.deepcopy(case['update_record']))
                if mode == 'unfrozen_revision':
                    for row in case['revision_records']: e.apply(copy.deepcopy(row))
                elif mode == 'no_terminal': self.revised(e, case)
                if mode != 'no_terminal': e.apply(copy.deepcopy(case['terminal_record']))
                self.assertEqual(self.report(e)['strictly_paired_target_updates'], 1)
                self.assertEqual(self.report(e)['fully_linked_historical_stages'], 0)

    def test_synthetic_terminal_header_mutations_do_not_complete(self):
        for mode in ('id', 'state', 'bool', 'type', 'extra', 'mixed'):
            with self.subTest(mode=mode):
                e, case, message = self.run_case(terminal=False)
                row = copy.deepcopy(case['terminal_record']); payload = row['payload']
                if mode == 'id': payload['respId'] -= 1
                elif mode == 'state': payload['gameStateId'] -= 1
                elif mode == 'bool': payload['gameStateId'] = True
                elif mode == 'type': payload['type'] = 'ClientMessageType_SelectTargetsResp'
                elif mode == 'extra': payload['targets'] = []
                else: row['greToClientEvent'] = {'greToClientMessages': []}
                e.apply(row)
                self.assertEqual(self.report(e)['strictly_paired_terminal_submits'], 0)
                self.assertEqual(self.report(e)['fully_linked_historical_stages'], 0)

    def test_synthetic_revised_lease_version_or_identity_change_revokes_terminal(self):
        for mode in ('lease', 'version', 'collision', 'source', 'scope', 'stop'):
            with self.subTest(mode=mode):
                e, case, message = self.run_case(terminal=False)
                self.assertEqual(self.report(e)['independently_revised_selections'], 1)
                if mode == 'lease': e.ordinal += 10**15
                elif mode == 'version': e.reducer._target_build_context = None
                elif mode == 'collision':
                    e.reducer.zones[9876] = {'zoneId': 9876, 'type': 'ZoneType_Hand',
                        'visibility': 'Visibility_Private', 'objectInstanceIds': [2]}
                elif mode == 'source':
                    e.reducer.objects[message['selectTargetsReq']['sourceId']]['grpId'] += 1
                elif mode == 'scope': e.reducer.match = 'synthetic-other-match'
                else:
                    for event in e.publisher.stop('sample_limit'): self.assertTrue(e.consumer.accept_event(event))
                row = copy.deepcopy(case['terminal_record'])
                e.stage.prepare(row); e.reducer.apply(row); e.stage.after_apply()
                self.assertEqual(self.report(e)['strictly_paired_target_updates'], 1)
                self.assertEqual(self.report(e)['strictly_paired_terminal_submits'], 0)
                self.assertEqual(self.report(e)['fully_linked_historical_stages'], 0)

    def test_synthetic_tracked_identity_migration_annotation_breaks_revision(self):
        for ident in (100, 2):
            with self.subTest(tracked_entity=ident):
                e, case, message = self.ready(); self.freeze(e, message)
                e.apply(copy.deepcopy(case['update_record']))
                records = copy.deepcopy(case['revision_records'])
                gs = records[0]['greToClientEvent']['greToClientMessages'][0]['gameStateMessage']
                gs['annotations'] = [{'type': ['AnnotationType_ObjectIdChanged'],
                    'affectorId': ident, 'affectedIds': [ident], 'details': [
                        {'key': 'orig_id', 'type': 'KeyValuePairValueType_int32', 'valueInt32': [ident]},
                        {'key': 'new_id', 'type': 'KeyValuePairValueType_int32', 'valueInt32': [9999]}]}]
                for row in records: e.apply(row)
                revised = records[-1]['greToClientEvent']['greToClientMessages'][-1]
                self.freeze(e, revised); e.apply(copy.deepcopy(case['terminal_record']))
                self.assertEqual(self.report(e)['strictly_paired_target_updates'], 1)
                self.assertEqual(self.report(e)['independently_revised_selections'], 0)
                self.assertEqual(self.report(e)['fully_linked_historical_stages'], 0)

    def test_synthetic_repeated_update_diff_or_consumed_request_cannot_complete(self):
        for mode in ('response', 'diff', 'batched_diff', 'consumed_request', 'competing_request'):
            with self.subTest(mode=mode):
                e, case, message = self.ready(); self.freeze(e, message)
                e.apply(copy.deepcopy(case['update_record']))
                if mode == 'response': e.apply(copy.deepcopy(case['update_record']))
                elif mode == 'consumed_request': e.apply(wrap(copy.deepcopy(message)))
                elif mode == 'competing_request':
                    changed = copy.deepcopy(message); changed['msgId'] += 100
                    e.apply(wrap(changed))
                elif mode == 'diff':
                    gs = case['revision_records'][0]['greToClientEvent']['greToClientMessages'][0]
                    e.apply(wrap(copy.deepcopy(gs)))
                else:
                    row = copy.deepcopy(case['revision_records'][0]); messages = row['greToClientEvent']['greToClientMessages']
                    messages.insert(1, copy.deepcopy(messages[0])); e.apply(row)
                self.revised(e, case)
                e.apply(copy.deepcopy(case['terminal_record']))
                self.assertEqual(self.report(e)['strictly_paired_target_updates'], 1)
                self.assertEqual(self.report(e)['fully_linked_historical_stages'], 0)

    def test_synthetic_cancel_undo_full_gap_reset_and_partial_break_pending(self):
        for mode in ('cancel', 'undo', 'full', 'gap', 'typed_prev', 'reset', 'partial'):
            with self.subTest(mode=mode):
                e, case, message = self.ready(); self.freeze(e, message)
                e.apply(copy.deepcopy(case['update_record']))
                if mode in ('cancel', 'undo'):
                    e.apply({'payload': {'type': 'ClientMessageType_CancelActionReq' if mode == 'cancel' else 'ClientMessageType_UndoReq'}})
                elif mode == 'full': e.apply(rows_for(self.samples[case['initial_mp84_case']])[2])
                elif mode in ('gap', 'typed_prev'):
                    row = copy.deepcopy(case['revision_records'][0])
                    gs = row['greToClientEvent']['greToClientMessages'][0]['gameStateMessage']
                    gs['prevGameStateId'] = 9 if mode == 'gap' else 10.0
                    e.apply(row)
                elif mode == 'reset': e.reducer.reset(2); e.stage.reset()
                else: e.stage.reset(); e.publish(partial=True)
                self.revised(e, case); e.apply(copy.deepcopy(case['terminal_record']))
                self.assertEqual(self.report(e)['fully_linked_historical_stages'], 0)

    def test_synthetic_lease_stop_and_late_freeze_cannot_authorize_historical_update(self):
        for mode in ('lease', 'stop', 'late_freeze'):
            with self.subTest(mode=mode):
                e, case, message = self.ready()
                evidence = self.evidence(e, message); policy = e.consumer.shadow_decision()
                if mode != 'late_freeze': self.freeze(e, message, evidence, policy)
                if mode == 'lease': e.ordinal += 10**15
                elif mode == 'stop':
                    for event in e.publisher.stop('sample_limit'): self.assertTrue(e.consumer.accept_event(event))
                if mode in ('lease', 'stop'):
                    # The subscription has intentionally ended. Exercise the
                    # production stage/reducer edge without trying to publish
                    # another event through the offline harness's dead lease.
                    row = copy.deepcopy(case['update_record'])
                    e.stage.prepare(row); e.reducer.apply(row); e.stage.after_apply()
                else:
                    e.apply(copy.deepcopy(case['update_record']))
                if mode == 'late_freeze': self.freeze(e, message, evidence, policy)
                self.assertEqual(self.report(e)['strictly_paired_target_updates'], 0)
                self.assertEqual(self.report(e)['fully_linked_historical_stages'], 0)

    def test_historical_report_is_detached_and_does_not_restore_consumed_candidate(self):
        e, case, message = self.run_case()
        retained = self.report(e, last=True)
        retained['frozen_reviewed_domains'] = 999
        retained['last_historical_fact']['input_sent'] = True
        report = self.report(e, last=True)
        self.assertEqual(report['frozen_reviewed_domains'], 1)
        self.safe(report['last_historical_fact'])
        e.apply(copy.deepcopy(case['terminal_record']))
        e.apply(wrap(copy.deepcopy(message)))
        self.freeze(e, message)
        self.assertEqual(self.report(e)['strictly_paired_target_updates'], 1)
        self.assertEqual(self.report(e)['fully_linked_historical_stages'], 1)
        self.assertEqual(e.consumer.current_decision_options()['options'], [])
        self.assertEqual(e.consumer.shadow_decision()['status'], 'expired')


class PlayerTargetRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads(FIXTURE.read_text(encoding='utf8'))
        self.case = copy.deepcopy(next(c for c in self.fixture['cases'] if c['expected_complete']))
        samples = json.loads(TARGET_FIXTURE.read_text(encoding='utf8'))['cases']
        self.sample = copy.deepcopy(next(s for s in samples if s['case'] == self.case['initial_mp84_case']))
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'synthetic-wrapper-real-stage-projections.jsonl'
        self.clock = Clock()

    def start(self):
        rows = rows_for(self.sample)
        self.path.write_bytes(HEADER + encoded(rows[:-1]))
        self.runtime = LocalShadowRuntime(self.path, interval=0, samples=None, clock_ns=self.clock,
            observation_mode='controlled_stream_replay', player_target_stages=True)
        self.gen = self.runtime.frames()
        self.addCleanup(self.gen.close); self.addCleanup(self.runtime.close)
        next(self.gen)
        return self.append([rows[-1]])

    def append(self, rows):
        with self.path.open('ab') as stream: stream.write(encoded(rows))
        return next(self.gen)

    def test_completed_poll_runtime_freezes_and_links_real_projected_terminal(self):
        frame = self.start()
        self.assertEqual(frame['time_scope'], 'current_at_completed_poll')
        self.assertEqual(self.runtime.player_target_stage_history()['frozen_reviewed_domains'], 1)
        original_policy = copy.deepcopy(frame['shadow_decision'])
        current = self.runtime.current_frame()
        self.assertEqual(current['shadow_decision'], original_policy)
        self.assertEqual(self.runtime.player_target_stage_history()['frozen_reviewed_domains'], 1)
        self.assertNotEqual(self.append([self.case['update_record']])['time_scope'], 'current_at_completed_poll')
        self.assertEqual(self.runtime.player_target_stage_history()['strictly_paired_target_updates'], 1)
        revised = self.append(self.case['revision_records'])
        self.assertEqual(revised['time_scope'], 'current_at_completed_poll')
        self.assertEqual(self.runtime.player_target_stage_history()['independently_revised_selections'], 1)
        terminal = self.append([self.case['terminal_record']])
        self.assertNotEqual(terminal['time_scope'], 'current_at_completed_poll')
        report = self.runtime.player_target_stage_history(include_last=True)
        self.assertEqual(report['fully_linked_historical_stages'], 1)
        self.assertFalse(report['last_historical_fact']['input_sent'])
        self.runtime.close()
        self.assertNotEqual(self.runtime.current_frame()['time_scope'], 'current_at_completed_poll')

    def test_synthetic_partial_pending_cannot_resume_terminal_lineage(self):
        self.start(); self.append([self.case['update_record']])
        with self.path.open('ab') as stream: stream.write(b'{"synthetic_partial":')
        partial = next(self.gen)
        self.assertNotEqual(partial['time_scope'], 'current_at_completed_poll')
        with self.path.open('ab') as stream: stream.write(b'true}\n')
        next(self.gen)
        self.append(self.case['revision_records']); self.append([self.case['terminal_record']])
        self.assertEqual(self.runtime.player_target_stage_history()['strictly_paired_target_updates'], 1)
        self.assertEqual(self.runtime.player_target_stage_history()['fully_linked_historical_stages'], 0)

    def test_synthetic_expired_runtime_frame_withholds_update(self):
        self.start()
        self.clock.now += 6_000_000_000
        self.assertNotEqual(self.runtime.current_frame()['time_scope'], 'current_at_completed_poll')
        self.append([self.case['update_record']])
        self.assertEqual(self.runtime.player_target_stage_history()['strictly_paired_target_updates'], 0)

    def test_synthetic_expired_pending_stage_cannot_cross_new_consumer_subscription(self):
        self.start(); self.append([self.case['update_record']])
        self.assertEqual(self.runtime.player_target_stage_history()['strictly_paired_target_updates'], 1)
        previous_consumer = self.runtime.consumer
        self.clock.now += 6_000_000_000
        revised = self.append(self.case['revision_records'])
        # A genuinely new request may obtain a fresh current subscription, but
        # the expired update lineage cannot travel with that subscription.
        self.assertIsNot(self.runtime.consumer, previous_consumer)
        self.assertEqual(revised['time_scope'], 'current_at_completed_poll')
        self.assertEqual(self.runtime.player_target_stage_history()['independently_revised_selections'], 0)
        self.append([self.case['terminal_record']])
        report = self.runtime.player_target_stage_history()
        self.assertEqual(report['strictly_paired_target_updates'], 1)
        self.assertEqual(report['strictly_paired_terminal_submits'], 0)
        self.assertEqual(report['fully_linked_historical_stages'], 0)

    def test_foreign_thread_current_frame_cannot_touch_expired_owner_context(self):
        self.start()
        self.clock.now += 6_000_000_000
        revision = self.runtime._stage_observer.revision
        cached = revision.cached
        results, errors = [], []
        def read_from_foreign_thread():
            try: results.append(self.runtime.current_frame())
            except BaseException as error: errors.append(error)
        with patch.object(self.runtime.consumer, 'current_view',
                side_effect=AssertionError('foreign thread touched Consumer')) as current_view, \
             patch.object(revision, 'reset',
                side_effect=AssertionError('foreign thread mutated revision')) as reset:
            worker = threading.Thread(target=read_from_foreign_thread)
            worker.start(); worker.join(5)
            self.assertFalse(worker.is_alive())
            self.assertEqual(errors, [])
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]['reason'], 'owner_thread_required')
            self.assertNotEqual(results[0]['time_scope'], 'current_at_completed_poll')
            self.assertIsNone(results[0]['request_binding'])
            current_view.assert_not_called(); reset.assert_not_called()
        self.assertIs(revision.cached, cached)


if __name__ == '__main__':
    unittest.main()
