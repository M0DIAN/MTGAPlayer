# Evidence-grounded land-development research

MP87 adds the explicit `land_development_research.v1` policy alongside MP66.
It proposes a finite resource-development preference when the current engine
offers exactly one reviewed ordinary land Play. It does not rank all competing
Cast/Activate actions, prove optimality or complete legality, encode a response
or send input. The original MP66 decision remains a separate unchanged result.

## Real evidence and the supported profile

The original MP81 archive is 3,225,997 bytes, SHA256
`1d75cd1b65ac868da1e9e0025032c7380317fcbf8669016a00fcb536e44a73ac`.
Its verified one-generation archive and original first-current poll cuts retain
53 authenticated requests /42 current opportunities /13 ActionsAvailable.
The older164-request cohort is excluded. All13 active inventories were audited,
including all8 Play rows across5 requests, rather than only the later5 selected
Play rows. All8 sources are unique currently own-visible Hand Cards with exact
source/CardId agreement. Their Play shapes have precisely the existing five
reviewed fields. Competing rows and their original positions are retained.

The existing official offline SQLite metadata source is 259,883,008 bytes,
SHA256 `1be0105411ad989ca60e233f1341eaaa9276e3a679c89f1ef6f07e07ede10d25`,
Data `2026.64.0.280`, GRP `280.1327372`. Four exact CardIds resolve uniquely:
92359,92360,95062,96839. Each has the unique typed CardType→localization bridge
to Land. The source label alone is not authentication; actual bytes, versions,
schema, unique enum/localization rows and the selected source records were
checked. No network download, fuzzy name lookup or client-code execution is
used. A new native source format preserves this provenance without pretending
the data is Scryfall.

The first ordinary profile is deliberately limited to the observed unlinked
primary Basic Land/Island metadata: single reviewed type/supertype/subtype
bridges, no linked faces in either direction, non-token/non-rebalanced/
non-digital records, and empty explicit extra mode/text/frame/ability fields.
Other three Land records have unreviewed hybrid/ability data and are not admitted.
The exact predicate uses properties rather than CardId, action position, card
name or historical choice. Empty explicit abilities do not exclude intrinsic
mana abilities. No `normal` layout or current face is invented.

## Currentness and heuristic scope

The supported phase is explicit own Main1 with typed turn number, active player,
decision player and priority player. The observed step is missing. It remains
unknown; an explicit unreviewed or contradictory step is rejected. Unknown
Stack is not empty Stack. A known nonempty Stack rejects this narrow profile;
unknown Stack is an unresolved legality constraint, not an inference of legality.

Only the reviewed header/ActionsAvailable/parameters-absent Prompt shape is
admitted. Prompt meaning and general routing remain unknown. This does not
classify Prompt as harmless or fix MP66's unknown-request-fields gate. All Play
offers must be reviewed; an unknown competing Play cannot be filtered away to
manufacture uniqueness. Multiple Play rows always abstain, including identical
land copies. Unknown action fields, unsupported structure, coverage truncation
and identity conflicts fail closed. Known partial complex actions retain their
unknown costs/targets and tactical value. The heuristic assumes that developing
the uniquely reviewed basic resource is worth studying; it does not claim to
have compared every competing action's utility.

The policy reuses CurrentDecisionOptions, the static-rule context and the same
Consumer request/ref/lease gates. Runtime supplies its existing completed-poll
raw stamp. Taking a new stamp inside a detached helper cannot authenticate an
older Consumer snapshot. Raw/current source and turn facts are checked before
and after computation. Consumption, replacement, retransmission, partial,
Full/reset, gap, expiration, stop and changes during calculation revoke the
result. No result cache, second state, Reducer or request ledger is added.
The new report checks the existing Consumer's owner identity; default Consumer
behavior is unchanged.

## Explicit local API

Prepare the explicit local reference before starting the subscription:

```python
from mtgaplayer.rules_index import prepare_mtga_land_reference
from mtgaplayer.shadow_runtime import LocalShadowRuntime

reference = prepare_mtga_land_reference(
    local_catalog_path,
    reviewed_card_ids,
    expected_sha256="1be0105411ad989ca60e233f1341eaaa9276e3a679c89f1ef6f07e07ede10d25",
    expected_source_version={"Data": "2026.64.0.280", "GRP": "280.1327372"},
)
runtime = LocalShadowRuntime(
    source,
    research_policy="land_development_research.v1",
    prepared_rules=reference,
)
```

Preparation uses a bounded exact-ID subset, read-only immutable SQLite queries,
source hash before/after reading, and the same PreparedRulesIndex container.
The original Scryfall preparation/loading APIs stay unchanged. Strategy calls
perform no filesystem, SQLite or network I/O. The current version recognizes
only the reviewed native source pin; missing cards or unknown versions abstain.
There is no required installed client, database or private runtime for default
operation or public CI.

Opt-in frames add an independent `research_decision` with status, reason,
policy version, current binding/ref, the original option_key, static source,
phase evidence and unknown constraints. The default `shadow_decision` is not
overwritten. Local detailed reports contain current local references;
`safe_summary` exports only bounded whitelisted status/reason/count data.
All strategic-optimality, payment, complete-legality and execution verification
flags stay false. Historical MP84–86 facts never grant current strategy rights.

## Historical comparison and limits

The owner froze each of the13 current research results before applying the next
record. Measured outcomes are1 research preference /12 abstentions /0 unsupported.
The one preference is aa-10; aa-1/2 retain multiple Play competition. Reasons are
multiple Play2, no Play6, unsupported ordinary profile2, unsupported active
structure2, and the research heuristic1. Eight offered Land memberships are
static-verified; only one request is eligible for the new heuristic.

All13 later responses are uniquely paired and Reducer-consumed, with immediate
research revocation. Five selected Play. One frozen policy preference is strictly
comparable and agrees with the actual Play; the other4 selected Play have no
comparable preference. Across all13 actual selections,12 are uncomparable.
An agreement is not correctness, win rate, actual resource benefit or optimality.
The original42 MP66 results remain1 preference /33 abstentions /8 unsupported.
MP85 stages and MP86 source genealogy retain their separate evidence grades.

## Validation and measured local cost

Local Python3.11 passes1,189 full tests (182.879s), including18 new direct tests;
the focused16-module batch passes218 tests (39.651s). Windows doctor passes
without input. Complete affected legacy outputs match the accepted base across
825,554 leaf values: ten real JSONL sources/1,152 record observations, all53
authenticated defaults, existing full history reports and41 completed append
frames/safe summaries. Normalization covers transport refs, source/version
digests and timing, rather than semantic fields. Separate committed-candidate
review and actual Linux/Windows CI remain required delivery gates.

One uninstrumented production Runtime replay uses the real local performance
clock and the original cuts. Milliseconds:

| Measurement | n | p50 | p95 | p99 | max |
|---|---:|---:|---:|---:|---:|
| Added policy, ActionsAvailable |13|5.9843|11.6227|11.6227|11.6227|
| Full local poll→frame, ActionsAvailable |13|52.4883|121.4738|121.4738|121.4738|
| Publication→frame, ActionsAvailable |13|34.1546|55.8480|55.8480|55.8480|
| All incremental poll→frame |41|17.7121|81.5221|121.4738|121.4738|
| Cold historical startup |1|223.7980|223.7980|223.7980|223.7980|

One-time reference preparation takes382.8415ms before creating the Consumer and
is excluded from hot policy/frame timings. The correctness replay separately
uses logical lease time for historical-boundary checks; its zero timing values
are not performance evidence. No repeated long benchmark or real game is used.

The [owner receipt](evidence/mp87-land-development-owner.json) and
[public projections](../tests/fixtures/land_development_real.README.md) distinguish
owner-authenticated raw game bytes from independent public-source/static-data
review. Controlled replay proves neither historical wall-clock leases nor actual
MTGA end-to-end timing. MP76 AutoTap evidence remains blocked; historical Windows
qualification and MP81 current_view_unavailable causes remain UNKNOWN.
`input_sent=false`; `P10=NOT_RUN`.
