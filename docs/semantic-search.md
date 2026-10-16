# Read-only Search observation, semantic samples v8

Use `export-semantic-samples INPUT --schema-version 8 --output NEW.json` to add
the observed own hidden-library Search shape to v7. The default remains v1.
Existing v1–v7 exports and replays retain their complete values. V8 delegates all
non-Search episodes together to v7, preserving older cross-episode target checks.
This does not add Search to DecisionState, legal choices or execution support.

The producer first uses the existing authenticated request digest, own-recipient
and continuity gate. The Search source must already appear in the current public
projection as an own-controlled Stack instance; an unknown card catalog identity
is allowed. Only the requested zone's Library/owner/Hidden labels and a zone alias
are staged. Neither library membership nor hidden gameObject card data is read
to identify an option.

Each itemsSought option has a request-scoped `search_item_ref` and
`visibility: request_identifier_only`. These references are distinct from public
`object_ref` values. Equal integers across namespaces do not imply equality,
visibility or card identity. The unfiltered itemsToSearch list is checked for
unique identifiers and itemsSought membership, then discarded; only its count is
exported. Prompt values and producer-private context are omitted.

The finite profile retains explicit maxFind=1, AllowCancel_No and
AllowFailToFind_Any literals. It observes one submitted item from the current
request domain. minFind and the meaning of fail-to-find remain unknown. Empty
selections fall outside this observed profile, without a legality conclusion.
Unknown shapes and fields reject the whole pair.

Only the first continuous Diff after submission is retained. A selected item may
map to a new public object through an explicit ObjectIdChanged annotation whose
affector matches the bound source. A separate matching ZoneTransfer must identify
the requested Library, the public Battlefield, category Put, the same source and
the same new object. Competing or malformed relevant mappings suppress the fact
claim. The hidden original does not need a visible card identity; no missing-value
equality or historical card lookup establishes identity.

Same-batch conflicts are checked against the explicit mapping's related raw
identifiers before ordered facts are interpreted, so an earlier foreign-source
transfer cannot escape the conflict check. If the original identifier also
remains in the current public projection, migration facts are withheld. These
checks consult public membership and annotation identifiers, never hidden faces.

The output separates offered options, client submission, first continuous state,
explicit mapping and public transfer facts. These facts do not establish complete
search legality, server acceptance, full rule effect or a causal relationship to
an earlier Activate. Full baselines, interruptions, next requests and missing
successors retain their existing bounded evidence statuses. Portable replay
validates the sanitized relationships and cannot reauthenticate private logs.
