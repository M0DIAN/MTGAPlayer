# MP78 retained current Search request projections

These two request-only projections come from the frozen MP76 `new_player`
snapshot (3,882,223 bytes, SHA256
`f4881c042ff40c8685a9f116a90a329e6a19f8533775ce65183842715bfbbc61`).
MP77's verified four raw segments reproduce exactly the same bytes; this is
one source, not an additional cohort.

Owner authentication used the existing production history pipeline and froze
each request at its first accepted observation, before any later response:

| Request record | itemsToSearch count | offered items | response record |
| --- | ---: | ---: | --- |
| 287 | 47 | 8 | 294 |
| 441 | 45 | 7 | 452 |

Both requests satisfy the unchanged Semantic v8 finite profile: own visible
public Stack Ability, own Hidden Library metadata, unique typed item lists and
offered subset, explicit maxFind1, AllowFailToFind_Any and AllowCancel_No. Source
identity/unique public zone and typed continuity were checked separately. The
two later SearchResp envelopes strictly pair to consumed requests and select
offered members; that historical observation does not participate in these
request projections. No successor state or hidden card identity is retained.

`request_projection` is the actual existing v8 projector result at that freeze.
Public object, zone and request-item aliases use separate namespaces; only the
minimal visible source labels are retained. The unfiltered list is count-only.
Prompts, original identifiers, authentication, accounts, hidden faces, original
file paths and raw GRE envelopes are omitted. minFind and fail-to-find meaning
remain null. This portable artifact does **not** authenticate the original log.

`test_current_search.rows_for` constructs explicitly synthetic auth/Full/GRE
wrappers and identifier domains around these retained counts. They exercise
the current API plumbing and negative mutations; they are **not** real current
GRE authentication. Actual raw current/ref/lease and response-consumption
acceptance is owner-local, with bounded safe receipts. Independent reviewers
inspect this public artifact and safe receipts, not private raw bytes.

The older v8 fixture (41/4, original5,625,878-byte log) remains a separate
historical artifact. Its missing original is not reauthenticated by this data.
The new34-request cohort is not added to the old164 denominator or2/164 policy
baseline. The second frozen MP76 source contains0 authenticated own requests.
