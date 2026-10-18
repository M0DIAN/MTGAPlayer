# Current Search request evidence (MP78)

An explicit owner-thread side observation reuses Semantic v8's finite request
projector, without adding Search to default MP65 choices or MP66 policy:

```python
options = consumer.current_decision_options(
    current_search_context=(same_reducer, accepted_search_message))
evidence = options['current_search_evidence']
```

`mtgaplayer.current-search-evidence.v1` reports the current request binding,
snapshot ref, public own Stack source, own Hidden Library labels, unfiltered
item count, offered positions, request-scoped search-item aliases, explicit
maxFind and unknown minFind/fail-to-find meaning. Output is bounded by the
existing options limit (maximum64); total offered count and truncation are
separate. Each returned member carries its request/ref and the explicit
`request_scoped_search_item_not_object_or_card` namespace. Equal alias integers
across requests or domains do not establish object/card identity.

`current_local_constraints_verified` means only the offered-membership,
unique-identifier and explicit upper-count slice. Members are not full search
proposals. `complete_proposals=[]` and `complete_proposal_count=null` do not mean
zero legal choices. Minimum count, empty/fail-to-find choices, complete domain,
hidden identities, rule legality and strategic value remain unknown. All input,
execution, full-legality, response-encoding and server-acceptance flags stay
false. A single offered item still cannot acquire a research preference.

The same accepted raw digest and typed binding must match the existing Consumer
snapshot before and after projection. Public visible state, source identity,
requested-zone labels, request continuity/ref/lease and execution isolation are
rechecked. Source fingerprinting precedes projection so an in-flight Ability
group/parent change cannot escape merely because card_id is unknown. Private
sticky Search interruption witnesses share the existing single RawReducer;
they never appear in default documents. Cancel/Undo, unsupported/mixed/broadcast
input, Full/recovery, gaps, resets, consumption and replacement cannot revive
an old observation. Partial/expired/stopped Consumer views return no members.

The optional offline aggregate uses the existing one-pipeline history evaluator:

```text
mtgaplayer evaluate-shadow-history <private-source> --current-search-evidence
```

Only first accepted authenticated requests enter the request denominator.
Offered/returned memberships and strictly consumed SearchResp submissions have
their own units. The original default historical report and policy stay intact.
One bounded frozen comparison context retains only this request's returned
members; later response membership is checked with the existing v8 decoder
after strict type/header/consumption pairing. A selection outside the retained
bounded member slice, or an unsupported/incomplete response, stays unreviewed,
not a rule violation. Later public transfers never
fill earlier hidden identity or confer current authority. Nothing is encoded
or sent to MTGA.

Real owner acceptance uses two current requests from the same frozen snapshot:
records287/441 have47/45 unfiltered items and8/7 offered members; responses294/452
pair and consume. MP77 archives are the same bytes and are deduplicated. New
sources remain separate from the original164-request history. The older v8
41/4 portable episode supports historical structural regression only; its
missing raw source has not been reauthenticated. See the fixture README for
provenance and the distinction between real projections and synthetic wrappers.

The module never reads hidden card faces, looks up search IDs as game objects,
queries card rules online, builds a second state/reducer, or enumerates search
combinations. Timing is the local incremental side projection on frozen
historical requests; it is not proof of a live three-second MTGA loop.
