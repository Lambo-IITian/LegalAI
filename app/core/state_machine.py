import logging
from datetime import datetime, timedelta, timezone
from app.models.case import CaseStatus, VALID_TRANSITIONS, TERMINAL_STATES
from app.core.exceptions import InvalidCaseState

logger = logging.getLogger(__name__)

# Hours until each stage expires
STAGE_DEADLINES = {
    CaseStatus.INVITE_SENT:       7  * 24,  # 7 days for respondent to open
    CaseStatus.RESPONDENT_VIEWED: 5  * 24,  # 5 days for respondent to respond
    CaseStatus.ROUND_PENDING:     3  * 24,  # 3 days per offer round
    CaseStatus.PROPOSAL_ISSUED:   2  * 24,  # 2 days to accept/reject
    CaseStatus.SETTLING:          14 * 24,  # 14 days for payment
    CaseStatus.ANALYZED:          14 * 24,  # 14 days before abandonment
}


def transition(case: dict, new_status: CaseStatus) -> dict:
    """
    The ONLY function that changes case status anywhere in the app.
    Validates the transition, sets the deadline, returns updated case dict.
    Raises InvalidCaseState if transition is not allowed.
    """
    current = CaseStatus(case["status"])

    if current in TERMINAL_STATES:
        raise InvalidCaseState(current.value, "non-terminal state")

    allowed = VALID_TRANSITIONS.get(current, [])
    if new_status not in allowed:
        raise InvalidCaseState(
            current.value,
            f"one of {[s.value for s in allowed]}"
        )

    now = datetime.now(timezone.utc)
    case["status"]     = new_status.value
    case["updated_at"] = now.isoformat()

    # Set deadline for the new state if applicable
    deadline_hours = STAGE_DEADLINES.get(new_status)
    if deadline_hours:
        deadline = now + timedelta(hours=deadline_hours)
        case["current_deadline"] = deadline.isoformat()
    else:
        case["current_deadline"] = None

    logger.info(
        f"Case transition | id={case['id']} | "
        f"{current.value} -> {new_status.value} | "
        f"deadline={case.get('current_deadline', 'none')}"
    )
    return case


def is_terminal(case: dict) -> bool:
    return CaseStatus(case["status"]) in TERMINAL_STATES


def is_expired(case: dict) -> bool:
    """Returns True if the case has passed its current stage deadline."""
    deadline_str = case.get("current_deadline")
    if not deadline_str:
        return False
    deadline = datetime.fromisoformat(deadline_str)
    return datetime.now(timezone.utc) > deadline


def get_allowed_transitions(case: dict) -> list:
    current = CaseStatus(case["status"])
    return [s.value for s in VALID_TRANSITIONS.get(current, [])]