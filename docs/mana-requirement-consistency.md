# Current mana requirement and predictive output (MP75)

Accepted base is `1ee9b168bf9772721c1c848d8b64eb1a4d5f793b`, tree
`19650b8b8d55940246882a57184581176eef0242`. MP72 already parsed current
requirements and uniquely associated each predictive descriptor with an offered
Activate_Mana action and its manaPaymentOption. That structural join did not
compare requirement amounts with predictive amounts. Direct synthetic controls
over both retained projections show MP72 still accepts Red1/Black2 requirements
with Black1 output, or repeated descriptors. They are counterexamples to an
inference from MP72, not new real game evidence.

## Explicit interface

```python
stage = assess_current_cost_stage(
    consumer, same_reducer, accepted_message, mana_requirement_match=True)
match = stage["mana_requirement_match"]
```

The keyword defaults to false. MP72's complete default return, State/Event1–15,
Candidate2–6, MP65 options, MP66 policy and MP70 intents are unchanged. The
existing accepted-message digest, current request binding, Consumer snapshot/
ref/lease and append-phase gates still surround calculation. No result is cached.

The optional report has its own `mtgaplayer.current-mana-requirement-match.v1`
schema label. `reviewed_predictive_mana_amount_consistent` means only that the
reviewed predictive units equal the observed concrete requirement. It is not
complete payment, action legality, response encoding or permission to execute.

All GRE parsing still uses `project_mana_stage`, `_amount`, `_parameter`,
`action` and the existing typed literal join. The added calculation supports
one concrete non-Generic color requirement, a positive integer quantity within
the existing parser's bounds, and exactly one solution, descriptor and unit.
It compares colors and quantities exactly: an excess unit does not acquire an
unproved offset or conversion rule. A supported discrepancy is a contradiction
of this observed scheme's finite equality only, never proof that no other
payment route exists.

Multiple requirements, Generic/hybrid shapes, multiple solutions, descriptors
or units remain unreviewed. No units from alternative actions are added.
Repeated sources inside a proposed route are explicitly withheld. Repeated
sources among the ten offered alternative actions remain separate positions and
are permitted; they do not represent simultaneous available resources.

The descriptor, its predictive unit and its uniquely matched offered action
must agree on source and ability group with strict typed equality. Positive
unit/ability identities are required. The chosen public own Battlefield Card
uses MP74's existing public/unique-zone identity gate; its visible catalog
identity must match the offered action. The requirement's associated object
retains its unknown rule role and is never substituted for a payment source.
The ability join is observed protocol identity, not a verified ability catalog.

## Lifecycle and independent evidence levels

The new proof additionally reuses the same reducer's typed state-continuity
witness. A bounded private current-cost interruption bit is set by the already
existing interruption sites: Cancel/Undo, unsupported non-UI payloads, mixed
records, own broadcast requests and Full observations. It survives an exact old
request retransmission and is removed from all public reducer documents. It
does not change legacy reducer acceptance or target-stage behavior. Ordinary
standalone UI telemetry does not add cost evidence.

A stronger MP75 proof refusal remains in the optional report. It does not
erase MP72's independent structural observation or relabel a typed-continuity
failure as an unsupported request shape. This distinction has a direct history
regression. Consumption, replacement, invalid binding/digest, partial, gap,
reset, conflict, stop and lease expiry continue to use the existing gates;
expiry or consumption during computation discards the result. No second reducer,
request ledger, retained current state or historical-response input is added.

These levels remain distinct:

- Requirement and predictive output observed.
- Reviewed color/count equality and descriptor/unit/offered identity consistency.
- Source readiness, ability catalog truth, additional costs and complete payment
  unknown; all associated verification/permission fields remain false.

An observed solution container alone is not an observed predictive output.
Empty descriptor or mana-unit lists keep `predictive_output_observed=false`
and cannot produce an amount match.

`tapped=null` is not untapped. Earlier untap facts are not used. Predictive mana
is not paid mana. No previous Cast source or target list is inherited. A future
PerformAutoTapActionsResp cannot contribute to this current calculation, and a
client submission does not establish server acceptance.

## Actual owner evidence and historical units

Both unchanged owner-local source hashes were authenticated before semantic
reading and rechecked afterward. The same164 distinct authenticated requests
include12 PayCosts:10 reviewed nonmana requests with48 local proposals, and2
reviewed mana requests with20 original payment-action rows. The two mana
requests are separate records630 and668 from the existing Player source, not
one request deduplicated by similar shape. Each was frozen at first acceptance
before any later response: Black1 requirement, ten actions at positions0–9,
one Black1 predictive solution at position0 joining payment action position1.

The existing public fixture `current_mana_cost_real_v1.json` is reused without
alteration. Its two aliased real projections are not original GRE envelopes.
Synthetic authentication, enclosing requests and mutations remain controls;
independent reviewers use these public projections and safe owner receipts,
without claiming to authenticate private original bytes.

```text
mtgaplayer evaluate-shadow-history OWNER_LOG \
  --current-cost-stages --mana-requirement-match
```

The new flag requires the old flag. It adds only a bounded aggregate report;
default and previously opted-in reports retain their old functional fields.
Policy is frozen before cost evaluation in the same production pipeline.
Requirements, solutions, action rows, reviewed comparisons and historical
submissions are separate units. Unknown readiness/full-payment counts are null.
The existing9 strictly paired historical cost submissions remain historical
consumption evidence, not payment-completion proofs. No original values, player
identities, payloads or local paths are exported.

The [safe owner receipt](evidence/mp75-mana-requirement.safe.json) records the
actual final-source counts, hashes, full default-return comparisons and bounded
added-only measurements. Actual reviewed matches are2, contradictions0 and
unsupported combination shapes0 in this finite cohort. Source readiness,
complete payment and complete action legality remain null. All164 complete
frozen options/policy and both previous complete history reports match except
version/timing metadata and the new optional report. Final exact-HEAD full
Python3.11, doctor, independent review and actual
Linux/Windows PR/main CI remain separate delivery gates.

Only the added arithmetic/identity helper is timed using the existing quantile
utility at the two real current observations. Existing outer raw/Consumer
currentness gates lie outside this nested timing. No second log parse, state
construction, combination enumeration, online API or LLM is used. These small
offline samples do not establish real MTGA end-to-end latency.

| Added helper only | n | p50 ms | p95 ms | p99 ms | max ms |
|---|---:|---:|---:|---:|---:|
| Two current Player observations |2|0.1983|0.2030|0.2030|0.2030|

The frozen Equip source has no mana-stage observations, so its added-helper
sample count is0 and quantiles are null. Its nonmana observations still retain
the original MP72 evidence. No additional benchmark or real game was started.

Remaining gaps include Generic/hybrid/compound requirements, multiple-resource
route constraints, source readiness, additional costs, payment-selection and
response-index semantics, explicit parent-cost links, server acceptance and
complete legality. Historical Windows qualification root cause stays UNKNOWN;
later passing checks do not prove a repair. `input_sent=false`; `P10=NOT_RUN`.
