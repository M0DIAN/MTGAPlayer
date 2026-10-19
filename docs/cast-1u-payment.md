# Limited 1U Cast payment evidence

MP98 separates a current predicted route from historical ManaPaid source links.
Neither report is an executable Cast or proof of complete payment/legality.
The APIs are explicit opt-ins in `mtgaplayer.cast_1u_predictive`; the default
runtime, Cardflow and Unified v1/v2/v3 do not call them or change their outputs.

| Level | Evidence | Supported scope |
| --- | --- | --- |
| L1 | Current predicted route | Exact Generic1+Blue1; two distinct Blue1 predictive units and sources; same-request matching Activate_Mana options/selections; unique observed ability identity and strict public Battlefield sources. |
| L2 | Resources available now | Unknown. Both real pre-request tapped literals are unknown. Offered or predictive mana is not readiness. |
| L3 | Historical actual source links | One selected 1U Cast, explicit Hand-to-Stack identity migration/CastSpell, and two ManaPaid source links matching its predicted source set; subsequent tapped literals observed separately. Actual amount/color and complete accounting remain unknown. |
| L4 | Arbitrary new-choice legality | Not implemented. No universal mana or rules solver. |

## Current owner API

`assess_current_cast_1u_predictive(consumer, reducer, message, prepared_rules,
completed_stamp=...)` reuses the existing MP96 parent verification and shared
Consumer/ref/lease/completed-poll checks before and after calculation. Missing,
consumed, replaced, expired, partial, reset, gap, Cancel/Undo or stopped contexts
cannot supply a current positive. No saved report or last_valid grants input.

The two predicted descriptors must agree with unique original active mana
offers. `ability_observation` rejects an ambiguous selected uniqueAbilityId;
the Reducer's existing strict mana-source projection requires public object
and zone visibility and unique membership. An explicitly tapped source refuses
the current profile. Missing tapped literals remain unknown; even explicit
untapped literals do not establish complete source readiness.

## Historical replay API

```python
from mtgaplayer.cast_1u_predictive import reconcile_observed_cast_1u_sources

report = reconcile_observed_cast_1u_sources(semantic_samples_v2_document)
```

This accepts the existing `mtgaplayer.semantic-samples.v2` contract and first
runs its bounded `replay_samples` checks. It then requires an exact full-row
response match, the same reviewed 1U/two-Blue predictive route, an own-Hand
96626 source, one explicit source migration to that Card on Stack, and the
CastSpell fact. Exactly two ManaPaid links must refer to that migrated spell
in its first CastSpell state, with two distinct expected sources. Missing,
duplicate, additional, wrong-source or wrong-spell links refuse a positive.
The complete retained trace must be continuous, reviewed and untruncated;
source identity/ownership/Battlefield location must persist. Subsequent tapped
values are a separate observation, not evidence of prior readiness.

`historical_source_links_consistent` means the observed **source links** match,
not two actual mana units or paid1U. Results have `time_scope=historical_only`,
`current_available=false`, no current binding/ref/lease, and
`raw_source_auth_revalidated=false`. They cannot become current candidates.
The historical producer authenticates the private pair; portable replay only
checks the declared scrubbed artifact. It does not verify private original bytes.

MP34's exact v2 `mana_paid` fact schema and Generic1 evaluation stay unchanged.
Those facts omit opaque ManaPaid `id/color` details. No numeric color meaning,
actual unit amount, predictive-to-actual mana ID identity, or event completeness
is inferred. In the two original episodes, actual IDs differ numerically from
the predicted IDs; the namespaces are not conflated.

## Real evidence and privacy

The Owner rechecked MP91 opportunity20 and MP81 opportunity8 against their
immutable original archive hashes using the existing MP97 follower/reducer,
MP15 strict request/response consumption and MP86 full original-row match.
Each has two explicit ManaPaid annotations to its migrated Cast, from precisely
the two predicted public sources, which are subsequently tapped. Both prior
tapped states remain unknown. This is a new finite two-source join beyond
MP34's Generic1/single-source evaluator; the old evaluator still returns
`insufficient_evidence` for these literal1U routes.

`tests/fixtures/cast_1u_payment_real.json` retains MP91's complete11 active rows
and38-state reviewed trace. It is a real-field alias projection, not raw GRE,
not a synthetic bootstrap and not a whole-archive pair census. The v2 format
does not project inactive rows; its wrapper records the original inactive
count1 explicitly. All physical/request/state/mana/ability IDs and non-subject
card identities are opaque aliases. Only subject96626 is retained as a card
identity. Original private logs, account identity and hidden card definitions
are not included. Synthetic test mutations are separately labeled.

MP81's12-row original request also has the observed two source links. Another
Cast row's target shape exceeds the old v2 portable profile; it is not deleted
to manufacture a second portable positive. Its bounded Owner findings are in
`docs/evidence/mp98-owner.json`. Independent reviewers inspect public field
projections and safe receipts, not private bytes they have not accessed.

All payment-completeness, legality, server acceptance, strategy optimality and
execution permissions remain false; `input_sent=false`, `P10=NOT_RUN`.
The next higher-payment blocker is exact-build meaning/accounting of actual
ManaPaid details and a complete resource/payment witness, not another strategy
coverage audit or an assumption that unknown competing effects equal zero.
