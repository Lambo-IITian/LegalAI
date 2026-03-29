import logging
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

from app.core.exceptions import CaseNotFound
from app.models.case import CaseStatus
from app.models.negotiation import ProofResponseRequest, ProposalDecision, ProposalResponseRequest
from app.routers.negotiation import _build_insights, proposal_response, proof_response
from app.services.cosmos_service import cosmos_service

router = APIRouter()
logger = logging.getLogger(__name__)


class RespondentVerify(BaseModel):
    case_id: str
    email: str


class RespondentDecision(BaseModel):
    case_id: str
    email: str
    decision: str
    reason: str | None = None


class RespondentCounterClaim(BaseModel):
    case_id: str
    email: str
    counter_claim: str = Field(..., min_length=5, max_length=3000)
    counter_amount: float | None = None


class RespondentProofResponse(BaseModel):
    case_id: str
    email: str
    round_number: int
    request_id: str
    response_text: str = Field(..., min_length=5, max_length=3000)
    file_refs: list[str] = []


def _verify_case_email(case_id: str, email: str) -> dict:
    case = cosmos_service.get_case(case_id)
    if not case:
        raise CaseNotFound(case_id)
    if case["respondent_email"].lower() != email.lower():
        raise HTTPException(status_code=403, detail="Email does not match case records.")
    return case


@router.get("/case/{case_id}")
async def get_respondent_case(case_id: str, email: str):
    case = _verify_case_email(case_id, email)

    if case["status"] == CaseStatus.INVITE_SENT.value:
        cosmos_service.transition_case(case_id, CaseStatus.RESPONDENT_VIEWED)
        case = cosmos_service.get_case(case_id)

    respondent_view = cosmos_service.get_case_for_respondent(case_id)
    neg = cosmos_service.get_negotiation_by_case(case_id)
    round_number = case.get("current_round", 0)
    current_round = cosmos_service.get_round(neg["id"], round_number) if neg and round_number > 0 else None

    dispute_summary = {
        "claimant_name": case["claimant_name"],
        "claim_amount": case.get("claim_amount"),
        "currency": case.get("currency", "INR"),
        "dispute_type": (case.get("intake_data") or {}).get("dispute_type"),
        "severity": (case.get("intake_data") or {}).get("severity"),
        "key_issues": (case.get("intake_data") or {}).get("key_issues", []),
    }
    legal_summary = {
        "applicable_laws_count": len((case.get("legal_data") or {}).get("applicable_laws", [])),
        "forum": (case.get("legal_data") or {}).get("forum_name"),
        "claimant_rights": (case.get("legal_data") or {}).get("claimant_rights", []),
        "respondent_defenses": (case.get("legal_data") or {}).get("respondent_defenses", []),
    }

    return {
        "case": respondent_view,
        "status": case["status"],
        "track": case.get("track"),
        "dispute_summary": dispute_summary,
        "legal_summary": legal_summary,
        "insights": _build_insights(case),
        "negotiation": {
            "current_round": round_number,
            "max_rounds": case.get("max_rounds", 3),
            "current_waiting_on": neg.get("current_waiting_on") if neg else None,
            "respondent_submitted_this_round": bool((current_round or {}).get("respondent", {}).get("submitted_at")),
            "proposal_pending": bool(
                current_round
                and (current_round.get("ai_proposed_amount") or current_round.get("ai_proposed_actions"))
                and (current_round.get("respondent") or {}).get("decision") == ProposalDecision.PENDING.value
            ),
            "ai_proposed_amount": current_round.get("ai_proposed_amount") if current_round else None,
            "ai_reasoning": current_round.get("ai_reasoning") if current_round else None,
            "respondent_decision": (current_round.get("respondent") or {}).get("decision") if current_round else None,
            "proof_requests": neg.get("proof_requests", []) if neg else [],
            "shared_notes": neg.get("shared_notes", []) if neg else [],
            "rounds": neg.get("rounds", []) if neg else [],
        } if neg else None,
    }


@router.post("/accept-in-full")
async def accept_in_full(body: RespondentVerify):
    case = _verify_case_email(body.case_id, body.email)
    if case["status"] not in [CaseStatus.RESPONDENT_VIEWED.value, CaseStatus.INVITE_SENT.value, CaseStatus.ANALYZED.value]:
        raise HTTPException(status_code=409, detail=f"Cannot accept in full at this stage. Status: {case['status']}")

    settled_amount = case.get("claim_amount", 0) or 0
    from app.models.negotiation import ProposalDecision
    neg = cosmos_service.create_negotiation(body.case_id, {"offer_type": "monetary", "full_acceptance": True, "proof_requests": [], "shared_notes": []})
    cosmos_service.add_round_to_negotiation(
        neg["id"],
        {
            "round_number": 1,
            "offer_type": "monetary",
            "claimant": {"amount": settled_amount, "actions": [], "decision": ProposalDecision.ACCEPT.value, "submitted_at": datetime.now(timezone.utc).isoformat()},
            "respondent": {"amount": settled_amount, "actions": [], "decision": ProposalDecision.ACCEPT.value, "submitted_at": datetime.now(timezone.utc).isoformat()},
            "ai_proposed_amount": settled_amount,
            "ai_reasoning": "Respondent accepted the full claimed amount.",
            "proposal_issued_at": datetime.now(timezone.utc).isoformat(),
            "unresolved_proof_request_ids": [],
            "settlement_candidate_amount": settled_amount,
            "settlement_candidate_reason": "Respondent accepted the full claim.",
        },
    )

    from app.routers.negotiation import _handle_settlement
    cosmos_service.update_case(body.case_id, {"current_round": 1, "negotiation_id": neg["id"], "action_required_by": None})
    if case["status"] == CaseStatus.INVITE_SENT.value:
        cosmos_service.transition_case(body.case_id, CaseStatus.RESPONDENT_VIEWED)
    if cosmos_service.get_case(body.case_id)["status"] == CaseStatus.RESPONDENT_VIEWED.value:
        cosmos_service.transition_case(body.case_id, CaseStatus.NEGOTIATION_OPEN)

    import asyncio
    asyncio.create_task(_handle_settlement(body.case_id))
    return {"message": f"You have accepted the full amount of Rs. {settled_amount:,.0f}. Settlement agreement is being generated.", "settled_amount": settled_amount, "outcome": "SETTLED"}


@router.post("/dispute-facts")
async def dispute_facts(body: RespondentCounterClaim):
    _verify_case_email(body.case_id, body.email)
    cosmos_service.update_case(
        body.case_id,
        {
            "respondent_version": body.counter_claim,
            "respondent_version_at": datetime.now(timezone.utc).isoformat(),
            "respondent_counter_amount": body.counter_amount,
        },
    )
    return {"message": "Your version of events has been recorded and will be visible in negotiation and included in the case file."}


@router.post("/decline")
async def decline_participation(body: RespondentVerify):
    case = _verify_case_email(body.case_id, body.email)
    cosmos_service.update_case(
        body.case_id,
        {"respondent_declined": True, "respondent_declined_at": datetime.now(timezone.utc).isoformat()},
    )
    cosmos_service.transition_case(body.case_id, CaseStatus.AUTO_ESCALATED)

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
    return {"message": "Your decision to decline has been recorded. The claimant will be notified and a court-ready case file noting your non-participation will be generated automatically."}


@router.post("/proposal-response")
async def respondent_proposal_response(body: RespondentDecision, background_tasks: BackgroundTasks):
    case = _verify_case_email(body.case_id, body.email)
    try:
        decision = ProposalDecision(body.decision)
    except ValueError:
        raise HTTPException(status_code=400, detail="decision must be 'ACCEPT' or 'REJECT'")

    request = ProposalResponseRequest(
        case_id=body.case_id,
        round_number=case.get("current_round", 1),
        decision=decision,
        party="respondent",
        reason=body.reason,
    )
    return await proposal_response(request, background_tasks, current_user=None)


@router.post("/proof-response")
async def respondent_proof_response(body: RespondentProofResponse):
    _verify_case_email(body.case_id, body.email)
    request = ProofResponseRequest(
        case_id=body.case_id,
        round_number=body.round_number,
        party="respondent",
        request_id=body.request_id,
        response_text=body.response_text,
        file_refs=body.file_refs,
    )
    return await proof_response(request, current_user=None)
