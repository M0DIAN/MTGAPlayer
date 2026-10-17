# MP61: current Cast and Activate offered associations

Issue [#74](https://github.com/M0DIAN/MTGAPlayer/issues/74) extends one explicit,
read-only contract to retain independently checked Cast and Activate relations
from the same current request. Its authority is a finite **offered data
association**, not a payable action, final target set or client response.

Accepted handoff: main `2732c2a567e37e3864b1f76ce0bbafdc4e288861`, tree
`a2cd6cb5929a3e14bf9544872a342f548f4cd4f7`. MP60 found no request with both
existing strict profiles eligible. That result remains an evidence gap, not a
reproduced regression. MP61 adds a newly supported real Cast slice; it does not
claim that MP59 already accepted this request.

## Original-byte gate and review boundary

The owner-local reviewer reopened the frozen original, 7,718,945 bytes, SHA256
`6bab453be2830750af3983a70ce4843f747252ef950e1e4ced628785d7cfac07`, and the
request-only prefix, 7,664,967 bytes, SHA256
`e8a8732c67e8bd4a9c019ec042aae7d067efc54b7797576b8ce53b4d1ffd2635`.
The existing single RawFollower/RawReducer authenticated auth record 1136, room
record 1141, genuine Full1143:m1 and the continuous accepted state through
1402:m0 before own request1402:m1. There are 281 accepted state messages and
zero continuity errors in the checked new-game interval. Record ordinals are one-based; GRE message
indices and action positions are zero-based.

The same current request contains 17 active and 5 inactive actions. The five Cast
positions 0–4 remain in that denominator, including unsupported rows. The gate
inspected the complete original rows and their current source, target and
predictive mana witnesses before response1421:

| Original current offer | Finite observed relation |
| --- | --- |
| Cast1 and Cast3 | Each has explicit Black:1, one target slot with three public Battlefield members, and its own checked association to active mana10 |
| Active mana10 | The complete same-request row, predictive unit identity, color/count, option and selection agree with each reviewed Cast independently |
| Activate6 | The existing MP57 Generic2 target/predictive-payment association remains 1, with the independently checked active mana12 and mana14 witnesses |
| Cast2 | Its more complex shape remains unsupported; no result is borrowed from Cast1/3 |

Six Cast member alternatives and one Activate association are separate counts.
Shared witnesses do not make alternatives simultaneously payable. Target
minimum, maximum, selected count and complete legal domain remain unknown.
Current tap/readiness is unknown; neither omitted `isTapped`, a proto3 default,
nor an MP58 historical event supplies payment permission.

The original `prompt` is retained: exactly a nonzero uint32 `promptId`, with
`parameters` absent. Its unchanged appearance in 15 accepted ActionsAvailable observations is only correlation; retransmissions were not excluded.
The original target `highlight` fields are strictly typed strings and remain in
the new observation. Neither field is silently stripped to satisfy an old
parser. Their preservation is separate from the finite cost/member/mana checks.

Raw log bytes and installed DLL bytes were authenticated by the owner-local
root reviewer. Independent review inspected code, explicitly whitelisted
recovered source text, audit methods and safe receipts; it did **not** open the
withheld original logs or DLLs. Public fixtures and replay cannot authenticate
those withheld bytes. Response1421 and subsequent target, ManaPaid, resolution
or attachment evidence establish no pre-response quantity, payment or legality.

## Installed client and pinned external evidence

The checked installed live build is `0.1.14517.1329972`. Its owner-local
read-only recovery manifest has SHA256
`b04ae93c584893f7425ace86aec5055de8596f38db996c5e5389e79bf43cd9ad`.
Independent review matched both physical-file and normalized-LF text hashes for
all 62 successful recovered types. One failed empty output for the incorrect
type name `Wotc.Mtga.DuelScene.Interactions.WorkflowPrompt` is excluded; the
correct `WorkflowVisuals.WorkflowPrompt` was recovered separately. The root
reviewer rehashed the source DLLs after recovery and found no changes.

| Assembly | Installed SHA256 |
| --- | --- |
| `Core.dll` | `3e85d45e88b10a2fd3841e3abe6f5b37a17e0c42d360c93988e2270b4fdc858a` |
| `SharedClientCore.dll` | `42f2fb5f062ccc6098182a902d411746070759a404e875b6e0aac44d3b7ccc6e` |
| `Wizards.MDN.GreProtobuf.dll` | `7ca28480089cc2b21417abfea82b9c8721ff855f0369966858d70d58f2afcdae` |

External inspection is pinned to
[`ettrue124/ArcaneForge@45f27866c5dfd5891fc101c00e611a36254d2f49`](https://github.com/ettrue124/ArcaneForge/tree/45f27866c5dfd5891fc101c00e611a36254d2f49),
tree `8098d545963eff4ed2cdad2e555e55d27116f4be`. Its
[20261010 routing manifest](https://github.com/ettrue124/ArcaneForge/blob/45f27866c5dfd5891fc101c00e611a36254d2f49/analysis/arena-request-catalog-20261010/request-menu-mapping.json)
declares different hashes for **all three** assemblies:

| Assembly | Older catalog SHA256 |
| --- | --- |
| `Core.dll` | `947441eecc9a9231503af434ad7970e6af0bc2c56148d56991bba5b6c76458e6` |
| `SharedClientCore.dll` | `ff02a80282f36c45d6a639c6dc5013eff16406bce6eb0ef9985b59e1c3244b33` |
| `Wizards.MDN.GreProtobuf.dll` | `0170f35ec3af708871d41d6a6e939f8faf5972a18691f8c7ac168f3458bfc928` |

The separate, newer
[`action-inventory/actions.json`](https://github.com/ettrue124/ArcaneForge/blob/45f27866c5dfd5891fc101c00e611a36254d2f49/analysis/action-inventory/actions.json)
declares 2026-10-16 extraction and the three installed full hashes above. Its
193 Shared source files are byte-identical to the older catalog's 193 handler
files. The same directory's
[`adapter-coverage.json`](https://github.com/ettrue124/ArcaneForge/blob/45f27866c5dfd5891fc101c00e611a36254d2f49/analysis/action-inventory/adapter-coverage.json)
still declares older hashes. A directory name or matching manifest therefore
does not substitute for the installed-method inspection or establish independent
decompilation provenance. The older UI catalog supplies locations to inspect,
not current-build authority. Its own scope excludes complete asset-tree recovery
and live UI verification.

No third-party decompiled source, client binary, card database or asset is
copied into the repository or used as a product dependency. These pinned sources
are research references only; [THIRD_PARTY.md](../THIRD_PARTY.md) records that
boundary.

## Exact prompt routing and finite non-interference

The installed `BaseUserRequest` preserves the nonzero envelope prompt separately
from the request body. `ActionsAvailableRequest` copies the original active and
inactive lists; its translator sets that request as the pending interaction.
This is positive data-flow evidence, not a conclusion from a field name or a
search with no matches. The corresponding
[published request class](https://github.com/ettrue124/ArcaneForge/blob/45f27866c5dfd5891fc101c00e611a36254d2f49/analysis/action-inventory/sources/42f2fb5f062ccc60/GreClient.Rules.ActionsAvailableRequest.cs)
and [translator](https://github.com/ettrue124/ArcaneForge/blob/45f27866c5dfd5891fc101c00e611a36254d2f49/analysis/action-inventory/sources/42f2fb5f062ccc60/GreClient.Rules.ActionsAvailableRequestTranslator.cs)
are supporting references; the inherited installed implementations were also
inspected locally.

The complete installed `CannotTakeActionWorkflow` routing predicate is:

```text
inactive_count > 0
AND cancellation == AllowCancel.No
AND active_count == 1
AND active[0].type == Pass
AND (resolving_card != null OR (prompt != null AND prompt.id == 1134))
```

The nonnull resolving-card branch returns true independently of prompt. Thus
1134 is not the whole predicate. The
[pinned older translation](https://github.com/ettrue124/ArcaneForge/blob/45f27866c5dfd5891fc101c00e611a36254d2f49/analysis/arena-request-catalog-20261010/ui-sources/Wotc.Mtga.DuelScene.Interactions.ActionsAvailable.ActionsAvailableTranslation.cs#L270)
is a concrete counterexample to universal prompt irrelevance, and the installed
method was checked rather than assumed identical.

For this authenticated request, 17 active actions exclude that route regardless
of the numeric prompt; the observed prompt also differs from1134. There is no
OpeningHandAction. Active Activate6 excludes the all-resolution-Cast route.
The original action-source zones include Hand and Battlefield, neither remapped
by `IncludeNHCInHand`; this excludes all-Hand and single-zone routing. Battlefield
also excludes the supported multi-zone branch. Ordinary translation therefore
uses default ActionsAvailable **when loop/roundtrip do not preempt it**. This
conditional route statement is not a runtime observation of an open game UI.

The default workflow constructs `GreInteraction` from offered actions. Complete
`ClientSideInteraction`, `ActionProcessor` and `ActionSubmission` callbacks were
inspected: modal selection maps back to the existing interaction, while ordinary
submission unwraps its `GreAction`. The installed prompt provider/engine and
header providers return formatted text. `GameManager.FillAltBlackboard` does
expose the current workflow, request and prompt to asset predicates; request and
interaction PromptId evaluators can consequently affect asset selection. In the
inspected default/modal consumers, those results supply header/subheader text
or Pass-button text/style/SFX; the code supplies the callbacks. The source-card
indirector's typed `CardId` prompt-parameter branch is excluded here because the
actual parameter list is empty. UI display equality is not established.

Real action transformations remain explicitly outside the offered-data claim.
UI lists can be filtered, deduplicated or auto-selected. Batch mana submission
clones an action and removes unselected `ManaPaymentOptions`. The color-picker's
first gate requires every action to be `ActivateMana` with nonempty options, so
Cast1/3 cannot enter it. Its later `ManaSelectionFlow` response construction is
not certified by this audit; no stronger claim about mana10's UI behavior follows.
These facts prevent treating all eventual responses as unchanged original rows.

The supported conclusion is only that, in the inspected installed processing
paths, this exact parameters-absent prompt does not rewrite the two reviewed
original offered cost/member/predictive-mana associations. It does not prove
that every prompt is decorative, that all UI candidates are identical, or that
the offered association satisfies every instruction or rule of the game.

## Explicit additive contract and authority

Only State/Event **12**, request parameters **8** and candidates **6** enable the
new view. It reuses the existing finite single-unit route checks for Black1 and
the older Blue1 slice, plus the MP57 Activate association. Each family is checked
independently against one request binding, full original row identity/flags,
public source/member observations and its own active mana witness. The composite
retains the complete 17-row inventory so profile priority cannot hide Activate6
after Cast1/3 become newly supported. It is not a union of different games or
different request bindings, and it does not combine alternatives into a plan.

Unknown costs, modes/X, malformed or unsupported fields, hidden/off-Hand Cast
sources, unsupported target shapes and ambiguous/mismatching mana rows withhold
the affected association. Complete prompt observation and strict string
highlight preservation belong to the new contract; old strict parsers keep
their old rejection behavior. State/Event1–11, candidates2–5, old request
profiles, MP57 relation, MP58 tap evidence, manual validators, Advisor,
semantic1–10 and defaults are compatibility requirements, not permission to
reinterpret an old artifact as a new-profile positive.

All current results use the existing Consumer's exact session, request binding,
snapshot/ref and lease. Consumption, replacement, expiry, partial input, gaps,
reset or stop revoke the current view, with a post-assessment/output recheck.
Actual response1421 consumes the request; subsequent evidence must never revive
its old proof. No second reducer, board, request ledger or executor is added.

Complete payability, target quantities/domain/selection legality, complete
costs/payment, rules effects, response encoding, server acceptance and native
input remain unverified. Readiness remains unknown, `input_sent=false`,
**P10 NOT_RUN**; there is no real-action latency claim. This document records the
evidence and contract boundaries, not test, CI or PR completion.
