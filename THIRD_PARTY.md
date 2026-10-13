# Source inspection and reuse

Read-only source: `E:\MTGA\skills\mtga-play`, VERSION **0.4.6**, MIT, Copyright (c) 2026 MODIAN. Installed copy: `C:\Users\Administrator\.agents\skills\mtga-play`, VERSION 0.4.6. arena_log.py hashes match. No game assets, database, original full logs, private backend or Skill package are redistributed.

| Source file (SHA256) | Decision |
| --- | --- |
| arena_log.py `2c7ad020ca31ced817bbd972d13a47143251a9e8573e9412de54cc536cd00ebf` | Adapt LogFollower reset/prefix/anchor algorithm into stream.py and raw_log.py. Normalized stream uses strict NDJSON; raw_log.py separately adapts bounded brace/quote framing, GRE Full/Diff entity replacement and visible-zone gating. Both use opened-handle fstat. Raw identity binding adds authenticated clientId→room reservedPlayers.userId→seat and recipient checks; it does not rely on recipient alone. |
| track_state.py `ce44c269186548fa520523ef77a8ee5e2be94cb56a5140b56bf37467dc0e1653` | Adopt diagnostic last_valid/first_error separation concept; transactional reducer is new. No watcher copied. |
| card_model.py `fe4e73b6cc2a5e3263a316ddebbede7ca7a39894c452f460fcf4df2d43af6dadf` | Not ported: export_cards/database coupling; explicit synthetic rules replace it. |
| arena_ui.mjs `8628c90089aa7f38867d9b18d3721b3ee21d6b17398fe27c3465834cb7f8532c` | Replaced: injected sky backend and agent_screen_review confirmation cannot establish independent operation. |
| match_session.mjs `423203787f9baeb92c49856ec1326116cc50b62267a95361a57e3f15b3c4d4a3` | Replaced with native executor; retain ideas of cancellation, immutable intent and request binding. No JS shipped. |

MIT notice is retained in [LICENSES/mtga-play-MIT.txt](LICENSES/mtga-play-MIT.txt).

Inspected focused arena_log and match_boundary tests. The 0.4.1 acceptance live-failure/terminal traceback confirms a historical seat conflict but does not contain the triggering original protocol sequence. Current 0.4.6 already has cross-match handling; do not infer that historical defect persists. This candidate's tests are explicitly synthetic, including same-match/new-game seat rebinding, old Full/duplicate/gap recovery, consumed request retransmission, and corruption without a subsequent state. They are not a replay of that historical match.

MP4's `tests/fixtures/player_log_minimal.jsonl` is a reduced real Player.log chain observed 2026-10-13, taken from the latest match's raw entry ordinals 4560, 4562, 4563, 4566, 4567, 4568, with a minimal earlier authentication envelope. It retains actual Full/Diff IDs and previous-ID links, zone/object membership and visibility/viewers, public player life, a broadcast prompt, a local Mulligan request and its client `respId`/`gameStateId` relation. Match/user identities and timestamps are replaced with fixture tokens; authentication credentials, chat, transactions, unrelated payloads, names and original log prefixes are omitted. Non-visible opponent identity is replaced with `HIDDEN_SENTINEL` where present. The original Player.log, game resources and private runtime are not committed. Fixture tests assert the observed Full 1 → Diff 2/3/6 chain and known own-hand cards; this supports the sampled protocol slice only.
