from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class CaseTrack(str, Enum):
    MONETARY_CIVIL = "monetary_civil"
    NON_MONETARY = "non_monetary"
    EMPLOYMENT = "employment"
    CONSUMER = "consumer"
    CRIMINAL = "criminal"


class CaseStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ANALYZING = "ANALYZING"
    ANALYZED = "ANALYZED"
    CRIMINAL_ADVISORY = "CRIMINAL_ADVISORY"
    INVITE_SENT = "INVITE_SENT"
    RESPONDENT_VIEWED = "RESPONDENT_VIEWED"
    NEGOTIATION_OPEN = "NEGOTIATION_OPEN"
    WAITING_FOR_CLAIMANT = "WAITING_FOR_CLAIMANT"
    WAITING_FOR_RESPONDENT = "WAITING_FOR_RESPONDENT"
    PROOF_REQUESTED = "PROOF_REQUESTED"
    PROOF_RESPONSE_PENDING = "PROOF_RESPONSE_PENDING"
    MEDIATOR_REVIEW = "MEDIATOR_REVIEW"
    PROPOSAL_ISSUED = "PROPOSAL_ISSUED"
    SETTLEMENT_PENDING_CONFIRMATION = "SETTLEMENT_PENDING_CONFIRMATION"
    SETTLING = "SETTLING"
    SETTLED = "SETTLED"
    ESCALATING = "ESCALATING"
    ESCALATED = "ESCALATED"
    AUTO_ESCALATED = "AUTO_ESCALATED"
    ABANDONED = "ABANDONED"


VALID_TRANSITIONS = {
    CaseStatus.SUBMITTED: [CaseStatus.ANALYZING],
    CaseStatus.ANALYZING: [CaseStatus.ANALYZED, CaseStatus.CRIMINAL_ADVISORY],
    CaseStatus.ANALYZED: [CaseStatus.INVITE_SENT, CaseStatus.ABANDONED],
    CaseStatus.INVITE_SENT: [CaseStatus.RESPONDENT_VIEWED, CaseStatus.AUTO_ESCALATED],
    CaseStatus.RESPONDENT_VIEWED: [
        CaseStatus.NEGOTIATION_OPEN,
        CaseStatus.AUTO_ESCALATED,
    ],
    CaseStatus.NEGOTIATION_OPEN: [
        CaseStatus.WAITING_FOR_CLAIMANT,
        CaseStatus.WAITING_FOR_RESPONDENT,
        CaseStatus.PROOF_REQUESTED,
        CaseStatus.PROOF_RESPONSE_PENDING,
        CaseStatus.MEDIATOR_REVIEW,
        CaseStatus.SETTLEMENT_PENDING_CONFIRMATION,
        CaseStatus.AUTO_ESCALATED,
    ],
    CaseStatus.WAITING_FOR_CLAIMANT: [
        CaseStatus.WAITING_FOR_RESPONDENT,
        CaseStatus.PROOF_REQUESTED,
        CaseStatus.PROOF_RESPONSE_PENDING,
        CaseStatus.MEDIATOR_REVIEW,
        CaseStatus.SETTLEMENT_PENDING_CONFIRMATION,
        CaseStatus.SETTLING,
        CaseStatus.ESCALATING,
        CaseStatus.AUTO_ESCALATED,
    ],
    CaseStatus.WAITING_FOR_RESPONDENT: [
        CaseStatus.WAITING_FOR_CLAIMANT,
        CaseStatus.PROOF_REQUESTED,
        CaseStatus.PROOF_RESPONSE_PENDING,
        CaseStatus.MEDIATOR_REVIEW,
        CaseStatus.SETTLEMENT_PENDING_CONFIRMATION,
        CaseStatus.SETTLING,
        CaseStatus.ESCALATING,
        CaseStatus.AUTO_ESCALATED,
    ],
    CaseStatus.PROOF_REQUESTED: [
        CaseStatus.PROOF_RESPONSE_PENDING,
        CaseStatus.WAITING_FOR_CLAIMANT,
        CaseStatus.WAITING_FOR_RESPONDENT,
        CaseStatus.MEDIATOR_REVIEW,
        CaseStatus.SETTLEMENT_PENDING_CONFIRMATION,
        CaseStatus.ESCALATING,
    ],
    CaseStatus.PROOF_RESPONSE_PENDING: [
        CaseStatus.WAITING_FOR_CLAIMANT,
        CaseStatus.WAITING_FOR_RESPONDENT,
        CaseStatus.MEDIATOR_REVIEW,
        CaseStatus.SETTLEMENT_PENDING_CONFIRMATION,
        CaseStatus.ESCALATING,
    ],
    CaseStatus.MEDIATOR_REVIEW: [
        CaseStatus.PROPOSAL_ISSUED,
        CaseStatus.SETTLEMENT_PENDING_CONFIRMATION,
        CaseStatus.ESCALATING,
    ],
    CaseStatus.PROPOSAL_ISSUED: [
        CaseStatus.WAITING_FOR_CLAIMANT,
        CaseStatus.WAITING_FOR_RESPONDENT,
        CaseStatus.PROOF_REQUESTED,
        CaseStatus.PROOF_RESPONSE_PENDING,
        CaseStatus.SETTLEMENT_PENDING_CONFIRMATION,
        CaseStatus.SETTLING,
        CaseStatus.ESCALATING,
    ],
    CaseStatus.SETTLEMENT_PENDING_CONFIRMATION: [
        CaseStatus.SETTLING,
        CaseStatus.WAITING_FOR_CLAIMANT,
        CaseStatus.WAITING_FOR_RESPONDENT,
        CaseStatus.ESCALATING,
    ],
    CaseStatus.SETTLING: [CaseStatus.SETTLED],
    CaseStatus.ESCALATING: [CaseStatus.ESCALATED],
    CaseStatus.CRIMINAL_ADVISORY: [],
    CaseStatus.SETTLED: [],
    CaseStatus.ESCALATED: [],
    CaseStatus.AUTO_ESCALATED: [],
    CaseStatus.ABANDONED: [],
}


TERMINAL_STATES = {
    CaseStatus.SETTLED,
    CaseStatus.ESCALATED,
    CaseStatus.AUTO_ESCALATED,
    CaseStatus.ABANDONED,
    CaseStatus.CRIMINAL_ADVISORY,
}


class RespondentType(str, Enum):
    INDIVIDUAL = "individual"
    COMPANY = "company"


class DisputeSubmission(BaseModel):
    dispute_text: str = Field(..., min_length=50, max_length=5000)
    claimant_name: str = Field(..., min_length=2, max_length=100)
    claimant_email: str
    claimant_phone: str
    claimant_state: str
    claimant_city: str
    respondent_name: str = Field(..., min_length=2, max_length=200)
    respondent_email: str
    respondent_phone: Optional[str] = None
    respondent_type: RespondentType = RespondentType.INDIVIDUAL
    respondent_company_name: Optional[str] = None
    respondent_company_reg: Optional[str] = None
    incident_date: Optional[str] = None
    claim_amount: Optional[float] = None
    currency: str = "INR"
    evidence_file_ids: list[str] = []
    claimant_consent: bool = False
    disclaimer_acknowledged: bool = False


class CaseDocument(BaseModel):
    id: str
    created_at: str
    updated_at: str
    status: CaseStatus
    track: Optional[CaseTrack] = None

    claimant_name: str
    claimant_email: str
    claimant_phone: str
    claimant_state: str
    claimant_city: str
    respondent_name: str
    respondent_email: str
    respondent_phone: Optional[str] = None
    respondent_type: RespondentType = RespondentType.INDIVIDUAL
    respondent_company_name: Optional[str] = None
    respondent_verified: bool = False

    dispute_text: str
    incident_date: Optional[str] = None
    claim_amount: Optional[float] = None
    currency: str = "INR"
    evidence_file_ids: list[str] = []

    intake_data: Optional[dict] = None
    legal_data: Optional[dict] = None
    analytics_data: Optional[dict] = None
    documents_data: Optional[dict] = None

    current_round: int = 0
    max_rounds: int = 3
    negotiation_id: Optional[str] = None
    settled_amount: Optional[float] = None
    settled_actions: Optional[list] = None
    action_required_by: Optional[str] = None
    direct_settlement_amount: Optional[float] = None
    direct_settlement_reason: Optional[str] = None

    current_deadline: Optional[str] = None
    invite_deadline: Optional[str] = None
    payment_deadline: Optional[str] = None

    settlement_honored: Optional[bool] = None
    breach_notice_sent: bool = False
    mediation_certificate_url: Optional[str] = None

    claimant_consent: bool = False
    disclaimer_acknowledged: bool = False
