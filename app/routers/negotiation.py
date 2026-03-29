import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from app.core.dependencies import get_current_user, get_current_user_optional
from app.core.exceptions import CaseNotFound, UnauthorizedAccess
from app.core.negotiation_rules import check_direct_settlement, next_waiting_state, pending_proof_requests, resolve_round_outcome
from app.models.case import CaseStatus
from app.models.negotiation import OfferType, ProofResponseRequest, ProposalDecision, ProposalResponseRequest, SubmitOfferRequest
from app.services.cosmos_service import cosmos_service
from app.services.email_service import email_service

router = APIRouter()
logger = logging.getLogger(__name__)

NEGOTIATION_ENTRY_STATES = {
    CaseStatus.RESPONDENT_VIEWED.value,
    CaseStatus.NEGOTIATION_OPEN.value,
    CaseStatus.WAITING_FOR_CLAIMANT.value,
    CaseStatus.WAITING_FOR_RESPONDENT.value,
    CaseStatus.PROOF_REQUESTED.value,
    CaseStatus.PROOF_RESPONSE_PENDING.value,
    CaseStatus.MEDIATOR_REVIEW.value,
    CaseStatus.PROPOSAL_ISSUED.value,
    CaseStatus.SETTLEMENT_PENDING_CONFIRMATION.value,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _normalize_list(values) -> list[str]:
    return [str(v).strip() for v in (values or []) if str(v).strip()]


def _get_track_offer_type(case: dict) -> str:
    return OfferType.ACTION_LIST.value if case.get("track") == "non_monetary" else OfferType.MONETARY.value


def _ensure_negotiation(case: dict) -> dict:
    neg = cosmos_service.get_negotiation_by_case(case["id"])
    if neg:
        return neg
    neg = cosmos_service.create_negotiation(
        case["id"],
        {
            "offer_type": _get_track_offer_type(case),
            "zopa_min": (case.get("analytics_data") or {}).get("zopa_min"),
            "zopa_max": (case.get("analytics_data") or {}).get("zopa_max"),
            "proof_requests": [],
            "shared_notes": [],
            "current_waiting_on": None,
        },
    )
    cosmos_service.update_case(case["id"], {"negotiation_id": neg["id"]})
    return neg


def _default_round(neg: dict, round_number: int) -> dict:
    return {
        "round_number": round_number,
        "offer_type": neg["offer_type"],
        "claimant": {
            "amount": None,
            "actions": [],
            "explanation": None,
            "proof_note": None,
            "requested_proof": [],
            "conditions": [],
            "decision": ProposalDecision.PENDING.value,
            "decision_reason": None,
            "submitted_at": None,
            "decided_at": None,
        },
        "respondent": {
            "amount": None,
            "actions": [],
            "explanation": None,
            "proof_note": None,
            "requested_proof": [],
            "conditions": [],
            "decision": ProposalDecision.PENDING.value,
            "decision_reason": None,
            "submitted_at": None,
            "decided_at": None,
        },
        "ai_proposed_amount": None,
        "ai_proposed_actions": None,
        "ai_reasoning": None,
        "ai_pressure_points": None,
        "mediator_summary": None,
        "unresolved_proof_request_ids": [],
        "immediate_outcome": None,
        "settlement_candidate_amount": None,
        "settlement_candidate_reason": None,
        "proposal_issued_at": None,
        "round_deadline": None,
    }


def _get_or_create_round(neg: dict, round_number: int) -> dict:
    round_doc = cosmos_service.get_round(neg["id"], round_number)
    if round_doc:
        return round_doc
    round_doc = _default_round(neg, round_number)
    cosmos_service.add_round_to_negotiation(neg["id"], round_doc)
    return round_doc


def _save_round(neg_id: str, round_doc: dict) -> None:
    cosmos_service.upsert_round_in_negotiation(neg_id, round_doc["round_number"], round_doc)


def _append_shared_note(neg_id: str, round_number: int, party: str, note_type: str, text: str | None) -> None:
    if not text or not text.strip():
        return
    cosmos_service.append_shared_note(
        neg_id,
        {
            "id": _new_id("note"),
            "round_number": round_number,
            "party": party,
            "note_type": note_type,
            "text": text.strip(),
            "created_at": _now(),
        },
    )


def _record_proof_requests(neg_id: str, round_doc: dict, requested_by: str, items: list[str]) -> list[str]:
    requested_from = "respondent" if requested_by == "claimant" else "claimant"
    created_ids = []
    for item in _normalize_list(items):
        proof_id = _new_id("proof")
        cosmos_service.append_proof_request(
            neg_id,
            {
                "id": proof_id,
                "round_number": round_doc["round_number"],
                "requested_by": requested_by,
                "requested_from": requested_from,
                "request_text": item,
                "status": "PENDING",
                "created_at": _now(),
                "visible_to_both_parties": True,
                "response_text": None,
                "file_refs": [],
                "response_at": None,
            },
        )
        created_ids.append(proof_id)
        _append_shared_note(neg_id, round_doc["round_number"], requested_by, "proof_request", f"Requested proof from {requested_from}: {item}")
    round_doc["unresolved_proof_request_ids"] = sorted(set((round_doc.get("unresolved_proof_request_ids") or []) + created_ids))
    return created_ids


def _apply_case_status(case: dict, new_status: CaseStatus, extra_updates: dict | None = None) -> dict:
    if case["status"] == new_status.value:
        return cosmos_service.update_case(case["id"], extra_updates or {})
    return cosmos_service.transition_case(case["id"], new_status, extra_updates or {})


def _ensure_negotiation_open(case: dict) -> dict:
    current = cosmos_service.get_case(case["id"])
    if current["status"] == CaseStatus.INVITE_SENT.value:
        current = cosmos_service.transition_case(case["id"], CaseStatus.RESPONDENT_VIEWED)
    if current["status"] == CaseStatus.RESPONDENT_VIEWED.value:
        current = cosmos_service.transition_case(case["id"], CaseStatus.NEGOTIATION_OPEN)
    return current


def _next_waiting_state(round_doc: dict, neg: dict) -> tuple[CaseStatus, str | None]:
    return next_waiting_state(round_doc, neg)


def _open_direct_settlement(case: dict, neg: dict, round_doc: dict, amount: float, reason: str) -> dict:
    round_doc["ai_proposed_amount"] = amount
    round_doc["ai_reasoning"] = reason
    round_doc["settlement_candidate_amount"] = amount
    round_doc["settlement_candidate_reason"] = reason
    round_doc["immediate_outcome"] = "DIRECT_SETTLEMENT"
    round_doc["proposal_issued_at"] = _now()
    _save_round(neg["id"], round_doc)
    cosmos_service.update_negotiation(neg["id"], {"current_waiting_on": "both"})
    return _apply_case_status(
        case,
        CaseStatus.SETTLEMENT_PENDING_CONFIRMATION,
        {
            "current_round": round_doc["round_number"],
            "action_required_by": "both",
            "direct_settlement_amount": amount,
            "direct_settlement_reason": reason,
        },
    )


def _check_direct_settlement(case: dict, neg: dict, round_doc: dict):
    return check_direct_settlement(case, neg, round_doc)


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


def _resolve_round_outcome(round_number: int, max_rounds: int, claimant_decision: str, respondent_decision: str, rejection_reason: str) -> str:
    return resolve_round_outcome(round_number, max_rounds, claimant_decision, respondent_decision, rejection_reason)


async def _handle_offer_submission(case: dict, neg: dict, round_doc: dict, body: SubmitOfferRequest, party: str) -> dict:
    party_doc = round_doc[party]
    amount = body.offer_amount
    actions = _normalize_list(body.demands if party == "claimant" else body.commitments)
    party_doc.update(
        {
            "amount": amount,
            "actions": actions,
            "explanation": body.explanation.strip() if body.explanation else None,
            "proof_note": body.proof_note.strip() if body.proof_note else None,
            "requested_proof": _normalize_list(body.requested_proof),
            "conditions": _normalize_list(body.conditions),
            "submitted_at": _now(),
        }
    )
    round_doc[party] = party_doc
    _append_shared_note(neg["id"], round_doc["round_number"], party, "explanation", party_doc.get("explanation"))
    _append_shared_note(neg["id"], round_doc["round_number"], party, "proof_note", party_doc.get("proof_note"))
    if party_doc.get("conditions"):
        _append_shared_note(neg["id"], round_doc["round_number"], party, "conditions", "; ".join(party_doc["conditions"]))
    if party_doc.get("requested_proof"):
        _record_proof_requests(neg["id"], round_doc, party, party_doc["requested_proof"])

    direct = _check_direct_settlement(case, neg, round_doc)
    if direct:
        _save_round(neg["id"], round_doc)
        updated_case = _open_direct_settlement(case, neg, round_doc, direct[0], direct[1])
        return {
            "message": direct[1],
            "round_number": round_doc["round_number"],
            "status": updated_case["status"],
            "action_required_by": "both",
            "settlement_candidate_amount": direct[0],
        }

    _save_round(neg["id"], round_doc)
    neg = cosmos_service.get_negotiation_by_case(case["id"])
    next_status, waiting_on = _next_waiting_state(round_doc, neg)
    if next_status == CaseStatus.MEDIATOR_REVIEW:
        _apply_case_status(case, CaseStatus.MEDIATOR_REVIEW, {"current_round": round_doc["round_number"], "action_required_by": None})
        cosmos_service.update_negotiation(neg["id"], {"current_waiting_on": None})
        return {
            "message": "Both parties have submitted. The AI mediator is preparing a proposal.",
            "round_number": round_doc["round_number"],
            "status": CaseStatus.MEDIATOR_REVIEW.value,
            "action_required_by": None,
        }

    updated_case = _apply_case_status(
        case,
        next_status,
        {"current_round": round_doc["round_number"], "action_required_by": waiting_on},
    )
    cosmos_service.update_negotiation(neg["id"], {"current_waiting_on": waiting_on})
    return {
        "message": f"{party.title()} submission recorded. {updated_case['status']} now active.",
        "round_number": round_doc["round_number"],
        "status": updated_case["status"],
        "action_required_by": waiting_on,
    }


@router.post("/submit-claimant-offer")
async def submit_claimant_offer(
    body: SubmitOfferRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
):
    case = cosmos_service.get_case(body.case_id)
    if not case:
        raise CaseNotFound(body.case_id)
    if case["claimant_email"] != current_user["email"]:
        raise UnauthorizedAccess()
    if case["status"] not in NEGOTIATION_ENTRY_STATES:
        raise HTTPException(status_code=409, detail=f"Case is not open for claimant action. Current: {case['status']}")

    case = _ensure_negotiation_open(case)
    neg = _ensure_negotiation(case)
    round_number = body.round_number or case.get("current_round") or 1
    round_doc = _get_or_create_round(neg, round_number)
    result = await _handle_offer_submission(case, neg, round_doc, body, "claimant")
    if result["status"] == CaseStatus.MEDIATOR_REVIEW.value:
        background_tasks.add_task(_run_mediation, body.case_id, neg["id"], round_number)
    return result


@router.post("/submit-respondent-offer")
async def submit_respondent_offer(
    body: SubmitOfferRequest,
    background_tasks: BackgroundTasks,
):
    case = cosmos_service.get_case(body.case_id)
    if not case:
        raise CaseNotFound(body.case_id)
    if case["status"] not in (NEGOTIATION_ENTRY_STATES | {CaseStatus.INVITE_SENT.value}):
        raise HTTPException(status_code=409, detail=f"Case is not accepting respondent action. Current: {case['status']}")

    case = _ensure_negotiation_open(case)
    neg = _ensure_negotiation(case)
    round_number = body.round_number or case.get("current_round") or 1
    round_doc = _get_or_create_round(neg, round_number)
    result = await _handle_offer_submission(case, neg, round_doc, body, "respondent")
    if result["status"] == CaseStatus.MEDIATOR_REVIEW.value:
        background_tasks.add_task(_run_mediation, body.case_id, neg["id"], round_number)
    else:
        email_service.send_respondent_offer_notification(
            to_email=case["claimant_email"],
            claimant_name=case["claimant_name"],
            case_id=body.case_id,
            round_num=round_number,
        )
    return result


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

    proof_item = next((item for item in neg.get("proof_requests", []) if item["id"] == body.request_id), None)
    if not proof_item:
        raise HTTPException(status_code=404, detail="Proof request not found.")
    if proof_item["requested_from"] != body.party:
        raise HTTPException(status_code=403, detail="This proof request is not assigned to your side.")

    cosmos_service.update_proof_request(
        neg["id"],
        body.request_id,
        {
            "status": "RESPONDED",
            "response_text": body.response_text.strip(),
            "file_refs": _normalize_list(body.file_refs),
            "response_at": _now(),
        },
    )

    round_doc = cosmos_service.get_round(neg["id"], body.round_number)
    refreshed_neg = cosmos_service.get_negotiation_by_case(body.case_id)
    round_doc["unresolved_proof_request_ids"] = [item["id"] for item in _pending_proof_requests(refreshed_neg, body.round_number)]
    _save_round(neg["id"], round_doc)
    _append_shared_note(neg["id"], body.round_number, body.party, "proof_response", body.response_text)

    refreshed_case = cosmos_service.get_case(body.case_id)
    next_status, waiting_on = _next_waiting_state(round_doc, refreshed_neg)
    updated_case = _apply_case_status(
        refreshed_case,
        next_status,
        {"current_round": body.round_number, "action_required_by": waiting_on},
    )
    cosmos_service.update_negotiation(refreshed_neg["id"], {"current_waiting_on": waiting_on})
    return {
        "message": "Proof response recorded and shared with the other party.",
        "status": updated_case["status"],
        "action_required_by": waiting_on,
    }


async def _run_mediation(case_id: str, neg_id: str, round_number: int):
    try:
        from app.agents.negotiation_agent import run_negotiation_agent

        case = cosmos_service.get_case(case_id)
        neg = cosmos_service.negotiations.read_item(item=neg_id, partition_key=neg_id)
        round_doc = cosmos_service.get_round(neg_id, round_number)
        if not round_doc:
            raise RuntimeError("Negotiation round not found for mediation.")

        proposal = await run_negotiation_agent(
            case=case,
            negotiation=neg,
            round_number=round_number,
            claimant_offer=(round_doc.get("claimant") or {}).get("amount") or (round_doc.get("claimant") or {}).get("actions"),
            respondent_offer=(round_doc.get("respondent") or {}).get("amount") or (round_doc.get("respondent") or {}).get("actions"),
        )

        round_doc.update(
            {
                "ai_proposed_amount": proposal.get("proposed_amount"),
                "ai_proposed_actions": proposal.get("proposed_actions"),
                "ai_reasoning": proposal.get("reasoning"),
                "ai_pressure_points": {
                    "claimant": proposal.get("claimant_pressure"),
                    "respondent": proposal.get("respondent_pressure"),
                },
                "mediator_summary": proposal.get("mediator_notes"),
                "proposal_issued_at": _now(),
            }
        )
        _save_round(neg_id, round_doc)
        cosmos_service.update_negotiation(neg_id, {"last_proposal": proposal, "current_waiting_on": "both"})
        cosmos_service.transition_case(case_id, CaseStatus.PROPOSAL_ISSUED, {"current_round": round_number, "action_required_by": "both"})

        portal_url = f"{case.get('routing', {}).get('base_url', '')}/respond/{case_id}"
        proposed_amount = proposal.get("proposed_amount", 0) or 0
        reasoning = proposal.get("reasoning", "")
        for email, name in [
            (case["claimant_email"], case["claimant_name"]),
            (case["respondent_email"], case["respondent_name"]),
        ]:
            email_service.send_proposal(
                to_email=email,
                party_name=name,
                case_id=case_id,
                round_num=round_number,
                proposed_amount=proposed_amount,
                reasoning=reasoning,
                portal_url=portal_url,
            )
    except Exception as exc:
        logger.error("Mediation failed | case_id=%s | error=%s", case_id, exc)
        cosmos_service.update_case(case_id, {"mediation_error": str(exc)})


@router.post("/proposal-response")
async def proposal_response(
    body: ProposalResponseRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user_optional),
):
    case = cosmos_service.get_case(body.case_id)
    if not case:
        raise CaseNotFound(body.case_id)
    if case["status"] not in {
        CaseStatus.PROPOSAL_ISSUED.value,
        CaseStatus.SETTLEMENT_PENDING_CONFIRMATION.value,
        CaseStatus.WAITING_FOR_CLAIMANT.value,
        CaseStatus.WAITING_FOR_RESPONDENT.value,
    }:
        raise HTTPException(status_code=409, detail=f"No active proposal. Case status: {case['status']}")

    if body.party == "claimant":
        if not current_user or current_user["email"] != case["claimant_email"]:
            raise UnauthorizedAccess()
    elif body.party != "respondent":
        raise HTTPException(status_code=400, detail="party must be 'claimant' or 'respondent'")

    neg = cosmos_service.get_negotiation_by_case(body.case_id)
    if not neg:
        raise HTTPException(status_code=404, detail="Negotiation not found.")
    round_doc = cosmos_service.get_round(neg["id"], body.round_number)
    if not round_doc:
        raise HTTPException(status_code=404, detail="Negotiation round not found.")

    round_doc[body.party]["decision"] = body.decision.value
    round_doc[body.party]["decision_reason"] = body.reason.strip() if body.reason else None
    round_doc[body.party]["decided_at"] = _now()
    _save_round(neg["id"], round_doc)
    _append_shared_note(neg["id"], body.round_number, body.party, "decision_reason", body.reason)

    claimant_decision = round_doc["claimant"]["decision"]
    respondent_decision = round_doc["respondent"]["decision"]
    if claimant_decision != ProposalDecision.PENDING.value and respondent_decision != ProposalDecision.PENDING.value:
        if claimant_decision == ProposalDecision.ACCEPT.value and respondent_decision == ProposalDecision.ACCEPT.value:
            background_tasks.add_task(_handle_settlement, body.case_id)
            return {"message": "Both parties accepted. Generating settlement agreement.", "outcome": "SETTLED"}

        rejection_reason = " ".join(filter(None, [round_doc["claimant"].get("decision_reason"), round_doc["respondent"].get("decision_reason")])).lower()
        outcome = _resolve_round_outcome(
            body.round_number,
            case.get("max_rounds", 3),
            claimant_decision,
            respondent_decision,
            rejection_reason,
        )
        if outcome == "PROOF_REQUESTED":
            requested_from = "respondent" if "claimant" in rejection_reason else "claimant"
            cosmos_service.append_proof_request(
                neg["id"],
                {
                    "id": _new_id("proof"),
                    "round_number": body.round_number,
                    "requested_by": "claimant" if requested_from == "respondent" else "respondent",
                    "requested_from": requested_from,
                    "request_text": rejection_reason or "Additional proof requested before settlement decision.",
                    "status": "PENDING",
                    "created_at": _now(),
                    "visible_to_both_parties": True,
                    "response_text": None,
                    "file_refs": [],
                    "response_at": None,
                },
            )
            updated_case = _apply_case_status(case, CaseStatus.PROOF_REQUESTED, {"current_round": body.round_number, "action_required_by": requested_from})
            cosmos_service.update_negotiation(neg["id"], {"current_waiting_on": requested_from})
            return {"message": "Proposal decision recorded. Case has moved into proof exchange.", "outcome": "PROOF_REQUESTED", "status": updated_case["status"]}

        if outcome == "ESCALATED":
            background_tasks.add_task(_handle_escalation, body.case_id)
            return {"message": "Maximum rounds reached without settlement. Escalation has started.", "outcome": "ESCALATED"}

        background_tasks.add_task(_start_next_round, body.case_id, body.round_number + 1)
        return {"message": f"Proposal rejected. Round {body.round_number + 1} is now open.", "outcome": "NEXT_ROUND", "next_round": body.round_number + 1}

    waiting_on = "claimant" if claimant_decision == ProposalDecision.PENDING.value else "respondent"
    waiting_state = CaseStatus.WAITING_FOR_CLAIMANT if waiting_on == "claimant" else CaseStatus.WAITING_FOR_RESPONDENT
    updated_case = _apply_case_status(case, waiting_state, {"current_round": body.round_number, "action_required_by": waiting_on})
    cosmos_service.update_negotiation(neg["id"], {"current_waiting_on": waiting_on})
    return {"message": "Decision recorded. Waiting for the other party.", "your_decision": body.decision.value, "status": updated_case["status"]}


async def _handle_settlement(case_id: str):
    try:
        from app.agents.document_agent import generate_settlement_agreement

        case = cosmos_service.get_case(case_id)
        neg = cosmos_service.get_negotiation_by_case(case_id)
        round_number = case.get("current_round", 1)
        round_doc = cosmos_service.get_round(neg["id"], round_number)
        settled_amount = (
            round_doc.get("settlement_candidate_amount")
            or round_doc.get("ai_proposed_amount")
            or (round_doc.get("respondent") or {}).get("amount")
            or case.get("claim_amount")
            or 0
        )
        cosmos_service.transition_case(case_id, CaseStatus.SETTLING, {"settled_amount": settled_amount})
        settlement_url = await generate_settlement_agreement(case, settled_amount)
        cosmos_service.transition_case(case_id, CaseStatus.SETTLED, {"settlement_url": settlement_url, "settled_amount": settled_amount})
        cosmos_service.update_negotiation(neg["id"], {"final_outcome": "SETTLED", "current_waiting_on": None})

        for email, name in [
            (case["claimant_email"], case["claimant_name"]),
            (case["respondent_email"], case["respondent_name"]),
        ]:
            email_service.send_settlement_confirmation(
                to_email=email,
                party_name=name,
                case_id=case_id,
                settled_amount=settled_amount,
                download_url=settlement_url,
            )
    except Exception as exc:
        logger.error("Settlement handling failed | case_id=%s | error=%s", case_id, exc)


async def _handle_escalation(case_id: str):
    try:
        from app.agents.document_agent import _generate_mediation_certificate
        from app.services.blob_service import blob_service

        case = cosmos_service.get_case(case_id)
        cosmos_service.transition_case(case_id, CaseStatus.ESCALATING)
        docs_data = case.get("documents_data") or {}
        court_url = docs_data.get("court_file_url", "")
        cert_bytes = _generate_mediation_certificate(case)
        cert_blob = f"mediation_cert_{case_id}.pdf"
        blob_service.upload("pdfs", cert_blob, cert_bytes)
        cert_url = blob_service.generate_download_url("pdfs", cert_blob)
        cosmos_service.transition_case(case_id, CaseStatus.ESCALATED, {"mediation_certificate_url": cert_url})

        neg = cosmos_service.get_negotiation_by_case(case_id)
        if neg:
            cosmos_service.update_negotiation(neg["id"], {"final_outcome": "ESCALATED", "current_waiting_on": None})

        for email, name in [
            (case["claimant_email"], case["claimant_name"]),
            (case["respondent_email"], case["respondent_name"]),
        ]:
            email_service.send_escalation_notice(
                to_email=email,
                party_name=name,
                case_id=case_id,
                download_url=court_url or cert_url,
            )
    except Exception as exc:
        logger.error("Escalation handling failed | case_id=%s | error=%s", case_id, exc)


async def _start_next_round(case_id: str, next_round_number: int):
    case = cosmos_service.get_case(case_id)
    neg = cosmos_service.get_negotiation_by_case(case_id)
    if neg:
        cosmos_service.update_negotiation(neg["id"], {"current_waiting_on": None})
    cosmos_service.transition_case(case_id, CaseStatus.NEGOTIATION_OPEN, {"current_round": next_round_number, "action_required_by": None})

    from app.config import settings

    portal_url = f"{settings.BASE_URL}/respond/{case_id}"
    for email, name in [
        (case["respondent_email"], case["respondent_name"]),
        (case["claimant_email"], case["claimant_name"]),
    ]:
        email_service.send_next_round_invite(
            to_email=email,
            party_name=name,
            case_id=case_id,
            round_num=next_round_number,
            portal_url=portal_url,
        )


@router.get("/status/{case_id}")
async def get_negotiation_status(
    case_id: str,
    current_user: dict = Depends(get_current_user_optional),
):
    case = cosmos_service.get_case(case_id)
    if not case:
        raise CaseNotFound(case_id)

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
            "proposed_amount": current_round.get("ai_proposed_amount"),
            "ai_reasoning": current_round.get("ai_reasoning"),
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
