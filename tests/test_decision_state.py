"""DecisionState v1 over committed scrubbed GRE fixtures.

Injected action/combat bodies and catalog metadata below are explicitly
synthetic test data; they are not additional observed protocol evidence.
Only the Python standard library is required.
"""
import copy
import itertools
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from mtgaplayer.cli import replay, watch
from mtgaplayer.combat_frontier import ATTACK, BLOCK
from mtgaplayer.decision_state import build_decision_state
from mtgaplayer.raw_log import RawFollower, RawReducer
from test_action_frontier import frames, save
from test_choice_graph import history, valid_later_state_and_request
from test_combat_frontier import baseline, body, request, response
from test_decision_input import rows as selectn_rows
from test_raw_log import entries, state
from test_response_evidence import action_request, reply


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / 'schemas/decision-state.v1.schema.json'
VERSION = 'mtgaplayer.decision-state.v1'
SAFETY_FLAGS = ('legal_choice_verified', 'complete_legality_verified',
                'response_encoding_verified', 'server_acceptance_verified',
                'execution_ready', 'input_sent')


def own_request(row):
    return next(message for message in row['greToClientEvent']['greToClientMessages']
                if message.get('type', '').endswith('Req'))


def action_message(row):
    return next(message for message in row['greToClientEvent']['greToClientMessages']
                if message.get('type') == 'GREMessageType_ActionsAvailableReq')


def current_action(row):
    """Drop fixture state messages, retaining only the synthetic own request."""
    return {'greToClientEvent': {'greToClientMessages': [
        copy.deepcopy(action_message(row))]}}


def walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


class DecisionStateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / 'sanitized-test.jsonl'

    def replay_rows(self, rows, **options):
        save(self.path, rows)
        return replay(self.path, format='player-log', **options)

    def observed(self, rows, **options):
        return self.replay_rows(rows, decision_state=True, **options)['decision_state']

    def action_document(self):
        document = self.replay_rows(history()[:-1], decision_input=True,
                                    action_frontier=True, choice_graph=True)
        # Internal staging metadata from the known uninterrupted fixture chain;
        # the legacy public JSON deliberately omits this reducer fact.
        document['current']['request']['_continuity_verified'] = True
        return document

    def assert_safe(self, result):
        self.assertIsNotNone(result)
        self.assertEqual(result['schema_version'], VERSION)
        self.assertIs(result['read_only'], True)
        self.assertIsNone(result['effect_claims'])
        self.assertEqual(result['legal_action_space']['expanded_plans'],
                         {'completeness': 'unknown', 'plans': None})
        self.assertIsNone(result['game']['mana'])
        self.assertIsNone(result['game']['rules'])
        self.assertIsNone(result['game']['effective_combat_stats'])
        for row in result['visible_objects']:
            self.assertIsNone(row['effective_power'])
            self.assertIsNone(row['effective_toughness'])
        for node in walk(result):
            for name in SAFETY_FLAGS + ('actionable', 'usable_now', 'executor_connected'):
                if name in node:
                    self.assertIs(node[name], False, name)
            if 'read_only' in node:
                self.assertIs(node['read_only'], True)
            for name, value in node.items():
                if 'completeness' in name:
                    self.assertNotEqual(value, 'complete_verified')
        self.assertEqual(result['unresolved'], sorted(set(result['unresolved'])))

    def assert_no_request(self, result):
        self.assert_safe(result)
        self.assertEqual(result['status'], 'state_observed_without_request')
        self.assertIsNone(result['binding']['request_id'])
        self.assertIsNone(result['binding']['request_type'])
        space = result['legal_action_space']
        self.assertIsNone(space['request_type'])
        self.assertIsNone(space['choice_graph'])
        self.assertEqual(space['immediate_frontier'], {
            'kind': None, 'availability': 'not_provided',
            'completeness': 'unknown', 'projection': None})

    def test_full_and_diff_keep_visible_state_without_current_request(self):
        for length, state_id in ((3, 1), (4, 2)):
            with self.subTest(state_id=state_id):
                document = self.replay_rows(entries()[:length], decision_state=True)
                result = document['decision_state']
                self.assert_no_request(result)
                self.assertEqual(result['binding']['game_state_id'], state_id)
                self.assertEqual(result['binding']['source_generation'],
                                 document['source']['generation'])
                self.assertEqual([obj['instance_id'] for obj in result['visible_objects']],
                                 [obj['id'] for obj in document['current']['objects']])
                self.assertEqual(result['game']['hidden_counts'],
                                 document['current']['hidden_counts'])
                self.assertEqual(result['game']['players'], document['current']['players'])

    def test_full_and_diff_can_bind_synthetic_actions_with_choice_graph(self):
        full_request = current_action(action_request([{'actionType': 'ActionType_Pass'}]))
        action_message(full_request)['gameStateId'] = 1
        for rows in (entries()[:3] + [full_request], history()[:-1]):
            with self.subTest(state=action_message(rows[-1])['gameStateId']):
                document = self.replay_rows(rows, decision_state=True)
                explicit = self.replay_rows(rows, decision_input=True,
                                            action_frontier=True, choice_graph=True)
                result = document['decision_state']
                self.assert_safe(result)
                self.assertEqual(result['status'], 'state_and_request_observed')
                frontier = result['legal_action_space']['immediate_frontier']
                self.assertEqual((frontier['kind'], frontier['availability'],
                                  frontier['completeness']),
                                 ('actions_available', 'observed', 'partial'))
                self.assertEqual(frontier['projection'], explicit['action_frontier'])
                self.assertEqual(result['legal_action_space']['choice_graph'],
                                 explicit['choice_graph'])
                for key in ('decision_input', 'action_frontier', 'choice_graph'):
                    self.assertNotIn(key, document)
                self.assertNotIn('_frontier_rows', json.dumps(document))
                self.assertNotIn('_frontier_request_identity', json.dumps(document))

    def test_select_n_preserves_raw_maximum_and_unknown_minimum(self):
        result = self.observed(selectn_rows())
        self.assert_safe(result)
        self.assertEqual(result['binding']['request_type'], 'GREMessageType_SelectNReq')
        frontier = result['legal_action_space']['immediate_frontier']
        self.assertEqual((frontier['kind'], frontier['availability'], frontier['completeness']),
                         ('select_n', 'observed', 'partial'))
        self.assertEqual(frontier['projection'], {
            'offered_instance_ids': [175, 176, 178, 179], 'max_sel_raw': 2,
            'min_sel_verified': None, 'combinations_complete': False,
            'source_ids_not_visibility_joined': True})
        self.assertIsNone(result['legal_action_space']['choice_graph'])
        self.assertIn('select_n_minimum_unknown', result['unresolved'])

    def test_synthetic_attack_and_block_are_only_current_combat_projection(self):
        for typ, kind in ((ATTACK, 'declare_attackers'), (BLOCK, 'declare_blockers')):
            with self.subTest(typ=typ):
                rows = baseline() + [request(typ)]
                document = self.replay_rows(rows, decision_state=True,
                                            decision_input=True, combat_frontier=True)
                result = document['decision_state']
                self.assert_safe(result)
                frontier = result['legal_action_space']['immediate_frontier']
                self.assertEqual(frontier['kind'], kind)
                self.assertEqual(frontier['availability'], 'observed')
                self.assertEqual(frontier['projection'], document['combat_frontier'])
                self.assertEqual(frontier['projection']['combat_request_type'], typ)
                self.assertIsNone(result['legal_action_space']['choice_graph'])
                self.assertEqual(frontier['projection']['engine_offered_candidates'][0]
                                 ['candidate_instance_id'], 701)

    def test_missing_empty_and_unsupported_domains_are_distinct(self):
        for mode, expected in (('missing', 'unknown'), ('empty', 'confirmed_empty'),
                               ('unsupported', 'unsupported')):
            with self.subTest(kind='actions', mode=mode):
                rows = frames()
                message = action_message(rows[-1])
                if mode == 'missing':
                    message.pop('actionsAvailableReq')
                elif mode == 'empty':
                    message['actionsAvailableReq'] = {'actions': []}
                else:
                    message['type'] = 'GREMessageType_SyntheticFutureReq'
                result = self.observed(rows)
                self.assert_safe(result)
                frontier = result['legal_action_space']['immediate_frontier']
                self.assertEqual(frontier['availability'], expected)
                self.assertEqual(frontier['completeness'],
                                 'partial' if mode == 'empty' else 'unknown')
                if mode == 'empty':
                    self.assertEqual(frontier['projection']['templates'], [])
                elif mode == 'missing':
                    self.assertIsNone(frontier['projection']['templates'])
                else:
                    self.assertIsNone(frontier['projection'])
        for mode in ('missing', 'empty'):
            with self.subTest(kind='combat', mode=mode):
                row = request(references=())
                if mode == 'missing':
                    body(row).clear()
                frontier = self.observed(baseline() + [row])['legal_action_space']['immediate_frontier']
                self.assertEqual(frontier['availability'],
                                 'confirmed_empty' if mode == 'empty' else 'unknown')
                self.assertEqual(frontier['projection']['engine_offered_candidates'],
                                 [] if mode == 'empty' else None)
        # Oversized offered data can withhold DecisionInput without invalidating
        # the verified board or manufacturing an empty legal-action domain.
        oversized = frames()
        action_message(oversized[-1])['actionsAvailableReq'] = {
            'actions': [{'actionType': 'ActionType_Pass'}] * 257}
        observed = self.observed(oversized)
        self.assert_safe(observed)
        self.assertEqual(observed['status'], 'state_and_request_observed')
        self.assertEqual(observed['legal_action_space']['immediate_frontier']['availability'], 'unknown')
        self.assertIsNone(observed['legal_action_space']['immediate_frontier']['projection']['templates'])
        # Explicit synthetic projected overflow: unavailable DecisionInput must
        # not discard valid visible state or import the stale supplied frontier.
        projected = self.action_document()
        projected['current']['request']['action_inventory']['offered_count'] = 257
        projected['decision_input'] = None
        observed = build_decision_state(projected)
        self.assert_safe(observed)
        self.assertIsNone(observed['legal_action_space']['immediate_frontier']['projection'])
        self.assertIn('decision_input_projection_unavailable', observed['unresolved'])

    def test_current_binding_rejects_each_mismatch_and_stale_decision_input(self):
        document = self.action_document()
        self.assert_safe(build_decision_state(document))
        replacements = (
            ('generation', lambda d: d['source'].update(generation=2)),
            ('match', lambda d: d['current'].update(match='SYNTHETIC_OTHER_MATCH')),
            ('game', lambda d: d['current'].update(game=2)),
            ('self_seat', lambda d: d['current'].update(self_seat=2)),
            ('game_state_id', lambda d: d['current'].update(game_state_id=999)),
            ('request_id', lambda d: d['current']['request'].update(id=999)),
            ('request_type', lambda d: d['current']['request'].update(type=ATTACK)),
            ('request_state', lambda d: d['current']['request'].update(game_state_id=999)),
            ('ownership', lambda d: d['current']['request']['binding'].update(ownership_verified=False)),
            ('not_current', lambda d: d['current']['request'].update(current=False)),
        )
        for name, replace in replacements:
            with self.subTest(field=name):
                changed = copy.deepcopy(document)
                replace(changed)
                self.assertIsNone(build_decision_state(changed))
        for mutate in (
                lambda d: d['current'].update(valid=False),
                lambda d: d['source'].update(partial_record=True),
                lambda d: d.update(error='SYNTHETIC_GAP'),
                lambda d: d['source'].update(format='normalized-ndjson-v1'),
                lambda d: d['source'].update(mode='other'),
                lambda d: d['source'].update(input_sent=True),
                lambda d: d['source'].update(executor_connected=True),
                lambda d: d['current'].update(actionable=True),
                lambda d: d['current'].update(legal_actions=[])):
            changed = copy.deepcopy(document)
            mutate(changed)
            self.assertTrue(changed['last_valid']['valid'])
            self.assertIsNone(build_decision_state(changed))
        for malformed in (None, [], {}, {'current': None, 'source': {}},
                          {'last_valid': document['last_valid']}):
            self.assertIsNone(build_decision_state(malformed))

    def test_child_and_nested_identity_mismatches_cannot_import_candidates(self):
        document = self.action_document()
        identity = document['action_frontier']['request_identity']
        for field, value in identity.items():
            with self.subTest(field=field):
                changed = copy.deepcopy(document)
                changed['action_frontier']['request_identity'][field] = (
                    value + 1 if type(value) is int else value + '-other')
                result = build_decision_state(changed)
                frontier = result['legal_action_space']['immediate_frontier']
                self.assertIsNone(frontier['projection'])
                self.assertIsNone(result['legal_action_space']['choice_graph'])
                self.assertEqual(frontier['availability'], 'unknown')
        changed = copy.deepcopy(document)
        changed['action_frontier']['templates'][0]['action_key']['request_identity']['request_id'] = 999
        self.assertIsNone(build_decision_state(changed)['legal_action_space']
                          ['immediate_frontier']['projection'])
        for location in ('request_identity', 'nested_action_key'):
            with self.subTest(graph=location):
                changed = copy.deepcopy(document)
                # Shared identities in legacy projections are permitted; isolate
                # the child mutation so this test changes only the graph.
                changed['choice_graph'] = copy.deepcopy(document['choice_graph'])
                target = changed['choice_graph']['request_identity'] if location == 'request_identity' else (
                    changed['choice_graph']['action_nodes'][0]['action_key']['request_identity'])
                target['request_id'] = 999
                result = build_decision_state(changed)
                self.assertIsNotNone(result['legal_action_space']['immediate_frontier']['projection'])
                self.assertIsNone(result['legal_action_space']['choice_graph'])
                self.assertIn('choice_graph_unavailable_or_mismatched', result['unresolved'])
        with self.subTest(graph='missing'):
            changed = copy.deepcopy(document)
            changed.pop('choice_graph')
            result = build_decision_state(changed)
            self.assertIsNone(result['legal_action_space']['choice_graph'])
            self.assertIn('choice_graph_unavailable_or_mismatched', result['unresolved'])
        combat = self.replay_rows(baseline() + [request()], decision_input=True, combat_frontier=True)
        combat['current']['request']['_continuity_verified'] = True
        for location in ('combat_request_type', 'request_type'):
            with self.subTest(combat=location):
                changed = copy.deepcopy(combat)
                target = changed['combat_frontier'] if location == 'combat_request_type' else (
                    changed['combat_frontier']['request_identity'])
                target[location] = BLOCK
                self.assertIsNone(build_decision_state(changed)['legal_action_space']
                                  ['immediate_frontier']['projection'])
        with self.subTest(combat='nested_request_type'):
            changed = copy.deepcopy(combat)
            candidate = changed['combat_frontier']['engine_offered_candidates'][0]['candidate_key']
            candidate['request_identity'] = copy.deepcopy(candidate['request_identity'])
            candidate['request_identity']['request_type'] = BLOCK
            result = build_decision_state(changed)
            self.assertIsNone(result['legal_action_space']['immediate_frontier']['projection'])

    def test_child_authority_flags_and_completeness_cannot_be_elevated(self):
        document = self.action_document()
        mutations = [('action_frontier', name, True) for name in SAFETY_FLAGS]
        mutations += [('action_frontier', 'read_only', False),
                      ('action_frontier', 'immediate_completeness', 'complete_verified'),
                      ('choice_graph', 'execution_ready', True)]
        for child, name, value in mutations:
            with self.subTest(child=child, name=name):
                changed = copy.deepcopy(document)
                changed[child][name] = value
                result = build_decision_state(changed)
                self.assert_safe(result)
                space = result['legal_action_space']
                self.assertIsNone(space['choice_graph'] if child == 'choice_graph' else
                                  space['immediate_frontier']['projection'])

    def test_consumed_replaced_and_advanced_actions_never_restore_old_request(self):
        initial = history()[:-1]
        old = current_action(initial[-1])
        newer = copy.deepcopy(old)
        action_message(newer)['msgId'] = 38
        advance = valid_later_state_and_request()[0]
        cases = (('consumed', [reply()], None),
                 ('replaced', [newer], 38),
                 ('advanced', [advance], None))
        for mode, ending, expected_id in cases:
            with self.subTest(mode=mode):
                result = self.observed(initial + ending + [old])
                self.assert_safe(result)
                self.assertEqual(result['binding']['request_id'], expected_id)
                if expected_id is None:
                    self.assert_no_request(result)
                else:
                    self.assertEqual(result['legal_action_space']['immediate_frontier']
                                     ['projection']['request_identity']['request_id'], expected_id)

    def test_consumed_or_replaced_combat_cannot_restore_old_candidates(self):
        for mode, ending, expected in (('consumed', response(), None),
                                       ('replaced', request(BLOCK, 991), 991)):
            with self.subTest(mode=mode):
                result = self.observed(baseline() + [request(), ending, request()])
                self.assert_safe(result)
                self.assertEqual(result['binding']['request_id'], expected)
                if expected is None:
                    self.assert_no_request(result)
                else:
                    self.assertEqual(result['legal_action_space']['immediate_frontier']['kind'],
                                     'declare_blockers')

    def test_partial_tail_gap_recovery_and_generation_reset_discard_candidates(self):
        initial = baseline() + [request()]
        save(self.path, initial)
        follower = watch(self.path, interval=0, samples=5, decision_state=True)
        first = next(follower)
        self.assert_safe(first['decision_state'])
        encoded = (json.dumps(response()) + '\n').encode('utf-8')
        with self.path.open('ab') as stream:
            stream.write(encoded[:19])
        partial = next(follower)
        self.assertTrue(partial['source']['partial_record'])
        self.assertIsNone(partial['decision_state'])
        self.assertTrue(partial['last_valid']['valid'])
        with self.path.open('ab') as stream:
            stream.write(encoded[19:])
        self.assert_no_request(next(follower)['decision_state'])
        gap = copy.deepcopy(entries()[3])
        state(gap)['prevGameStateId'] = 999
        with self.path.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(gap) + '\n')
        discontinuous = next(follower)
        self.assertEqual(discontinuous['error'], 'state_gap_or_missing_full')
        self.assertIsNone(discontinuous['decision_state'])
        save(self.path, baseline())  # Short replacement starts a new generation.
        reset = next(follower)
        self.assertGreater(reset['source']['generation'], first['source']['generation'])
        self.assert_no_request(reset['decision_state'])
        self.assertEqual(reset['decision_state']['binding']['source_generation'],
                         reset['source']['generation'])
        # A Full recovery in the same generation must not revive a retired request.
        recovered = self.observed(initial + [gap, baseline()[2], request()])
        self.assert_safe(recovered)
        self.assertIsNone(recovered['legal_action_space']['immediate_frontier']['projection'])
        self.assertEqual(recovered['legal_action_space']['immediate_frontier']['completeness'], 'unknown')
        # The same lifecycle gate applies to ActionsAvailable, even without the
        # new CLI flag. An identical Full can repair state, never an expired request.
        message = copy.deepcopy(action_message(frames()[-1]))
        message['gameStateId'] = 1
        message['actionsAvailableReq'] = {'actions': [{'actionType': 'ActionType_Pass'}]}
        own_action = {'greToClientEvent': {'greToClientMessages': [message]}}
        original = baseline() + [own_action]
        self.assertEqual(self.observed(original)['legal_action_space']['immediate_frontier']
                         ['availability'], 'observed')
        restored_rows = original + [gap, baseline()[2], own_action]
        self.assert_no_request(self.observed(restored_rows))
        legacy = self.replay_rows(restored_rows, decision_input=True, action_frontier=True)
        self.assertEqual(legacy['current']['request']['id'], message['msgId'])
        self.assertIsNotNone(legacy['action_frontier'])  # Existing read-only diagnostic contract.
        self.assertNotIn('_continuity_verified', json.dumps(legacy))
        self.assert_no_request(build_decision_state(legacy))
        combined = self.replay_rows(restored_rows, decision_state=True,
                                   decision_input=True, action_frontier=True)
        self.assert_no_request(combined.pop('decision_state'))
        self.assertEqual(combined, legacy)
        fresh = copy.deepcopy(own_action)
        action_message(fresh)['msgId'] += 1
        self.assertEqual(self.observed(restored_rows + [fresh])['legal_action_space']
                         ['immediate_frontier']['availability'], 'observed')

    def test_hidden_card_identity_and_unknown_private_values_are_not_exposed(self):
        rows = frames()
        reducer = RawReducer()
        reducer.reset(1)
        for row in rows[:9]:
            reducer.apply(row)
        hidden = next(zone['objectInstanceIds'][0] for zone in reducer.zones.values()
                      if zone.get('type') == 'ZoneType_Hand' and zone.get('ownerSeatId') == 2)
        for row in rows:
            for message in row.get('greToClientEvent', {}).get('greToClientMessages', []):
                for obj in message.get('gameStateMessage', {}).get('gameObjects', []):
                    if obj.get('instanceId') == hidden:
                        obj['grpId'] = 88005544
        result = self.observed(rows)
        self.assert_safe(result)
        self.assertNotIn(hidden, [obj['instance_id'] for obj in result['visible_objects']])
        text = json.dumps(result)
        for secret in ('88005544', 'PRIVATE_COST_SENTINEL', 'PRIVATE_TARGET_SENTINEL',
                       'UNEXPECTED_PRIVATE_VALUE', 'PRIVATE_UNKNOWN', 'ActionType_FutureVariant',
                       '_frontier_rows', '_frontier_request_identity'):
            self.assertNotIn(secret, text)
        result = self.observed(baseline() + [request(references=(704,))])
        candidate = result['legal_action_space']['immediate_frontier']['projection']
        self.assertIsNone(candidate['engine_offered_candidates'][0]['candidate_instance_id'])
        for secret in ('PRIVATE_FIELD', 'PRIVATE_VALUE', 'PRIVATE_RECIPIENT', '99117733'):
            self.assertNotIn(secret, json.dumps(result))

    def test_synthetic_catalog_stats_do_not_become_effective_stats_or_effects(self):
        document = self.replay_rows(baseline())
        # Deliberately synthetic metadata, injected after the visible projection.
        document['current']['objects'][0]['local_card'] = {
            'status': 'resolved', 'name': 'Synthetic catalog example',
            'set_code': 'TST', 'collector_number': '001',
            'catalog_stats': {'power': 3, 'toughness': 4},
            'effects': 'PRIVATE_CATALOG_EFFECT', 'private': 'PRIVATE_CATALOG_VALUE'}
        result = build_decision_state(document)
        self.assert_safe(result)
        knowledge = result['card_knowledge']
        self.assertEqual(knowledge['source'], 'local_catalog_static_only')
        self.assertEqual(knowledge['objects'][0]['knowledge']['static_catalog_stats'], {
            'power': 3, 'toughness': 4, 'source': 'Cards.Power/Toughness',
            'effective_in_game': False, 'rules_verified': False})
        self.assertNotIn('PRIVATE_CATALOG', json.dumps(result))

    def test_assembly_is_pure_and_deeply_isolated_in_both_directions(self):
        document = self.action_document()
        original = copy.deepcopy(document)
        result = build_decision_state(document)
        pristine = copy.deepcopy(result)
        self.assertEqual(document, original)
        document['current']['objects'][0]['zone'] = 'SYNTHETIC_MUTATED_ZONE'
        document['current']['hidden_counts']['SYNTHETIC'] = 99
        document['action_frontier']['templates'][0]['request_identity']['request_id'] = 99
        document['choice_graph']['action_nodes'][0]['constraints'].clear()
        self.assertEqual(result, pristine)
        result['game']['hidden_counts']['OUTWARD_ONLY'] = 77
        result['visible_objects'][0]['zone'] = 'OUTWARD_ONLY'
        result['legal_action_space']['immediate_frontier']['projection']['templates'].clear()
        result['legal_action_space']['choice_graph']['action_nodes'].clear()
        self.assertEqual(build_decision_state(original), pristine)
        self.assertNotIn('OUTWARD_ONLY', json.dumps(original))

    def test_new_flag_preserves_all_existing_explicit_projection_combinations(self):
        names = ('decision_input', 'action_gaps', 'action_frontier', 'choice_graph', 'combat_frontier')
        valid = []
        for values in itertools.product((False, True), repeat=len(names)):
            options = dict(zip(names, values))
            if ((options['action_gaps'] or options['action_frontier'] or options['combat_frontier'])
                    and not options['decision_input']) or (options['choice_graph'] and not options['action_frontier']):
                continue
            valid.append(options)
        self.assertEqual(len(valid), 13)
        for rows in (frames(), baseline() + [request(BLOCK)]):
            save(self.path, rows)
            for options in valid:
                with self.subTest(request=own_request(rows[-1])['type'], options=options):
                    for dry in (False, True):
                        plain = replay(self.path, dry=dry, format='player-log', **options)
                        observed = replay(self.path, dry=dry, format='player-log',
                                          decision_state=True, **options)
                        self.assertNotIn('decision_state', plain)
                        self.assert_safe(observed.pop('decision_state'))
                        self.assertEqual(observed, plain)
                    plain = list(watch(self.path, interval=0, samples=2, **options))
                    observed = list(watch(self.path, interval=0, samples=2,
                                          decision_state=True, **options))
                    for before, after in zip(plain, observed):
                        self.assert_safe(after.pop('decision_state'))
                        self.assertEqual(after, before)

    def test_actual_cli_standalone_flag_and_existing_dependency_guards(self):
        executable = Path(sys.prefix) / ('Scripts/mtgaplayer.exe' if os.name == 'nt' else 'bin/mtgaplayer')
        self.assertTrue(executable.is_file(), 'installed CLI entrypoint is required')
        save(self.path, frames())
        for command in ('replay', 'dry-run', 'watch'):
            with self.subTest(command=command):
                arguments = [str(executable), command, str(self.path)]
                arguments += ['--samples', '1', '--interval', '0.01'] if command == 'watch' else ['--format', 'player-log']
                def run(extra):
                    return subprocess.run(arguments + extra, cwd=ROOT, capture_output=True,
                                          text=True, encoding='utf-8', timeout=8, check=False)
                plain, enabled = run([]), run(['--decision-state'])
                self.assertEqual(plain.returncode, 0, plain.stderr)
                self.assertEqual(enabled.returncode, 0, enabled.stderr)
                self.assertEqual(enabled.stderr, '')
                result = json.loads(enabled.stdout)
                self.assert_safe(result.pop('decision_state'))
                self.assertEqual(result, json.loads(plain.stdout))
                for flag, reason in (('--action-gaps', 'action_gaps_requires_decision_input'),
                                     ('--action-frontier', 'action_frontier_requires_decision_input'),
                                     ('--choice-graph', 'choice_graph_requires_action_frontier'),
                                     ('--combat-frontier', 'combat_frontier_requires_decision_input')):
                    guarded = run(['--decision-state', flag])
                    self.assertEqual(guarded.returncode, 1)
                    self.assertEqual(json.loads(guarded.stdout), {'error': reason, 'input_sent': False})
        wrong_format = subprocess.run([str(executable), 'replay', str(self.path), '--decision-state'],
                                      cwd=ROOT, capture_output=True, text=True, encoding='utf-8',
                                      timeout=8, check=False)
        self.assertEqual(wrong_format.returncode, 1)
        self.assertEqual(json.loads(wrong_format.stdout)['error'],
                         'decision_state_requires_player_log_format')

    def test_replay_and_each_watch_sample_poll_the_raw_source_once(self):
        save(self.path, frames())
        original = RawFollower.poll
        with patch.object(RawFollower, 'poll', autospec=True, side_effect=original) as poll:
            document = replay(self.path, format='player-log', decision_state=True)
            self.assertEqual(poll.call_count, 1)
            self.assertEqual(document['decision_state']['binding']['game_state_id'],
                             document['current']['game_state_id'])
        with patch.object(RawFollower, 'poll', autospec=True, side_effect=original) as poll:
            stream = watch(self.path, interval=0, samples=3, decision_state=True)
            for count in range(1, 4):
                document = next(stream)
                self.assertEqual(poll.call_count, count)
                self.assertEqual(document['decision_state']['binding']['source_generation'],
                                 document['source']['generation'])
                self.assertEqual(document['decision_state']['source']['byte_offset'],
                                 document['source']['byte_offset'])

    def test_schema_metadata_local_refs_and_required_output_invariants(self):
        schema = json.loads(SCHEMA.read_text(encoding='utf-8'))
        self.assertEqual(schema['$schema'], 'https://json-schema.org/draft/2020-12/schema')
        self.assertEqual(schema['$id'], 'urn:mtgaplayer:decision-state:v1')
        self.assertEqual(set(schema['type']), {'object', 'null'})
        self.assertEqual(schema['properties']['schema_version']['const'], VERSION)
        self.assertIs(schema['additionalProperties'], False)
        self.assertEqual(set(schema['required']), set(schema['properties']))
        self.assertIn('complete_verified', schema['$defs']['completenessVocabulary']['enum'])
        self.assertEqual(schema['$defs']['phase1Completeness']['allOf'][1]['enum'],
                         ['partial', 'unknown'])
        # This checks the checked-in schema's structure, not a substitute validator.
        types = {'null', 'boolean', 'object', 'array', 'number', 'integer', 'string'}
        for node in walk(schema):
            if '$ref' in node:
                self.assertTrue(node['$ref'].startswith('#/'))
                target = schema
                for part in node['$ref'][2:].split('/'):
                    target = target[part.replace('~1', '/').replace('~0', '~')]
                self.assertIsInstance(target, dict)
            if 'type' in node:
                declared = node['type'] if isinstance(node['type'], list) else [node['type']]
                self.assertTrue(set(declared) <= types)
            if 'required' in node:
                self.assertEqual(len(node['required']), len(set(node['required'])))
                self.assertTrue(all(isinstance(name, str) for name in node['required']))
        for rows in (entries()[:3], frames(), selectn_rows(), baseline() + [request()]):
            result = self.observed(rows)
            self.assert_safe(result)
            self.assertEqual(set(result), set(schema['required']))
            self.assertEqual(set(result['binding']), set(schema['$defs']['binding']['required']))
            self.assertEqual(set(result['execution']), set(schema['properties']['execution']['required']))
            identity = {'generation': result['binding']['source_generation'], **{
                key: result['binding'][key] for key in
                ('match', 'game', 'self_seat', 'game_state_id', 'request_id')}}
            for node in walk(result['legal_action_space']):
                if 'request_identity' in node:
                    for name, value in identity.items():
                        self.assertEqual(node['request_identity'][name], value)
                        self.assertIs(type(node['request_identity'][name]), type(value))

if __name__ == '__main__':
    unittest.main()
