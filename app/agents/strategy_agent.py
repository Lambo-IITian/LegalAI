import logging

from app.services.openai_service import openai_service

logger = logging.getLogger(__name__)


STRATEGY_PROMPT = """
You are a senior Indian disputes strategist and litigation advisor.
Your client is the CLAIMANT. Your job is to give them the smartest, most practical game plan
to maximize their outcome — in mediation first, and in court as a backup.

Be concrete and specific — reference the actual facts, amounts, statutes, and evidence.
Do not give generic advice. Every recommendation must be tailored to THIS case.
Do not exaggerate the claimant's position. Do not recommend illegal or unsafe actions.

STRATEGY FRAMEWORK:
1. Start from the claimant's legal position (legal_standing + evidence quality)
2. Identify what the respondent is most afraid of (pressure_points)
3. Determine what evidence gaps must be fixed before negotiating
4. Decide the right tone for negotiation (collaborative/firm/pressure)
5. Plan the court backup route if mediation fails

Respond ONLY in valid JSON. No markdown. No text outside JSON.
{
  "recommended_positioning": "2-3 sentence paragraph explaining the optimal stance for the claimant in this specific case — based on their actual strengths and legal position",
  "what_to_say": [
    "Point 1: Specific talking point — e.g. 'Reference the signed rental agreement dated [date] as the anchor for your deposit claim'",
    "Point 2: Specific framing point",
    "Point 3: Specific closing argument",
    "Point 4: Optional fourth point if high-complexity case"
  ],
  "what_not_to_say": [
    "Avoid 1: Specific thing to avoid — e.g. 'Do not mention that you did not get the move-out inspection done — it weakens your position'",
    "Avoid 2"
  ],
  "evidence_to_gather": [
    "Specific document or proof to collect — e.g. 'Bank statement showing NEFT transfer of Rs. 45,000 on [date] to [respondent]'",
    "Specific witness statement or record to obtain"
  ],
  "proof_gaps_to_fix_first": [
    "Gap 1: Most critical missing evidence — fix before next round",
    "Gap 2: Second most important"
  ],
  "mistakes_to_avoid": [
    "Mistake 1: Specific strategic error to avoid in this case",
    "Mistake 2",
    "Mistake 3"
  ],
  "negotiation_posture": "collaborative|firm|pressure",
  "negotiation_posture_reason": "Why this posture for this specific respondent and case",
  "pressure_points": [
    "Pressure point 1 — specific legal/reputational/financial risk the respondent faces",
    "Pressure point 2"
  ],
  "when_to_use_pressure": "Specific trigger — e.g. 'If respondent offers below Rs. X in round 2, mention the consumer forum filing fee is Rs. 200 and NCDRC success rate is 80%'",
  "best_settlement_range": "Rs. X (floor — do not accept below) to Rs. Y (aspirational — open at this)",
  "opening_ask_recommendation": "Specific advice on what the claimant should ask for in round 1 and why",
  "court_backup_plan": [
    "Step 1: Specific immediate action if mediation fails",
    "Step 2: Which court/forum to file in and estimated timeline",
    "Step 3: What to do about evidence and legal notice before filing"
  ],
  "best_next_action": "Single most impactful action the claimant should take RIGHT NOW — before the next round"
}
"""


def generate_case_strategy(case: dict) -> dict:
    """
    Strategy Agent — advises the claimant on negotiation tactics.
    Uses gpt-4o for strategic depth.
    Called after analytics to have ZOPA context available.
    """
    intake    = case.get("intake_data") or {}
    legal     = case.get("legal_data") or {}
    analytics = case.get("analytics_data") or {}
    track     = case.get("track", "monetary_civil")

    # Build a rich, case-specific context
    claim = case.get("claim_amount") or 0
    zopa_min  = analytics.get("zopa_min") or 0
    zopa_max  = analytics.get("zopa_max") or claim
    zopa_opt  = analytics.get("zopa_optimal") or ((zopa_min + zopa_max) / 2)

    statutory_floor = ""
    if track == "employment":
        floor = legal.get("total_statutory_dues", 0) or 0
        statutory_floor = f"\n- Statutory dues floor (NEVER accept below): Rs. {floor:,.0f}"

    user_message = f"""
Build a winning case strategy for this claimant. Be specific to these facts.

CASE DETAILS:
- Dispute: {case.get('dispute_text', '')[:1500]}
- Track: {track}
- Claimant: {case.get('claimant_name')} | {case.get('claimant_state')}
- Respondent: {case.get('respondent_name')} ({case.get('respondent_type', 'individual')})
- Original claim: Rs. {claim:,.0f}
- Incident date: {case.get('incident_date', 'Not specified')}

INTAKE ANALYSIS:
- Dispute category: {intake.get('dispute_category', 'N/A')}
- Severity: {intake.get('severity', 'N/A')}
- Evidence strength: {intake.get('evidence_strength_score', 'N/A')}/100
- Evidence available: {intake.get('evidence_available', [])}
- Missing proof: {intake.get('missing_proof_checklist', [])}
- Key facts: {intake.get('key_facts', [])}
- Claimant strengths: {intake.get('claimant_strengths', [])}
- Claimant weaknesses: {intake.get('claimant_weaknesses', [])}

LEGAL ANALYSIS:
- Legal standing: {legal.get('legal_standing', 'N/A')}
- Legal standing reason: {legal.get('legal_standing_reason', 'N/A')}
- Forum if escalated: {legal.get('forum_name', 'N/A')}
- Primary statutes: {[l.get('act') + ' S.' + str(l.get('section', '')) for l in legal.get('applicable_laws', [])[:4] if l.get('strength') == 'PRIMARY']}
- Claimant rights: {legal.get('claimant_rights', [])[:4]}
- Respondent's likely defenses: {legal.get('respondent_defenses', [])[:4]}
- Relief available: {legal.get('relief_available', [])[:4]}

ANALYTICS:
- Win probability: {analytics.get('win_probability', 'N/A')}%
- ZOPA floor (minimum to accept): Rs. {zopa_min:,.0f}
- ZOPA optimal (fair settlement): Rs. {zopa_opt:,.0f}
- ZOPA ceiling (maximum likely): Rs. {zopa_max:,.0f}
- Court cost estimate: Rs. {analytics.get('court_cost_estimate', 0):,.0f}
- Time to court judgment: {analytics.get('time_to_resolution_months', 'N/A')} months
- Payment recovery probability: {analytics.get('payment_recovery_probability', 'N/A')}%{statutory_floor}

STRATEGY TASK:
Advise the claimant on: what to say, what evidence to fix first, how to apply pressure,
where to open in negotiation, and what the backup court plan is.
"""

    try:
        result = openai_service.call_json(
            system_prompt=STRATEGY_PROMPT,
            user_message=user_message,
            use_large_model=True,
            temperature=0.3,
            max_tokens=2000,
        )

        # Validate key fields
        for field in ["what_to_say", "evidence_to_gather", "mistakes_to_avoid",
                      "court_backup_plan", "proof_gaps_to_fix_first",
                      "pressure_points", "what_not_to_say"]:
            if not isinstance(result.get(field), list):
                result[field] = []

        if not result.get("best_next_action"):
            gaps = intake.get("missing_proof_checklist", [])
            result["best_next_action"] = (
                f"Gather the missing evidence first: {gaps[0]}" if gaps
                else "Organize all existing evidence into a clear chronology before the next negotiation round."
            )

        if not result.get("recommended_positioning"):
            result["recommended_positioning"] = (
                f"Your legal standing is {legal.get('legal_standing', 'MODERATE')} "
                f"with evidence strength {intake.get('evidence_strength_score', 50)}/100. "
                f"Stay factual, anchor every demand to documented proof, and reference "
                f"applicable law when the respondent pushes back."
            )

        logger.info(
            f"Strategy Agent complete | track={track} | "
            f"posture={result.get('negotiation_posture')} | "
            f"case_id={case.get('id', 'N/A')}"
        )
        return result

    except Exception as exc:
        logger.error(
            "Strategy agent failed | case_id=%s | error=%s",
            case.get("id"), exc
        )
        return _fallback_strategy(case, intake, legal, analytics)


def _fallback_strategy(case: dict, intake: dict, legal: dict, analytics: dict) -> dict:
    """Robust fallback strategy — still useful even if LLM fails."""
    track = case.get("track", "monetary_civil")
    claim = case.get("claim_amount") or 0
    zopa_min = analytics.get("zopa_min") or round(claim * 0.55, 0)
    gaps = intake.get("missing_proof_checklist", [])
    defenses = legal.get("respondent_defenses", [])

    return {
        "recommended_positioning": (
            f"Your legal position is {legal.get('legal_standing', 'MODERATE')}. "
            "Stay factual, present your documents clearly, and tie every demand to proof you can show. "
            "If the respondent refuses a reasonable settlement, the cost of court is on their side too."
        ),
        "what_to_say": [
            "Open by stating the specific amount owed and the date it became due — be precise.",
            f"Reference your key document (e.g. contract, payslip, order confirmation) as the legal anchor.",
            f"Mention that going to court would cost approximately Rs. {analytics.get('court_cost_estimate', 75000):,.0f} and take {analytics.get('time_to_resolution_months', 30)} months — the respondent faces the same cost.",
            "Close by proposing a specific amount and a specific payment timeline.",
        ],
        "what_not_to_say": [
            "Avoid making threats you cannot follow through on.",
            "Do not volunteer weaknesses in your evidence — let the respondent raise them.",
        ],
        "evidence_to_gather": gaps[:4] or [
            "Bank statement or payment receipt proving amount paid",
            "Written communication (email/WhatsApp) showing acknowledgment or dispute",
        ],
        "proof_gaps_to_fix_first": gaps[:2] or ["Identify and collect all written documentation immediately"],
        "mistakes_to_avoid": [
            "Do not exaggerate facts or make claims you cannot prove — it destroys credibility.",
            "Do not send emotional messages — keep all communication professional and documented.",
            "Do not change your position inconsistently between rounds.",
        ],
        "negotiation_posture": "firm",
        "negotiation_posture_reason": "A firm but professional posture is appropriate when legal standing is clear.",
        "pressure_points": defenses[:2] or [
            "The respondent risks a formal court order if mediation fails.",
            "Legal interest at 18% per annum accrues from the default date.",
        ],
        "when_to_use_pressure": "If respondent offers less than 50% of claim by round 2, escalate tone and reference court consequences explicitly.",
        "best_settlement_range": f"Floor: Rs. {zopa_min:,.0f} | Target: Rs. {analytics.get('zopa_optimal', claim):,.0f}",
        "opening_ask_recommendation": f"Open at your full claim of Rs. {claim:,.0f} in round 1 to anchor the negotiation.",
        "court_backup_plan": [
            f"Send formal legal notice by registered post to {case.get('respondent_name')} within 7 days of failed mediation.",
            f"File in {legal.get('forum_name', 'the appropriate court')} — estimated filing fee Rs. {analytics.get('court_cost_estimate', 50000) * 0.1:,.0f}.",
            "Submit this mediation certificate as evidence of pre-litigation good faith attempt.",
        ],
        "best_next_action": (
            f"Collect the missing evidence: {gaps[0]}" if gaps
            else "Prepare a clear timeline of events with document references before the next round."
        ),
    }
