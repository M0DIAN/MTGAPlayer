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

## MP92: explicit Basic Swamp extension

`land_development_research.v2` adds one independently reviewed profile to this
same finite resource-development heuristic: unlinked primary Basic Land/Swamp,
single Subtype69/Loc653, Types5/Supertypes1/Subtypes69, TypeText261494,
SubtypeText653, empty RawFrameDetail, and the same strict empty ability/link/
extra-text fields and zero token/digital/rebalance flags. It does not interpret
every Land as an Island, support Mountain, rank competing land drops, or compare
all Cast/Activate tactics. The v1 Island predicate and all original policies,
including `unified_research.v1`, retain their existing outputs.

MP91's existing authenticated source is8,382,052 bytes, SHA256
`aa5cafb94467184c013539651a619a6101292e2cdf7225e619246aac16ea2e5b`.
Its93 accepted requests include39 startup history and54 append;50 distinct
completed-poll live opportunities include24 ActionsAvailable and4 SelectTargets.
Repeated frames are excluded. The owner rechecked all789 immutable segment
hashes/ranges and all50 frozen poll/request/ref/digest boundaries, then reused
the recorded current options/visible state/source audit. No GRE reparse, second
Reducer, additional real game or future response was needed for this analysis.

All24 first land refusals were reviewed. Two static identity gaps are different:
the solePlay106531 in opportunity42 uniquely resolves to the reviewed Basic
Swamp profile; solePlay96828 in opportunity28 is nonbasic Plains/Swamp with
hybrid framing and three explicit abilities. The latter's version-specific
static text includes paying2life or entering tapped, and is not supported.
All six Play CardIds were resolved with the existing native factory, including
its actual hash-before/after and unique typed enum/localization checks.

Eight multiple-Play refusals contain25 Play memberships, not25 requests; six
contain the new Swamp. They still abstain. Four structure refusals retain their
original first reason; two also contain multiple Play and two contain no Play.
Their frozen Activate shapes contain two mana-cost rows, one target slot and
two predicted auto-tap actions. Frozen shapes alone do not identify the exact
unreviewed inner semantic branch; no general action interpretation was added.
All ten original no-Play requests contain Cast/ActivateMana/Pass/FloatMana;
three also contain Activate. No automatic Pass inference follows.

All four target requests have a version-bound96854/191026 leaves-battlefield
fixed-base2damage instruction and complete mixed four-member domains: two
players plus two opponent-controlled public Cards86835 with current GRE P/T4/5.
One is tapped; the other has unknown tapped state. Corresponding static type is
Creature/Elemental, but this is not a current dynamic-type proof. With selflife9
and opponentlife20, absent reviewed marked damage/modification/tactical value,
neither player damage nor object damage has a verified comparison advantage.
MP89 retains all four abstentions; static toughness is not an actual-kill test.

The new policy reuses the current invocation's original v1 source/structure
audit and the same CurrentDecisionOptions. It extends only the two static/
ordinary-profile refusal cases, requiring a complete unique Play inventory,
matching request/ref, a unique own Hand source, exact native metadata, and the
same ownMain1/Stack gates. It additionally requires the existing current exact
build/resource capability. It runs inside the original Consumer owner and
completed-poll raw-stamp checks before/after calculation. No saved v1 report is
used in production. The pure internal extension can evaluate an old frozen
options/audit pair for offline research, which grants no live lease authority.

```python
runtime = LocalShadowRuntime(
    source,
    research_policy="land_development_research.v2",  # explicit; no new default
    prepared_rules=prepare_mtga_land_reference(
        local_catalog_path,
        [92359, 95062, 96828, 96839, 106531, 106533],
        expected_sha256="1be0105411ad989ca60e233f1341eaaa9276e3a679c89f1ef6f07e07ede10d25",
        expected_source_version={"Data": "2026.64.0.280", "GRP": "280.1327372"},
    ),
)
```

References must be prepared before creating the subscription. The explicit
v2 report records the selected current option, request/ref, static profile and
phase, while retaining unknown dynamic restrictions, land-drop limits, actual
mana benefit, stack emptiness and tactical opportunity costs. Source CardId,
list position and prior player choices are identity facts, never tie-breakers.
Multiple Play always abstains, including identical copies. Consumption,
replacement, expiry, partial/reset/gap, Cancel/Undo and stop revoke the result.

On all original50 frozen opportunities, original MP66 and MP90 stay0preference/
41abstain/9unsupported; original MP87 on24AA stays0/24/0 and MP89 on4targets
stays0/4/0. The separate v2 frozen-input research comparison on24AA is1preference/
23abstain/0unsupported. Its sole preference is opportunity42, before any later
response is consulted. Other26 request families are outside this land policy;
this is not a replacement unified-policy total. No historical agreement,
winrate, legality or strategy-quality claim is made.

See the [public retained projection](../tests/fixtures/land_swamp_real.README.md)
and [owner evidence receipt](evidence/mp92-owner.json). Runtime wiring/lifecycle
tests use explicitly synthetic transport separately from the real frozen
semantic positive. The independent reviewer does not personally certify owner-
private raw game bytes. MP91's2814 revocation-query samples still have aggregate
timings only; request-family and history/terminal subdivisions remain
NOT_RECORDED. No offline metric is relabeled as historical live performance.
The one unknown current_view_unavailable cause does not justify a product fix.

`complete_legality_verified=false`; `strategic_optimality_verified=false`;
`execution_ready=false`; `input_sent=false`; `P10=NOT_RUN`.
