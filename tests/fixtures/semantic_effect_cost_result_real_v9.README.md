# Curated real nonmana selection and sacrifice observation

semantic_effect_cost_result_real_v9.json is the unchanged episode at producer
index26 from semantic v9's export of the frozen phase3 original stopped log.
Original source SHA-256:
4e888a7d29a9ac7f25c5d7aabc9517d5042c260d4065fa6c136e64ae45b616af.
The same 732 records are framed by RawFollower; RawReducer authenticates request
473/state338 at record603/GRE1 and its consumed EffectCostResp at record622.
The first continuous successor is record623/GRE0/state339, previous338.

The actual response selected offered position1. Raw annotation745 maps the
selected old object to its new reference; annotation746 explicitly identifies a
Battlefield→Graveyard Sacrifice. Both use the same public stack affector. The
visible endpoints have the same known Card identity and owner; the old reference
is absent afterward and the new reference absent before. Two other annotations
are omitted. In the portable episode these refs are selected116, new149 and
affector148. They are scoped aliases, not raw GRE IDs.

The complete producer counts are54 matched pairs,29 exported episodes,25
unsupported and0 omitted. This curated container retains one exact episode;
only its sample list/counts/unsupported list describe the curation. Its source
framed-record count remains732. Normalizing just the new trace facts to the old
endpoint-only contract gives the unchanged real v7 episode, checked in tests.

Raw authentication/account identity, prompts, UI metadata, raw annotations,
hidden objects, screenshots and collection records remain local and ignored.
Only the existing visible projection and two finite annotation relations are
retained; observed public Card IDs are not hidden identities. The request's
source remains unknown. The observed affector does not prove parent Activate,
complete payment, full legality, later Search causality or server acceptance.
Portable replay does not reauthenticate the private source.

Raw-producer mutations in test_semantic_effect_cost_result.py are explicitly
synthetic controls. They exercise refusal and cannot establish another real
payment mechanism or P10 defect repair. No upstream mana algorithm is needed for
this nonmana result.
