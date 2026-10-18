# Current PayCosts evidence (MP72)

`assess_current_cost_stage(consumer, reducer, accepted_message)` is an explicit
read-only owner-thread API. The caller supplies the **same** production reducer
and its accepted GRE message, not a reconstructed envelope or an offline state.
It reuses `DecisionConsumer.current_decision_options()` and the shared before/
after snapshot/ref/lease/append gate. The original request digest and its own
binding are authenticated before and after projection; the current visible
identity projection must also agree with the reducer. No result is cached.

This does not extend State/Event1–15, Candidate2–6, MP65 options, MP66 policy or
MP70 intents. Existing default outputs are unchanged. The API exposes private
current bindings/object references to the local owner, just like MP65; do not
publish those identity-bearing returns. The CLI exports aggregates only:

```text
mtgaplayer evaluate-shadow-history OWNER_SELECTED_LOG --current-cost-stages
```

That is explicitly historical simulation. Each observation is evaluated at the
first authenticated accepted request before another message is applied. Future
responses are only counted afterward through the existing post-consumption
ResponseEvidence gate. No log is reread to build another game state.

## What is new and what already existed

The same two authenticated sources still contain164 distinct own requests,
including12 PayCosts (6+6). The old `unsupported/request_strategy_unsupported`
is MP66's lack of a PayCosts strategy branch. It did **not** establish that all12
had unsupported protocol data or lacked local alternatives.

| Current evidence | Requests | Separate row/member count |
|---|---:|---:|
| Existing strict nonmana single-object selection, min/max1/1 |10|48 local proposals|
| New finite mana-payment stage, not a complete payment proposal |2|2 requirements,20 offered actions,2 predictive solutions|
| Additional unreviewed whole request shapes in this cohort |0|not a universal protocol-coverage claim|

The10 old requests retain their original Candidate v2/MP65 alternatives without
choosing one. The public existing16-member fixture remains16 independent local
proposals; no new capability is claimed for repackaging it.

The genuinely new profile preserves ordered `color/count/objectId` requirements
and their current visible associated objects, plus the independent original
payment-action positions and predictive autoTap descriptors. Amounts, action
literals, mana options, autoTap types and visible-object joins reuse existing
checkers. Each predictive descriptor must join uniquely to an offered current
payment action and its literal mana option. This is a structural association,
not proof that the solution can currently pay the requirement. No mana-choice
candidate or Cartesian product is constructed.

The inspected finite body has `manaCost`, `paymentActions`, `paymentSelection`
and `autoTapActionsReq`; its selector has exactly the seven observed context/
list/id/validation/weight fields, with ids and min/max absent. Those absences
remain unknown rather than zero/empty selections. Prompt representation is
checked but its routing meaning remains unknown. Other shapes fail closed.

## Protocol and source boundary

The retained pinned public client text is ArcaneForge at
`45f27866c5dfd5891fc101c00e611a36254d2f49`, under
`analysis/arena-request-catalog-20261010/`. Its `Full-list.md` describes the
PayCosts container and ManaRequirement fields. `PayCostsRequest.cs` constructs
its action child from the **same** incoming envelope. Its `OnChildSubmit` forwards
SelectNResp, PerformActionResp, EffectCostResp and PerformAutoTapActionsResp.
This container-parent relation does not refer to a preceding Cast/Activate.

`ui-sources/Wotc.Mtga.DuelScene.Interactions.PayCostWorkflow.cs:61–66` uses
ManaRequirement.ObjectId as a current game-object highlight key. This supports
the limited associated-object reference; it does not identify a mana producer,
a mandatory payment object, or the earlier submitted Cast. The code retains
that role as unknown. No new client extraction or runtime route claim is made.
See [safe source receipt](evidence/mp72-current-cost.safe.json).

Nine cost submissions pair strictly with their own consumed request: eight
EffectCostResp and one PerformAutoTapActionsResp. The latter is envelope/
consumption evidence, not an independently proved selected-index meaning or
server acceptance. Default MP68 pairing/comparison totals are unchanged; the
additional child path is counted only in this opt-in report.

Twenty-six prior complex submissions are uniquely observed over the whole
cohort. Nine cost requests have an earlier paired complex context in the same
continuous game scope, eight immediately among accepted requests and one with
three intervening requests. These are **temporal** diagnostics. There are zero
verified explicit parent-cost links; all12 causal relations remain unverified.
The current API therefore returns no historical parent context and never
inherits its target lists, predictive payment or permission. A bounded prior
scope in the history counter is diagnostic only, never a request ledger or
current candidate authority.

## Limits, lifecycle and validation

All complete payment, legality, response-encoding, server-acceptance and input
permission flags stay false; historical full-payment/full-action counts are
null. Ten requests have local cost proposals, while the two mana-stage complete
candidate domains remain unknown. Preference coverage stays2/164.

Consumption, replacement, replay of consumed messages, raw-content mismatch,
seat/state/request mismatch, visibility disagreement, reset, gap, conflict,
partial transport, stop and expiry revoke/withhold the observation. Expiry or
raw consumption during calculation discards the computed result. A subsequent
request must establish its own binding and constraints. A requestless current
state snapshot may remain after consumption; it cannot authorize the old stage.

Public tests use two owner-produced projections from records630 and668, each
frozen before its response; original envelopes/prompts and private identities
are omitted. Reconstructed envelopes/lifecycle mutations are explicitly
synthetic controls, not new real evidence. Reviewers validate portable structure
and owner receipts; they do not claim to authenticate private original bytes.

Original Cast103 and Equip1402 chains contain no PayCosts stage added by this
work. Their separate Card/Ability, choice/currentness, consumption and MP67
multi-slot boundaries remain unchanged. Existing Windows qualification failure
root cause remains unknown; this task neither hides it nor claims to fix it.

Only the added current-stage API is timed in the opt-in historical evaluation.
It includes currentness checks, existing cached MP65 access and finite local
projection. Offline timings are not native MTGA end-to-end latency.

Actual added-only bounded observations, milliseconds (six requests per source):

| Source | n | p50 | p95 | p99 | max |
|---|---:|---:|---:|---:|---:|
| Frozen Equip history |6|1.1245|2.1451|2.1451|2.1451|
| Existing Player history |6|1.5825|2.7979|2.7979|2.7979|

The two complete legacy history returns match retained pre-MP71 results except
version/timing metadata. All164 complete frozen MP65 options and MP66 policy
returns match with this opt-in enabled/disabled. The direct and relevant
regression batch passes200 tests. Final exact-HEAD full Python3.11, Windows
doctor, independent review and Linux/Windows PR/main CI are separate delivery
gates; these local evidence results do not substitute for them.

Next evidence priority remains complete target sets and stage selection, then
reviewed requirement/payment combinations with an explicit parent link where
one is actually claimed. Other unsupported families need classification before
estimating their implementation value. The12-request investigation is not a
prediction of policy-coverage improvement.

`input_sent=false`; `P10=NOT_RUN`.

MP75 adds an explicit `mana_requirement_match=True` side report and historical
`--mana-requirement-match` flag. It compares a single concrete requirement to a
single predictive unit without changing this MP72 default structural contract.
See [mana-requirement-consistency.md](mana-requirement-consistency.md).
