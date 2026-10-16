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

## Pre-response research (State/Event v6)

Use `--decision-state-version 6` for the opt-in current PayCosts projection.
The nested request-parameters v3 profile carries the authenticated enclosing
binding, the same observed cost selection and historical_response_used=false.
Its domain comes entirely from the current accepted request and uniquely visible
own battlefield objects. No response or successor is read to produce it. V5
continues to expose null request parameters for this request type; v1–v4 also
retain their original output. Default versions and read-only behavior do not change.

An explicit research proposal uses the current binding and one reference from
cost_selection.offered_object_refs:

```python
{"request_identity": current["binding"],
 "proposed_cost_selection": {"selected_object_refs": [offered_ref]}}
```

`consume-events --validate-choice proposal.json` uses the existing current-only
Consumer wrapper and rechecks its lease after validation. History-only,
consumed, replaced, expired, partial, conflicting and stopped requests provide
no current assessment and cannot fall back to last_valid.

Empty, repeated, multiple or nonmember selections contradict known constraints.
Unsupported profiles or missing identity/visibility evidence stay insufficient.
Passing establishes only offered_visible_single_nonmana_selection_consistency:
complete costs, payment completion, future parameters, parent source, rules
effect, cancellation/undo reachability and server acceptance remain unverified.
The legacy action frontier and choice graph remain null for this profile; no
ActionsAvailable inventory is invented. The explicit domain lives in the current
request parameters. A historical selection/result cannot validate another candidate.

The [request-only real state](../tests/fixtures/decision_state_effect_cost_real_v6.README.md)
was produced with an exact prefix ending before response622. Formal v6 contracts
reuse local v5 definitions: [State](../schemas/decision-state.v6.schema.json) and
[Event](../schemas/decision-event.v6.schema.json). Register all three URNs locally;
no network schema resolution or product dependency is required.

## First observed sacrifice result (semantic v9)

`export-semantic-samples --schema-version 9` inherits v8 and adds the two explicit
facts from the real first successor339 after request473/state338 and response622.
The existing accepted-state observer supplies the message and visible endpoint;
no second parser, reducer or lifecycle is introduced. The [upstream reuse
assessment](mtgacoach-reuse.md) establishes why a mana matcher does not address
this nonmana result.

This finite slice accepts exactly one ObjectIdChanged and one ZoneTransfer with
category Sacrifice in that state. The selected own battlefield object must leave
the visible projection; its unique new reference must appear in the own public
graveyard with the same known Card identity. Both annotations must name one
affector visible on the own stack at both endpoints. The public source/destination
zone metadata and existing state continuity must agree. Other migration/transfer
annotations, malformed fields, conflicting affectors or endpoint ambiguity
withhold the result even when an additional annotation appears unrelated.
The two other real annotations remain explicitly omitted. This is intentionally
a narrow observed shape, not a generalized effect or sacrifice-rules engine.

The portable trace retains `object_id_changed` and `sacrifice_transfer`, each with
`observed_affector_ref`. Missing or unsupported facts retain the valid submission
and endpoint but return `selected_card_sacrifice_observed=false` and
`selected_card_result=insufficient_evidence`. Positive evidence reports
`selected_card_result=observed_explicit_annotation_chain`. That result binds only
the actual selected reference; another candidate cannot borrow it. Annotation
order within the same state is not used as causal evidence. Later states cannot
repair a missing first-successor result.

The request's `source_object_ref` stays null: the observed affector does not fill
an absent request binding. `payment_completed_verified`, `rules_effect_verified`,
`complete_legality_verified` and `server_acceptance_verified` remain false;
parent Activate and later Search causality remain unknown. Portable replay checks
internal consistency, not the private original's authenticity.

State/Event v6 and ChoiceValidation keep their existing pre-response current-request
boundary and tri-state checks. No future successor data enters a current proposal.
Defaults and semantic v1–v8 retain their earlier contracts, including endpoint-only
cost observations in v7/v8. The [curated real v9 episode](../tests/fixtures/semantic_effect_cost_result_real_v9.README.md)
is newly exported; prior fixtures are unchanged.
