import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.models.case import CaseStatus
from app.services.cosmos_service import cosmos_service
from app.core.exceptions import CaseNotFound

router = APIRouter()
logger = logging.getLogger(__name__)


# ── Request Models ────────────────────────────────────────────

class RespondentVerify(BaseModel):
    case_id: str
    email:   str


class RespondentOfferSubmit(BaseModel):
    case_id:     str
    email:       str
    offer_amount: float | None = None        # monetary
    commitments:  list[str] | None = None    # non-monetary


class RespondentDecision(BaseModel):
    case_id:  str
    email:    str
    decision: str   # "ACCEPT" or "REJECT"


class RespondentCounterClaim(BaseModel):
    case_id:        str
    email:          str
    counter_claim:  str
    counter_amount: float | None = None


# ══════════════════════════════════════════════════════════════
# GET CASE — RESPONDENT VIEW
# ══════════════════════════════════════════════════════════════

@router.get("/case/{case_id}")
async def get_respondent_case(case_id: str, email: str):
    """
    Returns filtered case view for respondent.
    No auth token needed — respondent verifies via email parameter.
    Analytics data hidden — respondent never sees win probability or ZOPA.
    """
    case = cosmos_service.get_case(case_id)
    if not case:
        raise CaseNotFound(case_id)

    # Verify email matches respondent
    if case["respondent_email"].lower() != email.lower():
        raise HTTPException(
            status_code=403,
            detail="Email does not match case records.",
        )

    # Mark case as respondent viewed if still INVITE_SENT
    if case["status"] == CaseStatus.INVITE_SENT.value:
        cosmos_service.transition_case(case_id, CaseStatus.RESPONDENT_VIEWED)
        case = cosmos_service.get_case(case_id)

    # Get filtered view — no analytics, no win probability
    respondent_view = cosmos_service.get_case_for_respondent(case_id)

    # Get current negotiation state
    neg          = cosmos_service.get_negotiation_by_case(case_id)
    round_number = case.get("current_round", 0)
    current_round = None

    if neg and round_number > 0:
        current_round = cosmos_service.get_round(neg["id"], round_number)

    return {
        "case":    respondent_view,
        "status":  case["status"],
        "track":   case.get("track"),
        "dispute_summary": {
            "claimant_name":  case["claimant_name"],
            "claim_amount":   case.get("claim_amount"),
            "currency":       case.get("currency", "INR"),
            "dispute_type":   (case.get("intake_data") or {}).get("dispute_type"),
            "severity":       (case.get("intake_data") or {}).get("severity"),
            "key_issues":     (case.get("intake_data") or {}).get("key_issues", []),
        },
        "legal_summary": {
            "applicable_laws_count": len(
                (case.get("legal_data") or {}).get("applicable_laws", [])
            ),
            "forum":         (case.get("legal_data") or {}).get("forum_name"),
            "claimant_rights": (case.get("legal_data") or {}).get("claimant_rights", []),
            # Respondent sees their likely defenses (fair — they need to prepare)
            "respondent_defenses": (case.get("legal_data") or {}).get("respondent_defenses", []),
        },
        "negotiation": {
            "current_round":   round_number,
            "max_rounds":      case.get("max_rounds", 3),
            "respondent_submitted_this_round": (
                current_round.get("respondent_offer") is not None or
                bool(current_round.get("respondent_commitments"))
            ) if current_round else False,
            "proposal_pending": bool(
                current_round and
                (current_round.get("ai_proposed_amount") or
                 current_round.get("ai_proposed_actions")) and
                current_round.get("respondent_decision") == "PENDING"
            ),
            "ai_proposed_amount": (
                current_round.get("ai_proposed_amount") if current_round else None
            ),
            "ai_reasoning": (
                current_round.get("ai_reasoning") if current_round else None
            ),
            "respondent_decision": (
                current_round.get("respondent_decision") if current_round else None
            ),
        } if current_round else None,
    }


# ══════════════════════════════════════════════════════════════
# RESPONDENT FULL ACCEPT (before negotiation starts)
# ══════════════════════════════════════════════════════════════

@router.post("/accept-in-full")
async def accept_in_full(body: RespondentVerify):
    """
    Respondent agrees to pay the full claimed amount before any negotiation.
    Skips negotiation entirely → immediate settlement.
    """
    case = cosmos_service.get_case(body.case_id)
    if not case:
        raise CaseNotFound(body.case_id)

    if case["respondent_email"].lower() != body.email.lower():
        raise HTTPException(status_code=403, detail="Email mismatch.")

    if case["status"] not in [
        CaseStatus.RESPONDENT_VIEWED.value,
        CaseStatus.INVITE_SENT.value,
        CaseStatus.ANALYZED.value,
    ]:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot accept in full at this stage. Status: {case['status']}",
        )

    settled_amount = case.get("claim_amount", 0) or 0

    # Create a one-round negotiation record for audit trail
    from app.models.negotiation import ProposalDecision
    neg = cosmos_service.create_negotiation(body.case_id, {
        "offer_type": "monetary",
        "full_acceptance": True,
    })
    cosmos_service.add_round_to_negotiation(neg["id"], {
        "round_number":      1,
        "offer_type":        "monetary",
        "claimant_offer":    settled_amount,
        "respondent_offer":  settled_amount,
        "ai_proposed_amount": settled_amount,
        "claimant_decision":  ProposalDecision.ACCEPT.value,
        "respondent_decision": ProposalDecision.ACCEPT.value,
        "ai_reasoning":      "Respondent accepted the full claimed amount.",
    })

    # Handle settlement immediately
    from app.routers.negotiation import _handle_settlement
    cosmos_service.transition_case(body.case_id, CaseStatus.NEGOTIATING)
    cosmos_service.update_case(body.case_id, {
        "current_round":  1,
        "negotiation_id": neg["id"],
    })

    import asyncio
    asyncio.create_task(_handle_settlement(body.case_id))

    return {
        "message":        f"You have accepted the full amount of Rs. {settled_amount:,.0f}. Settlement agreement is being generated.",
        "settled_amount": settled_amount,
        "outcome":        "SETTLED",
    }


# ══════════════════════════════════════════════════════════════
# RESPONDENT DISPUTES FACTS
# ══════════════════════════════════════════════════════════════

@router.post("/dispute-facts")
async def dispute_facts(body: RespondentCounterClaim):
    """
    Respondent adds their version of facts to the case record.
    This is NOT a counter-claim — it adds context for AI agents.
    The respondent's version is stored and included in court file.
    """
    case = cosmos_service.get_case(body.case_id)
    if not case:
        raise CaseNotFound(body.case_id)

    if case["respondent_email"].lower() != body.email.lower():
        raise HTTPException(status_code=403, detail="Email mismatch.")

    cosmos_service.update_case(body.case_id, {
        "respondent_version":       body.counter_claim,
        "respondent_version_at":    __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat(),
        "respondent_counter_amount": body.counter_amount,
    })

    return {
        "message": "Your version of events has been recorded and will be included in the case file.",
    }


# ══════════════════════════════════════════════════════════════
# RESPONDENT DECLINES TO PARTICIPATE
# ══════════════════════════════════════════════════════════════

@router.post("/decline")
async def decline_participation(body: RespondentVerify):
    """
    Respondent formally declines to participate in mediation.
    Triggers auto-escalation with non-participation noted in court file.
    """
    case = cosmos_service.get_case(body.case_id)
    if not case:
        raise CaseNotFound(body.case_id)

    if case["respondent_email"].lower() != body.email.lower():
        raise HTTPException(status_code=403, detail="Email mismatch.")

    cosmos_service.update_case(body.case_id, {
        "respondent_declined":    True,
        "respondent_declined_at": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat(),
    })

    cosmos_service.transition_case(body.case_id, CaseStatus.AUTO_ESCALATED)

    # Generate court file noting non-participation
    from app.agents.document_agent import _generate_court_file
    from app.services.blob_service import blob_service

    async def _gen():
        case_fresh = cosmos_service.get_case(body.case_id)
        cf_bytes = await _generate_court_file(
            case_fresh,
            case_fresh.get("intake_data", {}),
            case_fresh.get("legal_data", {}),
            case_fresh.get("analytics_data", {}),
        )
        blob_name = f"court_file_autodeclined_{body.case_id}.pdf"
        blob_service.upload("pdfs", blob_name, cf_bytes)
        url = blob_service.generate_download_url("pdfs", blob_name)

        from app.services.email_service import email_service
        email_service.send_escalation_notice(
            to_email=case["claimant_email"],
            party_name=case["claimant_name"],
            case_id=body.case_id,
            download_url=url,
        )

    import asyncio
    asyncio.create_task(_gen())

    return {
        "message": (
            "Your decision to decline has been recorded. The claimant will be "
            "notified and a court-ready case file noting your non-participation "
            "will be generated automatically."
        ),
    }


# ══════════════════════════════════════════════════════════════
# PROPOSAL RESPONSE (ACCEPT / REJECT)
# ══════════════════════════════════════════════════════════════

@router.post("/proposal-response")
async def respondent_proposal_response(
    body: RespondentDecision,
    background_tasks: __import__("fastapi").BackgroundTasks,
):
    """
    Respondent accepts or rejects the AI proposal.
    Delegates to the negotiation router's proposal-response endpoint.
    """
    from app.models.negotiation import ProposalDecision, ProposalResponseRequest
    from app.routers.negotiation import proposal_response

    case = cosmos_service.get_case(body.case_id)
    if not case:
        raise CaseNotFound(body.case_id)

    if case["respondent_email"].lower() != body.email.lower():
        raise HTTPException(status_code=403, detail="Email mismatch.")

    try:
        decision = ProposalDecision(body.decision)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="decision must be 'ACCEPT' or 'REJECT'",
        )

    request = ProposalResponseRequest(
        case_id=body.case_id,
        round_number=case.get("current_round", 1),
        decision=decision,
        party="respondent",
    )

    return await proposal_response(request, background_tasks, current_user=None)