# MP59: current Blue1 Cast member probes

Issue [#71](https://github.com/M0DIAN/MTGAPlayer/issues/71) adds one explicit,
read-only profile. A probe checks one offered target **member** and its same
request's predictive mana route. It does not select a final target set, encode a
response, prove physical readiness or enumerate all legal Magic actions.

## Evidence gate and temporal boundary

Before implementation, the existing single RawFollower/RawReducer replayed
only records **1–103** of `tests/fixtures/player_log_single_target.jsonl`.
The retained scrubbed-real fixture is 113 records, canonical LF 68,174 bytes,
SHA256 `723b6c4ba89a02874044afb1006ad7cf1507997cbc55436b6dc5ee75067a5b81`.
Its request-only prefix is canonical LF 60,858 bytes, SHA256
`1616b632532286f5437c4675c814a25a6a902b40e0de67c19308b37cafaf0c9d`.
Windows checkout CRLF bytes differ; these fingerprints normalize CRLF to LF.

Authentication1, room2, genuine Full3/state1 and every subsequent Diff through
record102/state100 pass existing seat/room/continuity gates. Request103 is own
seat2, request10100/state100, with a verified current request digest. All eight
active positions are retained; the two inactive rows never supply a witness.

| Current record103 observation | Verified scope |
| --- | --- |
| Cast1: source1066/group97320/facet225; Cast3: source1255/group97320/facet294 | Separate own Card instances, self-viewable private Hand, agreeing unique zone membership and visible catalog identity |
| Each offers slot1: 1243,1247,1257,1262 | Four distinct public Battlefield members; opponent Card1243 and Token1262 are included |
| Each literal cost is Blue:1 and has one predictive Blue unit | Exact finite cost and same-request predictive route, independently per Cast row |
| Active mana5: source1256/group96839/facet295/ability30000/unique30003, isBatchable=true | Complete offered row identity/flags; exact single option/selection and unit20000 source/group/color/count match |
| Source1256 has public own-controlled Battlefield membership | Its object catalog ID and independent uniqueAbilities are omitted; their pair is **not verified** |
| Cast2 has two slots | Opaque/unreviewed, with original position retained |

Current target minimum, maximum and selected count remain **null**. The four
references are a menu, not a complete legal domain or a selected four-target
set. Both Cast alternatives share the same predictive unit; eight probes are
independent alternatives, not eight simultaneously payable actions. Current
tap is null; no proto3 default, literal false, Equip evidence or later state
is used to infer untapped/readiness/payability.

Only after freezing that current result was the suffix audited separately.
Actual response104 uniquely equals the complete original Cast3 row and
consumes request10100. Diff105 publishes its Hand→Stack relation;
request106/10102 has explicit min=max1 under its **new** binding. Response107,
revised Unselect request109/10104, final Submit110 and public results111–113
corroborate that historical path only. They never backfill record103's bounds,
domain equality, payment, legality or Cast1's unchosen outcome. Existing
SelectTargets support may inspect106 on its own current binding. Return
causation remains unverified.

These are fixture-level structural checks, **not cryptographic authentication
of the private original Player.log**. Scoped aliases, retained-source mapping
and omissions remain documented in [THIRD_PARTY.md](../THIRD_PARTY.md#mp38-pre-response-single-target-choice-2026-10-16).
The original fixture bytes and provenance are unchanged. Synthetic mutations
and transport clocks in the new tests are explicitly labeled as controls.

## Explicit contracts and use

Only State/Event **11**, request parameters **7**, candidates **5** enable this
profile. State/Event1–10, candidates2–4, MP57 relationv1, MP58 provenancev1,
semantic1–10 and default behavior retain their previous values. State11 keeps
the separately bound v10 tap field; it is null for this Cast episode.

Create a request-only copy in an ignored artifact directory, then inspect it:

```powershell
New-Item -ItemType Directory -Force artifacts/local-mp59 | Out-Null
.venv/Scripts/python.exe -c "from pathlib import Path; p=Path('tests/fixtures/player_log_single_target.jsonl'); Path('artifacts/local-mp59/current.jsonl').write_bytes(b''.join(p.read_bytes().splitlines(keepends=True)[:103]))"
.venv/Scripts/python.exe -m mtgaplayer replay artifacts/local-mp59/current.jsonl --format player-log --decision-state-version 11 --known-choice-candidates --known-choice-candidates-version 5
```

For a real append stream, use `watch <source> --decision-events
--decision-state-version 11`, then `consume-events --known-choice-candidates
--known-choice-candidates-version 5`. History, partial input, digest conflict,
gaps/reset, wrong seat, consumed/superseded requests, lease expiry and closed
transport return no current proposals. The existing Consumer owner-thread,
snapshot/ref and final post-sidecar checks apply without a second ledger.

The candidate report separates active8, target-bearing Cast3, reviewed Cast2,
and observed/examined/verified/unknown/contradicted/unexamined/returned/omitted
member counts. The real prefix returns8; a return limit3 still records8
verified and5 omitted. At most256 probes are examined and64 returned. Each
result preserves its original action_key, full source identifiers/flags,
slot/member, predictive witness and current snapshot ref. Use the nested
`proposal` with the existing explicit choice validator; the surrounding witness
is diagnostic context, not client-response encoding.

Only exact Blue1, one slot, distinct public members, one predictive unit and
one matching active mana row with exact single option/selection are reviewed.
Other colors/costs/modes/X, hidden or off-Hand sources, unsupported fields,
multi-slot rows, ambiguous offers, inactive or mismatching mana rows and
explicitly tapped sources withhold the relevant probes. Missing tap alone
does not block this narrower offered-route check. All complete target/domain/
quantity/cost/payment/rules/legality/acceptance/encoding/execution authorities
remain false; readiness remains unknown and input_sent=false. **P10 NOT_RUN**;
no real-action latency claim is made.

Regression entry point: `python -m unittest discover -s tests -p
test_cast_target_members.py -v`, followed by the full unittest suite and the
Windows read-only `mtgaplayer doctor` probe. No new dependency, card database,
strategy ranker, native input or game connection is introduced.
