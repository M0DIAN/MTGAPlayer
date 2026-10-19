# Parent Cast to mixed player-target source lineage

MP86 adds one finite historical source relationship. An actual selected Cast
can be linked through explicit Card identity/zone changes and Ability creation
to an independently current MP84 target request. This is source genealogy,
not a rules trigger proof, complete action plan or tactical decision.

The feature uses the existing CastStage inside StageObserver and the single
RawFollower → RawReducer → Publisher → Consumer → LocalShadowRuntime pipeline.
No second game state, request ledger, workflow engine, response encoder or rule
solver is introduced. The bounded context expires or clears on interruption;
retained historical facts cannot rearm a consumed request.

The explicit owner API is `LocalShadowRuntime(..., parent_target_lineage=True)`;
the corresponding command is `watch-shadow --parent-target-lineage`. Both imply
the existing `player_target_stages` opt-in. Default behavior stays unchanged.
`parent_target_lineage_history()` returns bounded counts. Its optional
`include_last=True` adds one owner-local historical fact containing local refs;
only the default count report and `safe_summary` are suitable for public
diagnostics. Neither report is an actionable current decision.

## The real positive and its limits

The owner reverified the same MP77 archive: 3,225,997 bytes, SHA256
`1d75cd1b65ac868da1e9e0025032c7380317fcbf8669016a00fcb536e44a73ac`,
one generation, 217 continuous complete segments and 367 framed records. All
three pinned MP84 assembly hashes still match. Counts remain 53 authenticated
requests, 42 original current opportunities, 13 ActionsAvailable and 14
SelectTargets. The older 164 requests are not included.

All 13 ActionsAvailable have a unique exact selected row and a strictly paired,
Reducer-consumed PerformActionResp. Eight selections are Cast and five are
Play; none is Activate. This does not prove those actions fully legal or paid.
The complete parent inventory, its action position and its original completed
poll are preserved. No later child information changes that frozen inventory
or policy.

Only one candidate has the required new source edges:

1. The selected own Hand Card has an explicit ObjectIdChanged and CastSpell
   transfer to a new public, uniquely located Stack Card.
2. Across typed continuous states, the same Card has an explicit Resolve
   transfer from Stack to Battlefield.
3. A unique AbilityInstanceCreated annotation names that Card as affector;
   the new Ability's parent, group, owner/controller and source-zone agree.
   The Ability is already explicitly public in a public Pending zone at this
   time. Later Stack visibility is not used to invent earlier visibility.
4. A later accepted Diff explicitly changes that same Ability's zoneId and
   both Pending/Stack membership lists. Its remaining identity stays stable.
   There is no ZoneTransfer annotation for this edge; it is an observed
   same-entity state-location change.
5. A separately authenticated first-current completed poll provides the MP84
   child request. Its source/group and its independently checked target slot
   refer to the verified Stack Ability. The Cast's earlier empty target data
   is not populated from this future child.

The child has two player candidates and one existing public Battlefield
candidate. The actual subsequent update selects the public object. Therefore
the new positive is **one mixed-domain source lineage**, with **zero linked
actual player selections and zero linked MP85 complete stages**. The other ten
MP85 source relationships stay unverified. The absence of a verified parent
does not prove those requests had no parent. MP85's two completed player stages
and its nine unlinked attempts retain their separate evidence levels.

## The intermediate SelectN is not an identity shortcut

Between Ability creation and the current child, one authenticated
TriggeredAbility/Stacking SelectN receives a strictly paired and consumed
response. Its ids are `[0]`, with `OrderingType_OrderArbitraryOnce`. These are
not ordinary selected members of the offered three-reference domain.

The fixed build-matched public
[SelectNRequest source](https://github.com/ettrue124/ArcaneForge/blob/45f27866c5dfd5891fc101c00e611a36254d2f49/analysis/action-inventory/sources/42f2fb5f062ccc60/GreClient.Rules.SelectNRequest.cs#L354-L359)
contains this dedicated construction. Its Git blob is
`70262a39357cb89b61797f441e2790b2bab15ccc`; SHA256 is
`a2f0e263f53a60c098947bd3b85faefd4986e639898cc1141a57dbdf070f14c3`.
The corresponding
[translator](https://github.com/ettrue124/ArcaneForge/blob/45f27866c5dfd5891fc101c00e611a36254d2f49/analysis/action-inventory/sources/42f2fb5f062ccc60/GreClient.Rules.SelectNRequestTranslator.cs)
only constructs the request; it does not supply an identity remapping proof.

Matching that construction does not authenticate the historical runtime call
path, full ordering, member-to-Ability mapping or SelectN legality. The finite
branch uses only its exact envelope and consumption, with source identity
checked independently before/after. Neither the zero sentinel nor an offered
SelectN reference is used to derive the final Ability. Other unreviewed
intervening requests or submissions break the bounded context.

## Currentness, evidence and privacy

The parent and child are separately frozen through the same Consumer at real
completed append polls. Their request bindings, raw stamps, version capability,
snapshot refs and local leases are checked before/after computation. Parent
consumption is historical; it does not keep the parent's snapshot current while
the child is observed. Partial, reset, Full, wrong typed predecessor, duplicate
Diff/response, Cancel/Undo, competing sources, expiry and stop fail closed.
An Ability creation must be new relative to the immediately preceding accepted
object-ID set, as well as independently source-linked. The bounded presence set
contains no hidden card faces and does not create a second state projection.
Known client/GRE transport shapes are type checked separately; UI transport
records supply no source edge. Unknown or conflicting wrapper fields interrupt
the finite context.

The public Pending witness is producer-only provenance. It does not expand the
current visible-object projection or resolve MP82's request-scoped members.
Unknown or hidden objects never become strategy candidates from this history.
Historical output keeps all input/execution permissions false, and preserves
unknown payment, dynamic effects, complete legality, server acceptance and rules
causation. Default MP65/66 options and the original 1/33/8 policy remain separate.

The [owner receipt](evidence/mp86-parent-target-owner.json) records private-byte
and version authentication, finite per-parent review and the exact edge scope.
The [public projection](../tests/fixtures/parent_player_target_lineage_real.README.md)
uses explicit aliases and synthetic authentication/Full wrappers. Independent
reviewers verify that projection, safe receipts and source; they do not claim
to authenticate private archive or installed DLL bytes.

New latency measurements cover only the added bounded association work in
controlled replay. They do not establish historical wall-clock leases or real
MTGA end-to-end latency. The final owner replay has 43 measured polls:
p50/p95/p99/max = 0.4102/29.3033/77.8687/77.8687 ms. These measure the added
CastStage work, including the completed-poll freeze, rather than the entire
pipeline. No generic performance qualification was repeated.

Local Python3.11 verification passes all 1,171 tests (187.330 s), including the
23 new direct tests; the focused 21-module batch passes 329 tests (51.095 s).
Windows doctor and the explicit CLI smoke pass with no input. The complete
affected legacy outputs match the accepted base across 825,554 leaf values:
ten real JSONL sources/1,152 record observations, all 53 authenticated defaults,
the complete existing MP73/history report and 41 completed append frames/safe
summaries. Only transport refs, source/version digests and timing values are
normalized; no semantic field is omitted from the comparison. Final exact
candidate review, Linux/Windows CI and natural main CI are separate delivery
gates.
Historical MP81 current_view_unavailable and Windows qualification root causes
remain UNKNOWN. `input_sent=false`; `P10=NOT_RUN`.
