# Retained land-development current-request projections

`land_development_real.json` has LF SHA256
`918c78dc531dc44329d1726eb0bdcca76877f698e37ffaadf858cba78dc99dd0`.
It retains two original completed-poll current opportunities from the MP81
archive: aa-1, with three competing Play rows, and aa-10, with one Play at
original active position6 alongside complex actions. Full active/inactive
inventories, then-visible/own-visible objects, unique zone membership and
turn/priority facts are retained. Object/group/zone/facet/ability references
are consistently aliased; only the four explicitly reviewed public static
CardIds retain their literal values. Names, account payload and hidden faces
are omitted. Raw equivalence is false.

Authentication and Full bootstrap supplied by tests are explicitly synthetic;
they do not authenticate the original private log. Initial current state and
message contain no future response. The actual historical response is a
separate field and may only be read after freezing the research result.
Missing step and unknown Stack stay unknown, never filled from later records.

`land_static_reference_real.json` has LF SHA256
`fc04dbe48ac90d1003d2c21205de6dec2c6d00d43337c0f3bfbbf19a57352ae3`.
It contains the exact `prepare_mtga_land_reference(...).lookup(...)` output
for four real CardIds. The owner and independent reviewer each ran the actual
read-only production preparation against the existing official offline
database, pinned to its SHA256 and Data/GRP versions. Portable tests reconstruct
the same PreparedRulesIndex from these literal detached results; CI does not
claim to authenticate the original 259,883,008-byte SQLite file.

The static projection has its own native source format. It contains no invented
Scryfall UUID, Oracle ID, card text or `layout=normal`. All four IDs resolve
uniquely to static Land; only the current reviewed unlinked primary Basic Land
profile qualifies for this first policy. Empty explicit ability data does not
prove absence of intrinsic mana abilities. Neither static metadata nor an
engine-offered row proves current complete legality or server acceptance.

Synthetic mutations and reconstructed failing SQLite databases are explicitly
counterexamples. They are not additional real policy positives.
