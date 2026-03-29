import logging
import os
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile

from app.agents.strategy_agent import generate_case_strategy
from app.config import settings
from app.core.case_router import route_case
from app.core.dependencies import get_current_user
from app.core.exceptions import CaseNotFound, ContentSafetyViolation, UnauthorizedAccess
from app.models.case import CaseStatus, DisputeSubmission
from app.services.blob_service import blob_service
from app.services.content_safety import content_safety_service
from app.services.cosmos_service import cosmos_service
from app.services.email_service import email_service

router = APIRouter()
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# CASE SUBMISSION
# ─────────────────────────────────────────────────────────────

@router.post("/submit")
async def submit_case(
    body: DisputeSubmission,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
):
    # 1. Consent + disclaimer
    if not body.claimant_consent:
        raise HTTPException(status_code=400, detail=(
            "You must consent to data processing under "
            "India's Digital Personal Data Protection Act 2023."
        ))
    if not body.disclaimer_acknowledged:
        raise HTTPException(status_code=400, detail=(
            "You must acknowledge that LegalAI Resolver provides "
            "AI-assisted document drafting only and is not a substitute "
            "for advice from a licensed advocate."
        ))

    # 2. Email must match logged-in user
    if current_user["email"].lower() != body.claimant_email.lower():
        raise HTTPException(status_code=403, detail="Claimant email must match your logged-in account.")

    # 3. Cannot file against yourself
    if body.claimant_email.lower() == body.respondent_email.lower():
        raise HTTPException(status_code=400, detail="Claimant and respondent cannot be the same email address.")

    # 4. Content Safety
    try:
        content_safety_service.check_text(body.dispute_text)
    except ContentSafetyViolation:
        raise HTTPException(status_code=400, detail=(
            "Your submission contains content that violates our safety policy. "
            "Please revise and resubmit."
        ))

    # 5. Create case
    case_data = body.model_dump()
    case      = cosmos_service.create_case(case_data)
    case_id   = case["id"]
    logger.info(f"Case created | id={case_id} | email={body.claimant_email}")

    cosmos_service.transition_case(case_id, CaseStatus.ANALYZING)

    # 6. Fast case router (sync)
    routing = route_case(
        dispute_text=body.dispute_text,
        claim_amount=body.claim_amount,
        respondent_type=body.respondent_type.value,
        claimant_state=body.claimant_state,
    )
    cosmos_service.update_case(case_id, {"track": routing["track"], "routing": routing})

    # 7. Criminal → no mediation
    if routing.get("is_criminal") or routing["track"] == "criminal":
        cosmos_service.transition_case(case_id, CaseStatus.CRIMINAL_ADVISORY)
        background_tasks.add_task(_handle_criminal_advisory, case_id)
        return {
            "case_id": case_id,
            "status":  "CRIMINAL_ADVISORY",
            "track":   "criminal",
            "message": (
                "This dispute involves criminal elements. AI mediation is not possible. "
                "A legal advisory with FIR guidance is being generated."
            ),
        }

    # 8. Background pipeline for all other tracks
    background_tasks.add_task(_run_full_pipeline, case_id)

    return {
        "case_id": case_id,
        "status":  "ANALYZING",
        "track":   routing["track"],
        "message": "Case submitted. AI analysis is in progress (30–60 seconds).",
    }


# ─────────────────────────────────────────────────────────────
# BACKGROUND PIPELINE
# ─────────────────────────────────────────────────────────────

async def _handle_criminal_advisory(case_id: str):
    """Runs intake + legal + document agents for criminal track."""
    try:
        from app.agents.intake_agent   import run_intake_agent
        from app.agents.legal_agent    import run_legal_agent
        from app.agents.document_agent import run_document_agent

        case   = cosmos_service.get_case(case_id)
        intake = await run_intake_agent(case)
        cosmos_service.save_agent_output(case_id, "intake_data", intake)

        case  = cosmos_service.get_case(case_id)
        legal = await run_legal_agent(case)
        cosmos_service.save_agent_output(case_id, "legal_data", legal)

        case = cosmos_service.get_case(case_id)
        docs = await run_document_agent(case)
        cosmos_service.save_agent_output(case_id, "documents_data", docs)

        logger.info(f"Criminal advisory complete | case_id={case_id}")

    except Exception as e:
        logger.error(f"Criminal advisory failed | case_id={case_id} | error={e}")
        cosmos_service.update_case(case_id, {"pipeline_error": str(e)})


async def _run_full_pipeline(case_id: str):
    """Runs all 4 agents sequentially then transitions to ANALYZED."""
    try:
        import time
        from app.core.monitoring import track_agent_call, track_case_event
        from app.agents.intake_agent    import run_intake_agent
        from app.agents.legal_agent     import run_legal_agent
        from app.agents.analytics_agent import run_analytics_agent
        from app.agents.document_agent  import run_document_agent

        track_case_event(case_id, "PIPELINE_STARTED")

        agents = [
            ("intake_agent",    run_intake_agent,    "intake_data"),
            ("legal_agent",     run_legal_agent,     "legal_data"),
            ("analytics_agent", run_analytics_agent, "analytics_data"),
            ("document_agent",  run_document_agent,  "documents_data"),
        ]

        for agent_name, agent_fn, output_key in agents:
            logger.info(f"Pipeline | {agent_name} | case_id={case_id}")
            start = time.time()
            try:
                case   = cosmos_service.get_case(case_id)
                result = await agent_fn(case)
                cosmos_service.save_agent_output(case_id, output_key, result)
                track_agent_call(agent_name, case.get("track", "unknown"), True, (time.time() - start) * 1000)
            except Exception as agent_err:
                track_agent_call(agent_name, "unknown", False, (time.time() - start) * 1000)
                logger.error(f"Agent failed | name={agent_name} | case_id={case_id} | error={agent_err}")
                cosmos_service.update_case(case_id, {f"{agent_name}_error": str(agent_err)})

        cosmos_service.transition_case(case_id, CaseStatus.ANALYZED)
        track_case_event(case_id, "PIPELINE_COMPLETE")
        logger.info(f"Pipeline complete | case_id={case_id}")

    except Exception as e:
        logger.error(f"Pipeline failed | case_id={case_id} | error={e}")
        cosmos_service.update_case(case_id, {
            "pipeline_error":     str(e),
            "pipeline_failed_at": datetime.now(timezone.utc).isoformat(),
        })
        # Try to advance so the case is not stuck in ANALYZING forever
        try:
            cosmos_service.transition_case(case_id, CaseStatus.ANALYZED)
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────
# READ ENDPOINTS
# ─────────────────────────────────────────────────────────────

@router.get("/my-cases")
async def get_my_cases(current_user: dict = Depends(get_current_user)):
    cases = cosmos_service.get_cases_by_email(current_user["email"])
    return {"cases": cases, "total": len(cases)}


@router.get("/{case_id}/status")
async def get_case_status(case_id: str):
    """Public polling endpoint — no auth required."""
    case = cosmos_service.get_case(case_id)
    if not case:
        raise CaseNotFound(case_id)
    from app.core.state_machine import get_allowed_transitions, is_expired
    return {
        "case_id":             case_id,
        "status":              case["status"],
        "track":               case.get("track"),
        "current_round":       case.get("current_round", 0),
        "pipeline_error":      case.get("pipeline_error"),
        "allowed_transitions": get_allowed_transitions(case),
        "is_expired":          is_expired(case),
    }


@router.get("/{case_id}")
async def get_case(case_id: str, current_user: dict = Depends(get_current_user)):
    """Full case details — claimant only."""
    case = cosmos_service.get_case(case_id)
    if not case:
        raise CaseNotFound(case_id)
    if case["claimant_email"].lower() != current_user["email"].lower():
        raise UnauthorizedAccess()
    return case


# ─────────────────────────────────────────────────────────────
# SEND INVITE
# ─────────────────────────────────────────────────────────────

@router.post("/{case_id}/send-invite")
async def send_invite(case_id: str, current_user: dict = Depends(get_current_user)):
    """
    Sends the dispute invite email to the respondent.
    Case must be ANALYZED. Transitions to INVITE_SENT.

    EMAIL:
      • Respondent → case invite with 7-day deadline warning
      • Claimant   → confirmation that invite was sent
    """
    case = cosmos_service.get_case(case_id)
    if not case:
        raise CaseNotFound(case_id)
    if case["claimant_email"].lower() != current_user["email"].lower():
        raise UnauthorizedAccess()
    if case["status"] != CaseStatus.ANALYZED.value:
        raise HTTPException(
            status_code=409,
            detail=f"Case must be ANALYZED to send invite. Current: {case['status']}",
        )

    # Send invite to respondent
    sent = email_service.send_case_invite(
        to_email=case["respondent_email"],
        respondent_name=case["respondent_name"],
        claimant_name=case["claimant_name"],
        case_id=case_id,
        claim_amount=case.get("claim_amount"),
        dispute_summary=case["dispute_text"],
    )
    if not sent:
        raise HTTPException(status_code=503, detail="Failed to send invite email. Please try again.")

    # Notify claimant that invite was dispatched
    email_service.send_case_update(
        to_email=case["claimant_email"],
        party_name=case["claimant_name"],
        case_id=case_id,
        headline="Invite sent to respondent",
        summary=(
            f"Your dispute invite has been sent to {case['respondent_name']} "
            f"({case['respondent_email']}). They have 7 days to respond before "
            "the case is automatically escalated."
        ),
        portal_url=settings.BASE_URL,
        action_label="View Your Case",
    )

    cosmos_service.transition_case(case_id, CaseStatus.INVITE_SENT)
    logger.info(f"Invite sent | case_id={case_id} | to={case['respondent_email']}")
    return {"message": f"Invite sent to {case['respondent_email']}", "status": "INVITE_SENT"}


# ─────────────────────────────────────────────────────────────
# EVIDENCE UPLOAD
# ─────────────────────────────────────────────────────────────

@router.post("/{case_id}/evidence-upload")
async def upload_evidence(
    case_id: str,
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    case = cosmos_service.get_case(case_id)
    if not case:
        raise CaseNotFound(case_id)
    if case["claimant_email"].lower() != current_user["email"].lower():
        raise UnauthorizedAccess()

    allowed = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".doc", ".docx", ".txt"}
    original_name = file.filename or "evidence.bin"
    ext = os.path.splitext(original_name)[1].lower()
    if ext and ext not in allowed:
        raise HTTPException(status_code=400, detail="Unsupported evidence file type.")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    blob_name    = f"{case_id}/{uuid.uuid4().hex}_{original_name}"
    content_type = file.content_type or "application/octet-stream"
    blob_service.upload("evidence", blob_name, content, content_type=content_type)
    download_url = blob_service.generate_download_url("evidence", blob_name, expiry_hours=720)

    file_record = {
        "id":           uuid.uuid4().hex,
        "filename":     original_name,
        "blob_name":    blob_name,
        "url":          download_url,
        "content_type": content_type,
        "uploaded_at":  datetime.now(timezone.utc).isoformat(),
        "uploaded_by":  current_user["email"],
    }
    evidence_ids   = list(case.get("evidence_file_ids", [])) + [file_record["id"]]
    evidence_files = list(case.get("evidence_files", []))    + [file_record]
    cosmos_service.update_case(case_id, {
        "evidence_file_ids": evidence_ids,
        "evidence_files":    evidence_files,
    })
    return file_record


# ─────────────────────────────────────────────────────────────
# STRATEGY
# ─────────────────────────────────────────────────────────────

@router.post("/{case_id}/strategy")
async def generate_strategy(case_id: str, current_user: dict = Depends(get_current_user)):
    case = cosmos_service.get_case(case_id)
    if not case:
        raise CaseNotFound(case_id)
    if case["claimant_email"].lower() != current_user["email"].lower():
        raise UnauthorizedAccess()

    strategy = generate_case_strategy(case)
    cosmos_service.update_case(case_id, {"strategy_data": strategy})
    return strategy


# ─────────────────────────────────────────────────────────────
# PAYMENT CONFIRMATION
# ─────────────────────────────────────────────────────────────

@router.post("/{case_id}/confirm-payment")
async def confirm_payment(
    case_id: str,
    honored: bool,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
):
    """
    Claimant confirms whether the respondent paid the settled amount.
    Only valid on SETTLED cases.

    EMAIL (if not honored):
      • Claimant → breach of settlement notice with download link
    """
    case = cosmos_service.get_case(case_id)
    if not case:
        raise CaseNotFound(case_id)
    if case["claimant_email"].lower() != current_user["email"].lower():
        raise UnauthorizedAccess()
    if case["status"] != CaseStatus.SETTLED.value:
        raise HTTPException(status_code=409, detail="Payment confirmation only available for SETTLED cases.")

    cosmos_service.set_settlement_honored(case_id, honored)

    if honored:
        cosmos_service.update_case(case_id, {
            "payment_confirmed_at": datetime.now(timezone.utc).isoformat()
        })
        return {"message": "Payment confirmed. Case fully resolved.", "outcome": "PAYMENT_RECEIVED"}

    background_tasks.add_task(_generate_and_send_breach_notice, case_id)
    return {
        "message": "Payment breach recorded. A Breach of Settlement Notice is being generated.",
        "outcome": "BREACH_RECORDED",
    }


async def _generate_and_send_breach_notice(case_id: str):
    """
    EMAIL: Claimant receives breach notice PDF download link.
    """
    try:
        from app.agents.document_agent import generate_breach_notice

        case       = cosmos_service.get_case(case_id)
        breach_url = await generate_breach_notice(case)

        cosmos_service.update_case(case_id, {
            "breach_notice_sent": True,
            "breach_notice_url":  breach_url,
            "breach_noticed_at":  datetime.now(timezone.utc).isoformat(),
        })

        settled_amount = case.get("settled_amount", 0) or 0
        email_service.send_case_update(
            to_email=case["claimant_email"],
            party_name=case["claimant_name"],
            case_id=case_id,
            headline="Breach of Settlement Notice Ready",
            summary=(
                f"Your Breach of Settlement Notice has been generated for Case "
                f"#{case_id[:8].upper()} (amount: Rs. {settled_amount:,.0f}). "
                "This document is stronger than the original demand letter as it "
                "references the executed settlement agreement. Send it to the respondent "
                "immediately. If payment is still not received within 7 days, file it "
                "with the appropriate court as breach of contract."
            ),
            portal_url=breach_url,
            action_label="Download Breach Notice",
        )
        logger.info(f"Breach notice generated and sent | case_id={case_id}")

    except Exception as e:
        logger.error(f"Breach notice failed | case_id={case_id} | error={e}")


# ─────────────────────────────────────────────────────────────
# MEDIATION CERTIFICATE
# ─────────────────────────────────────────────────────────────

@router.get("/{case_id}/mediation-certificate")
async def get_mediation_certificate(case_id: str, current_user: dict = Depends(get_current_user)):
    case = cosmos_service.get_case(case_id)
    if not case:
        raise CaseNotFound(case_id)
    if (case["claimant_email"].lower() != current_user["email"].lower() and
            case["respondent_email"].lower() != current_user["email"].lower()):
        raise UnauthorizedAccess()

    docs_data = case.get("documents_data") or {}
    url = docs_data.get("mediation_certificate_url")

    if not url:
        try:
            from app.agents.document_agent import _generate_mediation_certificate
            cert_bytes = _generate_mediation_certificate(case)
            blob_name  = f"mediation_cert_{case_id}.pdf"
            blob_service.upload("pdfs", blob_name, cert_bytes)
            url = blob_service.generate_download_url("pdfs", blob_name, expiry_hours=720)
            cosmos_service.update_case(case_id, {
                "documents_data": {**docs_data, "mediation_certificate_url": url}
            })
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to generate certificate: {e}")

    return {
        "download_url": url,
        "doc_type":     "mediation_certificate",
        "note": "This certificate can be presented in court as evidence of a genuine pre-litigation mediation attempt.",
    }


# ─────────────────────────────────────────────────────────────
# TIMELINE
# ─────────────────────────────────────────────────────────────

@router.get("/{case_id}/timeline")
async def get_case_timeline(case_id: str, current_user: dict = Depends(get_current_user)):
    case = cosmos_service.get_case(case_id)
    if not case:
        raise CaseNotFound(case_id)
    if (case["claimant_email"].lower() != current_user["email"].lower() and
            case["respondent_email"].lower() != current_user["email"].lower()):
        raise UnauthorizedAccess()

    neg    = cosmos_service.get_negotiation_by_case(case_id)
    rounds = neg.get("rounds", []) if neg else []
    docs   = cosmos_service.get_documents_by_case(case_id)

    events = [{"timestamp": case["created_at"], "event": "CASE_SUBMITTED", "label": "Case submitted"}]

    if case.get("intake_data"):
        events.append({"timestamp": case.get("updated_at"), "event": "ANALYZED", "label": "AI analysis complete"})

    for r in rounds:
        rn = r["round_number"]
        cl = r.get("claimant") or {}
        rs = r.get("respondent") or {}
        if cl.get("submitted_at"):
            events.append({"timestamp": cl["submitted_at"], "event": f"ROUND_{rn}_CLAIMANT_OFFER",  "label": f"Round {rn}: Claimant submitted offer"})
        if rs.get("submitted_at"):
            events.append({"timestamp": rs["submitted_at"], "event": f"ROUND_{rn}_RESPONDENT_OFFER", "label": f"Round {rn}: Respondent submitted offer"})
        if r.get("proposal_issued_at"):
            amt = r.get("ai_proposed_amount", 0) or 0
            events.append({"timestamp": r["proposal_issued_at"], "event": f"ROUND_{rn}_PROPOSAL", "label": f"Round {rn}: AI proposal — Rs. {amt:,.0f}"})

    if case["status"] == "SETTLED":
        events.append({"timestamp": case.get("settled_at") or case["updated_at"], "event": "SETTLED", "label": f"Settled — Rs. {case.get('settled_amount', 0):,.0f}"})
    elif case["status"] in ("ESCALATED", "AUTO_ESCALATED"):
        events.append({"timestamp": case.get("escalated_at") or case["updated_at"], "event": "ESCALATED", "label": "Escalated — court file generated"})

    events.sort(key=lambda x: x["timestamp"] or "9999")
    return {
        "case_id":   case_id,
        "status":    case["status"],
        "timeline":  events,
        "documents": [{"doc_type": d["doc_type"], "created_at": d["created_at"]} for d in docs],
    }
