"""Evidence-limited 1U Cast predictive-source reconciliation (MP98 research only).

A coherent predicted auto-tap route is neither a completed payment nor a legal
action. The existing MP96 Cast research remains unchanged and authoritative for
parent selection/currentness; this opt-in assessor adds no policy or input path.
"""
import copy
import hashlib
import json

from .cast_cardflow import assess_current_cast_cardflow
from .cast_target_members import _equal
from .choice_candidates import _assess_current_report
from .decision_consumer import EXECUTION, _bounded_json
from .request_parameters import LiteralRefs
from .semantic_cast import action, _detail
from .semantic_activate import ability_observation
from .semantic_samples import _need
from .shadow_runtime import _stamp

VERSION = "mtgaplayer.cast-1u-predictive-source.v1"
PROFILE = "reviewed_generic_one_blue_one_two_blue_predictive_units"
CONSISTENT = "reviewed_predictive_amount_consistent"
REASONS = frozenset((
    "parent_cast_preference_unavailable",
    "parent_binding_or_content_changed",
    "cast_auto_tap_shape_not_reviewed",
    "predictive_source_or_unit_repeated",
    "predictive_unit_not_reviewed",
    "unique_matching_current_mana_offer_missing",
    "offered_mana_option_or_selection_mismatch",
    "public_source_or_ability_identity_unverified",
    "source_explicitly_tapped",
))


def _unknown(reason, ref=None, *, parent_status=None):
    expired = reason.startswith("consumer_") or reason in (
        "current_snapshot_binding_invalid", "current_snapshot_expired_or_changed",
        "parent_binding_or_content_changed", "owner_thread_required",
    )
    return {
        "schema_version": VERSION,
        "profile": PROFILE,
        "status": "expired" if expired else "insufficient_evidence",
        "reason": reason,
        "request_binding": None,
        "source_snapshot_ref": copy.deepcopy(ref),
        "reviewed_cast_option_key": None,
        "parent_research_status": parent_status,
        "literal_requirement": {"generic": 1, "blue": 1},
        "predictive_blue_units": None,
        "distinct_predictive_sources": None,
        "matched_offered_mana_actions": None,
        "explicit_untapped_sources": None,
        "sources_with_unknown_tapped_state": None,
        "predictive_amount_consistency_verified": False,
        "predictive_source_identity_consistency_verified": False,
        "source_readiness_verified": False,
        "actual_mana_paid_observed": False,
        "payment_verified": False,
        "complete_payment_verified": False,
        "legal_choice_verified": False,
        "complete_legality_verified": False,
        "server_acceptance_verified": False,
        "response_encoding_verified": False,
        "strategic_optimality_verified": False,
        "read_only": True,
        **EXECUTION,
    }


def _route(raw, cast):
    """Shared exact current-offer projection; no outcome or resource solver."""
    _need(_equal(cast.get("manaCost"), [
        {"color": ["ManaColor_Generic"], "count": 1},
        {"color": ["ManaColor_Blue"], "count": 1},
    ]), "parent_binding_or_content_changed")
    solution = cast.get("autoTapSolution")
    _need(type(solution) is dict and set(solution) == {"autoTapActions"}, "cast_auto_tap_shape_not_reviewed")
    descriptors = solution["autoTapActions"]
    _need(type(descriptors) is list and len(descriptors) == 2, "cast_auto_tap_shape_not_reviewed")

    sources = set()
    mana_ids = set()
    routes = []
    for descriptor in descriptors:
        _need(type(descriptor) is dict and set(descriptor) == {
            "instanceId", "abilityGrpId", "manaPaymentOption"
        }, "cast_auto_tap_shape_not_reviewed")
        source_id = descriptor["instanceId"]
        group_id = descriptor["abilityGrpId"]
        _need(
            type(source_id) is int and source_id > 0
            and type(group_id) is int and group_id > 0,
            "cast_auto_tap_shape_not_reviewed",
        )
        _need(source_id not in sources, "predictive_source_or_unit_repeated")
        sources.add(source_id)
        option = descriptor["manaPaymentOption"]
        _need(type(option) is dict and set(option) == {"mana"}
              and type(option["mana"]) is list and len(option["mana"]) == 1,
              "predictive_unit_not_reviewed")
        unit = option["mana"][0]
        _need(type(unit) is dict and set(unit) == {
            "manaId", "color", "srcInstanceId", "specs", "abilityGrpId", "count"
        }, "predictive_unit_not_reviewed")
        mana_id = unit["manaId"]
        _need(type(mana_id) is int and mana_id > 0, "predictive_unit_not_reviewed")
        _need(mana_id not in mana_ids, "predictive_source_or_unit_repeated")
        mana_ids.add(mana_id)
        _need(
            unit["color"] == "ManaColor_Blue"
            and type(unit["count"]) is int and unit["count"] == 1
            and _equal(unit["specs"], [{"type": "ManaSpecType_Predictive"}])
            and type(unit["srcInstanceId"]) is int and unit["srcInstanceId"] == source_id
            and type(unit["abilityGrpId"]) is int and unit["abilityGrpId"] == group_id,
            "predictive_unit_not_reviewed",
        )

        offered = [row for row in raw if type(row) is dict
                   and row.get("actionType") == "ActionType_Activate_Mana"
                   and type(row.get("instanceId")) is int and row["instanceId"] == source_id
                   and type(row.get("abilityGrpId")) is int and row["abilityGrpId"] == group_id]
        _need(len(offered) == 1, "unique_matching_current_mana_offer_missing")
        mana = offered[0]
        # Same parser/known raw shape as MP96, not a new GRE decoder.
        action(mana, LiteralRefs(), ())
        _need(
            _equal(mana.get("manaPaymentOptions"), [option])
            and _equal(mana.get("manaSelections"), [{
                "instanceId": source_id,
                "abilityGrpId": group_id,
                "options": [{"mana": [{"color": "ManaColor_Blue", "count": 1}]}],
            }]),
            "offered_mana_option_or_selection_mismatch",
        )
        unique_ability = mana.get("uniqueAbilityId")
        _need(type(unique_ability) is int and unique_ability > 0,
              "public_source_or_ability_identity_unverified")
        routes.append((source_id, mana))
    return routes


def _positive(state, ref, reducer, message, parent, completed_stamp):
    # The MP96 policy has already checked the full parent offer, exact catalog,
    # visible Hand card and static/phase gates. Never borrow a later outcome.
    _need(
        _equal(parent["request_binding"], state["binding"])
        and _equal(parent["source_snapshot_ref"], ref)
        and state["binding"]["request_type"] == "GREMessageType_ActionsAvailableReq"
        and _equal(_stamp(reducer, message, state), completed_stamp),
        "parent_binding_or_content_changed",
    )
    raw = message["actionsAvailableReq"]["actions"]
    position = parent["source_identity"]["list_position"]
    _need(type(position) is int and 0 <= position < len(raw), "parent_binding_or_content_changed")
    cast = raw[position]
    _need(
        cast["actionType"] == "ActionType_Cast"
        and cast["grpId"] == 96626
        and _equal(action(cast, LiteralRefs(), ()), parent["cast_action_evidence"])
        and _equal(cast["manaCost"], [
            {"color": ["ManaColor_Generic"], "count": 1},
            {"color": ["ManaColor_Blue"], "count": 1},
        ]),
        "parent_binding_or_content_changed",
    )
    routes = _route(raw, cast)
    untapped = unknown_tapped = 0
    for source_id, mana in routes:
        unique_ability = mana["uniqueAbilityId"]
        source = reducer.objects.get(source_id)
        visible = [o for o in state["visible_objects"] if type(o) is dict and o.get("instance_id") == source_id]
        seat = state["binding"]["self_seat"]
        _need(
            type(source) is dict and source.get("type") == "GameObjectType_Card"
            and source_id in reducer._mana_source_refs()
            and type(source.get("grpId")) is int and source["grpId"] == mana.get("grpId")
            and type(source.get("ownerSeatId")) is int and source["ownerSeatId"] == seat
            and type(source.get("controllerSeatId")) is int and source["controllerSeatId"] == seat
            and len(visible) == 1
            and visible[0]["zone"] == "ZoneType_Battlefield"
            and type(visible[0]["card_id"]) is int and visible[0]["card_id"] == mana.get("grpId")
            and type(visible[0]["owner_seat"]) is int and visible[0]["owner_seat"] == seat
            and type(visible[0]["controller_seat"]) is int and visible[0]["controller_seat"] == seat
            and ability_observation(mana, source.get("uniqueAbilities")) == "verified_observed_pair",
            "public_source_or_ability_identity_unverified",
        )
        if visible[0]["tapped"] is True:
            raise ValueError("source_explicitly_tapped")
        if visible[0]["tapped"] is False:
            untapped += 1
        else:
            _need(visible[0]["tapped"] is None, "public_source_or_ability_identity_unverified")
            unknown_tapped += 1

    # Record counts, not raw source IDs or mana IDs. Blue2 is a numeric match
    # for observed {Generic1,Blue1}, NOT proof that MTGA will pay or accept it.
    _need(_equal(_stamp(reducer, message, state), completed_stamp),
          "parent_binding_or_content_changed")
    result = _unknown(CONSISTENT, ref, parent_status=parent["status"])
    result.update(
        status=CONSISTENT,
        request_binding=copy.deepcopy(state["binding"]),
        reviewed_cast_option_key=copy.deepcopy(parent["preferred_option_key"]),
        predictive_blue_units=2,
        distinct_predictive_sources=len(routes),
        matched_offered_mana_actions=2,
        explicit_untapped_sources=untapped,
        sources_with_unknown_tapped_state=unknown_tapped,
        predictive_amount_consistency_verified=True,
        predictive_source_identity_consistency_verified=True,
    )
    _bounded_json(result)
    return result


def assess_current_cast_1u_predictive(consumer, reducer, message, prepared_rules, *,
                                      completed_stamp=None):
    """Owner-thread read-only current-stage research; never a payment verdict.

    The parent MP96 report authenticates the one reviewed Cast and current
    catalog before we compare its *same-request* two predictive mana options.
    Caller must use the existing production Consumer/Reducer and accepted raw
    message, with the original completed-poll stamp. No cached history, input
    or late client response is considered.
    """
    if completed_stamp is None:
        return _unknown("completed_poll_context_required")
    parent = assess_current_cast_cardflow(
        consumer, reducer, message, prepared_rules, completed_stamp=completed_stamp)
    if parent["status"] != "research_preference":
        result = _unknown("parent_cast_preference_unavailable",
                          parent_status=parent["status"])
        if parent["status"] == "expired":
            result["status"] = "expired"
        return result

    def evaluate(state, *, source_snapshot_ref):
        try:
            return _positive(state, source_snapshot_ref, reducer, message, parent, completed_stamp)
        except (ValueError, TypeError, KeyError, IndexError, RecursionError, OverflowError) as error:
            reason = str(error)
            return _unknown(reason if reason in REASONS else
                            "cast_auto_tap_shape_not_reviewed",
                            source_snapshot_ref, parent_status=parent["status"])

    return _assess_current_report(consumer, evaluate, _unknown)


def reconcile_observed_cast_1u_sources(document):
    """Opt-in historical v2 source-link replay, never a current payment verdict.

    The existing portable producer certifies the request/response pair; replay
    does not reauthenticate private bytes. MP34 preserves ManaPaid source/spell
    links, not its opaque id/color details or actual units. This profile joins
    those links to the selected Cast's same-request predicted sources only.
    """
    from .semantic_cast import VERSION as SAMPLES_V2
    from .semantic_samples import replay_samples
    from .semantic_activate import raw_action

    _need(type(document) is dict and document.get("schema_version") == SAMPLES_V2,
          "historical_v2_samples_required")
    replay = replay_samples(document)  # existing size, typed shape and trace checks
    reports = []
    for sample, checked in zip(document["samples"], replay["samples"]):
        report = _unknown("historical_source_links_unverified")
        report.update(schema_version="mtgaplayer.cast-1u-observed-sources.v1",
            profile=PROFILE, time_scope="historical_only", current_available=False,
            raw_source_auth_revalidated=False, identity=copy.deepcopy(sample["identity"]),
            observed_mana_paid_source_links=None, observed_sources_tapped=None,
            historical_source_links_consistent=False, actual_color_count_verified=False)
        try:
            position = checked["selected_action_position"]
            rows = sample["request"]["payload"]["actions"]
            chosen = sample["response"]["payload"]["action"]
            _need(type(position) is int and _equal(rows[position], chosen),
                  "historical_selected_row_not_exact")
            raw = [raw_action(a) for a in rows]
            cast = raw[position]
            _need(cast["actionType"] == "ActionType_Cast" and cast["grpId"] == 96626,
                  "historical_cast_profile_unreviewed")
            routes = _route(raw, cast)
            seat = sample["identity"]["self_seat"]
            before = {o["object_ref"]: o for o in sample["before"]["objects"]}
            source = before[cast["instanceId"]]
            _need(source["zone"] == "ZoneType_Hand" and source["card_id"] == 96626
                  and source["owner"] == source["controller"] == seat,
                  "historical_cast_source_unverified")
            trace = sample["trace"]
            _need(trace["status"] in ("eof", "next_request_observed") and not trace["truncated"]
                  and trace["states"] and all(s["facts_status"] == "reviewed_subset" for s in trace["states"]),
                  "historical_trace_incomplete")
            first = trace["states"][0]
            migrations = [f for s in trace["states"] for f in s["facts"]
                if f["kind"] == "object_id_changed" and f["original_object_ref"] == cast["instanceId"]]
            _need(len(migrations) == 1 and migrations[0] in first["facts"],
                  "historical_cast_migration_ambiguous")
            spell = migrations[0]["new_object_ref"]
            objects = {o["object_ref"]: o for o in first["snapshot"]["objects"]}
            involved = [f for s in trace["states"] for f in s["facts"]
                if f["kind"] == "object_id_changed" and
                (f["original_object_ref"] in (cast["instanceId"], spell) or
                 f["new_object_ref"] in (cast["instanceId"], spell))]
            _need(len(involved) == 1 and spell not in before and
                  all(cast["instanceId"] not in {o["object_ref"] for o in s["snapshot"]["objects"]}
                      for s in trace["states"]), "historical_cast_migration_ambiguous")
            _need(objects[spell]["zone"] == "ZoneType_Stack" and objects[spell]["card_id"] == 96626
                  and objects[spell]["owner"] == objects[spell]["controller"] == seat
                  and sum(f == {"kind":"zone_transfer", "object_ref":spell,
                      "source_zone":"ZoneType_Hand", "destination_zone":"ZoneType_Stack",
                      "category":"CastSpell"} for f in first["facts"]) == 1,
                  "historical_cast_stack_unverified")
            expected = {sid for sid, _ in routes}
            links = [(s, f) for s in trace["states"] for f in s["facts"]
                     if f["kind"] == "mana_paid"]
            _need(len(links) == 2 and all(s is first and f["spell_object_ref"] == spell for s, f in links)
                  and {f["source_object_ref"] for _, f in links} == expected,
                  "historical_paid_source_links_mismatch")
            for sid, offered in routes:
                original = before[sid]
                _need(original["card_id"] == offered["grpId"] and
                      original["zone"] == "ZoneType_Battlefield" and
                      original["owner"] == original["controller"] == seat,
                      "historical_payment_source_unverified")
                for state in trace["states"]:
                    visible = {o["object_ref"]: o for o in state["snapshot"]["objects"]}
                    obj = visible[sid]
                    _need(all(_equal(obj[k], original[k]) for k in ("card_id", "zone", "owner", "controller")),
                          "historical_payment_source_changed")
                    _need(not any(f["kind"] == "object_id_changed" and
                                  (f["original_object_ref"] in expected or f["new_object_ref"] in expected)
                                  for f in state["facts"]), "historical_payment_source_changed")
            report.update(status="historical_source_links_consistent",
                reason="same_cast_predicted_sources_match_observed_mana_paid_links",
                observed_mana_paid_source_links=2,
                observed_sources_tapped=sum(objects[sid]["tapped"] is True for sid in expected),
                historical_source_links_consistent=True, actual_mana_paid_observed=True)
        except (ValueError, TypeError, KeyError, IndexError):
            pass  # opaque or contradictory history cannot grant a current result
        reports.append(report)
    return {"schema_version":"mtgaplayer.cast-1u-observed-source-replay.v1",
        "time_scope":"historical_only", "samples":reports, "raw_source_auth_revalidated":False,
        "current_available":False, "complete_payment_verified":False,
        "complete_legality_verified":False, "read_only":True, **EXECUTION}


# Same-build PE/IL evidence, not a card-database Colors mapping or runtime DLL
# dependency. See docs/cast-1u-payment.md for the two different parser branches.
MANA_FIELDS_VERSION = "mtgaplayer.cast-1u-mana-fields.v1"
MANA_FIELDS_PROOF = {
    "client_build": "2026.64.0.14517.1329972",
    "header_sha256": "6f0427d6b57e660e862dbaa8810f57c60c318613fa52f0bf44d27ac3e104d2c0",
    "SharedClientCore.dll": "42f2fb5f062ccc6098182a902d411746070759a404e875b6e0aac44d3b7ccc6e",
    "SharedClientCore_mvid": "c162c20f-ba79-438b-abd6-058f915926a3",
    "Wizards.MDN.GreProtobuf.dll": "7ca28480089cc2b21417abfea82b9c8721ff855f0369966858d70d58f2afcdae",
    "GreProtobuf_mvid": "3acc2830-eab7-4327-be16-8969a71eb3aa",
    "parser_MoveNext_body_sha256": "c5c5fd05cb344d89e02d84e9c4b5b01b120db7ad9519b48ef1b667d8ce41fcf2",
}


def verify_observed_cast_1u_mana_fields(document, evidence):
    """Explicit portable historical field check; never authenticates raw bytes.

    An Owner supplies a separately scrubbed, whole-document-bound projection of
    two singleton int32 id/color details. References are opaque aliases in an
    ACTUAL-mana namespace, not request-local predictive mana IDs. The preexisting
    v2 replay authenticates neither original private source nor caller claims;
    this checker has exactly that same trust boundary. A matching declared
    version selects a pinned interpretation, not a fresh build attestation.

    Only the annotation's encoded color and distinct identifiers are reviewed.
    The client can instead use an old pool entry's Color/Count; missing pool
    fields do not select its Count=1 fallback. No actual units are inferred.
    """
    base = reconcile_observed_cast_1u_sources(document)
    report = {
        "schema_version": MANA_FIELDS_VERSION,
        "status": "unknown", "reason": "payment_field_evidence_unavailable",
        "time_scope": "historical_only", "current_available": False,
        "request_binding": None, "source_snapshot_ref": None,
        "provenance_scope": "declared_owner_projection_not_raw_or_build_reauthentication",
        "raw_source_auth_revalidated": False, "source_build_reauthenticated": False,
        "observed": None, "verified_scope": [],
        "annotation_color_encoding_verified": False,
        "unknown": ["effective_client_event_color", "client_pool_lookup_branch",
                    "actual_mana_units", "duplicate_or_merged_engine_accounting",
                    "additional_costs_and_complete_payment", "pre_request_source_readiness"],
        "contradicted": [], "contradicted_scope": None, "actual_mana_units": None,
        "actual_paid_color_verified": False, "payment_verified": False,
        "complete_payment_verified": False, "source_readiness_verified": False,
        "server_acceptance_verified": False, "response_encoding_verified": False,
        "complete_legality_verified": False, "strategic_optimality_verified": False,
        "read_only": True, **EXECUTION,
    }
    try:
        _bounded_json(evidence)
        _need(type(evidence) is dict and set(evidence) == {
            "schema_version", "document_sha256", "identity", "version_evidence", "events",
            "mana_id_namespace"
        } and evidence["schema_version"] == MANA_FIELDS_VERSION,
            "payment_field_evidence_shape_unreviewed")
        _need(evidence["mana_id_namespace"] == "aliased_actual_mana_not_predictive",
              "payment_field_mana_namespace_unreviewed")
        # Hash canonical UTF-8 JSON, not filesystem bytes or normalized log text.
        digest = hashlib.sha256(json.dumps(document, sort_keys=True, ensure_ascii=True,
            separators=(",", ":"), allow_nan=False).encode("utf8")).hexdigest()
        _need(evidence["document_sha256"] == digest, "payment_document_digest_mismatch")
        _need(_equal(evidence["version_evidence"], MANA_FIELDS_PROOF),
              "payment_field_build_not_reviewed")
        _need(len(document["samples"]) == 1 and len(base["samples"]) == 1,
              "payment_field_single_sample_required")
        sample = document["samples"][0]
        _need(_equal(evidence["identity"], sample["identity"]), "payment_sample_identity_mismatch")
        _need(base["samples"][0]["historical_source_links_consistent"],
              "historical_source_links_unverified")
        first = sample["trace"]["states"][0]
        indexed = [(i, f) for i, f in enumerate(first["facts"]) if f["kind"] == "mana_paid"]
        events = evidence["events"]
        _need(type(events) is list and len(events) == len(indexed) == 2,
              "payment_field_rows_incomplete_or_extra")
        annotation_refs, mana_refs, fact_indices = set(), set(), set()
        colors = []
        for event in events:
            _need(type(event) is dict and set(event) == {
                "state_ref", "fact_index", "source_object_ref", "spell_object_ref",
                "annotation_ref", "details"
            }, "payment_field_row_shape_unreviewed")
            _need(type(event["fact_index"]) is int and event["fact_index"] not in fact_indices,
                  "payment_field_fact_repeated_or_invalid")
            matches = [f for i, f in indexed if i == event["fact_index"]]
            _need(len(matches) == 1 and
                  _equal(event["state_ref"], first["snapshot"]["state_ref"]) and
                  _equal(event["source_object_ref"], matches[0]["source_object_ref"]) and
                  _equal(event["spell_object_ref"], matches[0]["spell_object_ref"]),
                  "payment_field_state_source_or_spell_mismatch")
            fact_indices.add(event["fact_index"])
            ref = event["annotation_ref"]
            _need(type(ref) is str and ref in ("paid-annotation-1", "paid-annotation-2")
                  and ref not in annotation_refs, "payment_field_annotation_repeated_or_unreviewed")
            annotation_refs.add(ref)
            details = _detail(event)  # same singleton/duplicate-key parser as MP34
            _need(set(details) == {"id", "color"} and all(type(v) is int for v in details.values())
                  and all(d["type"] == "KeyValuePairValueType_int32" for d in event["details"]),
                  "payment_field_detail_type_unreviewed")
            _need(details["id"] in (1, 2) and details["id"] not in mana_refs,
                  "payment_field_actual_reference_repeated_or_unreviewed")
            mana_refs.add(details["id"])
            colors.append(details["color"])
        report["observed"] = {"annotation_rows": 2, "distinct_actual_mana_refs": 2,
                              "Blue_encoded_color_rows": colors.count(2)}
        # This exact finite profile checks the two observed Blue encodings;
        # it neither rejects other colors as invalid GRE nor solves payment.
        if any(c not in range(14) for c in colors):
            report["reason"] = "payment_color_encoding_not_reviewed"
        elif colors != [2, 2]:
            report.update(status="contradicted", reason="encoded_colors_differ_from_two_blue_profile",
                          contradicted=["two_Blue_annotation_color_encodings"],
                          contradicted_scope="reviewed_annotation_encoding_profile_only")
        else:
            report.update(status="verified_scope", reason="same_cast_two_Blue_annotation_color_encodings",
                annotation_color_encoding_verified=True,
                verified_scope=["exact_build_annotation_color_encoding_Blue",
                    "distinct_actual_mana_identifier_aliases", "same_cast_predicted_source_links"])
    except (ValueError, TypeError, KeyError, IndexError, OverflowError, RecursionError) as error:
        # A malformed/opaque field artifact cannot grant partial verification.
        reason = str(error)
        report["reason"] = reason if reason.startswith(("payment_", "historical_")) else "payment_field_evidence_shape_unreviewed"
    _bounded_json(report)
    return report
