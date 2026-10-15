"""Accepted raw content uses the existing single request digest ledger."""
import copy
import unittest

from mtgaplayer.raw_log import RawReducer
from mtgaplayer.response_evidence import _current_verified_raw_request
from test_raw_log import entries

class RequestContentBindingTests(unittest.TestCase):
    def test_actual_accepted_event_authenticates_only_its_content(self):
        accepted = []
        reducer = RawReducer(observer=lambda event, details:
            accepted.append(details['message']) if event == 'request_accepted' else None)
        for row in entries()[:3]:
            reducer.apply(row)
        message = {'type': 'GREMessageType_DeclareAttackersReq', 'msgId': 990,
            'gameStateId': 1, 'systemSeatIds': [1], 'declareAttackersReq': {'qualifiedAttackers': []}}
        reducer.apply({'greToClientEvent': {'greToClientMessages': [message]}})
        self.assertEqual(accepted, [message])
        self.assertIsNotNone(_current_verified_raw_request(reducer, message))
        for seats in ([True], [1.0], [2], [1, 2]):
            rejected = copy.deepcopy(message)
            rejected['systemSeatIds'] = seats
            self.assertIsNone(_current_verified_raw_request(reducer, rejected))
        altered = copy.deepcopy(message)
        altered['declareAttackersReq']['qualifiedAttackers'] = [{'attackerInstanceId': 701}]
        self.assertIsNone(_current_verified_raw_request(reducer, altered))
        reducer.apply({'payload': {'type': 'ClientMessageType_DeclareAttackersResp',
            'respId': 990, 'gameStateId': 1}})
        self.assertIsNone(_current_verified_raw_request(reducer, message))

if __name__ == '__main__':
    unittest.main()
