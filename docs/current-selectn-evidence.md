# Current choice-domain coverage (MP82)

The new evidence is an explicit read-only observation over the existing owner
thread, single RawReducer, Publisher and Consumer:

```python
options = consumer.current_decision_options(
    current_selectn_context=(same_reducer, accepted_selectn_message))
evidence = options['current_selectn_evidence']
```

`LocalShadowRuntime` dispatches the same observation for TriggeredAbility after
its complete-poll current gate. Old Resolution frames retain empty local
evidence. The CLI safe summary exports only status and whitelisted counts.
Default MP65 options and MP66 policy do not incorporate these opaque members.
State/Event1–15 and Candidate2–6 are unchanged.

## Evidence and scope decision

The owner reverified the MP81 MP77 archive: one complete generation, 217
contiguous segments, 3,225,997 bytes, SHA256
`1d75cd1b65ac868da1e9e0025032c7380317fcbf8669016a00fcb536e44a73ac`,
367 framed records, no partial tail or framing error. Its 53 authenticated
requests, 42 distinct completed-poll current opportunities and 396 repeated
current observations remain different units. Older164 is a separate cohort.

All 14 current SelectTargets and seven current SelectN were investigated at
their original MP81 first-current **source byte offsets**, using only the
original bytes through that completed poll. A controlled runtime initializes
with the first Mulligan as history, then reproduces the following41 current
prefixes; it does not turn that historical baseline into a new opportunity.
All21 investigated choices are among those41. Separate first-acceptance
comparison matches all42 original full default options and policies. These
controlled replays are historical simulation, not new live opportunities.

SelectTargets was investigated first. The one already supported request has
an own public Stack Card source and one public Battlefield Select member;
its complete local proposal and original research preference remain intact.
The other13 requests all have an own public Stack Ability, a typed targetIdx,
self targetingPlayer and explicit min=max1. Eleven contain Select entries:
two have one public Battlefield member plus two unresolved references, and
nine have two unresolved references. Two instead contain only an unresolved
Unselect literal with selectedTargets1; these are current selected-state
observations, not new complete Select domains. Across those13 there are24
unresolved memberships and two public Battlefield memberships. Their missing
identities cannot be discarded to manufacture complete proposals.

The existing strict source joins pass. The supported Card request has distinct
source and targeting group roles; their unequal values are not a contradiction.
No reviewed source/type/zone contradiction was found. All13 gaps require
unknown reference identities or unproved selection roles in addition to any
first cancellation/profile rejection. Existing MP74 checks still reject them;
changing a cancellation check alone cannot establish member identities.
SelectTargets code and proposal boundaries are unchanged in this task.

Two SelectN requests already use the old Resolution profile and retain their
three offered options each. The five others have a different real profile:
TriggeredAbility / Stacking, InstanceId / Dynamic / NonRepeatable, exactly
eight payload fields, unique positive uint32 references, explicit minSel1 and
maxSel equal to the offered list length (2,3,3,6,10). All24 references are absent
from the respective current visible projections. The old Resolution and
Discard validators correctly refuse this different context/shape. This is the
one request family extended in MP82, because its current list structure and
explicit bounds can be verified without guessing object identities.

The [bounded owner receipt](evidence/mp82-choice-domain-owner.json) records
per-request classifications, actual comparison units and measured timings.
The [portable fixture](../tests/fixtures/current_selectn_triggered_real_v1.README.md)
retains five aliased request-only projections, not raw authentication envelopes.
Independent reviewers can check these public projections, code and safe
receipts; they do not claim to authenticate private original bytes.

## New finite evidence contract

`mtgaplayer.current-selectn-evidence.v1` accepts only the reviewed exact
envelope/payload fields and enums, own seat, typed positive message/state IDs,
existing finite prompt syntax, 2..64 unique positive uint32 members, minSel1
and maxSel equal to the offered member count. A visible-object collision is
outside this unresolved-member profile and stays unreviewed. Unknown extra
fields, contexts, weights, repeats, mixed operations or inconsistent bounds
fail closed. No existing Resolution/Discard validator is relaxed.

The result separates these concepts:

| Field | Reviewed meaning |
| --- | --- |
| engine_offered_members | Position aliases in this exact request/ref |
| reviewed_visible_members | Empty; no reviewed visible object identity |
| unresolved_member_references | The same offered aliases, identities unknown |
| observed_quantity_bounds | Explicit minSel/maxSel literals only |
| current_selected_literals | null; none supplied in this profile |
| reviewed_local_proposals | Empty; no complete combinations established |
| unknown_combination_constraints | Order, combinations, weights, rules and tactics unknown |

Every returned alias carries the original current request binding and snapshot
ref. `IdType_InstanceId` describes the encoding; it does not join those numbers
to cards, abilities, seats, request IDs or catalog IDs. Original numeric member
references are not exported. Hidden raw objects are never consulted to fill
their identities. Counts of unresolved members and total offered members remain
separate from returned aliases and truncation.

`current_local_constraints_verified` covers unique typed offered references and
explicit minimum/maximum **structure only**. It does not mean that all counts,
orders or subsets within those bounds are legal. Absent source, cancellation,
weights, unfiltered domain and prompt meaning remain unknown. No permutations,
Cartesian products, response encoding or new complete proposals are produced.
`complete_proposal_count=null` and `complete_legal_actions=null`; an empty
returned proposal list is not zero legal choices. `research_eligible=false`
and all execution permissions remain false.

The pinned public descriptor's enum labels were checked at
[ArcaneForge45f2786 actions.json](https://github.com/ettrue124/ArcaneForge/blob/45f27866c5dfd5891fc101c00e611a36254d2f49/analysis/action-inventory/actions.json),
blob `67ee1165147d21a8cf34c901348be164ff14eeb9`, SHA256
`52c2e3074d3487526c1266746b0adb3f846a175fcbabb7f15090051de65d6301`.
This verifies labels, not complete ordering semantics or an installed-client
execution path. No client decompilation, game resource or runtime dependency
is introduced.

## Currentness, comparison and validation

Before and after projection the same authenticated raw digest, current request,
self seat/match/game, typed Full/Diff continuity, visible projection and Consumer
snapshot/ref/lease must agree. The existing single Reducer gains a private
SelectN interruption flag, stripped from old documents. Cancel/Undo/nonUI,
mixed or broadcast input, Full/reset, gaps, consumption and retransmission
cannot restore interrupted evidence. Runtime also rechecks its full completed
poll fingerprint. Partial, stop, replacement and mutation during computation
discard the current frame. Cache hits still pass currentness checks and never
cache the optional evidence as authority.

The five new requests each have a later strict Reducer-consumed SelectNResp
pair; the two old requests also have strict pairs. These seven header/consumption
matches are counted only afterward via existing ResponseEvidence. They do not
decode complete final ordering/choice semantics, backfill earlier members or
prove acceptance. Historical final-choice comparison remains null.

Direct counterexamples cover strict shapes/types, hidden Card/Ability and
numeric namespace collisions, visible collisions, duplicates, count conflicts,
wrong digest/seat/match/game, truncation and lifecycle changes. Independent
pre-review found a missing nonUI interruption entry point: the runtime frame
was revoked but an explicit API call could recover old SelectN evidence.
The SelectN nonUI entry now uses the existing interruption mechanism, with
Cancel/Undo/unknown-payload and retransmission regressions.
An additional independent mutation check found that the explicit API also
needed the accepted-state digest comparison already enforced by the runtime.
The projection now freezes and rechecks its bytes digest; the standalone API
and complete frame both reject a digest change during computation. The visible
ID set is built once, without repeated member-by-member state projection.

The owner compares complete default documents/options/policies on ten existing
JSONL sources (1,152 record observations), all53 authenticated source requests,
the original42 defaults, and the full prior opt-in historical report. Transport
refs, code/version digests and timings are normalized;472,380 leaf values match.
The original42 policy partition remains1 research preference /33 abstentions /
8 unsupported. No new research preference is created.

Added-only projection timings and complete local frame timings are recorded
separately, including old-profile rejection, abstention, unsupported and revoked
cases. Five new-prefix frames plus25 warm explicit reads give30 observed
projection samples. The full-frame comparison has41 current prefixes, with the
first Mulligan deliberately excluded as startup history. Small samples and
shared-machine noise do not establish a general speedup or real MTGA latency.
The accepted MP81 live baseline is preserved separately. Its one
`current_view_unavailable` and historical Windows qualification root cause both
remain UNKNOWN. input_sent=false; P10=NOT_RUN.
