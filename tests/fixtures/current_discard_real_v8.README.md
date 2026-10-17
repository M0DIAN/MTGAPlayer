# MP56 current Discard provenance

`current_discard_real_v8.json` is a sanitized **current State8** projection of
one authentic pre-response request and its post-response/post-successor-record
current states. It is separate from the older v6 historical fixture and from
`player_log_selectn.jsonl`. It does not recreate raw authentication or a Full.

Owner-local unchanged original: ignored
`artifacts/local-live-poc-dev/artifacts/local-live-poc/source-evidence-04/Player-prefix-at-snapshot04.log`,
3237895 bytes, SHA256
`9f33dc04cddc13cdb50adc09b8bd58c71b3d80b0cfb08157b1cf3bad010f0ecb`.
Existing RawFramer finds278 complete records, no errors/partial record. Auth72,
room77 and genuine Full79/message1 establish the game's source; there are zero
continuity errors through request213/message4/state273. Ordinals are one-based;
GRE message indices are zero-based. Raw identities and original bytes remain
owner-local and cannot be reauthenticated by portable replay.

The request-only full prefix ends at byte2981911 (zero-based end-exclusive),
SHA256 `31dab49cbfa63368d5918cf9c7ddc0f2d1bd289f2f992fd606df901719e6ce05`.
It excludes actual response224 and all result225 input. The existing reducer's
current request/digest/own-seat gate authenticates eight distinct offered refs
in the visible own Hand, explicit minSel=maxSel1 and the strict
TurnBased/Discard/InstanceId/Dynamic/NonRepeatable shape. New producer checks
require ordinary physical Cards, matching own Hand zone/object ownership and
zoneId, unique membership, and explicit visibility to self. Unsupported offers
withhold the whole profile; they are never dropped to manufacture an eight-set.

`before_response` is this offline State8. The eight `proposals` are constructed
only from its current offered domain, each validated by the same manual checker.
`after_response` is the request-free current state immediately after actual
SelectNResp224 (bytes2987115–2987613), selecting original offered position4.
`after_successor_record` is the current projection after the **whole record225**
(2987613–3015487), which contains five ordered accepted Diffs. Its first Diff
explicitly follows273; the fixture endpoint is after the fifth, not the first.
Neither later
state is an input to discovering or validating the pre-response proposals.
The older v6 historical checker independently corroborates migration/Discard
only for the actual position4; the other seven have no observed outcomes.

All match, game/generation, object, zone, request and state references use
fixture-scoped aliases. Seats, public life/turn, zones, visible tapping/stats,
fixed enums, quantities and uninterpreted numeric prompt values remain.
All `card_id` and card knowledge values are null. Source offsets/timestamps,
names, raw account/match/object identities, hidden objects/card identities,
credentials, prompts/parameter names, raw envelopes, annotations, screenshots
and alias maps are omitted. Hidden zone **counts** remain counts only.
No hidden hand/list is reconstructed; unknown cancel/source/unfiltered/weight
fields stay null. This is not raw-log semantic equivalence.

Canonical LF bytes32990; SHA256
`76ef5d23d5b9e10bbb72eb9f6daee018a25f6cf1c0cd215affc975e216010603`.
Negative mutations and transport/raw initialization in tests are synthetic
controls, not additional real games. Known membership/count consistency never
proves global discard legality, hand-limit rules, strategy, effect, response
encoding, server acceptance or execution. All authority flags stay false.
