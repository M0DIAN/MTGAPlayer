# MP49 — current authenticated public target-menu observation

The frozen real Generic2 Activate ActionsAvailableReq has 20 active rows,
six target-bearing Activate rows at positions **2,4,5,6,7,8** and
respective observed public Battlefield target counts **6,10,6,6,6,6**.

An opt-in read-only `observed_action_target_menus` report uses the
existing RawReducer and its current content-digest/own-seat verification.
It exposes strictly validated one-slot Activate **offered visible object IDs**
only after the existing public visibility projection. Invalid, private,
duplicate, unexpected or large nested target data withholds that entire
row without including unknown values. Partial framing, stale/consumed/
replaced requests or incorrect request digests withhold all old evidence.

```sh
mtgaplayer replay /private/Player.log --format player-log --observed-action-target-menus
mtgaplayer watch /private/Player.log --samples 5 --observed-action-target-menus
```

Observed offered IDs are NOT proven complete legal target domains.
No minimum/maximum selection, client encoding, complete payment,
rules legality, server acceptance, outcome/causality, freshness or
input is verified. No new parser, DecisionState/Event schema,
candidate proposal, native input or live game interaction is added;
the default replay/watch output is unchanged without the flag.
P10 remains NOT_RUN.

## MP51 — Request-time public source/ability pair consistency

The existing opt-in target-menu report is now
`mtgaplayer.action-target-menu-observation.v2`. It reuses
`semantic_activate.ability_observation` to join each targeted Activate
row's `uniqueAbilityId` and `abilityGrpId` with its **current,
own-visible, public Battlefield source's** published `uniqueAbilities`
list. This upgrades source/ability **identity evidence**, not target
legality or a future response link.

The retained real request's six target-bearing rows all have a unique
matching source-ability pair. The report counts
`verified_source_ability_menu_rows`,
`unverified_source_ability_menu_rows`, and
`contradicted_source_ability_rows_withheld` separately. A missing,
malformed or duplicate public ability observation keeps the offered
menu for research but marks its pairing **insufficient_evidence**;
an explicit group mismatch with the uniquely observed matching
ability **withholds the affected row** rather than exposing it as a
candidate. The pair is never reconstituted from a previous Full frame,
another source or a later client response.

Although these six source/ability **pairs** are now observed consistently,
the **targets are still not verified legal choices**. The snapshot
does not establish min/max, global restrictions, multiple stages,
complete payment, ability resolution, encoding, acceptance or a
parent Activate→SelectTargets/PayCosts/Search causal edge.
