# Current decision options

`DecisionConsumer.current_decision_options(limit=64)` returns a detached,
read-only `mtgaplayer.current-decision-options.v1` research view. The equivalent
CLI opt-in adds `current_decision_options` to each Consumer diagnostic:

```powershell
python -m mtgaplayer watch <Player.log> --decision-events --decision-state-version 15 |
    python -m mtgaplayer consume-events --current-decision-options
```

Use State/Event14 for the Equip revision context, or15 for Cast context. Both
retain the common v13 Equip first-stage context; v15 has no v14 revision field.
This interface adds no State/Event version. Defaults and other opt-ins retain
their previous outputs. Recorded history alone cannot become current options.

The existing Consumer owner thread obtains one current state/ref, evaluates
existing inventories and validators, then checks the current ref and lease
again. Each option carries that request binding and snapshot reference. A
one-entry data cache avoids recomputing the same ref/limit collection. Reads,
including cache hits, still pass both currentness checks. Request consumption,
replacement, invalidation, expiry or stopping cannot revive cached options or
diagnostic `last_valid` state. The API does not introduce cross-thread access.

## Evidence and coverage

The report exposes the already projected visible state, request literals,
current continuation summary and its explicitly historical parent binding.
Continuation summaries are not raw-source reauthentication. It reuses Advisor
inventory and one profile-selected Candidates v2–v6 collection. It does not
reparse logs, look up rules online, or add a solver or validator.

Options preserve source, original list position, scope and unknown constraints:

| Kind | Meaning |
| --- | --- |
| `engine_action`, `engine_member` | Offered inventory; row-local checks can annotate an action at its original position |
| `parent_cast_member_probe`, `parent_activate_member_probe` | A member probe under an ActionsAvailable parent, not a final target set |
| `final_target_set` | A whole desired set checked under its separately current SelectTargets request |
| `current_selected_literal_probe` | Current Unselect/selected literal consistency, not a recovered Select domain |
| `activate_target_payment_association` | Existing same-request local association, not an executable payment plan |
| `discard_selection_probe`, `cost_selection` | Existing finite request-local proposals |

Evidence levels are `engine_offered`, `structurally_decoded`,
`known_constraints_verified`, `insufficient_evidence`,
`violated_known_constraints`, `unsupported` and `expired`. Violations and source
gaps also appear in `unresolved`; unknown or contradicted rows gain no verified
proposal. `research_eligible` permits inspection only. Every report and option
keeps legality/execution/input flags false, including locally verified options.

`engine_offered_count` has an explicit unit. Each source retains its own
coverage, probe budget, null totals and truncation. `reviewed_candidate_count`
counts only returned options with local verification, not all engine actions.
Global `unknown_count` stays null: these domains have no common denominator.
Limits1–64 cap returned options; constructed omissions and source truncation are
reported separately. Unknown counts are never obtained by subtracting member
probes from action rows. SelectN and attack/block requests retain observed
members and unknown combination constraints.

## Evidence boundaries and measurement

The retained Cast chain103→104→105→106→107→109→110 has8 active action rows and8
parent member probes at103 (2 Cast rows ×4 members), then4 request-local
singleton proposals at106. Consumption at107 invalidates them. The Stack Card
Unselect request109 keeps its own literals and unknown selected-set consistency;
it cannot reuse106's Select domain. Submit110 does not restore earlier options.

The frozen Equip chain1402→1421→1422→1424→1425→1426 is checked at each cutoff
before reading later data. The portable parent has17 action rows plus6 Cast
member probes and1 Activate association. The first child has1 final-set proposal;
the revised child has1 current-selected literal probe with its own binding.
Consumption yields no options; a later new request may offer fresh options.
State14 and15 are checked independently, without importing v14 revision context
into v15. Original logs stay private; public fixtures retain existing aliases.

`python scripts/measure_decision_options.py --samples 30 --output <report.json>`
uses existing performance quantiles on five public Cast/Equip cases. Cold API
timing includes view copies, existing checks, adaptation and the final gate;
warm timing includes cache copies and both gates. Prefix parsing and synthetic
transport preparation occur outside timed loops. Reports retain code/fixture
hashes and raw timings. This is local API timing, not full-game latency or P10.
Complete legality remains unimplemented. `input_sent=false`; `P10=NOT_RUN`.
