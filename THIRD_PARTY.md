# Source inspection and reuse

Read-only source: `E:\MTGA\skills\mtga-play`, VERSION **0.4.6**, MIT, Copyright (c) 2026 MODIAN. Installed copy: `C:\Users\Administrator\.agents\skills\mtga-play`, VERSION 0.4.6. arena_log.py hashes match. No game assets, database, original full logs, private backend or Skill package are redistributed.

| Source file (SHA256) | Decision |
| --- | --- |
| arena_log.py `2c7ad020ca31ced817bbd972d13a47143251a9e8573e9412de54cc536cd00ebf` | Adapt only LogFollower reset/prefix/anchor/bounded append algorithm into stream.py. Replace brace framing with strict normalized NDJSON, ordered parse errors, opened-handle fstat. |
| track_state.py `ce44c269186548fa520523ef77a8ee5e2be94cb56a5140b56bf37467dc0e1653` | Adopt diagnostic last_valid/first_error separation concept; transactional reducer is new. No watcher copied. |
| card_model.py `fe4e73b6cc2a5e3263a316ddebbede7ca7a39894c452f460fcf4df2d43af6dadf` | Not ported: export_cards/database coupling; explicit synthetic rules replace it. |
| arena_ui.mjs `8628c90089aa7f38867d9b18d3721b3ee21d6b17398fe27c3465834cb7f8532c` | Replaced: injected sky backend and agent_screen_review confirmation cannot establish independent operation. |
| match_session.mjs `423203787f9baeb92c49856ec1326116cc50b62267a95361a57e3f15b3c4d4a3` | Replaced with native executor; retain ideas of cancellation, immutable intent and request binding. No JS shipped. |

MIT notice is retained in [LICENSES/mtga-play-MIT.txt](LICENSES/mtga-play-MIT.txt).

Inspected focused arena_log and match_boundary tests. The 0.4.1 acceptance live-failure/terminal traceback confirms a historical seat conflict but does not contain the triggering original protocol sequence. Current 0.4.6 already has cross-match handling; do not infer that historical defect persists. This candidate's tests are explicitly synthetic, including same-match/new-game seat rebinding, old Full/duplicate/gap recovery, consumed request retransmission, and corruption without a subsequent state. They are not a replay of that historical match.
