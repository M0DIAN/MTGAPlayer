# Exact-build resources and limited target-effect research

MP89 adds explicit `target_effect_research.v1` alongside the unchanged MP66 and
MP87 policies. Its sole effect category is a version-bound, exact-ability fixed
BASE two-damage instruction. In a complete domain containing precisely the two
verified players on different teams, the finite research heuristic prefers base
damage directed toward the opponent over self. It does not predict actual damage
or compare the tactical value of damaging a public object.

## Recovered historical provenance

MP88 correctly stopped implementation when its finite investigation had not
identified the resource-version bridge. That negative investigation conclusion
is superseded by previously overlooked startup records in the original archive;
the uncommitted MP88 progress entry remains preserved in its separate worktree.
No discarded record or historical conclusion is silently rewritten.

The owner reauthenticated all3,225,997 archived bytes, SHA256
`1d75cd1b65ac868da1e9e0025032c7380317fcbf8669016a00fcb536e44a73ac`.
The first16KiB precede the original current opportunities and contain:

1. Line59: client build `2026.64.0.14517.1329972`.
2. Line78: request for the official matching
   `External_2026.64.0.14517.1329972-windows.mtga` resource pointer.
3. Lines84–86: one pointer entry, selection of
   `Automatic|Manifest_c98372b34219b5c4aa478e8bf296f5ee.mtga`, completion.

The retained manifest bytes have MD5 exactly matching that recorded content
identity, and SHA256
`908abd96f922ad0e90c802863640cc0ac1f9df25f40fa618171bf78ca9849a5e`.
Its unique raw card-database entry specifies259,883,008 bytes and SHA256
`1be0105411ad989ca60e233f1341eaaa9276e3a679c89f1ef6f07e07ede10d25`.
The actual read-only database independently matches both, with Data
`2026.64.0.280` and GRP `280.1327372`.

This is a direct startup resource-selection chain, rather than matching version
prefixes, timestamps, DLL hashes or later game results. Independent review read
only specified startup metadata from the bounded prefix, plus actual manifest
and database bytes. It does not claim to authenticate all private gameplay bytes.
The pointer response was not separately retained; the bridge relies on the
official client's archived selection record and MD5 content identity. It is
trusted historical resource applicability, not cryptographic historical runtime
attestation or evidence against malicious file substitution/in-memory changes.

New finite searches also covered pre-MP81 receipts, installer/version/download
metadata and known cache locations once. Those separately corroborate installed
build or selected resources; their timestamps and coexistence are not used as
the provenance bridge. No full-disk search or online resource download was used.

## Exact effect and current target evidence

The original53 authenticated requests /42 opportunities /14 SelectTargets and
their first-current poll cuts remain fixed. Twelve target domains are complete.
Eleven have current public own Stack Ability sources. Each exact source group,
public `objectSourceGrpId`, request/slot group, type, zone and ownership is checked.
The version-reviewed client/provider namespace bridge is reused; neither a
numeric player ID nor a prompt parameter enters the catalog lookup.

The two actual definitions are1553/catalog90673 (enters) and191026/catalog96854
(leaves the battlefield), each a fixed two-damage any-target BASE instruction.
The distinct same-card172054 sacrifice-to-Golem ability is retained and cannot
borrow the damage definition. The191027 outer token-creator embedding is also
retained; it is not itself treated as a numeric damage modification. Modes, X,
cost fields, links, generic and card-specific text must match the entire reviewed
literal profile. Unknown variants fail closed. Card103460/26818 and its existing
single-object domain are not admitted to this effect policy.

Both mixed domains retain all three alternatives (two players and one public
object) and abstain. Nine complete domains contain the two verified players.
Two Unselect-only requests abstain; an already selected literal is not a fresh
domain. Relevant current player/life/team facts are independently typed and bound.
Utility uses relative affiliation only, never target number/order, name or
historical choice. Equal or unreviewed alternatives cannot be arbitrarily ranked.

## API, currentness and compatibility

```python
from mtgaplayer.rules_index import prepare_mtga_target_effect_reference
from mtgaplayer.shadow_runtime import LocalShadowRuntime

reference = prepare_mtga_target_effect_reference(
    local_catalog_path, [90673, 96854],
    expected_sha256="1be0105411ad989ca60e233f1341eaaa9276e3a679c89f1ef6f07e07ede10d25",
    expected_source_version={"Data": "2026.64.0.280", "GRP": "280.1327372"},
)
runtime = LocalShadowRuntime(
    source, research_policy="target_effect_research.v1", prepared_rules=reference,
)
```

Preparation reuses `PreparedRulesIndex`, bounded exact queries and hash-before/
after read-only SQLite. Hot policy lookup performs no I/O. The existing byte
observer recognizes the reviewed startup source from the same RawFollower.
Unknown, duplicate, late or changed resource selections invalidate this separate
capability, while the MP84 build-only contract remains unchanged. The two actual
General Audio/Localization selections are allowed only in their reviewed early
position; they cannot authorize a different main manifest.

The policy reuses current MP84 evidence through the original Consumer, then
checks the original completed-poll stamp and current request/digest/match/game/
seat/ref/lease before and after work. Public source catalog and player/resource
facts join that internal stamp. Consumption, replacement, cancellation/undo,
partial, reset, gaps, expiration, stop and concurrent state changes revoke the
result. There is no second state, request ledger, result cache, GRE parser or
response encoder. MP84 local proposal keys remain separate from unchanged MP65
default inventories and from default MP66 research eligibility.

## Actual historical research result

Across14 current target requests:9 research preferences /4 abstentions /
1 unsupported. Eleven exact effect instances were identified; nine were eligible
for this heuristic. All14 later strict consumed target updates/terminal requests
immediately revoked their old research result.

Only two preferences have a fully linked, consumed update→independently current
revision→terminal stage suitable for complete-set comparison. Both agree; zero
disagree. Seven other preferences and twelve of all14 requests are uncomparable
under that strict unit. A selected member update alone is not silently promoted
to a final submitted set. The heuristic was fixed before examining later choices;
none were training/tuning labels. This single historical game is not an independent
policy-quality evaluation, correctness rate, win rate or optimality result.

Default MP66 remains1 preference /33 abstentions /8 unsupported, and MP87 remains
1 /12 /0 across its13 ActionsAvailable requests. Existing MP85 stage and MP86
source-lineage counts remain unchanged. Exact local tests, compatibility and
performance results are recorded in the companion owner receipt; final candidate
review, two-platform CI and natural main push CI remain separate delivery gates.

Actual damage, prevention/replacement/dynamic effects, tactical opportunity cost,
full legality, server acceptance, encoding and strategic optimality remain unknown.
All execution/verification permissions remain false. Historical AutoTap, Windows
qualification and MP81 current_view_unavailable roots are unchanged.
`input_sent=false`; `P10=NOT_RUN`.
