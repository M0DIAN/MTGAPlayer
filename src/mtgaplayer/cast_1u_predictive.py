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
    solution = cast.get("autoTapSolution")
    _need(type(solution) is dict and set(solution) == {"autoTapActions"}, "cast_auto_tap_shape_not_reviewed")
    descriptors = solution["autoTapActions"]
    _need(type(descriptors) is list and len(descriptors) == 2, "cast_auto_tap_shape_not_reviewed")

    sources = set()
    mana_ids = set()
    untapped = 0
    unknown_tapped = 0
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
        source = reducer.objects.get(source_id)
        visible = [o for o in state["visible_objects"] if type(o) is dict and o.get("instance_id") == source_id]
        seat = state["binding"]["self_seat"]
        _need(
            type(source) is dict and source.get("type") == "GameObjectType_Card"
            and type(source.get("grpId")) is int and source["grpId"] == mana.get("grpId")
            and type(source.get("ownerSeatId")) is int and source["ownerSeatId"] == seat
            and type(source.get("controllerSeatId")) is int and source["controllerSeatId"] == seat
            and len(visible) == 1
            and visible[0]["zone"] == "ZoneType_Battlefield"
            and type(visible[0]["card_id"]) is int and visible[0]["card_id"] == mana.get("grpId")
            and type(visible[0]["owner_seat"]) is int and visible[0]["owner_seat"] == seat
            and type(visible[0]["controller_seat"]) is int and visible[0]["controller_seat"] == seat
            and type(source.get("uniqueAbilities")) is list
            and sum(type(a) is dict and type(a.get("id")) is int
                    and a["id"] == unique_ability and type(a.get("grpId")) is int
                    and a["grpId"] == group_id for a in source["uniqueAbilities"]) == 1,
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
        distinct_predictive_sources=len(sources),
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
