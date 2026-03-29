import unittest

from app.models.case import CaseStatus
from app.models.negotiation import ProposalDecision
from app.core.negotiation_rules import check_direct_settlement, next_waiting_state, resolve_round_outcome


class NegotiationLogicTests(unittest.TestCase):
    def test_offer_greater_than_claimant_ask_stops_negotiation(self):
        case = {"claim_amount": 45000}
        neg = {"rounds": []}
        round_doc = {
            "round_number": 1,
            "claimant": {"amount": 42000},
            "respondent": {"amount": 46000},
        }
        amount, reason = check_direct_settlement(case, neg, round_doc)
        self.assertEqual(amount, 46000)
        self.assertIn("directly", reason.lower())

    def test_claimant_matching_existing_respondent_offer_stops_negotiation(self):
        case = {"claim_amount": 45000}
        neg = {"rounds": []}
        round_doc = {
            "round_number": 1,
            "claimant": {"amount": 30000},
            "respondent": {"amount": 32000},
        }
        amount, _ = check_direct_settlement(case, neg, round_doc)
        self.assertEqual(amount, 32000)

    def test_proof_request_flow_blocks_mediator_until_answered(self):
        round_doc = {
            "round_number": 1,
            "claimant": {"submitted_at": "2026-03-30T00:00:00+00:00"},
            "respondent": {"submitted_at": "2026-03-30T00:01:00+00:00"},
        }
        neg = {"proof_requests": [{"id": "proof_1", "round_number": 1, "status": "PENDING", "requested_from": "respondent"}]}
        status, waiting_on = next_waiting_state(round_doc, neg)
        self.assertEqual(status, CaseStatus.PROOF_REQUESTED)
        self.assertEqual(waiting_on, "respondent")

    def test_proof_response_flow_returns_to_mediator_review_once_both_submitted(self):
        round_doc = {
            "round_number": 1,
            "claimant": {"submitted_at": "2026-03-30T00:00:00+00:00"},
            "respondent": {"submitted_at": "2026-03-30T00:01:00+00:00"},
        }
        neg = {"proof_requests": [{"id": "proof_1", "round_number": 1, "status": "RESPONDED", "requested_from": "respondent"}]}
        status, waiting_on = next_waiting_state(round_doc, neg)
        self.assertEqual(status, CaseStatus.MEDIATOR_REVIEW)
        self.assertIsNone(waiting_on)

    def test_normal_three_round_rejection_flow_escalates_on_final_round(self):
        outcome = resolve_round_outcome(
            round_number=3,
            max_rounds=3,
            claimant_decision=ProposalDecision.REJECT.value,
            respondent_decision=ProposalDecision.REJECT.value,
            rejection_reason="amount too low",
        )
        self.assertEqual(outcome, "ESCALATED")

    def test_rejection_for_missing_proof_opens_proof_exchange(self):
        outcome = resolve_round_outcome(
            round_number=1,
            max_rounds=3,
            claimant_decision=ProposalDecision.REJECT.value,
            respondent_decision=ProposalDecision.ACCEPT.value,
            rejection_reason="Need more proof and evidence before accepting",
        )
        self.assertEqual(outcome, "PROOF_REQUESTED")

    def test_accept_in_full_or_settlement_confirmation_marks_settled(self):
        outcome = resolve_round_outcome(
            round_number=1,
            max_rounds=3,
            claimant_decision=ProposalDecision.ACCEPT.value,
            respondent_decision=ProposalDecision.ACCEPT.value,
            rejection_reason="",
        )
        self.assertEqual(outcome, "SETTLED")


if __name__ == "__main__":
    unittest.main()
