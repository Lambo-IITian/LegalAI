from app.models.case import CaseStatus
from app.models.negotiation import ProposalDecision


def latest_party_amount(neg: dict, party: str):
    for round_doc in sorted(neg.get("rounds", []), key=lambda item: item["round_number"], reverse=True):
        amount = (round_doc.get(party) or {}).get("amount")
        if amount is not None:
            return amount
    return None


def claimant_target_amount(case: dict, neg: dict, round_doc: dict):
    current = (round_doc.get("claimant") or {}).get("amount")
    if current is not None:
        return current
    previous = latest_party_amount(neg, "claimant")
    if previous is not None:
        return previous
    return case.get("claim_amount")


def pending_proof_requests(neg: dict, round_number: int) -> list[dict]:
    return [item for item in neg.get("proof_requests", []) if item.get("round_number") == round_number and item.get("status") == "PENDING"]


def next_waiting_state(round_doc: dict, neg: dict) -> tuple[CaseStatus, str | None]:
    pending_proof = pending_proof_requests(neg, round_doc["round_number"])
    if pending_proof:
        return CaseStatus.PROOF_REQUESTED, pending_proof[0]["requested_from"]
    claimant_submitted = (round_doc.get("claimant") or {}).get("submitted_at")
    respondent_submitted = (round_doc.get("respondent") or {}).get("submitted_at")
    if claimant_submitted and respondent_submitted:
        return CaseStatus.MEDIATOR_REVIEW, None
    if claimant_submitted:
        return CaseStatus.WAITING_FOR_RESPONDENT, "respondent"
    if respondent_submitted:
        return CaseStatus.WAITING_FOR_CLAIMANT, "claimant"
    return CaseStatus.NEGOTIATION_OPEN, None


def check_direct_settlement(case: dict, neg: dict, round_doc: dict):
    claimant_amount = (round_doc.get("claimant") or {}).get("amount")
    respondent_amount = (round_doc.get("respondent") or {}).get("amount")
    claimant_target = claimant_target_amount(case, neg, round_doc)
    if respondent_amount is not None and claimant_target is not None and respondent_amount >= claimant_target:
        return respondent_amount, "Respondent has met or exceeded the claimant's demand. Negotiation should move directly to settlement confirmation."
    if claimant_amount is not None and respondent_amount is not None and claimant_amount <= respondent_amount:
        return respondent_amount, "The claimant's latest ask is within the respondent's current offer. Negotiation should move directly to settlement confirmation."
    return None


def resolve_round_outcome(round_number: int, max_rounds: int, claimant_decision: str, respondent_decision: str, rejection_reason: str) -> str:
    if claimant_decision == ProposalDecision.ACCEPT.value and respondent_decision == ProposalDecision.ACCEPT.value:
        return "SETTLED"
    if "proof" in rejection_reason or "evidence" in rejection_reason:
        return "PROOF_REQUESTED"
    if round_number >= max_rounds:
        return "ESCALATED"
    return "NEXT_ROUND"
