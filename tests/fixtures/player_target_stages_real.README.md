# Retained player target stage projections

`player_target_stages_real.json` contains 11 genuine scrubbed continuation
projections from the same MP81 archive as `current_target_players_real.json`.
Its LF-normalized SHA256 is
`3fb36caefd5ea18ccfa4a0ceb4036296f819241df26d4a7c060e65bbc0edc2a0`.
Each `initial_mp84_case` references an existing independently frozen MP84 Select
projection. Two episodes reuse the corresponding genuine Unselect request
projection after an actual typed Diff, then the actual terminal envelope.
Nine episodes deliberately contain no independently reviewed revision/terminal.
Ten updates select a player; one selects an existing public Battlefield object.

The owner checked raw SHA256, MP77 continuity, original completed-poll offsets,
version evidence, exact response consumption, one Diff, stable source/role
witnesses and absence of involved migration annotations. The safe per-case
attestations are in `docs/evidence/mp85-player-target-owner.json`. These owner
claims cannot be independently authenticated from these projections alone.

Request/state/source/group/zone/prompt aliases and a consistent self-seat
permutation reuse MP84's scheme. Revised state aliases become 11 after initial
10. Unrelated telemetry, actions, timers, annotations and hidden objects are
omitted; raw equivalence is expressly false. Positive Diff projections preserve
the actual type, predecessor/successor types, update field when present, and
relevant message ordering. The owner separately attests no source/selected
entity migration in each original Diff. Omitting annotations from this portable
projection cannot itself prove that fact about the original bytes.

Test authentication and Full bootstrap are synthetic transport wrappers, not
original MTGA authentication. Explicit freezes model the original completed-poll
boundaries, not request-accepted callbacks. All modified payloads, reordered
stages, collision/visibility changes and migration annotations in counterproofs
are synthetic negatives. No synthetic response is presented as a real positive.

These samples prove finite local historical relationships only. They do not
establish parent Cast/Activate causality, server acceptance, complete legality,
historical wall-clock lease timing or strategy correctness. No private raw log
or installed game binary is required for portable tests.
