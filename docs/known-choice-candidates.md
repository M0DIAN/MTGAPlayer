# MP47: reviewed current known-constraint alternatives (opt-in)

The separate explicit [MP59 candidates5](current-cast-target-members.md)
supports current Blue1 Cast member probes on State/Event11. It retains unknown
target quantities and predictive payment/readiness limits; candidates2–4 and
their existing profiles keep their previous contracts.

**Not all legal Magic actions.** This bounded pure enumerator reuses the
existing current-request ChoiceValidation, semantic target and payment checks.
It never simulates rules, future requests, hidden information or native input.

Supported profiles:
- Current authenticated single-object nonmana PayCostsReq, with 16 offered
  visible-own objects in the retained real request-only State6.
- Current single-slot public SelectTargetsReq with explicit min/max and
  all-Select target rows. The retained real prefix has four one-target sets.
  Re-presented Unselect-only rows do **not** provide a complete new Select domain.

The enumerator yields at most 64 bounded, structurally valid proposal objects.
It counts the total **within reviewed constraints** before truncating; its
`exhaustive_for_reviewed_constraints` is never full-game completeness.
Global requirements/restrictions, effects, parent request origin, complete
payment, other stages of a choice graph, server acceptance and actual response
encoding remain unknown. Every execution and legality flag stays false.

Offline pure research needs the explicit state contract:

```sh
mtgaplayer replay /private/Player.log --format player-log --decision-state-version 6 --known-choice-candidates
```

Opt-in current Consumer diagnostics on an existing DecisionEvent stream:

```sh
mtgaplayer consume-events --known-choice-candidates
```

For live observation, proposals are bound to the exact current Consumer
snapshot and rechecked after computation and other sidecars. On consumption,
replacement, history-only, staleness, disconnect, malformed or incomplete
domains: no proposals, no fallback to last_valid. Older CLI behavior and
State/Event schemas do not change; no new GRE parser, external dependency,
card rule inference, UI action, native input or MTGA contact. These numbers
measure finite known alternatives, **not** legal move coverage.


## MP48 — Cast/Activate current offered-row subset

The **same opt-in** known-choice report now admits the already reviewed
pre-response Cast/Activate rows of an authenticated current
`ActionsAvailableReq`. Its opt-in report version is
`mtgaplayer.known-choice-candidates.v2` because the report adds
`action_row_coverage`; default replay/Consumer and DecisionState/Event
schemas remain unchanged.

The retained **Generic2 Activate** real request has 20 engine-active rows,
but only **positions 1 and 3** pass the existing narrow source/ability/
predictive-payment checks. The retained **Generic1 Cast** real request has
six active rows, but only **position 1** passes its narrow predictive-payment
checks. All other positions remain unreviewed/unknown or explicitly
contradict the existing known constraints; **offered** is not automatically
**fully legal**.

For this action profile, `action_row_coverage` reports all engine-active
rows as `engine_active_action_rows`, then
`verified_known_consistent_rows`, `unknown_or_unreviewed_rows`
and `contradicted_known_constraint_rows`. The counter is across the
entire authenticated active inventory, even when at most 64 candidate
proposals are returned. Missing or opaque target/payment modes never
become admissible proposals, and all returned rows are rechecked through
the existing `validate_proposed_choice` (no new game-rule authority).
Current live snapshot leases and no-input gating are unchanged.

An exhaustive list **of verified known-consistent rows** does not imply
all actions in the game, all alternative parameter combinations, complete
mana/cost rules, legal response encoding or server acceptance. This step
adds no new GRE parser, card effect inference, hidden-object reads,
automatic execution or real MTGA input.
