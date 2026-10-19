# Retained parent-to-target source projection

`parent_player_target_lineage_real.json` is one aliased projection from the
authenticated MP81 archive. Its LF SHA256 is
`2266882033520e0df59a3da46edacfe199c03050df73f779d04af1f4c112abdb`.
Raw equivalence is false. Private authentication belongs to the owner receipt;
test authentication and Full bootstrap are explicitly synthetic.

The initial projection retains all 25 then-visible/own-visible entities and
their actual zone identities, plus the complete parent inventory (11 active,
four inactive). Per-entity/group/zone/state/request aliases preserve equality
and ordering. The source Card aliases 300→301; the later Ability alias is100.
The parent selected Cast remains position1. Card and Ability groups retain
separate actual relationships. The three intervening UI records retain only
their type and actual transport wrapper shape; unrelated UI payload, effects,
timers and hidden faces are omitted. No new positive is synthesized.

Four genuine typed Diffs preserve the source edges: ID change/CastSpell into
Stack, a stable observation, Resolve to Battlefield plus explicit public
Pending Ability creation, and raw same-Ability Pending→Stack location updates.
The last edge has no ZoneTransfer annotation. Other public Pending Ability
object rows are retained; the owner separately attests uniqueness of the
matching source/Ability group and absence of contradictory identity events.

`poll_batches` preserves the two actual subsequent completed-poll groups.
The first contains the Cast response and two UI/two GRE records through
SelectN. The second contains one UI record, its actual consumed SelectN response
and the final GRE record with Diff/current SelectTargets. The seven
`continuation_records` provide the same ordered projection for direct
prepare/apply/after-apply tests. Actual client/GRE transport fields are retained
with aliased request/transaction/timestamp values. Transport metadata never
establishes request identity. First freeze occurs after
`parent_initial.message`; child freeze occurs after the second complete batch,
before `target_update`. Request-accepted callbacks are not freeze substitutes.

SelectN references deliberately use a separate request-scoped alias namespace.
Its actual `[0] + OrderArbitraryOnce` response is retained as a dedicated opaque
construction, never as an offered member, object identity, order or legal choice.
The source lineage uses only direct Card/Ability identities and accepted state
changes. Matching fixed public client construction does not prove that runtime
branch executed.

The child is MP84's mixed domain: two players plus one public Battlefield
object. The genuine MP85 update selects that object. There is no actual player
choice or completed terminal stage in this positive. Other MP62/64 positives
remain regression evidence and are not counted as MP86 additions. Every test
mutation and clock is synthetic and must be described as a counterexample.
