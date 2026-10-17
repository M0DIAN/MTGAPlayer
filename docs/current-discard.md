# MP56 current one-of-eight Discard proposals

Issue65 starts from freshly verified accepted main
`5bf27eeb32ae61bf5c3ad0c40b7081d0524bc54b`, tree
`a8683bb1b40027a1b5e7b724862f474e8a2753e4`. Natural main
CI39008209545 passed Linux/Windows666 tests each. Before coding, the owner-local
original was found and its exact3237895-byte SHA256
`9f33dc04cddc13cdb50adc09b8bd58c71b3d80b0cfb08157b1cf3bad010f0ecb`
verified. Actual auth/room/Full, request digest, own seat, continuous state273,
eight visible own-hand offers and response213→224→first accepted Diff225 were
separately checked by owner-local replay through the existing source gates. See
[portable fixture provenance](../tests/fixtures/current_discard_real_v8.README.md).

## Explicit opt-in contract

State/Event8 adds exactly one new current profile,
`mtgaplayer.request-parameters.v5 / current_visible_own_hand_discard_one_of_eight`.
RawReducer's new `include_current_discard` flag defaults false and is enabled
only by State8 in replay/watch. Projection happens in the same accepted request
path and reuses `semantic_hand.project_request/check_request`. The producer
checks current physical Card/Hand ownership, zone equality, unique membership
and self visibility before publishing any of the eight offered refs. The pure
Consumer check requires eight unique positive IDs with unique visible own-Hand
joins and the exact explicit1/1/nonrepeatable finite shape. Other offer counts
or SelectN variants remain unsupported.

The old generic SelectN minimum stays unknown in State1–7. New explicit
constraints live only in State8's request parameters; its legacy generic
frontier is not_applicable/unknown with no graph or new inferred minimum.
No request ledger, GRE decoder, rule engine, hand-limit inference, catalog/game
resource, strategy policy, executor or dependency is added.

```powershell
# Offline research; no freshness or execution grant.
.\.venv\Scripts\python.exe -m mtgaplayer replay /private/Player.log --format player-log --decision-state-version 8 --known-choice-candidates --known-choice-candidates-version 4
# Current stream; no manually supplied proposal file.
.\.venv\Scripts\python.exe -m mtgaplayer watch /private/Player.log --decision-events --decision-state-version 8 | .\.venv\Scripts\python.exe -m mtgaplayer consume-events --known-choice-candidates --known-choice-candidates-version 4
```

Python: `enumerate_known_candidates(state, version=4)` is offline research;
`assess_current_known_candidates(consumer, version=4)` uses current Consumer
identity/append/lease gates and the post-calculation snapshot check. Sidecars
recheck after all assessments. No history or `last_valid` fallback. Response
consumption, supersession, changed digest, wrong scope/session, partial/gap,
reset/replacement, expiration/stop/EOF revoke current proposals.

An explicit manual proposal is:

```json
{
  "request_identity": "<the complete current binding object>",
  "proposed_discard_selection": {"selected_object_refs": [12345]}
}
```

The illustration's binding placeholder/ID must be replaced with actual current
values; it is not a loadable proposal. Optional `source_snapshot_ref` pins the
same current snapshot. Strict IDs, one selected member and nonrepeatability
are checked by the new pure wrapper around existing `check_request` and
`check_response` logic. Actual client responses/successors are not arguments.
Protocol request ID0 remains supported, while object IDs must be positive.

Known-candidates v4 covers only this new profile and returns direct existing
manual proposal shapes. All eight are equal known-constraint alternatives in
offer order; original chosen position4 receives no priority or result evidence.
Result fields identify `discard_single_member_probe`, binding/ref/scope,
offered count8, explicit minimum/maximum1, and verified/unknown/contradicted
probe counts. Actual `selected_count` stays null: a proposal length is not an
observed current selection. Python `limit` can truncate the return list (maximum64);
the reviewed verified total and omitted count remain explicit. JSON size bounds
apply before/after; validator version/scope/strict deny fields and returned ref
must match or the entire result is withheld.

Unknown cancellation/source/unfiltered/weight fields remain null. Complete
legality/payment, unfiltered-domain and quantity-rule completeness, effect,
response encoding, server acceptance and execution remain false. Advisor stays
unchanged and abstains; this is no instruction to discard or strategic ranking.
Default State/Event1, old versions1–7, semantic1–10 and candidate v2/v3 retain
their complete prior values. The one older selector test now rejects5 because
4 is explicitly supported; no prior behavior assertion is skipped.

## Evidence and validation boundary

Owner-local original-byte watch→Publisher→Consumer starts with history through212,
appends request213 (bytes2964669–2981911), retains original records214–223, then actual
response224. Before the response there are8 verified proposals; consumption
emits0 in that poll. The first accepted Diff225 and remaining original suffix
through278 cannot revive any old binding/ref or cached proposal. Genuine new
requests may independently supply new opportunities. Bytes3237710–3237895 are
trailing framing text, not a partial JSON record.

Two product CLI processes reproduce8→0 without `--validate-choice` or proposal
input and terminate naturally with exit0. Local80 polls at50ms/30s age policy
test frozen-source lifecycle, not a new match, server freshness or performance.
Record225 contains five accepted ordered Diffs; the portable post-record endpoint
is after all five, while only its first Diff is the historical first successor.
Private raw files/outputs/maps/names/identities/screenshots remain ignored.
Independent method/privacy review cannot authenticate private bytes withheld
from reviewers; the portable fixture checks internal consistency only.

Separate clean accepted-main-tree baseline and candidate processes compare
complete State/Event1–7, default v2 and opt-in v3 candidates, legacy validators,
Advisor and Consumer defaults at95 current-request endpoints each; complete
semantic1–10 documents/replays; default replay/watch; and both prior manual
target fixtures including their v2/v3/Advisor outputs. Semantic compatibility
alone reserializes unchanged new-game records; actual current/CLI proof uses
original bytes. No schema is silently masked as an unsupported source.

Final exact-head tests/doctor, independent code/evidence/privacy review and
head/identical-tree synthetic-merge Linux/Windows CI receipts are recorded in
the Draft PR. `input_sent=false`, `P10=NOT_RUN`; no new gameplay/capture, latency
claim or main merge. The prior historical v6 fixture remains unchanged.
