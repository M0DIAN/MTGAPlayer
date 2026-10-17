# MP53 current request evidence

Issue59 starts from accepted main
`45893038f74d6ebc4fabdbf2c6c5d454ef110b2d`, tree
`9a24751b88e381da56eb359da91207627dcf08ca`, freshly fetched before branching.
The owner-local source and portable projection are pinned in the
[fixture provenance](../tests/fixtures/decision_state_activate_target_member_real_v7.README.md).

The useful change is one explicit current contract, State/Event7 carrying
request-parameters v4 `current_public_activate_target_member`. It reuses the
accepted RawReducer request/digest, seat and Full/Diff continuity gates, existing
target-menu row parser, ability observation, frontier/graph, proposal checker
and Consumer. It adds no parser, reducer, response ledger, general target solver
or input adapter. State/Event1–6, semantic1–10, default projection and observed
menu v2 retain their accepted behavior.

A proposal names an original row position, exact source/card/facet/ability-group/
unique-ability identity, target slot and one explicit public reference. The
current complete row inventory retains unsupported alternatives as opaque shapes.
Only strict public object plus agreeing unique public Battlefield membership can
enter a reviewed menu. Unknown/ambiguous ability lists stay insufficient; explicit
source-group contradictions are scoped known violations. Source ownership and
control must both agree with self. Duplicate target/action identities, hidden or
crossed references and unreviewed target keys/types cannot certify a menu. The
only newly accepted presentation field is a string highlight, whose value is
discarded. This pre-response acceptance does not rely on MP52's post-response
exact-match permission. Existing graph slot/count observations must agree with
the new menu; they never supply selection bounds.

`verified_known_constraints` checks this row's source/ability/slot/member relation.
It leaves target quantity insufficient, all complete legality/payment/domain/
response/acceptance/input flags false, and future parameters unknown. A slot or
explicit-membership mismatch is a violation of this limited observed relation,
not proof of global target illegality. This profile does not enumerate final
target sets; known-choice enumeration returns an explicit proposal requirement.

The owner-local real verification used original byte slices from one immutable
source, not reserialized positives. Byte ranges use zero-based start/end-exclusive
offsets. Source SHA256 is
`6bab453be2830750af3983a70ce4843f747252ef950e1e4ced628785d7cfac07`.

| Stage | Original records | Byte range | Result |
| --- | --- | --- | --- |
| Watch startup | 1136–1401 | 6320585–7647248 | Auth/room/genuine Full; history supplies no new opportunity |
| Request append | 1402 | 7647248–7664967 | 17 positions; position6 member verified before response |
| Intervening append | 1403–1420 | 7664967–7674282 | Original records retained; old request still current |
| Actual response append | 1421 | 7674282–7676983 | request_consumed invalidation in that poll; old proposal insufficient |
| Target/result append | 1422–1428 | 7676983–7716339 | Old proposal remains insufficient |
| Remaining observed suffix | 1429–1433 | 7716339–7718943 | Different request; old proposal remains insufficient |

Startup-slice SHA256:
`ea1413f6186c06e27cf8f95a4c480bfba5d43c04a6781cf54eb974cae068662f`.
The two trailing original non-JSON bytes after record1433 are irrelevant framing
text, not a missing GRE record. The full source hash remains unchanged.

Both the deterministic watch_decision_events→Consumer path and two independent
product CLI processes verified the sequence on the same append file and Consumer
subscription. The CLI run loaded its explicit proposal before subscription,
used80 polls at50ms and a30s local observation-age policy, then naturally stopped
with watch/consumer exit0. Default5s expiry was also observed in an earlier longer
driver run; it correctly refused the retained reference and was not a product
failure. No observation establishes server timing or <3s gameplay.

Afterwards, standard v10 export/replay of the frozen original independently
verified one actual historical episode, selected_position6, original
request1402/msg1→response1421 and matching selected literal. Other16 positions
receive no historical outcome. Portable State snapshots only test their own
sanitized contracts; private authentication is owner-local and has not been
independently authenticated by a reviewer without the private bytes.

Separate baseline/candidate Python processes compare complete values: all
State1–6 projections at179 current-request record endpoints each, full semantic
documents/replays1–10 on the same genuine new-game records, and default replay/
watch on the exact prefix are equal. Semantic v10 still exports/replays exactly
one episode. The semantic comparison input is explicitly a reserialized unchanged
record range for collector compatibility, separate from original-byte lifecycle
verification. No old real-product defect or P10 repair is claimed.

Focused falsification covers bindings/digest, parent/pair ambiguity, raw/public
visibility, duplicate references/rows, slot/member mismatch, string-only highlight,
unsupported quantity fields, Boolean identities, source-group and graph
contradictions, alternative response borrowing, request replacement, partial/gap,
history, stop and both observation/silence leases. Exact-head testing, independent
review and head/synthetic-merge CI receipts belong to the draft PR; no main CI or
merge is claimed for this task. All raw logs, private CLI/State outputs, maps and
drivers remain ignored and owner-local. No real MTGA input was performed.
