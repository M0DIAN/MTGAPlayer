# MTGAPlayer

Independent Python 3.11 CLI with normalized JSONL state, finite synthetic tactics, a read-only MTGA Player.log GRE projection, and a Windows native interactive test harness. Runtime uses only the standard library. **Raw GRE never reaches the policy or native executor. MTGA automatic object localization and MTGA input are not enabled.**

```powershell
# Use an independent Python 3.11, never a Codex interpreter cache.
python3.11.exe -m venv .venv
.\.venv\Scripts\python.exe -m pip install --no-build-isolation -e .
.\.venv\Scripts\mtgaplayer.exe doctor
.\.venv\Scripts\mtgaplayer.exe replay examples\synthetic.jsonl
.\.venv\Scripts\mtgaplayer.exe dry-run examples\synthetic.jsonl
.\.venv\Scripts\mtgaplayer.exe replay --format player-log tests\fixtures\player_log_minimal.jsonl
.\.venv\Scripts\mtgaplayer.exe replay --format player-log tests\fixtures\player_log_selectn.jsonl
# Confirmed local source on the development machine; pass your explicit path elsewhere.
.\.venv\Scripts\mtgaplayer.exe watch "C:\Users\Administrator\AppData\LocalLow\Wizards Of The Coast\MTGA\Player.log" --samples 5 --interval 0.5
# MP7: schema-only probe on an explicit local log (never sends MTGA input).
.\.venv\Scripts\python.exe scripts\inspect_actions.py "C:\Users\Administrator\AppData\LocalLow\Wizards Of The Coast\MTGA\Player.log"
# MP9: inspect nested complex-action field TYPES and same-request raw-ID equality only.
.\.venv\Scripts\python.exe scripts\inspect_actions.py "C:\Users\Administrator\AppData\LocalLow\Wizards Of The Coast\MTGA\Player.log" --complex-relations
.\.venv\Scripts\python.exe -m unittest discover -s tests -v

# Actual input to the separately launched synthetic harness only.
# Interactive Windows desktop, 96 DPI, 820x580 client area required.
# Output must be a NEW directory. Default: 30 actions, 10 compound casts.
.\.venv\Scripts\mtgaplayer.exe benchmark --output artifacts\local-native-01
# Optional negative scenarios retain their own failure evidence:
.\.venv\Scripts\mtgaplayer.exe benchmark --output artifacts\local-unsupported --scenario unsupported
.\.venv\Scripts\mtgaplayer.exe benchmark --output artifacts\local-disappear --scenario target-disappear

# Standalone interactive test window, no player:
.\.venv\Scripts\mtgaplayer.exe harness --directory artifacts\local-manual --nonce manual --count 30
```

`py -3.11` can create the .venv where the Python launcher is installed. Linux/offline CI uses `python -m pip install -e .`, the same unittest command and replay/dry-run. `doctor --config config.toml` accepts only optional string `log_path`; `--log` overrides it. Doctor reports interpreter/base prefix, configuration, log existence, current-session window visibility and desktop limitations without screenshots or input. Sandbox window inventory is not the user's desktop inventory.

`replay --format player-log` reads a specified Player.log and reports a structurally continuous, player-visible snapshot. `watch` polls an explicit file for a finite number of samples (1–1000) at a bounded interval and emits JSON lines. Its first sample processes history; later samples process only appended bytes. `--max-history-bytes` bounds startup or replacement replay (default 64 MiB). Replacement/truncation resets identity and waits for a new authenticated room and Full. Empty polls do not change `source_state_timestamp`; the final sample marks `stopped`. Raw source results always have `actionable: false`, `input_sent: false`, and `executor_connected: false`. A structurally valid offline snapshot is historical evidence, not a live action opportunity. In finite `watch`, `source.candidate_event` is non-null only when a matching GRE request appears among this poll's newly framed append records and remains complete, supported and own-seat-verified; initial history, unrelated appends (including completion of an unrelated partial tail), idle polls and retransmissions cannot emit it. The event repeats the verified request identity/count only (full evidence remains in `current.request`) and always carries `read_only: true`. Even this append-only observation is not a legal action or a proof of current screen/input readiness; `current.actionable`, `input_sent` and `executor_connected` remain false.

After an authenticated, own-seat `ActionsAvailableReq`, the raw decoder may return a bounded `current.request.action_inventory`: counts/types from `actionsAvailableReq.actions` and exact flat Pass/Play raw descriptors only. Optional `inactiveActions` are counted but **never** included as offered options. This is source observation, not confirmed playable combinations: `request.supported=false`, `candidates=[]`, `legal_actions=null`, `actionable=false`; no strategy or native MTGA input is enabled. MP8 additionally surfaces request-scoped, non-executable `complex_raw_shapes` for Cast/Activate/Activate_Mana: validated raw identifier/flag fields, and only the existence and element counts of opaque `manaCost`, `targets`, `manaPaymentOptions`, `manaSelections` and `autoTapSolution` containers. **No nested values, legal response semantics, payment choice or target assignment are decoded.** MP9 additionally records same-request numeric ID-pair equality between active mana actions and auto-tap/mana-selection entries; it links to an action-array position only if the pair has exactly one active match. Unknown/duplicate pairs are unlinked. Raw targetIdx and target-entry counts are shape observations only. Up to 64 rows per nested array are examined, with truncation explicit; no payment, target assignment, response encoding or legal action is inferred. FloatMana remains type-only. MP10 joins only the described active Play/Cast/Activate/Activate_Mana source `instanceId` to an **already-visible** object in the current accepted state. `current.request.action_inventory.visible_source_links` lists unique matches by instance ID; absent, invisible or ambiguous sources are explicitly unresolved. A raw action `grpId` equality comparison to the visible `card_id` is only a diagnostic, never a card rule or legality check. No hidden-zone object is resolved and no input or strategy behavior changes. The bounded offline summary mode `python scripts/inspect_actions.py <Player.log> --visible-sources` reports only type/status counts from accepted own-request visible-source links, never raw card or action identifiers.

The raw decoder identifies the local seat only when `authenticateResponse.clientId` matches exactly one `gameRoomConfig.reservedPlayers.userId`, and a state GRE message targets that seat. Full requires match/game identity, two players, the public battlefield and stack, and the own hand zone. Diff requires the exact previous state ID and replaces listed zone/object/player entities, including deletions; a gap or corruption waits for a reliable Full. Broadcast and other-seat requests cannot become current. An own, single-recipient `SelectNReq` with the observed InstanceId/Dynamic/NonRepeatable resolution shape exposes its exact `ids` as engine-offered candidates, bound to source generation, match, game, state and verified seat. Its `maxSel` and observed constraints are recorded; absent `minSel` stays null and legal combinations are unknown. The candidate IDs are not enriched from hidden-zone cards. Other request types and unrecognized shapes carry an unsupported reason with no candidates. Client `respId` records submission only, not server confirmation; consumed, superseded and older-state requests do not reopen. Projection includes own visible hand, public battlefield/stack/graveyard, and counts for hidden zones. Unknown mana, rules, layout, opportunities and legal actions remain null. This supports observation of the sampled GRE format, not general MTGA tactics or visual localization.

### MP11 opt-in local card metadata

The optional `--card-db` argument on raw `replay` accepts an explicitly selected local MTGA SQLite `Raw_CardDatabase_*.mtga` file (under the installation's `MTGA_Data/Downloads/Raw` folder). The lookup is strictly read-only and offline; it maps only previously visible `card_id` values to `enUS` card titles and optional set/collector metadata. Duplicates, missing names and unsupported database schemas remain unresolved. Nothing queries hidden cards or enriches diagnostic `last_valid`; existing raw action and no-input boundaries remain unchanged.

A separate `scripts/inspect_card_catalog.py --log <Player.log> --card-db <actual.db>` scan reports **counts only**, not names, IDs or filenames. No game resource is bundled, and no runtime internet access or external model is required. Local card names do not establish complete Oracle rules, legal responses, mana payment or strategy.


```powershell
.\.venv\Scripts\mtgaplayer.exe replay --format player-log --card-db "<Raw_CardDatabase_file.mtga>" "<Player.log>"
.\.venv\Scripts\python.exe scripts\inspect_card_catalog.py --log "<Player.log>" --card-db "<Raw_CardDatabase_file.mtga>"
```



### MP15 offline client response-envelope and own-request linkage (read-only)

The next blocker after MP14 is **not knowing how actual client responses encode a selected Pass, Play, Cast or other action**. An existing sanitized real-source Player.log fixture already contains `ClientMessageType_PerformActionResp` with **only** the `type`, `respId` and `gameStateId` root fields. These three fields establish an observed *response envelope*, **not** which offered action was selected and not a complete action-payload contract.

The optional schema-only counter reuses `scripts/inspect_actions.py`, RawFollower and RawReducer, rather than adding a second parser or a sender:

```powershell
.\.venv\Scripts\python.exe scripts\inspect_actions.py "<Player.log>" --response-envelopes
```

It links a historical `ClientMessageType_*Resp` **only when the immediately preceding reducer state has a current authenticated own-seat request whose request ID and game-state ID exactly match the response**, and the reducer records the client submission. Superseded, mismatched, broadcast, other-seat or duplicate responses stay unlinked. It aggregates safe response-type categories, counts of matching requests, the known **offered** Pass/Play context (never a claimed chosen move), whitelisted field **names and storage type classes**, opaque nested field shapes and the count of intervening UIMessage envelopes. It never prints request/card/player IDs, raw scalar values, private keys, file paths, action-selection values or complete payloads. Shape variation is capped and truncation is explicit.

**Actual installed-log update (owner-executed, aggregate only):** the owner's 6,021-frame Player.log yielded 423 accepted own requests, 485 historical client response records, 369 exactly paired own responses and 116 unmatched/noncurrent. All **216** paired ActionsAvailable requests had `performActionResp.actions` arrays. Of these, **122** offered Pass without Play and **94** offered Pass together with Play; this is **offer context, not the action chosen**. A further **167/216** action responses contained one nonallowlisted sibling field under `performActionResp`, whose name/value were intentionally suppressed.

To understand the remaining real response **array element format** without guessing, MP15 adds a second, *explicit* read-only diagnostic mode using the **same** probe and own-request matching chain:

```powershell
.\.venv\Scripts\python.exe scripts\inspect_actions.py "<Player.log>" --response-action-shapes
```

It reports only bucketed lengths of already matched `performActionResp.actions` arrays, aggregate per-element JSON storage types, a **fixed whitelist** of field names and their storage kinds (including one level of nested known object fields), and **types but not names or values** of suppressed unknown fields. Limits: 64 array items per matched response, 24 fields per element, 16 fields per nested known object, and 48 aggregate shape variants; overflows are explicit. Unlike `--response-envelopes`, the detailed option reads array elements **in memory** but never prints raw content, card/action IDs, selected action values, hidden fields or local paths. Prior `--response-envelopes` output is unchanged. Even if the response contains `actionType`, its scalar value stays unobserved: no Pass-vs-Play selection, legal action or response encoding is asserted.

**Historical client responses observed in a log are not messages sent by this tool.** `response_encoding_verified=false`, `selected_action_type_verified=false`, `pass_vs_play_selection_verified=false`, `gameplay_effect_verified=false`, `legal_actions=null`, `actionable=false` and `input_sent=false` remain. No MTGA input, native automation, inferred action encoding, mana/target contract or <3 s live-performance claim is introduced. The owner may supply only the count-only JSON from the original locally installed Player.log to determine the next evidence-focused implementation.

### MP15 opt-in first engine-offered action frontier (read-only)

`--action-frontier` requires `--decision-input` and a Player.log replay or finite watch. It adds a separate `action_frontier` property with one `ActionTemplate` for **each position in the current authenticated own-seat** `ActionsAvailableReq.actions` array, including duplicate rows, `FloatMana`, unknown types and malformed shapes. The template contains the request identity, original array position, recognized type or a fixed unknown label, existing verified visible-source link when available, whitelisted opaque parameter container sizes, and explicit unresolved evidence. Private values, unknown field names and raw action IDs are excluded. `inactiveActions` never become templates. The existing raw inventory, decision input and gap report keep their prior meanings and default output stays unchanged.

```powershell
.\.venv\Scripts\mtgaplayer.exe replay --format player-log --decision-input --action-frontier "<Player.log>"
.\.venv\Scripts\mtgaplayer.exe watch --decision-input --action-frontier "<Player.log>" --samples 5
```

Coverage reports `engine_active_action_count = interpreted_action_count + unsupported_action_count`. “Interpreted” means only an existing reviewed structural description; malformed or unreviewed rows are explicit unsupported templates. Immediate completeness is `partial` even when every row has a description, since payment, targets and response encoding remain unverified. Future choice expansion stays `unknown`; no later request is presumed. Missing/invalid action payloads and other current request types yield `unknown` coverage with null counts and null templates, not a fabricated zero. Invalid or partial current snapshots yield `action_frontier: null`; diagnostic `last_valid` is never reused. Finite watch may finish with `stopped=true` while retaining a historical diagnostic frontier, always `actionable=false`, `execution_ready=false` and `input_sent=false`. This is level-one engine-offered structure, not verified legal choices or MTGA input.

### MP14 action evidence/gap classification (still read-only)

MP13 produced a **request-bound observation**, not an action-execution contract. MP14 optionally classifies only **engine-described active action positions** into typed *engineering evidence gaps*; it never marks Pass, Play, Cast, Activate or Activate_Mana as executable, legal, strategically good or complete. An unknown/undetailed action such as `FloatMana` is counted by its observed type but gets **no invented position or response parameters**. A visible source join is not a Magic permission; even an explicit same-request mana pair/target slot is only raw structural equality, **not** a validated payment or target.

```powershell
# Offline request-level gap details: requires BOTH flags.
.\.venv\Scripts\mtgaplayer.exe replay --format player-log --decision-input --action-gaps "<Player.log>"
# With optional previously supported, visible-card-only catalog metadata:
.\.venv\Scripts\mtgaplayer.exe replay --format player-log --decision-input --action-gaps --card-db "<Raw_CardDatabase_file.mtga>" "<Player.log>"
# Existing read-only watcher: never promotes a gap report to live input authority.
.\.venv\Scripts\mtgaplayer.exe watch --decision-input --action-gaps "<Player.log>" --samples 5
# Owner-local historical evidence: count-only across accepted own requests.
.\.venv\Scripts\python.exe scripts\inspect_actions.py "<Player.log>" --gap-coverage
```

`action_gap_report` is an opt-in top-level property, **null** when there is no current verified `ActionsAvailableReq` decision input. Its summaries contain only recognized type labels, array positions, raw container and relation counts, existing visible source/link statuses, and *named missing semantic evidence* (effect interpretation, payment/target legality and response encoding). No raw card IDs, target IDs, titles, private GRE fields or complete actions are emitted in `--gap-coverage` aggregate output. Request-wide gaps always include rules, response encoding, strategy and live freshness; `strategy_evaluation_complete=false`, `legal_actions=null`, `actionable=false`, `input_sent=false` and `executor_connected=false` remain.

This is a development **coverage map**, not an AI player, Magic rule engine, list of legal moves or authorization to click MTGA. Running the historical probe on the owner's original file may help prioritize which action types need the next narrow real-format evidence; it does not establish actual <3-second decision or execution.

### MP13 request-bound read-only decision observation

The MP13 opt-in `--decision-input` view composes **only the already-projected current raw GRE snapshot**: authenticated own-seat request identity (generation/match/game/state/request ID), turn/players, the existing own-hand/public visible objects, MP10 source links, MP8–9 **opaque** cost/target shape/equality evidence, and optional MP11–12 localized card names/stored numeric power and toughness. It never re-opens hidden raw objects or joins an offered SelectN option ID to hidden card metadata. Its compact `decision_input.request.engine_action_inventory.described_rows` contains only engine-described active rows; unrecognized/undetailed actions remain counted but **not invented**. All positional mana/target evidence remains uninterpreted, and legal target/payment flags remain false.

```powershell
# Offline-only observation, optionally including stored catalog metadata:
.\.venv\Scripts\mtgaplayer.exe replay --format player-log --decision-input --card-db "<Raw_CardDatabase_file.mtga>" "<Player.log>"
# Existing read-only watch; no card database read on the polling loop:
.\.venv\Scripts\mtgaplayer.exe watch --decision-input "<Player.log>" --samples 5
```

This adds a **separate output-only `decision_input` property** only when requested; existing replay/watch payloads stay unchanged by default. Invalid, partial, unbound or absent-current-request observations yield `decision_input: null` with **no fallback to diagnostic `last_valid`**. Even an appended watch request has `source.freshness_verified=false`: offline historical data, finite polling and file timestamps are **not live action authority**. `read_only=true`, `actionable=false`, `legal_actions=null`, `input_sent=false`, `executor_connected=false`, `strategy_selected=false` remain invariant. No policy/LLM, Magic rules engine, input coordinates, native MTGA bridge or <3 second execution proof is added. `--decision-input` is rejected for the separate synthetic normalized replay format.

### MP12 opt-in card capability schema evidence (read-only)

To avoid guessing whether the installed MTGA database contains card types, mana costs, abilities, targets or rules text, the next stage starts with a **schema-only** diagnostic. It opens only the explicitly selected SQLite catalog in immutable/read-only mode and returns `Cards` column names with SQLite **storage affinity** plus names of potentially relevant game-data tables. It never selects card rows, so **no card values, names, IDs, rules text or local paths** enter its JSON output. Table-name filtering and column limits are explicit; column names alone do **not** prove any game-rule meaning or legality.

```powershell
.\.venv\Scripts\python.exe scripts\inspect_card_capability_schema.py --card-db "<Raw_CardDatabase_file.mtga>"
```

This diagnostic does **not** add an ability parser, modify the existing MP11 card title lookup, touch `RawReducer`, enable strategy, or send MTGA input. The owner's real catalog schema report established 60 `Cards` columns, including `Types`, `Colors`, `Power`, `Toughness` and `AbilityIds` stored as SQLite TEXT; **actual value encoding and ability semantics are still unknown**. For a strictly bounded follow-up, the existing `inspect_card_catalog.py` offers an opt-in `--capability-shapes` mode that queries only card GrpIds already shown in verified own-seat GRE visible objects and reports **aggregate storage grammar types** for a fixed allowlist: null, JSON-array-looking, symbolic text, numeric text, and similar classes. Unlike the schema-only command it does read these *visible* Cards rows, but it never exports their values, card names, GrpIds, local paths or nested content. Shape labels cannot be treated as card abilities or valid mana payments. The owner's real installed-source shape scan found that, among 82 Cards rows for 83 GRE-visible IDs, `Power` and `Toughness` were each **34 bounded integer-like text / 48 empty text**, whereas `Types` and `Colors` were largely opaque numeric codes and `AbilityIds` contained varying string formats. Accordingly MP12 supports one narrow **optional, static catalog-literal overlay** when `replay --format player-log --card-db <file>` is explicitly selected: a uniquely localized, already-visible card may have `local_card.catalog_stats.power/toughness` as bounded ASCII integers; missing/empty/star/fractional/nonliteral values remain `null`. It is a *stored catalog literal*, **not in-game effective power/toughness** and never a rule or legality assertion. Duplicate raw GrpIds continue to be ambiguous and never receive stats. The `--capability-shapes` count-only output additionally reports how many distinct localized visible IDs had parsed numeric literals without exporting numeric card values. No Types/Colors enum mapping, ability resolution, mana legality or native input has been added.

```powershell
.\.venv\Scripts\python.exe scripts\inspect_card_catalog.py --log "<Player.log>" --card-db "<Raw_CardDatabase_file.mtga>" --capability-shapes
```

 After observing the real installed schema, a later MP12 candidate may decode only confirmed narrow fields as read-only decision metadata; unknown rule semantics remain null.

The benchmark starts its own process and verifies PID, HWND and nonce title. Screenshots find checksummed object markers bound to state/request/layout; log order never supplies screen order. Markers are **a harness-only protocol**, not MTGA vision. Layouts alternate; each mouse event requires a fresh screenshot. GDI capture and SendInput use ctypes. On Windows the harness launches the same base interpreter directly to avoid venv redirector PID ambiguity, loading the installed package source; no external desktop runtime is required.

Handshake does not prove desktop pixels are ready. Startup, each input step and effect confirmation share bounded read-only screenshot waiting. Only missing pixels or an older visual context may be resampled, with a short wait between attempts and unchanged logical state/request/layout before and after capture. Focus loss, takeover, ambiguous identities and context changes refuse immediately. Confirmation locks the exact terminal state and effect; waiting never repeats input or resets the semantic-action timer.

The harness changes semantic state only from real mouse callbacks: drag land to the drop region; click spark, target and confirmation; or click pass. Confirmation checks source movement/land count, mana and target health, or priority transfer with root-request completion. SendInput success is only dispatch. Only exact target/submit successor requests/versions are allowed, retaining root context, expiry and timing.

Unknown effects, missing markers, target loss, focus loss, detected manual input, Escape, `stop`/`pause` files, exceptions or timeout stop the loop. Owned held buttons are released. Unknown results are never automatically retried. Re-enable by inspecting evidence and explicitly starting a fresh run/directory; no automatic resume.

The producer writes `normalized.jsonl` and `ui-events.jsonl`; the player writes every observed root opportunity to `opportunities.jsonl`, including fail/unsupported/timeout/paused/cancelled/uncertain results. Seven monotonic timestamps are retained (null if not reached); compound subrequests do not reset the opportunity origin. Reports use nearest-rank p50/p95/p99/max for successful end-to-end, all ended opportunities, pre-input/input/post-input, plus startup separately. PASS requires 30+ consecutive confirmed actions, all three classes, 10+ compound casts, ordered timestamps, no failed opportunities and max <=3000ms. No-input startup failure is BLOCKED_NATIVE with null confirmed latency. Evidence is synthetic; no game screenshots or private logs.

Normalized schema 1 is distinct from raw GRE and old derived events. Each line is a complete UTF-8 JSON object ending in newline. `begin` binds opaque `match`, `game`, integer `self_seat`; only an explicit new-game boundary or source generation can rebuild binding. Retired identities cannot reopen; same-game seat conflict invalidates current. See [examples/synthetic.jsonl](examples/synthetic.jsonl).

- `full`: complete `state_version`, `objects`, `request`, `mana`, `land_plays`, `phase`, `priority`, `effects`, `layout`, `outcome`. Missing fields remain null/unknown. Objects have unique integer `id`, integer `owner`, `zone`, `visibility`, `rule`, optional `hp`/`tapped`.
- `diff`: increasing version, exact `previous`, whitelisted `changes`. Included objects are a full list replacement. Gaps, old Full and corrupt complete lines block until an explicit non-regressing Full; binding/duplicate conflicts require a new explicit game boundary or source generation. Identical Full does not refresh freshness during normal continuity.
- `request`: current state version plus immutable `id`, `kind`, `opportunity_id`/`opportunity_at`, `root`, optional visible `source`/`targets`. IDs are opaque, not assumed monotonic. Consumed/executing/uncertain roots never reopen on retransmission or Full.
- `response`: consumes `request_id`, without establishing a semantic effect. `heartbeat` neither refreshes state nor repairs errors.

Only own `self` hand and explicitly public battlefield/stack/graveyard objects reach projection. Hidden zones expose counts, no IDs/rules. Request/outcome references must be visible. Invalid `current` has no stale objects/request; `last_valid` is diagnostic only and first error is preserved. `valid_until`, `last_observed`, `missing_fields` expose freshness/unknowns. Replay is an offline projection/recommendation, never native execution evidence.

Supported **synthetic rules v1**: main-phase own priority; no continuous effects; one land play per scene; integer generic mana pool; `spark` costs exactly one generic and deals one damage to one visible opposing `inert_creature`; inert creatures have no other abilities. Scores prefer land, spark, then legal pass. Unknown visible own/opponent rules/effects or missing required fields return unsupported even if pass would otherwise be available. No real card database, colored mana, combat, stack responses, triggers, general Magic legality, win-rate or optimal-play claim.

Measured status/blockers and raw evidence: [docs/progress.md](docs/progress.md). Source decisions/hashes: [THIRD_PARTY.md](THIRD_PARTY.md). CI separates Ubuntu offline checks from Windows no-input doctor, each with a 10-minute limit. Frozen candidate identity, actual CI revisions and independent review are reported on the candidate PR and final handoff. The native normal set passed; retained negative scenarios include an unsupported effect, an uncertain target disappearance and a reordering timeout. This does not establish MTGA or dynamic-layout three-second performance.
