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