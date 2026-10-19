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

## MP99: exact-build historical annotation fields

`verify_observed_cast_1u_mana_fields(document, evidence)` is a separate opt-in
portable check. It reuses the unchanged MP98 source-link replay and accepts one
whole-document-bound field projection, version `mtgaplayer.cast-1u-mana-fields.v1`.
The digest is SHA256 of UTF-8 `json.dumps(document, sort_keys=True,
ensure_ascii=True, separators=(",", ":"), allow_nan=False)`, not raw file bytes.
Sample identity, first Cast state, exact fact index, source and spell must match.
Two annotation aliases and two **actual** mana aliases must be distinct; these
aliases never join the predictive mana-ID namespace. The existing MP34 strict
singleton-detail parser checks the retained `id/color` structure and types.
Missing, additional, repeated, mistyped or transferred fields do not verify.
This finite portable profile uses actual-mana aliases1/2 and annotation aliases
`paid-annotation-1/2`; these are scrubbed representation limits, not restrictions
on real GRE IDs or a claim that IDs themselves count mana units.

The Owner inspected only relevant static methods and enum metadata in the same
installed assemblies already authenticated by MP61/84/95. Their hashes and MVIDs
still match those receipts, and the actual archive prelude supplies the matching
full build `2026.64.0.14517.1329972`. No game assembly was executed or modified.
The [MP99 safe receipt](evidence/mp99-owner.json) records the exact identities.

In `SharedClientCore.dll`, `ManaPaidAnnotationParser.GetManaId` reads the first
int32 under `id`; `GetColor` reads the first int32 under `color`. Its iterator
`<Process>d__7.MoveNext` checks annotation type34 and takes `affectedIds[0]` as
the consumer. It first looks up `id` in old LocalPlayer, then Opponent,
`IdToManaMap`. A hit reuses that old `MtgMana`, including its Color and Count;
the event producer is that player. A miss constructs `ManaInfo` with this id,
the detail color and **client event Count=1**; its producer is `affectorId`.
`MtgMana` copies those fields. Same-build GreProtobuf `ManaColor.Blue` is2.
This is the protocol enum, independent of card-database Colors encodings.

One parser invocation yields one event. The inspected client code provides no
server guarantee of event uniqueness, amount splitting/merging, complete cost
accounting or actual resource deduction. Client fallback Count1 is not a theorem
that every annotation means one paid unit. In particular, the pool-hit branch
does not even use the annotation color as the effective event color.

Both original selected episodes were reauthenticated at the original completed
poll boundaries, without recomputing a strategy. MP91 retains11 active/1 inactive
rows and38 trace states; MP81 retains12 active/0 inactive and3 trace states.
Each has two same-spell/source-linked annotations with two distinct actual id
literals and `color=2`. The new portable positive uses MP91's existing unaltered
v2 document plus `tests/fixtures/cast_1u_mana_fields_real.json`; its actual mana
and annotation identifiers are independently scrubbed aliases. MP81's other
Cast remains outside oldv2; no row was deleted to create another positive.

Both preceding player projections omit `manaPool`. This check does not assume
those omitted fields select a client branch. The verified scope is therefore
**the encoded Blue annotation field and its source/spell association**, with
distinct actual identifier aliases. Effective client event color, actual paid
units, merged/duplicate engine accounting and full/additional payment remain
unknown. A different reviewed color yields `contradicted` only for this finite
two-Blue annotation profile; it does not mean payment failed. Unknown enum
values remain unknown. No output supplies an actual amount or grants payment.

The Owner also reused MP58's existing `TapObserver` on the same reducer. MP91 has
no pre-request source tap events; MP81 has old typed tap/untap observations, but
later source-row replacement invalidates their witnesses. All four current tap
literals remain null and all four event witnesses unknown. A missing bool is
not false; a later paid/tapped source does not establish prior readiness.

The portable checker verifies consistency of a supplied artifact with the pinned
version interpretation. Its exact version tuple is required, but it does not
authenticate private bytes, a live build, or caller declarations. Those remain
Owner evidence. It reports `observed`, `verified_scope`, `unknown` and narrowly
scoped `contradicted`; `raw_source_auth_revalidated=false` and
`source_build_reauthenticated=false`. It is historical_only, has no current
request binding/ref/lease/option, and is never called by Runtime or a policy.
Original APIs, schemas, default and Unified v1-v3 outputs remain unchanged.

The next core blocker is a version-applicable engine accounting witness for
units/merging plus continuous pre-request source availability. For a future
**human-operated, read-only** capture, retain exact-build raw bytes from before
both source identities through the request, strict response and payment states;
include distinct-color and multi-unit/pooled-mana contrasts. For untap evidence,
retain a same-source true+typed1 calibration, a fresh typed0 and an uninterrupted
chain to the current request without source replacement/Full/gap. Keep actual
mana IDs, pool contents/counts, costs and annotations owner-local. Such a capture
would test a finite path, not establish universal legality. MP99 starts no game.
