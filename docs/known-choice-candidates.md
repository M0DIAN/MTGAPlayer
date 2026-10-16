# MP47: reviewed current known-constraint alternatives (opt-in)

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
