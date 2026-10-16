"""Observed Activate target menus from real GRE prefix, with synthetic refusals."""
import copy
import json
import tempfile
import unittest
import subprocess
import sys
from pathlib import Path
from mtgaplayer.cli import replay,watch
from mtgaplayer.raw_log import RawReducer
from mtgaplayer.action_target_menus import TargetMenuObserver,VERSION

SOURCE=Path(__file__).parent/'fixtures/player_log_activate_generic_two.jsonl'


class TargetMenuTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.path=Path(tmp.name)/'source.log'
        self.rows=[json.loads(s) for s in SOURCE.read_text().splitlines()]
        self.write(self.rows[:5])

    def write(self,rows):
        self.path.write_text(''.join(json.dumps(x)+'\n' for x in rows))

    def inspect(self,rows=None):
        if rows is not None:self.write(rows)
        return replay(self.path,format='player-log',observed_action_target_menus=True)

    def target(self,rows):
        return rows[4]['greToClientEvent']['greToClientMessages'][0][
            'actionsAvailableReq']['actions'][2]['targets'][0]['targets']

    def test_true_current_request_has_six_bounded_visible_target_menus(self):
        d=self.inspect();r=d['observed_action_target_menus']
        self.assertEqual(r['schema_version'],VERSION)
        self.assertEqual(r['status'],'observed_public_target_menus')
        self.assertEqual([r[k] for k in ('engine_active_action_rows',
            'target_bearing_action_rows','reviewed_public_menu_rows','withheld_target_rows')],
            [20,6,6,0])
        self.assertEqual([x['list_position'] for x in r['menus']],[2,4,5,6,7,8])
        self.assertEqual([x['offered_visible_target_count'] for x in r['menus']],[6,10,6,6,6,6])
        objects={obj['id']:obj for obj in d['current']['objects']}
        for menu in r['menus']:
            self.assertTrue(all(objects[x]['zone']=='ZoneType_Battlefield'
                                for x in menu['offered_visible_target_refs']))
            self.assertIsNone(menu['selection_count'])
            self.assertFalse(menu['target_selection_legality_verified'])
        self.assertEqual(r['request_id'],d['current']['request']['id'])
        for key in ('target_minimum_verified','target_maximum_verified',
                    'target_domain_complete_verified','target_selection_legal_verified',
                    'complete_payment_verified','complete_legality_verified',
                    'server_acceptance_verified','response_encoding_verified',
                    'historical_response_used','input_sent'):
            self.assertFalse(r[key],key)

    def test_malformed_hidden_duplicate_and_private_fields_withhold_entire_row(self):
        for typ in ('private','unknown','duplicate','too_many'):
            with self.subTest(typ=typ):
                rows=copy.deepcopy(self.rows[:5])
                targets=self.target(rows)
                if typ=='private':targets[0]['secret']='PRIVATE_SENTINEL'
                elif typ=='unknown':targets[0]['targetInstanceId']=987654321
                elif typ=='duplicate':targets.append(copy.deepcopy(targets[0]))
                else:targets.extend(copy.deepcopy(targets[0]) for _ in range(65))
                report=self.inspect(rows)['observed_action_target_menus']
                self.assertEqual((report['target_bearing_action_rows'],
                                  report['reviewed_public_menu_rows'],
                                  report['withheld_target_rows']),(6,5,1))
                self.assertNotIn(2,[x['list_position'] for x in report['menus']])
                self.assertNotIn('PRIVATE_SENTINEL',json.dumps(report))
                self.assertNotIn('987654321',json.dumps(report))

    def test_response_and_later_request_never_revive_prior_menu(self):
        r=self.inspect(self.rows[:6])['observed_action_target_menus']
        self.assertEqual(r['status'],'insufficient_evidence')
        self.assertEqual(r['menus'],[])
        later=self.inspect(self.rows)['observed_action_target_menus']
        self.assertNotEqual(later['request_id'],10002)
        self.assertFalse(later['input_sent'])

    def test_unfinished_record_disables_even_previously_seen_menu(self):
        with self.path.open('a') as out:out.write('{"greToClientEvent":')
        d=self.inspect()
        self.assertEqual(d['observed_action_target_menus']['reason'],'source_framing_incomplete')
        self.assertEqual(d['observed_action_target_menus']['menus'],[])
        self.assertFalse(d['current']['valid'])

    def test_request_content_digest_must_match_accepted_request(self):
        reducer=RawReducer();reducer.reset(1)
        for x in self.rows[:5]:reducer.apply(x)
        observer=TargetMenuObserver()
        # Both wrong headers and same-header changed nested content must
        # fail against RawReducer's accepted request digest ledger.
        for mode in ('wrong_header','same_header_changed_body'):
            changed=copy.deepcopy(self.rows[4])
            request=changed['greToClientEvent']['greToClientMessages'][0]
            if mode=='wrong_header':
                request['msgId']+=5
            else:
                request['actionsAvailableReq']['actions'][2][
                    'targets'][0]['targets'][0]['targetInstanceId']+=1
            observer.observe(reducer,changed)
            self.assertEqual(observer.current(reducer)['menus'],[],mode)
        observer.observe(reducer,self.rows[4])
        self.assertEqual(len(observer.current(reducer)['menus']),6)


    def test_real_cli_replay_and_finite_watch_opt_in_only(self):
        cmd=[sys.executable,'-m','mtgaplayer']
        replay_run=subprocess.run([*cmd,'replay',str(self.path),
            '--format','player-log','--observed-action-target-menus'],
            capture_output=True,text=True,timeout=20)
        self.assertEqual(replay_run.returncode,0,replay_run.stderr)
        report=json.loads(replay_run.stdout)['observed_action_target_menus']
        self.assertEqual(report['reviewed_public_menu_rows'],6)
        self.assertFalse(report['input_sent'])
        watch_run=subprocess.run([*cmd,'watch',str(self.path),'--samples','1',
            '--interval','.01','--observed-action-target-menus'],
            capture_output=True,text=True,timeout=20)
        self.assertEqual(watch_run.returncode,0,watch_run.stderr)
        report=json.loads(watch_run.stdout.splitlines()[0])['observed_action_target_menus']
        self.assertEqual(report['reviewed_public_menu_rows'],6)
        self.assertFalse(report['input_sent'])
        refused=subprocess.run([*cmd,'replay',str(self.path),
            '--observed-action-target-menus'],capture_output=True,text=True,timeout=20)
        self.assertNotEqual(refused.returncode,0)

    def test_default_replay_and_watch_values_stay_unchanged(self):
        default=replay(self.path,format='player-log')
        observed=self.inspect()
        self.assertEqual(default,{k:v for k,v in observed.items()
                                  if k!='observed_action_target_menus'})
        old=list(watch(self.path,interval=0,samples=1))
        extra=list(watch(self.path,interval=0,samples=1,
                         observed_action_target_menus=True))
        self.assertEqual(old[0],{k:v for k,v in extra[0].items()
                                  if k!='observed_action_target_menus'})
        self.assertEqual(extra[0]['observed_action_target_menus']['reviewed_public_menu_rows'],6)
        self.assertFalse(extra[0]['source']['input_sent'])
