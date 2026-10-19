"""Evidence-limited 1U Cast predictive-source reconciliation (MP98 research only).

A coherent predicted auto-tap route is neither a completed payment nor a legal
action. The existing MP96 Cast research remains unchanged and authoritative for
parent selection/currentness; this opt-in assessor adds no policy or input path.
"""
import copy

from .cast_cardflow import assess_current_cast_cardflow
from .cast_target_members import _equal
from .choice_candidates import _assess_current_report
from .decision_consumer import EXECUTION, _bounded_json
from .request_parameters import LiteralRefs
from .semantic_cast import action
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
