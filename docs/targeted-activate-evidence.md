# MP52: targeted Activate evidence gap and minimum capture

Issue [#57](https://github.com/M0DIAN/MTGAPlayer/issues/57), initial audit outcome **B**.
This section records the initial tracked-fixture audit. A subsequent
[owner-local Equip recapture](targeted-activate-capture.md) supplies a genuine
continuous targeted Activate episode; its raw evidence and portable-export
limits are recorded separately. The original fixture inventory below remains
unchanged and does not include that private recapture.

Audited main: `26a571b26a4ff6880867cdf63f1f9758e3fd1e5e`, matching the issue's
accepted baseline. The retained evidence does **not establish an actual
target-bearing Activate followed by its target request, selection and result**.
The initial audit introduced no production linkage or synthetic positive chain.

The audit covers all ten tracked `tests/fixtures/*.jsonl` files (1,152 records),
the curated semantic exports, their provenance, and the existing reducer and
semantic checks. Private original logs/assets were not reread. This is a finding
about retained evidence, not proof that such an interaction never happened.
The adjacent [machine-readable inventory](targeted-activate-evidence.json) pins
the fixture contents and separates established facts from missing evidence.

## What the source establishes

| Evidence | Actual observation | Missing edge |
| --- | --- | --- |
| Generic2 Activate, fixture rows 1–10 | Full346, contiguous Diffs347–350; own request10002/state347 at row5; exact offered-row response at row6 selects **position3**, with no targets. Three successor states observe the corresponding public Ability, payment relations, resolution and deletion before request10006. | The six target-bearing positions **2,4,5,6,7,8** were not selected by this response. There is no SelectTargetsReq in this excerpt. |
| Same Generic2 request, prefix rows1–5 | MP49/51's existing observer reports six public target menus, counts **6,10,6,6,6,6**, with six consistent current source/ability pairs. | Offered parameters and pair consistency do not establish a chosen target, target quantity, future request, complete payment or acceptance. |
| Single-target fixture, rows103–113 | Actual **Cast position3** → public Stack spell → SelectTargets request10102/state101 → selection update → new request10104/state102 → final SubmitTargets → public submission/resolution observations. | Its parent is Cast. It cannot supply an Activate parent. The target's public departure does not establish Return causation. |
| Other retained raw excerpts | There are 13 PerformActionResp records: only three retain action bodies (one no-target Activate, two Cast); ten are header-only. Six SelectTargetsReq records occur: two full bodies in the Cast chain, four bodyless in the SelectN excerpt. | Header/type presence cannot establish a chosen targeted row or a causal chain. |
| Curated v9 PayCosts and v8 Search | Separately validated selection/sacrifice and Search/public transfer episodes; both READMEs cite the same original hash. PayCosts request source is null. | Neither retains the targeted Activate parent. Equal alias148 across separately curated files cannot authenticate their missing raw context. |

Raw fixture row numbers above are one-based; action positions are zero-based.
Their state/request/object numbers are sanitized fixture references, not IDs
that can be compared across captures. Original record-to-fixture mappings,
removed UI envelopes and alias namespaces are documented in
[THIRD_PARTY.md](../THIRD_PARTY.md) under MP39 and MP38. In particular, Generic2
retains original request3435/message1 and response3447; eleven intervening
UIMessage records contain no GRE state/semantic choice. The target fixture
retains actual Cast response3316, target request3318, update3333, new
request3334 and final submit3335. The later unrelated Ability request at
3337/message3 was excluded and cannot be attributed to that Cast or an Activate.

The curated [v9 provenance](../tests/fixtures/semantic_effect_cost_result_real_v9.README.md)
and [v8 provenance](../tests/fixtures/semantic_search_real_v8.README.md) each
retain one episode from 732 original records. Their reported source hash is
`4e888a7d29a9ac7f25c5d7aabc9517d5042c260d4065fa6c136e64ae45b616af`;
portable replay does not authenticate those removed bytes. The
[cross-request test](../tests/test_semantic_cross_request.py) explicitly labels
its composition synthetic. It is not additional real positive evidence.

## Smallest falsifiable future slice

After obtaining one genuine continuous capture, assess separately:
**offered-only**, **actual submission matched**, **explicit public relationship
observed**, **causality unknown**, and **invalid binding**. Do not collapse these
facts into a complete legal action or server acceptance.

Reuse [RawReducer](../src/mtgaplayer/raw_log.py), the
[current request/digest gate](../src/mtgaplayer/response_evidence.py), and the
[sample collector](../src/mtgaplayer/semantic_samples.py). The
[Activate checker](../src/mtgaplayer/semantic_activate.py) currently rejects
nonempty target parameters in its finite v5 action profile. The
[target linker](../src/mtgaplayer/semantic_targets.py) currently has a Cast-only
parent edge and requires complete visible endpoint equality across episodes.
These are implementation limits, not proof of illegal gameplay.

Baseline source checks: [v5 action restriction, lines19–25](https://github.com/M0DIAN/MTGAPlayer/blob/26a571b26a4ff6880867cdf63f1f9758e3fd1e5e/src/mtgaplayer/semantic_activate.py#L19-L25),
[actual-row equality, lines403–407](https://github.com/M0DIAN/MTGAPlayer/blob/26a571b26a4ff6880867cdf63f1f9758e3fd1e5e/src/mtgaplayer/semantic_activate.py#L403-L407),
and [endpoint/Cast linkage, lines351–371](https://github.com/M0DIAN/MTGAPlayer/blob/26a571b26a4ff6880867cdf63f1f9758e3fd1e5e/src/mtgaplayer/semantic_targets.py#L351-L371).

v5 and v9 are different finite assessments: v9 inherits the v4 literal/target
path and can retain the existing no-target Activate, but does not provide v5's
Activate ability/payment assessment. A v9 export is not a replacement v5
certificate. The existing target resolution check compares a spell's `card_id`
to annotation `grpid`; the v5 Ability endpoint has `card_id=null` and checks a
separate ability-group relation. A real targeted Ability resolution therefore
needs its own evidence review before reusing a Cast resolution conclusion.

Only controls that discriminate the implemented future rule should be added:
wrong generation/game/seat, supersession or changed request digest; wrong
source/ability pair; absent or discontinuous successor; private, duplicate or
ambiguous targets; wrong target slot; and a counterfactual row attempting to
borrow the actual selected row's result. No new linkage is implemented here,
so no invented targeted positive fixture or duplicate test modules are added.

## Minimum owner-local raw capture contract

Capture **one manually played interaction in one session** where the actual
submitted row is a target-bearing Activate. Keep the original stopped snapshot
private and immutable. Preserve actual order, including costs or other choices
between activation and target selection; no particular MTGA order is assumed.

1. Keep authentication/room evidence needed for the existing unique own-seat
   binding, the actual latest Full, and **every intervening state-changing GRE
   message, request and client response** through the result and next request
   (or observed end). Record original framed ordinals/message indices, byte
   count, SHA256, source generation/reset boundaries and producer code SHA.
   A gap/new Full can establish a new baseline, but cannot repair the lost edge.
2. Keep the complete active ActionsAvailable array and actual selected row:
   `actionType`, `instanceId`, `grpId`, `facetId`, `abilityGrpId`,
   `uniqueAbilityId`, flags and present cost/payment/target containers. Retain
   literal `targetIdx` and offered `targetInstanceId` relations. Preserve the
   current public Battlefield source's owner/controller, membership/visibility
   and **complete** `uniqueAbilities` list. Do not select just the matching pair.
3. Keep the actual PerformActionResp body plus `type`, `respId`, `gameStateId`;
   it must consume the same current own request and uniquely match the offered
   identity/parameters. Keep every intermediate PayCosts/other request and
   actual response. Temporal adjacency alone is not parent proof.
4. Keep each actual SelectTargetsReq header (`msgId`, `gameStateId`,
   `systemSeatIds`) and body: `sourceId`, `abilityGrpId`, `targetIdx`,
   `targetingAbilityGrpId`, `targetingPlayer`, bounds/selected count **only when
   present**, and the complete Select/Unselect entries. Keep actual
   SelectTargetsResp increments, re-presented requests and final
   SubmitTargetsReq, including header-only submits. Top-level ability group,
   targeting ability group, Card group and unique ability are distinct
   namespaces. Missing minima/selected counts remain unknown.
5. Keep the first continuous public successor and subsequent relevant states,
   explicit public Ability `parentId`/group and creation annotation where
   present, PlayerSubmittedTargets and resolution/result annotations, object
   migration/deletion and visible endpoints. Record the source/target relationship
   actually published. Do not require an Ability to appear before a target
   request if the source orders it otherwise. Missing parent/group or explicit
   target consequence leaves that relation unknown, even with a valid submission.

For the smallest existing target profile, a source must be uniquely visible on
Stack and candidates on public Battlefield, with one target slot. If the real
capture differs, retain the raw shape locally for review; do not alter it to
fit the profile. Hidden identities must not be recovered or promoted to public.
Selection cardinality, modes/X and additional costs come only from explicit
source evidence. An observed public consequence alone is not server acceptance
or proof that the selected target caused it.

Raw account/authentication values, hidden card identities, credentials, prompts,
UI/chat metadata, timestamps and screenshots remain local/ignored. A shareable
fixture must use consistent scoped aliases and an explicit field allowlist,
retain every necessary state/choice relation, and include its local original
ordinal/hash mapping. Do not splice excerpts, fabricate Full states, convert an
unchosen row into the response, merge alias tables, or infer omitted values.
Sanitized replay checks internal consistency; it cannot reauthenticate the
private original. Review public annotations before sharing them, too.

From the repository root, on the **same immutable private snapshot**, use
distinct new private output files (the exporter refuses overwrites):

```powershell
$capturePath = '<private stopped Player.log snapshot>'
$v5Path = '<new private Activate v5.json>'
$v9Path = '<new private targets and costs v9.json>'
Get-FileHash -Algorithm SHA256 -LiteralPath $capturePath
(Get-Item -LiteralPath $capturePath).Length
.\.venv\Scripts\python.exe -m mtgaplayer export-semantic-samples $capturePath --schema-version 5 --max-samples 256 --output $v5Path
.\.venv\Scripts\python.exe -m mtgaplayer replay-semantic-samples $v5Path
.\.venv\Scripts\python.exe -m mtgaplayer export-semantic-samples $capturePath --schema-version 9 --max-samples 256 --output $v9Path
.\.venv\Scripts\python.exe -m mtgaplayer replay-semantic-samples $v9Path
Get-FileHash -Algorithm SHA256 -LiteralPath $capturePath
(Get-Item -LiteralPath $capturePath).Length
```

Keep these outputs private pending the field/provenance review above. These
commands send no game input. Export limits, unsupported pairs and profile
differences mean **absence from an export is not absence from the raw log**.
Inspect the original contiguous segment with the existing reducer before
deciding whether a targeted slice is implementable. Stop if the source changed,
framing is partial, relevant pairs were omitted, or scope/continuity is unknown.

## Reproduce the retained-evidence findings

Run the following Python from the repository root using project Python 3.11.
It uses existing framing, reducer, menu and sample APIs; it creates no files.
Fingerprints normalize CRLF to LF, matching Git fixture bytes across platforms.

```python
import hashlib
import json
from pathlib import Path
from mtgaplayer.raw_log import RawFollower, RawReducer
from mtgaplayer.action_target_menus import TargetMenuObserver
from mtgaplayer.semantic_samples import collect_samples, replay_samples

root = Path('tests/fixtures')
manifest = json.loads(Path('docs/targeted-activate-evidence.json').read_text())
assert {p.name for p in root.glob('*.jsonl')} == set(manifest['raw_fixtures'])
records = {}
for name, expected in manifest['raw_fixtures'].items():
    path = root / name
    data = path.read_bytes().replace(b'\r\n', b'\n')
    assert len(data) == expected['lf_bytes']
    assert hashlib.sha256(data).hexdigest() == expected['lf_sha256']
    follower = RawFollower(path)
    _, rows = follower.poll()
    assert follower.framer.errors == 0 and not follower.framer.partial
    assert len(rows) == expected['records']
    records[name] = rows
assert sum(map(len, records.values())) == manifest['total_raw_records']
payloads = [r.get('payload', {}) for rows in records.values() for r in rows]
responses = [p for p in payloads if p.get('type') == 'ClientMessageType_PerformActionResp']
assert len(responses) == 13
assert sum('performActionResp' in p for p in responses) == 3

name = 'player_log_activate_generic_two.jsonl'
reducer = RawReducer()
reducer.reset(1)
observer = TargetMenuObserver()
for row in records[name][:5]:
    reducer.apply(row)
    observer.observe(reducer, row)
menu = observer.current(reducer)
assert [m['list_position'] for m in menu['menus']] == [2, 4, 5, 6, 7, 8]
assert [m['offered_visible_target_count'] for m in menu['menus']] == [6, 10, 6, 6, 6, 6]
assert menu['verified_source_ability_menu_rows'] == 6
doc = collect_samples(root / name, schema_version=5, max_samples=256)
report = replay_samples(doc)
assert doc['counts'] == dict(matched_pairs=1, exported=1, sample_limit_omissions=0, unsupported_pairs=0)
assert report['samples'][0]['selected_action_position'] == 3
assert doc['samples'][0]['response']['payload']['action']['action_type'] == 'ActionType_Activate'
assert not doc['samples'][0]['response']['payload']['action']['parameters'].get('targets')
assert len(doc['samples'][0]['trace']['states']) == 3
assert report['samples'][0]['trace_status'] == 'next_request_observed'

doc = collect_samples(root / 'player_log_single_target.jsonl', schema_version=4, max_samples=256)
report = replay_samples(doc)
assert doc['counts'] == dict(matched_pairs=3, exported=3, sample_limit_omissions=0, unsupported_pairs=0)
assert doc['samples'][0]['response']['payload']['action']['action_type'] == 'ActionType_Cast'
assert report['samples'][0]['selected_action_position'] == 3
last = report['samples'][-1]['target_evidence']
assert all(last[k] for k in ('linked_cast_origin', 'linked_previous_actual_selection',
    'final_submission_observed', 'targets_submitted_annotation_observed', 'source_resolution_observed'))
assert last['return_causation'] == 'unverified'
for name in ('semantic_effect_cost_result_real_v9.json', 'semantic_search_real_v8.json'):
    doc = json.loads((root / name).read_text())
    assert replay_samples(doc)['artifact_checks_passed']
    assert len(doc['samples']) == 1
assert manifest['delivery'] == 'B_evidence_gap_and_capture_contract'
assert not any(manifest['authority'].values())
print('MP52 initial retained-fixture checks passed; those fixtures do not establish a targeted Activate chain')
```

The genuine owner-local capture now supplies the opt-in v10
[portable fixture and finite linkage](../tests/fixtures/semantic_activate_targets_real_v10.README.md).
The initial tracked-fixture findings above remain historical. Complete
legality, response encoding, server acceptance, execution and real-action
latency remain unverified; input is false and **P10 remains NOT_RUN**.
