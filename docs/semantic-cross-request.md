# MP46: opt-in same-source Stack observation, not a causal trace

Use exactly **one** opt-in v9 portable semantic export, and request an extra
read-only report:

```sh
mtgaplayer export-semantic-samples /private/Player.log --schema-version 9 --max-samples 256 --output /private/semantic-v9.json
mtgaplayer replay-semantic-samples /private/semantic-v9.json --shared-stack-observation
```

The added `shared_stack_observation` report is **not** part of the default
replay and does not change the v9 file or previous contracts. The existing
v9 validator must succeed first. Inputs using any earlier schema are refused,
rather than borrowing unsupported payment or Search facts.

A candidate link needs **all** of the following within that single document:
an earlier v9 PayCosts selection with observed first-successor explicit
Sacrifice result and a visible Stack affector, a later v8-compatible Search
with explicit selected-item public transfer and an own Stack source, identical
match/game/seat scope and identical scoped object alias, ordered *observed*
state endpoints, and that public Stack alias uniquely present with own
owner/controller at four retained endpoints. Ambiguous many-to-one and
one-to-many candidate assignments are withheld. Unsupported or missing
observations remain absent links, not negative game-rule conclusions.

The link documents only a **candidate shared public Stack object across two
observed episodes**. Producer reference aliases are session-scoped within a
single original collection; numeric equality in separately curated JSON
files is never authority to join them. The two separately curated real
episodes were combined solely as an explicitly **synthetic test input**
to exercise the same-document join. This test does not reauthenticate the
private original log or establish the actual live linkage. Portable replay
cannot prove that the document was not manually spliced or forged.

In particular **the PayCosts request's source remains null**. Stack affector
identity must not be substituted for request-source, and identical Stack
aliases/order cannot prove parent Activate, payment completion, PayCosts
causing Search, triggered-effect resolution, correct hidden Search choice,
complete legality, server acceptance, or response/UI execution. Every such
claim remains false or unknown. No second reducer, raw parsing, card/rules
database, hidden objects, clock-based causality, network, native MTGA input,
current DecisionState change or strategy is added.

For authoritative cross-request linkage in a local real log, the user must
run a **fresh v9 export on the same immutable raw input** and independently
verify it using original record/generation/request identities and continuity.
This report is research evidence only and explicitly returns
`source_auth_revalidated=false`.
