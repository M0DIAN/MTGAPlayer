# Historical shadow evaluation (MP68)

`mtgaplayer evaluate-shadow-history <explicit-local-file>` returns a bounded,
anonymous historical summary. It never opens a game or produces input. The
versioned report is `mtgaplayer.shadow-history-evaluation.v1`; existing
State/Event1–15 and all policy/option/candidate contracts remain unchanged.

## Reuse and order

The existing `inspect_actions.py --response-choice-correlation` and
`--complex-response-choice-correlation` associate consumed historical responses
with offered action identities. `--gap-coverage` counts structural coverage.
None freezes MP66 choices. Their poll/record final snapshots can miss a request
that is consumed or replaced later in the same batch. MP68 therefore uses the
existing RawFramer/RawReducer accepted-request callback and CLI projections,
StageObserver, Publisher, Consumer, MP65 and unchanged MP66 policy. It does not
add a GRE parser, rules checker, strategy algorithm or second reducer.

At each authenticated current request callback, before another GRE message is
applied, the evaluator publishes a simulated current snapshot, obtains options,
calls the existing shadow API and freezes detached data privately. After later
records it uses ResponseEvidence's current-own and post-consumption gates plus
the existing simple/complex correlators. A mixed response/GRE envelope cannot
enter comparison. Duplicate requests/responses do not create extra samples.
Every record drives existing current-state revocation; a revoked ref cannot
remain current. EOF/partial/limit/stop also withdraw live-view data.

Internal watch/append event metadata is a controlled simulation required by the
current Consumer. It is not a real MTGA opportunity. The output explicitly says
`historical_simulation` and `live_decision_opportunity=false`. The local clock is
logical, not inferred historical elapsed time or server freshness. No event,
snapshot, binding, option key, raw payload or private identifier is exported.

## Units and comparison

`observed_requests` means unique authenticated current own requests at their
first accepted observation. It is not a count of records, offered actions,
target members, every UI choice or requests rejected before a valid baseline.
`evaluable=research_preferences+abstentions`; `observed=evaluable+unsupported+
invalid_or_incomplete`. `expired_or_consumed` is an overlapping lifecycle count,
not an additional partition. Zero observed requests gives null rates, not proof
that the source contained no game choices. Framing completeness does not prove
continuous semantic acceptance of every record; continuity errors are separate.

`abstention_reasons` contains actual abstain reason codes only. `policy_reasons`
also includes preferences/unsupported results. Additional unresolved labels and
action-category counts are multi-label request counts, not causal attribution.
Existing authenticated inventory type labels remain observable even when the
Advisor withholds all engine options because request fields are uninterpreted.
An unknown inventory never implies an empty legal-action domain.

Historical choices count strictly paired reducer-consumed submissions, including
member updates. Unique complex identity is not a full plan. Current comparison
is limited to complete simple Play/Pass rows identified by the existing strict
classifier and MP66's existing unique Play preference. A target member update
cannot stand for a complete final-set proposal; a SubmitTargets without a
uniquely established full set is also uncomparable. `uncomparable` is paired
submissions minus comparable preferences, not all requests. Agreement means
historical identity agreement only, never legality, optimality or win rate.
Member slot indices must be actual integers in this new statistic; legacy
boolean/float equality with integer1 is not typed identity proof.

## Actual owner cohort

Two existing owner-local sources were evaluated without a new match. Their
authenticated request identities have zero overlap (checked only in owner
memory); public Cast regression data is not pooled into this cohort.

| Source digest | Records | Observed | Evaluable | Preferences | Abstain | Unsupported |
|---|---:|---:|---:|---:|---:|---:|
| `6bab453be2830750af3983a70ce4843f747252ef950e1e4ced628785d7cfac07` |1433|80|62|1|61|18|
| `b5b9d4cb013bb6e82c42070c9d238e5a2121ac1f15106bb5beb4aae2977974ca` |1490|84|64|1|63|20|
| Total, distinct request identities |2923|164|126|2|124|38|

This finite cohort has preference coverage2/164 (1.22%), abstention124/164
(75.61%), and unsupported38/164 (23.17%). Among evaluable requests preferences
are2/126 (1.59%). It is not a population estimate. A third pre-existing source
had136 framed records but zero authenticated current requests; its coverage
rates are null and it adds no request samples.

| Request class | Observed | Evaluable | Preferences | Abstain | Unsupported | Invalid | Ended |
|---|---:|---:|---:|---:|---:|---:|---:|
| ActionsAvailable |74|74|0|74|0|0|73|
| SelectTargets |28|28|2|26|0|0|28|
| SelectN |16|16|0|16|0|0|16|
| PayCosts |12|0|0|0|12|0|12|
| DeclareAttackers |6|6|0|6|0|0|6|
| DeclareBlockers |2|2|0|2|0|0|2|
| Other |26|0|0|0|26|0|26|

There are142 strictly paired submissions,59 uniquely identified,0 comparable
preferences,0 agreements,0 disagreements and142 uncomparable submissions.
Agreement rate is null because its denominator is zero. The two actual target
preferences do not supply full historical final-set comparisons.

Mandatory Cast cutoffs103→104→105→106→107→109→110 remain separate controls:
position2 multi-slot membership is no full action, position3 remains distinct,
106 has four competing target options and abstains,107/110 revoke,109 has no
borrowed106 domain. For original Equip1402→1421→1422→1424→1425→1426, owner hash
verification precedes evaluation;1422 freezes the sole research preference
before1424, member selection is uncomparable,1425 abstains and1426 revokes.
Independent reviewers use public controls and safe receipts, never claim to
authenticate owner-private bytes themselves.

## Measured gaps and priorities

The largest primary abstain code is `request_fields_not_fully_interpreted`:74
requests (all observed ActionsAvailable; observed Cast74/Activate47/Play26 are
overlapping labels, not extra choices). Next work should first establish the
missing current request-field semantics and retain the default refusal until
verified. This evidence does not justify inventing tactics behind that gate.

Second is unsupported request-family coverage:38 requests, of which owner-local
whitelisted classification identifies PayCosts12, Group8, Search6 and Mulligan4;
the remaining8 need classification before being called strategic choices.
Establish finite request/complete-proposal evidence for these30 classified
requests rather than treating unknown combinations as no legal action.

Third is full target-set and selection-stage semantics:26 target abstentions
(17 multiple/unresolved choices,9 selected-literal/probe cases), plus2 research
preferences that still cannot be compared to a member update as a full set.
This exceeds the separate SelectN16 and combat8 abstention groups in this
cohort. Those remain visible follow-on gaps. Rankings describe this cohort's
observed impact, not ease of implementation or predicted playing strength.

## Bounds, privacy and timing

Initial source size is frozen before reading; later growth is not followed.
Defaults cap file size at64MiB and records at100,000; frame size reuses the
existing4MiB bound. Summary labels and timing samples are capped. A changed,
partial or limited source is explicitly incomplete. Errors return fixed codes,
never paths or exception text. No raw/card/identity trace or database is added.

Stage timing reuses `live_performance.quantiles` with nearest-rank n/p50/p95/
p99/max, capped first samples, null for empty samples. Read/framing samples are
bounded input reads; reducer samples are records; options/shadow samples are
requests; state/publication and bookkeeping have their own call counts.
Reducer timing includes callback freezes, and shadow API timing includes its
existing cached-options/currentness checks. Stages overlap and cannot be summed.
Bookkeeping measures the added aggregation/comparison work; startup, final
summary/code hashing and output serialization are outside those stages. This
same-process offline measurement does not prove real MTGA three-second latency.

No MP66 algorithm changes, complete legality solver, new State/Event version,
online service or native input. input_sent=false; P10=NOT_RUN.
