# Version-bound current player targets (MP84)

MP83 correctly retained unknown referents without a source-version bridge. The
legacy target projector requires visible Battlefield objects; players cannot
satisfy that contract. MP84 adds a separately namespaced, explicit current-owner
profile after establishing the missing version and entity-ID evidence. It does
not change the legacy object-only validator or the default candidate/policy data.

## Version gate

The pinned [ArcaneForge GreInterface source](https://github.com/ettrue124/ArcaneForge/blob/45f27866c5dfd5891fc101c00e611a36254d2f49/analysis/action-inventory/sources/42f2fb5f062ccc60/GreClient.Rules.GreInterface.cs#L269-L292)
maps `PlayerInfo.SystemSeatNumber` to `MtgPlayer.InstanceId`. Its blob is
`63c8e7f8eb8bb89d9c52dae58e0803e1bea27f1d`, also used by the current mirror.
The newer manifest declares the checked assembly hashes, but the same source
blob appears under older directories and adjacent adapter metadata is older.
The directory label and extraction date alone are insufficient version proof.

The owner verified the complete MP81 archive's line59 version header before all
42 first-current boundaries: full build `2026.64.0.14517.1329972`. Installed Live
release `0.1.14517.1329972` agrees. Fresh Core, SharedClientCore and GRE assembly
SHA256/MVIDs match the accepted pre-MP81 MP61 receipt and newer public manifest.
Finite PE metadata/IL inspection in those exact installed bytes establishes:

- Full-state player construction stores SystemSeatNumber in entity InstanceId.
- Avatar Model field/getter have type MtgPlayer; avatar InstanceId reads its Model.
- Target click eligibility passes entity InstanceId to a lookup comparing
  TargetInstanceId. Player/card lookup uses the same entity identity relationship.

The owner read bytes only, without loading or executing client code. No binary,
decompiled implementation, research dependency or game resource is distributed.
The [version receipt](evidence/mp84-player-target-version.json) pins full hashes,
method identities, signature evidence and provenance caveats. Independent review
examines public sources and whitelisted static evidence/safe receipts, not private
original bytes or the withheld installed assemblies. Exact historical binary
capture and absence of in-memory patches at MP81 remain unproven; this is a finite
build-level compatibility conclusion, not historical binary attestation.

## Current source witness and API

```python
options = consumer.current_decision_options(
    current_target_context=(same_reducer, accepted_message))
evidence = options['current_target_evidence']
```

LocalShadowRuntime uses its existing unique RawFollower/RawReducer and owner
thread. A small byte observer recognizes the one reviewed full version header in
the first16KiB. The same follower's existing prefix reread verifies its bytes;
incremental scanning rejects a second Version header anywhere in the stream.
Only owner-context watch increases that existing identity prefix from256 bytes
to16KiB. No extra file reader, GRE parser, state, ledger or runtime binary lookup
is introduced. The private capability belongs to that reducer, generation and
reset epoch; serialized JSON cannot transfer it to another reducer. Missing,
incomplete, duplicate, modified or unreviewed build evidence yields no player
role. Default watch/replay outputs and archive byte-observer metadata stay intact.

The explicit sidecar returns `mtgaplayer.current-target-request.v2` only for this
new role profile; the prior profile continues returning v1. No State/Event or
Candidate version is added. MP65 default options/coverage and MP66 inputs remain
unchanged. The legacy `object_refs` proposal cannot encode a player.

Each new member keeps its position and Select/Unselect literal, with one role:

| Role | Namespace | Identity |
|---|---|---|
| verified_player | version_verified_player_instance | verified player seat / instance reference |
| verified_public_object | public_game_object | current public Battlefield Card or Token reference and type |
| unresolved | unresolved_request_member | local position alias; no hidden identity |

Version evidence alone does not identify a member. Every request verifies its
current unique typed player list and rejects player/entity ambiguity, including
raw hidden-object existence and zone memberships. Hidden faces and properties
are neither read to establish a target nor exported. Zone IDs, card catalog IDs
and unique-ability IDs are separate namespaces; numerical equality there does not
create an entity match or conflict. A source using either player ID is rejected.
The source must independently be the current own public Stack Ability with
unique zone membership and both group literals matching. Source, slot, targeting
seat, explicit1/1 counts, prompts and operation structure retain strict checks.

Any unknown member remains in the result and prevents a complete Select domain.
Only an entirely reviewed all-Select list with no selected-count literal can use
the existing bounded target-subset enumerator. A truncated new domain emits no
partial proposal inventory. New proposals include typed namespaced referents,
request binding, snapshot ref and deterministic option key; their local verdict
is `verified_known_constraints`, and `research_eligible=false`. Full target rules,
effects, costs, execution, encoding, acceptance and tactical utility remain unknown.

Unselect-only1/1/1 records expose the current selected literal only. They never
become a Select domain, complete final submission or new proposal. Mixed
operations also cannot establish a complete Select domain.

Before/after guards recheck raw digest, accepted current request, typed continuity,
source/public identities, build capability, player list and collision witness.
The completed-poll frame fingerprint additionally tracks those role dependencies.
Consumption, replacement, partial, Full/reset, gap, interruption, stop, ref changes
or lease expiry revoke the whole current result. Exact retransmission cannot
restore consumed/interrupted evidence, and no last_valid/history is consulted.

## Real acceptance and compatibility

The owner reverified the complete one-generation217-segment MP81 archive:
3,225,997 bytes, SHA256
`1d75cd1b65ac868da1e9e0025032c7380317fcbf8669016a00fcb536e44a73ac`.
All367 framed records are complete. Denominators remain53 authenticated requests,
42 distinct original current opportunities and14 SelectTargets. Each opportunity
is replayed only through its original first-current completed-poll byte offset.
The first historical Mulligan is not recounted as a new append opportunity.

| New finite evidence | Actual count |
|---|---:|
| Previously unresolved target requests / memberships |13 /24|
| Version-bound player-target requests / memberships |13 /24|
| Distinct verified player referents |2|
| Remaining unknown memberships in these13 requests |0|
| Existing public Battlefield members alongside player choices |2|
| New complete local Select domains / local proposals |11 /24|
| Unselect-only requests / converted Select domains |2 /0|
| Truncated new domains |0|
| Complete target or action legality |unknown|

The [owner receipt](evidence/mp84-current-player-target-owner.json) records bounded
per-request counts and measured scope. Thirteen public aliased projections support
portable tests; synthetic authentication/Full wrappers do not authenticate the
private archive. No future responses are included in the projections or admitted
to their identity decisions.

All42 original full default options/policy results remain1 research preference,
33 abstentions and8 unsupported. All53 authenticated defaults, the complete
existing history report, and10 real JSONL sources/1,152 recordwise documents,
options, policy and Candidate2–6 returns match the base across783,470 leaf values.
Transport refs, source/version digests and timings alone are normalized. All41
append current frames and safe summaries match after removing only the13 new
explicit role sidecars; other target evidence and MP82 SelectN results remain.

One controlled replay plus three warm checks per new request measures added role
projection n52: p50 .4689ms, p95 .7227ms, p99/max .9201ms. Whole warm opt-in API
n39: p50 1.6089ms, p95 2.0273ms, p99/max 2.4109ms. Target completed-poll frames
n14: p50 13.4763ms, p95/p99/max17.8086ms. These nested same-process local samples
are not causal latency guarantees or a real MTGA three-second qualification.

Focused synthetic counterproofs cover version/owner/generation, raw namespace
collisions, hidden visibility, Card/Token/Ability distinction, partial domains,
typed proposal tampering, quantity/source/slot/seat, lifecycle and in-flight
changes. Independent review found and repaired typed-role omission, source-seat
ambiguity, late duplicate version headers, completed-frame hidden collision
freshness and same-valued float/bool raw source-group identities. The last was
found after the first candidate review, so that candidate's PASS/CI cannot
substitute the repaired HEAD's gates. Full Python3.11, doctor, exact-HEAD review and actual PR/main CI are
separate delivery gates; their precise revisions/results belong to PR receipts.

MP81 current_view_unavailable and historical Windows qualification root causes
remain UNKNOWN. `input_sent=false`; `P10=NOT_RUN`.
