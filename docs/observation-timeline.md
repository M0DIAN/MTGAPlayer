# Frozen observation timelines

`mtgaplayer.observation_timeline` reads an existing local collector snapshot.
It uses RawReducer and the established authenticated current-request, response
consumption and semantic identity gates. It creates no collector, game sender,
GRE parser or action classifier.

```python
from mtgaplayer.observation_timeline import analyze_snapshot

result = analyze_snapshot(snapshot_directory, semantic_source=stable_original_log)
```

The smaller `analyze_timeline(records, markers, poll_journal=...)` API accepts
the collector's already decoded wrapper rows. It does not alter its inputs.
The snapshot API checks the three input JSONL hashes against the frozen manifest.
The original log is optional. A bounded read verifies its metadata before and
after copying at most 64 MiB into a private temporary file. RawFollower and the
existing semantic exporter both read that same copy; its bytes/identity/metadata
are rechecked after export. Its entry values and order must equal the wrapper.
A mismatch withholds semantic traces. The original evidence is never rewritten.
Temporary files are removed after analysis; the default workspace is the ignored
`artifacts/local-observation-timeline-work` in this checkout. Callers may select
another private ignored workspace with `semantic_work_directory`; the command
uses the output directory. Source integrity failures never become a successful
marker association.

For an existing private snapshot, save a new local report:

```powershell
python -m mtgaplayer.observation_timeline <snapshot-directory> --semantic-source <stable-original-log> --output artifacts/local-live-phase2/task2/timeline.json
```

`protocol_pairs` records exact request/response evidence separately from marker
matching. Each pair retains generation, local scope/request/state binding,
request and response record references, the request's GRE batch index, phase
context and the existing offered-choice identity verdict. Its confirmation is
`client_submission_only`. A continuous accepted successor is a separate state
observation; it does not itself prove the selected action's rule effect.

When a matching stable original source is supplied, the existing v4 semantic
exporter and replay attach their trace and Cast submission/stack/resolution
findings. The module reuses the producer's request/response projectors to map
supported samples in verified source order; count or type disagreement withholds
the join. It does not implement another Cast trace or infer resolution from a
Cast response. Missing targets stay `missing`, and neither missing targets nor
an empty literal establishes a targetless spell's complete rules.

`marker_associations` has four outcomes:

| Classification | Meaning |
|---|---|
| `protocol_supported_unique` | One compatible protocol observation has a unique offered identity. |
| `multiple_candidates` | Several observations remain, or one request's offered identity is ambiguous. |
| `temporal_only` | A protocol observation overlaps the marker window, but its compatible action identity is unproven. |
| `unreliable` | Markers, source integrity or timing are unreliable, or no temporal protocol observation exists. |

Every outcome keeps `marker_action_causality_verified=false`. The unique result
describes a candidate observation, not proof that the user's marked action caused
that submission. A targeted or targetless Cast marker only matches the base Cast
family; its subtype remains unverified unless separate evidence establishes it.
Combat submissions currently retain their exact protocol edge but do not acquire
an offered-action identity from this module.

Matching uses local monotonic poll detection intervals, including boundary
overlap. Those intervals describe when the collector found bytes, not guaranteed
action-occurrence times. Missing polls cannot silently expand a reliable window,
and the whole marker interval must be covered by frozen poll observations;
partial/null/corrupt input, later resets, inconsistent generation/clock metadata,
continuity errors and malformed or unpaired markers produce `unreliable`.
Unknown marker types become `None` and `unsupported_marker_type`; free text is
not echoed into the report.
Source log timestamp units and clock offset remain unknown. The report never
calculates network delay or chooses the nearest candidate.

The first real frozen experiment remains 13 strict protocol pairs and eight
marker groups: seven unique candidate groups and one group containing all three
Pass responses, records 208, 210 and 212. Those Pass requests occur in Main1,
BeginCombat and Main2. Their phases distinguish the observations; the marker has
no phase constraint, so none is removed. Cast evidence and marker causality remain
separate. This change makes an analysis contract explicit; it is not evidence of
a newly discovered real parser defect.

Reports contain local request/state bindings and record references but no raw
payloads, account/match identities, hidden objects or user notes. Keep the original
logs, snapshots and detailed local analyses in ignored experiment directories.
The checked-in regression cases identify their synthetic action bodies and use
the existing sanitized state fixtures. They do not establish a new live run.
