# MP55 reviewed target proposal discovery

Issue63 starts from accepted main
`ce7051224994b453547fee1caf3a6d3672b1f8d8`, tree
`647f43a92a2b216e7cb6f237bba607e0d4f5db29`. Natural push/main
CI39006080912 passed Linux/Windows653 tests each before branching. The existing
manual validators already support both real current profiles; default
known-candidates v2 deliberately returns no proposals on these two requests.

Explicit `--known-choice-candidates --known-choice-candidates-version 3` selects
`mtgaplayer.known-choice-candidates.v3`. This branch in the existing interface
constructs existing proposals and calls `validate_proposed_choice` on the same
State. No parser, reducer, ledger, solver, Advisor policy, State/Event version,
semantic exporter, dependency or input path is added. Version2 remains the exact
default. Version3 covers only these two profiles; unsupported profiles return
insufficient evidence, while version2 retains its older domains.

```powershell
# Offline research only: no freshness or execution grant.
.\.venv\Scripts\python.exe -m mtgaplayer replay /private/Player.log --format player-log --decision-state-version 7 --known-choice-candidates --known-choice-candidates-version 3
# Current observation: feed the existing watch --decision-events stream here.
.\.venv\Scripts\python.exe -m mtgaplayer consume-events --known-choice-candidates --known-choice-candidates-version 3
```

Python callers use `enumerate_known_candidates(state, version=3)` for offline
research, or `assess_current_known_candidates(consumer, version=3)` for current
observation. Live results use the same owner-thread Consumer current/ref/lease
checks, followed by a snapshot check after calculation and other sidecars.
History, consumed/replaced request, wrong scope, partial/gap, expired/stopped or
closed state cannot supply proposals. There is no `last_valid` fallback.

| Current profile | `probe_kind` | Constructed existing proposal | Authentic positive |
| --- | --- | --- | --- |
| `current_public_activate_target_member` (State7) | `target_member_probe` | `proposed_activate_target_member`, current position/identity/slot/member | Request1402: position6, one verified public member;17 rows =1 verified +16 unknown |
| `reviewed_single_slot_public_targets` (State5–7) | `already_selected_literal_probe` | `proposed_current_selected_target_set`, exact `literal_selected` and current source/groups/slot/player | Request1425: one literal, explicit min=max=selected_count=1, single Unselect, public Stack Ability/Battlefield member |

The candidates array contains direct existing proposal objects. Result-level
`probe_kind`, `validation_scope`, `request_binding` and `source_snapshot_ref`
describe them without changing the manual proposal loader. Unknown source/ability
pairs remain unknown; explicit contradictions describe only reviewed constraints.
Validator version, profile-specific scope, strict read-only/execution flags and
required false completeness flags must match; drift discards the whole result.

Member proposals have no observed quantity bounds: all three `target_quantities`
values are null. One offered member does not imply min=max1. Selected-literal
proposals preserve the current 1/1/1 observations; quantity-rule completeness
stays false. They supply no newly selectable domain, Submit instruction, payment,
future choices, response encoding or server acceptance. Legacy `check_final_set`
still refuses to enumerate Unselect-only requests. Advisor still abstains. Every
complete-legality/payment/target-domain and execution/input flag remains false;
`verified_known_constraints` means only the named check.

## Bounded counts

At most256 explicit member probes are constructed and validated in original row
and offer order, with at most64 proposals returned (Python `limit` may lower64).
`probe_coverage` reports observed, examined, verified, unknown, contradicted,
unexamined and verified-but-omitted counts separately. Unexamined offers are
never certified: the candidate total is null when any remain; truncation is true.
Otherwise the total counts verified probes, including those omitted by the
return limit. Exhaustive refers only to reviewed probes without unexamined or
unknown probes or omitted verified proposals, never full action legality.

`action_row_coverage` preserves every original position, source/ability status
and explicit public-member count. A row with a verified member is counted once;
a contradicted-only row is contradicted; opaque or unexamined-only rows are
unknown. Row counts and probe counts cannot describe all parameter combinations.
Selected-literal results have null action-row coverage. Existing JSON size bounds
apply before and after calculation; invalid/oversized results discard all proposals.

## Evidence and limits

Only the two existing sanitized real State fixtures are reused, unchanged:

- MP53 `decision_state_activate_target_member_real_v7.json`, canonical LF
  SHA256 `c2b9294c683799abebfa6956006ca9146c9c035ee371cb2b2ccab4737ab8a5c4`.
- MP54 `current_selected_target_set_real_v5.json`, canonical LF
  SHA256 `64488e9b3f67014322757ccb975be2143a29bd56e86a55c6528625e50b73dfaa`.

Adjacent provenance files describe aliases/omissions. No third real fixture or
historical v10 suffix certifies a current proposal. Tests mutate these states and
create transport envelopes only as synthetic controls; the Generic2 Activate
raw excerpt tests CLI wiring only. Portable tests cannot reauthenticate the
removed private source.

Owner-local original-byte verification uses the frozen7718945-byte original,
SHA256 `6bab453be2830750af3983a70ce4843f747252ef950e1e4ced628785d7cfac07`,
1433 framed records, no framing errors/partial record. Auth1136, room1141 and
genuine Full1143/message1 provide the new-game baseline; the earlier Undo gap
supplies no predecessor. Request/digest/seat authentication and zero new-game
continuity errors are checked before any response. Ordinals are one-based,
message indices zero-based, byte ranges zero-based/end-exclusive.

| Case | History startup | Request append | Actual consumed response | Later suffix |
| --- | --- | --- | --- | --- |
| Member, State7 | 1136–1401,6320585–7647248 | 1402/msg1,7647248–7664967 | 1421,7674282–7676983 (UI1403–1420 preserves current) | 1422–1433,7676983–7718943 |
| Selected, State5 | 1136–1424,6320585–7684011 | 1425/msg1,7684011–7689086 | 1426,7689086–7689521 | 1427–1433,7689521–7718943 |

Full-prefix SHA256:1402 `e8a8732c67e8bd4a9c019ec042aae7d067efc54b7797576b8ce53b4d1ffd2635`;
1425 `a0d1fe1d97662714bc6aa60cb77a9418769881962595fae302d0069e5299b44c`.
Two trailing non-JSON bytes after record1433 are framing text.

Each original-byte same-file watch→Consumer case discovers one proposal before
response, emits zero in the consumption poll and refuses the cached old proposal
through the suffix. Later genuine new requests may independently produce
proposals with new bindings/refs; they never revive the old request. Two product
CLI processes per case, without `--validate-choice` or any proposal file,
reproduce discovery/revocation and natural stop/EOF with exit0. The local test
uses80 polls at50ms and a30s age policy: frozen-source lifecycle checks, not
gameplay or server/performance measurements.

Independent baseline/candidate processes compare complete State1–7, default v2
candidates, legacy verdicts and Advisor at179 accepted request endpoints each;
Event1–7 append streams; Consumer views/default diagnostics/v2 sidecars; both
manual proposal results; semantic1–10 documents/replays; default replay/watch.
Baseline MP54 has the exact accepted-main tree. Semantic compatibility alone
uses unchanged new-game records reserialized to isolate the prior gap, separate
from the original-byte current/CLI proof.

Original files, identifiers, names, hidden data, maps, diagnostics and helper
drivers stay local/ignored. Independent source/method/privacy review does not
authenticate private bytes withheld from the reviewer. Exact-head review/tests,
doctor and head/identical-tree synthetic-merge CI receipts are recorded in the
Draft PR. No MTGA input/injection or new match; `input_sent=false`, `P10=NOT_RUN`.
No latency claim, main merge or repaired old product defect is asserted.
