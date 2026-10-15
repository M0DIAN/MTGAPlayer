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

`py -3.11` can create the .venv where the Python launcher is installed. Linux/offline CI uses `python -m pip install -e .`, the same unittest command and replay/dry-run. The parallel Windows no-input CI job also runs the complete unittest suite before doctor; SQLite fixtures close connections explicitly while preserving transactions. `doctor --config config.toml` accepts only optional string `log_path`; `--log` overrides it. Doctor reports interpreter/base prefix, configuration, log existence, current-session window visibility and desktop limitations without screenshots or input. Sandbox window inventory is not the user's desktop inventory.

`replay --format player-log` reads a specified Player.log and reports a structurally continuous, player-visible snapshot. `watch` polls an explicit file for a finite number of samples (1–1000) at a bounded interval and emits JSON lines. Its first sample processes history; later samples process only appended bytes. `--max-history-bytes` bounds startup or replacement replay (default 64 MiB). Replacement/truncation resets identity and waits for a new authenticated room and Full. Empty polls do not change `source_state_timestamp`; the final sample marks `stopped`. Raw source results always have `actionable: false`, `input_sent: false`, and `executor_connected: false`. A structurally valid offline snapshot is historical evidence, not a live action opportunity. In finite `watch`, `source.candidate_event` is non-null only when a matching GRE request appears among this poll's newly framed append records and remains complete, supported and own-seat-verified; initial history, unrelated appends (including completion of an unrelated partial tail), idle polls and retransmissions cannot emit it. The event repeats the verified request identity/count only (full evidence remains in `current.request`) and always carries `read_only: true`. Even this append-only observation is not a legal action or a proof of current screen/input readiness; `current.actionable`, `input_sent` and `executor_connected` remain false.

After an authenticated, own-seat `ActionsAvailableReq`, the raw decoder may return a bounded `current.request.action_inventory`: counts/types from `actionsAvailableReq.actions` and exact flat Pass/Play raw descriptors only. Optional `inactiveActions` are counted but **never** included as offered options. This is source observation, not confirmed playable combinations: `request.supported=false`, `candidates=[]`, `legal_actions=null`, `actionable=false`; no strategy or native MTGA input is enabled. MP8 additionally surfaces request-scoped, non-executable `complex_raw_shapes` for Cast/Activate/Activate_Mana: validated raw identifier/flag fields, and only the existence and element counts of opaque `manaCost`, `targets`, `manaPaymentOptions`, `manaSelections` and `autoTapSolution` containers. **No nested values, legal response semantics, payment choice or target assignment are decoded.** MP9 additionally records same-request numeric ID-pair equality between active mana actions and auto-tap/mana-selection entries; it links to an action-array position only if the pair has exactly one active match. Unknown/duplicate pairs are unlinked. Raw targetIdx and target-entry counts are shape observations only. Up to 64 rows per nested array are examined, with truncation explicit; no payment, target assignment, response encoding or legal action is inferred. FloatMana remains type-only. MP10 joins only the described active Play/Cast/Activate/Activate_Mana source `instanceId` to an **already-visible** object in the current accepted state. `current.request.action_inventory.visible_source_links` lists unique matches by instance ID; absent, invisible or ambiguous sources are explicitly unresolved. A raw action `grpId` equality comparison to the visible `card_id` is only a diagnostic, never a card rule or legality check. No hidden-zone object is resolved and no input or strategy behavior changes. The bounded offline summary mode `python scripts/inspect_actions.py <Player.log> --visible-sources` reports only type/status counts from accepted own-request visible-source links, never raw card or action identifiers.

The raw decoder identifies the local seat only when `authenticateResponse.clientId` matches exactly one `gameRoomConfig.reservedPlayers.userId`, and a state GRE message targets that seat. Full requires match/game identity, two players, the public battlefield and stack, and the own hand zone. Diff requires the exact previous state ID and replaces listed zone/object/player entities, including deletions; a gap or corruption waits for a reliable Full. Broadcast and other-seat requests cannot become current. An own, single-recipient `SelectNReq` with the observed InstanceId/Dynamic/NonRepeatable resolution shape exposes its exact `ids` as engine-offered candidates, bound to source generation, match, game, state and verified seat. Its `maxSel` and observed constraints are recorded; absent `minSel` stays null and legal combinations are unknown. The candidate IDs are not enriched from hidden-zone cards. Other request types and unrecognized shapes carry an unsupported reason with no candidates. Client `respId` records submission only, not server confirmation; consumed, superseded and older-state requests do not reopen. Projection includes own visible hand, public battlefield/stack/graveyard, and counts for hidden zones. MP24 also includes ordinary Card objects in Exile only when both the zone and object explicitly report Visibility_Public and their membership agrees. Private/unknown Exile remains count-only; no face-down identity or general Exile publicity is inferred. Unknown mana, rules, layout, opportunities and legal actions remain null. This supports observation of the sampled GRE format, not general MTGA tactics or visual localization.

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

### MP16 historical response-choice correlation (read-only)

`python scripts/inspect_actions.py "<Player.log>" --response-choice-correlation` reuses the MP15 exact current-own request and compatible-response gate. It reports aggregate `unique`, `multiple`, `no_match` and `incomplete_or_unsupported` counts for historical client submissions. Only exact flat Pass/Play fields are compared with active candidates in the same request. Incomplete same-type source coverage, unknown shapes, complex actions and oversized arrays stay unsupported. Inactive actions are excluded. Output contains fixed action-type categories and counts, without raw identifiers, private values or paths.

`unique` means request-candidate equality only; it does not establish server acceptance, complete response encoding, legal actions or gameplay effects. No input is sent. The new mode is mutually exclusive with other diagnostic modes; default MP15 envelope and action-shape output remain unchanged.

The separate `--complex-response-choice-correlation` mode extends this historical identity comparison to Cast, Activate and Activate_Mana after the same MP15 gate. Cast requires exact instance/group/facet identity; abilities additionally require both ability-group and unique-ability identity. All observed identifier fields must agree in presence and value. Boolean flags require consistent presence and strict storage types; their values never disambiguate complex identities. Every same-type active candidate must have sufficient, structurally supported evidence; omitted candidates, missing or invalid IDs, unknown action fields, unsupported shapes and truncation yield `incomplete_or_unsupported`. Duplicate identities remain `multiple`, including rows with differing flags or opaque parameters. `no_match` requires a complete, validated same-type candidate set. Inactive actions are excluded; Pass/Play retain the earlier classifier.

Output separates `selected_action_identity`, `response_parameter_evidence` and `legal_parameter_verification`. Fixed action-type rows each report `matched_response_count`, the four result counts, `truncated_count` and `unknown_parameter_count`, with complete accounting. The last count includes responses with opaque parameter contents or unknown fields; it can coexist with proven identity equality. Unknown wrapper siblings are suppressed and counted without changing the identity comparison. Target, cost and mana containers are observed only by presence and storage kind, with bounded structure; no parameter contents, unknown names, identifiers, request identities or targets leave the probe. Modes, target legality, payment, future requests and response encoding remain unverified. `response_encoding_verified`, `legal_choice_verified`, `execution_ready` and `input_sent` stay false; `read_only` stays true. This mode is mutually exclusive with all other probe modes; default replay/watch and existing response reports are unchanged.

### MP16 Phase 4 verified necessary choice constraints (read-only)

The mutually exclusive `scripts/inspect_actions.py --verified-choice-constraints` probe validates historical **SelectNReq → SelectNResp only**, after the existing authenticated exact-current-own-request type/ID/state and RawReducer consumption gate. It checks a strict integer `selectNResp.ids` array, membership in that request's `selectNReq.ids` (not `unfilteredIds`), the confirmed `maxSel`, and uniqueness only within the supported `NonRepeatable` protocol slice. Extra/unknown shapes are unsupported; missing binding/evidence is insufficient. `minSel` remains unknown: an empty array may satisfy known necessary constraints without proving it is a legal complete response; `allowCancel=false` supplies no inferred minimum. Decoded weight boundary types must also match the observed integer protocol; no new request parser or raw reducer is introduced.

```powershell
.\.venv\Scripts\python.exe -B scripts\inspect_actions.py "<explicit local sanitized log>" --verified-choice-constraints
```

The CLI emits only fixed categories/counts and source-integrity metadata. Both **all observed client responses** and the SelectN subset reconcile four classes: `verified_known_constraints`, `violated_known_constraints`, `insufficient_evidence`, `unsupported_protocol`. Unsupported non-SelectN responses remain in the denominator. Partial/corrupt sources withhold SelectN verification and graphs; an unframed tail is reported as partial rather than invented as a counted response. The checked-in full state prefix `player_log_selectn.jsonl` plus its real `player_log_selectn_response.jsonl` tail yields all responses **15: 1/0/0/14** and SelectN **1: 1/0/0/0**, in the class order above. The original private Player.log is not needed.

Explicit local Python opt-in `mtgaplayer.response_evidence.inspect_verified_choice_constraints(path)` returns identity-bearing **historical** SelectN graphs, separate from the count-only CLI. Each eligible graph retains the full request identity, request-offered instance domain and source, confirmed maximum/unknown minimum, ChoiceConstraint validation level, historical checks, unresolved evidence and provenance. These IDs are supplied by that request; hidden raw objects never enrich them. Graphs are partial, refer to the request snapshot at response time, and do not revive consumed candidates or create a Cast→SelectN causal edge. Existing temporal history and ActionsAvailable/Pass/Play/Cast/Activate graphs/default replay/watch remain unchanged.

`engine_offered` and `known_constraint_satisfied` are separate claims. `complete_legality_verified`, `server_acceptance_verified`, `legal_choice_verified`, `response_encoding_verified`, `execution_ready` and `input_sent` remain **false**. Client submission, syntactic membership and quantity checks are not complete legality, verified encoding or server acceptance. No target/mana/mode/X solver, strategy, real MTGA input or latency qualification is added.

### Opt-in live read-only performance and continuity baseline

```powershell
.\.venv\Scripts\python.exe -m mtgaplayer performance-baseline "<explicit Player.log>" --duration 600 --interval 0.25
```

This separate command accepts 600–900 seconds and follows a monotonic deadline without the existing watch sample cap. It opens the selected log only through the production follower's `rb` path, runs the existing reducer, DecisionInput, ActionFrontier and ChoiceGraph once per poll, and prints one final safe aggregate. It does not copy/hash the log, emit snapshots, open a card database or send input. Default replay/watch outputs and watch's 1000-sample limit remain unchanged. Short offline durations are available only through the Python API for tests.

Every timing has `sample_count`, nearest-rank `p50_ms/p95_ms/p99_ms/max_ms` (empty groups use null). Read/framing, summed per-record reducer apply, state projection, DecisionInput, Frontier, Graph and the internal pipeline are separate. Internal time includes collector overhead and excludes sleep, final summary, JSON serialization and output; summary/serialization costs are reported separately, output-write cost is null. Actual poll intervals, absolute interval jitter, deadline lateness and skipped deadlines are separate scheduler measurements.

Groups reconcile to `all_polls`: first `startup_history`, later `file_reset`, successful Full acquisition/recovery `baseline_recovery`, complete-record `incremental`, added bytes without a complete record `partial_append`, and no new bytes `empty_poll`, in that precedence. Normal incremental percentiles exclude startup, reset and Full reinitialization. Partial polls count unfinished-record observations, including unchanged pending partials. JSON record counts (including malformed sentinels) differ from GRE message counts. Invalid/partial current state never falls back to `last_valid`.

Unique authenticated own requests are observed at the reducer acceptance point, including requests consumed or superseded within the same batch/record. Snapshot build counts and unique request coverage are separate, so idle polls cannot inflate request coverage. `supported` retains the reducer's existing meaning: ActionsAvailable remains false (`action_details_unverified`) even when a partial Frontier/Graph builds; SelectN has no existing root ChoiceGraph and is explicitly not applicable. No-current-request polls are separate from unsupported requests. Reports contain fixed categories/counts/timings and OS/Python/code revision only; identities remain in memory for deduplication. Event-to-log-write and true end-to-end latency remain null, and `input_sent`, `execution_ready` and `legal_choice_verified` remain false. Offline validation, actual live observation and independent acceptance are recorded separately in the final handoff and safe aggregate evidence.

### MP16 opt-in composite choice graph (read-only)

`--choice-graph` requires `--decision-input --action-frontier` with Player.log replay or finite watch. For the **current authenticated own** ActionsAvailable request, it adds `choice_graph` with one ActionNode per active Cast, Activate or Activate_Mana row. Every constraint carries the full request identity and original action position. It describes observed target group positions, raw target indices and array counts; mana-selection and auto-tap links to same-request active mana positions; and observed cost/payment container counts. A count is not a required selection quantity, a target domain, or a legal payment. Mode, X, additional-cost choice, target/payment legality and response encoding stay unresolved. `immediate_frontier` remains partial and `expanded_choices` unknown; no combinations are generated. Consumed, stale, partial or mismatched current requests yield `choice_graph: null`. Default output and Pass/Play behavior stay unchanged.

```powershell
.\.venv\Scripts\mtgaplayer.exe replay --format player-log --decision-input --action-frontier --choice-graph "<Player.log>"
.\.venv\Scripts\mtgaplayer.exe watch --decision-input --action-frontier --choice-graph "<Player.log>" --samples 5
python scripts/inspect_actions.py "<Player.log>" --choice-graph-history
```

The last command is a **count-only** offline historical probe behind the existing exact own-request/client-response type, ID, state and reducer-consumption gate. The local Python API `inspect_historical_choice_graphs(path)` returns bound historical source graphs when an explicitly chosen log is suitable; it includes request/action identities and should stay local. A uniquely correlated submitted action may receive an observed successor only after a later accepted state and a whitelisted own request in the same generation, match, game and seat. Supported SelectN successors expose only their own offered count and raw `maxSel`, with minimum and legal combinations unknown. Each graph records whether a successor was observed, absent, discontinuous, unsupported in ordering, or could not be linked to an action. Temporal adjacency does not prove the action caused the next request or that the server accepted a legal choice. All graph and node execution flags remain false.

### MP18 opt-in DecisionEvent v1 publication

`watch --decision-events` emits a separate JSONL event stream, internally assembling DecisionState v1. Omit the legacy projection flags in this mode; their standalone behavior and dependency guards are unchanged. Example using a committed scrubbed fixture:

```powershell
python -m mtgaplayer watch --decision-events --samples 3 --interval 0.25 --max-observation-age-ms 1000 tests/fixtures/player_log_selectn.jsonl
```

The [Draft 2020-12 event schema](schemas/decision-event.v1.schema.json) has id `urn:mtgaplayer:decision-event:v1`, version `mtgaplayer.decision-event.v1`. Load it and the unchanged DecisionState schema into a validator's local registry by their URN ids; no network resolution or runtime validator dependency is needed. Each session has a random ID and increasing sequence numbers. `snapshot` carries one final-poll DecisionState and its reference; `invalidate` withdraws a reference using a fixed reason and carries no old candidates; `liveness` reports local observation age; `stopped` withdraws subscription activity with sample_limit, user_interrupt or source_error (the Python publisher also supports other_supported_reason).

Snapshots are deduplicated by full identity and semantic projection content, excluding transport offsets, phase and finite-watch flags. Consumption, replacement, state/identity advance, detected source reset, continuity loss and partial tails revoke the consumer reference. Event-mode partial observation uses the existing request continuity fact to prevent its later retransmission from restoring old candidates. A valid board after request end may still be published without a request. Only final poll state is exported: transient requests that arrive and end inside one poll are not individual snapshots. Startup and reset remain history until the first complete valid baseline; history never sets new_request_observed. Append is the post-baseline observation phase and also includes empty polls; the phase label alone proves neither new evidence nor a new request. Server freshness remains unverified.

The pure Python `DecisionPublisher.observe(document, metadata)` consumes an already assembled watch observation and scalar lifecycle facts; `mtgaplayer.cli.watch_decision_events(...)` iterates events through the existing follower/reducer. No additional source reader, request ledger, transport or input path is created. Consumers must drop revoked references and all references on stopped, EOF or abandonment; abrupt process/pipe loss cannot guarantee a final JSON line. The subscription flag describes the local publisher, not game validity or execution permission.

Time fields use one injectable monotonic nanosecond clock (default perf_counter_ns), never wall time. `poll_started_ns`/`poll_completed_ns` bound the local pipeline; `last_state_change_ns` records polls accepting non-retransmitted Full/Diff, and `last_request_change_ns` records accepted new/ended requests. `last_new_evidence_ns` also includes reset/continuity facts, not arbitrary added bytes or retransmissions. Observation age is measured from the evidence anchor of the last published snapshot; empty polls do not renew it. The optional consumer age limit defaults to disabled, accepts 1ns..24h (CLI milliseconds), and is exceeded only when age is strictly greater than the limit. observation_stale revokes a consumer reference without changing RawReducer continuity or claiming the game changed.

Per-poll timings separate read/framing, reducer apply/loop bookkeeping, DecisionState assembly and event preparation. These four segments do not exhaust poll_to_publish: reducer document projection and source packaging are included in the total only. poll_to_publish ends before JSON encoding/stdout/consumer delivery. These local measurements exclude server-to-log latency, source timestamp age and actual game/decision/input latency. DecisionState freshness_verified remains false, effects/effective P/T remain null, read_only remains true and all six legality/execution flags remain false.

### MP18 local DecisionEvent consumer

`consume-events` reads only DecisionEvent v1 JSONL from stdin. For example, from the repository root with the independent project Python 3.11:

```powershell
& .\.venv\Scripts\python.exe -m mtgaplayer watch tests\fixtures\player_log_selectn.jsonl --decision-events --samples 5 --interval .001 |
    & .\.venv\Scripts\python.exe -m mtgaplayer consume-events --max-event-silence-ms 5000 --max-observation-age-ms 5000
```

The Python API is `DecisionConsumer(max_event_silence_ns=..., max_observation_age_ns=..., clock_ns=...)`, `accept_event(event) -> bool`, `current_view() -> dict`, `tick() -> dict`, and `close(reason='cancelled') -> dict`. Views and cached snapshots are deep copies. The optional `accept_event(..., received_ns=...)` uses the same **consumer-local** clock; the stdin adapter stamps complete lines before queueing so queue/decode delay counts toward leases. No producer timestamp is subtracted from the consumer clock.

Each instance binds one session starting at sequence 1, including an initial liveness without a snapshot. Every subsequent sequence must be consecutive. References include the full generation/match/game/seat/state/request/type binding. A snapshot needs exact event/reference/state identity agreement, and another snapshot requires prior exact invalidation. A mismatched revoke, unknown liveness reference, elevated nested authority, forged completeness, malformed structure or stream ordering error clears the cache and quarantines the instance. The standard-library checks have finite size/depth limits and enforce supported shapes and safety invariants; the existing Draft 2020-12 schemas remain the formal contracts. No runtime schema dependency is added.

Local states are `WAITING`, `OBSERVING`, `INVALIDATED`, `STALE`, `CLOSED` and `PROTOCOL_ERROR`. Only `OBSERVING` has a current DecisionState/reference. Invalidated references cannot be restored by liveness; stale, closed or quarantined instances require a new explicit subscription. A `session_stopped` invalidation permits only the terminal stopped event next. All views remain read-only, non-actionable and disconnected from execution. `new_request_observed` preserves the publisher's observation flag; history snapshots and candidate content grant no new decision opportunity or input authority. `source.freshness_verified` remains false.

Both local lease defaults are five seconds, configurable from 1ns to 24h, with expiration strictly above the limit. They are consumer policy, **not MTGA protocol TTLs**. Liveness updates transport receipt and can increase the reported age; it cannot reduce age or renew the original evidence anchor. Observation age is conservatively the maximum of the existing locally elapsed age and the latest producer-reported age plus local queue delay. This still cannot measure server state age or time spent upstream before local receipt.

A bounded reader queue allows ticks while stdin remains open and silent. Queue overflow terminates with protocol error rather than skipping events. Input exceptions, partial/unterminated JSON lines, cancellation, output disconnect and EOF clear current content. EOF without stopped reports `unexpected_eof` and exit 1; normal stopped exits 0 (producer `source_error` exits 1). Stale/protocol failure exits 1. The CLI emits only consumer status, sequence and safe reason/authority fields, without echoing bindings or private DecisionState content.

One independent daemon writes diagnostics, while the consumer core exclusively validates events, maintains its cache and checks the unchanged leases. The output bound is 64 pending ordinary diagnostics, one in-flight write and one reserved terminal diagnostic. Output overflow clears current with `PROTOCOL_ERROR/diagnostic_output_queue_overflow`; input overflow retains its separate `input_queue_overflow` reason. Failure/cancellation prioritizes the final reason and discards pending diagnostics, marking the terminal `diagnostics_complete=false` with `diagnostics_dropped`. This truncates diagnostic history, not the validated input event order. Quarantine ends the subscription; its unread input tail is not claimed delivered.

Shutdown waits at most 750ms for output. Persistent blocking can leave one daemon write in flight until CLI process exit closes the OS pipe. Arbitrary programmatic callbacks cannot be forcibly cancelled; their owner must release/close the resource if it needs that thread to finish. CLI writes use raw descriptors to avoid a daemon holding Python's buffered stdout lock at interpreter shutdown. Bytes already in flight cannot be recalled, and the final diagnostic may never arrive. A downstream reader must treat EOF/nonzero termination as session invalidation and require a new subscription. Internal revocation continues while stdout is blocked; external timely notification over that blocked channel is not guaranteed. OS scheduling, source/server freshness and a real three-second loop remain unqualified.

### MP18 local delivery qualification

From the repository root, run `.\.venv\Scripts\python.exe scripts/qualify_delivery.py --samples 200 --interval .01`. This stdlib-only development tool appends scrubbed/synthetic records to controller-owned temporary files and launches the actual `python -m mtgaplayer watch --decision-events` and `consume-events` CLI processes with a direct OS pipe. It never accepts a private log as input. Temporary `sitecustomize` probes add producer read-offset/event-sequence evidence and post-validation consumer cache confirmations; formal events and production modules on disk are unchanged. A separate uninstrumented CLI pair checks the literal entry points. Probe copies/confirmation output add overhead, so these are instrumented local observations.

The safe summary, sample records and transport/cache trace are saved as `artifacts/local-mp18-phase4/qualification.json`, `qualification-samples.jsonl` and `qualification-events.jsonl`. The controller's own monotonic timestamps measure before-write and flush-return to consumer result read; they include result output/read overhead and do not measure pure consumer processing or disk durability. Startup, changed polls and idle polls are separate. Producer durations are deduplicated per poll, child clocks are never cross-subtracted, and unknown serialization/queue/source stages stay unknown. Successful distributions use nearest rank; failures, timeouts, unassociated results and unattempted samples remain explicit.

Qualification covers request delivery/consumption/replacement, state advance, continuity failure, partial completion, Full recovery, reset, poll-level burst coalescing, a larger visible-object frame, natural stop, abrupt EOF and an open silent pipe. Its original Phase 4 backpressure result reproduced synchronous output blocking the core; that historical evidence is preserved. The default measurement interval is 10ms, not the production watch default of 250ms; results from different intervals must stay separate. No live/server freshness or real three-second-loop qualification follows from these local synthetic results.

Run `.\.venv\Scripts\python.exe scripts/qualify_backpressure.py --output artifacts/local-mp18-phase5/backpressure.json` for the bounded Phase 5 counterexamples. They pause reading actual consumer stdout, confirm an actual write remains blocked, and observe core cache clearing before reads resume: observation age with continuing liveness, open-pipe transport silence, a new request, separate input/output overflow, synthetic Python cancellation, abnormal producer EOF and blocking beyond shutdown grace. Temporary read-only probes sample plain internal fields and wrap original core transitions; the observer never calls `tick` or `current_view`. Test stderr is internal evidence only, not a product notification bypass. Output recovery checks the final reason; persistent blocking explicitly permits terminal loss and records the abandoned writer. Normal/deep-copy/default CLI regressions remain in the existing suites.

### MP21 offline static-rule reference index

Prepare a local Scryfall **card JSON array** yourself, then create a new versioned index:

```powershell
python -m mtgaplayer import-rules "<local-card-array.json>" --output "<new-rules-v1.sqlite>" --source-version "<dataset-version>"
```

The command streams UTF-8 input (up to 2 GiB, one million records and 1 MiB buffered per card), stores only selected static fields, and reports counts plus the source SHA-256. `source_version` is a user-supplied label, not independent freshness or authenticity proof. Existing outputs are never overwritten; failed imports leave no published index. Select a new path to update.

`mtgaplayer.rules_index.lookup_rules(path, arena_ids)` reads exact Arena IDs from the index with immutable/read-only SQLite. Missing IDs stay unresolved; every duplicate ID stays ambiguous, including identical duplicates. Names never disambiguate. Scryfall printing/Oracle IDs, digital flag, layout and separate card faces are preserved; absent fields stay null. No face is selected, no face texts or costs are merged, and `power`/`toughness` remain literal strings. Reference text/keywords/cost are not current effects, effective stats, payment legality or complete rules. Runtime performs no downloads or LLM calls; the repository bundles no card dataset. Default replay/watch and DecisionState/Event v1 remain unchanged.

### MP22 visible-object static-rule context

```powershell
python -m mtgaplayer replay --format player-log --rules-index "<rules-v1.sqlite>" "<explicit Player.log>"
```

`--rules-index` implies `--decision-state` for raw replay/dry-run. It adds a separate `static_rule_context` with `schema_version=mtgaplayer.static-rule-context.v1`, full state/request `binding`, `rules_source` version/SHA provenance, one `objects` row per projected visible object, reconciled `counts`, unresolved facts and false execution flags. The Python entry is `mtgaplayer.rule_context.build_static_rule_context(decision_state, index_path)`.

For a subscription, `mtgaplayer.rules_index.load_rules_index(index_path)` prepares the explicit local index once before starting event consumption. The returned `PreparedRulesIndex.lookup(arena_ids)` has the same valid-data result as file lookup, returns detached copies and performs no filesystem or SQLite operations. Its source version/SHA stay fixed even if the original path is removed or replaced; start a new subscription to change versions. Defaults bound 100,000 indexed IDs and 64 MiB of encoded JSON payload, including metadata values (Python heap overhead is additional). Complete row/metadata validation and count reconciliation precede publication; limits or corruption fail explicitly. Missing IDs stay unresolved and duplicate catalog IDs stay ambiguous. No downloads or implicit reload.

### Optional DecisionState / DecisionEvent v2 turn context

```powershell
python -m mtgaplayer replay "<explicit Player.log>" --format player-log --decision-state-version 2
python -m mtgaplayer watch "<explicit Player.log>" --decision-events --decision-state-version 2 --samples 1000 | python -m mtgaplayer consume-events --advice --rules-index "<rules-v1.sqlite>"
```

Version1 remains the default and its three-field turn contract is unchanged. Explicit `--decision-state-version 2` adds observed `phase`, `step` and `priorityPlayer` to `DecisionState v2`; event mode emits `DecisionEvent v2` embedding only State v2. A Consumer accepts either pair but pins the first accepted Event version for its subscription; mixed/crossed/unknown versions fail closed. Python entry points use `decision_state_version=2` on replay/watch/watch_decision_events, `version=2` on build_decision_state and `state_version=2` on DecisionPublisher. Formal v1/v2 schemas are separate local URNs.

Values are literal bounded `Phase_...` / `Step_...` labels and seat1/2 or null, not a phase rules engine or complete enum claim. Decision player and priority player are independent. Missing entire Diff turnInfo inherits the prior observation; a provided turnInfo replaces it, so omitted fields become null. Never infer step from nextStep, turn changes or prior phase. Invalid new fields withhold State v2 (explicit replay exits1); legacy raw/DecisionInput/v1 output remains unchanged. Private turn staging is removed before CLI output. Existing Advisor/static references accept validated v2, without changing policy, effects, legality or execution rights.

### Current Consumer static references

```powershell
python -m mtgaplayer consume-events --rules-index "<rules-v1.sqlite>"
python -m mtgaplayer consume-events --advice --rules-index "<rules-v1.sqlite>"
```

This explicit option prepares the index before creating the Consumer or starting its leases/input reader. Diagnostics add `current_rule_context` (`mtgaplayer.current-static-rule-context.v1`) with the full `source_snapshot_ref`, state/request `binding`, `source_phase` and source version/SHA. Python callers pass `prepared_rules=load_rules_index(path)` to `consume_events`; `assess_current_rule_context(consumer, prepared)` also reads the existing Consumer directly. Paths and detached views cannot establish a current context. Index preparation failure produces an explicit unavailable context while normal evidence-only advice/status continues. Without the option, output is unchanged.

The existing owner thread associates only validated visible catalog IDs. History and requestless snapshots may supply static reference, marked by their phase/binding; `new_live_opportunity` is always false. No new Consumer/reducer, policy or execution path is introduced. Each current context permits at most 1 MiB of encoded reference-card JSON, counting repeated visible instances before copying; excess yields `rules_context_limits_exceeded`, empty objects and no partial result. This bounds reference payload, not Python heap or total diagnostic bytes. Rules-source and current-reference bindings stay independent: static data never proves live freshness, current face, effects, payment, targets or full legality.

Invalidation, lease expiry, source stop, malformed stream, EOF and subscription stop remove reference content. A final owner-thread lease/ref check after **all** sidecars also revokes earlier advice if context computation crossed expiry. Output backpressure cannot stop cache clearing, but already in-flight bytes cannot be recalled and terminal delivery can be lost after the existing grace. Readers must discard old results on ref change, invalidation, termination or EOF; a serialized reference context grants no continuing currentness.

Only already-projected visible `card_id` values supply exact lookups. SelectN instance references, hidden cards, last_valid, names and ambiguous visible-instance identities supply no completion. Rows distinguish resolved static reference, absent ID, catalog ambiguity, missing card ID and visible identity ambiguity. Multi-face data remains separate and `current_face` stays null; static text, costs, keywords and literal P/T never become current effects or legal actions. The sidecar describes its bound snapshot, grants no continuing currentness and must be discarded when that binding changes. Missing/invalid indices yield an unavailable context with empty content and an explicit reason; an otherwise valid raw replay still exits successfully. Invalid state never triggers a catalog query. DecisionState/Event v1, Advisor, default replay/watch and the existing local title catalog are unchanged.

### Visible snapshot endpoint changes

```powershell
python -m mtgaplayer consume-events --observed-changes
python -m mtgaplayer consume-events --observed-changes --advice --rules-index "<rules-v1.sqlite>"
```

This opt-in adds `observed_changes` (`mtgaplayer.observed-changes.v1`) to the existing owner-thread diagnostics; Python callers use `consume_events(..., observed_changes=True)`. Default output is unchanged and both Event/State version pairs work. It retains at most one validated comparison baseline and accepts only an existing Consumer's accepted `state_advanced` invalidation immediately followed by a valid append snapshot. A tick/liveness gap while invalidated discards that baseline conservatively. Other invalidations, reset/recovery, identity breaks, partial/malformed source, expiry, EOF and stop clear it. No second reducer, Consumer, lifecycle ledger, timer or worker is introduced.

Results are `baseline_observed`, `endpoints_compared` or `unavailable`. Full before/after snapshot refs bind successful comparisons; `source_snapshot_ref` is the after ref. Counts reconcile to change entries. Fields include known public player life and same-instance/same-known-card zone, tapped and controller values. Missing/ambiguous identity or unknown endpoints are not compared. Entering/leaving only means membership in the visible projection; a left instance ID is a previously published reference, not an assertion about its later hidden destination. Static rules and hidden/request-only references never enrich these facts.

These are two published endpoints, not a complete GRE event sequence, damage/death/draw/resolution proof or a cause/effect model. No tracked differences does not prove the game was unchanged. The existing 512-object input bounds limit rows; at most1MiB of encoded change-row JSON is returned, otherwise the entire result is unavailable without partial entries (not a heap/total-diagnostic bound). A final current-ref/lease check after all sidecars clears comparisons and earlier advice when computation crosses expiry. Output backpressure does not stop clearing; in-flight bytes remain irrevocable and external readers must revoke on invalidation/ref change/termination/EOF. All execution flags and new_live_opportunity stay false.

### MP23 Advisor CLI delivery

Enable read-only evidence assessment on the existing event pipeline:

```powershell
python -m mtgaplayer watch "<explicit Player.log>" --decision-events --samples 1000 --interval 0.25 | python -m mtgaplayer consume-events --advice
# Explicit experiment; still research-only and never sends input:
python -m mtgaplayer consume-events --advice --advice-policy simple_type_research.v1
# Historical research, optionally alongside the MP22 static-rule sidecar:
python -m mtgaplayer replay --format player-log --advice --rules-index "<rules-v1.sqlite>" "<explicit Player.log>"
```

`--advice` defaults to `evidence_only.v1`; `--advice-policy` requires `--advice`. Without these flags, existing status-only consumer output and replay output are unchanged. Opted-in diagnostics add the existing versioned `decision_advice` object, including snapshot/request bindings and candidate references; keep these local. The same Consumer owner thread computes advice; reader/writer workers own no state, and no second ledger or policy algorithm is introduced. Replay/dry-run assessment is always historical, with no current preference; static rules remain separate and never affect policy scores.

For the supported SelectN slice, the State/Consumer boundary requires a nonempty unique domain of strict instance IDs and a strict positive `max_sel_raw` no larger than that domain, matching the existing GRE decoder. Invalid domains are rejected rather than repaired or labeled integrity-verified. Advisor exposes one LA1 `candidate_assessments` row per offered option in original order, keyed by full request identity and `option_position`. `offered_instance_id` remains a request reference: no card/name/static-rule enrichment and no fabricated ActionsAvailable `list_position`. Both policies continue to abstain on SelectN; minimum, legal combinations, strategic utility and encoding remain unknown.

Append observations may receive the existing explicitly selected simple-type research preference; historical requests cannot. Liveness retains the identical snapshot-bound advice and `new_live_opportunity=false`. Invalidated, expired, closed, malformed or stopped subscriptions cannot supply a preference or candidates. A final owner-thread check discards advice if assessment crossed the observation lease. Consumers must discard earlier advice on invalidation/termination/EOF; an advice object grants no continuing currentness.

The existing bounded independent output queue, fail-closed overflow, strict event order, leases and shutdown grace are unchanged. Already in-flight bytes cannot be recalled and persistently blocked stdout cannot guarantee timely revocation/terminal delivery; queued records are research observations of their bound snapshots. This finite producer/one-shot consumer is no server-freshness, optimal-strategy, real-game execution or three-second-loop qualification. No database/network/LLM work is added to the current consumer path.

### MP19 evidence-bounded decision advisor (read-only research)

`mtgaplayer.decision_advisor` assesses existing projections without calling the synthetic harness policy, parsing GRE, querying a database or connecting an executor. The APIs are:

```python
from mtgaplayer.decision_advisor import (
    assess_current_decision, assess_decision_state, SIMPLE_TYPE_POLICY,
)

# consumer is the existing DecisionConsumer; call on its owner thread.
evidence = assess_current_decision(consumer)
experiment = assess_current_decision(consumer, policy_version=SIMPLE_TYPE_POLICY)
history = assess_decision_state(replayed_decision_state)
```

The current entry reads one fresh `consumer.current_view()` before pure assessment. A detached view dictionary is rejected because it cannot notice subsequent invalidation, EOF or expiry. Current research requires OBSERVING, a matching snapshot/state/request binding, a newly observed request and watch/append provenance. WAITING, INVALIDATED, STALE, CLOSED, PROTOCOL_ERROR and historical requests explicitly abstain. Re-evaluate the latest consumer after lifecycle changes; an old advice object grants no continuing currentness. The pure state-only entry always marks `historical_research_only`, never creates a live opportunity and never grants a current preference. No second consumer, reducer or lifecycle ledger is created.

Advice uses `schema_version=mtgaplayer.decision-advice.v1`, `assessment_status` (`abstain` or `research_preference`), snapshot/request binding, policy version, coverage, candidate assessments, nullable preferred candidate/basis, abstention reason and unresolved facts. It keeps `read_only=true`, `new_live_opportunity=false` and all execution/legality flags false. Action references normalize the projection's legacy `generation` to `source_generation` and include match/game/seat/state/request/type plus the original engine `list_position`; identical types at different positions remain different candidates. Only active frontier templates supply actions. Count, positions, identities, active-only scope and source links must reconcile; null/conflicting/truncated inventories remain unknown. ChoiceGraph can reveal a conflict but never supply missing actions, and its raw identifiers/parameters are not exported.

The default `evidence_only.v1` policy abstains from preference while preserving all valid candidates, including unsupported ones. Evidence properties such as ENGINE_OFFERED, STRUCTURE_INTERPRETED, PARAMETERS_PARTIAL, UNSUPPORTED_STRUCTURE, COMBINATION_UNKNOWN and RESPONSE_UNVERIFIED are separate from strategic utility, which remains null. LA1/limited structural LA2 evidence provides no new LA3 legal-choice, LA4 execution or LA5 outcome proof.

Explicit `simple_type_research.v1` may prefer the sole Play position only when every active row is an interpreted simple Pass/Play, other rows are Pass, parameter shapes are empty and there are no unknown fields, unsupported reasons or graph conflicts. Both `preference_basis` and `policy_basis` are `unverified_simple_type_heuristic`. This is a type preference experiment, not a claim that Play is correct, Pass is conservative, the source is a land or costs/targets are legal. Multiple Play, complex/unknown actions, incomplete structures and Pass-only inventories abstain; position never supplies strategic weight. No response payload, coordinates or ActionPlan is produced.

SelectN reports existing candidate count and raw maxSel with unknown minimum/combinations. Combat reports only existing public candidate references and explicit blocker relations; attack recipients, mandatory combat, combinations, ordering and damage remain unknown. Neither request participates in strategy ranking.

Run `.\.venv\Scripts\python.exe scripts/measure_decision_advisor.py --samples 200` for bounded scrubbed/synthetic timings: extraction, evidence classification, heuristic preference and the complete current API, with N/p50/p95/p99/max and raw local durations. Stage calls are independent, not additive. Timing fields stay outside deterministic advice. This measures no real source, server freshness or live three-second loop. Default replay/watch, Consumer, DecisionState and the old synthetic policy remain unchanged.

### MP18 opt-in unified DecisionState v1

`--decision-state` assembles a single read-only snapshot, using the existing GRE reducer and projections. It works alone; the independent `--decision-input`, `--action-frontier`, `--choice-graph` and `--combat-frontier` options retain their existing dependency checks and opt-in output. Examples using committed sanitized fixtures:

```powershell
python -m mtgaplayer replay --format player-log --decision-state tests/fixtures/player_log_selectn.jsonl
python -m mtgaplayer watch --decision-state --samples 1 tests/fixtures/player_log_minimal.jsonl
```

The additional `decision_state` property uses `schema_version=mtgaplayer.decision-state.v1`; its independent [Draft 2020-12 JSON Schema](schemas/decision-state.v1.schema.json) also accepts null for invalid, discontinuous or partial current sources. A valid state without a current own request still exposes verified visible state, with null request identity and an unknown/not_provided action space. It never substitutes last_valid or an empty legal-action domain. `binding.source_generation` corresponds to the existing child projections' `request_identity.generation`; all other identity fields must agree with the same current snapshot.

Only the current request's ActionsAvailable frontier/ChoiceGraph, SelectN observation or CombatFrontier participates. `confirmed_empty` means an explicitly observed empty offered container, with completeness still partial; missing/unavailable/unsupported data remains null and unknown. Expanded plans remain unknown. SelectN IDs are request references, not visibility joins. Combat recipients remain count-only and missing blocker relationships remain unknown. No historical response validation becomes a current verified choice.

Replay's optional `--card-db` enrichment contributes static knowledge for already visible objects only. Effective power/toughness and effect_claims remain null; static P/T is not effective P/T. All six legality/encoding/acceptance/execution/input flags are false, read_only is true, and source freshness is unverified even for watch. No new log reader, parser, rule graph, effect engine, runtime dependency, IPC or input path is added. Default output is unchanged. A private continuity bit in the existing reducer request distinguishes uninterrupted requests from requests retained for legacy diagnostics after Full recovery; DecisionState excludes the latter until a fresh request, without altering the legacy read-only diagnostics or adding a second lifecycle ledger.

### MP17 opt-in strict combat references (read-only)

`replay`/`dry-run --format player-log --decision-input --combat-frontier` and finite `watch --decision-input --combat-frontier` optionally project the latest authenticated combat request snapshot. DeclareAttackers reads only `qualifiedAttackers[].attackerInstanceId`; DeclareBlockers reads `blockers[].blockerInstanceId` and its explicit `attackerInstanceIds` relationships. Only references uniquely matching the existing public battlefield projection are exposed. Missing/invalid/duplicate/truncated data remains unresolved; unqualified aliases, historical flags and default recipients never fill a gap. Default output is unchanged.

The frontier reports request identity, observed/verified/unresolved reference counts, partial/unknown completeness and provenance. Counts describe reference occurrences, not legal combinations. `legalDamageRecipients` is count-only; the complete attacker and attack-target domains, combat restrictions, order/damage, encoding and server acceptance remain unknown. Historical/stopped snapshots confer no live availability; all legality/execution/input flags remain false. This is a local implementation candidate supported by a strict-gate safe aggregate, not an executor or combat solver. See the current progress entry for real-source and test limitations.

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

### Research preference admission

The opt-in simple_type_research.v1 policy requires explicitly interpreted request fields and positive source card-ID agreement for Play. Unknown request-envelope/body fields and missing legacy evidence withhold a preference while retaining engine-offered rows and their positions. A unique visible instance and agreement of card IDs are independent observations; mismatch is not proof of an illegal action. Evidence-only remains the default, and no result grants execution authority.
