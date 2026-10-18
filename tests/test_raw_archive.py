"""Raw storage tests use controlled files, never a fabricated game positive."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from mtgaplayer.raw_archive import RawArchive,verify_archive,private_directory
from mtgaplayer.raw_log import RawFollower,RawFramer

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import local_live_poc as poc


class RawArchiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.log=self.root/'Player.log';self.output=self.root/'archive';self.writer=None

    def tearDown(self):
        if self.writer is not None and not self.writer.closed:self.writer.close()
        self.tmp.cleanup()

    def archive(self,**kwargs):
        self.writer=RawArchive(self.log,self.output,**kwargs);return self.writer

    def manifest(self):return json.loads((self.output/'manifest.json').read_text())

    def captured(self,number=0):
        return b''.join((self.output/s['file']).read_bytes() for s in self.manifest()['generations'][number]['segments'])

    def test_exact_bytes_partial_invalid_and_raw_framer_replay(self):
        data=b'\xffprefix\r\n { "x" : 1 }\r\n{broken}\n{"unfinished":"\xe4'
        self.log.write_bytes(data);writer=self.archive();writer.poll();writer.close()
        self.assertEqual(self.captured(),data)
        result=verify_archive(self.output);gen=result['generations'][0]
        self.assertEqual(gen['sha256'],hashlib.sha256(data).hexdigest())
        self.assertTrue(gen['partial_record']);self.assertEqual(gen['framing_errors'],1)
        self.assertFalse(result['complete_source_files_verified'])
        framer=RawFramer();expected=framer.feed(data)
        replay=RawFramer();actual=[]
        for s in self.manifest()['generations'][0]['segments']:actual+=replay.feed((self.output/s['file']).read_bytes())
        self.assertEqual(actual,expected)

    def test_bounded_append_no_duplicate_and_clean_stop(self):
        self.log.write_bytes(b'prefix\r\n{"x":1}\n');writer=self.archive(max_poll_bytes=7)
        writer.poll();first=self.manifest()['generations'][0]
        self.assertEqual(first['byte_count'],7);self.assertGreater(first['backlog_bytes'],0)
        with self.log.open('ab') as f:f.write(b'{"y":2}\n')
        while writer.follower.offset<self.log.stat().st_size:writer.poll()
        saved=self.manifest()['generations'][0]['segments'];writer.poll()
        self.assertEqual(saved,self.manifest()['generations'][0]['segments'])
        writer.close();self.assertEqual(self.captured(),self.log.read_bytes())
        self.assertTrue(verify_archive(self.output)['complete_source_files_verified'])

    def test_rotation_replacement_keeps_old_generation_and_known_backlog(self):
        self.log.write_bytes(b'A'*100);writer=self.archive(max_poll_bytes=10);writer.poll()
        saved=self.captured();old=self.root/'retired.log';self.log.rename(old)
        self.log.write_bytes(b'{"new":true}\n');writer.poll();writer.close()
        result=verify_archive(self.output)
        self.assertEqual(self.captured(0),saved);self.assertEqual(len(result['generations']),2)
        self.assertTrue(result['rotation_gap_possible'])
        self.assertEqual(result['generations'][0]['known_unread_bytes_at_rotation'],90)
        self.assertFalse(result['complete_source_files_verified'])

    def test_truncate_and_same_name_rewrite_are_new_generations(self):
        self.log.write_bytes(b'A'*512);writer=self.archive();writer.poll()
        self.log.write_bytes(b'B'*16);writer.poll()
        self.log.write_bytes(b'C'*16);writer.poll();writer.close()
        self.assertEqual([g['bytes'] for g in verify_archive(self.output)['generations']],[512,16,16])
        self.assertEqual(self.captured(0),b'A'*512);self.assertEqual(self.captured(1),b'B'*16)

    def test_interior_rewrite_not_hidden_by_edge_witnesses_at_stop(self):
        self.log.write_bytes(b'A'*1024);writer=self.archive();writer.poll()
        with self.log.open('r+b') as stream:stream.seek(500);stream.write(b'B')
        writer.poll();self.assertEqual(writer.follower.generation,1)
        writer.close();result=verify_archive(self.output)
        self.assertFalse(result['generations'][0]['source_verified_at_stop'])
        self.assertFalse(result['complete_source_files_verified'])
        self.assertEqual(self.captured(),b'A'*1024)

    def test_resume_verifies_full_prefix_and_partial_framer(self):
        first=b'prefix{"x":';self.log.write_bytes(first);writer=self.archive();writer.poll();writer.close()
        with self.log.open('ab') as stream:stream.write(b'42}\r\n')
        writer=self.archive(resume=True);self.assertEqual(writer.follower.offset,len(first))
        reset,records=writer.poll();self.assertFalse(reset);self.assertEqual(records,[{'x':42}])
        writer.close();result=verify_archive(self.output)
        self.assertEqual(self.captured(),self.log.read_bytes());self.assertEqual(len(result['generations']),1)
        self.assertTrue(result['unobserved_resume_interval']);self.assertTrue(result['rotation_gap_possible'])

    def test_resume_interior_mismatch_starts_new_generation(self):
        self.log.write_bytes(b'A'*1024);writer=self.archive();writer.poll();writer.close()
        with self.log.open('r+b') as stream:stream.seek(500);stream.write(b'B')
        writer=self.archive(resume=True);writer.poll();writer.close()
        self.assertEqual(len(self.manifest()['generations']),2)
        self.assertEqual(self.captured(0),b'A'*1024);self.assertEqual(self.captured(1),self.log.read_bytes())

    def test_closed_writer_cannot_revoke_resumed_writer_commit(self):
        self.log.write_bytes(b'{}');old=self.archive();old.poll();old.close()
        with self.log.open('ab') as stream:stream.write(b'{}')
        writer=self.archive(resume=True);writer.poll();committed=self.manifest()
        with self.assertRaises(ValueError):old.poll()
        old.failed();old.follower.poll()
        self.assertEqual(self.manifest(),committed)
        writer.close();self.assertEqual(self.captured(),b'{}{}')

    def test_crash_orphan_is_not_committed_or_deleted_on_resume(self):
        self.log.write_bytes(b'{"first":1}\n');writer=self.archive();writer.poll()
        with self.log.open('ab') as stream:stream.write(b'{"later":2}\n')
        with patch('mtgaplayer.raw_archive._commit',side_effect=OSError(28,'test_full')):writer.poll()
        writer.lock.close();writer.closed=True # simulated process loss after fsynced segment, before metadata
        prefix=self.captured();self.assertNotEqual(prefix,self.log.read_bytes())
        self.assertGreater(verify_archive(self.output)['uncommitted_segment_files'],0)
        writer=self.archive(resume=True);writer.poll();writer.close()
        self.assertEqual(self.captured(),self.log.read_bytes())
        self.assertGreater(verify_archive(self.output)['uncommitted_segment_files'],0)

    def test_space_and_io_failure_preserve_checkpoint_and_production_records(self):
        self.log.write_bytes(b'{"x":1}');writer=self.archive();writer.poll();saved=self.captured()
        with self.log.open('ab') as stream:stream.write(b'{"y":2}')
        usage=__import__('shutil').disk_usage(self.root)
        with patch('mtgaplayer.raw_archive.shutil.disk_usage',return_value=type(usage)(1,1,0)):
            reset,records=writer.poll()
        self.assertEqual(records,[{'y':2}]);self.assertEqual(self.captured(),saved)
        self.assertIsNotNone(writer.follower.byte_observer_error)
        writer.close();self.assertTrue(verify_archive(self.output)['archive_error'])

    def test_source_read_error_does_not_commit_pending_or_prevent_close(self):
        self.log.write_bytes(b'{"x":1}');writer=self.archive();writer.poll()
        self.log.unlink()
        with self.assertRaises(OSError):writer.poll()
        writer.close();self.assertEqual(self.captured(),b'{"x":1}')
        self.assertFalse(verify_archive(self.output)['complete_source_files_verified'])

    def test_tampered_segment_ranges_or_hash_rejected(self):
        self.log.write_bytes(b'{"x":1}');writer=self.archive();writer.poll();writer.close()
        manifest=self.manifest();file=self.output/manifest['generations'][0]['segments'][0]['file']
        original=file.read_bytes();file.write_bytes(b'Z'*len(original))
        self.assertEqual(verify_archive(self.output)['status'],'invalid_or_incomplete_archive')
        file.write_bytes(original)
        for kind in ('start','end','name','generation'):
            bad=copy.deepcopy(manifest);gen=bad['generations'][0];seg=gen['segments'][0]
            if kind=='start':seg['byte_start']=True
            if kind=='end':seg['byte_end']+=1
            if kind=='name':seg['file']='../Player.log'
            if kind=='generation':gen['generation']=2
            (self.output/'manifest.json').write_text(json.dumps(bad))
            self.assertEqual(verify_archive(self.output)['status'],'invalid_or_incomplete_archive')
        (self.output/'manifest.json').write_text(json.dumps(manifest))

    def test_privacy_guard_and_existing_directory_not_overwritten(self):
        self.assertEqual(private_directory(self.output),self.output.resolve())
        with self.assertRaises(ValueError):private_directory(ROOT/'docs'/'raw-private')
        self.log.write_bytes(b'{}');writer=self.archive();writer.close()
        with self.assertRaises(FileExistsError):RawArchive(self.log,self.output)
        self.assertEqual(self.log.read_bytes(),b'{}')

    def test_git_failure_inside_worktree_fails_closed(self):
        failure=subprocess.CompletedProcess([],128,stdout='',stderr='not exported')
        with patch('mtgaplayer.raw_archive.subprocess.run',return_value=failure):
            with self.assertRaises(ValueError):private_directory(ROOT/'docs'/'unignored-private-raw')

    def test_archive_path_cannot_contain_source_or_follow_segment_link(self):
        self.log.write_bytes(b'{}')
        with self.assertRaises(ValueError):RawArchive(self.log,self.root)
        writer=self.archive();writer.poll();writer.close()
        segment=self.output/self.manifest()['generations'][0]['segments'][0]['file']
        original=segment.read_bytes();segment.unlink()
        try:segment.symlink_to(self.log)
        except OSError:
            segment.write_bytes(original)
            return # platform privilege unavailable; other path traversal controls still apply
        self.assertEqual(verify_archive(self.output)['status'],'invalid_or_incomplete_archive')

    def test_exclusive_writer_and_read_only_verification(self):
        self.log.write_bytes(b'{}');writer=self.archive();writer.poll()
        with self.assertRaises(OSError):RawArchive(self.log,self.output,resume=True)
        before={p.name:p.read_bytes() for p in self.output.iterdir() if p.is_file() and p.name!='.writer.lock'}
        verify_archive(self.output)
        self.assertEqual(before,{p.name:p.read_bytes() for p in self.output.iterdir() if p.is_file() and p.name!='.writer.lock'})

    def test_cli_archive_and_verifier_do_not_export_paths_or_raw_values(self):
        self.log.write_bytes(b'{"private_unique_payload":1}\n')
        cmd=[sys.executable,str(ROOT/'scripts/local_live_poc.py')]
        run=subprocess.run(cmd+['archive','--log',str(self.log),'--output',str(self.output),'--once'],capture_output=True,text=True)
        self.assertEqual(run.returncode,0,run.stderr)
        verify=subprocess.run(cmd+['verify-archive','--archive',str(self.output)],capture_output=True,text=True)
        self.assertEqual(verify.returncode,0,verify.stderr)
        for out in (run.stdout,verify.stdout):
            self.assertNotIn(str(self.root),out);self.assertNotIn('private_unique_payload',out)
            self.assertTrue(json.loads(out)['complete_source_files_verified'])

    def test_collector_archive_error_isolated_from_game_state_and_default(self):
        fixture=ROOT/'tests/fixtures/player_log_minimal.jsonl';self.log.write_bytes(fixture.read_bytes())
        a=poc.Collector(self.log,self.root/'normal',capture=lambda *a,**k:None)
        b=poc.Collector(self.log,self.root/'with-archive',capture=lambda *a,**k:None,raw_archive=self.output)
        try:
            with patch('mtgaplayer.raw_archive.shutil.disk_usage',side_effect=OSError('private_path_not_public')):
                a.poll_once(screenshots=False);b.poll_once(screenshots=False)
            self.assertEqual(a.reducer.document(),b.reducer.document())
            self.assertEqual(a.counts,b.counts);self.assertFalse(a.manifest['raw_bytes_retained'])
            health=json.loads((b.output/'health.json').read_text())
            self.assertNotIn('log_error',health);self.assertIsNotNone(health['raw_archive']['error'])
        finally:a.close();b.close()


if __name__=='__main__':unittest.main()
