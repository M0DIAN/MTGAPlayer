# Current Cast to four offered target members (MP64)

MP64 adds one opt-in observational relationship: the actual selected Cast was
consumed, its own Hand Card has an explicitly observed ID transfer to a public
Stack **Card**, and a separately authenticated first target request is current.
It reuses the existing four-singleton target validator and Candidate v2. It does
not add a target solver, response encoder, payment checker or execution path.

## Evidence and cutoffs

The source is the existing retained scrubbed-real
[`player_log_single_target.jsonl`](../tests/fixtures/player_log_single_target.jsonl),
not cryptographically reauthenticated private original bytes. Its provenance
and alias rules remain in THIRD_PARTY and
[the MP59 contract](current-cast-target-members.md). No source fixture changed.
Windows checkout bytes contain CRLF; fingerprints below use UTF-8/LF.

| Cutoff | Evidence available at that cutoff |
| --- | --- |
| 103 | Auth1/room2/seat2, genuine Full3/state1 and 99 continuous Diffs to state100. Request10100 offers eight active/two inactive rows. Cast position3 is own Hand1255/group97320/facet294, Blue1, one predictive route and slot1 members1243/1247/1257/1262. No target-count bounds. The whole current parent state/report is frozen here. |
| 104 | Exact original row position3 uniquely matches the actual PerformActionResp. Existing same-apply consumption and post-consumption pairing succeed. This is client selection, not acceptance/payment. |
| 105 | Accepted Diff101←100, exact ObjectIdChanged1255→1264 and CastSpell transfer from Hand113 to Stack105. Public own Stack Card1264 retains the known group. Old1255 moves to Limbo; it is not required to disappear from the reducer's raw map. |
| 106 | Fresh own request10102/state101/source1264, slot1, explicit min=max1, selected count absent, exactly four ordered Select members. Abort/undo=true. The child state/report is frozen before parsing107+. The ability group and targeting group remain separate namespaces; neither is inferred from the Cast's catalog/facet identifiers. |
| 107–110 | Separately, Select1262 consumes10102; Diff102←101 precedes fresh10104 with1/1/1 and Unselect1262; exact header-only Submit consumes10104. These support revocation only. |
| 111–113 | Later observations do not revive any consumed request or supply earlier constraints. |

The full113-record normalized file is68,174 bytes, SHA256
`723b6c4ba89a02874044afb1006ad7cf1507997cbc55436b6dc5ee75067a5b81`.
The103 prefix is60,858 bytes,
`1616b632532286f5437c4675c814a25a6a902b40e0de67c19308b37cafaf0c9d`;
the106 prefix is63,699 bytes,
`8787cab48fbfa46d5a74c499b42583f8d28ad58b4aeaf4e160f38e0405a5c82b`.
The [safe receipt](evidence/mp64-current-cast-continuation.safe.json) binds the
pre-implementation freezes. It is a producer execution record, not proof of
private original authenticity. Tests reuse this fixture rather than introducing
another source or inventing a real positive. All mutations/clocks/transport
envelopes are labeled synthetic.

## Distinct capability and version choice

MP59 already enumerates eight parent member probes across Cast1 and Cast3;
historical semantic Cast replay already sees later annotations. MP38 already
validates four current singleton proposals. None establishes this current
cross-request association. MP62 is an Activate/Battlefield→Stack Ability path,
with ability IDs and a single-member child. MP63/#79 revises that Ability child;
it cannot prove a Cast/Card relationship.

The strict State13/Consumer contract has no compatible container for this new
provenance. Explicit State/Event **15** therefore adds only nullable
`cast_choice_continuation`. The original MP64 candidate branched independently
from main while State/Event14 was reserved for unmerged #79. Local integration
registers both as parallel profiles without changing either PR; see
[integration preparation](mp63-mp64-integration.md). V15 retains v13 fields without the
v14 revision field. Older versions, schemas, candidates, Advisor and defaults
keep their values. Candidate v2 is reused unchanged.

The subordinate Cast context runs inside the same StageObserver and the single
RawFollower/RawReducer path. It caches one authenticated original inventory,
requires one exact unique selected row, pairs only after consumption, observes
one continuous Diff and then binds the fresh child. The producer checks typed
Card identity, own Hand/public Stack endpoints, explicit annotations, unique
zone membership and new-instance absence from the earlier raw object map.
The finite profile accepts the witnessed ordered four members, not arbitrary
menus or additional annotations. Portable replay checks consistency of that
attestation against current visible objects and the typed Stack projection;
it cannot reauthenticate raw annotations, earlier offers or source bytes.

## Read-only use and authority

```powershell
mtgaplayer replay <prefix-through-106.jsonl> --format player-log --decision-state-version 15 --current-cast-continuation
mtgaplayer watch <Player.log> --decision-events --decision-state-version 15 | mtgaplayer consume-events --current-cast-continuation
```

`replay` is offline research. Consumer reports additionally require a new append
observation, current snapshot/ref, live local transport and unexpired lease;
every proposal uses that child's own binding/ref, never the parent's.

`engine_offered=true` and `known_constraints_verified=true` describe only the
four provided alternatives and the request's explicit one-target bounds. All
complete legality/domain, full costs/payability/payment, rules causation,
acceptance, encoding, execution and input flags remain false. Missing tap state
is unknown. Other parent positions receive no observed continuation. The109
Unselect request is a separate current observation with no MP64 first-child
proof; this change does not implement Card-based selected-set submission.

Consumption104/107/110, replacement, unknown submissions, cancel/undo, conflicts,
retransmission, mixed records, wrong scope/source, Full/reset, discontinuity,
partial polls, pending-context limits, history-only observations, stale refs,
lease expiry and stop revoke/withhold this proof. The observer clears pending
lineage on a partial poll even when no current request exists. Quarantine lasts
through the entire rejected record, preventing later callbacks from rearming it.
Existing default target diagnostics remain separate when only the association
is unknown. Diagnostic `last_valid` never restores the Cast proof or proposals.

## Parallel continuation profiles

State/Event14 and15 are independent extensions of13. Version14 carries only
its required nullable revised field;15 carries only its required nullable Cast
field. Opt-ins require their exact version. One StageObserver retains one
RawReducer and both subordinate contexts: Cast observes before first, Revision
after first. First-only clearing preserves sibling prepared transitions; reset
and partial polls clear the contexts. Both Consumer diagnostics participate in
the final current snapshot/ref/lease recheck. Card/Ability, cross-subscription,
missing-parent and cross-path selection controls cannot borrow the other
profile's history. The repaired MP63 predecessor and retransmission guards are
retained. Old schemas/defaults remain unchanged.

Focused verification: `python -m unittest discover -s tests -p
test_cast_continuation.py -v`, then the required full suite and Windows
`mtgaplayer doctor`. Formal schema validation uses development tools only; no
runtime dependency is added. No MTGA input/game automation, P10 or latency claim.
