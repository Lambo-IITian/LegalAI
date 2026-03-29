import logging
import asyncio
from datetime import datetime, timedelta, timezone
from app.models.case import CaseStatus
from app.services.cosmos_service import cosmos_service
from app.core.state_machine import is_expired

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════
# MAIN EXPIRY CHECK — runs every hour
# ══════════════════════════════════════════════════════════════

async def run_expiry_check():
    """
    Checks all non-terminal cases with a deadline.
    For each expired case applies the correct action.
    """
    cases = cosmos_service.get_cases_needing_expiry_check()
    logger.info(f"Expiry check running | {len(cases)} cases to check")

    expired = [c for c in cases if is_expired(c)]
    logger.info(f"Expiry check | {len(expired)} expired cases found")

    for case in expired:
        await _handle_expired_case(case)


async def _handle_expired_case(case: dict):
    """Applies the correct expiry action based on current status."""
    case_id = case["id"]
    status  = case["status"]

    try:
        if status == CaseStatus.ANALYZED.value:
            await _expire_analyzed(case_id)

        elif status == CaseStatus.INVITE_SENT.value:
            await _expire_invite_sent(case_id, case)

        elif status == CaseStatus.RESPONDENT_VIEWED.value:
            await _expire_respondent_viewed(case_id, case)

        elif status in {
            CaseStatus.NEGOTIATION_OPEN.value,
            CaseStatus.WAITING_FOR_CLAIMANT.value,
            CaseStatus.WAITING_FOR_RESPONDENT.value,
            CaseStatus.PROOF_REQUESTED.value,
            CaseStatus.PROOF_RESPONSE_PENDING.value,
        }:
            await _expire_round_pending(case_id, case)

        elif status in {
            CaseStatus.PROPOSAL_ISSUED.value,
            CaseStatus.SETTLEMENT_PENDING_CONFIRMATION.value,
        }:
            await _expire_proposal_issued(case_id, case)

        elif status == CaseStatus.SETTLING.value:
            await _expire_settling(case_id, case)

    except Exception as e:
        logger.error(f"Expiry handler failed | case_id={case_id} | status={status} | error={e}")


# ══════════════════════════════════════════════════════════════
# EXPIRY HANDLERS PER STATE
# ══════════════════════════════════════════════════════════════

async def _expire_analyzed(case_id: str):
    """
    ANALYZED → ABANDONED
    Claimant submitted a case but never sent the invite within 14 days.
    No notification — case quietly closed.
    """
    cosmos_service.transition_case(case_id, CaseStatus.ABANDONED, {
        "abandoned_reason": "Claimant did not send invite within 14 days of analysis"
    })
    logger.info(f"Case abandoned | case_id={case_id} | reason=no_invite_sent")


async def _expire_invite_sent(case_id: str, case: dict):
    """
    INVITE_SENT → AUTO_ESCALATED
    Respondent never opened the email within 7 days.
    Claimant is notified with court file.
    """
    cosmos_service.transition_case(case_id, CaseStatus.AUTO_ESCALATED, {
        "auto_escalation_reason": (
            "Respondent did not open the invite within 7 days. "
            "Non-participation noted in court file."
        )
    })

    docs_data = case.get("documents_data") or {}
    court_url = docs_data.get("court_file_url", "")

    from app.services.email_service import email_service
    email_service.send(
        to_email=case["claimant_email"],
        subject=f"Case Auto-Escalated — Respondent Did Not Respond — #{case_id[:8].upper()}",
        html_body=f"""
        <div style="font-family:Arial;background:#0F2A4A;padding:24px;border-radius:8px;">
            <h3 style="color:#D97706;">LegalAI Resolver — Case Update</h3>
            <p style="color:#E2E8F0;">Dear {case['claimant_name']},</p>
            <p style="color:#E2E8F0;">
                <b>{case['respondent_name']}</b> did not respond to the mediation
                invite within 7 days. Your case has been automatically escalated.
            </p>
            <p style="color:#E2E8F0;">
                A court-ready case file has been prepared. The respondent's
                non-participation is documented as evidence of bad faith.
            </p>
            {'<a href="' + court_url + '" style="display:block;background:#DC2626;color:#fff;text-align:center;padding:12px;border-radius:6px;text-decoration:none;font-weight:bold;margin-top:16px;">Download Court File</a>' if court_url else ''}
        </div>
        """,
    )
    logger.info(f"Auto-escalated | case_id={case_id} | reason=invite_not_opened")


async def _expire_respondent_viewed(case_id: str, case: dict):
    """
    RESPONDENT_VIEWED → AUTO_ESCALATED
    Respondent opened the invite but did not submit a response within 5 days.
    """
    cosmos_service.transition_case(case_id, CaseStatus.AUTO_ESCALATED, {
        "auto_escalation_reason": (
            "Respondent viewed the case but did not submit a response within 5 days."
        )
    })

    docs_data = case.get("documents_data") or {}
    court_url = docs_data.get("court_file_url", "")

    from app.services.email_service import email_service
    email_service.send(
        to_email=case["claimant_email"],
        subject=f"Case Auto-Escalated — Respondent Did Not Engage — #{case_id[:8].upper()}",
        html_body=f"""
        <div style="font-family:Arial;background:#0F2A4A;padding:24px;border-radius:8px;">
            <h3 style="color:#D97706;">LegalAI Resolver — Case Update</h3>
            <p style="color:#E2E8F0;">Dear {case['claimant_name']},</p>
            <p style="color:#E2E8F0;">
                <b>{case['respondent_name']}</b> viewed your case but did not
                submit a response within 5 days. Your case has been escalated.
                Their deliberate non-engagement is documented in the court file.
            </p>
            {'<a href="' + court_url + '" style="display:block;background:#DC2626;color:#fff;text-align:center;padding:12px;border-radius:6px;text-decoration:none;font-weight:bold;margin-top:16px;">Download Court File</a>' if court_url else ''}
        </div>
        """,
    )
    logger.info(f"Auto-escalated | case_id={case_id} | reason=no_response_after_view")


async def _expire_round_pending(case_id: str, case: dict):
    """
    Waiting/proof state expired (3 days).
    If both sides have already submitted numbers, trigger mediation.
    Otherwise auto-escalate for non-participation or stale proof exchange.
    """
    neg = cosmos_service.get_negotiation_by_case(case_id)
    if not neg:
        logger.warning(f"Negotiation wait state expired but no negotiation found | case_id={case_id}")
        return

    round_number  = case.get("current_round", 1)
    current_round = cosmos_service.get_round(neg["id"], round_number)

    if not current_round:
        return

    claimant_submitted = bool((current_round.get("claimant") or {}).get("submitted_at"))
    respondent_submitted = bool((current_round.get("respondent") or {}).get("submitted_at"))
    if claimant_submitted and respondent_submitted:
        from app.routers.negotiation import _run_mediation
        await _run_mediation(case_id, neg["id"], round_number)
        return

    from app.routers.negotiation import _handle_escalation
    await _handle_escalation(case_id)


async def _expire_proposal_issued(case_id: str, case: dict):
    """
    Proposal/settlement confirmation expired (2 days) — one or both parties did not decide.
    Treat missing decision as REJECT.
    """
    neg = cosmos_service.get_negotiation_by_case(case_id)
    if not neg:
        return

    round_number  = case.get("current_round", 1)
    current_round = cosmos_service.get_round(neg["id"], round_number)

    if not current_round:
        return

    from app.models.negotiation import ProposalDecision
    now     = datetime.now(timezone.utc).isoformat()
    updates = {}

    claimant_state = current_round.get("claimant") or {}
    respondent_state = current_round.get("respondent") or {}

    if claimant_state.get("decision") == ProposalDecision.PENDING.value:
        claimant_state["decision"] = ProposalDecision.REJECT.value
        claimant_state["decided_at"] = now
        updates["claimant"] = claimant_state
        logger.info(f"Auto-rejected claimant | case_id={case_id} | reason=timeout")

    if respondent_state.get("decision") == ProposalDecision.PENDING.value:
        respondent_state["decision"] = ProposalDecision.REJECT.value
        respondent_state["decided_at"] = now
        updates["respondent"] = respondent_state
        logger.info(f"Auto-rejected respondent | case_id={case_id} | reason=timeout")

    if updates:
        cosmos_service.update_round_in_negotiation(neg["id"], round_number, updates)

    # Now process the outcome (both are now non-PENDING)
    max_rounds = case.get("max_rounds", 3)
    if round_number >= max_rounds:
        from app.routers.negotiation import _handle_escalation
        await _handle_escalation(case_id)
    else:
        from app.routers.negotiation import _start_next_round
        await _start_next_round(case_id, round_number + 1)


async def _expire_settling(case_id: str, case: dict):
    """
    SETTLING expired (14 days) — payment deadline passed.
    Auto-generate breach notice and notify claimant.
    """
    settled_amount = case.get("settled_amount", 0) or 0

    cosmos_service.update_case(case_id, {
        "settlement_honored":   False,
        "payment_overdue":      True,
        "payment_overdue_at":   datetime.now(timezone.utc).isoformat(),
    })

    # Generate breach notice
    from app.agents.document_agent import generate_breach_notice
    try:
        breach_url = await generate_breach_notice(case)
        cosmos_service.update_case(case_id, {
            "breach_notice_sent": True,
            "breach_notice_url":  breach_url,
        })
    except Exception as e:
        logger.error(f"Auto breach notice failed | case_id={case_id} | error={e}")
        breach_url = None

    from app.services.email_service import email_service
    email_service.send(
        to_email=case["claimant_email"],
        subject=f"Payment Deadline Passed — Breach Notice Ready — #{case_id[:8].upper()}",
        html_body=f"""
        <div style="font-family:Arial;background:#0F2A4A;padding:24px;border-radius:8px;">
            <h3 style="color:#DC2626;">Payment Deadline Passed</h3>
            <p style="color:#E2E8F0;">Dear {case['claimant_name']},</p>
            <p style="color:#E2E8F0;">
                The payment deadline of 14 days has passed.
                <b>{case['respondent_name']}</b> has not made the agreed payment
                of <b>Rs. {settled_amount:,.0f}</b>.
            </p>
            <p style="color:#E2E8F0;">
                A Breach of Settlement Notice has been automatically generated.
                This document is stronger than a demand letter as it references
                the signed settlement agreement.
            </p>
            {'<a href="' + breach_url + '" style="display:block;background:#DC2626;color:#fff;text-align:center;padding:12px;border-radius:6px;text-decoration:none;font-weight:bold;margin-top:16px;">Download Breach Notice</a>' if breach_url else ''}
        </div>
        """,
    )
    logger.info(f"Payment deadline expired | case_id={case_id} | amount={settled_amount}")


# ══════════════════════════════════════════════════════════════
# STARTUP INTEGRATION
# ══════════════════════════════════════════════════════════════

async def start_expiry_worker():
    """
    Runs expiry check every hour.
    Call this from app startup in main.py.
    """
    logger.info("Expiry worker starting — runs every 60 minutes")
    while True:
        try:
            await run_expiry_check()
        except Exception as e:
            logger.error(f"Expiry worker error: {e}")
        await asyncio.sleep(3600)
