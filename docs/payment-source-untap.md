# Explicit pre-request untap event witnesses

State/Event10 adds one nullable `payment_source_tap_provenance` field to State9.
It carries previously accepted source-local event locations across the existing
watch/Consumer process boundary. State9's exact contract cannot carry those
historical locations, so this single new version is necessary. Request params6,
the MP57 association, current tap literals and candidate2–4 remain unchanged.

```powershell
mtgaplayer replay Player.log --format player-log --decision-state-version 10 --payment-source-untap-witness
mtgaplayer watch Player.log --decision-events --decision-state-version 10 | mtgaplayer consume-events --payment-source-untap-witness
```

The separate diagnostic `mtgaplayer.payment-source-untap-witness.v1` joins
exactly the existing MP57 association's two payment sources to their event
provenance. Only two verified sources yield
`untapped_pre_request_witness_verified=true`. Per-source grades are
`explicit_pre_request_untap_then_continuous`, `current_explicit_tapped`,
`unknown` or `conflict`. This is event evidence: current `tapped` can remain null,
global readiness remains unknown, and overall payability, complete costs/payment,
target quantities, effects, legality, encoding, acceptance and input stay false.
It supplies no legal action or execution permission.

## One accepted-state observer

The opt-in `TapObserver` runs synchronously on the existing RawReducer's
`state_accepted` callback, after state validation/commit. It stores only bounded
source fingerprints, last event anchors and seen tap IDs: at most512 source
entries and64 tap IDs per source, with a16KiB fingerprint input bound. It holds
no second board, parser, request ledger or annotation database. Only ordinary
own public Battlefield Cards participate; only the two MP57 payment witnesses
are exported. RawReducer's default behavior and `_current().tapped` are untouched.

This finite captured shape requires a prior same-source explicit raw
`isTapped:true` paired with a strict typed `TappedUntappedPermanent tapped=1`,
followed by an explicit typed `tapped=0` on the same known public identity.
Details have exactly one integer0/1 scalar; Boolean, duplicate/missing/ambiguous
endpoints, duplicate annotations/IDs and conflicting explicit literals withhold
evidence. A tap with an unlocatable endpoint clears the scope, rather than being
silently treated as unrelated. Zero placeholders on unrelated annotations are
not source references. Unsupported/bounded-out instrumentation fails closed.

A listed Diff object replaces its old row and clears old proof. A fresh strict
untap event in that same accepted state can establish a new anchor when source
identity is unambiguous and no explicit literal contradicts it. An omitted
`isTapped` remains unknown; no field-container ordering or default=false is
inferred. Later source replacements, migrations, deletes, zone/membership,
owner/controller/publicness/ability identity changes, or relevant annotations
invalidate the old chain. Proof is never transferred along an ID migration.
Full/boundary/reset/recovery and continuity errors clear prior provenance.
Exact state/request retransmissions do not refresh event/request locations.

At `request_accepted`, the existing immutable request digest/seat/generation/
game/state gates are reused before freezing one current artifact on the existing
request. State10 cross-checks full typed source identities/positions and event
ordering against the current params6. It rejects a proven-untap claim that
contradicts a current explicit tapped=true literal. Locations are frame ordinal,
GRE message index, accepted state ID and annotation index; indices are zero-based.
Ordinals belong to that source generation's observed input stream. Original-file
ordinals and a new-game byte-slice watch stream therefore differ by their prefix.

`evaluate_witness` validates portable claims offline; it cannot reauthenticate
raw events. Live `assess_current_witness` also uses the existing Consumer's
append/current, new-request, session/ref/binding and lease gates. The assessment
and final sidecar output recheck the snapshot after calculation. Consumed,
superseded, stopped, partial/gapped/reset or expired snapshots expose no old
current proof. Last-valid diagnostic state never supplies a fallback.

Formal contracts: [State10](../schemas/decision-state.v10.schema.json),
[Event10](../schemas/decision-event.v10.schema.json). Register their State5/7/8/9
dependencies locally. Runtime additionally enforces cross-field ordering and
typed identity joins. Defaults, State/Event1–9, semantic1–10, manual validators,
Advisor, candidates2–4 and the MP57 diagnostic retain their old complete values.

## Owner-local frozen-source gate

The original7,718,945 bytes hash to
`6bab453be2830750af3983a70ce4843f747252ef950e1e4ced628785d7cfac07`;
all1,433 records frame without error or partial tail. The exact request-only
7,664,967-byte prefix hashes to
`e8a8732c67e8bd4a9c019ec042aae7d067efc54b7797576b8ce53b4d1ffd2635`.
Auth1136/room1141/genuine Full1143:m1 precede request1402:m1;281 new-game
accepted state messages have no continuity error. The same reducer's existing
MP57 validator confirms target action6/17 and the precise mana witnesses12/14.

| Source at mana row | Accepted tap/untap chain (record:message) | Latest untap |
| --- | --- | --- |
| 12 | true+1 at1204:0 →0 at1213:12 →true+1 at1250:0 →0 at1292:5 →true+1 at1336:0 →0 at1375:5 | annotation4 |
| 14 | true+1 at1336:0 →0 at1375:5 | annotation8 |

For this captured client, four source-local explicit true/typed1 pairs calibrate
the literal/event relationship. Strict typed0 events establish the separate
untap observations; no Proto3/Full/default semantics are used. All listed source
rows and event endpoints are own, unique and public at observation time.

Earlier migrations1178:0 and1307:0 have exact orig_id→new_id direction, old own
Hand membership before, old endpoint in Limbo afterward, new public Battlefield
endpoint, matching card group and explicit PlayLand transfer. Old IDs remain in
raw storage/Limbo, not as current Hand/Battlefield endpoints. No tap proof is
carried across these migrations; later fresh pairs anchor the two current IDs.

There are14 accepted states from1375:5 through1402:0 inclusive. Every intervening
source fingerprint, unique membership, zone and visibility agrees; neither
source has a later replacement, deletion or relevant annotation, including
affector references. Five accepted requests intervene, including the final
1402:1; event history is distinct from any one current request. The accepted
1402:0 state is explicitly checked before freezing1402:1. This closes MP57's
earlier research-audit cutoff at1401. Both existing raw/current tapped literals
still remain null; only the separate event-witness result advances.

Original-byte lifecycle and actual watch→consume-events processes establish
history0 →request1402 witnesses2 →through1420 still2 →actual1421 consumed poll0.
Later1422–1433 never revive the old binding/ref; both CLIs stop naturally without
manual proposal input. No response1421, ManaPaid1427 or attachment1428 informs the
current positive. Source bytes/maps/private diagnostics stay local and ignored.
The [portable fixture](../tests/fixtures/payment_source_untap_real_v10.README.md)
is separately sanitized and cannot replace raw authentication. Independent
review covers public artifacts and whitelisted audit methods/safe receipts;
reviewers cannot reauthenticate withheld private bytes. No new gameplay, MTGA
input/injection, P10 repair or latency claim; P10 remains NOT_RUN.
