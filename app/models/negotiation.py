from enum import Enum
from typing import Optional
from pydantic import BaseModel


class ProposalDecision(str, Enum):
    ACCEPT  = "ACCEPT"
    REJECT  = "REJECT"
    PENDING = "PENDING"


class OfferType(str, Enum):
    MONETARY    = "monetary"
    ACTION_LIST = "action_list"


class NegotiationRound(BaseModel):
    round_number:           int
    offer_type:             OfferType

    # Monetary fields
    claimant_offer:         Optional[float] = None
    respondent_offer:       Optional[float] = None
    ai_proposed_amount:     Optional[float] = None

    # Non-monetary fields
    claimant_demands:       Optional[list[str]] = None
    respondent_commitments: Optional[list[str]] = None
    ai_proposed_actions:    Optional[list[dict]] = None

    # Decisions
    claimant_decision:      ProposalDecision = ProposalDecision.PENDING
    respondent_decision:    ProposalDecision = ProposalDecision.PENDING

    # AI output
    ai_reasoning:           Optional[str] = None
    ai_pressure_points:     Optional[dict] = None

    # Timestamps
    claimant_offer_at:      Optional[str] = None
    respondent_offer_at:    Optional[str] = None
    proposal_issued_at:     Optional[str] = None
    claimant_decided_at:    Optional[str] = None
    respondent_decided_at:  Optional[str] = None
    round_deadline:         Optional[str] = None


class NegotiationDocument(BaseModel):
    id:             str
    case_id:        str
    created_at:     str
    updated_at:     Optional[str] = None
    offer_type:     OfferType
    rounds:         list[NegotiationRound] = []
    zopa_min:       Optional[float] = None
    zopa_max:       Optional[float] = None
    final_outcome:  Optional[str] = None


class SubmitOfferRequest(BaseModel):
    case_id:       str
    round_number:  int
    offer_amount:  Optional[float] = None      # monetary
    demands:       Optional[list[str]] = None  # non-monetary
    commitments:   Optional[list[str]] = None  # non-monetary


class ProposalResponseRequest(BaseModel):
    case_id:       str
    round_number:  int
    decision:      ProposalDecision
    party:         str  # "claimant" or "respondent"