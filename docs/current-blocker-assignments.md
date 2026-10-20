# Current blocker assignments (MP101 / Issue 113)

`DecisionConsumer.current_blocker_assignments` is an explicit read-only Owner
API. MP17 already verifies current combat identities and edges; MP36 already
checks historical selections, consumption and the first public result. Neither
previously constructed a hypothetical whole assignment for the current request.
This API adds only that finite request-local structural subset.

```python
# Trusted Owner, after the one LocalShadowRuntime has completed its poll:
report = runtime.consumer.current_blocker_assignments(
    runtime._reducer, runtime._message,
    completed_stamp=runtime._completed_stamp, limit=64,
)
```

These are the existing Runtime Owner context fields, not an invitation to build
a second reducer or supply unverified JSON. There is no default CLI, policy or
frame-output change. The API requires the Owner thread, an accepted append-phase
current request, the same request/digest/match/game/seat and public state as the
Consumer, the completed-poll witness and a live snapshot/ref/lease. It rechecks
both the raw context and Consumer after computing. Data-only returned reports
are observations at that boundary; retaining a dictionary grants no authority.
Requery for currentness. No result is cached or restored from `last_valid`.

## Reviewed subset

The version is `mtgaplayer.current-blocker-assignments.v1`; its profile is
`one_current_offered_attacker_per_listed_blocker`. Every listed blocker gets
exactly one attacker from **its own current row's** complete nonempty offered
list. This choice defines a bounded subset to investigate. It does not infer
that every blocker must block or that a zero-block configuration is legal.
The minimum and mandatory-blocking requirements remain unknown. No omitted or
selected-only row can borrow another row's or an earlier request's domain.

The existing `semantic_combat.request` parser and `check_request` enforce the
whole request shape, unique blocker rows, per-row membership, explicit typed
`maxAttackers=1` and opposing/own control. The existing MP17 frontier must agree
on every ordered row and edge. Existing public identity checks additionally
require current Card/Token Battlefield identity and unique public zone
membership. Hidden, unknown, wrong-side and Ability entities are refused.
Several blockers may share the same attacker if each current row offers it.

At most eight rows, sixteen offered attackers per row and sixty-four returned
assignments are supported. The total is the mathematical product for this
reviewed subset; enumeration stops at the return limit and reports truncation.
There is no unbounded product materialization or combat rules search. Each
option carries its own binding/ref, ordered source/target assignment and a
separate `reviewed_blocker_assignment` option namespace. Its local validation is
`verified_known_constraints` with scope
`whole_assignment_current_row_membership_and_explicit_max_one_only`.

Global combat rules, mandatory blocking, menace and other dynamic restrictions,
combat costs, damage order/assignment, server acceptance, response encoding and
strategic utility are unknown. `manaCost:[{}]` is retained only as an
uninterpreted shape. Complete legal action count is null. `research_eligible`,
`legal_choice_verified`, `complete_legality_verified`,
`strategic_optimality_verified` and every execution/input permission are false.
No candidate enters default CurrentDecisionOptions or any Unified policy.

## Retained real evidence and historical isolation

The existing MP36 field projections are reused unchanged:

| Retained projection | First current record | Blocker rows | Offered memberships | Returned subset |
| --- | ---: | ---: | ---: | ---: |
| `player_log_combat_blockers.jsonl` | 33 | 3 | 9 | 27 |
| `player_log_combat_unselect.jsonl` | 259 | 2 | 6 | 9 |

Each initial row has three current offered attackers, absent selected fields
and explicit max one. Each source is a public own Token; offered attackers are
public opposing Battlefield entities. Production RawFollower/RawReducer and
Runtime read only the prefix through each first current request before the new
API runs. These are two request boundaries, five blocker-row occurrences and
fifteen row-edge memberships, not five independently identified physical cards
or thirty-six independent games. The two fixture alias spaces are not used to
deduplicate physical instances across projections.

Both fixtures derive from the same previously recorded private original
SHA256 `8e75811da0c9e560507eadc276de34b7b08a7091f3c6086b88cad652fb9185b7`.
They are scrubbed field projections with sanitized authentication/wrapping.
MP101 independently checks their retained fields, not the private original
bytes or a new live match. Existing provenance is in THIRD_PARTY.md. Git-blob
SHA256 values (LF) are respectively
`27635b0b9a635afd0c6c263373baafd0f549bb5ab5f7a291e9a0bd772bd57ab5` and
`c03af5784ad3fc634f8dfa7edc986faefe88ac1de78ab23cba0ba87bfb9fc2d2`.
Windows CRLF worktree bytes have different hashes and are not mislabeled as the
LF blobs or original-source authentication.

Later records 36/39/42 and 262/265 are selected-only and produce no new current
assignment domain. Historical final Blockers Submit records 43 and 266, with
first results 44 and 267, remain two separate MP36 observations. The Attackers
control starts at 308 (two qualified/attacker rows, one explicit opposing-player
recipient each, absent selection, `canSubmitAttackers=true`); its later unselect,
Submit 315 and result 316 are separate historical facts. None supplies input to
the new initial Blockers proposals. Historical acceptance of one configuration
cannot validate other hypothetical configurations.

## Revocation and checks

Consumption, replacement, interruption/Cancel/Undo, Full/reset, gaps, partial
polls, expiry and stop return no candidates. The single RawReducer carries a
private bounded interruption flag on the current Blockers request; an exact
retransmission cannot clear it. It is omitted from legacy public documents.
There is no additional observer, request ledger, state schema or Candidate
version. Owner computation races recheck identities and raw context as well as
the existing Consumer lease/ref gate.

`tests/test_current_blockers.py` uses the real retained prefixes for positives
and explicitly labels mutations as synthetic counterexamples. It checks
per-row domains, shared attackers, selected-only refusal, typed capacities,
duplicates, hidden/wrong-side/Ability identities, consumption/retransmission,
interruptions, partial/gap/Full/stop/lease, Owner thread, bounded returns and
expiry during computation. Existing MP17/36, Consumer and Runtime tests remain
unchanged. Final exact revision, full tests, Windows doctor, independent review
and actual CI results are recorded in the delivery PR/receipts.

One bounded local measurement runs only this new API after the completed
Runtime poll, using a stable replay clock for the existing lease and the
existing performance quantiles. Twenty calls for record 33 (27 assignments):
p50 5.4606 ms, p95 6.3228 ms, p99/max 15.3004 ms. Twenty calls for record 259
(9 assignments): p50 2.9181 ms, p95 3.5239 ms, p99/max 3.6352 ms. This includes
the current Consumer/identity checks and bounded subset construction, not
historical ingestion or MTGA end-to-end time. No new live qualification claim.

No MTGA launch or input; `input_sent=false`; `P10=NOT_RUN`.
