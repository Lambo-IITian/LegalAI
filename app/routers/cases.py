import logging
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks, status
from app.models.case import DisputeSubmission, CaseStatus
from app.services.cosmos_service import cosmos_service
from app.services.content_safety import content_safety_service
from app.core.case_router import route_case
from app.core.dependencies import get_current_user
from app.core.exceptions import (
    ContentSafetyViolation,
    CaseNotFound,
    UnauthorizedAccess,
    InvalidCaseState,
)
from fastapi import BackgroundTasks
from app.models.case import CaseStatus
from app.core.dependencies import get_current_user
from app.core.exceptions import CaseNotFound, UnauthorizedAccess

router  = APIRouter()
logger  = logging.getLogger(__name__)


# ── Case Submission ───────────────────────────────────────────

@router.post("/submit")
async def submit_case(
    body: DisputeSubmission,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
):
    """
    Full case submission endpoint.
    Order of operations:
    1. Validate consent + disclaimer
    2. Verify claimant email matches token
    3. Content Safety check
    4. Create case in Cosmos (status = SUBMITTED)
    5. Run Case Router — classify track (fast, sync)
    6. Criminal track → CRIMINAL_ADVISORY immediately
    7. All other tracks → trigger background pipeline
    """

    # ── 1. Consent validation ─────────────────────────────
    if not body.claimant_consent:
        raise HTTPException(
            status_code=400,
            detail=(
                "You must consent to data processing under "
                "India's Digital Personal Data Protection Act 2023."
            ),
        )

    if not body.disclaimer_acknowledged:
        raise HTTPException(
            status_code=400,
            detail=(
                "You must acknowledge that LegalAI Resolver provides "
                "AI-assisted document drafting only and is not a substitute "
                "for advice from a licensed advocate."
            ),
        )

    # ── 2. Email must match logged-in user ────────────────
    if current_user["email"] != body.claimant_email:
        raise HTTPException(
            status_code=403,
            detail="Claimant email must match your logged-in account.",
        )

    # ── 3. Content Safety ─────────────────────────────────
    try:
        content_safety_service.check_text(body.dispute_text)
    except ContentSafetyViolation:
        raise HTTPException(
            status_code=400,
            detail=(
                "Your submission contains content that violates our "
                "safety policy. Please revise and resubmit."
            ),
        )

    # ── 4. Create case in Cosmos ──────────────────────────
    case_data = body.model_dump()
    case      = cosmos_service.create_case(case_data)
    case_id   = case["id"]
    logger.info(f"Case created | id={case_id} | email={body.claimant_email}")

    # Transition to ANALYZING
    cosmos_service.transition_case(case_id, CaseStatus.ANALYZING)

    # ── 5. Run Case Router ────────────────────────────────
    routing = route_case(
        dispute_text=body.dispute_text,
        claim_amount=body.claim_amount,
        respondent_type=body.respondent_type.value,
        claimant_state=body.claimant_state,
    )

    cosmos_service.update_case(case_id, {
        "track":   routing["track"],
        "routing": routing,
    })

    # ── 6. Criminal track — no mediation ─────────────────
    if routing.get("is_criminal") or routing["track"] == "criminal":
        cosmos_service.transition_case(case_id, CaseStatus.CRIMINAL_ADVISORY)
        background_tasks.add_task(_handle_criminal_advisory, case_id)
        return {
            "case_id": case_id,
            "status":  "CRIMINAL_ADVISORY",
            "track":   "criminal",
            "message": (
                "This dispute involves criminal elements. AI mediation is not "
                "possible for criminal matters. We have generated a legal advisory "
                "with guidance on filing an FIR and relevant authorities to contact."
            ),
        }

    # ── 7. Trigger full pipeline in background ────────────
    background_tasks.add_task(_run_full_pipeline, case_id)

    return {
        "case_id": case_id,
        "status":  "ANALYZING",
        "track":   routing["track"],
        "message": (
            "Case submitted successfully. AI analysis is in progress. "
            "This usually takes 30-60 seconds."
        ),
    }


# ── Background Tasks ──────────────────────────────────────────

async def _handle_criminal_advisory(case_id: str):
    """
    Background task for criminal track cases.
    Runs intake agent + legal agent + document agent (FIR advisory only).
    """
    try:
        from app.agents.intake_agent  import run_intake_agent
        from app.agents.legal_agent   import run_legal_agent
        from app.agents.document_agent import run_document_agent

        # Agent 1 — Intake
        case   = cosmos_service.get_case(case_id)
        intake = await run_intake_agent(case)
        cosmos_service.save_agent_output(case_id, "intake_data", intake)
        logger.info(f"Criminal: intake complete | case_id={case_id}")

        # Agent 2 — Legal (for IPC sections)
        case  = cosmos_service.get_case(case_id)
        legal = await run_legal_agent(case)
        cosmos_service.save_agent_output(case_id, "legal_data", legal)
        logger.info(f"Criminal: legal complete | case_id={case_id}")

        # Agent 4 — Document (generates FIR advisory PDF)
        case = cosmos_service.get_case(case_id)
        docs = await run_document_agent(case)
        cosmos_service.save_agent_output(case_id, "documents_data", docs)
        logger.info(f"Criminal: FIR advisory generated | case_id={case_id}")

    except Exception as e:
        logger.error(f"Criminal advisory failed | case_id={case_id} | error={e}")
        cosmos_service.update_case(case_id, {"pipeline_error": str(e)})


async def _run_full_pipeline(case_id: str):
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
                duration = (time.time() - start) * 1000
                track = case.get("track", "unknown")
                track_agent_call(agent_name, track, True, duration)
            except Exception as agent_err:
                duration = (time.time() - start) * 1000
                track_agent_call(agent_name, "unknown", False, duration)
                raise agent_err

        cosmos_service.transition_case(case_id, CaseStatus.ANALYZED)
        track_case_event(case_id, "PIPELINE_COMPLETE")

    except Exception as e:
        logger.error(f"Pipeline failed | case_id={case_id} | error={e}")
        track_case_event(case_id, "PIPELINE_FAILED", {"error": str(e)})
        cosmos_service.update_case(case_id, {
            "pipeline_error":     str(e),
            "pipeline_failed_at": datetime.now(timezone.utc).isoformat(),
        })


# ── Read Endpoints ────────────────────────────────────────────

@router.get("/my-cases")
async def get_my_cases(
    current_user: dict = Depends(get_current_user),
):
    """Get all cases for the logged-in user (claimant or respondent)."""
    cases = cosmos_service.get_cases_by_email(current_user["email"])
    return {"cases": cases, "total": len(cases)}


@router.get("/{case_id}/status")
async def get_case_status(case_id: str):
    """
    Public status check — no auth required.
    Used by frontend to poll during pipeline.
    """
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
async def get_case(
    case_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Full case details. Only claimant can access."""
    case = cosmos_service.get_case(case_id)
    if not case:
        raise CaseNotFound(case_id)
    if case["claimant_email"] != current_user["email"]:
        raise UnauthorizedAccess()
    return case


# ── Send Invite ───────────────────────────────────────────────

@router.post("/{case_id}/send-invite")
async def send_invite(
    case_id: str,
    current_user: dict = Depends(get_current_user),
):
    """
    Sends the SendGrid email invite to the respondent.
    Case must be in ANALYZED state.
    Transitions to INVITE_SENT.
    """
    case = cosmos_service.get_case(case_id)
    if not case:
        raise CaseNotFound(case_id)
    if case["claimant_email"] != current_user["email"]:
        raise UnauthorizedAccess()
    if case["status"] != CaseStatus.ANALYZED.value:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Case must be in ANALYZED state to send invite. "
                f"Current state: {case['status']}"
            ),
        )

    from app.services.email_service import email_service
    sent = email_service.send_case_invite(
        to_email=case["respondent_email"],
        respondent_name=case["respondent_name"],
        claimant_name=case["claimant_name"],
        case_id=case_id,
        claim_amount=case.get("claim_amount"),
        dispute_summary=case["dispute_text"],
    )

    if not sent:
        raise HTTPException(
            status_code=503,
            detail="Failed to send invite email. Please try again.",
        )

    cosmos_service.transition_case(case_id, CaseStatus.INVITE_SENT)
    logger.info(f"Invite sent | case_id={case_id} | to={case['respondent_email']}")
    return {
        "message": f"Invite sent to {case['respondent_email']}",
        "status":  "INVITE_SENT",
    }


# ── Settlement Confirmation ───────────────────────────────────

@router.post("/{case_id}/confirm-payment")
async def confirm_payment(
    case_id: str,
    honored: bool,
    current_user: dict = Depends(get_current_user),
):
    """
    Claimant confirms whether the respondent honored the settlement payment.
    If not honored → generates breach of settlement notice.
    """
    case = cosmos_service.get_case(case_id)
    if not case:
        raise CaseNotFound(case_id)
    if case["claimant_email"] != current_user["email"]:
        raise UnauthorizedAccess()
    if case["status"] != CaseStatus.SETTLED.value:
        raise HTTPException(
            status_code=409,
            detail="Case must be SETTLED to confirm payment.",
        )

    cosmos_service.set_settlement_honored(case_id, honored)

    if not honored:
        # Trigger breach notice generation in background
        background_tasks = BackgroundTasks()
        background_tasks.add_task(_generate_breach_notice, case_id)
        return {
            "message": (
                "Payment breach recorded. A Breach of Settlement Notice "
                "is being generated and will be emailed to you."
            ),
        }

    return {"message": "Payment confirmed. Case fully resolved."}


async def _generate_breach_notice(case_id: str):
    """Generate breach of settlement notice when payment is not honored."""
    try:
        from app.agents.document_agent import generate_breach_notice
        case = cosmos_service.get_case(case_id)
        await generate_breach_notice(case)
        logger.info(f"Breach notice generated | case_id={case_id}")
    except Exception as e:
        logger.error(f"Breach notice failed | case_id={case_id} | error={e}")


@router.post("/{case_id}/confirm-payment")
async def confirm_payment(
    case_id: str,
    honored: bool,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
):
    """
    Claimant confirms whether the respondent honored the payment.
    Only callable on SETTLED cases.
    If honored=False → generates Breach of Settlement Notice.
    """
    case = cosmos_service.get_case(case_id)
    if not case:
        raise CaseNotFound(case_id)
    if case["claimant_email"] != current_user["email"]:
        raise UnauthorizedAccess()
    if case["status"] != CaseStatus.SETTLED.value:
        raise HTTPException(
            status_code=409,
            detail="Payment confirmation only available for SETTLED cases.",
        )

    cosmos_service.set_settlement_honored(case_id, honored)

    if honored:
        cosmos_service.update_case(case_id, {
            "payment_confirmed_at": datetime.now(timezone.utc).isoformat()
        })
        return {
            "message": "Payment confirmed. Case fully resolved. Thank you for using LegalAI Resolver.",
            "outcome": "PAYMENT_RECEIVED",
        }
    else:
        # Payment not received — generate breach notice
        background_tasks.add_task(_generate_and_send_breach_notice, case_id)
        return {
            "message": (
                "Payment breach recorded. A Breach of Settlement Notice is being "
                "generated and will be emailed to you within 60 seconds."
            ),
            "outcome": "BREACH_RECORDED",
        }


async def _generate_and_send_breach_notice(case_id: str):
    """Background task — generates breach notice PDF and emails claimant."""
    try:
        from app.agents.document_agent import generate_breach_notice

        case = cosmos_service.get_case(case_id)

        # Generate breach notice PDF
        breach_url = await generate_breach_notice(case)

        # Mark breach notice sent
        cosmos_service.update_case(case_id, {
            "breach_notice_sent":   True,
            "breach_notice_url":    breach_url,
            "breach_noticed_at":    datetime.now(timezone.utc).isoformat(),
        })

        # Email claimant with download link
        from app.services.email_service import email_service
        email_service.send(
            to_email=case["claimant_email"],
            subject=f"Breach of Settlement Notice — Case #{case_id[:8].upper()}",
            html_body=f"""
            <div style="font-family:Arial;background:#0F2A4A;padding:24px;
                        border-radius:8px;">
                <h3 style="color:#DC2626;">Breach of Settlement Notice Ready</h3>
                <p style="color:#E2E8F0;">
                    Your Breach of Settlement Notice has been generated.
                    This document is stronger than the original demand letter
                    as it references the executed settlement agreement.
                </p>
                <a href="{breach_url}"
                   style="display:block;background:#DC2626;color:#fff;
                          text-align:center;padding:12px;border-radius:6px;
                          text-decoration:none;font-weight:bold;margin-top:16px;">
                    Download Breach Notice
                </a>
                <p style="color:#94A3B8;font-size:12px;margin-top:16px;">
                    Send this notice to the respondent immediately.
                    If payment is still not received within 7 days,
                    file this with the appropriate court as breach of contract.
                </p>
            </div>
            """,
        )

        logger.info(f"Breach notice generated and sent | case_id={case_id}")

    except Exception as e:
        logger.error(f"Breach notice generation failed | case_id={case_id} | error={e}")


# ══════════════════════════════════════════════════════════════
# MEDIATION CERTIFICATE DOWNLOAD
# ══════════════════════════════════════════════════════════════

@router.get("/{case_id}/mediation-certificate")
async def get_mediation_certificate(
    case_id: str,
    current_user: dict = Depends(get_current_user),
):
    """
    Returns the Mediation Certificate for this case.
    Available for all non-criminal tracks after ANALYZED.
    Useful in court as evidence of attempted pre-litigation resolution.
    """
    case = cosmos_service.get_case(case_id)
    if not case:
        raise CaseNotFound(case_id)

    if (case["claimant_email"] != current_user["email"] and
            case["respondent_email"] != current_user["email"]):
        raise UnauthorizedAccess()

    docs_data = case.get("documents_data") or {}
    url       = docs_data.get("mediation_certificate_url")

    if not url:
        # Generate on demand if not already done
        try:
            from app.agents.document_agent import _generate_mediation_certificate
            from app.services.blob_service import blob_service

            cert_bytes = _generate_mediation_certificate(case)
            blob_name  = f"mediation_cert_{case_id}.pdf"
            blob_service.upload("pdfs", blob_name, cert_bytes)
            url = blob_service.generate_download_url("pdfs", blob_name, expiry_hours=720)

            cosmos_service.update_case(case_id, {
                "documents_data": {
                    **(docs_data),
                    "mediation_certificate_url": url,
                }
            })
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to generate mediation certificate: {str(e)}",
            )

    return {
        "download_url": url,
        "doc_type":     "mediation_certificate",
        "note": (
            "This certificate can be presented in court as evidence of a "
            "genuine pre-litigation mediation attempt."
        ),
    }


# ══════════════════════════════════════════════════════════════
# CASE TIMELINE — For frontend display
# ══════════════════════════════════════════════════════════════

@router.get("/{case_id}/timeline")
async def get_case_timeline(
    case_id: str,
    current_user: dict = Depends(get_current_user),
):
    """
    Returns the full timeline of events for a case.
    Used by the frontend to show case progress visually.
    """
    case = cosmos_service.get_case(case_id)
    if not case:
        raise CaseNotFound(case_id)

    if (case["claimant_email"] != current_user["email"] and
            case["respondent_email"] != current_user["email"]):
        raise UnauthorizedAccess()

    neg    = cosmos_service.get_negotiation_by_case(case_id)
    rounds = neg.get("rounds", []) if neg else []
    docs   = cosmos_service.get_documents_by_case(case_id)

    events = []

    # Case created
    events.append({
        "timestamp": case["created_at"],
        "event":     "CASE_SUBMITTED",
        "label":     "Case submitted",
    })

    # Analysis complete
    if case.get("intake_data"):
        events.append({
            "timestamp": case["updated_at"],
            "event":     "ANALYZED",
            "label":     "AI analysis complete — 5 agents ran",
        })

    # Invite sent
    if case["status"] in [
        "INVITE_SENT", "RESPONDENT_VIEWED", "NEGOTIATING",
        "ROUND_PENDING", "PROPOSAL_ISSUED", "SETTLING",
        "SETTLED", "ESCALATING", "ESCALATED",
    ]:
        events.append({
            "timestamp": None,
            "event":     "INVITE_SENT",
            "label":     f"Invite sent to {case['respondent_name']}",
        })

    # Negotiation rounds
    for r in rounds:
        rn = r["round_number"]
        if r.get("claimant_offer_at"):
            events.append({
                "timestamp": r["claimant_offer_at"],
                "event":     f"ROUND_{rn}_CLAIMANT_OFFER",
                "label":     f"Round {rn}: Claimant submitted offer",
            })
        if r.get("respondent_offer_at"):
            events.append({
                "timestamp": r["respondent_offer_at"],
                "event":     f"ROUND_{rn}_RESPONDENT_OFFER",
                "label":     f"Round {rn}: Respondent submitted offer",
            })
        if r.get("proposal_issued_at"):
            events.append({
                "timestamp": r["proposal_issued_at"],
                "event":     f"ROUND_{rn}_PROPOSAL",
                "label":     f"Round {rn}: AI proposal issued — Rs. {r.get('ai_proposed_amount', 0):,.0f}",
            })

    # Outcome
    if case["status"] == "SETTLED":
        events.append({
            "timestamp": case["updated_at"],
            "event":     "SETTLED",
            "label":     f"Case settled — Rs. {case.get('settled_amount', 0):,.0f}",
        })
    elif case["status"] in ["ESCALATED", "AUTO_ESCALATED"]:
        events.append({
            "timestamp": case["updated_at"],
            "event":     "ESCALATED",
            "label":     "Case escalated — court file generated",
        })

    # Sort by timestamp (put None events at end)
    events.sort(key=lambda x: x["timestamp"] or "9999")

    return {
        "case_id":  case_id,
        "status":   case["status"],
        "timeline": events,
        "documents": [{
            "doc_type":   d["doc_type"],
            "created_at": d["created_at"],
        } for d in docs],
    }
