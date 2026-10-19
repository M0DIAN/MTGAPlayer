"""MP86 public real projections; bootstrap, clocks and mutations are synthetic.

No private archive, installed client, owner artifact or native input is opened.
The one positive connects a Cast source genealogy to a mixed target domain;
its actual update selects a public object, never an actual player or terminal.
"""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest

from mtgaplayer.choice_continuation import StageObserver
from mtgaplayer.decision_consumer import EXECUTION
from mtgaplayer.shadow_history import _Evaluation
from mtgaplayer.shadow_runtime import LocalShadowRuntime
from test_combat_frontier import baseline
from test_current_target_players import HEADER, bind_build
from test_current_target_request import wrap
from test_raw_log import state as raw_state


FIXTURE = Path(__file__).parent / 'fixtures/parent_player_target_lineage_real.json'


def encoded(rows):
    return ''.join(json.dumps(row, separators=(',', ':')) + '\n' for row in rows).encode()


def bootstrap(sample):
    """Invented authentication/Full transport over retained visible endpoints."""
    rows = baseline()
    gs = raw_state(rows[2]); initial = sample['parent_initial']
    gs['gameStateId'] = initial['message']['gameStateId']
    gs['gameObjects'] = copy.deepcopy(initial['objects'])
    gs['zones'] = copy.deepcopy(initial['zones'])
    gs['players'] = copy.deepcopy(initial['players'])
    return rows + [wrap(copy.deepcopy(initial['message']))]


def messages(row):
    return row.get('greToClientEvent', {}).get('greToClientMessages', [])


def states(sample):
    return [m['gameStateMessage'] for row in sample['continuation_records']
            for m in messages(row) if 'gameStateMessage' in m]


def child_message(sample):
    return next(m for row in reversed(sample['continuation_records']) for m in messages(row)
                if m['type'] == 'GREMessageType_SelectTargetsReq')


def opaque_response_index(sample):
    return next(i for i, row in enumerate(sample['continuation_records'])
                if row.get('payload', {}).get('type') == 'ClientMessageType_SelectNResp')


def opaque_request(sample):
    return next(m for row in sample['continuation_records'] for m in messages(row)
                if m['type'] == 'GREMessageType_SelectNReq')


class Clock:
    now = 1_000_000_000
    def __call__(self):
        return self.now


class ParentTargetLineageTests(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads(FIXTURE.read_text(encoding='utf8'))

    def ready(self, sample=None):
        sample = copy.deepcopy(self.fixture if sample is None else sample)
        e = _Evaluation()
        stage = StageObserver(e.reducer, include_parent_target_lineage=True)
        e.stage = stage
        def observe(event, details):
            stage.observe(event, details)
            if event == 'request_accepted': e.freeze(details)
            elif event == 'request_ended': e.end(details['request'])
        e.reducer.observer = observe
        for row in bootstrap(sample): e.apply(row)
        bind_build(e.reducer)
        return e, sample

    def freeze_parent(self, e, sample, *, options=None, policy=None):
        # Explicit marker models a completed append poll. _Evaluation's own
        # request callback is transport only and does not freeze MP86.
        options = e.consumer.current_decision_options() if options is None else options
        policy = e.consumer.shadow_decision() if policy is None else policy
        e.stage.freeze_parent_target_lineage(e.consumer, sample['parent_initial']['message'], options, policy)
        return copy.deepcopy((options, policy))

    def freeze_child(self, e, sample, *, evidence=None, options=None, policy=None):
        message = child_message(sample)
        evidence = e.consumer.current_decision_options(current_target_context=(e.reducer, message))[
            'current_target_evidence'] if evidence is None else evidence
        options = e.consumer.current_decision_options() if options is None else options
        policy = e.consumer.shadow_decision() if policy is None else policy
        e.stage.revision.freeze_player_targets(e.consumer, message, evidence, policy)
        e.stage.freeze_parent_target_lineage(e.consumer, message, options, policy, child_evidence=evidence)
        return copy.deepcopy(evidence)

    def report(self, e, *, last=False):
        return e.stage.cast.parent_target_lineage_history(include_last=last)

    def run_case(self, sample=None, *, freeze_parent=True, freeze_child=True, update=True):
        e, sample = self.ready(sample)
        if freeze_parent: self.freeze_parent(e, sample)
        e.apply(copy.deepcopy(sample['parent_response']))
        for row in sample['continuation_records']: e.apply(copy.deepcopy(row))
        if freeze_child: self.freeze_child(e, sample)
        if update: e.apply(copy.deepcopy(sample['target_update']))
        return e, sample

    def absent(self, e):
        result = self.report(e)
        self.assertEqual(result['parent_child_source_lineages'], 0)
        self.assertEqual(result['linked_player_target_requests'], 0)
        self.assertEqual(result['linked_mp85_target_updates'], 0)
        self.assertEqual(result['linked_mp85_complete_stages'], 0)

    def safe(self, value):
        for key in EXECUTION:
            if key in value: self.assertIs(value[key], False, key)
        for key in ('complete_legality_verified', 'server_acceptance_verified',
                    'rules_causation_verified', 'rules_trigger_causation_verified'):
            if key in value: self.assertIs(value[key], False, key)
        if 'current' in value: self.assertIs(value['current'], False)

    def test_real_projected_cast_links_a_mixed_domain_and_only_an_object_update(self):
        self.assertEqual(hashlib.sha256(FIXTURE.read_bytes().replace(b'\r\n', b'\n')).hexdigest(),
            '2266882033520e0df59a3da46edacfe199c03050df73f779d04af1f4c112abdb')
        self.assertEqual(self.fixture['origin'], 'retained_scrubbed_real')
        self.assertFalse(self.fixture['raw_equivalent'])
        e, sample = self.run_case()
        report = self.report(e, last=True)
        for key in ('frozen_parent_requests', 'strict_parent_responses', 'uniquely_selected_cast',
                    'verified_cast_transfers', 'verified_cast_resolutions', 'verified_ability_creations',
                    'verified_pending_to_stack_changes', 'strict_opaque_stacking_responses',
                    'parent_child_source_lineages', 'linked_player_target_requests', 'linked_mp85_target_updates'):
            self.assertEqual(report[key], 1, key)
        self.assertEqual(report['linked_mp85_complete_stages'], 0)
        fact = report['last_historical_fact']; self.safe(report); self.safe(fact)
        self.assertEqual(fact['parent_action_position'], 1)
        self.assertEqual(fact['parent_action_type'], 'ActionType_Cast')
        self.assertEqual(fact['parent_request_binding']['request_id'], 500)
        self.assertEqual(fact['child_request_binding']['request_id'], 502)
        edges = fact['source_transition_evidence']
        self.assertEqual([edge['kind'] for edge in edges], [
            'annotated_cast_hand_to_stack_card', 'source_identity_preserved',
            'annotated_resolve_and_unique_public_pending_ability_created',
            'explicit_state_location_pending_to_stack'])
        self.assertEqual([edge['state_id'] for edge in edges], [11, 12, 13, 14])
        self.assertEqual((edges[0]['original_object_ref'], edges[0]['card_object_ref']), (300, 301))
        self.assertEqual((edges[2]['card_object_ref'], edges[2]['ability_object_ref']), (301, 100))
        self.assertFalse(edges[2]['rules_trigger_causation_verified'])
        self.assertFalse(edges[3]['transfer_annotation_claimed'])
        self.assertEqual(fact['historical_target_update_status'], 'historical_target_update_verified')
        self.assertNotEqual(fact['historical_terminal_status'], 'historical_target_stage_complete')
        player = e.stage.revision.player_stage_report(include_last=True)
        self.assertEqual(player['strictly_paired_target_updates'], 1)
        self.assertEqual(player['historically_selected_player_targets'], 0)
        self.assertEqual(player['fully_linked_historical_stages'], 0)
        self.assertEqual(player['last_historical_fact']['historical_selected_role'], 'verified_public_object')
        self.assertIsNone(e.reducer.request)
        self.assertEqual(e.consumer.current_decision_options()['options'], [])
        self.assertEqual(e.consumer.shadow_decision()['status'], 'expired')

    def test_freeze_boundaries_and_default_policy_do_not_use_future_child_information(self):
        e, sample = self.ready()
        frozen = self.freeze_parent(e, sample); retained = copy.deepcopy(frozen)
        before = self.report(e, last=True)
        self.assertEqual(before['frozen_parent_requests'], 1)
        self.assertEqual(before['parent_child_source_lineages'], 0)
        self.assertEqual(frozen[1]['status'], 'abstain')
        self.assertEqual((e.consumer.current_decision_options(), e.consumer.shadow_decision()), frozen)
        e.apply(copy.deepcopy(sample['parent_response']))
        for row in sample['continuation_records']: e.apply(copy.deepcopy(row))
        self.assertEqual(self.report(e)['parent_child_source_lineages'], 0)
        options, policy = e.consumer.current_decision_options(), e.consumer.shadow_decision()
        evidence = self.freeze_child(e, sample)
        self.assertEqual(evidence['verified_player_memberships'], 2)
        self.assertEqual(evidence['returned_proposals'], 3)
        self.assertEqual(self.report(e)['parent_child_source_lineages'], 1)
        self.assertEqual(e.consumer.current_decision_options(), options)
        self.assertEqual(e.consumer.shadow_decision(), policy)
        self.assertEqual(policy['status'], 'abstain')
        self.assertEqual(frozen, retained)
        self.assertEqual(self.report(e, last=True)['last_historical_fact']['parent_frozen_policy'], frozen[1])
        self.assertEqual(self.report(e)['linked_mp85_target_updates'], 0)
        self.assertEqual(self.report(e)['linked_mp85_complete_stages'], 0)

    def test_synthetic_missing_independent_freezes_cannot_be_recovered_from_callbacks(self):
        for missing in ('parent', 'child'):
            with self.subTest(missing=missing):
                e, _ = self.run_case(freeze_parent=missing != 'parent', freeze_child=missing != 'child')
                self.absent(e)

    def test_synthetic_response_header_full_row_and_identity_ambiguities(self):
        for mode in ('response_id', 'typed_response_id', 'state', 'typed_state', 'row',
                     'two_rows', 'duplicate_offer', 'identity_alias', 'wrong_action_type', 'extra'):
            with self.subTest(mode=mode):
                s = copy.deepcopy(self.fixture); p = s['parent_response']['payload']
                actions = s['parent_initial']['message']['actionsAvailableReq']['actions']
                selected = p['performActionResp']['actions'][0]
                if mode == 'response_id': p['respId'] += 1
                elif mode == 'typed_response_id': p['respId'] = float(p['respId'])
                elif mode == 'state': p['gameStateId'] -= 1
                elif mode == 'typed_state': p['gameStateId'] = float(p['gameStateId'])
                elif mode == 'row': selected['shouldStop'] = False
                elif mode == 'two_rows': p['performActionResp']['actions'].append(copy.deepcopy(selected))
                elif mode in ('duplicate_offer', 'identity_alias'):
                    duplicate = copy.deepcopy(actions[1])
                    if mode == 'identity_alias': duplicate['shouldStop'] = False
                    actions.append(duplicate)
                elif mode == 'wrong_action_type': selected['actionType'] = 'ActionType_Activate'
                else: p['unreviewed'] = True
                e, _ = self.run_case(s); self.absent(e)

    def test_real_transport_metadata_is_not_a_gre_request_or_source_identity(self):
        e, sample = self.run_case(update=False)
        record = sample['parent_response']
        self.assertNotEqual(record['requestId'], record['payload']['respId'])
        self.assertEqual(set(record), {'payload', 'clientToMatchServiceMessageType',
            'requestId', 'timestamp', 'transactionId'})
        fact = self.report(e, last=True)['last_historical_fact']
        self.assertEqual(fact['parent_request_binding']['request_id'], record['payload']['respId'])
        serialized = json.dumps(fact)
        self.assertNotIn(record['transactionId'], serialized)
        self.assertNotIn('clientToMatchServiceMessageType', serialized)
        self.assertNotIn('transactionId', serialized)
        self.assertNotIn('timestamp', serialized)

    def test_synthetic_client_transport_metadata_must_match_the_observed_finite_wrapper(self):
        modes = ('request_bool', 'request_float', 'transaction_type', 'timestamp_type',
                 'unknown_transport', 'missing_transaction', 'mixed', 'extra')
        for endpoint in ('parent', 'opaque', 'ui'):
            for mode in modes:
                with self.subTest(endpoint=endpoint, mode=mode):
                    s = copy.deepcopy(self.fixture)
                    if endpoint == 'parent': row = s['parent_response']
                    elif endpoint == 'opaque': row = s['continuation_records'][opaque_response_index(s)]
                    else: row = next(r for r in s['continuation_records']
                        if r.get('payload', {}).get('type') == 'ClientMessageType_UIMessage')
                    if mode == 'request_bool': row['requestId'] = True
                    elif mode == 'request_float': row['requestId'] = float(row['requestId'])
                    elif mode == 'transaction_type': row['transactionId'] = 1
                    elif mode == 'timestamp_type': row['timestamp'] = False
                    elif mode == 'unknown_transport': row['clientToMatchServiceMessageType'] = 'Synthetic_UnknownTransport'
                    elif mode == 'missing_transaction': row.pop('transactionId')
                    elif mode == 'mixed': row['greToClientEvent'] = {'greToClientMessages': []}
                    else: row['synthetic_unreviewed'] = True
                    e, _ = self.run_case(s); self.absent(e)

    def test_synthetic_gre_transport_metadata_cannot_be_partly_or_mistyped(self):
        for mode in ('request_bool', 'request_float', 'transaction_type', 'timestamp_type',
                     'missing_transaction', 'missing_request', 'mixed', 'extra'):
            with self.subTest(mode=mode):
                s = copy.deepcopy(self.fixture)
                row = next(r for r in s['continuation_records'] if messages(r))
                self.assertEqual(set(row), {'greToClientEvent', 'requestId', 'timestamp', 'transactionId'})
                if mode == 'request_bool': row['requestId'] = True
                elif mode == 'request_float': row['requestId'] = float(row['requestId'])
                elif mode == 'transaction_type': row['transactionId'] = 1
                elif mode == 'timestamp_type': row['timestamp'] = False
                elif mode == 'missing_transaction': row.pop('transactionId')
                elif mode == 'missing_request': row.pop('requestId')
                elif mode == 'mixed': row['payload'] = {'type': 'ClientMessageType_UIMessage'}
                else: row['synthetic_unreviewed'] = True
                e, _ = self.run_case(s); self.absent(e)

    def test_synthetic_card_source_hand_visibility_and_unique_identity(self):
        for mode in ('wrong_group', 'ability', 'foreign_owner', 'hidden', 'wrong_zone', 'duplicate_zone'):
            with self.subTest(mode=mode):
                s = copy.deepcopy(self.fixture); initial = s['parent_initial']
                source = next(o for o in initial['objects'] if o['instanceId'] == 300)
                hand = next(z for z in initial['zones'] if z['zoneId'] == 2100)
                if mode == 'wrong_group': source['grpId'] += 1
                elif mode == 'ability': source['type'] = 'GameObjectType_Ability'
                elif mode == 'foreign_owner': source['ownerSeatId'] = source['controllerSeatId'] = 2
                elif mode == 'hidden': source['viewers'] = [2]; hand['viewers'] = [2]
                elif mode == 'wrong_zone': hand['type'] = 'ZoneType_Library'
                else: initial['zones'].append({**copy.deepcopy(hand), 'zoneId': 9999})
                e, _ = self.run_case(s); self.absent(e)

    def test_synthetic_each_real_source_edge_is_required_independently(self):
        modes = ('missing_oid', 'missing_cast_transfer', 'wrong_cast_category', 'wrong_source_zone',
                 'new_card_wrong_group', 'new_card_is_ability', 'missing_resolution_start',
                 'missing_resolution_complete', 'missing_resolve_transfer', 'wrong_resolve_destination',
                 'missing_creation', 'wrong_creation_parent', 'wrong_creation_member', 'missing_parent_ability',
                 'created_card', 'hidden_pending', 'missing_pending_member', 'missing_stack_member',
                 'changed_ability_parent', 'same_group_different_ability', 'competing_created_ability')
        for mode in modes:
            with self.subTest(mode=mode):
                s = copy.deepcopy(self.fixture); first, noop, creation, stack = states(s)
                new = next(o for o in first['gameObjects'] if o['instanceId'] == 301)
                ability = next(o for o in creation['gameObjects'] if o['instanceId'] == 100)
                if mode == 'missing_oid': first['annotations'].pop(0)
                elif mode == 'missing_cast_transfer': first['annotations'].pop(1)
                elif mode == 'wrong_cast_category': first['annotations'][1]['details'][2]['valueString'] = ['Resolve']
                elif mode == 'wrong_source_zone': first['annotations'][1]['details'][0]['valueInt32'] = [2001]
                elif mode == 'new_card_wrong_group': new['grpId'] += 1
                elif mode == 'new_card_is_ability': new['type'] = 'GameObjectType_Ability'
                elif mode == 'missing_resolution_start': creation['annotations'].pop(0)
                elif mode == 'missing_resolution_complete': creation['annotations'].pop(1)
                elif mode == 'missing_resolve_transfer': creation['annotations'].pop(2)
                elif mode == 'wrong_resolve_destination': creation['annotations'][2]['details'][1]['valueInt32'] = [2204]
                elif mode == 'missing_creation': creation['annotations'].pop(3)
                elif mode == 'wrong_creation_parent': creation['annotations'][3]['affectorId'] = 414
                elif mode == 'wrong_creation_member': creation['annotations'][3]['affectedIds'] = [413]
                elif mode == 'missing_parent_ability':
                    card = next(o for o in creation['gameObjects'] if o['instanceId'] == 301)
                    card['uniqueAbilities'] = []
                elif mode == 'created_card': ability['type'] = 'GameObjectType_Card'
                elif mode == 'hidden_pending':
                    ability['visibility'] = 'Visibility_Private'
                    next(z for z in creation['zones'] if z['zoneId'] == 2204)['visibility'] = 'Visibility_Private'
                elif mode == 'missing_pending_member':
                    next(z for z in creation['zones'] if z['zoneId'] == 2204)['objectInstanceIds'].remove(100)
                elif mode == 'missing_stack_member':
                    next(z for z in stack['zones'] if z['zoneId'] == 2000)['objectInstanceIds'] = []
                elif mode == 'changed_ability_parent': stack['gameObjects'][0]['parentId'] = 414
                elif mode == 'same_group_different_ability':
                    stack['gameObjects'][0]['instanceId'] = 413
                    next(z for z in stack['zones'] if z['zoneId'] == 2000)['objectInstanceIds'] = [413]
                    child_message(s)['selectTargetsReq']['sourceId'] = 413
                else:
                    other = {**copy.deepcopy(ability), 'instanceId': 600}
                    creation['gameObjects'].append(other)
                    next(z for z in creation['zones'] if z['zoneId'] == 2204)['objectInstanceIds'].append(600)
                    ann = copy.deepcopy(creation['annotations'][3]); ann['id'] += 100; ann['affectedIds'] = [600]
                    creation['annotations'].append(ann)
                e, _ = self.run_case(s); self.absent(e)

    def test_synthetic_typed_predecessors_and_tracked_identity_migration_fail_closed(self):
        for index in range(4):
            for mode in ('wrong', 'float', 'migration'):
                with self.subTest(edge=index, mode=mode):
                    s = copy.deepcopy(self.fixture); gs = states(s)[index]
                    if mode == 'wrong': gs['prevGameStateId'] -= 1
                    elif mode == 'float': gs['prevGameStateId'] = float(gs['prevGameStateId'])
                    else:
                        gs.setdefault('annotations', []).append({'type': ['AnnotationType_ObjectIdChanged'],
                            'affectedIds': [301], 'details': [
                                {'key': 'orig_id', 'type': 'KeyValuePairValueType_int32', 'valueInt32': [301]},
                                {'key': 'new_id', 'type': 'KeyValuePairValueType_int32', 'valueInt32': [9999]}]})
                    e, _ = self.run_case(s); self.absent(e)

    def test_synthetic_created_ability_must_be_absent_from_its_immediate_predecessor(self):
        # Invented counterexample: this source Ability already exists in the
        # otherwise empty second Diff. The later real-shaped Created annotation
        # cannot establish that it was newly created from its direct predecessor.
        sample = copy.deepcopy(self.fixture)
        first, predecessor, creation, stack = states(sample)
        ability = next(o for o in creation['gameObjects'] if o['instanceId'] == 100)
        pending = next(z for z in creation['zones'] if z['zoneId'] == 2204)
        predecessor['gameObjects'] = [copy.deepcopy(ability)]
        predecessor['zones'] = [{**copy.deepcopy(pending), 'objectInstanceIds': [100]}]
        e, _ = self.run_case(sample)
        report = self.report(e)
        self.assertEqual(report['strict_parent_responses'], 1)
        self.assertEqual(report['verified_cast_transfers'], 1)
        self.assertEqual(report['verified_ability_creations'], 0)
        self.absent(e)

    def test_synthetic_out_of_band_public_pending_source_changes_are_not_accepted_edges(self):
        for mode in ('parent', 'group', 'type', 'visibility', 'zone_visibility',
                     'duplicate_zone', 'card_abilities', 'new_competitor'):
            with self.subTest(mode=mode):
                e, sample = self.ready(); self.freeze_parent(e, sample)
                e.apply(copy.deepcopy(sample['parent_response']))
                split = opaque_response_index(sample)
                for row in sample['continuation_records'][:split]: e.apply(copy.deepcopy(row))
                ability = e.reducer.objects[100]; pending = e.reducer.zones[2204]
                if mode == 'parent': ability['parentId'] = 414
                elif mode == 'group': ability['grpId'] = float(ability['grpId'])
                elif mode == 'type': ability['type'] = 'GameObjectType_Card'
                elif mode == 'visibility': ability['visibility'] = 'Visibility_Private'
                elif mode == 'zone_visibility': pending['visibility'] = 'Visibility_Private'
                elif mode == 'duplicate_zone':
                    e.reducer.zones[9999] = {**copy.deepcopy(pending), 'zoneId': 9999}
                elif mode == 'card_abilities': e.reducer.objects[301]['uniqueAbilities'] = []
                else:
                    other = {**copy.deepcopy(ability), 'instanceId': 600}
                    e.reducer.objects[600] = other; pending['objectInstanceIds'].append(600)
                for row in sample['continuation_records'][split:]: e.apply(copy.deepcopy(row))
                self.freeze_child(e, sample); self.absent(e)

    def test_real_arbitrary_stacking_response_is_only_an_opaque_consumed_envelope(self):
        e, sample = self.run_case(update=False)
        response = sample['continuation_records'][opaque_response_index(sample)]['payload']['selectNResp']
        offered = opaque_request(sample)['selectNReq']['ids']
        self.assertEqual(response['ids'], [0]); self.assertNotIn(0, offered)
        report = self.report(e, last=True)
        self.assertEqual(report['strict_opaque_stacking_responses'], 1)
        fact = report['last_historical_fact']
        serialized = json.dumps(fact)
        self.assertNotIn('9000', serialized)
        self.assertNotIn('9001', serialized)
        self.assertNotIn('9002', serialized)
        opaque = fact['intermediate_request']
        self.assertEqual(opaque['offered_ref_count'], 3)
        self.assertTrue(opaque['strict_consumption_verified'])
        for key in ('member_identity_verified', 'member_selection_legality_verified',
                    'ordering_semantics_verified', 'ability_identity_inferred_from_response'):
            self.assertIs(opaque[key], False, key)
        self.assertFalse(fact['complete_legality_verified'])
        self.assertFalse(fact['server_acceptance_verified'])

    def test_synthetic_opaque_response_or_unreviewed_intermediate_request_breaks_lineage(self):
        for mode in ('response_id', 'typed_state', 'extra', 'arbitrary', 'literal_object', 'unknown_request'):
            with self.subTest(mode=mode):
                s = copy.deepcopy(self.fixture); p = s['continuation_records'][opaque_response_index(s)]['payload']
                if mode == 'response_id': p['respId'] += 1
                elif mode == 'typed_state': p['gameStateId'] = float(p['gameStateId'])
                elif mode == 'extra': p['selectNResp']['unreviewed'] = True
                elif mode == 'arbitrary': p['selectNResp']['useArbitrary'] = 'OrderingType_OrderAsIndicated'
                elif mode == 'literal_object': p['selectNResp']['ids'] = [100]
                else:
                    opaque_request(s)['type'] = 'GREMessageType_SearchReq'
                e, _ = self.run_case(s); self.absent(e)

    def test_synthetic_wrong_child_source_group_slot_or_seat_cannot_borrow_parent(self):
        for mode in ('card_source', 'other_ability', 'group', 'target_group', 'slot', 'target_player', 'recipient', 'typed_source'):
            with self.subTest(mode=mode):
                s = copy.deepcopy(self.fixture); m = child_message(s); body = m['selectTargetsReq']; slot = body['targets'][0]
                if mode == 'card_source': body['sourceId'] = 301
                elif mode == 'other_ability': body['sourceId'] = 413
                elif mode == 'group': body['abilityGrpId'] += 1
                elif mode == 'target_group': slot['targetingAbilityGrpId'] += 1
                elif mode == 'slot': slot['targetIdx'] += 1
                elif mode == 'target_player': slot['targetingPlayer'] = 2
                elif mode == 'recipient': m['systemSeatIds'] = [2]
                else: body['sourceId'] = float(body['sourceId'])
                e, _ = self.run_case(s); self.absent(e)

    def test_synthetic_sidecar_ref_version_scope_or_digest_changes_cannot_link(self):
        for mode in ('ref', 'request', 'version', 'match', 'game', 'seat', 'digest'):
            with self.subTest(mode=mode):
                e, sample = self.ready(); self.freeze_parent(e, sample)
                e.apply(copy.deepcopy(sample['parent_response']))
                for row in sample['continuation_records']: e.apply(copy.deepcopy(row))
                evidence = e.consumer.current_decision_options(current_target_context=(e.reducer, child_message(sample)))[
                    'current_target_evidence']
                if mode == 'ref': evidence['source_snapshot_ref']['sequence'] += 1
                elif mode == 'request': evidence['current_request_binding']['request_id'] += 1
                elif mode == 'version': e.reducer._target_build_context = None
                elif mode == 'match': e.reducer.match = 'synthetic-other-match'
                elif mode == 'game': e.reducer.game += 1
                elif mode == 'seat': e.reducer.seat = 2
                else: e.reducer.accepted_digest += b'synthetic-changed-digest'
                self.freeze_child(e, sample, evidence=evidence)
                self.absent(e)

    def test_synthetic_cancel_undo_reset_duplicate_diff_and_retransmission_break_pending(self):
        for mode in ('cancel', 'undo', 'reset', 'full', 'duplicate_response', 'duplicate_diff', 'parent_retransmit', 'competing_request'):
            with self.subTest(mode=mode):
                e, sample = self.ready(); self.freeze_parent(e, sample)
                e.apply(copy.deepcopy(sample['parent_response']))
                if mode in ('cancel', 'undo'):
                    e.apply({'payload': {'type': 'ClientMessageType_CancelActionReq' if mode == 'cancel' else 'ClientMessageType_UndoReq'}})
                elif mode == 'reset': e.reducer.reset(2); e.stage.reset()
                elif mode == 'full': e.apply(copy.deepcopy(bootstrap(sample)[2]))
                elif mode == 'duplicate_response': e.apply(copy.deepcopy(sample['parent_response']))
                elif mode == 'parent_retransmit': e.apply(wrap(copy.deepcopy(sample['parent_initial']['message'])))
                elif mode == 'competing_request':
                    m = copy.deepcopy(sample['parent_initial']['message']); m['msgId'] += 10; e.apply(wrap(m))
                duplicate_done = False
                for row in sample['continuation_records']:
                    e.apply(copy.deepcopy(row))
                    if mode == 'duplicate_diff' and not duplicate_done and messages(row):
                        e.apply(wrap(copy.deepcopy(messages(row)[-1])))
                        duplicate_done = True
                self.freeze_child(e, sample); self.absent(e)

    def test_historical_fact_is_detached_and_does_not_resurrect_consumed_parent(self):
        e, sample = self.run_case()
        report = self.report(e, last=True)
        report['parent_child_source_lineages'] = 999
        report['last_historical_fact']['input_sent'] = True
        current = self.report(e, last=True)
        self.assertEqual(current['parent_child_source_lineages'], 1)
        self.safe(current['last_historical_fact'])
        e.apply(copy.deepcopy(sample['target_update']))
        e.apply(wrap(copy.deepcopy(sample['parent_initial']['message'])))
        self.freeze_parent(e, sample)
        self.assertEqual(self.report(e)['parent_child_source_lineages'], 1)
        self.assertEqual(self.report(e)['linked_mp85_target_updates'], 1)
        self.assertEqual(e.consumer.current_decision_options()['options'], [])
        self.assertEqual(e.consumer.shadow_decision()['status'], 'expired')


class ParentTargetRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads(FIXTURE.read_text(encoding='utf8'))
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'synthetic-wrapper-real-parent-genealogy.jsonl'
        self.clock = Clock()

    def start(self, *, enabled=True):
        rows = bootstrap(self.fixture)
        self.path.write_bytes(HEADER + encoded(rows[:-1]))
        self.runtime = LocalShadowRuntime(self.path, interval=0, samples=None, clock_ns=self.clock,
            observation_mode='controlled_stream_replay', parent_target_lineage=enabled)
        self.gen = self.runtime.frames()
        self.addCleanup(self.gen.close); self.addCleanup(self.runtime.close)
        history = next(self.gen)
        self.assertNotEqual(history['time_scope'], 'current_at_completed_poll')
        return self.append([rows[-1]])

    def append(self, rows):
        with self.path.open('ab') as stream: stream.write(encoded(rows))
        return next(self.gen)

    def report(self, *, last=False):
        return self.runtime.parent_target_lineage_history(include_last=last)

    def test_actual_completed_poll_grouping_links_once_and_preserves_mp85_scope(self):
        parent = self.start()
        self.assertEqual(parent['time_scope'], 'current_at_completed_poll')
        self.assertEqual(self.report()['frozen_parent_requests'], 1)
        self.runtime.current_frame()
        self.assertEqual(self.report()['frozen_parent_requests'], 1)
        stacking = self.append(self.fixture['poll_batches'][0])
        self.assertEqual(stacking['request_type'], 'GREMessageType_SelectNReq')
        self.assertEqual(self.report()['parent_child_source_lineages'], 0)
        child = self.append(self.fixture['poll_batches'][1])
        self.assertEqual(child['time_scope'], 'current_at_completed_poll')
        self.assertEqual(self.report()['parent_child_source_lineages'], 1)
        self.assertEqual(child['shadow_decision']['status'], 'abstain')
        self.runtime.current_frame()
        self.assertEqual(self.report()['parent_child_source_lineages'], 1)
        self.append([self.fixture['target_update']])
        self.assertEqual(self.report()['linked_mp85_target_updates'], 1)
        self.assertEqual(self.report()['linked_mp85_complete_stages'], 0)
        player = self.runtime.player_target_stage_history()
        self.assertEqual(player['strictly_paired_target_updates'], 1)
        self.assertEqual(player['historically_selected_player_targets'], 0)
        self.assertEqual(player['fully_linked_historical_stages'], 0)
        self.runtime.close()
        self.assertNotEqual(self.runtime.current_frame()['time_scope'], 'current_at_completed_poll')

    def test_synthetic_partial_or_expired_pending_cannot_travel_to_fresh_child(self):
        for mode in ('partial', 'lease'):
            with self.subTest(mode=mode):
                self.start(); self.append(self.fixture['poll_batches'][0])
                if mode == 'partial':
                    with self.path.open('ab') as stream: stream.write(b'{"synthetic_partial":')
                    self.assertNotEqual(next(self.gen)['time_scope'], 'current_at_completed_poll')
                    with self.path.open('ab') as stream: stream.write(b'true}\n')
                    next(self.gen)
                else: self.clock.now += 6_000_000_000
                self.append(self.fixture['poll_batches'][1])
                self.assertEqual(self.report()['parent_child_source_lineages'], 0)
                self.runtime.close(); self.gen.close()

    def test_expired_parent_subscription_cannot_accept_a_late_real_response(self):
        self.start(); self.clock.now += 6_000_000_000
        self.assertNotEqual(self.runtime.current_frame()['time_scope'], 'current_at_completed_poll')
        self.append(self.fixture['poll_batches'][0]); self.append(self.fixture['poll_batches'][1])
        self.assertEqual(self.report()['strict_parent_responses'], 0)
        self.assertEqual(self.report()['parent_child_source_lineages'], 0)

    def test_default_runtime_has_no_lineage_or_player_stage_outputs(self):
        frame = self.start(enabled=False)
        self.assertIsNone(self.runtime.parent_target_lineage_history())
        self.assertIsNone(self.runtime.player_target_stage_history())
        self.assertNotIn('historical_parent_target_lineage', frame)
        self.assertNotIn('historical_player_target_stages', frame)
        self.assertEqual(frame['shadow_decision']['status'], 'abstain')

    def test_foreign_thread_cannot_mutate_or_read_owner_lineage_context(self):
        self.start(); results, errors = [], []
        def foreign():
            try: results.append(self.runtime.parent_target_lineage_history())
            except BaseException as error: errors.append(error)
        worker = threading.Thread(target=foreign); worker.start(); worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(results, [])
        self.assertEqual(len(errors), 1)
        self.assertEqual(str(errors[0]), 'owner_thread_required')


if __name__ == '__main__':
    unittest.main()
