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
