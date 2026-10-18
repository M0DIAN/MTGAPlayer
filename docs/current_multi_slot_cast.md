# Current multi-slot Cast observations (MP67)

This is a current-request local observation, not a target-set proposal. The
existing single-slot Cast/Activate validators and Candidate2–6 are unchanged.
The existing ActionFrontier/ChoiceGraph retains position, index and counts but
cannot distinguish a changed member ID: its old targets groups contain no
member references. `semantic_targets.action_targets` already decodes the
literal, so MP67 reuses it rather than adding a parser or rules engine.

## Retained real evidence gate

Open only records 1–103 of `tests/fixtures/player_log_single_target.jsonl` for
the positive proof. LF prefix: 60,858 bytes; SHA256
`1616b632532286f5437c4675c814a25a6a902b40e0de67c19308b37cafaf0c9d`.
Authentication, one Full and 99 accepted Diff states establish state100/seat2,
current ActionsAvailable request10100, eight active and two inactive actions.
This retained scrubbed source supports protocol relationships, not independent
reauthentication of the removed original private bytes.

Active position2 is Cast: integer source1245/group86855/facet284, boolean
shouldStop=true, manaCost `[{'color':['ManaColor_Red'],'count':1}]` (count integer).
The ordered slots are integer targetIdx2→[1243], targetIdx1→[1243]. Both member
references join the same current public Battlefield object. Source1245 joins
the current own Hand physical object; current card_id is null for source and
target. Group86855 is an action literal, not a verified card catalog/rules ID.
No autoTapSolution is present. Payment remains unknown, including alternative
routes, additional costs and actual payability. No free/failed-payment claim.

Freeze these facts before opening104. The later actual response selects
position3, not position2. Its Stack/SelectTargets continuation establishes
neither position2's successor nor its target combination. The same object
appearing in two slots does not prove that it may be selected in both.

## Additive opt-in contract

`replay(..., current_multi_slot_cast=True)`, `watch(...)` and
`watch_decision_events(...)` expose `--current-multi-slot-cast` for player-log
State5–15. Default false preserves complete old returns. No new State/Event
version is introduced. The extensible legacy ChoiceGraph targets constraint
adds only `current_multi_slot_cast`, versioned
`mtgaplayer.current-multi-slot-cast.v1`. Its old quantity/groups are unchanged.

The finite projection accepts current own-Hand Cast literals with manaCost,
shouldStop and 2–8 distinct positive target indices, each with 1–64 distinct
provided current public Battlefield members. Order is literal order; indices
are not sorted or interchanged. Unsupported fields, duplicate indices, hidden
or missing members and an observed conflicting source group withhold the new
observation. Cross-slot overlap is retained, not interpreted. No Cartesian
product is constructed. Missing source card identity stays unknown.

The nested contract carries the full bounded literal, existing action_key and
ordered per-slot refs, with minimum/maximum/selected_count null. RawReducer
attests visibility using accepted current state. Consumer validates the fixed
shape, scope, denials, current binding, original position/source/flags, visible
objects and old Graph groups/frontier shapes. These transport checks do not
reauthenticate raw source bytes. Missing extensions retain legacy behavior.

MP65 annotates the existing engine_action observation at its original position,
without constructing an extra option, proposal or reviewed complete action.
Its enclosing request binding and snapshot ref remain authoritative; the
existing Consumer lease and before/after currentness gates revoke cached data
on consumption/replacement/reset/partial/stopping/expiry. MP66 remains abstain:
two singleton slots do not imply a unique complete legal action. All execution,
complete-legality, combination/domain, response and payment proof flags remain
false; future selection constraints remain unknown.

## Verification boundary

Direct tests freeze103 before future lifecycle checks, preserve swapped literal
slot order on a fresh first request, reject conflicting retransmissions, and
exercise duplicate/missing slots, indices, member/source visibility, binding,
payment and authority inventions, consumption and all current revocations.
The actual position3 Cast chain and independent Equip chain remain regressions.
Formal existing schemas, selected complete old-interface comparisons, full
Python3.11 tests, Windows doctor, independent exact-candidate review and real
Linux/Windows CI are delivery gates, recorded with actual identities on the PR.

Only the directly affected controlled incremental path is timed with opt-in
off/on; projection uses the existing visible state, one reducer and no new
log read. This is offline timing, not live MTGA end-to-end proof. No online
service, client encoding, input adapter, new dependency or complete legality
solver is added. input_sent=false; P10=NOT_RUN.
