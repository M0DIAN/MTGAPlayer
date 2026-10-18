# Current target revision after an observed selection update

MP63 adds the finite association between an actually consumed first SelectTargets
request, its observed single Select update, and a separately current revised
request containing that selected member as Unselect. Opt-in State/Event14 adds
nullable `revised_choice_continuation`; `--current-target-revision` reports
`mtgaplayer.current-target-revision.v1`. Replay requires Player.log format and
State14; the event Consumer uses its existing current snapshot/ref and lease.
This is one observed two-child path, not a new target solver or input authority.

## Accepted capabilities and the precise addition

The baseline is accepted main
`d94710558c954408f02bb66ff4264def6780670a`, tree
`14137c31add733aaeb713a4cf31e4f7b7b7cadb2`.
[MP62's first-child context](current-choice-continuation.md) already associates
the actual consumed Equip parent1402/1421 with the new public Stack Ability and
the independently current first target request1422. It deliberately ends when
that first child is consumed. The existing target profile and candidate3 already
check1425's current 1/1/1 Unselect literal independently. Historical schema10
already matches the selection update to the revised request offline.

The new capability is only a current, request/ref/lease-bound association at1425:
actual selection1424 consumed the authenticated first child, one continuous
accepted Diff retained the relevant public identities, and the new request's
own selected literal matches that actual update. Membership/count checks remain
the existing `semantic_targets.check_current_selected_set` and `literal_selected`.
An Unselect-only menu supplies no complete current Select domain.

State/Event1–13, old request profiles1–8, candidates2–6 and semantic1–10 retain
their contracts. State14 keeps the existing first-child field and can report
that first stage through the existing first-child diagnostic. Its old field is
null at the revised stage; only the new revised-stage field is nonnull there.
The historical first-child context inside that new field keeps its original
binding and Ability creation state. Neither consumed binding becomes current.

## Ordered owner-side evidence gate

The owner authenticated the immutable original:7,718,945 bytes, SHA256
`6bab453be2830750af3983a70ce4843f747252ef950e1e4ced628785d7cfac07`,
1,433 framed records. Ordinals below are one-based records and zero-based
message positions. Auth1136, room1141 and genuine Full1143:m1 establish the
accepted own-seat game; there are zero continuity errors. There are282 accepted
states through the first child and283 through the revised child.

| Frozen original prefix | Bytes | SHA256 |
| --- | ---: | --- |
| First child1422:m1 | 7,682,758 | `f532ba434c3d82fb748ef91f3764cc1419d9a3f78595ed73aaee7020f399f239` |
| Actual Select response1424 | 7,684,011 | `ff359598bf5f020cc9f91840cf74524f66a89d4375887d5fb8048d20db546e53` |
| Revised request1425:m1 | 7,689,086 | `a0d1fe1d97662714bc6aa60cb77a9418769881962595fae302d0069e5299b44c` |
| Terminal submit1426 | 7,689,521 | `0b4c11af30e5f3a5c959dcf158ad8a82a53b02c7f62f87a01c4b0c328b80b1c6` |

The first child state/report was frozen before successor semantics were parsed:
17,922 bytes, SHA256
`e2f4074e72f3a0b76c5b1408b2f332bd0248c13936fe56d68170e1a3de19c75f`.
The audit then examined only1423–1425. Standalone UIMessage telemetry provides no
choice evidence. Actual1424 is a complete SelectTargetsResp, paired only after
the existing reducer consumes the exact current request in that poll. Every
reviewed response field is typed: exact headers, one positive integer slot,
one offered current member, literal Select, and an optional string highlight of
at most128 characters whose presence and value are retained. The old response
checker is reused behind this stricter observation boundary.

Exactly one accepted Diff intervenes before the separate own request1425:m1.
Its new request/state/digest binding is authenticated independently. The parent,
public Stack Ability and actual selected target retain strict private signatures
and public zone membership. Source, top-level ability group, independently
namespaced targeting group, slot and targeting player agree across the requests.
The revised request itself supplies min/max/selected1/1/1 and exactly one
Unselect member matching the actual update. Its prompts, optional-field presence,
highlights, cancel and undo fields are observed independently; no missing count
is supplied by prompt parameters or the previous request's domain.

The revised state and audit material were frozen before terminal semantics:
16,067 bytes, SHA256
`d2162c92759b97342d77a0cff0941d869fe1ef65b2732993a5573bd4d976fc13`.
Only then did Gate B parse1426. Its header-only SubmitTargetsReq has exactly
type/respId/gameStateId, matches the current revised request, and passes the
existing terminal gate after same-poll consumption. This observes client final
submission, not server acceptance.1427–1433 remain later lifecycle evidence;
they supply neither1425 constraints nor earlier currentness.

The root reviewer alone read and authenticated original bytes and ran the
owner-side gate. Independent review reads tracked/public code and explicitly
whitelisted safe receipts/methods, does not run private helpers, and cannot
rehash withheld original logs or private projections. The final gate method
fingerprint is `d496707cfe9be96f5808191d3338ad0007b197d381bc1d760ba919acc0402e6b`.
Its safe receipt SHA256 is
`b694cc4e342b077b829c710ad299bfe7dc4cee673775ea7c5aee920eef5085b8`.

## Finite observer and current contract

`StageObserver(include_revision=False)` preserves the old default. State14
explicitly enables its bounded `RevisionStage` on the same reducer. It captures
the authenticated active first child before old first-stage clearing, then
establishes pending revision context only after strict consumed-response pairing.
One accepted Diff and one new own request can establish the revised stage.
There is no second parser, board, Consumer, request history or branch search.

The new provenance `mtgaplayer.revised-choice-continuation.v1` contains the new
current binding, frozen historical first-child context, complete typed selection
update, revised observation, selected-target identity and
`intervening_diff_count=1`. The report distinguishes historical parent consumption,
first-child consumption, observed selection update, current revised request and
current selected-literal consistency. It leaves the old first-child field null
while the revised field is nonnull.

Producer signatures freeze both identity values and storage types, including a
deep copy of nested uniqueAbilities; float/int equality cannot replace typed
identity equality. The relevant source, Ability and target must remain public,
in the same uniquely joined zones, with unchanged signatures. Invalid callback
or mixed transport input quarantines the whole record, so a later accepted
callback from that same record cannot rebuild a cache. A subsequent prepare
starts a new record boundary. Full/reset, gaps, identity/seat changes, broadcast,
duplicates, unsupported shapes, cancel, Undo and other client payloads clear the
applicable context. Standalone UIMessage telemetry is the sole ignored payload.

At actual1424 the first current proof is revoked immediately; pending historical
selection context grants no current proof.1425 receives a new binding/ref/lease.
At actual1426 the revised request and its candidates are revoked in that poll.
An unsupported submit body or extra fields cannot certify terminal submission:
the new proof is withheld, while the unchanged default reducer may still retain
the request-local candidate3 observation. Later requests or retransmission cannot
restore either consumed binding. Consumer owner-thread, append/new-request,
partial/history/stopped/expiry gates and post-computation/output rechecks apply;
there is no `last_valid` or old-ref substitution.

## Producer continuity guards

A partial poll clears the v14 observer even between consumption and a new
request, when no current request carries a continuity bit. Completing that
record cannot restore the discarded lineage. An identical state-ID Diff is
quarantined before silent reducer retransmission can preserve pending Revision
context. Both the first and revised Diff predecessors use typed JSON identity
when Revision is enabled: numeric equality between an integer and float is not
identity evidence. The default reducer and the existing v1–13 observer behavior
remain unchanged. Direct synthetic regressions retain normal positive controls.

## Portable identity and authority limits

`current_target_revision_real_v14.json` contains eight portable snapshots at the
same parent/first/revised/consumption/result boundaries as MP62. Only
`revised_child` has the new field; `first_child` retains the old first-stage
positive. Canonical LF bytes:450,519, SHA256
`9332ebafad8d09ad17a08f19d2a1f5f783aa5a3d58f808cd1c7bc3df4ee1ac2c`.
The old State13 fixture is unchanged. Synthetic bootstrap, transport and mutation
controls do not create additional real paths or authenticate removed bytes.

The observed selected object is a Token, so its exported `card_ref` is null.
A Token's raw group in the private signature is not an Arena catalog card ID.
A Card observation instead requires a positive known card reference. Portable
checking cross-checks object_ref/card_ref, the visible Battlefield zone enum,
owner and controller, plus the existing typed public Stack member. Raw Battlefield
`zone_ref` and selected `object_type` are producer observations: the portable
visible-object contract cannot independently reauthenticate that zone ID or
distinguish Token from another unknown-card object. Strict private signatures
are an owner-side producer check, not a stronger portable claim.

This change reuses this repository's response, target, transition and lifecycle
checks. No third-party source, game resource, new runtime dependency, encoder or
native input path is imported. Current context is observed consistency, not
rules causation, complete target legality, a complete Select domain, all costs
or payment, successor unique-ability identity, response encoding or server
acceptance. All execution/input flags remain false; **P10 NOT_RUN**. No real-action
latency claim is made. Test, CI and PR status belong to final progress records.
