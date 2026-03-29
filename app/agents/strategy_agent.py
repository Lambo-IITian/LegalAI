import logging

from app.services.openai_service import openai_service

logger = logging.getLogger(__name__)


STRATEGY_PROMPT = """
You are a senior Indian disputes strategist helping a claimant maximize the chance of a favorable outcome.

Provide practical, legally-aware guidance that is clear and concrete.
Do not exaggerate certainty. Do not give unsafe criminal or illegal advice.

Respond ONLY in valid JSON:
{
  "recommended_positioning": "short paragraph",
  "what_to_say": ["point 1", "point 2", "point 3"],
  "evidence_to_gather": ["item 1", "item 2", "item 3"],
  "mistakes_to_avoid": ["mistake 1", "mistake 2", "mistake 3"],
  "negotiation_posture": "collaborative|firm|pressure",
  "pressure_points": ["point 1", "point 2"],
  "court_backup_plan": ["step 1", "step 2", "step 3"],
  "proof_gaps_to_fix_first": ["gap 1", "gap 2"],
  "best_next_action": "single practical next move"
}
"""


def generate_case_strategy(case: dict) -> dict:
    intake = case.get("intake_data") or {}
    legal = case.get("legal_data") or {}
    analytics = case.get("analytics_data") or {}

    user_message = f"""
Build a winning case strategy for this claimant.

CASE:
- Dispute: {case.get('dispute_text', '')[:1400]}
- Claim amount: {case.get('claim_amount')}
- Track: {case.get('track')}
- Claimant: {case.get('claimant_name')}
- Respondent: {case.get('respondent_name')}

INTAKE:
- Strengths: {intake.get('claimant_strengths', [])}
- Weaknesses: {intake.get('claimant_weaknesses', [])}
- Missing proof: {intake.get('missing_proof_checklist', [])}
- Key facts: {intake.get('key_facts', [])}

LEGAL:
- Standing: {legal.get('legal_standing')}
- Forum: {legal.get('forum_name')}
- Rights: {legal.get('claimant_rights', [])}
- Respondent defenses: {legal.get('respondent_defenses', [])}
- Opponent win paths: {legal.get('respondent_win_paths', [])}

ANALYTICS:
- Win probability: {analytics.get('win_probability')}
- Settlement range: min={analytics.get('zopa_min')}, optimal={analytics.get('zopa_optimal')}, max={analytics.get('zopa_max')}
- Court cost estimate: {analytics.get('court_cost_estimate')}
- Time to resolution months: {analytics.get('time_to_resolution_months')}
"""

    try:
        return openai_service.call_json(
            system_prompt=STRATEGY_PROMPT,
            user_message=user_message,
            use_large_model=True,
            temperature=0.3,
            max_tokens=1800,
        )
    except Exception as exc:
        logger.error("Strategy agent failed | case_id=%s | error=%s", case.get("id"), exc)
        return {
            "recommended_positioning": "Stay factual, stay consistent, and anchor every demand to proof you can actually show.",
            "what_to_say": [
                "State the exact facts in chronological order.",
                "Tie your demand to documents, messages, payments, or witnesses.",
                "Emphasize the cost and delay of court if the matter is not resolved now.",
            ],
            "evidence_to_gather": intake.get("missing_proof_checklist", []) or ["Written communications", "Payment records", "Photos or supporting documents"],
            "mistakes_to_avoid": [
                "Do not exaggerate facts you cannot prove.",
                "Do not send emotional threats or insults.",
                "Do not change your story from round to round.",
            ],
            "negotiation_posture": "firm",
            "pressure_points": legal.get("respondent_defenses", [])[:2],
            "court_backup_plan": [
                "Organize evidence into a clean chronology.",
                "Keep copies of all negotiation messages and proposals.",
                "Be ready with the demand letter, court file, and mediation certificate.",
            ],
            "proof_gaps_to_fix_first": intake.get("missing_proof_checklist", [])[:3],
            "best_next_action": "Upload the strongest missing proof and keep your negotiation position aligned with it.",
        }
