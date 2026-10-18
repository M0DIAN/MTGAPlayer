# Lossless local Player.log evidence archive (MP77)

This is explicit local evidence storage, not a game-input or rules feature.
The default Collector still stores reserialized framed records, not original
bytes. Its existing JSONL/screenshot snapshot contract is unchanged.

Run from this checkout with its Python 3.11 environment. Choose the source and
an **untracked Git-ignored directory or a directory outside Git** explicitly:

```powershell
python scripts/local_live_poc.py archive --log <Player.log> --output <private-directory> --once
python scripts/local_live_poc.py archive --log <Player.log> --output <private-directory> --resume --duration 60
python scripts/local_live_poc.py verify-archive --archive <private-directory>
```

Without `--once`/`--duration`, archive until Ctrl+C or a local `stop` file in the
archive directory. An existing `stop` file also stops a resumed session; the
tool never deletes it. `--once` means one bounded poll, **not necessarily EOF**.
Check the reported byte count/backlog and completion fields. A new archive
requires a new directory; only explicit `--resume` may reopen one.

The existing Collector also accepts `collect ... --raw-archive <directory>`.
It archives the **same read calls** that feed its existing RawFramer/RawReducer;
there is no additional state pipeline or incremental reread/copy. Collector
sessions remain fresh; resume is an archive-only operation, not restoration of
an old current game state. Archive-only mode does not capture screenshots.

## Bytes, generations and commit boundary

Each poll writes an exclusive, randomly named `segment-*.raw` file, preserving
all original bytes including non-UTF-8 text, whitespace, CRLF, malformed JSON
and unfinished tails. Segment files are never opened for overwrite. A segment
is evidence only after its bytes have been flushed/fsynced and an atomic
manifest replacement commits its generation, original byte interval, length,
SHA256 and start/completion timestamps. The manifest also carries a cumulative
generation SHA256. Empty polls do not create data segments.

The manifest and lock are mutable local bookkeeping, not immutable evidence
segments. A process-scoped OS file lock enforces one writer and is released on
process exit. Crash leftovers and pending metadata stay on disk and are counted
by verification; they are never automatically imported, overwritten or deleted.
An archive whose latest manifest says `running` lacks a clean stop. The logical
commit boundary is not an OS/storage power-loss guarantee; portable directory
fsync is unavailable on Windows.

The existing RawFollower recognizes file identity, truncation and first/last
witness changes. Every detected reset opens a new generation at byte zero and
preserves previous segments. A rotation marks a possible unread tail, including
the known unread backlog when observed. An EOF at an earlier poll does not
prove that nothing was appended immediately before rotation.

RawFollower's witnesses cannot detect every interior rewrite. Therefore an
active archive provides verified stored ranges, **not proof of a complete
unchanged source file**. Clean stop additionally hashes the entire captured
source prefix, checks the same file identity, size and stability, and requires
EOF. Interior rewrites fail this check. This is one final verification read,
not repeated whole-file copying on incremental polls.

Resume first verifies all committed segments/ranges/digests, then hashes the
whole current committed source prefix. Only a stable matching identity/prefix
can continue the same generation. Otherwise a new generation starts at zero
with a gap marker. The existing RawFramer is restored from committed bytes;
no Reducer/current authority is restored. The unobserved pause interval is
always explicit, even with matching bytes: unseen rotations cannot be excluded.

## Read-only verification and offline reuse

`verify-archive` never writes or repairs evidence. It reads the committed
manifest/segments, verifies exact lengths, SHA256, generation order and contiguous
nonoverlapping byte ranges, and reuses RawFramer for framing counts/errors and
partial-tail status. Missing/tampered segments or invalid references refuse
verification. Committed-prefix integrity, source verification at stop, framing
completeness, clean shutdown and possible rotation gaps are separate facts.
Partial/malformed captures cannot receive `complete_source_files_verified=true`.

For offline analysis, concatenate **only the verified segment files of one
generation in manifest order**, into a separately chosen private local file.
Never join different generations, pending files or uncommitted segments. The
result is the original captured byte prefix, readable by the existing replay
and historical-evaluation tools. Do not equate a captured prefix with a complete
source. Owner acceptance uses the two retained MP76 snapshots without changing
their hashes or claiming that they contain AutoTap responses.

## Resources and privacy

Default polls archive at most 1 MiB (`--max-poll-bytes`, maximum 16 MiB); reads
remain 64 KiB. Defaults reserve 8 MiB of disk space and cap committed bytes at
1 GiB, 16,384 segments, 1,024 generations and a 16 MiB manifest. Resource limits
fail explicitly and preserve earlier committed segments. Do not lower the
reserve to disguise disk-full failures. No retention deletion is implemented.
Checkpoint metadata grows within these limits. Resume and stop verification
are full-prefix reads outside the ordinary incremental hot path.

Archive failures disable that raw sink and are reported independently. The
Collector still processes the already-read records with its original Reducer;
an archive disk error is not reported as a game-state/log-read failure.

Raw bytes, private source path and file identities remain local. The verifier
prints only fixed summary fields, lengths, digests, generation/range/framing
counts and flags; it omits source paths, accounts, raw fields and payloads.
No upload, source modification, MTGA launch/input or P10 is performed. Keep the
entire archive private, including its manifest. This cannot recover MP76's
missing older bytes, prove payment completion, or establish real-time latency.
