# Current observed choice continuation

MP62 adds an explicit, read-only association between one actually consumed
target-bearing Activate parent, one subsequently created public Stack Ability,
and the independently current SelectTargets request for that Ability. Opt-in
State/Event **13** adds nullable `choice_continuation`; the pure report uses
`mtgaplayer.current-choice-continuation.v1`. A historical selected parent is
context for the current child, never a restored current parent or an execution
grant. Complete legal-choice verification remains false.

Use `--decision-state-version 13` for the State/Event contract. The explicit
`--current-choice-continuation` diagnostic is available on replay and on the
event Consumer; replay also requires `--format player-log` and State13. It
reports the same bounded context without changing the default version or
granting currentness to an offline snapshot.

## Existing capability and the bounded addition

The accepted baseline is main
`2b60878986b822121ce0389da15a5dd3c9fe4fe5`, tree
`4f8ac4dd03c75f0cbb461fb3dcac7d6d701ff10a`. The original-byte gate ran on
`fcd1e512f94ad3ca4c897e265172a00a09ad7af9`, whose tree is identical.

| Existing capability | Reuse in this slice |
| --- | --- |
| `semantic_targets.project_request/check_request/check_final_set` and the State5 target profile | The current child's own source, slot, public members, literal Select operations and explicit count bounds already support a request-local final-set check. |
| ChoiceValidation and candidates2 | The initial child's one Select member and explicit 1–1 bounds are existing coverage. No additional target solver or new target-candidate coverage is claimed. |
| Current selected-literal validation and candidates3 | The later 1/1/1 Unselect request remains a separate, independently current request. |
| Historical semantic schema10 | Actual full-row Activate matching and the public parent/group creation and target-link predicates supply finite reusable checks. The historical trace supplies no current lease or ref. |
| MP61 State/Event12 and request parameters8 | The parent retains the same 17 active rows, six Cast probes and one Activate relation before its actual consumption. |
| TapObserver, Publisher and Consumer | One reducer's synchronous accepted callbacks, bounded observer state, current binding/ref/lease checks and output rechecks remain the lifecycle model. |

The added fact is the bounded association to a **still-current child**, following
the actual parent response. Existing request profiles through8, target checks,
candidates2–6 and State/Event1–12 retain their contracts. A later response or
result cannot turn an unchosen parent alternative into an observed continuation.
The new association admits only one explicit Select member, literal 1–1 bounds
and absent selected count. Other target shapes keep their existing target
capability while this finite continuation context remains unknown.
The older historical v10 lifecycle and the
[current offered-association view](current-cast-activate-associations.md) remain
separate evidence scopes.

## Gate A: freeze the parent, then stop at the first child

The owner-side audit authenticated the immutable 7,718,945-byte original,
SHA256 `6bab453be2830750af3983a70ce4843f747252ef950e1e4ced628785d7cfac07`.
Original record ordinals are one-based and message positions zero-based.

| Frozen boundary | Bytes | SHA256 |
| --- | ---: | --- |
| Parent-only prefix through1402:m1 | 7,664,967 | `e8a8732c67e8bd4a9c019ec042aae7d067efc54b7797576b8ce53b4d1ffd2635` |
| Serialized parent State12, frozen before successor parsing | 155,956 | `797171b6896f88d164667d12b0b1bf34ef7570bfbfbf8c5934aa953a0edf9459` |
| Child-only prefix through1422:m1 | 7,682,758 | `f532ba434c3d82fb748ef91f3764cc1419d9a3f78595ed73aaee7020f399f239` |

Authentication1136, room1141 and Full1143:m1 establish the same own-seat game.
There are281 accepted states through the parent,282 through the child, zero
continuity errors and zero framing errors. The parent's complete State12 is
frozen before any successor is parsed. Gate A parses successors only through
1422; it uses no1424 selection,1425 bounds,1426 submission or later result.

The actual PerformActionResp1421 has exactly one selected action. Both complete
raw-row equality and complete flat-identity matching identify original active
position6 uniquely; its public source/catalog group and observed unique-ability
pair agree with the frozen parent. The response's complete reviewed envelope
includes typed `AutoPassPriority_Yes`. The existing response pairing gate
recognizes this client submission, and the reducer consumes the parent in that
poll. Its six Cast probes and one Activate relation become zero; the response
does not establish server acceptance or complete payment.

Accepted Diff1422:m0 precedes the separate request1422:m1 in the same GRE array.
The existing `semantic_activate.facts` checker reports
`reviewed_activate_subset` and exactly one new public Stack Ability creation
fact. Its raw type, public object/zone visibility, unique Stack membership,
explicit parent and ability group agree with the chosen parent source/group;
the reviewed creation annotation identifies the same endpoints. The Ability was
absent from the pre-consumption set of all object IDs, including private objects;
becoming public under an old private ID is not new creation evidence. The source
has unique zone membership, and the annotation's source zone must equal that
source's frozen Battlefield zone, not merely another Battlefield zone. This is
an observed public parent/group association,
not direct observation of a successor `uniqueAbilityId`.

The child's own recipient, request digest and binding are authenticated against
the single reducer. Its request/state identity differs from the consumed
parent's. `sourceId` joins that created Ability, top-level `abilityGrpId` joins
the parent's ability group, and the single `targetIdx` agrees. The slot's
`targetingAbilityGrpId` remains an independent namespace even though the actual
raw numeric values happen to agree; equality does not make the two namespaces
interchangeable.

The complete reviewed child shape is retained in the new observation boundary:

| Field | Literal observation and interpretation limit |
| --- | --- |
| Envelope prompt | Only a nonzero uint32 `promptId`; `parameters` is absent. |
| Slot prompt | A nonzero uint32 `promptId` and exactly one parameter with a nonempty string `parameterName` of at most128 characters, `type=ParameterType_Number`, and a typed signed int32 `numberValue`. All are retained as observations. |
| Slot bounds | `minTargets=1`, `maxTargets=1`; `selectedTargets` is absent and remains null in the existing projection. It is not defaulted to zero. |
| Target entries | One currently public Battlefield member, literal `SelectAction_Select`, and the original typed string `highlight` of at most128 characters. |
| Cancellation/undo | Literal `AllowCancel_Abort` and typed `allowUndo=true`. These are observations, not proof of UI reachability. |

Only the literal `minTargets`/`maxTargets` fields supply the child's count
constraints. The slot prompt's Number parameter is uninterpreted and is not
target-count evidence. The hand-selection helper's0–99 Number range is not
applicable. Prompt text semantics and universal prompt irrelevance are not
inferred. The legacy target projector intentionally omits prompt/highlight
values; retaining them here does not change that old profile.

The old v5 current target checker already verifies this child's sole final set
using its own member and 1–1 bounds. A separate schema10 export of exactly the
same stopped prefix contains one target request with `response=null`. These
checks establish baseline reuse and the missing current association separately;
they do not borrow a completed historical suffix for the child.

## Gate B: later lifecycle, kept separate from Gate A

The owner then audited the later original records without changing the frozen
parent snapshot or child-prefix proof. The full source frames to1,433 records
with zero framing errors. These later observations establish revocation and
request separation, not the initial child's missing information.

| Original boundary | Lifecycle observation |
| --- | --- |
| 1421 | The actual parent response consumes1402. |
| 1422:m0 then:m1 | Public Ability creation precedes the first independently current SelectTargets child. |
| 1424 | The actual single Select response consumes that first child; the current request becomes absent. Its continuation lineage is discarded. |
| 1425:m1 | A new request has explicit min/max/selected1/1/1 and one Unselect member. The existing selected-literal validator can assess it, but the MP62 first-child sidecar remains unknown/absent. |
| 1426 | The existing terminal SubmitTargets gate consumes the revised request. |
| 1427–1428 and later | Public submission/payment/result and subsequent requests remain later lifecycle or historical evidence. They cannot restore the parent or first child. |

In particular,1425 receives its own current binding/ref. It is not a renewal of
1422's lease, and MP62 does not propagate the first-child lineage into that new
request. The historical v10 profile continues to describe its broader sequence
under its existing contract.

## One reducer and finite current state

An opt-in `StageObserver` follows the existing TapObserver integration pattern:
the owner calls `prepare(record)` before the one reducer's `apply`, uses its
synchronous accepted-state/request callbacks, and calls `after_apply` to check
the consumed response against the captured current parent. This avoids changing
the default RawReducer response-consumption gate. The ordinary gate's historical
request-ID/state match alone is insufficient for a continuation.

Admission additionally requires the authenticated current request/digest,
uninterrupted same generation/match/game/seat, a fixed reviewed response type,
the exact response/current-state pair, no mixed response/GRE/auth/room record,
and unique complete offered-row and complete-identity matching. Public creation
must be observed before the independent child request. Ambiguous, unsupported
or conflicting data withholds the association.

There is at most one current raw-parent cache, one consumed pending parent and
one frozen current child. These are bounded proof context on the existing
reducer, not another board, parser or history ledger. Reset, discontinuity,
identity/seat change, unsupported ordering, Full/replacement, cancellation or
current-child termination clears the applicable context. Source reset also
resets the observer explicitly; reducer reset itself is not an accepted-message
callback. Retransmissions never create a fresh continuation or refresh a lease.
After the first child's consumption, later equal IDs or matching endpoints
cannot recreate its discarded lineage.

Standalone `ClientMessageType_UIMessage` telemetry is ignored: it supplies no
proof and does not clear the cache, pending edge or current child. A mixed
payload with GRE/authentication/room data is unsupported and clears context.
Cancellation, Undo and other client payloads revoke the applicable context;
retransmitting the child afterward cannot restore it. The pre-consumption object
ID set is bounded at4,096 and is not published as a private-object inventory.

The nullable field and pure report distinguish the observed historical selected
parent, independently verified current child, and consistency of their observed
relationship. A pure offline report cannot certify currentness. The live entry
uses the existing owner-thread Consumer, exact child snapshot/ref and request
binding, append/new-request provenance and leases, followed by the existing
post-assessment and output rechecks. Expiry, partial input, gaps, consumption,
replacement, reset, close or stop yields no current continuation. No `last_valid`
fallback or historical parent ref is an actionable current reference.

## Provenance, reuse and authority limits

The original log and private projections remain owner-local and are not
distributed. The root reviewer authenticated and ran the original-byte audits.
Independent review inspected tracked/public source, the public historical
fixture, and explicitly whitelisted audit methods and safe receipts; it did not
read or independently authenticate those withheld raw bytes, run the private
helpers, or inspect game binaries. Safe-receipt fingerprints for this audit are:

| Receipt/method | SHA256 |
| --- | --- |
| Gate A safe receipt | `10a6bb8d72d6787cee5d14c5c2f07b2bbced045ae2e2a29cd137c621e7886d05` |
| Gate A method | `0d376c24be37bb1dc152ed1bbb4d6edf9732c045c03d23e8ad26a59ddb05f285` |
| Gate B safe receipt | `4ce4e7defdc49371fb9d14d41d9bc23e61b3506087f9dd0baa609c3bf8afc6ba` |
| Gate B method | `acaffe626e9aa2c9a431543d4c505b615fab61f92f8e39448a44a7aa3bf86348` |

The [public safe receipt](evidence/mp62-current-continuation.safe.json) includes
both gates and the separate new current-pipeline audit. That audit checks the
exact1422-only prefix first, then the real append watch/Publisher/Consumer and
emitted JSONL stream adapter through later revocation. Product source hashes
describe owner-local worktree bytes; hosted checkout/tested revision and Git
tree evidence remain separate. The [portable fixture](../tests/fixtures/current_choice_continuation_real_v13.README.md)
contains no raw authentication or recoverable alias map.

The public `current_choice_continuation_real_v13.json` fixture retains eight
portable State13 snapshots: before the parent response, after parent consumption,
the first child, after first-child consumption, the revised request, after its
terminal consumption, the later result, and the final observation. Only the
first-child snapshot has nonnull continuation context. Its canonical LF bytes
are444,810, SHA256
`122a5382b936e404309d158e6098b32ab3bb04cfc1727cb294666846c89ed109`.
Portable consistency checking does not reauthenticate omitted original bytes.
Synthetic bootstrap envelopes, mutations and transport events in tests are not
additional real evidence.

Implementation reuses this repository's accepted request authentication,
response-pair checks, exact action comparison, strict public visibility,
Ability creation facts, target projection/checkers and Consumer lifecycle gates.
No third-party code, decompiled source, game/card resource, binary, native input
path or runtime dependency is imported. Existing attribution remains in
[THIRD_PARTY.md](../THIRD_PARTY.md); this addition requires no duplicate upstream
notice.

The relationship is observed consistency, not rules or effect causation.
Successor unique-ability continuation, complete target legality, quantity-rule
completeness, all costs/payment, response encoding and server acceptance remain
unverified. `complete_legal_choice_verified=false`, all execution/input flags
remain false, and **P10 NOT_RUN**. There is no real-action latency claim. Test,
CI and delivery status belong to the final progress/PR records, not this
evidence-boundary document.
