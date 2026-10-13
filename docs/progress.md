# MP0–MP3 candidate status

The user authorized implementation of the 2026-10-13 task pack, scoped repairs, tests, four logical commits, push and one candidate PR. Stop at the PR; do not merge or send MTGA input. The package is an independently runnable finite harness prototype, not a completed MTGA player.

Baseline: the supplied workspace was empty. Cloned `https://github.com/M0DIAN/MTGAPlayer.git`; remote main, initial HEAD and origin/main were `4fbdeb465dc185814654cff13efd487fb6678978` (tree `c03ba980f7783c61aa77a7370a905422152b7adf`). Network queries before development and before freezing confirmed the same remote main. No pre-existing changes or applicable parent AGENTS. Branch: `codex/mp0-mp3`. Candidate SHA, PR CI tested revision and frozen review are reported on the candidate PR and in the final handoff, avoiding a self-referential commit SHA in this file.

Product interpreter: independent Python **3.11.16**, base `D:\Development\python\cpython-3.11-windows-x86_64-none`, project `.venv`, tkinter 8.6. Python 3.12 was unavailable; 3.11 compatibility was exercised. Runtime: standard library only; setuptools is build-only. APD/Codex are development tools, not runtime dependencies.

| Task | Delivered / remaining |
| --- | --- |
| MP0 | Package, real CLI entry points, doctor, replay, lightweight split CI and source/license audit. |
| MP1 | Normalized NDJSON v1 incremental ingestion, partial records, replacement/truncation, explicit match/game generations, transactional projection, visible references, freshness, request ledger and diagnostic separation. Raw GRE/Player.log decoding remains unsupported: PARTIAL for real MTGA integration. |
| MP2 | Independent GDI screenshots, SendInput, marker identity binding, land drag / cast-target-submit / priority click, context invalidation and action-specific postconditions validated on the native harness. MTGA visual localization remains NOT_IMPLEMENTED: PARTIAL for real MTGA integration. |
| MP3 | Deterministic finite synthetic rules, persistent bounded loop, stop/pause/re-enable and complete semantic timing. Native normal set passes; unknown effects and dynamic reordering are refused. Actual cards/decks/full games remain unsupported: PARTIAL. |

| Acceptance layer | Actual evidence |
| --- | --- |
| OFFLINE | 32 focused unittest cases passed after repairs; package install, doctor, replay and dry-run actually run. Final root validation and source hashes: `artifacts/offline-candidate/validation.json`. Synthetic fixtures/mock executors are labelled offline. |
| NATIVE_HARNESS | `artifacts/native-local-02`: 30 consecutive real-input confirmations, land/cast/pass 10 each, including 10 complete target+submit casts. Real separate process, screenshots, 100 mouse callbacks and specific state effects. Final bundle also retains its own native run. |
| LIVE_MTGA | NOT_RUN. No game started or MTGA input/resources used. A visible MTGA title in doctor is only scoped window inventory, not adaptation or input evidence. |
| LATENCY | Normal local-02 set: p50 125 ms, p95 235 ms, p99/max 359 ms, startup 563 ms, timeouts 0. Limited harness result only. Reordering negative timed out at 3063 ms: overall dynamic-layout/MTGA three-second target is NOT_ESTABLISHED. |
| DECISION_QUALITY | Basic synthetic legality/tactics only. No win-rate, real-deck or global-optimum evidence. |

All opportunities retain seven monotonic timestamps, including null stages for refusal. Compound target/submit requests retain the root opportunity origin. Failure, unsupported, paused, cancelled, uncertain and timeout counts are not discarded. Native negatives: `native-negative-unsupported` has 1 unsupported/no input; `native-negative-target-disappear` has 1 confirmed land then 1 uncertain cast and stops without retry; `native-negative-reorder` has 1 timeout/no input. Their reports intentionally do not say native acceptance PASS.

Old source audit: both 52-file v0.4.6 copies match by SHA256, MIT. They are installed directories, not Git checkouts; release-record commit association is not checkout verification. The old v0.4.1 traceback survives, but its triggering original GRE sequence is absent. Current old source already handles cross-match boundaries; new synthetic regressions cannot establish reproduction of the historical game. See `THIRD_PARTY.md` for reused follower algorithm, replaced reducer/coordinator/UI and exact source hashes/license.

Repairs verified: duplicate/same-game identity and seat conflicts remain latched until explicit new identity/source reset; independent request events validate visible references transactionally. Shared screenshot readiness waiting is bounded by the original deadline/expiry, checks context before and after capture, retries only absent/old pixels, rejects ambiguity/focus/stop/takeover, and never retries semantic input. Terminal confirmation checks both matching pixels and the specific effect.

Evidence history is retained: `native-attempt-01` (venv redirector PID mismatch), `native-attempt-02` and `native-final*` (worker focus=0), `native-local-01` (initial pixels absent), `native-capture-probe` (real no-input harness screenshots), `readiness-repair` (before-source snapshots, initial fixture failure, passing repairs, source manifest), `native-local-02`, `native-negative-*`, and final `offline-candidate` / `native-final-candidate`. No original full game logs, hidden opponent data or game assets are distributed. Images show only the custom synthetic window.

APD development/repair produced code and scoped review, but its final read-only TEST stage could not create two temporary directories and could not access an effective foreground window. This is preserved as WORKER_NOT_PASS, not converted to whole-project PASS. Root validation uses the existing authorized desktop and project scratch directory without changing isolation or elevating permissions. Frozen-commit independent review is performed separately and must inspect task requirements, actual code and raw evidence.

Actual commands (from repository root):

```powershell
.\.venv\Scripts\python.exe -m pip install --no-build-isolation -e .
.\.venv\Scripts\python.exe -m mtgaplayer doctor
.\.venv\Scripts\python.exe -m mtgaplayer replay examples\synthetic.jsonl
.\.venv\Scripts\python.exe -m mtgaplayer dry-run examples\synthetic.jsonl
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe scripts\validate.py --suffix=-candidate
```

Each artifact manifest retains exact argv/exit codes. CI has Ubuntu logic/replay and Windows no-input doctor jobs, each capped at 10 minutes; current results and HEAD/base/merge-ref mapping belong to the candidate PR, not older green runs. Next batch: adapt verified raw GRE parsing, define a supported real deck/effect scope, then establish MTGA object recognition and authorized live confirmation. Harness markers and synthetic mana rules must not be extrapolated to the game.

## PR #1 response / Full retransmission repair (2026-10-13)

The starting candidate was `d3940641888e73b4fcac834bbff8bb94f7e91426` on `codex/mp0-mp3`. Independent reproduction through `.venv/Scripts/python.exe -m mtgaplayer replay` confirmed that `begin(m1,g1,seat=1), full(v1,r1), response(r1), identical full(v1,r1), full(v2,r2)` exits 1 with `valid=false` and latched `conflicting_duplicate_state`. Removing the retransmission exits 0 with valid request r2. Local raw inputs/stdout/stderr are retained in ignored `artifacts/local-response-repair/`; the regression tests retain the reproducible sequence in the PR.

This repair separates accepted producer content from local request consumption. Identical Full retransmissions must preserve the consumed-request ledger and the original state/request freshness, including after non-conflict corruption recovery; a genuinely newer legal version can still introduce r2. Content, seat, identity and immutable-request conflicts remain blocking. Scope is the reducer, directly related existing tests and this explanation.

Validation: the implementation agent first ran the new regressions against the old reducer and observed failures, then all **39 tests (original 32 + 7 new)** passed. Root independently reran the complete suite and the exact replay/control inputs: both now exit 0 with valid r2. The installed `mtgaplayer doctor`, existing example replay and dry-run also exit 0, all with `input_sent=false`. Added regressions cover consumed r1, state/request clocks and expiry, true conflict latching, non-conflict recovery, request/diff/new-game/generation lifecycle, and incremental `Reader.sample` / `Executor.context` with no dispatch. Existing diff omission semantics are preserved. Tests use project `.venv` Python 3.11 and project `.tmp` for TEMP/TMP because the sandbox cannot write the default Windows temporary directory.

Native impact is on the shared state-reading boundary: `Reader.sample` feeds this reducer to `Executor.context` and the run-loop actionable gate. The input adapter, screenshot/identity binding and semantic postconditions are unchanged. This round uses offline regression and no-input checks of that path; it does not claim a new screenshot/SendInput run. Existing native artifacts remain unchanged. `artifacts/native-final-candidate` is historical native-harness evidence associated with d394064 through equality of all 13 source-file SHA-256 values in `artifacts/offline-candidate/validation.json`; that manifest's top-level `head=4fbdeb...` records the precommit baseline, not its source content. The older `native-local-02` and three `native-negative-*` groups have intact recorded hashes but no per-run source-revision binding. None establishes native acceptance on the repaired HEAD.

The previous frozen-candidate independent report and CI remain historical records for d394064. The new incremental review and CI revision mapping are recorded on PR #1 against the repaired candidate. The PR is open and **non-Draft**, awaiting owner acceptance; do not merge. Real GRE decoding, real-deck decisions, MTGA object localization and the live three-second goal remain unfinished; LIVE_MTGA remains NOT_RUN.

APD 0.3.2 could not start this repair (`APD_FAIL_CLOSED: openai-codex is not installed`); no development stages ran and no global tool installation or APD retry was attempted. The authorized narrow repair uses separate implementation and independent review agents. This startup failure is separate from the earlier APD TEST limitation above.
