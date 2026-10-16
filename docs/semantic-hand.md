# Narrow hand-choice evidence (v6)

Opt in with `export-semantic-samples --schema-version 6`. V6 retains the complete
v4 Cast, Combat, Targets and Resolution-SelectN contract and adds only the
observed London/AcceptHand and TurnBased/Discard single-card shapes. V1–v5 stay
selectable and unchanged; v5 remains the separate Activate profile.

RawFollower/RawReducer, the authenticated current request and established exact
response gate remain the source authorities. The new module projects literal
fields and validates portable evidence; it creates no second state machine or
action ledger and makes no request actionable.

London exposes `AcceptHand` submission and, when observed, preservation of the
first successor's **visible own-hand reference set**. That fact does not assert
unchanged card-catalog identity or complete hand visibility. The prompt's 7 is
an uninterpreted numeric literal. Choice domain, mulligan count, remaining
attempts and bottom-card count stay unknown.

Discard validates explicit `minSel=maxSel=1`, nonrepeatable offered membership,
and that offered references join to the current visible own hand. Missing
allowCancel, sourceId, unfilteredIds and weight bounds stay null; Resolution
defaults are not substituted. Positive discard-result evidence needs the
selected reference's explicit ObjectIdChanged, disappearance of its old visible
reference, Discard Hand→Graveyard annotation and a known matching visible
`card_id`. Two unknown card IDs do not establish identity. Merely seeing hand
count 8→7 establishes neither the selected discard nor a hand-limit rule.

Both new profiles stop at the first continuous Diff. Later draws or discards
are outside that episode. Missing results remain insufficient evidence. All
complete-legality and global server-acceptance flags remain false; responses
remain `client_submission_only`.

Legacy v4 episodes are replayed together, preserving their original aliases and
cross-episode target-origin/selection links. V6 may allocate more aliases than
v4 because it retains additional episodes; unchanged v1–v5 outputs remain the
regression baseline. The [curated real fixture](../tests/fixtures/semantic_hand_real_v6.README.md)
documents its artifact-scoped counts separately from full producer totals.
