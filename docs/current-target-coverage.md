# Current target request coverage (MP74)

The accepted MP73 baseline is `76ec1fa1182fda2808f38be0858f0e6940cb3a40`,
tree `ba422f936a1cc9cfb6d52d924927524be6bef1cb`. Two unchanged owner-local
originals retain the same164 unique authenticated requests, including28
SelectTargets. Authentication precedes semantic reading; each request and its
visible state are examined at first acceptance before future responses.

## Actual failure causes

All12 formerly unprojected requests have a uniquely visible public Stack
Ability source, owned and controlled by the requesting seat. Source group agrees
with the request's ability group; slot/group/seat/quantity types are observed.
There is no evidence here requiring a new source zone or Card-as-Ability rule.

| Original first-accepted slice | Requests | Finite conclusion |
|---|---:|---|
| No cancellation, all offered members uniquely public Battlefield objects |4|Newly reviewable current shape|
| No cancellation, list also contains references outside current visible objects |6|Unverified visible identity|
| Abort, Unselect literal references absent from current visible objects |2|Unverified visible identity|

All10 No requests first fail the old Abort-only profile check. Six also fail
member visibility; the other two failures are Abort selected literals without
visible member identities. These are overlapping gates, not10 malformed
requests. Unknown references are not relabeled as players, zones or legal/illegal
objects. Their roles and zones remain unknown. Among visible members only
Battlefield is observed. No known field contradiction was needed to explain the
four new slices. The [safe owner receipt](evidence/mp74-current-target.safe.json)
retains bounded per-request reason/type classifications without original IDs,
payloads, identities or paths. Baseline checker line numbers refer to the base.

## Explicit current interface

```python
options = consumer.current_decision_options(
    current_target_context=(same_reducer, accepted_message), limit=64)
evidence = options["current_target_evidence"]
```

This is a trusted local owner-thread context, like MP72's current-cost API.
Supply the same production reducer and its actual accepted message. It is not
an external state-injection or JSON context API. The existing Consumer gate
checks append phase, current request/ref, lease and transport before and after.
The original reducer digest and typed binding are checked twice; its current
visible projection must agree with that Consumer state. Tracked raw public
identities are checked again before return. The side result is not cached.

The new finite profile is
`reviewed_no_cancel_stack_ability_public_battlefield_single_select`:

- One slot; positive typed source/group/slot identities and own targeting seat.
- Actual `AllowCancel_No`, both observed prompt representations, absent allowUndo.
- Own public Stack **Ability**, unique public membership, with both request
  ability-group literals matching the observed source group.
- All provided members are uniquely visible public Battlefield Card/Token
  objects; no missing references are dropped to salvage a list.
- Explicit integer min/max1/1; no selected count; a nonempty all-Select list.
- At most64 supplied members and the existing≤64 returned-proposal budget.

`semantic_targets.project_request` and the stricter observed-field helper are
reused through an explicit default-false No-cancel keyword. The literal No is
preserved, never removed or rewritten to Abort. Its spelling is already present
in the pinned [MP71 descriptor receipt](evidence/mp71-protocol-gate.json).
Neither general cancellation behavior nor Prompt routing is claimed verified.
The old parser/checker defaults still require Abort. No State/Event version,
request-parameter contract, Candidate2–6 contract or rule solver is added.

The bounded target-set enumeration was extracted from Candidate2 and shared,
preserving its old full returns. New side options are labeled
`reviewed_final_target_set`, carry the same request/ref and deterministic option
key, and have `research_eligible=false`. They verify local offered membership
and explicit count only. They remain separate from default MP65 `options` and
coverage, so MP66 sees no new tactical preference or changed default inputs.
All execution, encoding, server-acceptance and complete-legality flags stay false.

There is no new Unselect profile: both actual unsupported Unselect requests
lack a verified current visible identity. They stay unknown. Unselect is never
converted into a Select domain, and no previous list is borrowed.

## Invalidation and default isolation

Independent counterproofs exposed that the old reducer retains requests after
Cancel/Undo. New evidence therefore additionally uses one bounded private flag
on its current target request. Cancel/Undo, unsupported non-UI client payloads,
mixed transports, own-seat broadcast requests and Full observations interrupt
that evidence. The marker survives an exact old-request retransmission and is
always stripped from public documents. Ordinary standalone UI telemetry remains
valid. Only a genuinely new authenticated request can begin new evidence.

A second private boolean on the **same reducer** records typed state continuity
from an accepted Full through integer predecessor IDs. A same-valued float
predecessor cannot establish new evidence. Invalidation/reset/game boundary
clears this witness; a valid fresh Full can recover it. Legacy reducer state
acceptance, public documents, State/Event and default policy are unchanged.
There is no independent reducer, observer or request ledger.

The historical evaluator also clears its existing bounded side evidence on
partial/interruption. A later response after Cancel/Undo or other interruption
cannot become a newly reviewed pair even if the old reducer consumes its header.
Lease expiry or consumption during projection discards the result. Stopped,
partial, reset, replaced and consumed contexts cannot revive old references.

## Historical coverage, not invented episodes

```text
mtgaplayer evaluate-shadow-history OWNER_LOG \
  --target-stage-completions --current-target-coverage
```

The new flag requires MP73's flag and only adds a bounded optional report.
Default MP68–73 reports and denominator definitions are preserved. Policy is
frozen first using the original default MP65/MP66 path; only then is the extra
current observation obtained. A verified actual response can be counted later
through the existing `_selection` and post-consumption ResponseEvidence gates.

| Measurement | Result / unit |
|---|---|
| Previously unprojected |12 unique requests|
| Newly reviewed current requests / Select domains |4 /4 requests|
| Newly reviewed selected literals |0 requests|
| New local proposals |7 proposals across4 requests (2,3,1,1)|
| Still unsupported after explicit opt-in |8 requests|
| Newly reviewable paired Select updates |4 consumed submissions|
| Previously reviewed paired updates |4 consumed submissions|
| Strictly linked historical submitted sets |4 episodes, unchanged|
| Comparable original frozen preferences |2 episodes, unchanged;2 agreements|
| Additional linked terminal episodes established |0|
| Header-only terminal submissions without linked reviewed episode |10 submissions, unchanged|
| Additional unlinked episode count |null|
| Complete target/action legality |null / unverified|
| Original policy preferences |2/164 before and after|

Request, proposal, update and episode counts must not be added. The four new
local updates do not provide a complete selection process: this task does not
extend the strict MP73 continuation profiles to No-cancel stages. It never uses
a later Submit to fill the earlier domain. The public Cast106–110 chain retains
four competing proposals at106, the actual update at107,109's independent
selected literal and110's historical terminal proof. Owner Equip1422/1424/1425/
1426 keeps its original preference/expired/abstain/expired sequence.

## Reproducibility and remaining evidence

All164 default options/policy returns and both previous complete history reports
remain equal except version/timing metadata. The public four-case fixture is a
**typed, aliased finite projection**, not original GRE bytes. Identifier/seat/
request/state aliases, prompt parameter redactions and omission of unrelated
objects are explicit. Tests use synthetic authentication/Full envelopes only as
plumbing and label every mutation as a counterexample. The owner authenticates
private originals; independent reviewers use public fixtures, code and safe
receipts without claiming to have authenticated those private bytes.

Only added projection/candidate work is measured, through existing offline
timing tools. One bounded final-source measurement (milliseconds):

| Source | n requests | p50 | p95 | p99 | max |
|---|---:|---:|---:|---:|---:|
| Frozen Equip |7|1.2277|1.5432|1.5432|1.5432|
| Existing player |5|0.8175|1.2887|1.2887|1.2887|

These samples cover previously unprojected requests only, including refusals;
they measure projection and bounded candidate processing together. This is not
actual MTGA latency or a three-second qualification. Production reads no second
log, constructs no second game state and performs no new Cartesian enumeration,
online rules query, card lookup or LLM step.

Unknown reference roles, the two unsupported selected identities, dynamic target
rules/effects, complete combinations/payment and additional No-stage historical
links remain evidence gaps. Historical Windows qualification failure cause
remains **UNKNOWN**; later passing checks do not prove it was fixed.

`input_sent=false`; `P10=NOT_RUN`.
