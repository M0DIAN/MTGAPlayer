# MP70 finite current-stage action intents

This is an explicit read-only adapter over MP65, not another parser, rule
checker, candidate generator or policy. Baseline main was
`c69a5c3ae432e9b532d3c5409dfc31dada524003` (tree
`0dee70d751db73920f8d111d2ffff6059bc593fc`). MP66 remains unchanged.

## Distinct capability and interface

Before MP70, `decision_options.include` unwrapped a Cast generator item into
its proposal and discarded the existing checked `action_key` and
`payment_witness`. Activate target/payment relations remained separate options.
The continuation context retained parent binding but not its original action
position/identity. The underlying checkers already provided the evidence.

`DecisionConsumer.current_decision_options(include_complex_intents=True)` adds
`complex_action_intents` (`mtgaplayer.finite-action-intents.v1`). The default
return stays identical. CLI use requires both:

```text
consume-events --current-decision-options --complex-action-intents
evaluate-shadow-history INPUT --complex-action-intents
```

Each parent intent retains its original action key/position, current binding
and snapshot reference, checked parameter literal where available, ordered
independent target slots, reviewed member probes, and predictive payment
witnesses. One Cast with four probes is one parent intent. The checked Cast
witness is retained in the existing bounded MP65 data cache; opting in does
not enumerate candidates again. Both Consumer currentness checks still run,
including on cache hits. All State/Event1–15 and Candidate2–6 contracts remain
unchanged; no new State/Event version is introduced.

An intent's `finite_stage_intent_structure_verified` means the already checked
local evidence has been associated within one current stage. It is not a
complete action proposal. Parent target minimum/maximum/selected quantities,
full combinations, payment legality/readiness, extra costs, modes/X, dynamic
effects and tactical value remain unknown. A source's `tapped=null` stays null.
Absent autoTapSolution does not establish failed, free or unnecessary payment.
Every execution permission and complete-legality/encoding flag stays false.

First-child and revised-child intents use only the existing checked
continuation sidecar and that child's current MP65 proposals. The parent's
original position/identity is historical and `current=false`; the parent never
returns as a current engine action. A revised selected-literal probe is not a
final-submit proposal. MP63 State14 supports the revised Equip stage; State15
remains an independent extension of State13 and does not inherit that proof.
No sidecar means no associated intent, even if an unrelated target request
has superficially similar entries. Successor status remains unknown until
an independently accepted current child exists; no future plan is generated.

Truncated source/option coverage cannot produce a positive finite parent
structure. Retained probes cannot bypass the returned-option budget. Invalid
joins/output bounds fail closed. Consumption, replacement, lease expiry,
partial input, reset, discontinuity and stop use the existing invalidation
path; no second ledger or last-valid fallback exists.

## Real evidence and limits

The public retained Cast fixture was frozen at103 before parsing104. It has
8 active rows, 5 Cast rows, and independently reviewed target/payment evidence
for positions1 and3. Position3 has four public members and one predictive mana
row5; current tapped readiness is unknown. Positions1/3 sharing that witness
does not prove simultaneous payment. Position2 keeps ordered slots
`2→[1243], 1→[1243]`, Red1 and absent autoTapSolution, without a complete
combination or finite target/payment intent. The actual104 response chooses
position3 and provides no position2 continuation proof.

The103→104→105→106→107→109→110 sequence revokes consumed requests. Only106
has the checked first-child Cast Card association and its own four current
proposals.109 does not inherit106's Select domain;110 restores nothing.

The owner reauthenticated the frozen Equip original SHA256
`6bab453be2830750af3983a70ce4843f747252ef950e1e4ced628785d7cfac07`
and first froze the1402-only prefix SHA256
`e8a8732c67e8bd4a9c019ec042aae7d067efc54b7797576b8ce53b4d1ffd2635`.
Activate position6 joins one reviewed target and separate predictive rows12/14;
both tapped literals remain null. No successor semantics were parsed for this
parent gate. A later single production State14 append watch verified
1402→1421→1422→1424→1425→1426, including independent revised-request identity
and terminal revocation. Public portable Equip evidence reproduces that
contract; independent reviewers authenticate public samples and safe receipts,
not private original bytes.

The same two owner-local sources as MP68/69 remain byte-stable: frozen Equip
above and existing historical source SHA256
`b5b9d4cb013bb6e82c42070c9d238e5a2121ac1f15106bb5beb4aae2977974ca`.
Their164 distinct accepted requests (no cross-source identity overlap) include
74 ActionsAvailable requests and489 original active Cast/Activate rows:

| Source alias | Requests | Complex rows | Reviewed member rows | Predictive association rows | Finite parent stage rows |
|---|---:|---:|---:|---:|---:|
| frozen_equip | 80 | 290 | 15 | 15 | 15 |
| existing_player | 84 | 199 | 1 | 1 | 1 |
| total | 164 | 489 | 16 | 16 | 16 |

These are overlapping evidence counts per original row, not full legal
actions, requests, target-member counts or strategy preferences.473 rows lack
these reviewed member/payment associations. All489 still lack complete target
and payment proofs; full legal complex action count is null. Default frozen
options/policy returns and MP68/69 functional history summaries match, excluding
only version/timing metadata. Research preference coverage remains2/164.
No improved tactical preference coverage is claimed.
Local report coverage counts parent action rows separately from current child
stages. An optional adapter failure is counted as unavailable evidence and
cannot rewrite MP68's original options, policy statistics or comparison view.

## Validation and measurement

Direct counterexamples cover foreign action keys/typed identities, target or
payment borrowing, swapped Activate sources, shared Cast sources, multi-slot
non-combinations, budgets, cache mutation, expiration/revocation during
assembly, partial input, historical observations and wrong seats. Existing
Cast, Equip, Candidate, policy and historical-evaluation tests remain required.
Final local Python3.11.16 run passed885 full tests and162 focused tests;
Windows doctor passed without input. Independent compatibility audit compared
6,060 full functional returns,104 actual CLI outputs and28 final affected
history returns with no differences. Only genuine version/duration metadata
was normalized for history; CLI output used no normalization. Exact final
candidate independent review and Linux/Windows PR/main CI remain separate
delivery gates; these local results do not substitute for them.

`scripts/measure_decision_options.py --complex-action-intents-only --samples 30`
reuses the existing five public benchmark states, prepares them once, and
times only the added adapter and its cached current Consumer API. Final source
measurement (30 per case) in milliseconds:

| Case | Assembly p50 / p95 / p99 / max | Cached opt-in API p50 / p95 / p99 / max |
|---|---|---|
| Cast103 | .6457 / .8680 / 1.0491 / 1.0491 | 3.9332 / 4.7076 / 6.0281 / 6.0281 |
| Cast106 | .0906 / .0961 / .0962 / .0962 | 1.1223 / 1.2051 / 1.2549 / 1.2549 |
| Equip parent | .7195 / .8306 / 1.0018 / 1.0018 | 6.5720 / 7.0295 / 10.0746 / 10.0746 |
| Equip first child | .0420 / .0494 / .0577 / .0577 | .8414 / .9136 / 1.5813 / 1.5813 |
| Equip revised child | .0440 / .0730 / .0794 / .0794 | .9245 / 1.3547 / 1.5984 / 1.5984 |

This is same-process offline evidence, with synthetic append clock/lease. No
raw-log read, Reducer construction, second generation or combination search is
inside the assembly measurement. It is not MTGA end-to-end latency or a
three-second qualification. Default runtime behavior and input isolation are
separate required compatibility/review/CI gates.

`input_sent=false`; `P10=NOT_RUN`.
