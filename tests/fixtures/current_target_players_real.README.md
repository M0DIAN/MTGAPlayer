# MP84 current player-target projections

`current_target_players_real.json` contains13 owner-authenticated first-current
request/public-state field projections from the MP81 archive, source SHA256
`1d75cd1b65ac868da1e9e0025032c7380317fcbf8669016a00fcb536e44a73ac`
(3,225,997 bytes). LF-normalized fixture SHA256:
`04c8d04c64530ef4220bb2cee60f0d64446a41602bbed1d7608b11ba2a0b574c`.

Per-case request/state/object/group/zone/prompt identifiers are aliases. Self seat
is normalized to1 with the same permutation applied to player references. Public
source/target object type and visibility, target order, slot, operation, counts
and allowCancel/allowUndo presence are retained. Prompt number value/name are
redacted without interpreting their meaning. Unrelated fields, hidden objects,
account/authentication data, local paths and all later responses are omitted.
Minimal player records retain only their actual systemSeatNumber relationship.

These are field projections, not raw-equivalent logs. Tests wrap them in clearly
synthetic authentication/Full state and may add an empty public Battlefield.
Neither those wrappers nor mutations are additional real positive evidence.
Only the owner certified the original archive bytes; independent review uses
these public projections and the safe version/owner receipts.

Actual finite results:24 player memberships in13 requests, two additional known
public Battlefield members,11 complete local Select domains and24 local proposals.
Two Unselect-only requests remain selected literals with zero Select domains or
proposals. Full legality, response encoding, execution and tactical value remain
unknown. The reviewed source build is `2026.64.0.14517.1329972`; its header literal
in tests models the accepted shape, without authenticating a binary or private log.
