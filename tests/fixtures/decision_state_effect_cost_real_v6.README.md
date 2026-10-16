# Real request-only payment projection

This State v6 fixture was produced with the existing RawFollower/RawReducer and
DecisionState assembler from the frozen third-phase records, cut exactly after
record603/GRE1 (PayCostsReq473/state338). No later GRE, client response622 or
successor was supplied to that producer. The original source SHA-256 is
4e888a7d29a9ac7f25c5d7aabc9517d5042c260d4065fa6c136e64ae45b616af.

Only scope identities were replaced: match, generation/game/state/request,
visible instance IDs and the public Stack zone ID use local aliases. The source
byte offset is null. Public card catalog IDs, own/player-visible object values,
request option order and every verified selection literal are unchanged. No raw
log, account metadata, prompt or hidden object identity is included. The portable
fixture does not reauthenticate the removed private source.

All16 supplied references satisfy only the observed single-object/nonrepeatable
membership constraints. The historical semantic v7 fixture independently records
the actual selection at offered position1. Its outcome cannot establish payment
legality or a result for any other candidate. Synthetic raw-envelope mutations
in test_effect_cost_choice.py exercise projection and lifecycle refusal paths;
they are not new real-game evidence.
