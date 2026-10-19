"""MP84 build-witness controls.

The version-header literal is the reviewed real shape. Authentication/Full and
request envelopes come from the public scrubbed bootstrap or are synthetic.
These controls do not authenticate a private log, installed DLL, or new target
role; every stream mutation is a synthetic negative.
"""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from mtgaplayer.cli import watch
from mtgaplayer.raw_log import RawFollower, RawReducer
from mtgaplayer.shadow_runtime import LocalShadowRuntime
from mtgaplayer.target_build import BUILD, PREFIX_BYTES, PROFILE, TargetBuildObserver, current_build


HEADER = b'Version: 2026.64.0.14517 / 2026.64.0.14517.1329972 / \n'


def bootstrap():
    fixture = ROOT / 'tests/fixtures/player_log_minimal.jsonl'
    return b''.join(line + b'\n' for line in fixture.read_bytes().splitlines()[:3])


def request(ident=500):
    row = {'greToClientEvent': {'greToClientMessages': [{
        'type': 'GREMessageType_ActionsAvailableReq', 'systemSeatIds': [1],
        'msgId': ident, 'gameStateId': 1,
        'actionsAvailableReq': {'actions': [{'actionType': 'ActionType_Pass'}]},
    }]}}
    return (json.dumps(row, separators=(',', ':')) + '\n').encode()


class Clock:
    now = 1_000_000_000

    def __call__(self):
        return self.now


class BuildWitnessControls(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'synthetic-build-stream.log'

    def observe(self, raw=HEADER, **kwargs):
        self.path.write_bytes(raw)
        observer = TargetBuildObserver()
        follower = RawFollower(self.path, byte_observer=observer,
            identity_prefix_bytes=PREFIX_BYTES, **kwargs)
        reducer = RawReducer()
        self.poll(follower, observer, reducer)
        return follower, observer, reducer

    def poll(self, follower, observer, reducer):
        reset, rows = follower.poll()
        if reset:
            reducer.reset(follower.generation)
        for row in rows:
            reducer.apply(row)
        observer.bind(reducer)
        return reset, rows

    def append(self, data):
        with self.path.open('ab') as output:
            output.write(data)

    def assert_witness(self, reducer):
        evidence = current_build(reducer)
        self.assertEqual(evidence, {
            'client_build': BUILD, 'mapping_profile': PROFILE,
            'generation': reducer.generation,
            'header_sha256': hashlib.sha256(HEADER).hexdigest(),
        })

    def test_reviewed_header_literal_with_synthetic_bootstrap(self):
        follower, observer, reducer = self.observe(HEADER + bootstrap())
        self.assert_witness(reducer)
        self.assertTrue(reducer.document()['current']['valid'])
        self.assertEqual(follower.identity_prefix_bytes, PREFIX_BYTES)
        self.assertFalse(observer.failed_closed)

    def test_missing_and_unterminated_header_have_no_witness(self):
        for raw in (bootstrap(), HEADER.rstrip(b'\n'), b'Version: '):
            with self.subTest(raw_shape='bootstrap' if raw.startswith(b'{') else 'partial'):
                _, _, reducer = self.observe(raw)
                self.assertIsNone(current_build(reducer))

    def test_wrong_full_or_short_build_rejected_independently(self):
        for raw in (
            HEADER.replace(b'1329972', b'1329973'),
            HEADER.replace(b'2026.64.0.14517 /', b'2026.64.0.14518 /'),
            b'Version: 2026.64.0.14517 / 2026.64.0.14517 / \n',
            b'Version: 2026.64.0.14517.1329972 / 2026.64.0.14517.1329972 / \n',
        ):
            with self.subTest(header=raw):
                _, _, reducer = self.observe(raw + bootstrap())
                self.assertIsNone(current_build(reducer))

    def test_header_syntax_not_recovered_from_nearby_numbers(self):
        for raw in (
            b'prefix ' + HEADER,
            HEADER.replace(b'Version:', b'Version='),
            HEADER.replace(b' / ', b'/', 1),
            b'{"Version":"2026.64.0.14517.1329972"}\n',
        ):
            with self.subTest(header=raw):
                _, _, reducer = self.observe(raw)
                self.assertIsNone(current_build(reducer))

    def test_duplicate_header_is_not_a_unique_build_witness(self):
        for second in (HEADER, HEADER.replace(b'1329972', b'1329973')):
            with self.subTest(duplicate=second):
                _, _, reducer = self.observe(HEADER + b'\n' + second + bootstrap())
                self.assertIsNone(current_build(reducer))

    def test_duplicate_header_appended_inside_prelude_revokes(self):
        follower, observer, reducer = self.observe(HEADER)
        self.assert_witness(reducer)
        self.append(HEADER)
        self.poll(follower, observer, reducer)
        self.assertIsNone(current_build(reducer))

    def test_second_header_after_prelude_revokes_without_prefix_growth(self):
        follower, observer, reducer = self.observe(HEADER + bootstrap() + b'\n' * PREFIX_BYTES)
        self.assert_witness(reducer)
        prefix_before = bytes(observer.prefix)
        self.assertGreater(follower.offset, PREFIX_BYTES)
        self.append(HEADER)
        reset, _ = self.poll(follower, observer, reducer)
        self.assertFalse(reset)
        self.assertEqual(bytes(observer.prefix), prefix_before)
        self.assertTrue(observer.failed_closed)
        self.assertIsNone(current_build(reducer))

    def test_second_header_marker_across_follower_chunks_is_not_missed(self):
        for split in (1, 4, 7):
            with self.subTest(marker_bytes_in_first_chunk=split):
                second_start = 65536 - split
                raw = HEADER + b'\n' * (second_start - len(HEADER)) + HEADER + bootstrap()
                follower, observer, reducer = self.observe(raw)
                self.assertGreater(second_start, PREFIX_BYTES)
                self.assertEqual(follower.offset, len(raw))
                self.assertTrue(observer.failed_closed)
                self.assertIsNone(current_build(reducer))

    def test_second_header_marker_split_across_polls_is_not_missed(self):
        follower, observer, reducer = self.observe(HEADER + bootstrap() + b'\n' * PREFIX_BYTES)
        self.assert_witness(reducer)
        self.append(b'Vers')
        self.poll(follower, observer, reducer)
        self.append(HEADER[4:])
        self.poll(follower, observer, reducer)
        self.assertTrue(observer.failed_closed)
        self.assertIsNone(current_build(reducer))

    def test_end_prefix_hash_mismatch_rejects_even_without_change_flag(self):
        observer = TargetBuildObserver()
        observer.begin({'reset': True, 'generation': 1})
        observer.write(0, HEADER)
        observer.end({'identity_prefix_sha256': hashlib.sha256(b'synthetic changed prefix').hexdigest(),
            'source_changed_during_poll': False})
        reducer = RawReducer()
        reducer.reset(1)
        observer.bind(reducer)
        self.assertTrue(observer.failed_closed)
        self.assertIsNone(current_build(reducer))

    def test_header_change_during_follower_read_fails_final_prefix_check(self):
        self.path.write_bytes(HEADER + bootstrap())
        observer = TargetBuildObserver()
        follower = RawFollower(self.path, byte_observer=observer, identity_prefix_bytes=PREFIX_BYTES)
        reducer = RawReducer()
        real_write = observer.write

        def change_header_after_read(offset, chunk):
            real_write(offset, chunk)
            with self.path.open('r+b') as output:
                output.write(HEADER.replace(b'1329972', b'1329973'))

        with patch.object(observer, 'write', side_effect=change_header_after_read):
            reset, rows = follower.poll()
        self.assertTrue(reset)
        self.assertEqual(len(rows), 3)
        reducer.reset(follower.generation)
        for row in rows:
            reducer.apply(row)
        observer.bind(reducer)
        self.assertTrue(observer.failed_closed)
        self.assertIsNone(current_build(reducer))
        self.assertTrue(reducer.document()['current']['valid'])

    def test_ordinary_growth_during_read_with_same_prefix_keeps_witness(self):
        raw = HEADER + bootstrap() + b'\n' * PREFIX_BYTES
        self.path.write_bytes(raw)
        observer = TargetBuildObserver()
        follower = RawFollower(self.path, byte_observer=observer, identity_prefix_bytes=PREFIX_BYTES)
        reducer = RawReducer()
        real_write, real_end = observer.write, observer.end
        endings = []
        grew = False

        def append_ordinary_text(offset, chunk):
            nonlocal grew
            real_write(offset, chunk)
            if not grew:
                self.append(b'ordinary appended logger text\n')
                grew = True

        def capture_end(info):
            endings.append(info.copy())
            real_end(info)

        with patch.object(observer, 'write', side_effect=append_ordinary_text), patch.object(
                observer, 'end', side_effect=capture_end):
            reset, rows = follower.poll()
        self.assertTrue(reset)
        self.assertTrue(endings[0]['source_changed_during_poll'])
        self.assertEqual(endings[0]['identity_prefix_sha256'],
            hashlib.sha256(raw[:PREFIX_BYTES]).hexdigest())
        reducer.reset(follower.generation)
        for row in rows:
            reducer.apply(row)
        observer.bind(reducer)
        self.assert_witness(reducer)
        self.assertFalse(observer.failed_closed)
        self.poll(follower, observer, reducer)
        self.assert_witness(reducer)

    def test_partial_header_waits_for_complete_newline(self):
        follower, observer, reducer = self.observe(HEADER[:-1])
        self.assertIsNone(current_build(reducer))
        self.append(b'\n' + bootstrap())
        reset, _ = self.poll(follower, observer, reducer)
        self.assertFalse(reset)
        self.assert_witness(reducer)

    def test_poll_byte_cap_does_not_authorize_partial_version(self):
        follower, observer, reducer = self.observe(HEADER + bootstrap(), max_poll_bytes=23)
        self.assertIsNone(current_build(reducer))
        self.poll(follower, observer, reducer)
        self.assertIsNone(current_build(reducer))
        self.poll(follower, observer, reducer)
        self.assert_witness(reducer)

    def test_prelude_is_bounded_and_header_beyond_limit_is_unknown(self):
        follower, observer, reducer = self.observe(b'\n' * PREFIX_BYTES + HEADER + bootstrap())
        self.assertIsNone(current_build(reducer))
        self.assertEqual(len(observer.prefix), PREFIX_BYTES)
        self.assertEqual(len(follower.prefix), PREFIX_BYTES)

    def test_header_cut_at_prelude_boundary_is_unknown(self):
        _, observer, reducer = self.observe(b'\n' * (PREFIX_BYTES - len(HEADER) + 1) + HEADER)
        self.assertEqual(len(observer.prefix), PREFIX_BYTES)
        self.assertIsNone(current_build(reducer))

    def test_wrong_profile_or_build_does_not_authorize(self):
        for field, value in (('profile', 'unreviewed_profile'), ('build', '2026.64.0.14517.0')):
            with self.subTest(field=field):
                _, _, reducer = self.observe()
                setattr(reducer._target_build_context, field, value)
                self.assertIsNone(current_build(reducer))

    def test_capability_cannot_be_copied_to_another_reducer(self):
        _, _, reducer = self.observe()
        other = RawReducer()
        other.reset(reducer.generation)
        for capability in (reducer._target_build_context, copy.copy(reducer._target_build_context)):
            other._target_build_context = capability
            self.assertIsNone(current_build(other))
        other._target_build_context = dict(current_build(reducer))
        self.assertIsNone(current_build(other))

    def test_reset_epoch_and_generation_prevent_old_capability_restore(self):
        for generation in (1, 2):
            with self.subTest(generation=generation):
                _, _, reducer = self.observe()
                prior = reducer._target_build_context
                reducer.reset(generation)
                reducer._target_build_context = prior
                self.assertIsNone(current_build(reducer))

    def test_generation_requires_strict_integer(self):
        _, _, reducer = self.observe()
        reducer._target_build_context.generation = True
        self.assertIsNone(current_build(reducer))

    def test_replaced_same_filename_does_not_retain_old_witness(self):
        follower, observer, reducer = self.observe(HEADER + bootstrap())
        old_generation = reducer.generation
        prior = reducer._target_build_context
        replacement = self.path.with_suffix('.new')
        replacement.write_bytes(bootstrap())
        replacement.replace(self.path)
        reset, _ = self.poll(follower, observer, reducer)
        self.assertTrue(reset)
        self.assertEqual(reducer.generation, old_generation + 1)
        self.assertIsNone(current_build(reducer))
        reducer._target_build_context = prior
        self.assertIsNone(current_build(reducer))

    def test_in_place_header_change_after_first_256_bytes_resets(self):
        raw = b'\n' * 512 + HEADER + bootstrap() + b'\n' * PREFIX_BYTES
        follower, observer, reducer = self.observe(raw)
        self.assert_witness(reducer)
        before_generation = follower.generation
        changed = raw.replace(b'1329972', b'1329973', 1)
        self.assertEqual(changed[:256], raw[:256])
        self.assertEqual(changed[-64:], raw[-64:])
        with self.path.open('r+b') as output:
            output.write(changed)
        reset, _ = self.poll(follower, observer, reducer)
        self.assertTrue(reset)
        self.assertEqual(follower.generation, before_generation + 1)
        self.assertIsNone(current_build(reducer))

    def test_default_follower_identity_prefix_stays_256(self):
        raw = b'\n' * 512 + HEADER + bootstrap() + b'\n' * PREFIX_BYTES
        self.path.write_bytes(raw)
        follower = RawFollower(self.path)
        self.assertIsNone(follower.byte_observer)
        self.assertEqual(follower.identity_prefix_bytes, 256)
        self.assertTrue(follower.poll()[0])
        self.assertEqual(len(follower.prefix), 256)
        with self.path.open('r+b') as output:
            output.write(raw.replace(b'1329972', b'1329973', 1))
        self.assertFalse(follower.poll()[0])

    def test_identity_prefix_limit_strict_type_and_bounds(self):
        for value in (True, False, 0, -1, PREFIX_BYTES + 1, 256.0, '256'):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, 'invalid_raw_identity_prefix_limit'):
                    RawFollower(self.path, identity_prefix_bytes=value)

    def test_byte_observer_failure_withholds_build_not_gre_records(self):
        self.path.write_bytes(HEADER + bootstrap())
        observer = TargetBuildObserver()
        follower = RawFollower(self.path, byte_observer=observer, identity_prefix_bytes=PREFIX_BYTES)
        reducer = RawReducer()
        with patch.object(observer, 'write', side_effect=OSError('synthetic observer failure')):
            reset, rows = follower.poll()
        self.assertTrue(reset)
        self.assertEqual(len(rows), 3)
        self.assertEqual(follower.byte_observer_error['error_type'], 'OSError')
        self.assertIsNone(follower.byte_observer)
        reducer.reset(follower.generation)
        for row in rows:
            reducer.apply(row)
        observer.bind(reducer)
        self.assertTrue(observer.failed_closed)
        self.assertIsNone(current_build(reducer))
        self.assertTrue(reducer.document()['current']['valid'])

    def test_failed_observer_cannot_recover_by_new_generation(self):
        follower, observer, reducer = self.observe()
        observer.failed()
        observer.begin({'reset': True, 'generation': follower.generation + 1})
        observer.write(0, HEADER)
        reducer.reset(follower.generation + 1)
        observer.bind(reducer)
        self.assertIsNone(current_build(reducer))

    def test_discontinuous_byte_callback_is_fail_closed(self):
        observer = TargetBuildObserver()
        observer.begin({'reset': True, 'generation': 1})
        observer.write(1, HEADER)
        reducer = RawReducer()
        reducer.reset(1)
        observer.bind(reducer)
        self.assertTrue(observer.failed_closed)
        self.assertIsNone(current_build(reducer))

    def test_owner_watch_binds_witness_and_legacy_watch_does_not(self):
        self.path.write_bytes(HEADER + bootstrap())
        completed = []

        def owner(reducer, message, **metadata):
            if metadata.get('poll_completed'):
                completed.append((reducer, current_build(reducer)))

        with patch('mtgaplayer.cli.RawFollower', wraps=RawFollower) as follower:
            list(watch(self.path, 0, 1, _poll_observer=lambda metadata: None, _owner_observer=owner))
        self.assertEqual(len(completed), 1)
        self.assert_witness(completed[0][0])
        self.assertEqual(follower.call_args.kwargs['identity_prefix_bytes'], PREFIX_BYTES)
        self.assertIsInstance(follower.call_args.kwargs['byte_observer'], TargetBuildObserver)
        with patch('mtgaplayer.cli.RawFollower', wraps=RawFollower) as follower:
            list(watch(self.path, 0, 1))
        self.assertEqual(follower.call_args.kwargs['identity_prefix_bytes'], 256)
        self.assertIsNone(follower.call_args.kwargs['byte_observer'])


class BuildRuntimeControls(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'synthetic-runtime-build.log'
        self.path.write_bytes(HEADER + bootstrap())
        self.clock = Clock()
        self.runtime = LocalShadowRuntime(self.path, interval=0, clock_ns=self.clock,
            observation_mode='controlled_stream_replay')
        self.frames = self.runtime.frames()
        self.addCleanup(self.runtime.close)
        self.addCleanup(self.frames.close)
        next(self.frames)

    def append(self, data):
        with self.path.open('ab') as output:
            output.write(data)
        return next(self.frames)

    def assert_revoked(self, frame):
        self.assertNotEqual(frame['time_scope'], 'current_at_completed_poll')
        self.assertIsNone(frame['request_binding'])
        self.assertIsNone(frame['shadow_preference'])
        self.assertFalse(frame['input_sent'])

    def test_runtime_owner_uses_witness_and_header_rotation_revokes_frame(self):
        frame = self.append(request())
        self.assertEqual(frame['time_scope'], 'current_at_completed_poll')
        self.assertEqual(current_build(self.runtime._reducer)['client_build'], BUILD)
        replacement = self.path.with_suffix('.replacement')
        replacement.write_bytes(bootstrap() + request(501))
        replacement.replace(self.path)
        self.assert_revoked(next(self.frames))
        self.assertIsNone(current_build(self.runtime._reducer))

    def test_witness_change_after_completed_poll_revokes_current_frame(self):
        self.assertEqual(self.append(request())['time_scope'], 'current_at_completed_poll')
        self.runtime._reducer._target_build_context.profile = 'synthetic unreviewed profile'
        self.assert_revoked(self.runtime.current_frame())

    def test_partial_record_never_uses_build_to_restore_current_request(self):
        self.assertEqual(self.append(request())['time_scope'], 'current_at_completed_poll')
        self.assert_revoked(self.append(b'{"unrelated":'))
        self.assert_revoked(self.append(b'1}\n'))
        self.assert_revoked(self.append(request()))
        self.assertEqual(self.append(request(501))['time_scope'], 'current_at_completed_poll')

    def test_build_witness_does_not_bypass_expired_lease_or_stop(self):
        self.assertEqual(self.append(request())['time_scope'], 'current_at_completed_poll')
        self.clock.now += 5_000_000_001
        self.assert_revoked(self.runtime.current_frame())
        self.runtime.close()
        self.assert_revoked(self.runtime.current_frame())


if __name__ == '__main__':
    unittest.main()
