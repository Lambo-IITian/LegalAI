import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from app.config import settings
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


# ─────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str = "id") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _portal_url(case_id: str) -> str:
    return f"{settings.BASE_URL}/respond/{case_id}"


def _build_insights(case: dict) -> dict:
    """Build the insights block shown to both parties (no confidential data)."""
    intake    = case.get("intake_data") or {}
    legal     = case.get("legal_data") or {}
    analytics = case.get("analytics_data") or {}
    return {
        "what_helps_claimant":        intake.get("claimant_strengths") or legal.get("claimant_rights") or [],
        "what_hurts_claimant":        intake.get("claimant_weaknesses") or [],
        "respondent_defenses":        legal.get("respondent_defenses") or [],
        "recommended_settlement_range": {
            "min":     analytics.get("zopa_min"),
            "optimal": analytics.get("zopa_optimal"),
            "max":     analytics.get("zopa_max"),
        },
        "forum":                      legal.get("forum_name"),
        "win_probability":            analytics.get("win_probability"),
        "court_cost_estimate":        analytics.get("court_cost_estimate"),
        "time_to_resolution_months":  analytics.get("time_to_resolution_months"),
    }


def _default_round(neg: dict, round_number: int) -> dict:
    """Returns a fresh empty round dict."""
    return {
        "round_number":                round_number,
        "offer_type":                  neg.get("offer_type", OfferType.MONETARY.value),
        "claimant": {
            "amount":       None,
            "actions":      [],
            "explanation":  None,
            "decision":     ProposalDecision.PENDING.value,
            "submitted_at": None,
            "decided_at":   None,
        },
        "respondent": {
            "amount":       None,
            "actions":      [],
            "explanation":  None,
            "decision":     ProposalDecision.PENDING.value,
            "submitted_at": None,
            "decided_at":   None,
        },
        "ai_proposed_amount":          None,
        "ai_proposed_actions":         None,
        "ai_reasoning":                None,
        "settlement_candidate_amount": None,
        "settlement_candidate_reason": None,
        "proposal_issued_at":          None,
        "unresolved_proof_request_ids": [],
    }


def _ensure_negotiation_open(case: dict) -> dict:
    """Walk case from INVITE_SENT / RESPONDENT_VIEWED → NEGOTIATION_OPEN."""
    case_id = case["id"]
    status  = case["status"]

    if status == CaseStatus.INVITE_SENT.value:
        case = cosmos_service.transition_case(case_id, CaseStatus.RESPONDENT_VIEWED)
        status = case["status"]

    if status == CaseStatus.RESPONDENT_VIEWED.value:
        case = cosmos_service.transition_case(case_id, CaseStatus.NEGOTIATION_OPEN)

    return cosmos_service.get_case(case_id)


def _ensure_negotiation(case: dict) -> dict:
    """Create negotiation document if it does not exist yet."""
    neg = cosmos_service.get_negotiation_by_case(case["id"])
    if neg:
        return neg

    offer_type = (
        OfferType.ACTION_LIST.value
        if case.get("track") == "non_monetary"
        else OfferType.MONETARY.value
    )
    neg = cosmos_service.create_negotiation(
        case["id"],
        {
            "offer_type":       offer_type,
            "proof_requests":   [],
            "shared_notes":     [],
            "current_waiting_on": None,
        },
    )
    cosmos_service.update_case(case["id"], {"negotiation_id": neg["id"]})
    return neg


def _get_or_create_round(neg: dict, round_number: int) -> dict:
    """Fetch round by number; create it if missing."""
    existing = cosmos_service.get_round(neg["id"], round_number)
    if existing:
        return existing
    round_doc = _default_round(neg, round_number)
    cosmos_service.add_round_to_negotiation(neg["id"], round_doc)
    return round_doc


def _resolve_round_number(case: dict, requested: int | None) -> int:
    """Always derive round number from the case document, not the request body."""
    return case.get("current_round") or requested or 1


# ─────────────────────────────────────────────────────────────
# OFFER SUBMISSION (shared logic for claimant + respondent)
# ─────────────────────────────────────────────────────────────

async def _handle_offer_submission(
    case: dict,
    neg: dict,
    round_doc: dict,
    body: SubmitOfferRequest,
    party: str,         # "claimant" or "respondent"
    background_tasks: BackgroundTasks,
) -> dict:
    """
    Records offer from one party. If both parties have submitted, triggers
    AI mediation in a background task.

    EMAIL TRIGGERS:
      • After claimant submits → notify respondent to submit their offer
      • After respondent submits → notify claimant to submit their offer
      • When both submitted → AI mediation starts (no email here; proposal email
        is sent by _run_mediation once the AI proposes)
    """
    round_number = round_doc["round_number"]

    # Record this party's offer
    round_doc[party]["amount"]      = body.offer_amount
    round_doc[party]["actions"]     = body.demands or body.commitments or []
    round_doc[party]["explanation"] = body.explanation
    round_doc[party]["submitted_at"] = _now()

    cosmos_service.upsert_round_in_negotiation(neg["id"], round_number, round_doc)
    cosmos_service.update_case(case["id"], {"current_round": round_number})

    # Re-read to get latest state of both sides
    round_doc = cosmos_service.get_round(neg["id"], round_number)
    claimant_done   = bool(round_doc["claimant"]["submitted_at"])
    respondent_done = bool(round_doc["respondent"]["submitted_at"])

    if claimant_done and respondent_done:
        # Both offers in — trigger AI mediation
        cosmos_service.transition_case(
            case["id"],
            CaseStatus.MEDIATOR_REVIEW,
            {"current_round": round_number, "action_required_by": None},
        )
        background_tasks.add_task(_run_mediation, case["id"], neg["id"], round_number)
        return {
            "message":      "Both offers received. AI Mediator is generating a proposal.",
            "status":       CaseStatus.MEDIATOR_REVIEW.value,
            "round_number": round_number,
        }

    # Only one side submitted — notify the other party
    other = "respondent" if party == "claimant" else "claimant"
    waiting_status = (
        CaseStatus.WAITING_FOR_RESPONDENT
        if other == "respondent"
        else CaseStatus.WAITING_FOR_CLAIMANT
    )
    cosmos_service.transition_case(
        case["id"],
        waiting_status,
        {"current_round": round_number, "action_required_by": other},
    )
    cosmos_service.update_negotiation(neg["id"], {"current_waiting_on": other})

    # Send email to the other party telling them to submit
    if other == "respondent":
        # Claimant just submitted → email respondent
        email_service.send_case_update(
            to_email=case["respondent_email"],
            party_name=case["respondent_name"],
            case_id=case["id"],
            headline=f"Round {round_number}: Claimant has submitted their offer",
            summary=(
                f"{case['claimant_name']} has submitted their Round {round_number} offer. "
                "Please login to the respondent portal and submit your offer so the "
                "AI mediator can generate a settlement proposal."
            ),
            portal_url=_portal_url(case["id"]),
            action_label="Submit Your Offer",
        )
    else:
        # Respondent just submitted → email claimant
        email_service.send_case_update(
            to_email=case["claimant_email"],
            party_name=case["claimant_name"],
            case_id=case["id"],
            headline=f"Round {round_number}: Respondent has submitted their offer",
            summary=(
                f"{case['respondent_name']} has submitted their Round {round_number} offer. "
                "Please login and submit your Round {round_number} offer to trigger "
                "AI mediation."
            ),
            portal_url=settings.BASE_URL,
            action_label="Login and Submit Your Offer",
        )

    return {
        "message":      f"Offer submitted. Waiting for {other} to submit their offer.",
        "status":       waiting_status.value,
        "round_number": round_number,
    }


# ─────────────────────────────────────────────────────────────
# CLAIMANT OFFER
# ─────────────────────────────────────────────────────────────

@router.post("/submit-claimant-offer")
async def submit_claimant_offer(
    body: SubmitOfferRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
):
    case = cosmos_service.get_case(body.case_id)
    if not case:
        raise CaseNotFound(body.case_id)
    if case.get("claimant_email") != current_user.get("email"):
        raise UnauthorizedAccess()

    valid_states = {
        CaseStatus.ANALYZED.value,
        CaseStatus.INVITE_SENT.value,
        CaseStatus.RESPONDENT_VIEWED.value,
        CaseStatus.NEGOTIATION_OPEN.value,
        CaseStatus.WAITING_FOR_CLAIMANT.value,
    }
    if case["status"] not in valid_states:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot submit offer in state: {case['status']}",
        )

    case      = _ensure_negotiation_open(case)
    neg       = _ensure_negotiation(case)
    round_num = _resolve_round_number(case, body.round_number)
    round_doc = _get_or_create_round(neg, round_num)

    return await _handle_offer_submission(
        case, neg, round_doc, body, "claimant", background_tasks
    )


# ─────────────────────────────────────────────────────────────
# RESPONDENT OFFER
# ─────────────────────────────────────────────────────────────

@router.post("/submit-respondent-offer")
async def submit_respondent_offer(
    body: SubmitOfferRequest,
    background_tasks: BackgroundTasks,
):
    """No auth — respondent is verified by case email in the respondent router."""
    case = cosmos_service.get_case(body.case_id)
    if not case:
        raise CaseNotFound(body.case_id)

    valid_states = {
        CaseStatus.INVITE_SENT.value,
        CaseStatus.RESPONDENT_VIEWED.value,
        CaseStatus.NEGOTIATION_OPEN.value,
        CaseStatus.WAITING_FOR_RESPONDENT.value,
    }
    if case["status"] not in valid_states:
        raise HTTPException(
            status_code=409,
            detail=f"Case is not accepting respondent offers. Status: {case['status']}",
        )

    case      = _ensure_negotiation_open(case)
    neg       = _ensure_negotiation(case)
    round_num = _resolve_round_number(case, body.round_number)
    round_doc = _get_or_create_round(neg, round_num)

    return await _handle_offer_submission(
        case, neg, round_doc, body, "respondent", background_tasks
    )


# ─────────────────────────────────────────────────────────────
# AI MEDIATION BACKGROUND TASK
# ─────────────────────────────────────────────────────────────

async def _run_mediation(case_id: str, neg_id: str, round_number: int):
    """
    Runs the AI negotiation agent and issues a proposal.

    EMAIL: Sends proposal email to BOTH claimant and respondent.
    """
    try:
        from app.agents.negotiation_agent import run_negotiation_agent

        case      = cosmos_service.get_case(case_id)
        neg       = cosmos_service.negotiations.read_item(item=neg_id, partition_key=neg_id)
        round_doc = cosmos_service.get_round(neg_id, round_number)

        if not round_doc:
            logger.error(f"Mediation: round {round_number} not found | case_id={case_id}")
            return

        # Guard against duplicate mediation run (race condition)
        if round_doc.get("proposal_issued_at"):
            logger.warning(f"Mediation already ran for round {round_number} | case_id={case_id}")
            return

        claimant_offer   = round_doc["claimant"].get("amount") or round_doc["claimant"].get("actions")
        respondent_offer = round_doc["respondent"].get("amount") or round_doc["respondent"].get("actions")

        proposal = await run_negotiation_agent(
            case=case,
            negotiation=neg,
            round_number=round_number,
            claimant_offer=claimant_offer,
            respondent_offer=respondent_offer,
        )

        now = _now()
        cosmos_service.upsert_round_in_negotiation(neg_id, round_number, {
            **round_doc,
            "ai_proposed_amount":          proposal.get("proposed_amount"),
            "ai_proposed_actions":         proposal.get("proposed_actions"),
            "ai_reasoning":                proposal.get("reasoning"),
            "settlement_candidate_amount": proposal.get("proposed_amount"),
            "settlement_candidate_reason": proposal.get("reasoning"),
            "proposal_issued_at":          now,
        })

        cosmos_service.transition_case(
            case_id,
            CaseStatus.PROPOSAL_ISSUED,
            {"current_round": round_number, "action_required_by": None},
        )

        proposed_amount = proposal.get("proposed_amount", 0) or 0
        reasoning       = proposal.get("reasoning", "")
        portal          = _portal_url(case_id)

        # EMAIL both parties with the proposal
        for to_email, party_name in [
            (case["claimant_email"],   case["claimant_name"]),
            (case["respondent_email"], case["respondent_name"]),
        ]:
            email_service.send_proposal(
                to_email=to_email,
                party_name=party_name,
                case_id=case_id,
                round_num=round_number,
                proposed_amount=proposed_amount,
                reasoning=reasoning,
                portal_url=portal,
            )

        logger.info(
            f"Mediation complete | case_id={case_id} | "
            f"round={round_number} | proposed=Rs.{proposed_amount:,.0f}"
        )

    except Exception as e:
        logger.error(f"Mediation failed | case_id={case_id} | error={e}", exc_info=True)
        cosmos_service.update_case(case_id, {"mediation_error": str(e)})


# ─────────────────────────────────────────────────────────────
# PROPOSAL RESPONSE (Accept / Reject)
# ─────────────────────────────────────────────────────────────

@router.post("/proposal-response")
async def proposal_response(
    body: ProposalResponseRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user_optional),
):
    """
    Called by claimant (authenticated) or respondent (via respondent router, no auth).

    EMAIL:
      • Both accept  → settlement confirmation to BOTH parties
      • Any reject   → if more rounds left, next-round invite to BOTH parties
                       if max rounds hit, escalation notice to BOTH parties
    """
    case = cosmos_service.get_case(body.case_id)
    if not case:
        raise CaseNotFound(body.case_id)

    if case["status"] != CaseStatus.PROPOSAL_ISSUED.value:
        raise HTTPException(
            status_code=409,
            detail=f"No active proposal. Case status: {case['status']}",
        )

    # Auth: claimant must be logged in; respondent has no auth (party="respondent")
    if body.party == "claimant":
        if current_user and current_user["email"] != case["claimant_email"]:
            raise UnauthorizedAccess()
    elif body.party != "respondent":
        raise HTTPException(status_code=400, detail="party must be 'claimant' or 'respondent'")

    neg = cosmos_service.get_negotiation_by_case(body.case_id)
    if not neg:
        raise HTTPException(status_code=404, detail="Negotiation not found.")

    round_number = case.get("current_round", 1)
    round_doc    = cosmos_service.get_round(neg["id"], round_number)
    if not round_doc:
        raise HTTPException(status_code=404, detail=f"Round {round_number} not found.")

    # Record decision
    round_doc[body.party]["decision"]   = body.decision.value
    round_doc[body.party]["decided_at"] = _now()
    cosmos_service.upsert_round_in_negotiation(neg["id"], round_number, round_doc)

    cl_decision = round_doc["claimant"]["decision"]
    rs_decision = round_doc["respondent"]["decision"]

    logger.info(
        f"Proposal response | case_id={body.case_id} | party={body.party} | "
        f"decision={body.decision.value} | claimant={cl_decision} | respondent={rs_decision}"
    )

    # If both have decided
    if cl_decision != ProposalDecision.PENDING.value and rs_decision != ProposalDecision.PENDING.value:

        if (cl_decision == ProposalDecision.ACCEPT.value and
                rs_decision == ProposalDecision.ACCEPT.value):
            # BOTH ACCEPT → settle
            background_tasks.add_task(_handle_settlement, body.case_id)
            return {"message": "Both parties accepted. Generating settlement agreement.", "outcome": "SETTLED"}

        else:
            # At least one rejected
            max_rounds = case.get("max_rounds", 3)
            if round_number >= max_rounds:
                background_tasks.add_task(_handle_escalation, body.case_id)
                return {
                    "message": f"{max_rounds} rounds completed without settlement. Generating court file.",
                    "outcome": "ESCALATED",
                }
            else:
                next_round = round_number + 1
                background_tasks.add_task(_start_next_round, body.case_id, next_round)
                return {
                    "message":    f"Proposal rejected. Round {next_round} is now open.",
                    "outcome":    "NEXT_ROUND",
                    "next_round": next_round,
                }

    # Only one party decided so far
    waiting = "claimant" if cl_decision == ProposalDecision.PENDING.value else "respondent"
    waiting_status = (
        CaseStatus.WAITING_FOR_CLAIMANT
        if waiting == "claimant"
        else CaseStatus.WAITING_FOR_RESPONDENT
    )
    cosmos_service.transition_case(
        body.case_id,
        waiting_status,
        {"current_round": round_number, "action_required_by": waiting},
    )
    return {
        "message":      "Your decision recorded. Waiting for the other party.",
        "your_decision": body.decision.value,
    }


# ─────────────────────────────────────────────────────────────
# OUTCOME HANDLERS
# ─────────────────────────────────────────────────────────────

async def _handle_settlement(case_id: str):
    """
    Called when both parties accept a proposal.

    EMAIL: Settlement confirmation with download link to BOTH parties.
    """
    try:
        from app.agents.document_agent import generate_settlement_agreement

        case         = cosmos_service.get_case(case_id)
        neg          = cosmos_service.get_negotiation_by_case(case_id)
        round_number = case.get("current_round", 1)
        round_doc    = cosmos_service.get_round(neg["id"], round_number)
        settled_amount = (
            round_doc.get("settlement_candidate_amount") or
            round_doc.get("ai_proposed_amount") or 0
            if round_doc else 0
        )

        cosmos_service.transition_case(
            case_id,
            CaseStatus.SETTLING,
            {"settled_amount": settled_amount, "action_required_by": None},
        )

        settlement_url = await generate_settlement_agreement(case, settled_amount)

        cosmos_service.transition_case(
            case_id,
            CaseStatus.SETTLED,
            {
                "settlement_url":  settlement_url,
                "settled_amount":  settled_amount,
                "settled_at":      _now(),
                "action_required_by": None,
            },
        )

        # EMAIL both parties
        for to_email, party_name in [
            (case["claimant_email"],   case["claimant_name"]),
            (case["respondent_email"], case["respondent_name"]),
        ]:
            email_service.send_settlement_confirmation(
                to_email=to_email,
                party_name=party_name,
                case_id=case_id,
                settled_amount=settled_amount,
                download_url=settlement_url,
            )

        logger.info(f"Case settled | case_id={case_id} | amount=Rs.{settled_amount:,.0f}")

    except Exception as e:
        logger.error(f"Settlement handling failed | case_id={case_id} | error={e}", exc_info=True)
        cosmos_service.update_case(case_id, {"settlement_error": str(e), "settlement_error_at": _now()})


async def _handle_escalation(case_id: str):
    """
    Called when all rounds exhausted without settlement.

    EMAIL: Escalation notice with court file download to BOTH parties.
    """
    try:
        from app.agents.document_agent import _generate_mediation_certificate
        from app.services.blob_service import blob_service

        case = cosmos_service.get_case(case_id)
        cosmos_service.transition_case(case_id, CaseStatus.ESCALATING, {"action_required_by": None})

        # Generate mediation certificate
        cert_bytes = _generate_mediation_certificate(case)
        cert_blob  = f"mediation_cert_{case_id}.pdf"
        blob_service.upload("pdfs", cert_blob, cert_bytes)
        cert_url = blob_service.generate_download_url("pdfs", cert_blob)

        # Use court file if already generated, else use cert
        docs_data = case.get("documents_data") or {}
        court_url = docs_data.get("court_file_url") or cert_url

        cosmos_service.transition_case(
            case_id,
            CaseStatus.ESCALATED,
            {"mediation_certificate_url": cert_url, "escalated_at": _now(), "action_required_by": None},
        )

        # EMAIL both parties
        for to_email, party_name in [
            (case["claimant_email"],   case["claimant_name"]),
            (case["respondent_email"], case["respondent_name"]),
        ]:
            email_service.send_escalation_notice(
                to_email=to_email,
                party_name=party_name,
                case_id=case_id,
                download_url=court_url,
            )

        logger.info(f"Case escalated | case_id={case_id}")

    except Exception as e:
        logger.error(f"Escalation handling failed | case_id={case_id} | error={e}", exc_info=True)
        cosmos_service.update_case(case_id, {"escalation_error": str(e), "escalation_error_at": _now()})


async def _start_next_round(case_id: str, next_round_number: int):
    """
    Opens the next negotiation round.

    EMAIL: Next-round invite to BOTH parties.
    """
    try:
        case = cosmos_service.get_case(case_id)
        neg  = cosmos_service.get_negotiation_by_case(case_id)

        if neg:
            # Pre-create the next round document
            if not cosmos_service.get_round(neg["id"], next_round_number):
                cosmos_service.add_round_to_negotiation(
                    neg["id"], _default_round(neg, next_round_number)
                )
            cosmos_service.update_negotiation(neg["id"], {"current_waiting_on": None})

        cosmos_service.transition_case(
            case_id,
            CaseStatus.NEGOTIATION_OPEN,
            {"current_round": next_round_number, "action_required_by": None},
        )

        portal = _portal_url(case_id)

        # EMAIL both parties
        for to_email, party_name in [
            (case["claimant_email"],   case["claimant_name"]),
            (case["respondent_email"], case["respondent_name"]),
        ]:
            email_service.send_next_round_invite(
                to_email=to_email,
                party_name=party_name,
                case_id=case_id,
                round_num=next_round_number,
                portal_url=portal,
            )

        logger.info(f"Next round started | case_id={case_id} | round={next_round_number}")

    except Exception as e:
        logger.error(f"Next round start failed | case_id={case_id} | error={e}", exc_info=True)
        cosmos_service.update_case(case_id, {"next_round_error": str(e), "next_round_error_at": _now()})


# ─────────────────────────────────────────────────────────────
# PROOF RESPONSE
# ─────────────────────────────────────────────────────────────

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

    proof_item = next(
        (item for item in neg.get("proof_requests", []) if item.get("id") == body.request_id),
        None,
    )
    if not proof_item:
        raise HTTPException(status_code=404, detail="Proof request not found.")
    if proof_item.get("requested_from") != body.party:
        raise HTTPException(status_code=403, detail="This proof request is not assigned to your side.")

    cosmos_service.update_proof_request(
        neg["id"],
        body.request_id,
        {
            "status":        "RESPONDED",
            "response_text": body.response_text.strip(),
            "file_refs":     body.file_refs or [],
            "response_at":   _now(),
        },
    )

    cosmos_service.append_shared_note(
        neg["id"],
        {
            "id":           _new_id("note"),
            "round_number": body.round_number,
            "party":        body.party,
            "note_type":    "proof_response",
            "text":         body.response_text.strip(),
            "created_at":   _now(),
        },
    )

    # Re-check pending proof requests for this round
    refreshed_neg = cosmos_service.get_negotiation_by_case(body.case_id)
    round_doc     = cosmos_service.get_round(refreshed_neg["id"], body.round_number)
    pending = [
        item for item in refreshed_neg.get("proof_requests", [])
        if item.get("round_number") == body.round_number
        and item.get("status") == "PENDING"
    ]

    if round_doc:
        round_doc["unresolved_proof_request_ids"] = [item["id"] for item in pending]
        cosmos_service.upsert_round_in_negotiation(
            refreshed_neg["id"], body.round_number, round_doc
        )

    claimant_done   = bool((round_doc or {}).get("claimant", {}).get("submitted_at"))
    respondent_done = bool((round_doc or {}).get("respondent", {}).get("submitted_at"))

    if pending:
        waiting        = pending[0]["requested_from"]
        waiting_status = CaseStatus.PROOF_REQUESTED
    elif claimant_done and respondent_done:
        waiting        = None
        waiting_status = CaseStatus.MEDIATOR_REVIEW
    elif claimant_done:
        waiting        = "respondent"
        waiting_status = CaseStatus.WAITING_FOR_RESPONDENT
    elif respondent_done:
        waiting        = "claimant"
        waiting_status = CaseStatus.WAITING_FOR_CLAIMANT
    else:
        waiting        = None
        waiting_status = CaseStatus.NEGOTIATION_OPEN

    cosmos_service.transition_case(
        body.case_id,
        waiting_status,
        {"current_round": body.round_number, "action_required_by": waiting},
    )
    cosmos_service.update_negotiation(refreshed_neg["id"], {"current_waiting_on": waiting})

    return {
        "message":          "Proof response recorded and shared with the other party.",
        "status":           waiting_status.value,
        "action_required_by": waiting,
    }


# ─────────────────────────────────────────────────────────────
# NEGOTIATION STATUS
# ─────────────────────────────────────────────────────────────

@router.get("/status/{case_id}")
async def get_negotiation_status(
    case_id: str,
    current_user: dict = Depends(get_current_user_optional),
):
    case = cosmos_service.get_case(case_id)
    if not case:
        raise CaseNotFound(case_id)

    # Claimant gets full view; respondent-side access uses the respondent router
    if current_user and current_user.get("email") != case.get("claimant_email"):
        raise UnauthorizedAccess()

    neg          = cosmos_service.get_negotiation_by_case(case_id)
    round_number = case.get("current_round", 0)
    round_doc    = (
        cosmos_service.get_round(neg["id"], round_number)
        if neg and round_number > 0
        else None
    )

    current_round_detail = None
    if round_doc:
        cl = round_doc.get("claimant") or {}
        rs = round_doc.get("respondent") or {}
        current_round_detail = {
            "claimant_submitted":   bool(cl.get("submitted_at")),
            "respondent_submitted": bool(rs.get("submitted_at")),
            "proposal_issued":      bool(round_doc.get("proposal_issued_at")),
            "proposed_amount":      round_doc.get("settlement_candidate_amount") or round_doc.get("ai_proposed_amount"),
            "proposed_actions":     round_doc.get("ai_proposed_actions"),
            "ai_reasoning":         round_doc.get("ai_reasoning"),
            "claimant_decision":    cl.get("decision"),
            "respondent_decision":  rs.get("decision"),
            "claimant_offer":       cl.get("amount"),
            "respondent_offer":     rs.get("amount"),
        }

    return {
        "case_id":       case_id,
        "status":        case["status"],
        "current_round": round_number,
        "max_rounds":    case.get("max_rounds", 3),
        "track":         case.get("track"),
        "action_required_by": case.get("action_required_by"),
        "settlement_url":     case.get("settlement_url"),
        "insights":           _build_insights(case),
        "negotiation": {
            "id":                neg["id"] if neg else None,
            "offer_type":        neg.get("offer_type") if neg else None,
            "rounds_done":       len(neg.get("rounds", [])) if neg else 0,
            "current_waiting_on": neg.get("current_waiting_on") if neg else None,
            "rounds":            neg.get("rounds", []) if neg else [],
            "proof_requests":    neg.get("proof_requests", []) if neg else [],
            "shared_notes":      neg.get("shared_notes", []) if neg else [],
        },
        "current_round_detail": current_round_detail,
    }
