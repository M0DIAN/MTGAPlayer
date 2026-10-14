"""Narrow MP16 proof of Pass/Play request-local correlation and non-disclosure."""
import json
import unittest
from collections import Counter

from mtgaplayer.semantic_evidence import SemanticChoiceCounter


def request(rows):
    counts = Counter(row.get('action_type') for row in rows)
    return {'action_inventory': {
        'offered_count': len(rows), 'simple_shapes': rows,
        'types': [{'action_type': typ, 'count': count}
                  for typ, count in sorted(counts.items())]}}


def response(row, sibling=None):
    body = {'actions': [row]}
    if sibling is not None:
        body['PRIVATE_FIELD'] = sibling
    return {'performActionResp': body}


PASS = {'list_position': 0, 'action_type': 'ActionType_Pass'}
PLAY = {'list_position': 1, 'action_type': 'ActionType_Play',
        'instance_id': 166, 'grp_id': 96839, 'facet_id': 0, 'should_stop_raw': False}
PLAY_RESP = {'actionType': 'ActionType_Play', 'instanceId': 166,
             'grpId': 96839, 'facetId': 0, 'shouldStop': False}


class ChoiceCorrelationTests(unittest.TestCase):
    def count(self, cases):
        tracker = SemanticChoiceCounter()
        for pair in cases:
            tracker.add(*pair)
        return tracker.report()

    def test_pass_and_play_unique_and_unknown_sibling_not_exported(self):
        result = self.count([
            (request([PASS, PLAY]), response({'actionType': 'ActionType_Pass'})),
            (request([PASS, PLAY]), response(PLAY_RESP, 'SECRET_DO_NOT_EXPORT')),
        ])
        self.assertEqual(result['correlation_results'][0]['count'], 2)
        self.assertTrue(result['counts_account_for_all_matched_action_responses'])
        self.assertNotIn('SECRET_DO_NOT_EXPORT', json.dumps(result))
        self.assertNotIn('96839', json.dumps(result))
        self.assertFalse(result['complete_response_encoding_verified'])
        self.assertFalse(result['input_sent'])

    def test_duplicate_pass_is_multiple_not_first_match(self):
        double = [PASS, {'list_position': 1, 'action_type': 'ActionType_Pass'}]
        result = self.count([(request(double), response({'actionType': 'ActionType_Pass'}))])
        self.assertEqual(result['correlation_results'][1]['count'], 1)

    def test_play_exact_fields_required_wrong_identifiers_or_bool_are_not_matches(self):
        wrong = dict(PLAY_RESP, grpId=777)
        self.assertEqual(self.count([(request([PASS, PLAY]), response(wrong))])
                         ['correlation_results'][2]['count'], 1)
        bad = dict(PLAY_RESP, shouldStop=0)
        self.assertEqual(self.count([(request([PASS, PLAY]), response(bad))])
                         ['correlation_results'][3]['count'], 1)

    def test_unparsed_same_type_source_cannot_prove_no_match(self):
        req = request([PASS])
        req['action_inventory']['offered_count'] = 2
        req['action_inventory']['types'][0]['count'] = 2
        report = self.count([(req, response({'actionType': 'ActionType_Pass'}))])
        self.assertEqual(report['correlation_results'][3]['count'], 1)

    def test_unknown_extra_and_complex_are_unsupported_and_values_hidden(self):
        tracker = self.count([
            (request([PASS]), response({'actionType': 'ActionType_UNKNOWN_SECRET'})),
            (request([PASS]), response({'actionType': 'ActionType_Pass',
                                         'hidden': 'DONT_EXPORT'})),
            (request([PASS]), response({'actionType': 'ActionType_Cast',
                                         'targets': [{'private': 'VERY_SECRET'}]})),
            (request([PASS]), {'performActionResp': {'actions': [
                {'actionType': 'ActionType_Pass'}, {'actionType': 'ActionType_Pass'}]}}),
        ])
        self.assertEqual(tracker['correlation_results'][3]['count'], 4)
        self.assertEqual(tracker['matched_action_responses_classified'], 4)
        for secret in ('ActionType_UNKNOWN_SECRET', 'DONT_EXPORT', 'VERY_SECRET'):
            self.assertNotIn(secret, json.dumps(tracker))

    def test_corrupt_or_unbound_source_shapes_are_not_promoted_to_match(self):
        malformed = request([PASS, PLAY])
        malformed['action_inventory']['simple_shapes'] = [dict(PASS, list_position=True)]
        report = self.count([(malformed, response({'actionType': 'ActionType_Pass'}))])
        self.assertEqual(report['correlation_results'][3]['count'], 1)
        missing = request([PASS])
        del missing['action_inventory']['simple_shapes']
        report = self.count([(missing, response({'actionType': 'ActionType_Pass'}))])
        self.assertEqual(report['correlation_results'][3]['count'], 1)


if __name__ == '__main__':
    unittest.main()
