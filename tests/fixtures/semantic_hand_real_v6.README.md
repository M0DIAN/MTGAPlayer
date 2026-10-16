# Curated real hand-choice episodes

`semantic_hand_real_v6.json` retains two unchanged episodes from the v6 producer's
real local 2026-10-16 input: London `AcceptHand` and TurnBased single-card Discard.
The full producer read 278 framed records and produced 13 matched / 13 exported /
0 unsupported episodes. The two retained episodes were full-output indices 0 and
9. Their payloads, visible snapshots, traces and provenance flags are unchanged.

The fixture container counts are **artifact scoped**: 2 matched / 2 exported /
0 omissions / 0 unsupported. They describe this curated portable artifact, not
the original producer's totals. `source.framed_records=278` remains the original
source fact. Excluded legacy episodes are neither unsupported nor sample-limit
omissions. A private ignored sidecar binds the original source/full output/
fixture SHA-256 values and selected episode indices.

`retained_scrubbed_real` is an operator-supplied origin label. The original
producer verified the private request/response pair; portable replay cannot
reauthenticate the removed private source. No authentication flags were invented
or changed during curation. The fixture contains namespace aliases and the
established visible projection, without account/match IDs, raw payloads, prompt
identifiers, free-form prompt names, hidden card identities or user notes.
