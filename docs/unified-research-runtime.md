# Unified local research runtime

`unified_research.v1` is an explicit `LocalShadowRuntime` mode. The accepted
MP89 runtime accepted only one optional land or target policy and one reference;
there was no equivalent request-routed interface. This mode uses the existing
single owner, RawFollower, RawReducer, Publisher, Consumer and completed-poll
DecisionFrame. It adds no game state, request ledger, parser, result cache,
solver, response encoder or network/LLM dependency.

Prepare both detached references **before** starting the runtime:

```python
from mtgaplayer.rules_index import (
    prepare_mtga_land_reference, prepare_mtga_target_effect_reference,
)
from mtgaplayer.shadow_runtime import LocalShadowRuntime

source = {
    "expected_sha256": "1be0105411ad989ca60e233f1341eaaa9276e3a679c89f1ef6f07e07ede10d25",
    "expected_source_version": {"Data": "2026.64.0.280", "GRP": "280.1327372"},
}
land = prepare_mtga_land_reference(
    local_catalog_path, [92359, 92360, 95062, 96839], **source,
)
target = prepare_mtga_target_effect_reference(
    local_catalog_path, [90673, 96854], **source,
)
runtime = LocalShadowRuntime(
    player_log_path,
    research_policy="unified_research.v1",
    prepared_references={"land": land, "target_effect": target},
)
for frame in runtime.frames():
    decision = frame["unified_research_decision"]
    # Research observation only. Requery runtime.current_frame() for freshness.
```

The original `research_policy=None`, `land_development_research.v1` and
`target_effect_research.v1` plus `prepared_rules` APIs retain their behavior.
`prepared_references` is confined to unified mode, accepts only the two named
PreparedRulesIndex entries, and cannot be mixed with `prepared_rules`. Missing
entries are allowed: the applicable policy abstains using its own evidence gate.
Passing a different reference format does not authorize its use. Each reference
retains its independent source schema, format, SHA256, Data/GRP and reviewed scope.
Hot lookup performs no filesystem/SQLite I/O. Installed resources are not runtime
dependencies of default operation or public CI.

## Routing and arbitration

The unchanged `shadow_decision` always contains the MP66 result. ActionsAvailable
routes the same current frame to MP87; SelectTargets routes it to MP89. Its full
original detail is available as `research_decision`. Other request types use MP66
without calling unrelated specialist policies. The final, single result is
`unified_research_decision`, with policy version, selected policy, binding/ref,
candidate namespace/key, basis, evidence level, validation scope and unresolved
constraints. Legacy specialist abstentions can have null detail bindings under
their existing contracts; these cannot authorize a preference. The final current
unified report remains bound to the enclosing frame.

A valid original MP66 preference may survive specialist abstention/unsupported,
with its original weaker evidence and scope. It never acquires effect evidence.
Simultaneous preferences must identify one identical full current candidate in
the same namespace; matching positions or numbers across inventories is not
identity. Different verified candidates produce conflict abstention, without
policy-order, card, seat, position or historical-choice ranking. Missing,
ambiguous or unverified candidate identity revokes the entire frame. Reports that
fail global request/ref/lease checks invalidate the entire frame rather than
falling back. The arbiter is bounded by existing candidate limits.

The MP89 exact-build resource capability is retained. Unified land routing also
requires it, so a new/unknown client-resource version cannot inherit the old
catalog's land capability. This additional gate is confined to unified mode;
MP87's original single-policy contract is unchanged. The exact reviewed build
is `2026.64.0.14517.1329972`. See
[the MP89 provenance chain and its limitations](target-effect-research.md).

Current request/digest/match/game/seat/snapshot/ref/lease, original completed-poll
witness, visible state and resource capability are checked before and after work.
Consumption, replacement, partial, Full/reset, continuity gaps, Cancel/Undo,
expiry, stop and mid-computation changes revoke the entire result. No last_valid
or prior policy report restores it. Returned dictionaries describe their original
poll; they are never execution capabilities. `safe_summary` omits local identities,
payloads, references and candidate keys using bounded positive whitelists.

## Actual controlled historical validation

The owner reauthenticated the MP81 archive: 3,225,997 bytes, SHA256
`1d75cd1b65ac868da1e9e0025032c7380317fcbf8669016a00fcb536e44a73ac`,
367 records, 53 authenticated requests and the original 42 distinct endpoints.
Each of A/default, B/land, C/target and D/unified ran its own single production
Runtime, with exactly one RawFollower, RawReducer and Publisher/Consumer
subscription. D is an actual unified run, not a sum of old reports.

An authentic complete, valid, requestless prefix after an earlier consumed
transient request supplies the controlled replay warmup before the first frozen
Mulligan endpoint. All 42 subsequent completed polls end at the original byte
cutoffs and exactly match the original request bindings and accepted digests.
No intra-poll transient request or later record is exposed. This permits all42
offline endpoint evaluations without weakening the history fence. The original
startup arrangement (one history request plus41 append frames) is separately
preserved in default compatibility checks. Neither arrangement proves historical
wall-clock leases or creates real live MTGA opportunities.

| Actual population | preference | abstain | unsupported |
|---|---:|---:|---:|
| MP66, all42 |1|33|8|
| MP87,13 ActionsAvailable |1|12|0|
| MP89,14 SelectTargets |9|4|1|
| Unified, all42 |11|23|8|

The11 distinct unified preferences have sources MP66=1, MP87=1, MP89=9.
SelectTargets has10 unified preferences: nine effect preferences and the original
weaker MP66 Card-domain preference. That fallback does not become an effect claim.
Real conflicts=0. All A/B/C full per-request results match accepted main, including
static source versions/hashes; routed specialist details and MP66 outputs inside
D match their originals. Forty-one strictly consumed frozen requests immediately
lose their old result; the stopped runtime also returns only expired/no key.
Synthetic controls separately exercise conflicts and lifecycle interruptions.
No historical player choice is a policy input or arbitration label.

## Cost and engineering evidence

The companion [owner receipt](evidence/mp90-owner.json) records actual tests,
full-value compatibility and measured per-type quantiles. `unified_dispatch`
measures routing and bounded arbitration excluding specialist computation;
`research_policy` measures only the applicable specialist. Other requests have
no specialist sample, represented by n=0/null quantiles. Poll→frame includes
nested stages and must not be added to them. Failed/revoked polls and immediate
revocation calls have separate populations. References are prepared before the
Consumer; preparation is excluded from every hot-path metric.

Full Python3.11 tests, Windows doctor, independent exact candidate review, actual
Linux/Windows CI and natural main CI are separate delivery gates. Final identities
and post-merge results belong to the PR delivery receipt. No timing is a real
MTGA three-second qualification. Existing unknown historical AutoTap, Windows
qualification and MP81 current_view_unavailable causes remain unchanged.

No new effect category, tactical score or legality rule was added.
`complete_legality_verified=false`; `strategic_optimality_verified=false`;
`execution_ready=false`; `input_sent=false`; `P10=NOT_RUN`.

## MP93: explicit Unified v2

`unified_research.v2` is a separate opt-in composition of MP66,
`land_development_research.v2` (MP92) and `target_effect_research.v1` (MP89).
ActionsAvailable dispatches to Land v2; SelectTargets still dispatches to Target
Effect v1; other requests retain MP66. It extends the same runtime and
`combine_current_research`, with a strict allowlist of version mappings. The
decision envelope remains `mtgaplayer.unified-research-decision.v1`; its explicit
`policy_version` distinguishes the composition. No State/Event/Candidate version,
strategy algorithm, state, request ledger or cached preference is added.

```python
# Prepare outside the hot path, with the same pinned source arguments above.
land_v2 = prepare_mtga_land_reference(
    local_catalog_path,
    [92359, 92360, 95062, 96839, 96828, 106531, 106533],
    **source,
)
runtime = LocalShadowRuntime(
    player_log_path,
    research_policy="unified_research.v2",
    prepared_references={"land": land_v2, "target_effect": target},
)
```

The expanded detached land reference includes MP92's reviewed Basic Swamp.
It does not make nonbasic lands or multiple competing Play actions eligible.
Missing/wrong references retain their evidence refusal. The original default,
both standalone land versions, standalone target policy and Unified v1 retain
their complete behavior. In particular, Unified v1 always routes Land v1, even
if supplied an expanded reference. Passing a Land v2 report to the v1 arbiter,
or a Land v1 report to the v2 arbiter, is rejected. The optional keyword on
`combine_current_research` defaults to v1 for existing callers.

All arbitration, candidate namespaces, binding/ref/lease and completed-poll
checks above are shared. Conflicting candidates still abstain; MP66 fallback
retains its weaker evidence. Invalid/history/stopped/foreign-owner frames also
return the selected unified version's expired result, without a candidate key.
The safe summary explicitly recognizes only the two allowed compositions and
their respective specialist versions.

### Actual original-byte replay

The owner reverified both complete MP77 archives and their snapshots before
running the formal Runtime. MP91 has 8,382,052 bytes, SHA256
`aa5cafb94467184c013539651a619a6101292e2cdf7225e619246aac16ea2e5b`,
789 contiguous segments, 1,844 records and 93 authenticated requests. All 3,348
original completed-poll cutoffs were replayed, including the original 50 first
current endpoints with exact bindings, accepted digests and completed stamps.
MP81 uses the 3,225,997-byte archive above, 217 contiguous segments, 367 records
and 53 authenticated requests, with its authentic requestless warmup and 42
original endpoints. Neither source has a partial tail, framing error or rotation
gap. Original evidence remained unchanged after replay.

Each mode runs a single production Runtime, Follower and Reducer under one owner.
MP91's original inactivity schedule requires 32 successive Publisher/Consumer
subscriptions through the existing stale-terminal lifecycle; it does not create
parallel state or a second owner. MP81 uses one subscription. Results are frozen
before later bytes are appended; saved frames are diagnostic outputs only.

| Cohort / actual population | preference | abstain | unsupported |
|---|---:|---:|---:|
| MP91 Unified v1, all50 |0|41|9|
| MP91 standalone Land v2,24 ActionsAvailable |1|23|0|
| MP91 Unified v2, all50 |1|40|9|
| MP81 Unified v1, all42 |11|23|8|
| MP81 Unified v2, all42 |11|23|8|

Only MP91 opportunity42 gains a unified preference, for the existing MP92
Swamp proposal. The other49 gain none. All24 routed Land v2 detailed reports
match standalone Land v2, and all4 target reports match the original target
policy. MP81 gains no invented distinction. Real policy conflicts are zero.
MP91's50 and MP81's41 strictly consumed frozen requests each immediately revoke
the old result, with no revival; stop also revokes. Synthetic tests separately
exercise conflict, wrong namespaces/versions/references, mid-computation changes,
partial/reset/gap, Cancel/Undo, replacement and lease/owner failures.

Accepted-base versus candidate replay compares all five original modes on both
cohorts: 460 endpoint-mode frames and their matching-code safe summaries,
571,872 frame leaf values plus 23,494 summary leaf values, zero differences.
Canonical JSON comparison preserves types, source versions/hashes, ref bindings,
evidence and constraints; only random snapshot transport session/sequence and
actual timings are excluded. Original modes use identical reference inputs on
base and candidate; Unified v1 retains its original four-card land reference.
The expanded seven-card reference belongs to standalone Land v2 / Unified v2.
The original MP91 v1 freezes also match all50 four-component reports (50,816
leaf values). One already-expired empty poll retains a reason-only difference
under the offline logical clock; both scopes remain expired. No historical
subpoll wall-clock lease claim is made.

### Bounded local timing evidence

The [MP93 owner receipt](evidence/mp93-owner.json) retains n/p50/p95/p99/max for
v2 dispatch, actual Land v2 computation, full poll-to-frame and immediate
consumption queries, separately by cohort/family. A separate real-clock pass
uses the same raw bytes through warmup, original first-current endpoints and
tail, rather than repeating the live empty-poll schedule. Startup/history and
tail are separate from current frames. Prepared references are excluded. Nested
stages overlap and must not be added. These are controlled local replay samples,
not new MTGA field measurements or proof of a three-second closed loop. Test
processes were also active on the host; no isolated benchmark claim is made.

MP91's original 2,814 aggregate revocation timings still have no recoverable
per-family/history/terminal classification. New offline measurements cannot
backfill them. Historical `current_view_unavailable`, Windows qualification and
AutoTap evidence gaps retain their prior status. Input, response encoding,
complete legality and strategic optimality remain unverified/disabled.
