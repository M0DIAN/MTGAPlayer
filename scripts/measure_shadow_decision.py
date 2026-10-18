"""Small offline append-to-shadow-output benchmark; no MTGA qualification."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

from mtgaplayer import shadow_decision as policy
from mtgaplayer.cli import watch_decision_events
from mtgaplayer.decision_consumer import DecisionConsumer
from mtgaplayer.decision_publisher import DecisionPublisher
from mtgaplayer.live_performance import quantiles

ROOT=Path(__file__).resolve().parents[1]
STAGES=('poll_read_ns','reducer_apply_ns','decision_state_assembly_ns',
        'event_publication_ns','poll_to_publish_ns')


def measure(samples):
    git=lambda *a:subprocess.check_output(['git',*a],cwd=ROOT,text=True).strip()
    sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    manifest=lambda:{str(p.relative_to(ROOT)):sha(p) for p in
        [*(ROOT/'src/mtgaplayer').glob('*.py'),Path(__file__).resolve()]}
    before=manifest();head=git('rev-parse','HEAD');tree=git('rev-parse','HEAD^{tree}')
    fixture=ROOT/'tests/fixtures/player_log_single_target.jsonl'
    equip=ROOT/'tests/fixtures/current_target_revision_real_v14.json'
    fixtures={str(p.relative_to(ROOT)):sha(p) for p in (fixture,equip)}
    lines=fixture.read_bytes().splitlines(keepends=True);records=[]
    original=policy._decide;core_times=[]
    def timed_core(*a,**kw):
        start=time.perf_counter_ns();result=original(*a,**kw)
        core_times.append(time.perf_counter_ns()-start);return result
    with tempfile.TemporaryDirectory() as folder,patch.object(policy,'_decide',timed_core):
        path=Path(folder)/'public-input.jsonl';output=Path(folder)/'shadow-output.jsonl'
        for sample in range(samples):
            path.write_bytes(b''.join(lines[:102]));output.write_bytes(b'')
            # Interpreter/import startup and input preparation are not timed.
            start=time.perf_counter_ns()
            stream=watch_decision_events(path,interval=0,samples=9,decision_state_version=15,
                session_id='offline-shadow-benchmark')
            consumer=DecisionConsumer();offset=0
            def poll(phase,cutoff,started,flushed=None):
                nonlocal offset
                consumer_ns=0;count=0
                for event in stream:
                    tick=time.perf_counter_ns();accepted=consumer.accept_event(event)
                    consumer_ns+=time.perf_counter_ns()-tick;count+=1
                    if not accepted:raise ValueError('benchmark_event_rejected')
                    if event['event_type']=='liveness':break
                else:raise ValueError('benchmark_poll_missing')
                before_core=len(core_times);tick=time.perf_counter_ns()
                decision=consumer.shadow_decision();api_ns=time.perf_counter_ns()-tick
                if decision['preferred_option_key'] is not None:
                    raise ValueError('real_cast_chain_must_abstain')
                if cutoff in (103,106,109) and decision['status']!='abstain':
                    raise ValueError('expected_current_abstention')
                if cutoff in (104,105,107,110) and decision['status']!='expired':
                    raise ValueError('expected_revocation')
                tick=time.perf_counter_ns();encoded=(json.dumps(decision,separators=(',',':'))+'\n').encode()
                with output.open('ab') as sink:sink.write(encoded);sink.flush()
                emitted=time.perf_counter_ns()
                # Same-process controller reads the complete actual file output.
                with output.open('rb') as source:source.seek(offset);line=source.readline()
                offset+=len(line)
                if json.loads(line)!=decision:raise ValueError('output_observation_mismatch')
                observed=time.perf_counter_ns()
                records.append({'sample':sample,'phase':phase,'cutoff':cutoff,'events':count,
                    'status':decision['status'],'consumer_accept_ns':consumer_ns,'shadow_api_ns':api_ns,
                    'policy_core_ns':sum(core_times[before_core:]) if len(core_times)>before_core else None,
                    'serialize_write_flush_ns':emitted-tick,'local_start_to_observed_ns':observed-started,
                    'flush_to_observed_ns':observed-flushed if flushed is not None else None,
                    **{name:event['timing'][name] for name in STAGES}})
            try:
                poll('cold_history',102,start);previous=102
                for cutoff in (103,104,105,106,107,109,110):
                    start=time.perf_counter_ns()
                    with path.open('ab') as sink:sink.write(b''.join(lines[previous:cutoff]));sink.flush()
                    flushed=time.perf_counter_ns();previous=cutoff
                    poll('incremental',cutoff,start,flushed)
            finally:stream.close();consumer.close('benchmark_ended')

    # Positive policy-core timing uses the already published portable Equip
    # first-child state. Synthetic append transport is outside this timed loop.
    state=json.loads(equip.read_text(encoding='utf8'))['first_child']
    state=copy.deepcopy(state);state['source'].update(mode='watch',phase='append',stopped=False)
    clock=lambda:1_000_000
    pub=DecisionPublisher(clock_ns=clock,session_id='synthetic-shadow-core',state_version=14)
    meta={'poll_started_ns':clock(),'poll_completed_ns':clock(),'poll_read_ns':0,'reducer_apply_ns':0,
        'decision_state_assembly_ns':0,'request_changed':True,'new_final_request':True}
    c=DecisionConsumer(clock_ns=clock)
    for e in pub.observe({'decision_state':state,'source':{'phase':'append','partial_record':False}},meta):
        if not c.accept_event(e):raise ValueError('core_transport_invalid')
    options=c.current_decision_options();expected=c.shadow_decision();positive_core=[]
    if expected['status']!='research_preference':raise ValueError('unique_equip_preference_missing')
    for _ in range(samples):
        start=time.perf_counter_ns();result=original(options);positive_core.append(time.perf_counter_ns()-start)
        if result!=expected:raise ValueError('pure_core_not_deterministic')
    c.close('benchmark_ended')

    metrics=(*STAGES,'consumer_accept_ns','shadow_api_ns','policy_core_ns',
        'serialize_write_flush_ns','local_start_to_observed_ns','flush_to_observed_ns')
    def summarize(selected):
        return {'polls':len(selected),'latency_ms':{name:quantiles(
            [r[name]/1_000_000 for r in selected if r[name] is not None]) for name in metrics}}
    groups={phase:summarize([r for r in records if r['phase']==phase])
        for phase in ('cold_history','incremental')}
    groups['incremental_current_request']=summarize([r for r in records
        if r['phase']=='incremental' and r['status']=='abstain'])
    by_cutoff={str(cutoff):summarize([r for r in records if r['cutoff']==cutoff])
        for cutoff in (102,103,104,105,106,107,109,110)}
    assert before==manifest() and head==git('rev-parse','HEAD') and tree==git('rev-parse','HEAD^{tree}')
    assert fixtures=={str(p.relative_to(ROOT)):sha(p) for p in (fixture,equip)}
    return {'schema':'mtgaplayer.shadow-performance.v1','head':head,'tree':tree,
        'tracked_dirty':bool(git('status','--porcelain','--untracked-files=no')),
        'python':sys.version,'repetitions':samples,'source_sha256':before,'fixture_sha256':fixtures,
        'source_and_fixtures_stable':True,'groups':groups,'by_cutoff':by_cutoff,'raw_polls':records,
        'unique_equip_policy_core':quantiles([v/1_000_000 for v in positive_core]),
        'unique_equip_policy_core_raw_ns':positive_core,
        'definitions':{
            'local_start_to_observed_ns':'cold: watcher construction through history/output read; incremental: before controlled append through complete JSON read/validation in same process',
            'flush_to_observed_ns':'after input flush returns through complete output read/validation; local same-process filesystem path, no polling wait',
            'shadow_api_ns':'whole public API including MP65 generation/cache, existing Advisor when applicable and before/after currentness gates',
            'policy_core_ns':'instrumented pure interpretation of the same options/advice; excludes MP65 generation, Advisor calculation and currentness gates; null when gate skips policy',
            'producer_stages':'production watch/Publisher durations sampled once at liveness per poll; poll_to_publish includes sub-stages, never add them or their quantiles',
            'scope':'retained public Cast chain; direct owner Consumer; controlled append and file flush/read, interpreter already running; tiny wrapper timing overhead included',
            'positive_core':'portable real Equip first_child via synthetic transport; only already-built-options pure core timed, not incremental end-to-end',
        },'game_event_to_log_write_ms':None,'true_mtga_end_to_end_ms':None,
        'input_sent':False,'P10':'NOT_RUN'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--samples',type=int,default=20)
    parser.add_argument('--output',type=Path,default=ROOT/'artifacts/local-mp66/performance.json')
    args=parser.parse_args()
    if not 1<=args.samples<=100:parser.error('samples must be1..100')
    report=measure(args.samples);args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    print(json.dumps({'output':str(args.output),'polls':len(report['raw_polls']),
        'cold_history':report['groups']['cold_history']['polls'],
        'incremental':report['groups']['incremental']['polls']}))
    return 0


if __name__=='__main__':raise SystemExit(main())
