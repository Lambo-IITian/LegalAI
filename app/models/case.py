from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class CaseTrack(str, Enum):
    MONETARY_CIVIL = "monetary_civil"
    NON_MONETARY   = "non_monetary"
    EMPLOYMENT     = "employment"
    CONSUMER       = "consumer"
    CRIMINAL       = "criminal"


class CaseStatus(str, Enum):
    SUBMITTED         = "SUBMITTED"
    ANALYZING         = "ANALYZING"
    ANALYZED          = "ANALYZED"
    CRIMINAL_ADVISORY = "CRIMINAL_ADVISORY"
    INVITE_SENT       = "INVITE_SENT"
    RESPONDENT_VIEWED = "RESPONDENT_VIEWED"
    NEGOTIATING       = "NEGOTIATING"
    ROUND_PENDING     = "ROUND_PENDING"
    PROPOSAL_ISSUED   = "PROPOSAL_ISSUED"
    ROUND_FAILED      = "ROUND_FAILED"
    SETTLING          = "SETTLING"
    SETTLED           = "SETTLED"
    ESCALATING        = "ESCALATING"
    ESCALATED         = "ESCALATED"
    AUTO_ESCALATED    = "AUTO_ESCALATED"
    ABANDONED         = "ABANDONED"


# Every valid transition — enforced by state machine
VALID_TRANSITIONS = {
    CaseStatus.SUBMITTED:         [CaseStatus.ANALYZING],
    CaseStatus.ANALYZING:         [CaseStatus.ANALYZED,
                                   CaseStatus.CRIMINAL_ADVISORY],
    CaseStatus.ANALYZED:          [CaseStatus.INVITE_SENT,
                                   CaseStatus.ABANDONED],
    CaseStatus.INVITE_SENT:       [CaseStatus.RESPONDENT_VIEWED,
                                   CaseStatus.AUTO_ESCALATED],
    CaseStatus.RESPONDENT_VIEWED: [CaseStatus.NEGOTIATING,
                                   CaseStatus.AUTO_ESCALATED],
    CaseStatus.NEGOTIATING:       [CaseStatus.ROUND_PENDING,
                                   CaseStatus.AUTO_ESCALATED],
    CaseStatus.ROUND_PENDING:     [CaseStatus.PROPOSAL_ISSUED],
    CaseStatus.PROPOSAL_ISSUED:   [CaseStatus.SETTLING,
                                   CaseStatus.ROUND_FAILED],
    CaseStatus.ROUND_FAILED:      [CaseStatus.NEGOTIATING,
                                   CaseStatus.ESCALATING],
    CaseStatus.SETTLING:          [CaseStatus.SETTLED],
    CaseStatus.ESCALATING:        [CaseStatus.ESCALATED],
    CaseStatus.CRIMINAL_ADVISORY: [],
    CaseStatus.SETTLED:           [],
    CaseStatus.ESCALATED:         [],
    CaseStatus.AUTO_ESCALATED:    [],
    CaseStatus.ABANDONED:         [],
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
    COMPANY    = "company"


class DisputeSubmission(BaseModel):
    dispute_text:             str   = Field(..., min_length=50, max_length=5000)
    claimant_name:            str   = Field(..., min_length=2, max_length=100)
    claimant_email:           str
    claimant_phone:           str
    claimant_state:           str
    claimant_city:            str
    respondent_name:          str   = Field(..., min_length=2, max_length=200)
    respondent_email:         str
    respondent_phone:         Optional[str] = None
    respondent_type:          RespondentType = RespondentType.INDIVIDUAL
    respondent_company_name:  Optional[str] = None
    respondent_company_reg:   Optional[str] = None
    incident_date:            Optional[str] = None
    claim_amount:             Optional[float] = None
    currency:                 str = "INR"
    evidence_file_ids:        list[str] = []
    claimant_consent:         bool = False
    disclaimer_acknowledged:  bool = False


class CaseDocument(BaseModel):
    # Identity
    id:                        str
    created_at:                str
    updated_at:                str
    status:                    CaseStatus
    track:                     Optional[CaseTrack] = None

    # Parties
    claimant_name:             str
    claimant_email:            str
    claimant_phone:            str
    claimant_state:            str
    claimant_city:             str
    respondent_name:           str
    respondent_email:          str
    respondent_phone:          Optional[str] = None
    respondent_type:           RespondentType = RespondentType.INDIVIDUAL
    respondent_company_name:   Optional[str] = None
    respondent_verified:       bool = False

    # Dispute
    dispute_text:              str
    incident_date:             Optional[str] = None
    claim_amount:              Optional[float] = None
    currency:                  str = "INR"
    evidence_file_ids:         list[str] = []

    # Agent outputs — populated as pipeline runs
    intake_data:               Optional[dict] = None
    legal_data:                Optional[dict] = None
    analytics_data:            Optional[dict] = None
    documents_data:            Optional[dict] = None

    # Negotiation
    current_round:             int = 0
    max_rounds:                int = 3
    negotiation_id:            Optional[str] = None
    settled_amount:            Optional[float] = None
    settled_actions:           Optional[list] = None

    # Deadlines
    current_deadline:          Optional[str] = None
    invite_deadline:           Optional[str] = None
    payment_deadline:          Optional[str] = None

    # Post-settlement
    settlement_honored:        Optional[bool] = None
    breach_notice_sent:        bool = False
    mediation_certificate_url: Optional[str] = None

    # Consent
    claimant_consent:          bool = False
    disclaimer_acknowledged:   bool = False