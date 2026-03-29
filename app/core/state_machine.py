import logging
from datetime import datetime, timedelta, timezone

from app.core.exceptions import InvalidCaseState
from app.models.case import CaseStatus, TERMINAL_STATES, VALID_TRANSITIONS

logger = logging.getLogger(__name__)


STAGE_DEADLINES = {
    CaseStatus.INVITE_SENT: 7 * 24,
    CaseStatus.RESPONDENT_VIEWED: 5 * 24,
    CaseStatus.NEGOTIATION_OPEN: 3 * 24,
    CaseStatus.WAITING_FOR_CLAIMANT: 3 * 24,
    CaseStatus.WAITING_FOR_RESPONDENT: 3 * 24,
    CaseStatus.PROOF_REQUESTED: 3 * 24,
    CaseStatus.PROOF_RESPONSE_PENDING: 3 * 24,
    CaseStatus.PROPOSAL_ISSUED: 2 * 24,
    CaseStatus.SETTLEMENT_PENDING_CONFIRMATION: 2 * 24,
    CaseStatus.SETTLING: 14 * 24,
    CaseStatus.ANALYZED: 14 * 24,
}


def transition(case: dict, new_status: CaseStatus) -> dict:
    current = CaseStatus(case["status"])

    if current in TERMINAL_STATES:
        raise InvalidCaseState(current.value, "non-terminal state")

    allowed = VALID_TRANSITIONS.get(current, [])
    if new_status not in allowed:
        raise InvalidCaseState(current.value, f"one of {[s.value for s in allowed]}")

    now = datetime.now(timezone.utc)
    case["status"] = new_status.value
    case["updated_at"] = now.isoformat()

    deadline_hours = STAGE_DEADLINES.get(new_status)
    case["current_deadline"] = (
        (now + timedelta(hours=deadline_hours)).isoformat()
        if deadline_hours
        else None
    )

    logger.info(
        "Case transition | id=%s | %s -> %s | deadline=%s",
        case["id"],
        current.value,
        new_status.value,
        case.get("current_deadline", "none"),
    )
    return case


def is_terminal(case: dict) -> bool:
    return CaseStatus(case["status"]) in TERMINAL_STATES


def is_expired(case: dict) -> bool:
    deadline_str = case.get("current_deadline")
    if not deadline_str:
        return False
    deadline = datetime.fromisoformat(deadline_str)
    return datetime.now(timezone.utc) > deadline


def get_allowed_transitions(case: dict) -> list:
    current = CaseStatus(case["status"])
    return [s.value for s in VALID_TRANSITIONS.get(current, [])]
