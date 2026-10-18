"""Real sanitized current slices; enclosing transports/mutations are synthetic.

Portable replay checks finite consistency, not owner original-byte authenticity.
"""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from mtgaplayer import current_target_request as target, semantic_targets
from mtgaplayer.shadow_history import _Evaluation, evaluate_shadow_history
from mtgaplayer.request_parameters import LiteralRefs
from mtgaplayer.decision_consumer import EXECUTION
from test_combat_frontier import baseline
from test_raw_log import state as raw_state

FIXTURE = Path(__file__).parent/'fixtures/current_target_no_cancel_real.json'


def wrap(message): return {'greToClientEvent': {'greToClientMessages': [message]}}


def rows_for(sample):
    """Invented bootstrap over aliased real public endpoints; not real GRE replay."""
    rows = baseline(); gs = raw_state(rows[2])
    gs['gameStateId'] = 10; gs['gameObjects'] = copy.deepcopy(sample['objects'])
    gs['zones'] = [{**z, 'objectInstanceIds': []} for z in gs['zones'] if z['type']=='ZoneType_Hand']+copy.deepcopy(sample['zones'])
    return rows+[wrap(copy.deepcopy(sample['message']))]


class CurrentTargetRequestTests(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads(FIXTURE.read_text(encoding='utf8')); self.sample = self.fixture['cases'][0]

    def ready(self, sample=None, history=False):
        sample = copy.deepcopy(self.sample if sample is None else sample)
        e = _Evaluation(target_stage_completions=history, current_target_coverage=history)
        for row in rows_for(sample): e.apply(row)
        return e, sample['message']

    def report(self, e, message, limit=64):
        return e.consumer.current_decision_options(limit=limit,
            current_target_context=(e.reducer, message))['current_target_evidence']

    def denied(self, result):
        self.assertEqual(result['status'], 'insufficient_evidence')
        self.assertIsNone(result['current_request_binding']); self.assertIsNone(result['source_snapshot_ref'])
        self.assertEqual(result['local_proposals'], []); self.assertIsNone(result['current_offered_members'])

    def safe(self, result):
        for key in EXECUTION: self.assertIs(result[key], False, key)
        self.assertFalse(result['complete_target_legality_verified'])
        self.assertFalse(result['historical_response_used'])
        self.assertIn('complete_target_combination_unknown', result['unknown'])

    def test_four_real_portable_slices_preserve_no_literal_and_separate_local_proposals(self):
        self.assertEqual(self.fixture['origin'], 'retained_scrubbed_real'); self.assertFalse(self.fixture['raw_equivalent'])
        self.assertEqual(hashlib.sha256(FIXTURE.read_bytes().replace(b'\r\n', b'\n')).hexdigest(),
            '1003f7935d3d7e4e0c7e52451bad0ad2189c58d2e6d1eff22c1b65661f117a5d')
        self.assertEqual(len(self.fixture['cases']), 4)
        sizes = []
        for sample in self.fixture['cases']:
            e, message = self.ready(sample); report = self.report(e, message); self.safe(report)
            self.assertEqual(report['status'], 'observed'); self.assertEqual(report['profile'], target.PROFILE)
            self.assertEqual(report['target_constraints']['allow_cancel'], 'AllowCancel_No')
            self.assertEqual(report['source_identity']['object_type'], 'GameObjectType_Ability')
            sizes.append(report['returned_proposals'])
            self.assertEqual(report['returned_proposals'], len(sample['message']['selectTargetsReq']['targets'][0]['targets']))
            for option in report['local_proposals']:
                self.assertEqual(option['kind'], 'reviewed_final_target_set')
                self.assertFalse(option['research_eligible']); self.assertFalse(option['execution_ready'])
                self.assertEqual(option['request_binding'], report['current_request_binding'])
                self.assertEqual(option['source_snapshot_ref'], report['source_snapshot_ref'])
                self.assertEqual(len(option['proposal']['proposed_final_target_set']['object_refs']), 1)
        self.assertEqual(sizes, [2, 3, 1, 1])

    def test_old_projector_stays_strict_and_optin_preserves_cancel_field(self):
        e, message = self.ready(); visible = e.consumer.current_view()['decision_state']['visible_objects']
        objects = [{'object_ref': o['instance_id'], 'zone': o['zone']} for o in visible]
        with self.assertRaises(ValueError): semantic_targets.project_request(message, objects, 1, LiteralRefs(), ())
        value = semantic_targets.project_request(message, objects, 1, LiteralRefs(), (), allow_no_cancel=True)
        self.assertEqual(value, self.report(e, message)['target_constraints'])
        with self.assertRaises(ValueError): semantic_targets.check_request(value, objects, 1)
        for bad in (1, None, 'yes'):
            with self.assertRaises(ValueError): semantic_targets.project_request(message, objects, 1, LiteralRefs(), (), allow_no_cancel=bad)
        for bad in (True, (), [e.reducer, message]):
            with self.assertRaises(ValueError):e.consumer.current_decision_options(current_target_context=bad)
        self.denied(e.consumer.current_decision_options(current_target_context=(None, message))['current_target_evidence'])

    def test_default_options_policy_cache_and_detached_returns_unchanged(self):
        for sample in self.fixture['cases']:
            e, message = self.ready(sample); before = e.consumer.current_decision_options(); policy = e.consumer.shadow_decision()
            enriched = e.consumer.current_decision_options(current_target_context=(e.reducer, message))
            report = enriched.pop('current_target_evidence'); self.assertEqual(enriched, before)
            self.assertEqual(policy['status'], 'abstain'); self.assertEqual(e.consumer.shadow_decision(), policy)
            self.assertEqual(e.consumer.current_decision_options(), before)
            self.assertEqual(self.report(e, message), report)
            report['local_proposals'][0]['execution_ready'] = True
            self.assertFalse(self.report(e, message)['local_proposals'][0]['execution_ready'])
            self.assertNotIn('current_target_evidence', before)

    def test_synthetic_typed_fields_quantity_slot_and_mixed_counterexamples(self):
        for mode in ('source_bool', 'source_float', 'group_bool', 'target_bool', 'target_float', 'slot_bool',
                     'slot_float', 'duplicate_slot', 'wrong_player', 'minimum_bool', 'maximum_float',
                     'missing_minimum', 'selected_float', 'mixed', 'unselect', 'duplicate_member', 'extra',
                     'target_group_mismatch', 'missing_prompt', 'undo_present'):
            with self.subTest(mode=mode):
                sample = copy.deepcopy(self.sample); message = sample['message']; body = message['selectTargetsReq']; slot = body['targets'][0]
                if mode == 'source_bool': body['sourceId'] = True
                elif mode == 'source_float': body['sourceId'] = float(body['sourceId'])
                elif mode == 'group_bool': body['abilityGrpId'] = True
                elif mode == 'target_bool': slot['targets'][0]['targetInstanceId'] = True
                elif mode == 'target_float': slot['targets'][0]['targetInstanceId'] = float(slot['targets'][0]['targetInstanceId'])
                elif mode == 'slot_bool': slot['targetIdx'] = True
                elif mode == 'slot_float': slot['targetIdx'] = float(slot['targetIdx'])
                elif mode == 'duplicate_slot': body['targets'] *= 2
                elif mode == 'wrong_player': slot['targetingPlayer'] = 2
                elif mode == 'minimum_bool': slot['minTargets'] = True
                elif mode == 'maximum_float': slot['maxTargets'] = 1.0
                elif mode == 'missing_minimum': slot.pop('minTargets')
                elif mode == 'selected_float': slot['selectedTargets'] = 1.0
                elif mode == 'mixed': slot['targets'][1]['legalAction'] = semantic_targets.UNSELECT
                elif mode == 'unselect':
                    slot['selectedTargets'] = 1; slot['targets'] = [slot['targets'][0]]
                    slot['targets'][0]['legalAction'] = semantic_targets.UNSELECT
                elif mode == 'duplicate_member': slot['targets'].append(copy.deepcopy(slot['targets'][0]))
                elif mode == 'target_group_mismatch': slot['targetingAbilityGrpId'] += 1
                elif mode == 'missing_prompt': message.pop('prompt')
                elif mode == 'undo_present': message['allowUndo'] = True
                else: slot['unreviewed'] = True
                e, message = self.ready(sample); self.denied(self.report(e, message))

    def test_synthetic_source_target_zone_visibility_and_identity_counterexamples(self):
        for mode in ('source_zone', 'target_zone', 'source_card', 'source_group', 'source_owner',
                     'source_private', 'target_private', 'missing_target', 'duplicate_identity', 'duplicate_zone'):
            with self.subTest(mode=mode):
                sample = copy.deepcopy(self.sample); source = sample['objects'][0]; member = sample['objects'][1]
                if mode == 'source_zone': sample['zones'][0]['type'] = 'ZoneType_Battlefield'
                elif mode == 'target_zone': sample['zones'][1]['type'] = 'ZoneType_Exile'
                elif mode == 'source_card': source['type'] = 'GameObjectType_Card'
                elif mode == 'source_group': source['grpId'] += 100
                elif mode == 'source_owner': source['ownerSeatId'] = 2
                elif mode == 'source_private': source['visibility'] = 'Visibility_Private'; source['viewers'] = [1]
                elif mode == 'target_private': member['visibility'] = 'Visibility_Private'; member['viewers'] = []
                elif mode == 'missing_target': sample['message']['selectTargetsReq']['targets'][0]['targets'][0]['targetInstanceId'] = 1
                elif mode == 'duplicate_identity': sample['objects'].append(copy.deepcopy(member))
                else:
                    zone = copy.deepcopy(sample['zones'][1]); zone['zoneId'] += 100
                    sample['zones'].append(zone)
                e, message = self.ready(sample); self.denied(self.report(e, message))

    def test_raw_digest_authentication_rechecked_even_on_option_cache_hit(self):
        e, message = self.ready(); self.assertEqual(self.report(e, message)['status'], 'observed')
        for field, value in (('msgId', 501), ('gameStateId', 10.0), ('systemSeatIds', [2]), ('allowCancel', 'AllowCancel_Abort')):
            changed = copy.deepcopy(message); changed[field] = value; self.denied(self.report(e, changed))
        changed = copy.deepcopy(message); changed['selectTargetsReq']['targets'][0]['targetIdx'] += 1
        self.denied(self.report(e, changed))
        self.assertEqual(self.report(e, message)['status'], 'observed')

    def test_authoritative_visible_projection_cannot_disagree(self):
        e, message = self.ready(); original = e.reducer.document
        def empty(*args, **kwargs):
            result = original(*args, **kwargs); result['current']['objects'] = []; return result
        with patch.object(e.reducer, 'document', side_effect=empty): self.denied(self.report(e, message))

    def test_current_ref_replacement_consumption_and_old_replay_do_not_revive(self):
        e, message = self.ready(); old = self.report(e, message)['source_snapshot_ref']
        entry = copy.deepcopy(message['selectTargetsReq']['targets'][0]['targets'][0])
        e.apply({'payload': {'type': 'ClientMessageType_SelectTargetsResp', 'respId': 500, 'gameStateId': 10,
            'selectTargetsResp': {'target': {'targetIdx': 1, 'targets': [entry]}}}})
        self.denied(self.report(e, message)); e.apply(wrap(message)); self.denied(self.report(e, message))
        self.assertNotEqual(e.consumer.current_view()['current_snapshot_ref'], old)
        new = copy.deepcopy(message); new['msgId'] = 501; e.apply(wrap(new))
        self.denied(self.report(e, message)); self.assertEqual(self.report(e, new)['status'], 'observed')
        self.assertNotEqual(self.report(e, new)['source_snapshot_ref'], old)

    def test_partial_full_reset_gap_cancel_undo_stop_and_expiry_fail_closed(self):
        for mode in ('partial', 'full', 'reset', 'gap', 'cancel', 'undo', 'stop', 'expiry'):
            with self.subTest(mode=mode):
                e, message = self.ready()
                if mode == 'partial': e.publish(partial=True)
                elif mode == 'reset': e.reducer.reset(2)
                elif mode == 'full': e.apply(rows_for(self.sample)[2])
                elif mode == 'gap': e.apply(wrap({'type': 'GREMessageType_GameStateMessage', 'systemSeatIds': [1],
                    'gameStateMessage': {'type': 'GameStateType_Diff', 'gameStateId': 11, 'prevGameStateId': 9}}))
                elif mode in ('cancel', 'undo'): e.apply({'payload': {'type': 'ClientMessageType_CancelActionReq' if mode == 'cancel' else 'ClientMessageType_UndoReq'}})
                elif mode == 'stop':
                    for event in e.publisher.stop('sample_limit'): self.assertTrue(e.consumer.accept_event(event))
                else: e.ordinal += 10**15
                self.denied(self.report(e, message))

    def test_expiry_or_raw_consumption_during_projection_discards_result(self):
        for mode in ('expiry', 'consume'):
            e, message = self.ready()
            from mtgaplayer import choice_candidates
            original = choice_candidates._target_proposals
            def late(*args, **kwargs):
                result = original(*args, **kwargs)
                if mode == 'expiry': e.ordinal += 10**15
                else: e.reducer.apply({'payload': {'type': 'ClientMessageType_SubmitTargetsReq', 'respId': 500, 'gameStateId': 10}})
                return result
            with patch.object(choice_candidates, '_target_proposals', side_effect=late): self.denied(self.report(e, message))

    def test_interrupted_context_retransmission_and_response_cannot_restore_new_evidence(self):
        for mode in ('cancel', 'undo', 'unsupported', 'broadcast', 'mixed', 'partial', 'submit_extra'):
            with self.subTest(mode=mode):
                e, message = self.ready(history=True)
                if mode in ('cancel', 'undo', 'unsupported'):
                    typ = {'cancel':'ClientMessageType_CancelActionReq', 'undo':'ClientMessageType_UndoReq',
                        'unsupported':'ClientMessageType_UnreviewedRequest'}[mode]
                    e.apply({'payload': {'type': typ}})
                elif mode == 'broadcast':
                    b = copy.deepcopy(message); b['systemSeatIds'] = [1, 2]; e.apply(wrap(b))
                elif mode == 'mixed':
                    row = wrap(copy.deepcopy(message)); row['payload'] = {'type': 'ClientMessageType_UIMessage'}; e.apply(row)
                elif mode == 'submit_extra':
                    e.apply({'payload': {'type': 'ClientMessageType_SubmitTargetsReq', 'respId': 500,
                        'gameStateId': 10, 'unreviewed': True}})
                else:e.publish(partial=True)
                self.denied(self.report(e, message)); e.apply(wrap(copy.deepcopy(message)))
                self.denied(self.report(e, message))
                for version in (False, True):
                    self.assertNotIn('_target_evidence_interrupted', json.dumps(e.reducer.document(include_decision_state=version)))
                slot = message['selectTargetsReq']['targets'][0]
                e.apply({'payload': {'type': 'ClientMessageType_SelectTargetsResp', 'respId': 500, 'gameStateId': 10,
                    'selectTargetsResp': {'target': {'targetIdx': slot['targetIdx'], 'targets': [copy.deepcopy(slot['targets'][0])]}}}})
                self.assertEqual(e.target_coverage['paired_updates_newly_reviewable'], 0)
        e, message = self.ready(); before = self.report(e, message)
        e.apply({'payload': {'type': 'ClientMessageType_UIMessage'}})
        self.assertEqual(self.report(e, message), before)

    def test_no_observer_broadcast_and_typed_diff_predecessor_witness(self):
        e, message = self.ready(); e.reducer.observer = None
        broadcast = copy.deepcopy(message); broadcast['systemSeatIds'] = [1, 2]
        e.reducer.apply(wrap(broadcast)); self.denied(self.report(e, message))
        for predecessor in (10, 10.0, True):
            with self.subTest(predecessor=predecessor):
                e, message = self.ready()
                e.apply(wrap({'type': 'GREMessageType_GameStateMessage', 'systemSeatIds': [1],
                    'gameStateMessage': {'type': 'GameStateType_Diff', 'gameStateId': 11, 'prevGameStateId': predecessor}}))
                new = copy.deepcopy(message); new.update(msgId=501, gameStateId=11); e.apply(wrap(new))
                if type(predecessor) is int: self.assertEqual(self.report(e, new)['status'], 'observed')
                else: self.denied(self.report(e, new))

    def test_candidate_truncation_keeps_counts_and_unknown_rules(self):
        e, message = self.ready(self.fixture['cases'][1]); report = self.report(e, message, 1)
        self.assertEqual(report['candidate_total_for_reviewed_constraints'], 3)
        self.assertEqual(report['returned_proposals'], 1); self.assertTrue(report['truncated']); self.safe(report)
        bad = copy.deepcopy(self.sample); bad['message']['selectTargetsReq']['targets'][0]['targets'] *= 40
        e, message = self.ready(bad); self.denied(self.report(e, message))

    def test_historical_optin_counts_current_update_without_inventing_terminal(self):
        e, message = self.ready(history=True); policy = e.consumer.shadow_decision()
        slot = message['selectTargetsReq']['targets'][0]
        e.apply({'payload': {'type': 'ClientMessageType_SelectTargetsResp', 'respId': 500, 'gameStateId': 10,
            'selectTargetsResp': {'target': {'targetIdx': slot['targetIdx'], 'targets': [copy.deepcopy(slot['targets'][0])]}}}})
        self.assertEqual(e.target_coverage['newly_reviewed_current_requests'], 1)
        self.assertEqual(e.target_coverage['paired_updates_newly_reviewable'], 1)
        self.assertEqual(e.target_completions.report()['historical_reviewed_target_sets_submitted'], 0)
        self.assertEqual(e.target_completions.report()['comparable_shadow_target_preferences'], 0)
        self.assertEqual(policy['status'], 'abstain'); self.assertEqual(e.consumer.shadow_decision()['status'], 'expired')

    def test_history_cli_default_units_privacy_and_unfinished_eof(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'private-path-not-exported.log'
            path.write_text(''.join(json.dumps(row)+'\n' for row in rows_for(self.sample)), encoding='utf8')
            a = evaluate_shadow_history(path, target_stage_completions=True)
            b = evaluate_shadow_history(path, target_stage_completions=True, current_target_coverage=True)
            report = b.pop('current_target_request_coverage'); b['timings_ms'].pop('current_target_coverage')
            a.pop('timings_ms'); b.pop('timings_ms'); self.assertEqual(a, b)
            self.assertEqual(report['previously_unprojected_requests'], 1)
            self.assertEqual(report['newly_reviewed_current_requests'], 1)
            self.assertEqual(report['strictly_linked_historical_completions'], 0)
            self.assertIsNone(report['complete_target_legality'])
            for flags in (['--current-target-coverage'], ['--target-stage-completions', '--current-target-coverage']):
                result = subprocess.run([sys.executable, '-m', 'mtgaplayer', 'evaluate-shadow-history', str(path), *flags], capture_output=True, text=True)
                self.assertEqual(result.returncode, int(len(flags)==1), result.stdout+result.stderr)
                if len(flags)==2:
                    decoded = json.loads(result.stdout); self.assertEqual(decoded['current_target_request_coverage'], report)
                    for secret in (str(path), 'redacted-public-source', 'targetInstanceId'): self.assertNotIn(secret, result.stdout)

    def test_public_cast_contract_does_not_gain_no_cancel_evidence(self):
        path = Path(__file__).parent/'fixtures/player_log_single_target.jsonl'
        a = evaluate_shadow_history(path, target_stage_completions=True)
        b = evaluate_shadow_history(path, target_stage_completions=True, current_target_coverage=True)
        self.assertEqual(a['target_stage_completions'], b['target_stage_completions'])
        self.assertEqual(a['totals'], b['totals']); self.assertEqual(b['totals']['research_preferences'], 0)
        self.assertEqual(b['current_target_request_coverage']['newly_reviewed_current_requests'], 0)


if __name__ == '__main__': unittest.main()
