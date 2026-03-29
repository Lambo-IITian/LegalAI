import logging
import os
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

from app.config import settings
from app.core.exceptions import CaseNotFound
from app.models.case import CaseStatus
from app.models.negotiation import ProofResponseRequest, ProposalDecision, ProposalResponseRequest
from app.services.blob_service import blob_service
from app.services.cosmos_service import cosmos_service
from app.services.email_service import email_service

router = APIRouter()
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# REQUEST MODELS
# ─────────────────────────────────────────────────────────────

class RespondentVerify(BaseModel):
    case_id: str
    email:   str


class RespondentDecision(BaseModel):
    case_id:  str
    email:    str
    decision: str
    reason:   str | None = None


class RespondentCounterClaim(BaseModel):
    case_id:        str
    email:          str
    counter_claim:  str = Field(..., min_length=5, max_length=3000)
    counter_amount: float | None = None


class RespondentProofResponse(BaseModel):
    case_id:       str
    email:         str
    round_number:  int
    request_id:    str
    response_text: str = Field(..., min_length=5, max_length=3000)
    file_refs:     list[str] = []


class RespondentEvidenceUpload(BaseModel):
    case_id:      str
    email:        str
    filename:     str
    content_type: str = "application/octet-stream"
    base64_data:  str


# ─────────────────────────────────────────────────────────────
# HELPER
# ─────────────────────────────────────────────────────────────

def _verify_respondent(case_id: str, email: str) -> dict:
    """Load case and verify the email belongs to the respondent."""
    case = cosmos_service.get_case(case_id)
    if not case:
        raise CaseNotFound(case_id)
    if case["respondent_email"].lower() != email.lower():
        raise HTTPException(status_code=403, detail="Email does not match case records.")
    return case


# ─────────────────────────────────────────────────────────────
# GET CASE (RESPONDENT VIEW)
# ─────────────────────────────────────────────────────────────

@router.get("/case/{case_id}")
async def get_respondent_case(case_id: str, email: str):
    """
    Filtered case view for respondent — analytics/ZOPA always hidden.

    EMAIL: None (view only — no email triggered here).
    SIDE EFFECT: Transitions INVITE_SENT → RESPONDENT_VIEWED on first open.
    """
    case = _verify_respondent(case_id, email)

    if case["status"] == CaseStatus.INVITE_SENT.value:
        cosmos_service.transition_case(case_id, CaseStatus.RESPONDENT_VIEWED)
        case = cosmos_service.get_case(case_id)

    respondent_view = cosmos_service.get_case_for_respondent(case_id)
    neg             = cosmos_service.get_negotiation_by_case(case_id)
    round_number    = case.get("current_round", 0)
    current_round   = (
        cosmos_service.get_round(neg["id"], round_number)
        if neg and round_number > 0
        else None
    )

    proposal_issued = bool(
        current_round and (
            current_round.get("settlement_candidate_amount") or
            current_round.get("ai_proposed_amount")
        )
    )

    return {
        "case":   respondent_view,
        "status": case["status"],
        "track":  case.get("track"),
        "dispute_summary": {
            "claimant_name": case["claimant_name"],
            "claim_amount":  case.get("claim_amount"),
            "currency":      case.get("currency", "INR"),
            "dispute_type":  (case.get("intake_data") or {}).get("dispute_type"),
            "severity":      (case.get("intake_data") or {}).get("severity"),
            "key_issues":    (case.get("intake_data") or {}).get("key_issues", []),
        },
        "legal_summary": {
            "applicable_laws_count": len((case.get("legal_data") or {}).get("applicable_laws", [])),
            "forum":                 (case.get("legal_data") or {}).get("forum_name"),
            "respondent_defenses":   (case.get("legal_data") or {}).get("respondent_defenses", []),
        },
        "negotiation": {
            "current_round":               round_number,
            "max_rounds":                  case.get("max_rounds", 3),
            "claimant_submitted":          bool((current_round or {}).get("claimant", {}).get("submitted_at")),
            "respondent_submitted":        bool((current_round or {}).get("respondent", {}).get("submitted_at")),
            "proposal_pending": (
                proposal_issued and
                (current_round or {}).get("respondent", {}).get("decision") == ProposalDecision.PENDING.value
            ),
            # Only show AI proposal after it has been issued
            "ai_proposed_amount":  (
                current_round.get("settlement_candidate_amount") or current_round.get("ai_proposed_amount")
                if proposal_issued else None
            ),
            "ai_reasoning": current_round.get("ai_reasoning") if proposal_issued else None,
            "respondent_decision": (current_round or {}).get("respondent", {}).get("decision"),
            "proof_requests": neg.get("proof_requests", []) if neg else [],
            "shared_notes":   neg.get("shared_notes", []) if neg else [],
        } if neg is not None or round_number == 0 else None,
    }


# ─────────────────────────────────────────────────────────────
# ACCEPT IN FULL
# ─────────────────────────────────────────────────────────────

@router.post("/accept-in-full")
async def accept_in_full(body: RespondentVerify, background_tasks: BackgroundTasks):
    """
    Respondent accepts the claimant's full claimed amount without negotiation.

    EMAIL: Handled by _handle_settlement (settlement confirmation to both parties).
    """
    case = _verify_respondent(body.case_id, body.email)

    valid = {
        CaseStatus.INVITE_SENT.value,
        CaseStatus.RESPONDENT_VIEWED.value,
        CaseStatus.NEGOTIATION_OPEN.value,
    }
    if case["status"] not in valid:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot accept in full at this stage. Status: {case['status']}",
        )

    settled_amount = case.get("claim_amount", 0) or 0
    now = datetime.now(timezone.utc).isoformat()

    # Create negotiation + round 1 with full acceptance
    neg = cosmos_service.create_negotiation(body.case_id, {
        "offer_type":       "monetary",
        "full_acceptance":  True,
        "proof_requests":   [],
        "shared_notes":     [],
        "current_waiting_on": None,
    })
    cosmos_service.add_round_to_negotiation(neg["id"], {
        "round_number":                1,
        "offer_type":                  "monetary",
        "claimant": {
            "amount": settled_amount, "actions": [], "explanation": None,
            "decision": ProposalDecision.ACCEPT.value,
            "submitted_at": now, "decided_at": now,
        },
        "respondent": {
            "amount": settled_amount, "actions": [], "explanation": None,
            "decision": ProposalDecision.ACCEPT.value,
            "submitted_at": now, "decided_at": now,
        },
        "ai_proposed_amount":          settled_amount,
        "ai_reasoning":                "Respondent accepted the full claimed amount.",
        "settlement_candidate_amount": settled_amount,
        "settlement_candidate_reason": "Respondent accepted the full claim.",
        "proposal_issued_at":          now,
        "unresolved_proof_request_ids": [],
    })
    cosmos_service.update_case(body.case_id, {
        "current_round":  1,
        "negotiation_id": neg["id"],
        "action_required_by": None,
    })

    # Walk states to NEGOTIATION_OPEN before settlement handler runs
    current_status = cosmos_service.get_case(body.case_id)["status"]
    if current_status == CaseStatus.INVITE_SENT.value:
        cosmos_service.transition_case(body.case_id, CaseStatus.RESPONDENT_VIEWED)
        current_status = CaseStatus.RESPONDENT_VIEWED.value
    if current_status == CaseStatus.RESPONDENT_VIEWED.value:
        cosmos_service.transition_case(body.case_id, CaseStatus.NEGOTIATION_OPEN)

    # Trigger settlement in background (generates PDF + emails both parties)
    from app.routers.negotiation import _handle_settlement
    background_tasks.add_task(_handle_settlement, body.case_id)

    return {
        "message":        f"You have accepted Rs. {settled_amount:,.0f}. Settlement agreement is being generated.",
        "settled_amount": settled_amount,
        "outcome":        "SETTLED",
    }


# ─────────────────────────────────────────────────────────────
# DISPUTE FACTS (counter-narrative)
# ─────────────────────────────────────────────────────────────

@router.post("/dispute-facts")
async def dispute_facts(body: RespondentCounterClaim):
    """
    Respondent records their version of events.
    Included in the case file; visible to both parties in negotiation.
    No email triggered.
    """
    _verify_respondent(body.case_id, body.email)
    cosmos_service.update_case(body.case_id, {
        "respondent_version":        body.counter_claim,
        "respondent_version_at":     datetime.now(timezone.utc).isoformat(),
        "respondent_counter_amount": body.counter_amount,
    })
    return {"message": "Your version of events has been recorded and will be visible in negotiation and included in the case file."}


# ─────────────────────────────────────────────────────────────
# DECLINE PARTICIPATION
# ─────────────────────────────────────────────────────────────

@router.post("/decline")
async def decline_participation(body: RespondentVerify, background_tasks: BackgroundTasks):
    """
    Respondent formally declines to participate.
    Case auto-escalates immediately.

    EMAIL: Claimant receives escalation notice with court file.
    """
    case = _verify_respondent(body.case_id, body.email)

    cosmos_service.update_case(body.case_id, {
        "respondent_declined":    True,
        "respondent_declined_at": datetime.now(timezone.utc).isoformat(),
    })

    # Walk to RESPONDENT_VIEWED first if needed (AUTO_ESCALATED is only
    # reachable from INVITE_SENT or RESPONDENT_VIEWED)
    current_status = case["status"]
    if current_status == CaseStatus.INVITE_SENT.value:
        cosmos_service.transition_case(body.case_id, CaseStatus.RESPONDENT_VIEWED)

    cosmos_service.transition_case(body.case_id, CaseStatus.AUTO_ESCALATED)

    background_tasks.add_task(_generate_declined_court_file, body.case_id, case)

    return {
        "message": (
            "Your decision to decline has been recorded. The claimant will be notified "
            "and a court-ready case file noting your non-participation will be generated."
        )
    }


async def _generate_declined_court_file(case_id: str, case: dict):
    """
    Generates court file when respondent declines.
    EMAIL: Claimant receives escalation notice.
    """
    try:
        from app.agents.document_agent import _generate_court_file

        intake    = case.get("intake_data", {}) or {}
        legal     = case.get("legal_data", {}) or {}
        analytics = case.get("analytics_data", {}) or {}

        cf_bytes  = await _generate_court_file(case, intake, legal, analytics)
        blob_name = f"court_file_autodeclined_{case_id}.pdf"
        blob_service.upload("pdfs", blob_name, cf_bytes)
        url = blob_service.generate_download_url("pdfs", blob_name)

        cosmos_service.update_case(case_id, {
            "documents_data": {
                **(case.get("documents_data") or {}),
                "court_file_url": url,
            }
        })

        # EMAIL claimant
        email_service.send_escalation_notice(
            to_email=case["claimant_email"],
            party_name=case["claimant_name"],
            case_id=case_id,
            download_url=url,
        )
        logger.info(f"Declined court file generated | case_id={case_id}")

    except Exception as e:
        logger.error(f"Declined court file failed | case_id={case_id} | error={e}")


# ─────────────────────────────────────────────────────────────
# PROPOSAL RESPONSE
# ─────────────────────────────────────────────────────────────

@router.post("/proposal-response")
async def respondent_proposal_response(body: RespondentDecision, background_tasks: BackgroundTasks):
    """
    Respondent accepts or rejects the AI proposal.
    Delegates to the shared proposal_response handler in negotiation router.
    """
    case = _verify_respondent(body.case_id, body.email)

    try:
        decision = ProposalDecision(body.decision)
    except ValueError:
        raise HTTPException(status_code=400, detail="decision must be 'ACCEPT' or 'REJECT'")

    from app.routers.negotiation import proposal_response

    request = ProposalResponseRequest(
        case_id=body.case_id,
        round_number=case.get("current_round", 1),
        decision=decision,
        party="respondent",
        reason=body.reason,
    )
    return await proposal_response(request, background_tasks, current_user=None)


# ─────────────────────────────────────────────────────────────
# PROOF RESPONSE
# ─────────────────────────────────────────────────────────────

@router.post("/proof-response")
async def respondent_proof_response(body: RespondentProofResponse):
    """Respondent responds to a proof request from the claimant."""
    _verify_respondent(body.case_id, body.email)

    from app.routers.negotiation import proof_response

    request = ProofResponseRequest(
        case_id=body.case_id,
        round_number=body.round_number,
        party="respondent",
        request_id=body.request_id,
        response_text=body.response_text,
        file_refs=body.file_refs,
    )
    return await proof_response(request, current_user=None)


# ─────────────────────────────────────────────────────────────
# EVIDENCE UPLOAD
# ─────────────────────────────────────────────────────────────

@router.post("/evidence-upload")
async def respondent_evidence_upload(body: RespondentEvidenceUpload):
    """Respondent uploads evidence files (base64 encoded)."""
    import base64
    case = _verify_respondent(body.case_id, body.email)

    allowed = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".doc", ".docx", ".txt"}
    original_name = body.filename or "respondent_evidence.bin"
    ext = os.path.splitext(original_name)[1].lower()
    if ext and ext not in allowed:
        raise HTTPException(status_code=400, detail="Unsupported evidence file type.")

    try:
        content = base64.b64decode(body.base64_data)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid file encoding.")
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    blob_name    = f"{body.case_id}/respondent_{uuid.uuid4().hex}_{original_name}"
    blob_service.upload("evidence", blob_name, content, content_type=body.content_type)
    download_url = blob_service.generate_download_url("evidence", blob_name, expiry_hours=720)

    file_record = {
        "id":           uuid.uuid4().hex,
        "filename":     original_name,
        "blob_name":    blob_name,
        "url":          download_url,
        "content_type": body.content_type,
        "uploaded_at":  datetime.now(timezone.utc).isoformat(),
        "uploaded_by":  body.email,
    }
    evidence_ids   = list(case.get("evidence_file_ids", [])) + [file_record["id"]]
    evidence_files = list(case.get("evidence_files", []))    + [file_record]
    cosmos_service.update_case(body.case_id, {
        "evidence_file_ids": evidence_ids,
        "evidence_files":    evidence_files,
    })
    return file_record
