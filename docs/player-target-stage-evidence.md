# Player target selection and terminal evidence

MP85 extends the existing bounded `RevisionStage` with an explicit MP84 role
branch. It does not change the MP73 object-only report, State/Event1–15,
Candidate2–6, default options or shadow policy. No new reader, Reducer, request
ledger, rules solver, response encoder or input path is introduced.

## Opt-in and evidence boundaries

`LocalShadowRuntime(..., player_target_stages=True)` or
`mtgaplayer watch-shadow <local-log> --player-target-stages` enables the branch.
The CLI emits count-only safe summaries. The owner-local
`runtime.player_target_stage_history(include_last=True)` also returns the latest
bounded historical fact. It contains identities and must stay local unless
separately scrubbed. Retained history is never part of current options or policy.

The unique production watch passes its existing StageObserver to the runtime.
Only a new valid append request at a completed poll can freeze the same
Consumer's MP84 sidecar and policy. Freeze is not performed in request-accepted
callbacks, history startup, empty polls or retransmissions. Default frame and
summary fields are unchanged when the flag is absent.

The first freeze includes the complete offered role domain, all local proposals,
request binding, snapshot ref, current raw stamp, version mapping and policy.
The update must have the exact reviewed envelope, one offered Select member,
correct typed response/state/slot identifiers, an unchanged current request,
live Consumer lease/ref and unchanged raw/version/visibility witnesses. Existing
Reducer consumption and strict pairing establish a historical update only.
Player IDs never pass through Card identity/signature lookup.

An update can link to a revised stage only across one typed predecessor Diff,
unchanged source/public-object signatures, no migration involving the source or
selected entity, and no intervening competing request or client submission.
The revised request must independently become current at a completed poll and
pass MP84 again: same scope/source/groups/slot/targeting seat/version, explicit
one/one/one quantities, one Unselect literal and the same typed role identity.
List position and operation are checked separately at each endpoint. An initial
Select row is not equal to a revised Unselect row merely because their numbers
match.

Only a subsequently strict, consumed SubmitTargetsReq completes this historical
stage. Terminal headers, lease/ref, role evidence and before/after identity
witnesses are rechecked. Cancel/Undo, replacement, retransmission, duplicate Diff,
Full/reset, partial, gap, expiry or stop revoke current lineage. The runtime
clears an expired subscription's pending lineage before a new subscription can
be established. A foreign thread cannot tick the Consumer or mutate this stage.
Historical facts remain `current=false`, with all execution permissions false.

The bounded report keeps update-only, independently revised and completed stages
separate. It never imports a future selection into a prior current domain.
Parent-action causality, server acceptance, complete legality and tactical
correctness remain unproven. Agreement/disagreement are null: MP84 proposals
remain `research_eligible=false` and no comparable frozen preference exists.

## Actual owner-local acceptance

The [owner receipt](evidence/mp85-player-target-owner.json) records a fresh
verification of the complete MP77 archive and pinned MP84 client version:
3,225,997 bytes, SHA256
`1d75cd1b65ac868da1e9e0025032c7380317fcbf8669016a00fcb536e44a73ac`,
one generation, 217 contiguous complete segments and 367 framed records.
All three reviewed assembly hashes still match. No private raw payload, account,
absolute local path or hidden object face is published.

The original denominators remain 53 authenticated requests, 42 current
opportunities and 14 SelectTargets. The first historical Mulligan remains the
startup baseline; the other 41 original completed-poll byte cuts are replayed in
order with matching original raw digests, full default options and policy.

| Unit | Observed |
|---|---:|
| Frozen MP84 complete domains / proposals | 11 / 24 |
| Strict consumed target updates | 11 |
| Selected player / existing public object | 10 / 1 |
| Independently current revised selections | 2 |
| Strict consumed terminal submits | 2 |
| Fully linked historical player stages | 2 |
| Unlinked or interrupted domain attempts | 9 |
| Policy comparison unavailable | 11 |
| Historical agreements / disagreements | null / null |
| Complete target / action legality | null / null |

These are different units and must not be added. All 42 original policies remain
1 research preference, 33 abstentions and 8 unsupported. An observed player
choice is not proof of strategic correctness. The controlled replay proves API
lease checks using its simulation clock, not historical wall-clock lease timing
or live MTGA latency.

The [portable fixture](../tests/fixtures/player_target_stages_real.README.md)
contains genuine scrubbed update/revision/terminal projections. Authentication
and Full bootstrap in tests are explicitly synthetic. Independent reviewers
review public projections, code and safe owner receipts; they do not claim to
authenticate private archive or installed assembly bytes.

Synthetic counterproofs cover typed binding, extra fields, role/namespace
collision, hidden members, source/group/slot/player mismatch, nonunique/repeated
updates, missing independent freezes, terminal headers, migration conflicts,
Full/reset/partial/gap, subscription expiry, foreign threads and stop. MP73's
original Card and Ability paths remain separate and retain their default report.

Added work is measured over one controlled replay's 43 polls, including existing
RevisionStage prepare/observe/after-apply and explicit role freezes; see the
receipt's n/p50/p95/p99/max. This bounded nested local calculation is not a full
game-step latency claim. Complete default return-value comparisons and actual
full tests, Windows doctor, exact-HEAD review and Linux/Windows CI remain
separate delivery gates recorded with their actual revision in the PR.

MP81 `current_view_unavailable` and the historical Windows qualification root
causes remain UNKNOWN. `input_sent=false`; `P10=NOT_RUN`.
