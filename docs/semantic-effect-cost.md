# Observed nonmana payment selection (v7)

`export-semantic-samples --schema-version 7` adds one observed PayCosts/EffectCost
shape to v6. All v6 episodes are delegated together, preserving the existing
hand and v4 target-chain checks. V5 remains the separate Activate profile.
V1–v6 keep their original documents, counts, aliases and successor labels.

The default protocol map recognizes PayCostsReq → EffectCostResp using the
existing authenticated current-request and reducer-consumption gates. Older
semantic versions explicitly omit this new pair from their counts. The timeline
retains its protocol edge but does not pretend that its v4 semantic attachment
supports payment selection; existing v4 joins keep their original pair scope.

The opt-in profile accepts only explicit empty paymentActions, EffectCostType_Select,
NonMana_Payment/Payment, dynamic instance IDs, nonrepeatable selection, explicit
minSel=maxSel=1, aligned literal weights of 1 and the observed signed weight
endpoints. AllowCancel_Abort and allowUndo=true remain literal observations.
Every offered reference must join uniquely to the existing visible battlefield
projection, with observed own owner/controller. An unseen option, unknown field,
nonempty paymentActions or another shape rejects the entire profile. Prompt
values are checked structurally and omitted; they establish no source or rule.

The pure API is:

```python
project_request(message, visible, seat, refs, scope)  # projected payload
check_request(payload, visible, seat)                # raises on unsupported evidence
check_selection(payload, selected_refs, visible=visible, seat=seat)  # status, reason
```

`visible` uses object_ref, zone, owner and controller from the established visible
projection. LiteralRefs can keep visible IDs for current-state research; portable
export uses existing scoped aliases. Visibility is checked before alias creation.
The pure selection check has no response/successor argument and verifies only
known count, membership and nonrepeatable constraints. Identity/lifecycle remain
the caller's existing reducer/Consumer responsibility.

Portable replay records client submission and at most the first continuous Diff's
visible snapshot. It does not inspect annotations, establish payment completion,
sacrifice/exile, parent Activate identity, complete costs, cancellation/undo
reachability, complete legality or server acceptance. Missing results stay
unknown. The [curated real episode](../tests/fixtures/semantic_effect_cost_real_v7.README.md)
has artifact-scoped counts and does not reauthenticate the private source log.
