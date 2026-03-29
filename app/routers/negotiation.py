import logging
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from app.models.case import CaseStatus
from app.models.negotiation import (
    SubmitOfferRequest,
    ProposalResponseRequest,
    ProposalDecision,
    OfferType,
)
from app.services.cosmos_service import cosmos_service
from app.services.email_service import email_service
from app.core.dependencies import get_current_user, get_current_user_optional
from app.core.exceptions import CaseNotFound, UnauthorizedAccess, InvalidCaseState

router = APIRouter()
logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════
# CLAIMANT SUBMITS OFFER
# ══════════════════════════════════════════════════════════════

@router.post("/submit-claimant-offer")
async def submit_claimant_offer(
    body: SubmitOfferRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
):
    """
    Claimant submits their offer for the current round.
    If respondent has already submitted → triggers AI mediation.
    If respondent has not submitted → waits.
    """
    case = cosmos_service.get_case(body.case_id)
    if not case:
        raise CaseNotFound(body.case_id)
    if case["claimant_email"] != current_user["email"]:
        raise UnauthorizedAccess()

    # Case must be NEGOTIATING
    if case["status"] not in [
        CaseStatus.NEGOTIATING.value,
        CaseStatus.ROUND_PENDING.value,
        CaseStatus.ROUND_FAILED.value,
    ]:
        raise HTTPException(
            status_code=409,
            detail=f"Case must be in NEGOTIATING state. Current: {case['status']}",
        )

    track = case.get("track", "monetary_civil")
    round_number = body.round_number or case.get("current_round", 0) or 1

    # Get or create negotiation document
    neg = cosmos_service.get_negotiation_by_case(body.case_id)
    if not neg:
        offer_type = (
            OfferType.ACTION_LIST.value
            if track == "non_monetary"
            else OfferType.MONETARY.value
        )
        neg = cosmos_service.create_negotiation(body.case_id, {
            "offer_type": offer_type,
            "zopa_min":   case.get("analytics_data", {}).get("zopa_min"),
            "zopa_max":   case.get("analytics_data", {}).get("zopa_max"),
        })

    # Check if this round already exists
    existing_round = cosmos_service.get_round(neg["id"], round_number)

    now = datetime.now(timezone.utc).isoformat()

    if not existing_round:
        # First offer in this round — create the round
        round_data = {
            "round_number":       round_number,
            "offer_type":         neg["offer_type"],
            "claimant_offer":     body.offer_amount,
            "claimant_demands":   body.demands,
            "claimant_offer_at":  now,
            "claimant_decision":  ProposalDecision.PENDING.value,
            "respondent_decision": ProposalDecision.PENDING.value,
        }
        cosmos_service.add_round_to_negotiation(neg["id"], round_data)
        cosmos_service.update_case(body.case_id, {"current_round": round_number})
        cosmos_service.transition_case(body.case_id, CaseStatus.ROUND_PENDING)

        return {
            "message":      "Offer submitted. Waiting for respondent to submit their offer.",
            "round_number": round_number,
            "status":       "ROUND_PENDING",
        }

    else:
        # Round exists — update claimant offer
        cosmos_service.update_round_in_negotiation(neg["id"], round_number, {
            "claimant_offer":    body.offer_amount,
            "claimant_demands":  body.demands,
            "claimant_offer_at": now,
        })

        # Check if respondent already submitted
        if existing_round.get("respondent_offer") is not None or \
           existing_round.get("respondent_commitments"):
            # Both offers received → trigger AI mediation
            background_tasks.add_task(
                _run_mediation,
                body.case_id,
                neg["id"],
                round_number,
            )
            return {
                "message":      "Both offers received. AI Mediator is generating proposal.",
                "round_number": round_number,
                "status":       "MEDIATING",
            }

        return {
            "message":      "Offer submitted. Waiting for respondent.",
            "round_number": round_number,
            "status":       "ROUND_PENDING",
        }


# ══════════════════════════════════════════════════════════════
# RESPONDENT SUBMITS OFFER
# ══════════════════════════════════════════════════════════════

@router.post("/submit-respondent-offer")
async def submit_respondent_offer(
    body: SubmitOfferRequest,
    background_tasks: BackgroundTasks,
):
    """
    Respondent submits their offer for the current round.
    No auth required — respondent accesses via secure email link.
    """
    case = cosmos_service.get_case(body.case_id)
    if not case:
        raise CaseNotFound(body.case_id)

    valid_states = [
        CaseStatus.INVITE_SENT.value,
        CaseStatus.RESPONDENT_VIEWED.value,
        CaseStatus.NEGOTIATING.value,
        CaseStatus.ROUND_PENDING.value,
        CaseStatus.ROUND_FAILED.value,
    ]
    if case["status"] not in valid_states:
        raise HTTPException(
            status_code=409,
            detail=f"Case is not accepting offers. Status: {case['status']}",
        )

    # Move through intermediate states to reach NEGOTIATING
    if case["status"] == CaseStatus.INVITE_SENT.value:
        cosmos_service.transition_case(body.case_id, CaseStatus.RESPONDENT_VIEWED)
        case = cosmos_service.get_case(body.case_id)

    if case["status"] == CaseStatus.RESPONDENT_VIEWED.value:
        cosmos_service.transition_case(body.case_id, CaseStatus.NEGOTIATING)
        case = cosmos_service.get_case(body.case_id)

    track        = case.get("track", "monetary_civil")
    round_number = case.get("current_round", 0)
    if round_number == 0:
        round_number = 1

    neg = cosmos_service.get_negotiation_by_case(body.case_id)
    if not neg:
        offer_type = (
            OfferType.ACTION_LIST.value
            if track == "non_monetary"
            else OfferType.MONETARY.value
        )
        neg = cosmos_service.create_negotiation(body.case_id, {
            "offer_type": offer_type,
            "zopa_min":   (case.get("analytics_data") or {}).get("zopa_min"),
            "zopa_max":   (case.get("analytics_data") or {}).get("zopa_max"),
        })
        cosmos_service.update_case(body.case_id, {"negotiation_id": neg["id"]})

    existing_round = cosmos_service.get_round(neg["id"], round_number)
    now            = datetime.now(timezone.utc).isoformat()

    if not existing_round:
        round_data = {
            "round_number":           round_number,
            "offer_type":             neg["offer_type"],
            "respondent_offer":       body.offer_amount,
            "respondent_commitments": body.commitments,
            "respondent_offer_at":    now,
            "claimant_decision":      ProposalDecision.PENDING.value,
            "respondent_decision":    ProposalDecision.PENDING.value,
        }
        cosmos_service.add_round_to_negotiation(neg["id"], round_data)
        cosmos_service.update_case(body.case_id, {"current_round": round_number})

        try:
            cosmos_service.transition_case(body.case_id, CaseStatus.ROUND_PENDING)
        except Exception:
            pass  # Already in correct state

        email_service.send_respondent_offer_notification(
            to_email=case["claimant_email"],
            claimant_name=case["claimant_name"],
            case_id=body.case_id,
            round_num=round_number,
        )

        return {
            "message":      "Offer submitted. Waiting for claimant to submit their offer.",
            "round_number": round_number,
            "status":       "ROUND_PENDING",
        }

    else:
        cosmos_service.update_round_in_negotiation(neg["id"], round_number, {
            "respondent_offer":       body.offer_amount,
            "respondent_commitments": body.commitments,
            "respondent_offer_at":    now,
        })

        claimant_submitted = (
            existing_round.get("claimant_offer") is not None or
            bool(existing_round.get("claimant_demands"))
        )

        if claimant_submitted:
            background_tasks.add_task(
                _run_mediation, body.case_id, neg["id"], round_number
            )
            return {
                "message":      "Both offers received. AI Mediator is generating proposal.",
                "round_number": round_number,
                "status":       "MEDIATING",
            }

        return {
            "message":      "Offer submitted. Waiting for claimant.",
            "round_number": round_number,
            "status":       "ROUND_PENDING",
        }


# ══════════════════════════════════════════════════════════════
# AI MEDIATION BACKGROUND TASK
# ══════════════════════════════════════════════════════════════

async def _run_mediation(case_id: str, neg_id: str, round_number: int):
    """
    Background task — runs the AI Negotiation Agent and issues proposal.
    Triggered when both parties have submitted offers for the round.
    """
    try:
        from app.agents.negotiation_agent import run_negotiation_agent

        case = cosmos_service.get_case(case_id)
        neg  = cosmos_service.negotiations.read_item(
            item=neg_id, partition_key=neg_id
        )
        current_round = cosmos_service.get_round(neg_id, round_number)

        claimant_offer   = current_round.get("claimant_offer") or \
                           current_round.get("claimant_demands")
        respondent_offer = current_round.get("respondent_offer") or \
                           current_round.get("respondent_commitments")

        # Run AI Negotiation Agent
        proposal = await run_negotiation_agent(
            case=case,
            negotiation=neg,
            round_number=round_number,
            claimant_offer=claimant_offer,
            respondent_offer=respondent_offer,
        )

        # Store proposal on round
        now = datetime.now(timezone.utc).isoformat()
        cosmos_service.update_round_in_negotiation(neg_id, round_number, {
            "ai_proposed_amount":  proposal.get("proposed_amount"),
            "ai_proposed_actions": proposal.get("proposed_actions"),
            "ai_reasoning":        proposal.get("reasoning"),
            "ai_pressure_points": {
                "claimant":   proposal.get("claimant_pressure"),
                "respondent": proposal.get("respondent_pressure"),
            },
            "proposal_issued_at": now,
        })

        # Update negotiation document
        cosmos_service.update_negotiation(neg_id, {
            "last_proposal": proposal,
        })

        # Transition case to PROPOSAL_ISSUED
        cosmos_service.transition_case(case_id, CaseStatus.PROPOSAL_ISSUED)

        # Send email to both parties
        track           = case.get("track", "monetary_civil")
        proposed_amount = proposal.get("proposed_amount", 0)
        reasoning       = proposal.get("reasoning", "")
        portal_url      = f"{case.get('routing', {}).get('base_url', '')}/respond/{case_id}"

        email_service.send_proposal(
            to_email=case["claimant_email"],
            party_name=case["claimant_name"],
            case_id=case_id,
            round_num=round_number,
            proposed_amount=proposed_amount,
            reasoning=reasoning,
            portal_url=portal_url,
        )
        email_service.send_proposal(
            to_email=case["respondent_email"],
            party_name=case["respondent_name"],
            case_id=case_id,
            round_num=round_number,
            proposed_amount=proposed_amount,
            reasoning=reasoning,
            portal_url=portal_url,
        )

        logger.info(
            f"Mediation complete | case_id={case_id} | "
            f"round={round_number} | proposed={proposed_amount}"
        )

    except Exception as e:
        logger.error(f"Mediation failed | case_id={case_id} | error={e}")
        cosmos_service.update_case(case_id, {"mediation_error": str(e)})


# ══════════════════════════════════════════════════════════════
# ACCEPT / REJECT PROPOSAL
# ══════════════════════════════════════════════════════════════

@router.post("/proposal-response")
async def proposal_response(
    body: ProposalResponseRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user_optional),
):
    """
    Either party accepts or rejects the AI proposal.
    Claimant: authenticated via JWT.
    Respondent: no auth required (respondent portal).
    When both respond → check outcome.
    """
    case = cosmos_service.get_case(body.case_id)
    if not case:
        raise CaseNotFound(body.case_id)

    if case["status"] != CaseStatus.PROPOSAL_ISSUED.value:
        raise HTTPException(
            status_code=409,
            detail=f"No active proposal. Case status: {case['status']}",
        )

    # Validate party
    if body.party == "claimant":
        if current_user and current_user["email"] != case["claimant_email"]:
            raise UnauthorizedAccess()
    elif body.party == "respondent":
        pass  # No auth for respondent
    else:
        raise HTTPException(status_code=400, detail="party must be 'claimant' or 'respondent'")

    neg    = cosmos_service.get_negotiation_by_case(body.case_id)
    if not neg:
        raise HTTPException(status_code=404, detail="Negotiation not found.")

    round_number = case.get("current_round", 1)
    now          = datetime.now(timezone.utc).isoformat()

    # Update decision for this party
    decision_field = f"{body.party}_decision"
    decided_at     = f"{body.party}_decided_at"
    cosmos_service.update_round_in_negotiation(neg["id"], round_number, {
        decision_field: body.decision.value,
        decided_at:     now,
    })

    # Refresh round to check both decisions
    updated_round = cosmos_service.get_round(neg["id"], round_number)
    cl_decision   = updated_round.get("claimant_decision",  ProposalDecision.PENDING.value)
    rs_decision   = updated_round.get("respondent_decision", ProposalDecision.PENDING.value)

    logger.info(
        f"Proposal response | case_id={body.case_id} | "
        f"party={body.party} | decision={body.decision.value} | "
        f"claimant={cl_decision} | respondent={rs_decision}"
    )

    # ── Both have responded ────────────────────────────────────
    if (cl_decision != ProposalDecision.PENDING.value and
            rs_decision != ProposalDecision.PENDING.value):

        if (cl_decision == ProposalDecision.ACCEPT.value and
                rs_decision == ProposalDecision.ACCEPT.value):
            # BOTH ACCEPT → SETTLE
            background_tasks.add_task(_handle_settlement, body.case_id)
            return {
                "message": "Both parties accepted. Generating settlement agreement.",
                "outcome": "SETTLED",
            }

        else:
            # AT LEAST ONE REJECTS
            max_rounds = case.get("max_rounds", 3)

            if round_number >= max_rounds:
                # ESCALATE
                background_tasks.add_task(_handle_escalation, body.case_id)
                return {
                    "message": "3 rounds completed without settlement. Generating court file.",
                    "outcome": "ESCALATED",
                }
            else:
                # NEXT ROUND
                background_tasks.add_task(
                    _start_next_round, body.case_id, round_number + 1
                )
                return {
                    "message": f"Proposal rejected. Round {round_number + 1} is now open.",
                    "outcome": "NEXT_ROUND",
                    "next_round": round_number + 1,
                }

    # ── Only one party has responded ──────────────────────────
    return {
        "message": f"Your decision recorded. Waiting for the other party.",
        "your_decision": body.decision.value,
    }


# ══════════════════════════════════════════════════════════════
# OUTCOME HANDLERS
# ══════════════════════════════════════════════════════════════

async def _handle_settlement(case_id: str):
    """Called when both parties accept. Generates settlement PDF and notifies."""
    try:
        from app.agents.document_agent import generate_settlement_agreement

        case = cosmos_service.get_case(case_id)
        neg  = cosmos_service.get_negotiation_by_case(case_id)

        # Get the settled amount from the last round
        round_number = case.get("current_round", 1)
        last_round   = cosmos_service.get_round(neg["id"], round_number)
        settled_amount = last_round.get("ai_proposed_amount", 0) or 0

        # Transition → SETTLING
        cosmos_service.transition_case(case_id, CaseStatus.SETTLING, {
            "settled_amount": settled_amount,
        })

        # Generate settlement PDF
        settlement_url = await generate_settlement_agreement(case, settled_amount)

        # Transition → SETTLED
        cosmos_service.transition_case(case_id, CaseStatus.SETTLED, {
            "settlement_url":  settlement_url,
            "settled_amount":  settled_amount,
        })

        # Email both parties
        for email, name in [
            (case["claimant_email"],  case["claimant_name"]),
            (case["respondent_email"], case["respondent_name"]),
        ]:
            email_service.send_settlement_confirmation(
                to_email=email,
                party_name=name,
                case_id=case_id,
                settled_amount=settled_amount,
                download_url=settlement_url,
            )

        logger.info(f"Case settled | case_id={case_id} | amount={settled_amount}")

    except Exception as e:
        logger.error(f"Settlement handling failed | case_id={case_id} | error={e}")


async def _handle_escalation(case_id: str):
    """Called after 3 rounds with no settlement. Generates court file and notifies."""
    try:
        case = cosmos_service.get_case(case_id)

        # Transition → ESCALATING
        cosmos_service.transition_case(case_id, CaseStatus.ESCALATING)

        # Court file already generated at analysis time — get its URL
        docs_data   = case.get("documents_data") or {}
        court_url   = docs_data.get("court_file_url", "")

        # Also generate mediation certificate showing 3 rounds were attempted
        from app.agents.document_agent import _generate_mediation_certificate
        from app.services.blob_service import blob_service

        cert_bytes = _generate_mediation_certificate(case)
        cert_blob  = f"mediation_cert_{case_id}.pdf"
        blob_service.upload("pdfs", cert_blob, cert_bytes)
        cert_url   = blob_service.generate_download_url("pdfs", cert_blob)

        # Transition → ESCALATED
        cosmos_service.transition_case(case_id, CaseStatus.ESCALATED, {
            "mediation_certificate_url": cert_url,
        })

        # Email both parties
        for email, name in [
            (case["claimant_email"],  case["claimant_name"]),
            (case["respondent_email"], case["respondent_name"]),
        ]:
            email_service.send_escalation_notice(
                to_email=email,
                party_name=name,
                case_id=case_id,
                download_url=court_url or cert_url,
            )

        logger.info(f"Case escalated | case_id={case_id}")

    except Exception as e:
        logger.error(f"Escalation handling failed | case_id={case_id} | error={e}")


async def _start_next_round(case_id: str, next_round_number: int):
    """Called after rejection when rounds remain. Opens the next round."""
    try:
        from app.config import settings

        case = cosmos_service.get_case(case_id)

        # Transition → ROUND_FAILED → NEGOTIATING
        cosmos_service.transition_case(case_id, CaseStatus.ROUND_FAILED)
        cosmos_service.transition_case(case_id, CaseStatus.NEGOTIATING)

        portal_url = f"{settings.BASE_URL}/respond/{case_id}"

        # Email respondent to submit next round offer
        email_service.send_next_round_invite(
            to_email=case["respondent_email"],
            party_name=case["respondent_name"],
            case_id=case_id,
            round_num=next_round_number,
            portal_url=portal_url,
        )

        # Email claimant too
        email_service.send_next_round_invite(
            to_email=case["claimant_email"],
            party_name=case["claimant_name"],
            case_id=case_id,
            round_num=next_round_number,
            portal_url=portal_url,
        )

        logger.info(f"Next round started | case_id={case_id} | round={next_round_number}")

    except Exception as e:
        logger.error(f"Next round start failed | case_id={case_id} | error={e}")


# ══════════════════════════════════════════════════════════════
# STATUS ENDPOINTS
# ══════════════════════════════════════════════════════════════

@router.get("/status/{case_id}")
async def get_negotiation_status(
    case_id: str,
    current_user: dict = Depends(get_current_user_optional),
):
    """Get current negotiation state for polling."""
    case = cosmos_service.get_case(case_id)
    if not case:
        raise CaseNotFound(case_id)

    neg          = cosmos_service.get_negotiation_by_case(case_id)
    round_number = case.get("current_round", 0)

    if not neg:
        return {
            "case_id":      case_id,
            "status":       case["status"],
            "current_round": round_number,
            "negotiation":  None,
        }

    current_round = cosmos_service.get_round(neg["id"], round_number) if round_number > 0 else None

    return {
        "case_id":       case_id,
        "status":        case["status"],
        "current_round": round_number,
        "max_rounds":    case.get("max_rounds", 3),
        "track":         case.get("track"),
        "negotiation": {
            "id":          neg["id"],
            "offer_type":  neg.get("offer_type"),
            "rounds_done": len(neg.get("rounds", [])),
        },
        "current_round_detail": {
            "claimant_submitted":    current_round.get("claimant_offer") is not None or
                                     bool(current_round.get("claimant_demands"))
                                     if current_round else False,
            "respondent_submitted":  current_round.get("respondent_offer") is not None or
                                     bool(current_round.get("respondent_commitments"))
                                     if current_round else False,
            "proposal_issued":       bool(current_round.get("ai_proposed_amount") or
                                          current_round.get("ai_proposed_actions"))
                                     if current_round else False,
            "proposed_amount":       current_round.get("ai_proposed_amount")
                                     if current_round else None,
            "ai_reasoning":          current_round.get("ai_reasoning")
                                     if current_round else None,
            "claimant_decision":     current_round.get("claimant_decision")
                                     if current_round else None,
            "respondent_decision":   current_round.get("respondent_decision")
                                     if current_round else None,
        } if current_round else None,
    }
