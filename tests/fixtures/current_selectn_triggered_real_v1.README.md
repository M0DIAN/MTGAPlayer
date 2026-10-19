# MP82 retained TriggeredAbility/Stacking SelectN observations

This fixture retains five request-only projections from the MP81 single-game
source. Each request was frozen at its first current opportunity after a
complete poll, before its later response. These are five of that source's seven
current SelectN opportunities; they remain separate from older request cohorts.

Source metadata retained in the JSON:

- Original source bytes: 3,225,997.
- Original source SHA256:
  `1d75cd1b65ac868da1e9e0025032c7380317fcbf8669016a00fcb536e44a73ac`.
- This JSON fixture canonical Git/LF bytes: 5,003.
- This JSON fixture canonical Git/LF SHA256, checked against the actual Git blob:
  `765b40422eb01deb988ff5cab5bf460b10221e16f56fca14fdaef4cc73668f8d`.
- The owner's Windows CRLF checkout is 5,178 bytes, SHA256
  `890859a9f47745a92dd82887ea5772f9ad924a4314bfe9a654f7f7b74df84cf9`;
  normalizing only CRLF to LF reproduces the canonical fixture above.

| Retained case | Offered references | Explicit minSel | Explicit maxSel |
| --- | ---: | ---: | ---: |
| selectn-1 | 2 | 1 | 2 |
| selectn-3 | 3 | 1 | 3 |
| selectn-4 | 3 | 1 | 3 |
| selectn-6 | 6 | 1 | 6 |
| selectn-7 | 10 | 1 | 10 |

All five retain `SelectionContext_TriggeredAbility`, `OptionContext_Stacking`,
`IdType_InstanceId`, `SelectionListType_Dynamic` and
`SelectionValidationType_NonRepeatable`. The prompt contains only `promptId`.
Source, cancellation, weights and unfiltered-domain fields were not supplied;
their meanings remain unknown. The explicit count bounds are observed literals,
not a proof that every count or combination within them is legal.

All request/member numbers, seat, message ID, state ID and prompt ID in the
fixture are aliases. Their numeric equality across samples or namespaces does
not establish identity. The 24 offered memberships are absent from their
respective current visible projections. They are not 24 identified cards,
abilities or other public objects. The current evidence API emits request-local
position aliases with an explicit namespace and binding/ref; object, card and
zone identities stay null. Original member references and hidden identities are
not recovered through a raw-object or catalog lookup.

`raw_equivalent=false` and `authentication_envelope_retained=false` are explicit
fixture properties. Authentication, room records, the original raw envelope and
unrelated objects were omitted. The source hash labels the owner-verified source;
the public fixture cannot independently reauthenticate its original bytes or
reconstruct the original live session. `future_response_used_for_request=false`
records the request-only cutoff. No response, selected outcome or later object
identity is retained to fill the earlier request.

`rows_for` in `test_current_selectn.py` surrounds each retained request with
explicitly synthetic authentication, room and Full-state records. Runtime and
lifecycle tests use similarly synthetic stream wrappers and counterexamples.
They exercise current API binding, invalidation and isolation; they are not
additional real MTGA positive samples or original-current authentication.

The retained enums, list positions and explicit bounds do not establish stacking
order, ordering operations, complete combination constraints, response encoding,
server acceptance or complete legality. Current members do not become complete
proposals, selected literals or a research preference. All execution/input flags
remain false; complete proposal and legal-action counts remain unknown.
