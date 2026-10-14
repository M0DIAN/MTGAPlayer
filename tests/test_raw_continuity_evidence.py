"""Synthetic structural counterexample derived from safe continuity evidence.

These invented IDs, card placeholders, users and room are not a raw-log replay.
The observed RevealedCard/Hand/Revealed relation, its deletion tail and an
unlisted opaque row are modeled; unrelated fields and original values are absent.
"""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from mtgaplayer.cli import replay
from mtgaplayer.raw_log import RawReducer


MATCH = 'synthetic-continuity-match'
SELF = 'synthetic-continuity-self'
OTHER = 'synthetic-continuity-other'
OWN_HAND, OTHER_HAND, BATTLEFIELD, STACK, REVEALED = range(81001, 81006)
OWN_CARD, OTHER_CARD, REVEALED_CARD = range(71001, 71004)
OWN_GRP, OTHER_GRP, REVEALED_GRP = range(91001, 91004)
BASE_VERSION = 1000


def zone(zone_id, kind, owner, members=None, visibility='Visibility_Private'):
    row = {'zoneId': zone_id, 'type': kind, 'ownerSeatId': owner,
           'visibility': visibility}
    if members is not None:
        row['objectInstanceIds'] = members
    return row


def gre(*messages):
    return {'greToClientEvent': {'greToClientMessages': list(messages)}}


def state_message(payload):
    return {'type': 'GREMessageType_GameStateMessage', 'systemSeatIds': [1],
            'gameStateMessage': payload}


def full(version=BASE_VERSION, game=1):
    return gre(state_message({
        'type': 'GameStateType_Full', 'gameStateId': version,
        'gameInfo': {'matchID': MATCH, 'gameNumber': game,
                     'stage': 'GameStage_Play'},
        'gameObjects': [
            {'instanceId': OWN_CARD, 'type': 'GameObjectType_Card',
             'zoneId': OWN_HAND, 'grpId': OWN_GRP, 'ownerSeatId': 1,
             'controllerSeatId': 1, 'visibility': 'Visibility_Private',
             'viewers': [1]},
            {'instanceId': OTHER_CARD, 'type': 'GameObjectType_Card',
             'zoneId': OTHER_HAND, 'grpId': OTHER_GRP, 'ownerSeatId': 2,
             'controllerSeatId': 2, 'visibility': 'Visibility_Private',
             'viewers': [2], 'syntheticIdentity': 'OTHER_CARD_SENTINEL'},
        ],
        'zones': [zone(OWN_HAND, 'ZoneType_Hand', 1, [OWN_CARD]),
                  zone(OTHER_HAND, 'ZoneType_Hand', 2, [OTHER_CARD]),
                  zone(BATTLEFIELD, 'ZoneType_Battlefield', 1, [],
                       'Visibility_Public'),
                  zone(STACK, 'ZoneType_Stack', 1, [], 'Visibility_Public'),
                  zone(REVEALED, 'ZoneType_Revealed', 2, [],
                       'Visibility_Public')],
        'players': [{'systemSeatNumber': 1, 'lifeTotal': 20},
                    {'systemSeatNumber': 2, 'lifeTotal': 20}],
        'turnInfo': {'turnNumber': 1, 'activePlayer': 1, 'decisionPlayer': 1},
    }))


def request(version=BASE_VERSION + 1, request_id=61001, include_revealed=False):
    return {'type': 'GREMessageType_ActionsAvailableReq', 'systemSeatIds': [1],
            'msgId': request_id, 'gameStateId': version,
            'actionsAvailableReq': {'actions': [
                {'actionType': 'ActionType_Play', 'instanceId': OWN_CARD,
                 'grpId': OWN_GRP, 'facetId': 0, 'shouldStop': False},
                {'actionType': 'ActionType_Cast', 'instanceId': OTHER_CARD,
                 'manaCost': []},
                {'actionType': 'ActionType_Pass'},
                *([{'actionType': 'ActionType_Cast', 'instanceId': REVEALED_CARD,
                    'manaCost': []}]
                  if include_revealed else []),
            ]}}


def prefix():
    return [
        {'authenticateResponse': {'clientId': SELF}},
        {'matchGameRoomStateChangedEvent': {'gameRoomInfo': {
            'stateType': 'MatchGameRoomStateType_Playing',
            'gameRoomConfig': {'matchId': MATCH, 'reservedPlayers': [
                {'userId': SELF, 'systemSeatId': 1},
                {'userId': OTHER, 'systemSeatId': 2},
            ]}}}},
        full(),
        gre(state_message({'type': 'GameStateType_Diff',
                           'gameStateId': BASE_VERSION + 1,
                           'prevGameStateId': BASE_VERSION}), request()),
    ]


def reveal_state():
    # New private nonself RevealedCard declares an existing private Hand, but
    # belongs only to the same owner's public Revealed membership list.
    return {
        'type': 'GameStateType_Diff', 'gameStateId': BASE_VERSION + 2,
        'prevGameStateId': BASE_VERSION + 1,
        'gameObjects': [{
            'instanceId': REVEALED_CARD, 'type': 'GameObjectType_RevealedCard',
            'zoneId': OTHER_HAND, 'grpId': REVEALED_GRP, 'ownerSeatId': 2,
            'controllerSeatId': 2, 'visibility': 'Visibility_Private',
            'syntheticIdentity': 'REVEALED_CARD_SENTINEL',
        }],
        'annotations': [{'id': 51001, 'type': ['AnnotationType_RevealedCardCreated'],
                         'affectorId': REVEALED_CARD, 'affectedIds': [REVEALED_CARD]}],
        'zones': [zone(OTHER_HAND, 'ZoneType_Hand', 2, [OTHER_CARD]),
                  zone(REVEALED, 'ZoneType_Revealed', 2, [REVEALED_CARD],
                       'Visibility_Public')],
    }


def deletion_tail():
    # Zone rows are replacements: the Revealed row omits objectInstanceIds.
    return gre(state_message({
        'type': 'GameStateType_Diff', 'gameStateId': BASE_VERSION + 4,
        'prevGameStateId': BASE_VERSION + 3,
        'diffDeletedInstanceIds': [REVEALED_CARD],
        'zones': [zone(OTHER_HAND, 'ZoneType_Hand', 2, [OTHER_CARD]),
                  zone(REVEALED, 'ZoneType_Revealed', 2,
                       visibility='Visibility_Public')],
    }))


def reduce_prefix():
    reducer = RawReducer()
    reducer.reset(1)
    for row in prefix():
        reducer.apply(row)
    return reducer


def projected(rows):
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'synthetic-continuity.jsonl'
        path.write_text(''.join(json.dumps(row) + '\n' for row in rows),
                        encoding='utf-8')
        return replay(path, format='player-log', decision_input=True,
                      action_frontier=True, choice_graph=True)


class RawContinuityEvidenceTests(unittest.TestCase):
    def assert_blocked(self, document):
        self.assertFalse(document['current']['valid'])
        self.assertFalse(document['current']['actionable'])
        self.assertNotIn('objects', document['current'])
        self.assertNotIn('request', document['current'])

    def test_structural_reveal_is_opaque_and_continuity_survives_until_deletion(self):
        reducer = reduce_prefix()
        before = reducer.document()
        self.assertTrue(before['current']['valid'])
        self.assertEqual(before['current']['request']['binding']['self_seat'], 1)
        self.assertTrue(before['current']['request']['binding']['ownership_verified'])
        self.assertEqual([obj['id'] for obj in before['last_valid']['objects']], [OWN_CARD])
        good_projection = projected(prefix())
        for name in ('decision_input', 'action_frontier', 'choice_graph'):
            self.assertIsNotNone(good_projection[name], name)

        reveal = reveal_state()
        # Even an added self viewer cannot promote the opaque view to a card.
        reveal['gameObjects'][0]['viewers'] = [1, 2]
        event = gre(state_message(reveal), request(BASE_VERSION + 2, 61002, True))
        reducer.apply(event)
        document = reducer.document()
        self.assertIsNone(document['error'])
        self.assertTrue(document['current']['valid'])
        self.assertEqual(reducer.version, BASE_VERSION + 2)
        self.assertEqual(reducer.objects[REVEALED_CARD], reveal['gameObjects'][0])
        self.assertEqual(reducer.objects[REVEALED_CARD]['zoneId'], OTHER_HAND)
        self.assertNotIn(REVEALED_CARD, reducer.zones[OTHER_HAND]['objectInstanceIds'])
        self.assertEqual(reducer.zones[REVEALED]['objectInstanceIds'], [REVEALED_CARD])
        self.assertEqual(document['current']['hidden_counts'],
                         before['current']['hidden_counts'])
        self.assertEqual([obj['id'] for obj in document['current']['objects']], [OWN_CARD])

        projection = projected(prefix() + [event])
        for name in ('decision_input', 'action_frontier', 'choice_graph'):
            self.assertIsNotNone(projection[name], name)
        inventory = projection['current']['request']['action_inventory']
        opaque_link = next(link for link in inventory['visible_source_links']['links']
                           if link['list_position'] == 3)
        self.assertNotEqual(opaque_link['status'], 'visible_unique')
        self.assertNotIn('visible_object_id', opaque_link)
        # Own engine-offered raw request IDs stay in their existing read-only
        # inventory; they must not become visible physical source identities.
        for objects in (projection['current']['objects'],
                        projection['last_valid']['objects'],
                        projection['decision_input']['visible_objects']):
            self.assertNotIn(str(REVEALED_CARD), json.dumps(objects))
        serialized = json.dumps(projection)
        for hidden in (OTHER_GRP, REVEALED_GRP,
                       'OTHER_CARD_SENTINEL', 'REVEALED_CARD_SENTINEL'):
            self.assertNotIn(str(hidden), serialized)

        reducer.apply({'payload': {'type': 'ClientMessageType_ActionsAvailableResp',
                                  'respId': 61002, 'gameStateId': BASE_VERSION + 2}})
        self.assertIsNone(reducer.document()['current']['request'])
        unchanged = gre(state_message({'type': 'GameStateType_Diff',
                                       'gameStateId': BASE_VERSION + 3,
                                       'prevGameStateId': BASE_VERSION + 2}))
        reducer.apply(unchanged)  # No repeated Created annotation is required.
        self.assertIsNone(reducer.document()['error'])
        self.assertTrue(reducer.document()['current']['valid'])
        self.assertIn(REVEALED_CARD, reducer.objects)

        tail = deletion_tail()
        self.assertNotIn('objectInstanceIds',
                         tail['greToClientEvent']['greToClientMessages'][0]
                         ['gameStateMessage']['zones'][1])
        reducer.apply(tail)
        self.assertIsNone(reducer.document()['error'])
        self.assertTrue(reducer.document()['current']['valid'])
        self.assertEqual(reducer.version, BASE_VERSION + 4)
        self.assertNotIn(REVEALED_CARD, reducer.objects)
        self.assertNotIn('objectInstanceIds', reducer.zones[REVEALED])
        self.assertEqual(reducer.document()['current']['hidden_counts'],
                         before['current']['hidden_counts'])

    def test_ordinary_card_and_wrong_zone_relations_remain_conflicts(self):
        for variant in ('ordinary_card', 'ability', 'missing_type', 'unknown_type',
                        'physical_membership_zone', 'missing_hand', 'non_hand',
                        'public_hand', 'different_membership_owner',
                        'different_hand_owner', 'different_controller', 'missing_owner',
                        'invalid_owner', 'self_owner',
                        'public_object', 'private_revealed', 'hand_membership',
                        'extra_membership', 'malformed_membership', 'physical_equal'):
            with self.subTest(variant=variant):
                reducer = reduce_prefix()
                before = reducer.document()['last_valid']
                accepted = copy.deepcopy((reducer.version, reducer.objects, reducer.zones))
                state = reveal_state()
                if variant == 'ordinary_card':
                    state['gameObjects'][0]['type'] = 'GameObjectType_Card'
                elif variant == 'ability':
                    state['gameObjects'][0]['type'] = 'GameObjectType_Ability'
                elif variant == 'missing_type':
                    del state['gameObjects'][0]['type']
                elif variant == 'unknown_type':
                    state['gameObjects'][0]['type'] = 'GameObjectType_UnknownSynthetic'
                elif variant == 'physical_membership_zone':
                    state['zones'][1]['type'] = 'ZoneType_Stack'
                elif variant == 'missing_hand':
                    state['diffDeletedZoneIds'] = [OTHER_HAND]
                    state['zones'].pop(0)
                elif variant == 'non_hand':
                    state['zones'][0]['type'] = 'ZoneType_Graveyard'
                elif variant == 'public_hand':
                    state['zones'][0]['visibility'] = 'Visibility_Public'
                elif variant == 'different_membership_owner':
                    state['zones'][1]['ownerSeatId'] = 1
                elif variant == 'different_hand_owner':
                    state['zones'][0]['ownerSeatId'] = 1
                elif variant == 'different_controller':
                    state['gameObjects'][0]['controllerSeatId'] = 1
                elif variant == 'missing_owner':
                    del state['gameObjects'][0]['ownerSeatId']
                elif variant == 'invalid_owner':
                    state['gameObjects'][0]['ownerSeatId'] = True
                elif variant == 'self_owner':
                    state['gameObjects'][0].update(zoneId=OWN_HAND, ownerSeatId=1,
                                                   controllerSeatId=1)
                    state['zones'][0] = zone(OWN_HAND, 'ZoneType_Hand', 1, [OWN_CARD])
                    state['zones'][1]['ownerSeatId'] = 1
                elif variant == 'public_object':
                    state['gameObjects'][0]['visibility'] = 'Visibility_Public'
                elif variant == 'private_revealed':
                    state['zones'][1]['visibility'] = 'Visibility_Private'
                elif variant == 'hand_membership':
                    state['zones'][0]['objectInstanceIds'].append(REVEALED_CARD)
                elif variant == 'extra_membership':
                    state['zones'].append(zone(STACK, 'ZoneType_Stack', 2,
                                               [REVEALED_CARD], 'Visibility_Public'))
                elif variant == 'malformed_membership':
                    state['zones'][1]['objectInstanceIds'] = None
                else:  # Matching a physical zone must not turn the view into a card.
                    state['gameObjects'][0]['zoneId'] = BATTLEFIELD
                    state['zones'][1] = zone(BATTLEFIELD, 'ZoneType_Battlefield', 2,
                                             [REVEALED_CARD], 'Visibility_Public')
                reducer.apply(gre(state_message(state)))
                document = reducer.document()
                expected = ('invalid_zone_membership' if variant == 'malformed_membership'
                            else 'unsupported_revealed_card' if variant == 'physical_equal'
                            else 'object_zone_conflict')
                self.assertEqual(document['error'], expected)
                self.assertEqual((reducer.version, reducer.objects, reducer.zones), accepted)
                self.assert_blocked(document)
                self.assertEqual(document['last_valid'], before)
        blocked_projection = projected(prefix() + [gre(state_message(state))])
        for name in ('decision_input', 'action_frontier', 'choice_graph'):
            self.assertIsNone(blocked_projection[name], name)

    def test_unlisted_public_self_library_view_preserves_prior_acceptance(self):
        reducer = reduce_prefix()
        before = reducer.document()['current']
        library = 82001
        obj = {'instanceId': REVEALED_CARD, 'type': 'GameObjectType_RevealedCard',
               'zoneId': library, 'grpId': REVEALED_GRP, 'ownerSeatId': 1,
               'controllerSeatId': 1, 'visibility': 'Visibility_Public',
               'syntheticIdentity': 'UNLISTED_VIEW_SENTINEL'}
        event = gre(state_message({
            'type': 'GameStateType_Diff', 'gameStateId': BASE_VERSION + 2,
            'prevGameStateId': BASE_VERSION + 1, 'gameObjects': [obj],
            'zones': [zone(library, 'ZoneType_Library', 1, [], 'Visibility_Hidden')],
        }), request(BASE_VERSION + 2, 61002, True))
        reducer.apply(event)
        self.assertIsNone(reducer.document()['error'])
        self.assertTrue(reducer.document()['current']['valid'])
        self.assertEqual(reducer.objects[REVEALED_CARD], obj)
        self.assertTrue(all(REVEALED_CARD not in row.get('objectInstanceIds', [])
                            for row in reducer.zones.values()))
        projection = projected(prefix() + [event])
        self.assertEqual(projection['current']['objects'], before['objects'])
        self.assertEqual(projection['last_valid']['objects'], before['objects'])
        self.assertEqual(projection['current']['hidden_counts'], before['hidden_counts'])
        links = projection['current']['request']['action_inventory']['visible_source_links']
        opaque_link = next(link for link in links['links'] if link['list_position'] == 3)
        self.assertEqual(opaque_link['status'], 'not_in_visible_projection')
        self.assertNotIn('visible_object_id', opaque_link)
        self.assertNotIn(str(REVEALED_GRP), json.dumps(projection))
        self.assertNotIn('UNLISTED_VIEW_SENTINEL', json.dumps(projection))

    def test_wrong_previous_id_remains_blocked_until_full(self):
        reducer = reduce_prefix()
        prior = reducer.document()['last_valid']
        broken = reveal_state()
        broken['prevGameStateId'] = 999999
        reducer.apply(gre(state_message(broken)))
        self.assertEqual(reducer.document()['error'], 'state_gap_or_missing_full')
        self.assertEqual(reducer.version, BASE_VERSION + 1)
        self.assert_blocked(reducer.document())
        reducer.apply(gre(state_message({'type': 'GameStateType_Diff',
                                        'gameStateId': BASE_VERSION + 3,
                                        'prevGameStateId': BASE_VERSION + 2}),
                          request(BASE_VERSION + 3, 61003)))
        self.assertEqual(reducer.document()['error'], 'state_gap_or_missing_full')
        self.assert_blocked(reducer.document())
        self.assertEqual(reducer.document()['last_valid'], prior)
        reducer.apply(full(version=BASE_VERSION + 4))
        self.assertIsNone(reducer.document()['error'])
        self.assertTrue(reducer.document()['current']['valid'])


if __name__ == '__main__':
    unittest.main()
