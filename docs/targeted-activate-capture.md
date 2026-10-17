# MP52: owner-local targeted Activate recapture

On 2026-10-17 (Asia/Tokyo), the owner manually used **钢铁侠战甲 / Equip 2**.
This new capture supplies the real interaction missing from the
[initial retained-fixture audit](targeted-activate-evidence.md). It is a
read-only evidence delivery; production linkage is not implemented by this
documentation change. Card naming comes from the owner and supplied card image,
not an external card database or recovered hidden identity.

## Source and continuity

The frozen original-byte Player.log prefix contains **7,718,945 bytes**, SHA256
`6bab453be2830750af3983a70ce4843f747252ef950e1e4ced628785d7cfac07`.
It frames into **1,433 records**, with zero framing errors and no partial frame.
Two reads of the same open source prefix agreed; offline reads also retained
the same metadata and hash. No Full state or protocol message was manufactured.
The capture/replay producer was `27b2f3ff091ab3de9f534ce9a7e745aa8c5a4cca`.

Record numbers below are original one-based framing ordinals; message positions
are zero-based. They are locations, **not GRE identifiers**. The new game's
authentication is at record1136, room scope at1141 and real Full at1143/message1.
Actual records1136–1433 were separately replayed in order: 298 records,
286 accepted state events and zero reducer continuity-error callbacks.
This excludes the previous game's missing predecessor after Undo; that earlier
gap was never bridged or used as a fallback. The original-byte source retains
both games, so whole-file continuity must not be inferred from the new episode.

## Observed chain

| Original location | Authenticated observation |
| --- | --- |
| 1402/message1 → response1421 | Current own ActionsAvailable request and consumed PerformAction response. The chosen nonempty-target Activate has exactly one full-row match and one complete identity match among 17 offered rows. Its current own public Battlefield source publishes the selected unique-ability/group pair. |
| 1422/message0 | One explicitly created public Stack Ability has the selected Battlefield source as parent and the selected ability group. This is a parent/group observation; the source's unique-ability identifier is not supplied by the continuation. |
| 1422/message1 → response1424 | SelectTargets source is that unique created Stack Ability. Top-level ability group matches the Activate; targeting-ability group remains a separate namespace. The actual single Select matches the current target slot and offered entry. All target endpoints are strictly public Battlefield objects. |
| 1425/message1 → submit1426 | Re-presented target request retains the binding and explicitly presents the same single selected Unselect entry. The authenticated header-only SubmitTargets consumes this current request. Missing selected count in the earlier request remains unknown, not zero. |
| 1427/message0 | PlayerSubmittedTargets explicitly names the same public Stack Ability. Two ManaPaid observations concern the reviewed payment relations; they are not a complete-cost certificate. |
| 1428/message0 | The same created Ability has explicit ResolutionStart, ResolutionComplete and AbilityInstanceDeleted observations. One strict header-only AttachmentCreated annotation has the actual Battlefield Activate source as affector and the final submitted target as its sole affected object. Both endpoints are currently public Battlefield objects. The target was observed as an own-controlled Creature during the post-submit trace. |
| 1428/message1 | The next ActionsAvailable request is retained. The result probe follows the explicitly bound Ability through its resolution/deletion rather than treating a priority window as the end of the evidence. |

The actual target selection, final submission and explicit public result are
therefore retained in one continuous new-game episode. This does **not** verify
an old-host → new-host attachment transition: the probed attachment-like object
fields were absent. The annotation's literal endpoints are established; an
undocumented direction, rules effect causation, complete legality, server
acceptance and response-encoding authority are not inferred.

## Replay and delivery limits

Two ignored offline probes reuse one RawFollower/RawReducer, the existing
current-request/digest and consumed-response gates, target projectors and
Activate public-Ability facts. They emit only fixed labels, counts, booleans
and source locations. The result probe requires raw Visibility_Public and a
public Battlefield zone; visibility-filtered membership alone is insufficient.
The [machine-readable receipt](targeted-activate-capture.json) pins their hashes
and the observed/unsupported boundaries. A separate agent reviewed their source
and safe output; it did not read the private original or authenticate its bytes.
The source-copy procedure, authentication/room/Full locations and export counts
are author-recorded metadata, outside that independent safe-output review.

The existing v9 exporter returned `invalid_semantic_sample` on the complete
two-game source. Exporting actual same-source records1136–1433 succeeded and
portable replay passed: 28 matched pairs, 10 exported, 18 unsupported, zero
limit omissions. The selected Activate parent pair is **not retained** in that
export; whole-inventory projection is unsupported. The successful derivative
therefore cannot replace the raw parent evidence or be described as a complete
portable Activate chain. This export boundary does not invalidate the separately
authenticated original episode. No fields were edited to make it pass.

Raw originals, authentication/account values, hidden identities, prompts,
screenshots and private derivatives remain local and ignored. No public raw
fixture or production semantic change is included yet. The next engineering
step is an allowlisted, scoped portable fixture and a minimal opt-in linkage
with controls discriminating its actual rule. The existing Cast linker cannot
be relabelled as Activate: its Card resolution check does not authenticate an
Ability with a null card ID. Default behavior and schema versions are unchanged.
Input was never sent; **P10 remains NOT_RUN**.
