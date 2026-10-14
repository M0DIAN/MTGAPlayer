"""Phase 2 identity evidence is distinct from parameter legality and execution."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from mtgaplayer.raw_log import _available_action_inventory
from mtgaplayer.response_evidence import inspect_response_envelopes
from mtgaplayer.semantic_evidence import ComplexSemanticChoiceCounter, _classify
from test_response_evidence import action_request, reply, save, source_rows, SCRIPT


def action(typ='ActionType_Cast', **changes):
    row = {'actionType': typ, 'instanceId': 777001, 'grpId': 888002,
           'facetId': 0, 'shouldStop': False, 'manaCost': [],
           'autoTapSolution': {'autoTapActions': []}}
    if typ in ('ActionType_Activate', 'ActionType_Activate_Mana'):
        row.update(abilityGrpId=999003, uniqueAbilityId=999004)
    if typ == 'ActionType_Activate_Mana':
        for field in ('shouldStop', 'manaCost', 'autoTapSolution'):
            del row[field]
        row.update(isBatchable=True, isManaAbilityWithSideEffect=False,
                   manaSelections=[], manaPaymentOptions=[])
    row.update(changes)
    return row


def request(rows, inactive=None):
    payload = {'actions': rows}
    if inactive is not None:
        payload['inactiveActions'] = inactive
    return _available_action_inventory({'actionsAvailableReq': payload})


def response(row, **siblings):
    return {'performActionResp': {'actions': [row], **siblings}}


def classify(req, resp):
    counter = ComplexSemanticChoiceCounter()
    counter.add(req, resp)
    report = counter.report()
    results = report['selected_action_identity']['results_by_action_type']
    row = next(row for row in results if row['matched_response_count'])
    status = next(status for status in ('unique', 'multiple', 'no_match', 'incomplete_or_unsupported')
                  if row[status + '_count'])
    return status, row, report


class ComplexCorrelationTests(unittest.TestCase):
    def test_observed_identity_schemas_and_parameter_separation(self):
        for typ in ('ActionType_Cast', 'ActionType_Activate', 'ActionType_Activate_Mana'):
            with self.subTest(typ=typ):
                row = action(typ)
                status, _, report = classify(request([row]), response(row))
                self.assertEqual(status, 'unique')
                self.assertEqual(report['legal_parameter_verification']['status'], 'unverified')
                for flag in ('response_encoding_verified', 'legal_choice_verified',
                             'execution_ready', 'input_sent'):
                    self.assertIs(report[flag], False)
                self.assertIs(report['read_only'], True)

    def test_same_instance_abilities_and_facets_are_not_collapsed(self):
        for typ, discriminator in (('ActionType_Activate', 'abilityGrpId'),
                                   ('ActionType_Activate', 'uniqueAbilityId'),
                                   ('ActionType_Activate_Mana', 'uniqueAbilityId'),
                                   ('ActionType_Cast', 'facetId')):
            with self.subTest(typ=typ, discriminator=discriminator):
                first = action(typ)
                second = dict(first, **{discriminator: first[discriminator] + 1})
                self.assertEqual(classify(request([first, second]), response(second))[0], 'unique')
                wrong = dict(second, **{discriminator: second[discriminator] + 1})
                self.assertEqual(classify(request([first, second]), response(wrong))[0], 'no_match')
        row = action('ActionType_Activate')
        missing_ability = dict(row)
        del missing_ability['uniqueAbilityId']
        self.assertEqual(classify(request([row]), response(missing_ability))[0], 'incomplete_or_unsupported')

    def test_duplicate_identity_including_parameter_variants_is_multiple(self):
        row = action()
        other = dict(row, targets=[{'targetIdx': 0, 'targets': [111]}])
        self.assertEqual(classify(request([row, other]), response(row))[0], 'multiple')
        duplicate = action('ActionType_Activate')
        self.assertEqual(classify(request([duplicate, duplicate]), response(duplicate))[0], 'multiple')
        for typ, flag in (('ActionType_Cast', 'shouldStop'),
                          ('ActionType_Activate', 'shouldStop'),
                          ('ActionType_Activate_Mana', 'isBatchable'),
                          ('ActionType_Activate_Mana', 'isManaAbilityWithSideEffect')):
            first = action(typ)
            second = dict(first, **{flag: not first[flag]})
            with self.subTest(typ=typ, flag=flag):
                self.assertEqual(classify(request([first, second]), response(second))[0], 'multiple')

    def test_unknown_mode_or_other_discriminator_blocks_identity_claim(self):
        row = action('ActionType_Activate')
        for changed in (dict(row, SECRET_MODE=1),):
            status, counts, _ = classify(request([row]), response(changed))
            self.assertEqual(status, 'incomplete_or_unsupported')
            self.assertEqual(counts['unknown_parameter_count'], 1)
        other = dict(row, SECRET_MODE=2)
        self.assertEqual(classify(request([row, other]), response(row))[0], 'incomplete_or_unsupported')
        # Opaque parameter contents are observed, never parsed or certified.
        status, counts, _ = classify(request([row]), response(dict(row, targets=[{'SECRET_MODE': 'PRIVATE'}])))
        self.assertEqual(status, 'unique')
        self.assertEqual(counts['unknown_parameter_count'], 1)

    def test_unknown_wrapper_is_counted_without_erasing_proven_identity(self):
        row = action()
        status, counts, _ = classify(request([row]), response(row, PRIVATE_WRAPPER='SECRET_VALUE'))
        self.assertEqual(status, 'unique')
        self.assertEqual(counts['unknown_parameter_count'], 1)

    def test_required_identity_strict_types_missing_and_unknown(self):
        row = action('ActionType_Activate')
        for field in ('instanceId', 'grpId', 'facetId', 'abilityGrpId', 'uniqueAbilityId'):
            for value in (None, True, 1.0, '777001', -1, 2**53):
                with self.subTest(field=field, value=value):
                    self.assertEqual(classify(request([row]), response(dict(row, **{field: value})))[0],
                                     'incomplete_or_unsupported')
            missing = dict(row)
            del missing[field]
            self.assertEqual(classify(request([row]), response(missing))[0], 'incomplete_or_unsupported')
        self.assertEqual(classify(request([row]), response(dict(row, actionType='SECRET_UNKNOWN')))[0],
                         'incomplete_or_unsupported')

    def test_any_incomplete_same_type_candidate_blocks_unique_and_no_match(self):
        row = action('ActionType_Activate')
        for value in (None, True, 1.5):
            incomplete = dict(row, uniqueAbilityId=value, instanceId=12)
            for selected in (row, dict(row, instanceId=13)):
                self.assertEqual(classify(request([row, incomplete]), response(selected))[0],
                                 'incomplete_or_unsupported')
        req = request([row])
        req['action_inventory']['complex_raw_shapes'].clear()
        self.assertEqual(classify(req, response(dict(row, instanceId=13)))[0], 'incomplete_or_unsupported')
        req = request([row])
        del req['action_inventory']['_frontier_rows']
        self.assertEqual(classify(req, response(row))[0], 'incomplete_or_unsupported')

    def test_candidate_and_type_accounting_corruption_never_proves_no_match(self):
        row = action()
        for mutate in (
                lambda inv: inv['types'][0].update(count=2),
                lambda inv: inv.update(type_labels_complete=False),
                lambda inv: inv['complex_raw_shapes'][0].update(list_position=True),
                lambda inv: inv['complex_raw_shapes'].append(copy.deepcopy(inv['complex_raw_shapes'][0])),
                lambda inv: inv['_frontier_rows'][0].update(action_type=['bad']),
                lambda inv: inv['complex_raw_shapes'][0].update(raw_relations={}),
                lambda inv: inv['complex_raw_shapes'][0].pop('opaque_parameter_shapes'),
                lambda inv: inv['_frontier_rows'][0].pop('known_parameter_shapes'),
                lambda inv: inv['complex_raw_shapes'][0]['raw_relations']['auto_tap_mana_links'].pop('truncated'),
                lambda inv: inv.update(other_payload_fields_present=True)):
            req = request([row])
            mutate(req['action_inventory'])
            self.assertEqual(classify(req, response(dict(row, instanceId=1)))[0], 'incomplete_or_unsupported')

    def test_inactive_actions_are_excluded_and_empty_complete_set_can_prove_no_match(self):
        row = action()
        self.assertEqual(classify(request([], inactive=[row]), response(row))[0], 'no_match')
        self.assertEqual(classify(request([dict(row, instanceId=1)], inactive=[row]), response(row))[0], 'no_match')

    def test_truncation_and_wrong_parameter_storage_are_explicit(self):
        row = action()
        for changed in (dict(row, targets=1), dict(row, shouldStop=1),
                        dict(row, autoTapSolution=[])):
            self.assertEqual(classify(request([row]), response(changed))[0], 'incomplete_or_unsupported')
        selected = dict(row, targets=[{'targetIdx': 0, 'targets': []}] * 65)
        status, counts, _ = classify(request([row]), response(selected))
        self.assertEqual(status, 'incomplete_or_unsupported')
        self.assertEqual(counts['truncated_count'], 1)
        status, counts, _ = classify(request([selected]), response(row))
        self.assertEqual(status, 'incomplete_or_unsupported')
        self.assertEqual(counts['truncated_count'], 1)
        _, counts, _ = classify(request([row]), {'performActionResp': {'actions': [row] * 65}})
        self.assertEqual(counts['truncated_count'], 1)

    def test_privacy_fixed_categories_and_complete_accounting(self):
        counter = ComplexSemanticChoiceCounter()
        for row, offered in ((action(), [action()]), (action(), [action(), action()]),
                             (action(instanceId=1), [action()]),
                             (action(PRIVATE_FIELD='PRIVATE_VALUE'), [action()])):
            counter.add(request(offered), response(row))
        counter.add(request([]), response({'actionType': 'PRIVATE_TYPE'}))
        report = counter.report()
        self.assertTrue(report['selected_action_identity']['counts_account_for_all_matched_action_responses'])
        rows = report['selected_action_identity']['results_by_action_type']
        self.assertEqual(sum(row['matched_response_count'] for row in rows), 5)
        self.assertEqual([sum(row[status + '_count'] for row in rows) for status in
                          ('unique', 'multiple', 'no_match', 'incomplete_or_unsupported')], [1, 1, 1, 2])
        output = json.dumps(report)
        for secret in ('777001', '888002', '999003', 'PRIVATE_FIELD', 'PRIVATE_VALUE', 'PRIVATE_TYPE'):
            self.assertNotIn(secret, output)

    def test_exact_envelope_lifecycle_and_cli_mode(self):
        row = action('ActionType_Activate')
        details = {'actions': [row]}
        newer = action_request([row], msg_id=38)
        prompt = next(message for message in newer['greToClientEvent']['greToClientMessages']
                      if message.get('type') == 'GREMessageType_ActionsAvailableReq')
        frames = source_rows()[:9] + [action_request([row], msg_id=37),
                 {'greToClientEvent': {'greToClientMessages': [prompt]}}, reply(37, details=details),
                 reply(38, 24, details), reply(38, 23, details), reply(38, 23, details)]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'Player.log'
            save(path, frames)
            report = inspect_response_envelopes(path, complex_semantic_choices=True)
            result = subprocess.run([sys.executable, str(SCRIPT), str(path),
                                     '--complex-response-choice-correlation'], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), report)
            for mode in ('--response-choice-correlation', '--response-action-shapes', '--response-envelopes'):
                invalid = subprocess.run([sys.executable, str(SCRIPT), str(path),
                                          '--complex-response-choice-correlation', mode], capture_output=True, text=True)
                self.assertEqual(invalid.returncode, 2)
        self.assertEqual(report['matched_actions_available_responses'], 1)
        self.assertEqual(report['unmatched_or_noncurrent_responses'], 3)
        identity = report['complex_action_choice_correlation']['selected_action_identity']
        self.assertEqual(next(r for r in identity['results_by_action_type'] if r['action_type'] ==
                              'ActionType_Activate')['unique_count'], 1)

    def test_opponent_broadcast_and_wrong_response_type_never_reach_counter(self):
        row = action()
        for recipient in ([2], [1, 2]):
            frames = source_rows()[:9] + [action_request([row], recipient=recipient), reply(details={'actions': [row]})]
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'Player.log'
                save(path, frames)
                report = inspect_response_envelopes(path, complex_semantic_choices=True)
            self.assertEqual(report['complex_action_choice_correlation']['matched_action_responses_classified'], 0)
        wrong = reply(details={'actions': [row]})
        wrong['payload']['type'] = 'ClientMessageType_SelectNResp'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'Player.log'
            save(path, source_rows()[:9] + [action_request([row]), wrong, reply(details={'actions': [row]})])
            report = inspect_response_envelopes(path, complex_semantic_choices=True)
        self.assertEqual(report['complex_action_choice_correlation']['matched_action_responses_classified'], 0)

    def test_api_modes_are_mutually_exclusive(self):
        for modes in ({'semantic_choices': True}, {'action_shapes': True}):
            with self.assertRaises(ValueError):
                inspect_response_envelopes('not-opened', complex_semantic_choices=True, **modes)

    def test_new_mode_pass_play_decisions_exactly_reuse_phase1(self):
        passed = {'actionType': 'ActionType_Pass'}
        played = {'actionType': 'ActionType_Play', 'instanceId': 12,
                  'grpId': 13, 'facetId': 0, 'shouldStop': False}
        for rows, selected in (([passed], passed), ([passed, passed], passed),
                               ([played], played), ([played, played], played),
                               ([dict(played, grpId=14)], played),
                               ([passed, {'actionType': 'UNREVIEWED'}], passed),
                               ([played], dict(played, instanceId=True)),
                               ([passed], dict(passed, PRIVATE_MODE=1))):
            req, resp = request(rows), response(selected, PRIVATE_WRAPPER='OPAQUE')
            self.assertEqual(classify(req, resp)[0], _classify(req, resp)[1])


if __name__ == '__main__':
    unittest.main()
