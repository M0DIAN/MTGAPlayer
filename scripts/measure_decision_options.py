"""Bounded local current-options API timings; no game or native qualification."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from mtgaplayer.cli import replay
from mtgaplayer.decision_consumer import DecisionConsumer
from mtgaplayer.decision_publisher import DecisionPublisher
from mtgaplayer.live_performance import quantiles

ROOT=Path(__file__).resolve().parents[1]


def measure(samples, intents_only=False):
    def git(*args):return subprocess.check_output(['git',*args],cwd=ROOT,text=True).strip()
    paths=('src/mtgaplayer/decision_options.py','src/mtgaplayer/decision_consumer.py',
        'scripts/measure_decision_options.py')
    if intents_only: paths += ('src/mtgaplayer/action_intents.py',)
    code={'head':git('rev-parse','HEAD'),'tree':git('rev-parse','HEAD^{tree}'),
        'tracked_dirty':bool(git('status','--porcelain','--untracked-files=no')),
        'source_sha256':{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths}}
    fixture=ROOT/'tests/fixtures/player_log_single_target.jsonl'
    lines=fixture.read_bytes().splitlines(keepends=True)
    states={}
    with tempfile.TemporaryDirectory() as folder:
        path=Path(folder)/'public-prefix.jsonl'
        for cutoff in (103,106):
            path.write_bytes(b''.join(lines[:cutoff]))
            states['cast_'+str(cutoff)]=replay(path,format='player-log',decision_state_version=15)['decision_state']
    equip=ROOT/'tests/fixtures/current_target_revision_real_v14.json'
    public=json.loads(equip.read_text(encoding='utf8'))
    for name in ('before_parent','first_child','revised_child'):states['equip_'+name]=public[name]
    report={'code':code,'python':sys.version,'samples_per_case':samples,
        'inputs':'existing public Cast prefixes and portable Equip states; synthetic append transport/constant clock',
        'fixture_sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (fixture,equip)},
        'scope':'cold API: view copies, existing validators/generators, adaptation and final lease/ref check; warm API: cached data copies and both gates',
        'timing_note':'perf_counter_ns wall durations; no parsing inside timed loop; not additive stages or three-second game qualification',
        'input_sent':False,'P10':'NOT_RUN','cases':[]}
    if intents_only:
        report['scope']='MP70 assembly of already checked cached evidence, and cached opt-in API including Consumer gates; no re-enumeration'
    for name,state in states.items():
        state=copy.deepcopy(state);state['source'].update(mode='watch',phase='append',stopped=False)
        clock=lambda:1_000_000
        pub=DecisionPublisher(clock_ns=clock,session_id='synthetic-options-benchmark',
            state_version=int(state['schema_version'].rsplit('v',1)[1]))
        meta={'poll_started_ns':clock(),'poll_completed_ns':clock(),'poll_read_ns':0,'reducer_apply_ns':0,
            'decision_state_assembly_ns':0,'request_changed':True,'new_final_request':True}
        c=DecisionConsumer(clock_ns=clock)
        for event in pub.observe({'decision_state':state,'source':{'phase':'append','partial_record':False}},meta):
            if not c.accept_event(event):raise ValueError('benchmark_transport_invalid')
        expected=c.current_decision_options()
        if expected['status']!='partial' or not expected['options']:raise ValueError('benchmark_options_not_observed')
        times=({'intent_assembly_only':[],'same_snapshot_intent_api':[]} if intents_only
               else {'cold_api':[],'same_snapshot_cached_api':[]})
        if intents_only:
            from mtgaplayer.action_intents import assemble
            checked_state=c.current_view()['decision_state']; retained=c._decision_options_cache[2]
            expected_intents=assemble(checked_state,expected,retained)
        for _ in range(samples):
            # Force only the one data cache cold; Consumer/ref/lease stay real API checks.
            if not intents_only:c._decision_options_cache=None
            for stage in times:
                started=time.perf_counter_ns()
                if stage=='intent_assembly_only':value=assemble(checked_state,expected,retained)
                else:value=c.current_decision_options(include_complex_intents=intents_only)
                elapsed=time.perf_counter_ns()-started
                if intents_only:
                    if stage!='intent_assembly_only':value=value['complex_action_intents']
                    if value!=expected_intents:raise ValueError('benchmark_intents_changed')
                elif value!=expected:raise ValueError('benchmark_result_changed')
                times[stage].append(elapsed)
        report['cases'].append({'case':name,'returned_options':len(expected['options']),
            'engine_offered_count':expected['coverage']['engine_offered_count'],
            'raw_durations_ns':times,'latency_ms':{k:quantiles([n/1_000_000 for n in values]) for k,values in times.items()}})
        c.close('measurement_ended')
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--samples',type=int,default=30)
    parser.add_argument('--complex-action-intents-only',action='store_true',help='measure only MP70 assembly and cached opt-in API')
    parser.add_argument('--output',type=Path,default=ROOT/'artifacts/local-mp65/performance.json')
    args=parser.parse_args()
    if not 1<=args.samples<=1000:parser.error('samples must be1..1000')
    report=measure(args.samples,args.complex_action_intents_only);args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    print(json.dumps({'cases':len(report['cases']),'samples_per_case':args.samples,'output':str(args.output)}))
    return 0


if __name__=='__main__':raise SystemExit(main())
