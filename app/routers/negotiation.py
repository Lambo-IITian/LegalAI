import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from app.core.dependencies import get_current_user, get_current_user_optional
from app.core.exceptions import CaseNotFound, UnauthorizedAccess
from app.models.case import CaseStatus
from app.models.negotiation import (
    OfferType,
    ProofResponseRequest,
    ProposalDecision,
    ProposalResponseRequest,
    SubmitOfferRequest,
)
from app.services.cosmos_service import cosmos_service
from app.services.email_service import email_service

router = APIRouter()
logger = logging.getLogger(__name__)


# -------------------------
# Helpers
# -------------------------
def _now():
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str):
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _build_insights(case: dict) -> dict:
    intake = case.get("intake_data") or {}
    legal = case.get("legal_data") or {}
    analytics = case.get("analytics_data") or {}
    strengths = intake.get("claimant_strengths") or legal.get("claimant_rights") or []
    defenses = legal.get("respondent_defenses") or []
    weaknesses = intake.get("claimant_weaknesses") or analytics.get("risk_factors") or []
    proof_gaps = intake.get("missing_proof_checklist") or analytics.get("missing_evidence") or []
    return {
        "what_helps_claimant": strengths,
        "what_hurts_claimant": weaknesses,
        "respondent_defenses": defenses,
        "how_respondent_can_win": legal.get("respondent_win_paths") or defenses,
        "missing_proof": proof_gaps,
        "recommended_first_demand": analytics.get("recommended_first_demand") or case.get("claim_amount"),
        "recommended_settlement_range": {
            "min": analytics.get("zopa_min"),
            "optimal": analytics.get("zopa_optimal"),
            "max": analytics.get("zopa_max"),
        },
        "forum": legal.get("forum_name"),
        "win_probability": analytics.get("win_probability"),
        "court_cost_estimate": analytics.get("court_cost_estimate"),
        "time_to_resolution_months": analytics.get("time_to_resolution_months"),
    }


# -------------------------
# ROUND MANAGEMENT
# -------------------------
def _default_round(neg: dict, round_number: int):
    return {
        "round_number": round_number,
        "offer_type": neg["offer_type"],
        "claimant": {
            "amount": None,
            "actions": [],
            "explanation": None,
            "decision": "PENDING",
            "submitted_at": None,
        },
        "respondent": {
            "amount": None,
            "actions": [],
            "explanation": None,
            "decision": "PENDING",
            "submitted_at": None,
        },
        "ai_proposed_amount": None,
        "ai_reasoning": None,
        "proposal_issued_at": None,
    }


def _resolve_active_round_number(case, requested_round):
    if case.get("current_round"):
        return case["current_round"]
    return requested_round or 1


def _get_or_create_round(neg, round_number):
    round_doc = cosmos_service.get_round(neg["id"], round_number)
    if round_doc:
        return round_doc

    round_doc = _default_round(neg, round_number)
    cosmos_service.add_round_to_negotiation(neg["id"], round_doc)
    return round_doc


# -------------------------
# START NEXT ROUND (FIXED)
# -------------------------
async def _start_next_round(case_id, next_round_number):
    case = cosmos_service.get_case(case_id)
    neg = cosmos_service.get_negotiation_by_case(case_id)

    if neg:
        round_doc = cosmos_service.get_round(neg["id"], next_round_number)
        if not round_doc:
            round_doc = _default_round(neg, next_round_number)
            cosmos_service.add_round_to_negotiation(neg["id"], round_doc)

        cosmos_service.update_negotiation(
            neg["id"],
            {"current_waiting_on": None},
        )

    cosmos_service.transition_case(
        case_id,
        CaseStatus.NEGOTIATION_OPEN,
        {
            "current_round": next_round_number,
            "action_required_by": None,
        },
    )

    # Notify both parties
    for email, name in [
        (case["respondent_email"], case["respondent_name"]),
        (case["claimant_email"], case["claimant_name"]),
    ]:
        email_service.send_next_round_invite(
            to_email=email,
            party_name=name,
            case_id=case_id,
            round_num=next_round_number,
            portal_url="",
        )


# -------------------------
# OFFER SUBMISSION
# -------------------------
async def _handle_offer_submission(case, neg, round_doc, body, party):
    round_doc[party]["amount"] = body.offer_amount
    round_doc[party]["explanation"] = body.explanation
    round_doc[party]["submitted_at"] = _now()

    cosmos_service.upsert_round_in_negotiation(
        neg["id"],
        round_doc["round_number"],
        round_doc,
    )

    claimant_sub = round_doc["claimant"]["submitted_at"]
    respondent_sub = round_doc["respondent"]["submitted_at"]

    # If both submitted → mediation
    if claimant_sub and respondent_sub:
        cosmos_service.transition_case(
            case["id"],
            CaseStatus.MEDIATOR_REVIEW,
            {
                "current_round": round_doc["round_number"],
                "action_required_by": None,
            },
        )

        return {
            "status": CaseStatus.MEDIATOR_REVIEW.value,
            "round_number": round_doc["round_number"],
        }

    # Otherwise waiting for other party
    waiting = "respondent" if party == "claimant" else "claimant"
    waiting_status = (
        CaseStatus.WAITING_FOR_RESPONDENT
        if waiting == "respondent"
        else CaseStatus.WAITING_FOR_CLAIMANT
    )

    cosmos_service.transition_case(
        case["id"],
        waiting_status,
        {
            "current_round": round_doc["round_number"],
            "action_required_by": waiting,
        },
    )

    return {
        "status": waiting_status.value,
        "round_number": round_doc["round_number"],
    }


# -------------------------
# CLAIMANT OFFER
# -------------------------
@router.post("/submit-claimant-offer")
async def submit_claimant_offer(
    body: SubmitOfferRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
):
    case = cosmos_service.get_case(body.case_id)
    if not case:
        raise CaseNotFound(body.case_id)

    neg = cosmos_service.get_negotiation_by_case(body.case_id)

    round_number = _resolve_active_round_number(case, body.round_number)
    round_doc = _get_or_create_round(neg, round_number)

    result = await _handle_offer_submission(
        case, neg, round_doc, body, "claimant"
    )

    return result


# -------------------------
# RESPONDENT OFFER
# -------------------------
@router.post("/submit-respondent-offer")
async def submit_respondent_offer(
    body: SubmitOfferRequest,
    background_tasks: BackgroundTasks,
):
    case = cosmos_service.get_case(body.case_id)
    if not case:
        raise CaseNotFound(body.case_id)

    neg = cosmos_service.get_negotiation_by_case(body.case_id)

    round_number = _resolve_active_round_number(case, body.round_number)
    round_doc = _get_or_create_round(neg, round_number)

    result = await _handle_offer_submission(
        case, neg, round_doc, body, "respondent"
    )

    return result


# -------------------------
# PROPOSAL RESPONSE (FIXED ROUND FLOW)
# -------------------------
@router.post("/proposal-response")
async def proposal_response(
    body: ProposalResponseRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user_optional),
):
    case = cosmos_service.get_case(body.case_id)
    if not case:
        raise CaseNotFound(body.case_id)

    neg = cosmos_service.get_negotiation_by_case(body.case_id)
    round_doc = cosmos_service.get_round(neg["id"], body.round_number)

    round_doc[body.party]["decision"] = body.decision.value
    cosmos_service.upsert_round_in_negotiation(
        neg["id"], body.round_number, round_doc
    )

    claimant_decision = round_doc["claimant"]["decision"]
    respondent_decision = round_doc["respondent"]["decision"]

    # If both decided
    if claimant_decision != "PENDING" and respondent_decision != "PENDING":
        # Both accept → settlement
        if claimant_decision == "ACCEPT" and respondent_decision == "ACCEPT":
            cosmos_service.transition_case(
                body.case_id,
                CaseStatus.SETTLED,
                {"action_required_by": None},
            )
            return {"outcome": "SETTLED"}

        # Otherwise → next round
        max_rounds = case.get("max_rounds", 3)
        if body.round_number >= max_rounds:
            cosmos_service.transition_case(
                body.case_id,
                CaseStatus.ESCALATED,
                {"action_required_by": None},
            )
            return {"outcome": "ESCALATED"}

        await _start_next_round(body.case_id, body.round_number + 1)

        return {
            "outcome": "NEXT_ROUND",
            "next_round": body.round_number + 1,
        }

    # Waiting for other party decision
    waiting = "claimant" if claimant_decision == "PENDING" else "respondent"
    waiting_status = (
        CaseStatus.WAITING_FOR_CLAIMANT
        if waiting == "claimant"
        else CaseStatus.WAITING_FOR_RESPONDENT
    )

    cosmos_service.transition_case(
        body.case_id,
        waiting_status,
        {
            "current_round": body.round_number,
            "action_required_by": waiting,
        },
    )

    return {"message": "Waiting for other party decision"}


@router.post("/proof-response")
async def proof_response(
    body: ProofResponseRequest,
    current_user: dict = Depends(get_current_user_optional),
):
    case = cosmos_service.get_case(body.case_id)
    if not case:
        raise CaseNotFound(body.case_id)

    if body.party == "claimant":
        if not current_user or current_user["email"] != case["claimant_email"]:
            raise UnauthorizedAccess()
    elif body.party != "respondent":
        raise HTTPException(status_code=400, detail="party must be 'claimant' or 'respondent'")

    neg = cosmos_service.get_negotiation_by_case(body.case_id)
    if not neg:
        raise HTTPException(status_code=404, detail="Negotiation not found.")

    proof_item = next((item for item in neg.get("proof_requests", []) if item.get("id") == body.request_id), None)
    if not proof_item:
        raise HTTPException(status_code=404, detail="Proof request not found.")
    if proof_item.get("requested_from") != body.party:
        raise HTTPException(status_code=403, detail="This proof request is not assigned to your side.")

    cosmos_service.update_proof_request(
        neg["id"],
        body.request_id,
        {
            "status": "RESPONDED",
            "response_text": body.response_text.strip(),
            "file_refs": body.file_refs or [],
            "response_at": _now(),
        },
    )

    cosmos_service.append_shared_note(
        neg["id"],
        {
            "id": _new_id("note"),
            "round_number": body.round_number,
            "party": body.party,
            "note_type": "proof_response",
            "text": body.response_text.strip(),
            "created_at": _now(),
        },
    )

    refreshed_neg = cosmos_service.get_negotiation_by_case(body.case_id)
    round_doc = cosmos_service.get_round(refreshed_neg["id"], body.round_number)
    pending = [
        item for item in refreshed_neg.get("proof_requests", [])
        if item.get("round_number") == body.round_number and item.get("status") == "PENDING"
    ]

    if round_doc:
        round_doc["unresolved_proof_request_ids"] = [item["id"] for item in pending]
        cosmos_service.upsert_round_in_negotiation(refreshed_neg["id"], body.round_number, round_doc)

    claimant_submitted = bool((round_doc or {}).get("claimant", {}).get("submitted_at"))
    respondent_submitted = bool((round_doc or {}).get("respondent", {}).get("submitted_at"))

    if pending:
        waiting = pending[0]["requested_from"]
        waiting_status = CaseStatus.PROOF_REQUESTED
    elif claimant_submitted and respondent_submitted:
        waiting = None
        waiting_status = CaseStatus.MEDIATOR_REVIEW
    elif claimant_submitted:
        waiting = "respondent"
        waiting_status = CaseStatus.WAITING_FOR_RESPONDENT
    elif respondent_submitted:
        waiting = "claimant"
        waiting_status = CaseStatus.WAITING_FOR_CLAIMANT
    else:
        waiting = None
        waiting_status = CaseStatus.NEGOTIATION_OPEN

    cosmos_service.transition_case(
        body.case_id,
        waiting_status,
        {
            "current_round": body.round_number,
            "action_required_by": waiting,
        },
    )
    cosmos_service.update_negotiation(refreshed_neg["id"], {"current_waiting_on": waiting})

    return {
        "message": "Proof response recorded and shared with the other party.",
        "status": waiting_status.value,
        "action_required_by": waiting,
    }


@router.get("/status/{case_id}")
async def get_negotiation_status(
    case_id: str,
    current_user: dict = Depends(get_current_user_optional),
):
    case = cosmos_service.get_case(case_id)
    if not case:
        raise CaseNotFound(case_id)

    if current_user and current_user.get("email") != case.get("claimant_email"):
        raise UnauthorizedAccess()

    neg = cosmos_service.get_negotiation_by_case(case_id)
    round_number = case.get("current_round", 0)
    current_round = cosmos_service.get_round(neg["id"], round_number) if neg and round_number > 0 else None

    current_round_detail = None
    if current_round:
        claimant = current_round.get("claimant") or {}
        respondent = current_round.get("respondent") or {}
        current_round_detail = {
            "claimant_submitted": bool(claimant.get("submitted_at")),
            "respondent_submitted": bool(respondent.get("submitted_at")),
            "proposal_issued": bool(current_round.get("ai_proposed_amount") or current_round.get("ai_proposed_actions")),
            "proposed_amount": current_round.get("settlement_candidate_amount") or current_round.get("ai_proposed_amount"),
            "ai_reasoning": current_round.get("settlement_candidate_reason") or current_round.get("ai_reasoning"),
            "ai_reasoning_breakdown": current_round.get("ai_reasoning_breakdown"),
            "ai_reasoning_log": current_round.get("ai_reasoning_log", []),
            "claimant_decision": claimant.get("decision"),
            "respondent_decision": respondent.get("decision"),
            "claimant_offer": claimant.get("amount"),
            "respondent_offer": respondent.get("amount"),
            "claimant_explanation": claimant.get("explanation"),
            "respondent_explanation": respondent.get("explanation"),
            "claimant_proof_note": claimant.get("proof_note"),
            "respondent_proof_note": respondent.get("proof_note"),
            "claimant_requested_proof": claimant.get("requested_proof", []),
            "respondent_requested_proof": respondent.get("requested_proof", []),
            "settlement_candidate_amount": current_round.get("settlement_candidate_amount"),
            "settlement_candidate_reason": current_round.get("settlement_candidate_reason"),
            "unresolved_proof_request_ids": current_round.get("unresolved_proof_request_ids", []),
        }

    return {
        "case_id": case_id,
        "status": case["status"],
        "current_round": round_number,
        "max_rounds": case.get("max_rounds", 3),
        "track": case.get("track"),
        "action_required_by": case.get("action_required_by"),
        "settlement_url": case.get("settlement_url"),
        "settlement_email_status": case.get("settlement_email_status"),
        "ai_reasoning_log": case.get("ai_reasoning_log", []),
        "insights": _build_insights(case),
        "negotiation": {
            "id": neg["id"] if neg else None,
            "offer_type": neg.get("offer_type") if neg else None,
            "rounds_done": len(neg.get("rounds", [])) if neg else 0,
            "current_waiting_on": neg.get("current_waiting_on") if neg else None,
            "rounds": neg.get("rounds", []) if neg else [],
            "proof_requests": neg.get("proof_requests", []) if neg else [],
            "shared_notes": neg.get("shared_notes", []) if neg else [],
        },
        "current_round_detail": current_round_detail,
    }
