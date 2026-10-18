"""Local immutable raw-byte segments from the existing RawFollower read loop.

No GRE projection, reducer, uploader or execution path. Manifest commits name
only fsynced complete segments. Uncommitted files are retained, never recovered
as evidence merely because they exist. Public verification is a fixed summary.
"""
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import uuid

from .raw_log import RawFollower, RawFramer

VERSION = 'mtgaplayer.local-raw-archive.v1'
EMPTY = hashlib.sha256(b'').hexdigest()
MAX_SEGMENTS = 16384
MAX_MANIFEST = 16*1024*1024


def _now():return datetime.now(timezone.utc).isoformat(timespec='microseconds')


def private_directory(path):
    """Resolve links; allow outside Git or an untracked Git-ignored target."""
    path=Path(path).resolve()
    parent=path
    while not parent.exists():parent=parent.parent
    result=subprocess.run(['git','-C',str(parent),'rev-parse','--show-toplevel'],
        capture_output=True,text=True,check=False)
    if result.returncode==0:
        root=Path(result.stdout.strip()).resolve()
        relative=path.relative_to(root).as_posix()
        ignored=subprocess.run(['git','-C',str(root),'check-ignore','--no-index','--',relative+'/'],capture_output=True)
        tracked=subprocess.run(['git','-C',str(root),'ls-files','--',relative],capture_output=True)
        if ignored.returncode or tracked.returncode or tracked.stdout:
            raise ValueError('archive_directory_must_be_untracked_and_git_ignored_or_outside_git')
    elif any((ancestor/'.git').exists() for ancestor in (parent,*parent.parents)):
        raise ValueError('archive_git_privacy_check_failed')
    return path


def _commit(path, value):
    data=(json.dumps(value,sort_keys=True,indent=2)+'\n').encode('utf8')
    if len(data)>MAX_MANIFEST:raise ValueError('archive_manifest_limit')
    temporary=path.with_name('checkpoint-'+uuid.uuid4().hex+'.pending')
    with temporary.open('xb') as stream:
        stream.write(data);stream.flush();os.fsync(stream.fileno())
    os.replace(temporary,path)
    # Directory fsync is not exposed portably on Windows. We promise the
    # logical commit boundary, not immunity to storage/power-loss failures.


def _manifest(path):
    path=Path(path)/'manifest.json'
    if path.stat().st_size>MAX_MANIFEST:raise ValueError('archive_manifest_limit')
    value=json.loads(path.read_text(encoding='utf8'))
    if type(value) is not dict or value.get('schema_version')!=VERSION:
        raise ValueError('invalid_archive_manifest')
    return value


def _segment_path(root, name):
    if type(name) is not str or re.fullmatch(r'segment-[a-f0-9]{32}\.raw',name) is None:
        raise ValueError('invalid_archive_segment_name')
    path=root/name
    if path.is_symlink() or path.resolve().parent!=root.resolve():raise ValueError('invalid_archive_segment_path')
    return path


def _scan(root, manifest, feed=None):
    """Validate all committed bytes/ranges; no inferred or repaired segments."""
    generations=manifest.get('generations')
    if type(generations) is not list or len(generations)>1024:raise ValueError('invalid_archive_generations')
    names=set();summaries=[];last=0
    for gen in generations:
        number=gen['generation']
        if type(number) is not int or number!=last+1:raise ValueError('archive_generation_discontinuity')
        last=number;offset=0;whole=hashlib.sha256();framer=RawFramer();records=0
        for segment in gen['segments']:
            name=segment['file'];path=_segment_path(root,name)
            if name in names or len(names)>=MAX_SEGMENTS:raise ValueError('archive_segment_reused_or_limit')
            names.add(name)
            start,end=segment['byte_start'],segment['byte_end']
            if type(start) is not int or type(end) is not int or start!=offset or end<=start:
                raise ValueError('archive_byte_range_discontinuity')
            if path.stat().st_size!=end-start:raise ValueError('archive_segment_length_mismatch')
            digest=hashlib.sha256()
            with path.open('rb') as stream:
                for chunk in iter(lambda:stream.read(65536),b''):
                    digest.update(chunk);whole.update(chunk);records+=len(framer.feed(chunk))
                    if feed is not None:feed(number,chunk)
            if digest.hexdigest()!=segment['sha256']:raise ValueError('archive_segment_hash_mismatch')
            offset=end
        if type(gen['byte_count']) is not int or offset!=gen['byte_count'] or whole.hexdigest()!=gen['sha256']:
            raise ValueError('archive_generation_hash_or_length_mismatch')
        summaries.append({'generation':number,'bytes':offset,'sha256':whole.hexdigest(),
            'segments':len(gen['segments']),'ranges_contiguous':True,
            'framed_records':records,'partial_record':framer.partial,'framing_errors':framer.errors,
            'source_verified_at_stop':gen.get('source_verified_at_stop',False),
            'backlog_bytes_at_last_poll':gen.get('backlog_bytes'),
            'source_changed_during_poll':gen.get('source_changed_during_poll'),
            'rotation_gap_possible':gen.get('rotation_gap_possible',False),
            'known_unread_bytes_at_rotation':gen.get('known_unread_bytes_at_rotation')})
    return summaries,names


def verify_archive(directory):
    """Read-only, no absolute paths, field values, identities or raw error text."""
    root=Path(directory).resolve()
    try:
        manifest=_manifest(root);summaries,names=_scan(root,manifest)
        orphans=sum(p.name not in names for p in root.glob('segment-*.raw'))
        pending=sum(1 for _ in root.glob('*.pending'))
        stopped=manifest['status']=='stopped'
        return {'schema_version':VERSION,'status':'verified','generations':summaries,
            'committed_bytes':sum(s['bytes'] for s in summaries),
            'uncommitted_segment_files':orphans,'pending_metadata_files':pending,
            'clean_stop':stopped,'archive_error':manifest.get('archive_error'),
            'unobserved_resume_interval':manifest.get('unobserved_resume_interval',False),
            'rotation_gap_possible':bool(not stopped or manifest.get('unobserved_resume_interval') or
                any(s['rotation_gap_possible'] for s in summaries)),
            'complete_source_files_verified':bool(stopped and summaries and not orphans and not pending and
                not manifest.get('unobserved_resume_interval') and
                not manifest.get('archive_error') and all(s['source_verified_at_stop'] and
                not s['partial_record'] and not s['framing_errors'] and not s['rotation_gap_possible'] for s in summaries)),
            'read_only':True,'input_sent':False,'P10':'NOT_RUN'}
    except (OSError,ValueError,KeyError,TypeError) as exc:
        return {'schema_version':VERSION,'status':'invalid_or_incomplete_archive',
            'error_type':type(exc).__name__,'complete_source_files_verified':False,
            'read_only':True,'input_sent':False,'P10':'NOT_RUN'}


class RawArchive:
    """One writer; bounded polls, immutable data, resumable verified prefix."""
    def __init__(self, source, directory, *, resume=False, max_poll_bytes=1024*1024,
                 reserve_bytes=8*1024*1024, max_archive_bytes=1024**3):
        self.source=Path(source).resolve();self.root=private_directory(directory)
        if self.source==self.root or self.root in self.source.parents:
            raise ValueError('source_must_be_outside_archive_directory')
        if type(reserve_bytes) is not int or reserve_bytes<0 or type(max_archive_bytes) is not int or max_archive_bytes<1:
            raise ValueError('invalid_archive_resource_limit')
        self.root.mkdir(parents=True,exist_ok=resume)
        self.lock=(self.root/'.writer.lock').open('a+b');self.stream=None;self.closed=False
        self.reserve_bytes=reserve_bytes;self.max_archive_bytes=max_archive_bytes
        self.hasher=hashlib.sha256();self.candidate=None
        try:
            if os.name=='nt':
                import msvcrt
                if self.lock.seek(0,2)==0:self.lock.write(b'0');self.lock.flush()
                self.lock.seek(0)
                msvcrt.locking(self.lock.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(self.lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            self.follower=RawFollower(self.source,max_history_bytes=max_archive_bytes,
                byte_observer=self,max_poll_bytes=max_poll_bytes)
            if resume:
                self.manifest=_manifest(self.root)
                if self.manifest['source_path_private']!=str(self.source):raise ValueError('archive_resume_source_path_mismatch')
                summaries,_=_scan(self.root,self.manifest)
                self.follower.generation=len(summaries)
                if summaries:
                    gen=self.manifest['generations'][-1]
                    if self._source_matches(gen,require_eof=False):
                        self.follower.identity=tuple(gen['identity']);self.follower.offset=gen['byte_count']
                        def restore(number,chunk):
                            if number==gen['generation']:
                                self.hasher.update(chunk);self.follower.framer.feed(chunk)
                        _scan(self.root,self.manifest,restore)
                        with self.source.open('rb') as stream:
                            self.follower.prefix=stream.read(min(256,self.follower.offset))
                            self.follower.anchor_start=max(0,self.follower.offset-64)
                            stream.seek(self.follower.anchor_start)
                            self.follower.anchor=stream.read(self.follower.offset-self.follower.anchor_start)
                    else:
                        gen['rotation_gap_possible']=True
                        gen['closed_reason']='resume_source_mismatch'
                self.manifest['unobserved_resume_interval']=True
                self.manifest['status']='running';self.manifest['archive_error']=None
            else:
                self.manifest={'schema_version':VERSION,'source_path_private':str(self.source),
                    'started_at':_now(),'completed_at':None,'status':'running','generations':[],
                    'archive_error':None,'unobserved_resume_interval':False,
                    'private_evidence_do_not_upload':True,'input_sent':False}
            _commit(self.root/'manifest.json',self.manifest)
        except BaseException:
            self.lock.close();raise

    def _source_matches(self, gen, *, require_eof):
        try:
            with self.source.open('rb') as stream:
                pre=os.fstat(stream.fileno())
                identity=(pre.st_dev,pre.st_ino) if pre.st_ino else (pre.st_ctime_ns,)
                if list(identity)!=gen['identity'] or pre.st_size<gen['byte_count'] or require_eof and pre.st_size!=gen['byte_count']:return False
                digest=hashlib.sha256();remaining=gen['byte_count']
                while remaining:
                    chunk=stream.read(min(65536,remaining))
                    if not chunk:return False
                    digest.update(chunk);remaining-=len(chunk)
                post=os.fstat(stream.fileno())
            # Also detect path replacement while the original fd was open.
            current=self.source.stat()
            return digest.hexdigest()==gen['sha256'] and (pre.st_size,pre.st_mtime_ns,pre.st_ino)==(post.st_size,post.st_mtime_ns,post.st_ino)==(current.st_size,current.st_mtime_ns,current.st_ino)
        except OSError:return False

    def begin(self, meta):
        if self.closed:raise ValueError('archive_closed')
        self.candidate=copy.deepcopy(self.manifest)
        generations=self.candidate['generations']
        if meta['reset']:
            if generations:
                old=generations[-1];old['rotation_gap_possible']=True
                old['closed_reason']='rotation_or_rewrite'
                old['known_unread_bytes_at_rotation']=max(0,old['source_size_seen']-old['byte_count'])
            if meta['generation']!=len(generations)+1 or len(generations)>=1024:raise ValueError('archive_generation_limit_or_mismatch')
            generations.append({'generation':meta['generation'],'identity':meta['identity'],
                'started_at':_now(),'capture_completed_at':None,'byte_count':0,'sha256':EMPTY,
                'segments':[],'source_size_seen':meta['source_size'],'source_verified_at_stop':False,
                'rotation_gap_possible':False,'known_unread_bytes_at_rotation':None})
            self.hasher=hashlib.sha256()
        gen=generations[-1]
        if gen['byte_count']!=meta['byte_start'] or gen['identity']!=meta['identity']:
            raise ValueError('archive_byte_continuity_lost')
        gen['source_size_seen']=meta['source_size'];gen['source_verified_at_stop']=False
        self.start=meta['byte_start'];self.position=self.start;self.segment_hash=hashlib.sha256()
        self.started=_now();self.name=None

    def write(self, offset, data):
        if self.closed:raise ValueError('archive_closed')
        if offset!=self.position:raise ValueError('archive_noncontiguous_chunk')
        total=sum(g['byte_count'] for g in self.manifest['generations'])+self.position-self.start+len(data)
        if total>self.max_archive_bytes or shutil.disk_usage(self.root).free<len(data)+self.reserve_bytes:
            raise OSError(28,'archive_space_limit')
        if self.stream is None:
            if sum(len(g['segments']) for g in self.manifest['generations'])>=MAX_SEGMENTS:raise ValueError('archive_segment_limit')
            self.name='segment-'+uuid.uuid4().hex+'.raw';self.stream=(self.root/self.name).open('xb')
        if self.stream.write(data)!=len(data):raise OSError('archive_short_write')
        self.hasher.update(data);self.segment_hash.update(data);self.position+=len(data)

    def end(self, meta):
        if self.closed:raise ValueError('archive_closed')
        if self.position!=meta['byte_end']:raise ValueError('archive_poll_range_mismatch')
        if self.stream is not None:
            self.stream.flush();os.fsync(self.stream.fileno());self.stream.close();self.stream=None
        gen=self.candidate['generations'][-1]
        if self.name is not None:
            gen['segments'].append({'file':self.name,'byte_start':self.start,'byte_end':self.position,
                'sha256':self.segment_hash.hexdigest(),'started_at':self.started,'completed_at':_now()})
        gen.update(byte_count=self.position,sha256=self.hasher.hexdigest(),
            capture_completed_at=_now(),source_size_seen=max(meta['source_size'],meta['source_size_after']),
            backlog_bytes=max(0,meta['source_size'],meta['source_size_after'])-self.position,
            partial_record=meta['partial_record'],framing_errors=meta['framing_errors'],
            source_changed_during_poll=meta['source_changed_during_poll'])
        _commit(self.root/'manifest.json',self.candidate)
        self.manifest=self.candidate;self.candidate=None

    def failed(self):
        if self.closed:return
        if self.stream is not None:self.stream.close();self.stream=None
        self.candidate=None
        self.manifest['archive_error']='archive_io_or_continuity_failed'
        try:_commit(self.root/'manifest.json',self.manifest)
        except (OSError,ValueError):pass

    def poll(self):
        if self.closed:raise ValueError('archive_closed')
        return self.follower.poll()

    def close(self):
        if self.closed:return
        try:
            if self.stream is not None:self.failed()
            if self.manifest['generations']:
                gen=self.manifest['generations'][-1]
                gen['source_verified_at_stop']=self._source_matches(gen,require_eof=True)
                gen['source_verification_completed_at']=_now()
            self.manifest.update(status='stopped',completed_at=_now())
            _commit(self.root/'manifest.json',self.manifest)
        finally:
            self.closed=True;self.follower.byte_observer=None;self.lock.close()
