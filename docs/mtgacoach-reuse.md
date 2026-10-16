# mtgacoach reuse boundary for MP43

Project baseline: `902f69b419ee0b6d3536e07b2147d5275fe35b15`.
Preferred external source: `josharmour/mtgacoach`, fixed at
`2a9cab586ed120a9244f81834af72b7ab144be86` (tree
`72937c570da6df631a5363ebb43ad091ac1b8b6a`).

The targeted assessment supports reusing the upstream pure mana matcher when
verified current mana domains are available. It does **not** support inserting
that matcher into the retained MP43 nonmana payment. No upstream algorithm,
runtime dependency or execution capability is introduced. The implementation
following this assessment adds only semantic v9's historical sacrifice projection
through the existing collector; see [the contract](semantic-effect-cost.md).

## What the frozen real input establishes

The original stopped Player.log prefix is 5,625,878 bytes, SHA-256
`4e888a7d29a9ac7f25c5d7aabc9517d5042c260d4065fa6c136e64ae45b616af`.
Reading it with the existing RawFollower reproduces all 732 entries of the frozen
capture index (SHA-256
`79fc5df44a0a8620d7da1a8a9371e5a7130101b0b237e7af6b06e2c4067add5c`).
RawReducer accepts the state continuity and authenticates the current own request;
the existing response-consumption helper confirms the exact pair.

| Evidence | Established observation |
| --- | --- |
| record603/GRE0, state338, previous337 | The subsequently selected object is visible on the own battlefield. |
| record603/GRE1, PayCostsReq473/state338 | `paymentActions={}`; `EffectCostType_Select`; `SelectionContext_NonMana_Payment`; sixteen offered objects; explicit single nonrepeatable selection. There is no `manaCost`, `paymentSelection` or `autoTapActionsReq`. |
| record622, EffectCostResp473/state338 | The client submitted offered position1. The current request was consumed. |
| record623/GRE0, state339, previous338 | The first accepted continuous successor has `ObjectIdChanged` annotation745 and `ZoneTransfer` annotation746 with category `Sacrifice`. |
| Public endpoints and both annotations | The selected old object is absent afterward; its mapped new object is newly visible in the own graveyard. Public card identity agrees. Both annotations name the same source, independently visible on the stack at both endpoints. |

The finite conclusion is **the selected visible card's sacrifice was observed**.
The request has no verified source-object binding. The shared annotation source
is an observed affector, not permission to backfill the request source, identify
its parent Activate, or link the later Search by ordering alone. Complete payment,
complete legality, all additional costs and explicit server acceptance remain
unverified. ManaPaid annotations already present in state338 do not by themselves
prove completion of this later nonmana selection.

The capture index's byte references are **poll spans**, not precise per-record
offsets; record622 and record623 share a poll span. The record/GRE indices and
state/request identities establish the chain. Source and collection clocks are
not used to infer latency or causality.

An exact prefix ending at record603/GRE1 reproduces State6. Existing
ChoiceValidation accepts only the known count/membership/nonrepeatable constraints
for all sixteen current options, with payment completion and rules effects false.
The actual later outcome belongs only to position1; it supplies no outcome or
legality evidence for the other fifteen. Empty, repeated and nonmember proposals
are rejected by the existing validator. Historical semantic v7 and v8 still
report submission and a visible successor without claiming payment completion.

## Targeted upstream source comparison

All links below refer to the fixed commit, not a moving branch.

| Source | Useful implementation | Reuse decision for this input |
| --- | --- | --- |
| [gamestate_decisions.py](https://github.com/josharmour/mtgacoach/blob/2a9cab586ed120a9244f81834af72b7ab144be86/src/arenamcp/gamestate_decisions.py#L1050) | `_handle_pay_costs` separates mana requirements, automatic tap proposals, payment actions, pool selection and the presence of an effect cost; it clears older priority actions. | Architectural reference. Its coarse effect-cost flag does not preserve this selection/result chain, while our current parser already preserves the concrete domain and strict identity. No handler or GameState replacement. |
| [rules_engine.py](https://github.com/josharmour/mtgacoach/blob/2a9cab586ed120a9244f81834af72b7ab144be86/src/arenamcp/rules_engine.py#L269) | `_match_pips_to_sources` is a pure augmenting-path bipartite matcher. Each source index can satisfy at most one compatible pip. | First-choice algorithm for a future evidenced mana-assignment need. It cannot interpret nonmana selection, identity migration, sacrifice annotations or payment completion. No port for this episode. |
| [request_tracker.py](https://github.com/josharmour/mtgacoach/blob/2a9cab586ed120a9244f81834af72b7ab144be86/src/arenamcp/request_tracker.py#L160) | Content fingerprints, window context, in-flight suppression, bounded retries and outcome bookkeeping. | Do not import its lifecycle authority. A changed/absent fingerprint becomes ADVANCED, and an unchanged fingerprint after a grace period becomes REJECTED. Neither establishes our protocol-bound payment result or server acceptance. Existing reducer/Consumer gates remain authoritative. |

The matcher (lines269–302) uses builtins only. Its exact source-segment SHA-256 is
`79d756389eadf99b2a4cb99c36532d326e47377c13f0edaa51fab42944de048a`;
the containing file SHA-256 is
`ec62f0027a7323997a77ada3654a5b6e422f47cef6e8a18565ed0d57b3162fa5`.
Only this function's AST was compiled for investigation. The upstream package,
GUI, card database, runtime plugin, model services and input code were not loaded.

An independent exhaustive injective-assignment oracle agrees with the function
on 19,800 small abstract relation cases (zero through three pips and sources,
capability sets over W/U/C). These are synthetic mathematical controls, not new
real game evidence or complete MTG rules tests. Specific discriminating cases:

- W and U cannot both use one W/U source plus an incompatible C source.
- W then U can use sources W/U then W: the augmenting path repairs the first
  assignment, which a non-backtracking greedy assignment would miss.
- No pips returns true even with no sources. Applied to this nonmana request,
  that is vacuous matching, not evidence that a cost was paid.
- Negative pip counts are not validated by the function and also produce a
  vacuous result. A future adapter must reject malformed or unknown input first.

The positive benefit is avoiding duplicated multi-source matching logic and
double use of flexible sources. It becomes applicable only when current-request
evidence supplies the pip requirements and unique unit-capacity source choices.
Unknown inputs cannot become empty lists, inferred colors or zero costs. The
matcher has no physical source identity, generic-payment check, effect interpreter
or lifecycle authority; callers must establish those input contracts separately.

The surrounding `_get_mana_pool` derives capabilities from card names, types,
rules-text patterns, entering-turn/haste assumptions and floating mana.
`_can_afford` additionally treats certain Phyrexian/numeric hybrid symbols through
special-case shortcuts. These source assumptions are outside the verified
profile. Importing them would introduce a second rules authority; they are not
part of the proposed reuse. SelectN labels inferred from prompt keywords likewise
cannot establish this observed Sacrifice result.

## License and dependency finding

The pinned [pyproject.toml](https://github.com/josharmour/mtgacoach/blob/2a9cab586ed120a9244f81834af72b7ab144be86/pyproject.toml#L10)
declares MIT, and its [README](https://github.com/josharmour/mtgacoach/blob/2a9cab586ed120a9244f81834af72b7ab144be86/README.md#L59)
also states MIT. The inspected commit contains no standalone LICENSE/COPYING
file or copyright/permission notice in the three target modules. A future copied
algorithm must retain source attribution and the applicable MIT notice; do not
invent an upstream copyright notice or treat all bundled resources as covered
by the package metadata. No upstream source is distributed in this change.

The pure method requires no third-party dependency. Installing the entire package
would add MCP, watchdog, requests, audio/NumPy, keyboard, Qt and model/runtime
dependencies, which are unnecessary for the method and incompatible with this
project's independent stdlib-only product boundary. Python3.11 can run the method
without installing that package.

## Smallest useful MP43 implementation

The demonstrated benefit for this blocker is retaining the selected card's
explicit result without inventing complete payment legality. Semantic v9 uses
the following narrow historical-result projection:

1. An explicit new semantic export/replay version preserves exact v1–v8
   output. Use RawReducer's accepted-message observer and only the first
   continuous successor already retained by MP40.
2. It reuses the existing typed-annotation reader, scoped references, public endpoint
   projection and request/response consumption. Retain the selected-object
   mapping and explicit Battlefield→Graveyard Sacrifice facts, including their
   common observed affector and raw evidence references kept locally.
3. It requires consistent public endpoints and withholds ambiguous mappings, foreign or
   conflicting related transfers, missing annotations, wrong identity and state
   gaps. Do not add a second GRE parser, state machine or generalized effect engine.
4. It reports `selected_card_sacrifice_observed` as historical evidence. Complete
   payment, request-source binding, parent Activate and later Search causality
   remain unverified. The new sanitized real fixture is produced through the
   exporter; old v7/v8 artifacts retain their original values.
5. State6 and ChoiceValidation retain their existing current-request input contract.
   Join a historical result only to its recorded request identity and actual
   selected reference. Never feed state339 into a state338 proposal or validate
   another candidate using position1's result. No new DecisionState version is
   needed merely to label this historical outcome.

The inspected upstream files do not supply this strict result projection. There
is therefore no demonstrated benefit to adding upstream production code for
this particular change. The matching algorithm remains the preferred external
implementation once a real, supported mana-assignment domain makes it useful.

## Local reproduction

The ignored investigation is in `artifacts/local-mp43/assess_reuse.py`; its result
is `artifacts/local-mp43/reuse-assessment-results.json`. It checks the original
source/index hashes, exact reducer pairing and continuity, visible annotations,
the request-only State6/ChoiceValidation path, full real v7/v8 replay and the
isolated upstream matcher against the independent oracle. Run with the project
Python3.11 and this checkout's `src` on PYTHONPATH. The script depends on local
private evidence and is not a portable fixture or part of the installed product.

The assessment and the opt-in historical-result implementation are distinct.
Neither establishes a live payment evaluator, new live qualification, an upstream
full-suite run, a reproduced old defect or a P10 repair. Current validation
results and delivery status are recorded only in `docs/progress.md`.
