# Historical target-stage completion (MP73)

```text
mtgaplayer evaluate-shadow-history OWNER_SELECTED_LOG --target-stage-completions
```

This explicit historical simulation adds count-only stage evidence to the
existing MP68 report. Default reports, MP65 candidates, MP66 preferences and
State/Event1–15 / Candidate2–6 contracts remain unchanged. It never grants
current Submit permission, encodes a response or sends input.

## Existing capability and the actual addition

MP38 already checks current Select membership/counts; MP54 checks the selected
literal of a public Stack Ability. MP62/63/64 already observe first selection,
request consumption and finite continuation. The existing offline semantic
sample profiles (including schema4 and10) already recognize historical final
submissions. Repackaging those observations is not a new target solver.

The missing piece was a bounded connection between a **previously frozen MP66
full-set preference** and the independently revised request's actual terminal
submission. The existing `RevisionStage.client_submit_observed` is reused.
The same observer now optionally retains one frozen first-stage context through
the strict update, one Diff, independently checked revision and consumed Submit.
There is no second reducer, file reader, persistent request ledger or target
combination enumeration.

The Ability path keeps its original checks and State14 representation. An
explicit separate finite Card path checks public Stack Card identity and the
same public target identity. It accepts absent prompts only when actually
absent; present prompts still pass the original representation checker.
It does not pretend the Ability-only selected-set validator passed, serialize
Card data into State14 or prove a parent Cast's origin. This new relationship
begins at the authenticated current target request.

## Real chains and freeze boundaries

The retained public Cast fixture is read only through106 before107 is opened.
At106, request10102/state101 has four current Select members, min/max1/1 and no
selected count. Four complete **local** singleton proposals compete; MP66
abstains. At107 the exact Select update consumes10102. At108 the single typed
Diff102←101 preserves tracked public identities. At109, independent
request10104/state102 has one Unselect1262, min/max/selected1. This is109's own
selected literal, not106's current domain. Only110's exact header-only Submit,
paired with and consuming109, produces
`historical_reviewed_target_set_submitted`. No policy comparison is possible
for this public chain because106 abstained.

The owner authenticates both frozen originals before and after evaluation.
Equip1422 freezes its unique locally reviewed proposal,1424 consumes the actual
selection update,1425 independently verifies the Ability selected literal and
1426 pairs/consumes its terminal Submit. The policy sequence remains
research_preference → expired → abstain → expired. Neither1425 nor earlier
states borrow1426's future evidence. Reviewers inspect public fixtures, code
and the [safe receipt](evidence/mp73-target-stages.safe.json); they do not claim
personal authentication of private original bytes.

Public Cast106 prefix:63,805 bytes with original CRLF,
SHA256 `e8cc76d8b2803ca4cb1e4b7abd3522d25533c6b668a173dd628b52b9bc57fb89`.
Source hashes and owner Equip cutoff hashes are retained in the safe receipt.

## Actual28-request census and units

The same two owner sources have164 unique authenticated own requests with no
identity overlap;28 are SelectTargets. Counts below overlap and cannot be added.

| Frozen current evidence | Requests |
|---|---:|
| Supported complete current Select domain |4|
| Exactly one locally reviewed complete proposal |2|
| Multiple competing locally reviewed complete proposals |2|
| Supported selected literal / only Unselect; current Select domain absent |12|
| Request-parameter projection unavailable; current domain unknown |12|
| Explicit min/max in the supported projection |16|
| Explicit selected count in the supported projection |12|
| Returned locally reviewed options (including literal probes) |13|

The original17 `multiple_or_unresolved_target_choices` reasons actually split
into12 unprojected requests,3 Card selected-literal requests without old current
probes and only2 competing complete local domains. The other9 selected-only
requests are Ability probes with `selected_literal_or_probe_is_not_a_final_proposal`.
The2 unique proposals retain research preferences: **2/164**, unchanged.
None of this proves complete MTG target or action legality.

An additional owner-only raw shape census checks the12 unprojected requests
without inventing a second semantic projection. All12 have one nonempty raw
slot and integer min/max;10 have only Select entries and2 only Unselect entries
with integer selected count. Thus raw lists exist beyond the supported domain:
14 raw Select requests and14 raw Unselect requests overall,28 with integer
min/max and14 with integer selected count. These are **field observations**,
not12 additional verified current domains or selected-set identities. The
opt-in report's classification/quantity fields count the supported projection;
`request_parameters_unavailable=12` keeps the remaining semantics unknown.

| History evidence | Count / unit |
|---|---|
| Paired selection-response envelopes |14 submissions|
| Strictly reviewed single Select updates |4 submissions|
| Other paired, unreviewed selection shapes |10 submissions|
| Independently verified revised stages |4 requests|
| Strict header-only paired terminal Submits |14 submissions|
| Linked reviewed historical submitted sets |4 episodes (3 Card,1 Ability)|
| Comparable frozen complete-set preferences |2 completed episodes|
| Historical target agreements / disagreements |2 /0 comparable episodes|
| Uncomparable reviewed first-stage attempts |2 of4 attempts|
| Reviewed first-stage attempts missing a verified terminal |0 of4 attempts|
| Terminal Submits without a reviewed linked episode |10 submissions|
| Selected-literal requests without verified revision |8 requests|
| Number of additional unlinked episodes |null (not reconstructed)|

`uncomparable_target_episodes` uses the four supported first-stage Select
attempts as its denominator; it does **not** mean that every other terminal is
comparable. Unlinked selected requests are not silently grouped into invented
episodes. Agreement is equality under the reviewed finite single-slot semantics,
not correctness, optimality, server acceptance or legal-action accuracy.

## Strict comparison and invalidation

The first preference must predate the update and refer to the same request,
snapshot, option key and complete locally verified single-slot proposal. Actual
selection must pass the existing response checker and post-consumption pairing.
One typed contiguous Diff must preserve source/selected identities, without a
tracked migration annotation. The independently current revision must match
source, group, slot, seat, quantity and the actual Unselect literal. Its snapshot
must be frozen before terminal Submit. The terminal has exactly the reviewed
three header fields and must consume that revised request in the same scope.

Wrong slots, duplicate/deleted/replaced targets, mixed Select/Unselect, wrong
response/header/seat, typed predecessor confusion, source type changes,
contradictory migrations, duplicate Diff (including same-record batching),
same-episode consumed target-request retransmission, gaps, Full/reset, partial, Cancel/Undo, scope
changes and unfinished EOF withhold comparison. The new batch check is bounded
to256 messages and linear with typed state-ID membership. A completed historical
count never resurrects a current request or preference.

Tests explicitly label synthetic mutations and Equip bootstrap as plumbing or
counterexamples; they are not additional real MTGA positives. The real public
Cast positive and owner-authenticated Equip receipt supply the positive evidence.

## Added-only cost and remaining gaps

One bounded owner run measured only the existing RevisionStage's opt-in work
plus the new classification/comparison, not a repeated whole-pipeline benchmark:

| Source | n records | p50 ms | p95 ms | p99 ms | max ms |
|---|---:|---:|---:|---:|---:|
| Frozen Equip |1433|0.0053|0.6123|2.4781|3.9805|
| Existing player |1490|0.0044|0.4957|2.0907|4.4066|

These nested same-process offline timings overlap existing stages; they are not
actual MTGA latency or a three-second qualification. Data stays bounded to one
stage, ≤64 first members and the existing64-record pending age.

The12 unprojected requests,10 unlinked terminal Submits, general multi-slot/
quantity/retarget behavior and complete target/effect/payment rules remain
unverified. Historical Windows qualification failure root cause remains
**UNKNOWN**; passing later checks is not proof it was fixed.

`input_sent=false`; `P10=NOT_RUN`.
