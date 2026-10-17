# Current target and predictive-payment association

Explicit State/Event9 adds request-parameters6 profile
`current_target_generic_two_predictive_association`. The separate diagnostic
`mtgaplayer.activate-target-payment-relation.v1` checks one finite relation in a
single current own ActionsAvailable request. It returns no choice candidates.

```powershell
mtgaplayer replay Player.log --format player-log --decision-state-version 9 --activate-target-payment-relation
mtgaplayer watch Player.log --decision-events --decision-state-version 9 | mtgaplayer consume-events --activate-target-payment-relation
```

`evaluate_relation` is offline artifact consistency. `assess_current_relation`
additionally requires the existing Consumer's current append snapshot, exact
session/sequence/binding, new request observation and unexpired lease. Both the
assessment and Consumer sidecar output recheck the snapshot after calculation.
Historical input, consumption, replacement, reset, gap, partial input, expiry and
stop revoke the old relation. Offline artifacts cannot reauthenticate raw input.

## Finite checks and authority

The producer reuses the authenticated RawReducer request path, existing public
visibility/source ability observations and target-menu projection. All offered
positions remain present. Only reviewed literals are added: one explicit target
slot/member, ability-bound declared cost, two auto-tap descriptors and matching
active mana-row options/selections. Presentation-only `highlight` is validated
as a string by the menu checker before omission; targets themselves are retained.

The evaluator reuses the existing target-member validator and extracted pure
Generic2 route checker. A positive requires the same position, all five action
identifiers and every observed flag to agree with the row and graph; the current
source's unique-ability/group pair; an own public Battlefield target; exact
Generic2 tied to the activation group; two distinct own public Battlefield
sources and two distinct predictive Blue unit IDs. Each source/group has exactly
one active Activate_Mana row, a verified unique ability/group pair, exactly the
offered option and exactly its single-color selection. Unknown source/pair,
ambiguous rows, missing/extra unsupported fields and mismatches withhold the
relation. Explicit contradictions are not a legality verdict for other rows.
Input is bounded to256 rows/records and the existing bounded JSON envelope;
oversize or malformed contracts withhold the whole diagnostic.

Positive status is only
`offered_target_and_predictive_payment_relation_consistent`.
`payment_source_readiness=unknown_not_evaluated` and
`payment_source_untapped_verified=false` are independent of that status. Each
witness retains its nullable `current_tapped_literal`; null, true and false do
not certify readiness in this checker. Predictive descriptors can describe a
route even when physical readiness is unproven. Overall payability, full target
quantity/domain/selection legality, complete costs/payment, rules effects,
complete legality, encoding, acceptance and every executor/input flag stay false.
No other payment route, legal Activate, timing permission or executable action
is inferred. Candidate2–4 and Advisor gain no payable action from this profile.

State/Event1–8, semantics1–10, old manual validators and defaults retain their
existing values. The no-target Generic2 checker still refuses targeted actions;
its original return status/reason/checks are preserved around the shared helper.
No second reducer, parser, request ledger or tap-state interpreter is introduced.
Formal contracts: [State9](../schemas/decision-state.v9.schema.json) and
[Event9](../schemas/decision-event.v9.schema.json). Register their State5/7/8
dependencies locally; runtime enforces cross-object/typed identity constraints.

## Frozen evidence and limits

Owner-local original: 7,718,945 bytes, SHA256
`6bab453be2830750af3983a70ce4843f747252ef950e1e4ced628785d7cfac07`;
1,433 framed records, no framing errors or partial record. Auth1136, room1141
and genuine Full1143/message1 precede request1402/message1 with zero new-game
continuity errors. The exact request-only prefix is7,664,967 bytes, SHA256
`e8a8732c67e8bd4a9c019ec042aae7d067efc54b7797576b8ce53b4d1ffd2635`.
It ends before response1421. Source length/hash and current request digest,
seat, generation/game and complete17-row inventory were rechecked before coding.

| Current source relation | Proven observation | Readiness limit |
| --- | --- | --- |
| Action6 / target member | Same current source ability pair, one own public member, Generic2 | No full target quantity or legality |
| Payment witness12 | Unique same-request offered mana option/selection and predictive unit | Current raw/projected tapped literal absent/null |
| Payment witness14 | Unique same-request offered mana option/selection and a distinct predictive unit | Current raw/projected tapped literal absent/null |

A separate owner-local research audit examined only accepted records strictly
before1402. For source12, explicit tapped=true appears at1204/1250/1336;
ordered `TappedUntappedPermanent` tapped=0 appears at1213/1292/1375. For source14,
true appears at1336 and tapped=0 at1375. Both retain their public identity/zone
through1401 with no later explicit tap in that audited interval. Thus **each**
has an ordered explicit untap observation through1401, with research-only
provenance. This is not a current1402 readiness certificate: the audit excludes
1402's preceding state message, and client serializer/completeness/default
semantics were not validated. Identity-migration annotations mention the source
IDs earlier, but their direction is not certified by this audit. Neither a
partial Diff omission nor a Proto3 default was interpreted as false. Product
RawReducer tap behavior remains unchanged and readiness remains unknown.

Original-byte lifecycle checks use history through1401, append1402 (one relation),
append through1420 (same relation), then actual1421 (zero in that consumed poll).
Later1422–1433 never revive its old binding/reference. Separate actual watch and
consume-events processes exercise the same cuts without a proposal input and
stop naturally. Response1421 and later ManaPaid/Ability/Attach facts are excluded
from the current positive. Existing historical v10 remains separate corroboration.

The [portable fixture](../tests/fixtures/activate_target_payment_real_v9.README.md)
contains only sanitized pre/post State9 projections. Public tests verify
consistency and falsify the finite relation; they cannot authenticate withheld
raw bytes. Source audits, byte slicing and fixture derivation are owner-local;
independent review covers code, public artifacts and the whitelisted audit
method/safe receipts. No new gameplay, MTGA input, P10 repair or latency claim.
