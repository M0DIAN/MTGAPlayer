# Goal-conditioned Cast research

`cast_cardflow_research.v1` is an explicit read-only policy for the goal
`conditional_card_flow_research`. It researches one uniquely reviewed offered
Cast as a prospective source of a conditional enters trigger. Its comparison
scope is `goal_conditioned_heuristic_only`, not a ranking of all actions.

The single reviewed profile is official catalog96626, specific ability190898,
for build `2026.64.0.14517.1329972`. The existing MP89 resource witness binds
that archived build's manifest to catalog SHA256
`1be0105411ad989ca60e233f1341eaaa9276e3a679c89f1ef6f07e07ede10d25`,
Data `2026.64.0.280`, GRP `280.1327372`. The exact native metadata, generic and
specific texts, and separate activated ability190899 are checked together.
The base instruction draws one card when the artifact enters or leaves the
battlefield. The Cast heuristic researches only the prospective enters branch;
it never counts a future leaves trigger as another Cast benefit.

This establishes neither immediate Cast-draw, successful resolution, an actual
trigger nor net hand gain. Dynamic characteristics, trigger suppression,
replacement effects, future choice stages, payment, acceptance and strategic
opportunity costs remain unknown. FloatMana's resource value remains `null`.
The MP94/95 Pareto investigation is preserved and is not used for this policy.

## API and finite gates

Prepare the reference offline, before starting the same existing runtime:

```python
from mtgaplayer.rules_index import prepare_mtga_cardflow_reference
from mtgaplayer.shadow_runtime import LocalShadowRuntime

cardflow = prepare_mtga_cardflow_reference(
    local_catalog_path, [96626],
    expected_sha256="1be0105411ad989ca60e233f1341eaaa9276e3a679c89f1ef6f07e07ede10d25",
    expected_source_version={"Data": "2026.64.0.280", "GRP": "280.1327372"},
)
runtime = LocalShadowRuntime(
    player_log_path, research_policy="cast_cardflow_research.v1",
    prepared_rules=cardflow,
)
```

The factory reuses the existing native card-metadata loader and
`PreparedRulesIndex`. It reads only the one card's two ability definitions and
four exact localization rows in addition to the metadata. Hash/versions and
file identity are checked; current lookup does no SQLite, file, network or LLM
work. Missing, changed or ambiguous definitions cannot authorize research.

Current evaluation requires the same owner-thread authenticated self request,
complete ordered active inventory, MP65 identities and visible state. The
source must be one own-visible Hand Card with matching catalog, unmodified
overlay/type and exact current ability groups190898/190899. The offered Cast
has the reviewed1U literal and no unreviewed target, mode, X or extra parameter.
Predictive autoTap data is checked for existing literal shape, never payment.
Only own Main1 with verified active/decision/priority player, positive known
library count and live players is reviewed. An observed nonempty Stack is a
contradiction; unknown Stack stays explicitly unknown.

Multiple Cast offers satisfying the reviewed goal profile abstain. Every other
active action, including Cast, Activate, Activate_Mana, Pass, FloatMana and Play
when offered, stays in `unranked_competitors` with unknown utility. No candidate
is removed or assigned zero value to manufacture uniqueness. Unreviewed effects
may also support card flow; this policy does not claim to discover all of them.
The original inactive count is recorded separately.

The report binds request/ref and original option_key, source/facet, full
conditional reference/instruction, phase and goal evidence. All of
`effect_triggered_verified`, `net_hand_gain_verified`, `payment_verified`,
`strategic_dominance_verified`, `complete_legality_verified`,
`strategic_optimality_verified`, `execution_ready` and `input_sent` are false.
The evidence level is `version_bound_conditional_effect_goal_heuristic`.

## Currentness and integration

Consumer current/ref/lease checks enclose the calculation. The original
completed-poll stamp and authenticated raw request/digest/build/resource witness
are checked before and after it, together with the policy's additional raw
type/overlay/turn fields and the same current options. Consumption, replacement,
expiry, partial, Full/reset, gap, Cancel/Undo, stop and mid-calculation changes
revoke results. There is no last-valid recovery, second state or request ledger.

Explicit `unified_research.v3` adds this policy alongside Land v2 for
ActionsAvailable. SelectTargets still uses Target Effect v1; other requests
still use MP66. It uses the existing `combine_current_research` arbiter. Different
preferred candidates produce abstention even when their goals differ; there is
no Land/Cast priority. The Cast-only evidence permission does not change MP65's
`research_eligible` flags or authorize any other ineligible candidate.

Original defaults, all single policies and Unified v1/v2 retain their complete
contracts. No new State/Event or Candidate version, response encoding or input
path is introduced. `P10=NOT_RUN`.

## Evidence and tests

The owner authenticates the original MP91 archive and replays its original50
first-current boundaries with the production Runtime, freezing each report
before appending subsequent source bytes. Public
`tests/fixtures/cast_cardflow_real.json` retains opportunity20's relevant fields
and full active/inactive inventory, with aliased identifiers and synthetic
authentication/Full transport. Opaque library placeholders preserve only real
counts; no hidden identities, names, account data or future response is included.
It is not raw-equivalent and does not reauthenticate the private original bytes.
The separate reference fixture is output of the actual production factory.

Synthetic counterexamples cover source, effect, modes/targets/cost, competing
same-goal Casts, incomplete inventories, contradictory phase/library/Stack,
dedicated arbitration permission, conflicts and request lifecycle. They are
never counted as additional real positive opportunities. Controlled replay
timings describe local computation, not live MTGA end-to-end latency or a new
three-second qualification. Historical agreement is not correctness or win rate.

Actual owner replay results (preference / abstain / unsupported):

| Population | Original Unified v2 | Cast-only | Unified v3 |
| --- | --- | --- | --- |
| MP91 all50 current opportunities | 1 / 40 / 9 | 10 / 14 / 26 | 9 / 32 / 9 |
| MP81 all42 current opportunities | 11 / 23 / 8 | 3 / 10 / 29 | 14 / 20 / 8 |

On MP91's24 ActionsAvailable requests Cast-only is10/14/0. The primary ten
no-Play requests contribute5/5/0; all five requested opportunities20/41/43/46/48
have a preference, with10/10/11/11/11 unranked competitors. Five additional
reviewed offers occur among requests that also contain Play. Opportunity42's
real Land/Cast conflict abstains, so v3 replaces the old land preference there
and gains nine preferences elsewhere. No preference is generated for the
four structurally unreviewed requests. Complete six-mode old frames and safe
summaries compare equal on552 endpoint-mode pairs (691,502 +29,084 typed leaf
values), normalizing only transport session/sequence and actual timings.

See [the owner evidence receipt](evidence/mp96-owner.json) for source hashes,
denominators, current request revocations and bounded computation timings.
Independent review and hosted CI bind the final delivery separately. No new
real game or historical choice label is used to define or tune this goal.
