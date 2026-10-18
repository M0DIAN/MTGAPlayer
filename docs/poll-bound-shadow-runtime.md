# Poll-bound local shadow runtime (MP80)

`mtgaplayer watch-shadow <Player.log>` is an explicit read-only, single-owner
runtime. It runs until Ctrl+C; `--samples 20 --interval .25` makes it finite.
Use `--controlled-replay` when appending retained bytes in a controlled test.
The default CLI prints only whitelisted JSON summaries: request family,
currentness, separate evidence counts/units/truncation, policy/refusal status,
revocation and local timing. It never prints raw payloads, account identifiers,
request IDs, refs, option keys, card identities or the input path.

The owner API is deliberately more detailed:

```python
from mtgaplayer.shadow_runtime import LocalShadowRuntime

runtime = LocalShadowRuntime(owner_selected_path, interval=.25)
stream = runtime.frames()
try:
    for frame in stream:
        # Local research only; this dictionary has no input authority.
        inspect_locally(frame)
finally:
    stream.close()
    runtime.close()
```

Each frame includes the current request binding/ref, MP65 options with original
source coverage and evidence levels, the applicable local evidence, MP66 policy
and unknown constraints. Keep full owner data local. `current_frame()` rechecks
freshness on the same owner thread; retaining a dictionary cannot keep its
request alive. The generator is a synchronous pull API: the caller drives polls.
CLI output and caller processing can delay the next poll; reported computation
timings end before stdout emission. These observations cannot establish server
currentness, permissions or actual MTGA latency.

## Existing pipeline, one completed-poll boundary

The old `watch --decision-events | consume-events` interface transports reviewed
DecisionEvents. Its consumer has neither the authenticated RawReducer nor its
accepted message, so it cannot supply the raw contexts required by Target,
Cost, Search and Group interfaces. Its default protocol remains unchanged.

The new runtime calls the existing production `watch()` with private owner and
poll observers. There is one RawFollower, one RawReducer, existing StageObserver
and the same version15 state assembly. One retained accepted-message slot is
authenticated against that reducer; no new request ledger, state, parser or
rules engine is introduced. The completed poll is then published and consumed
by the existing Publisher/Consumer on the same owner thread.

Only the final unconsumed request of an append poll can become current. Earlier
requests consumed/replaced in that poll are never emitted as current frames.
Initial history/reset baselines have `observed_in_history` scope. Complete
append observations have `current_at_completed_poll` scope; partial, consumed,
conflicting, expired and stopped contexts have `expired_or_revoked` scope with
all current data removed. This is separate from MP68's per-request historical
freezes (`frozen_at_request_acceptance`), which this runtime does not use.

The raw digest, typed request identity, seat/match/game/state, completed-poll
visible fingerprint, Consumer binding/ref/lease and append/nonpartial/nonstopped
source must agree before and after the entire frame. Any global failure discards
the whole frame, including otherwise valid local evidence. Partial records,
non-UI client payloads, mixed envelopes, Full baselines and continuity breaks
clear the retained owner message; an old retransmission cannot restore it.
The existing STALE Consumer is terminal. Only a genuinely new accepted append
request may open a fresh Publisher/Consumer subscription using the same reducer;
empty polls and old retransmissions never renew an expired request.
Stopping also closes the Consumer if Publisher stop diagnostics fail.

## Evidence composition and limits

| Request | Existing data reused |
| --- | --- |
| ActionsAvailable | MP65 inventory/probes; MP70 finite complex intents |
| SelectTargets | MP65 candidates; MP74 current target evidence |
| PayCosts | MP65 cost candidates; MP72 stage and MP75 mana consistency |
| Search | MP78 finite current member observations |
| Group | MP79 finite grouping/member observations |
| SelectN / combat | Existing candidates and unresolved combinations |
| Mulligan / other | Explicit unsupported policy, full legal count unknown |

An action row, parent member probe, local target proposal, payment witness,
Search item and Group membership remain separate units. Unknown observed domains
are null, including an insufficient Cost stage. Structure/local consistency never
proves a complete action, payment route, tactical optimum or executable response.
All execution/legality flags remain false; `input_sent=false`, `P10=NOT_RUN`.
No State/Event or Candidate version, dependency or MP66 strategy is added.

## Retained-source controlled acceptance

Owner rechecked unchanged new_player: 3,882,223 bytes, SHA256
`f4881c042ff40c8685a9f116a90a329e6a19f8533775ce65183842715bfbbc61`;
new_previous: 382,841 bytes, SHA256
`936f6483b0169e30cf435a6249af28523fbbe73ea17aa23be3f560246c83bf9f`.
The MP77 archives verify the same bytes in four/one contiguous segments and are
duplicates, not additional cohorts. Source hashes were rechecked after the run.
Independent reviewers use public fixtures/controls and the safe owner receipt;
they do not certify private original bytes themselves.

Unchanged original bytes were cut only using existing RawFramer boundaries and
appended to ignored local temporary files. A recordwise schedule has553 polls:
one initialization through71,551 append polls through622,one empty poll. Of34
authenticated source requests,one is history-only and33 are distinct append
opportunities (233 current-frame observations, a different unit). The33 include
ActionsAvailable17, Attackers4, Group3, Mulligan1, PayCosts2, Search2, SelectN2
and Targets2. Search287/441 and Group143/302/490 match the independent APIs and
precede their later consumed responses. Coalesced polls retain only their final
request;143..165 yields none. A split143 becomes current only after completion.
Real-byte file replacement/truncation establishes a new history baseline and
revokes the old frame. Stopping leaves no current options/preference.

The historical34-source default remains0 preferences/25 abstentions/9 unsupported;
the other source has0 requests. Old164/2 preferences remain prior accepted
evidence; their missing originals were not reauthenticated. Complete34 default
option/policy returns, two default history reports and two Search/Group history
reports match the accepted base (34,109 leaf values; only report versions and
timings normalized). Public controls cover retained Cast103 single/multi-slot
separation, Target/Cost/Search/Group fixtures and SelectN/combat/unsupported
families, default State/Event1–15 and existing Equip/Cast regressions.

## Timing interpretation

`performance_report()` returns n/p50/p95/p99/max in milliseconds for actual
read/framing, reducer, state assembly, publication, consumption, options,
applicable evidence, policy, frame assembly and direct poll-to-frame boundaries.
Startup, append, empty, produced, consumed, invalid, reset and partial labels are
separate overlapping poll populations; do not add them. Failed attempts are kept,
unexecuted phases have n0/null quantiles, and per-phase retained samples are capped
at20,000 with attempted/omitted counts. Nested phases must not be summed.

One owner recordwise measurement (553 polls) gave poll-to-frame p50 3.2541ms,
p95 43.2212ms,p99 53.7829ms,max207.1324ms; frame assembly/publication/consumption
p50 1.0729ms,p95 34.2314ms,p99 38.3533ms,max61.6372ms. These are a local
controlled replay baseline, not a pass threshold or MTGA three-second proof.
The safe owner receipt retains all phase quantiles and invalid/empty samples.
Actual client-log emission delay, real polling schedule/backlog, stdout/caller
delay, server currentness and any authorized input/result loop remain unmeasured.
Historical Windows qualification failure root cause remains UNKNOWN.
