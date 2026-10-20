# Current attacker configurations (MP102 / Issue 115)

`DecisionConsumer.current_attacker_configurations` is an explicit read-only
Owner API. MP17 projects current combat identities/counts, MP36 checks historical
selected configurations and Submit/results, and MP101 constructs current blocker
assignments. None previously generated whole hypothetical current attacker-row
configurations. This API adds only a bounded nonempty structural research subset.

```python
# Trusted Owner after the single LocalShadowRuntime completes its poll:
report = runtime.consumer.current_attacker_configurations(
    runtime._reducer, runtime._message,
    completed_stamp=runtime._completed_stamp, limit=64,
)
```

Use the existing Runtime Owner context, not an additional reducer or unverified
request JSON. There is no new default CLI/frame/policy output, event schema,
request ledger, observer or runtime dependency. The API reuses MP101's existing
Consumer before/after ref/lease gate, the Runtime completed-poll/raw stamp and
strict public identity helpers. It requires the same accepted current
request/digest/match/game/seat and visible state. Owner thread, current append
phase, complete poll and valid Consumer/ref/lease are mandatory. Raw identity
and interruption state are also checked after calculation. Returned dictionaries
are observations at their boundary; requery for freshness. No cache/last_valid
can restore a consumed result.

## Supported structural subset

Version `mtgaplayer.current-attacker-configurations.v1`, profile
`nonempty_initial_rows_single_offered_opposing_player`:

- The entire initial attackers and qualifiedAttackers lists must match in
  order and source/recipient fields. Every selected field must be absent.
- Every source must have a unique current public Card/Token Battlefield
  identity controlled by self, with consistent unique zone membership.
- Each row must explicitly offer exactly one `DamageRecType_Player` recipient
  with a strict integer opposing `playerSystemSeatId`. No fallback, cross-row
  union, implicit recipient or generic object-ID-to-player conversion occurs.
- The existing `semantic_combat.request/check_request` verifies the full shape,
  known fields, side identities and per-row membership. The MP17 current
  frontier must agree on ordered sources and each offered recipient count.
- At most eight rows and sixty-four returned configurations. Each configuration
  keeps **every row**, with selected true/false and either its own offered
  typed player-system-seat recipient or null. At least one row is selected.
  Enumeration is bounded; the total `(2**rows)-1` counts only this structural
  subset and truncation is explicit. An unsupported/incomplete request has a
  null total and no candidates, not a finding of no legal attacks.

The independent option namespace is `reviewed_attacker_configuration`; every
option carries binding/ref, ordered row/source/selection data and
`verified_known_constraints` scoped to
`whole_nonempty_attacker_row_structure_and_current_player_recipient_membership_only`.
No option is admitted to default CurrentDecisionOptions, MP66 or Unified v1/v2/v3.
`research_eligible=false` for the report and all options.

False/unknown on an unselected row is a hypothetical configuration value, not a
proof that skipping that attacker is legal. Must-attack/goad, dynamic effects,
global combat rules, costs, blocking/damage assignment and strategic utility
remain unknown. `nonselection_legality_verified=false` and
`mandatory_attack_requirements_verified=false`. Zero-attack configurations are
excluded; minimum attack count and complete legal-action count are null.
`canSubmitAttackers=true` is reported as an observed literal only, never server
acceptance of arbitrary subsets. `manaCost:[{}]` stays uninterpreted. All legal
choice, complete legality, strategy, server/encoding and execution flags are false.

## Real retained evidence

| Existing projection | First current record | Source rows | Recipient memberships | Observed subset |
| --- | ---: | ---: | ---: | ---: |
| `player_log_combat_blockers.jsonl` | 8 | 3 | 3 | 7 |
| `player_log_combat_unselect.jsonl` | 308 | 2 | 2 | 3 |

Each prefix is processed through the existing production RawFollower/RawReducer
and Runtime: startup through the preceding record, append only the first current
request, complete its poll, then freeze the new report before reading responses.
Both initial menus have own public Token sources, exact qualified/attacker rows,
one explicit opposing Player recipient per row, absent selected fields and
canSubmit true. Counts are two current requests, five source-row occurrences,
five recipient memberships and seven plus three structural configurations.
They are not independent matches or deduplicated physical-card coverage.

Both files are MP36 scrubbed field projections from one private original
SHA256 `8e75811da0c9e560507eadc276de34b7b08a7091f3c6086b88cad652fb9185b7`.
MP102 uses the preserved real fields and sanitized authentication/wrapping;
it does not reauthenticate private original bytes. THIRD_PARTY.md records the
aliases and omissions. Git LF blob SHA256 values are respectively
`27635b0b9a635afd0c6c263373baafd0f549bb5ab5f7a291e9a0bd772bd57ab5` and
`c03af5784ad3fc634f8dfa7edc986faefe88ac1de78ab23cba0ba87bfb9fc2d2`.
Windows CRLF worktree hashes have a distinct scope.

Only after freezing, historical MP36 checks observe strict Submit9 (selected
rows zero) and first continuous state10, and the later incremental selections/
unselect before Submit315 (selected rows one) and first continuous state316.
Those are two historical submissions, not correctness labels or legality proofs
for these new hypothetical configurations. Revised requests311/314 produce no
new initial-profile candidates; no past domain or selected history is inherited.

## Revocation and validation

Consumption, replacement, Cancel/Undo/mixed records, Full/reset, gaps, partial
polls, lease expiry and stop revoke the new result. A private interruption flag
on the same current RawReducer request survives exact retransmission and is
omitted from legacy documents. No second lifecycle source exists.

`tests/test_current_attackers.py` reuses MP101's production Runtime prefix test
transport. Real prefixes supply positives; every mutation is explicitly
synthetic. Checks cover full/qualified list agreement, recipient/identity/type
and field failures, revised-stage refusal, nonempty whole-row output, bounds,
Owner/completed-poll binding, raw changes during calculation and lifecycle.
Default and MP101 full-return compatibility and the final exact revision's
full Python3.11/Windows doctor/independent review/actual two-platform CI results
are recorded in the delivery PR and safe local receipts.

Added-path local timing after the current poll, stable replay lease clock,
existing quantiles, twenty API calls per prefix: record8 p50 3.6607ms,
p95 5.0125ms, p99/max6.3778ms; record308 p50 2.7144ms, p95 3.0801ms,
p99/max3.3694ms. This is not new MTGA live or end-to-end latency evidence.

No MTGA launch/input, private-log upload or P10. `input_sent=false`; `P10=NOT_RUN`.
