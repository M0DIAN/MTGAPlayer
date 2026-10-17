# Real current selected target literal before Submit

The owner-local frozen MP52 original has 7,718,945 bytes, SHA256
`6bab453be2830750af3983a70ce4843f747252ef950e1e4ced628785d7cfac07`,
1,433 complete framed records, zero framing errors/partial tail. The fixture
uses the existing standard State5 producer on the original-byte prefix ending
at record1425/GRE message1, before actual Submit1426. Ordinals are one-based;
GRE message positions are zero-based. Prefix: 7,689,086 bytes, SHA256
`a0d1fe1d97662714bc6aa60cb77a9418769881962595fae302d0069e5299b44c`.
Auth1136, room1141 and genuine Full1143/message1 authenticate the same game.
Its283 accepted state events through1425 have zero continuity errors. The prior
game's post-Undo gap is never bridged.

`before_submit` already contains the accepted target profile's explicit
min/max/selected count1, one Unselect public BF reference and its public Stack
Ability source. `proposal` uses only this prefix and binds source, ability group,
separate targeting-ability group, target slot/player and the exact selected set.
It requests the new explicit current-selected check, not a new Select domain.
`after_submit` is the same producer after actual header-only Submit1426; its
current request is null. Later submission/result snapshots are not copied into
this fixture. Their refusal of the old proposal is separately checked on the
original-byte Consumer stream, without filling any pre-Submit field.

Match/generation/game use fixed fixture scope values only after strict type/value
scope equality across the original pre/post snapshots. Object, card, request,
state, Stack-zone, slot, ability-group and targeting-ability-group IDs use separate
consistent fixture-local aliases. Quantity1 remains literal. Byte offset and
source timestamp are null. No raw logs, credentials/accounts/names, hidden
identities, card catalog identities, prompt/highlight values, screenshots or
private alias maps are published. Other player-visible observations remain;
own-hand structural references/card groups are aliased and imply no rules lookup.
This is a sanitized State projection, not portable raw-source authentication.

Canonical LF:22,839 bytes, SHA256
`64488e9b3f67014322757ccb975be2143a29bd56e86a55c6528625e50b73dfaa`.
Owner-local regeneration compares the entire parsed fixture. Synthetic raw
controls in the tests explicitly change an older Cast source to an Ability for
projection/lifecycle falsification; they are not additional real Activate captures.
The real positive is this pre-Submit State and the separately verified original.

The check proves only the currently observed one-selected literal's consistency.
Selection-domain/quantity-rule completeness, full target/action/payment legality,
response encoding, server acceptance, input readiness and latency remain
unverified. Source group references bind this request; they do not independently
establish raw parent/group continuation. No MTGA input was sent; P10 NOT_RUN.
See [the original-byte method and bounds](../../docs/current-selected-target-set.md).
