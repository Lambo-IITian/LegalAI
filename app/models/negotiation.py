from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class ProposalDecision(str, Enum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"
    PENDING = "PENDING"


class OfferType(str, Enum):
    MONETARY = "monetary"
    ACTION_LIST = "action_list"


class RoundPartyState(BaseModel):
    amount: Optional[float] = None
    actions: Optional[list[str]] = None
    explanation: Optional[str] = None
    proof_note: Optional[str] = None
    requested_proof: list[str] = []
    conditions: list[str] = []
    decision: ProposalDecision = ProposalDecision.PENDING
    decision_reason: Optional[str] = None
    submitted_at: Optional[str] = None
    decided_at: Optional[str] = None


class ProofExchangeItem(BaseModel):
    id: str
    round_number: int
    requested_by: str
    requested_from: str
    request_text: str
    status: str = "PENDING"
    created_at: str
    visible_to_both_parties: bool = True
    response_text: Optional[str] = None
    file_refs: list[str] = []
    response_at: Optional[str] = None


class SharedNegotiationNote(BaseModel):
    id: str
    round_number: int
    party: str
    note_type: str
    text: str
    created_at: str


class NegotiationRound(BaseModel):
    round_number: int
    offer_type: OfferType
    claimant: RoundPartyState = Field(default_factory=RoundPartyState)
    respondent: RoundPartyState = Field(default_factory=RoundPartyState)
    ai_proposed_amount: Optional[float] = None
    ai_proposed_actions: Optional[list[dict]] = None
    ai_reasoning: Optional[str] = None
    ai_pressure_points: Optional[dict] = None
    mediator_summary: Optional[str] = None
    unresolved_proof_request_ids: list[str] = []
    immediate_outcome: Optional[str] = None
    settlement_candidate_amount: Optional[float] = None
    settlement_candidate_reason: Optional[str] = None
    proposal_issued_at: Optional[str] = None
    round_deadline: Optional[str] = None


class NegotiationDocument(BaseModel):
    id: str
    case_id: str
    created_at: str
    updated_at: Optional[str] = None
    offer_type: OfferType
    rounds: list[NegotiationRound] = []
    proof_requests: list[ProofExchangeItem] = []
    shared_notes: list[SharedNegotiationNote] = []
    zopa_min: Optional[float] = None
    zopa_max: Optional[float] = None
    final_outcome: Optional[str] = None
    current_waiting_on: Optional[str] = None


class SubmitOfferRequest(BaseModel):
    case_id: str
    round_number: int
    offer_amount: Optional[float] = None
    demands: Optional[list[str]] = None
    commitments: Optional[list[str]] = None
    explanation: Optional[str] = Field(default=None, max_length=2000)
    proof_note: Optional[str] = Field(default=None, max_length=2000)
    requested_proof: list[str] = []
    conditions: list[str] = []


class ProposalResponseRequest(BaseModel):
    case_id: str
    round_number: int
    decision: ProposalDecision
    party: str
    reason: Optional[str] = Field(default=None, max_length=1000)


class ProofResponseRequest(BaseModel):
    case_id: str
    round_number: int
    party: str
    request_id: str
    response_text: str = Field(..., min_length=5, max_length=3000)
    file_refs: list[str] = []
