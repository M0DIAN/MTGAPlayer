# Real Equip first-child continuation, portable State13

Eight snapshots retain the real request lifecycle: `before_parent`1402,
`parent_consumed`1421, `first_child`1422, `first_child_consumed`1424,
`revised_child`1425, `revised_child_consumed`1426, `later_result`1428 and
`final`1433. Only `first_child` has continuation context. The others exercise
revocation and separation, without supplying its target constraints.

The owner authenticated the frozen 7,718,945-byte original, SHA256
`6bab453be2830750af3983a70ce4843f747252ef950e1e4ced628785d7cfac07`.
The parent-only 7,664,967-byte prefix SHA256 is
`e8a8732c67e8bd4a9c019ec042aae7d067efc54b7797576b8ce53b4d1ffd2635`.
Its exact private request-before snapshot was frozen before successor parsing.
The genuine first-child prefix ends at1422:m1, 7,682,758 bytes, SHA256
`f532ba434c3d82fb748ef91f3764cc1419d9a3f78595ed73aaee7020f399f239`.
Auth1136, room1141, Full1143:m1 and281 accepted states precede parent1402:m1;
the child's Diff is the 282nd accepted state message. Actual response1421 uniquely selects
complete Activate row6, consumes the parent, then public Ability1422:m0 and
independently authenticated own SelectTargets1422:m1 establish the association.
No future1424+ response/result certifies the first child's choices.

The first child alone explicitly supplies min/max1/1, no selectedTargets,
one Select member, Abort cancellation and typed undo. Existing v5 target
validation already covers its membership/count. The new capability is only
current continuation context, with a consumed historical parent and a separate
child binding/ref/lease. On1424 it is discarded. Revised1425 is a different
request with an Unselect member, independently handled by the existing selected
literal checker; it receives no MP62 first-child context. Submit1426 consumes it.

Object/card/ability/unique/facet/request/state/zone/slot/mana/prompt/prompt-Number/
targeting-group identifiers use separate stable scoped alias namespaces.
Targeting group is independent of the top-level ability group. The prompt's
Number remains typed signed int32 and uninterpreted; it supplies no target count.
Prompts, optional-field presence, highlights, list ordering, count literals,
enums, Booleans and nulls retain their observed relationships. Known visible
catalog references become card aliases, while unknown identities stay null.
Match/generation/game are normalized. Card knowledge, offsets and timestamps
are null. Accounts, hidden objects, raw bytes, private aliases and client files
are withheld.

These are portable observations, not raw authentication. Independent reviewers
inspect the public source/fixture and whitelisted safe receipts/methods; they do
not authenticate withheld original bytes. Synthetic bootstrap messages,
transport clocks, mutations and negative cases in tests are explicitly synthetic.
See [the evidence and contract](../../docs/current-choice-continuation.md).

Canonical UTF-8/LF JSON:444,810 bytes; SHA256
`122a5382b936e404309d158e6098b32ab3bb04cfc1727cb294666846c89ed109`.
Windows checkout CRLF may differ. This fixture does not prove full legality,
payability, effect causation, response encoding, acceptance or game input.
`input_sent=false`; P10 remains NOT_RUN.
