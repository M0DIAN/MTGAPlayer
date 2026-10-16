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
