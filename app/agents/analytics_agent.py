import logging
from app.services.openai_service import openai_service

logger = logging.getLogger(__name__)


# ── System prompts — one per track ───────────────────────────

MONETARY_ANALYTICS_PROMPT = """
You are a senior Indian litigation analyst and dispute economics expert.
Analyze the case and produce precise quantitative projections.

ZOPA CALCULATION RULES:
- ZOPA (Zone of Possible Agreement) = realistic settlement range
- zopa_min = minimum claimant should accept (evidence-adjusted)
- zopa_max = maximum respondent would realistically pay
- zopa_optimal = most likely settlement point based on legal merits
- Base ZOPA on claim amount, evidence strength, legal standing, precedents
- Weak evidence (score < 40): ZOPA = 30-50% of claim amount
- Medium evidence (40-70): ZOPA = 50-75% of claim amount
- Strong evidence (70+): ZOPA = 70-90% of claim amount
- VERY_STRONG legal standing: ZOPA can reach 90-100% of claim

WIN PROBABILITY FACTORS (adjust base from legal standing):
- WEAK legal standing: 20-35%
- MODERATE: 40-55%
- STRONG: 60-75%
- VERY_STRONG: 75-90%
Then adjust: +10 if evidence score > 70, -10 if < 40
Then adjust: +5 if within limitation, -15 if borderline
Then adjust: +5 if respondent is individual (easier to compel), 
             -5 if large company (has legal team)

COURT COSTS (Indian realistic estimates):
- District court filing fee: Rs. 200-2000 (based on claim amount)
- Lawyer fee per hearing: Rs. 3000-15000
- Average hearings to judgment: 15-25
- Total realistic cost: Rs. 50,000-2,00,000 for most cases
- Time to judgment: 2-5 years typically

PAYMENT RECOVERY: Even after winning, getting money is hard in India.
- Individual respondent with assets: 60-70%
- Company (solvent): 75-85%
- Company (small/unknown): 40-55%
- Individual (unknown assets): 40-60%

Respond ONLY in valid JSON. No text outside JSON.
{
  "win_probability": integer 0-100,
  "win_probability_band": "e.g. 65-75%",
  "confidence_level": "LOW|MEDIUM|HIGH",
  "confidence_reason": "explanation",
  "zopa_min": number,
  "zopa_max": number,
  "zopa_optimal": number,
  "zopa_reasoning": "explanation of how ZOPA was calculated",
  "court_cost_estimate": number,
  "court_cost_breakdown": {
    "filing_fee": number,
    "lawyer_fees": number,
    "miscellaneous": number
  },
  "settlement_cost": number,
  "cost_comparison": "settle saves Rs. X and Y years",
  "payment_recovery_probability": integer 0-100,
  "payment_recovery_notes": "explanation",
  "time_to_resolution_months": integer,
  "interest_accruing_per_month": number,
  "negotiation_anchor": number,
  "recommended_path": "mediation|court|lok_adalat",
  "recommended_path_reason": "explanation",
  "settlement_urgency": "LOW|MEDIUM|HIGH",
  "settlement_urgency_reason": "why settle quickly or not"
}
"""


EMPLOYMENT_ANALYTICS_PROMPT = """
You are a senior Indian labour law analyst and dispute economics expert.
Analyze the employment dispute and produce precise projections.

STATUTORY DUES are the floor — claimant should never accept below statutory amounts.
ZOPA for employment:
- Floor: total statutory dues (notice pay + gratuity + PF)
- Ceiling: statutory dues + 20-30% for harassment/wrongful termination damages
- Optimal: statutory dues + 10-15%

LABOUR COURT SUCCESS RATES (India realistic):
- Wrongful termination with documentation: 55-70%
- Unpaid dues with payslips: 65-75%
- Harassment without witnesses: 30-45%
- POSH case: 50-65% (if properly filed with ICC)

NON-MONETARY components must be tracked separately:
- Experience letter: high compliance if in settlement (easily enforceable)
- Relieving letter: same
- PF transfer: statutory — nearly always enforceable

Respond ONLY in valid JSON. No text outside JSON.
{
  "win_probability": integer 0-100,
  "win_probability_band": "e.g. 60-70%",
  "confidence_level": "LOW|MEDIUM|HIGH",
  "confidence_reason": "explanation",
  "statutory_dues_floor": number,
  "zopa_min": number,
  "zopa_max": number,
  "zopa_optimal": number,
  "zopa_reasoning": "explanation",
  "negotiation_components": {
    "monetary": {
      "floor": number,
      "optimal": number,
      "ceiling": number
    },
    "non_monetary": [
      {
        "item": "experience_letter",
        "importance": "HIGH|MEDIUM|LOW",
        "compliance_likely": true|false
      }
    ]
  },
  "court_cost_estimate": number,
  "labour_court_success_rate": integer,
  "time_to_resolution_months": integer,
  "recommended_path": "demand_letter|labour_court|posh_committee|high_court",
  "recommended_path_reason": "explanation",
  "settlement_urgency": "LOW|MEDIUM|HIGH",
  "settlement_urgency_reason": "explanation",
  "payment_recovery_probability": integer 0-100,
  "negotiation_anchor": number
}
"""


CONSUMER_ANALYTICS_PROMPT = """
You are a senior Indian consumer rights analyst.
Analyze the consumer dispute under Consumer Protection Act 2019.

CONSUMER FORUM SUCCESS RATES (India realistic):
- E-commerce non-delivery with order proof: 80-90%
- Defective product with evidence: 70-80%
- Insurance claim rejection: 55-70%
- Banking fraud with documentation: 65-75%
- Builder delay (RERA): 60-75%

COMPENSATION STRUCTURE (Consumer Protection Act 2019):
- Refund of amount paid
- Compensation for mental agony (typically Rs. 5,000-50,000)
- Punitive damages (in egregious cases)
- Cost of litigation
- Interest on amount from date of complaint

ZOPA for consumer disputes:
- Always includes full refund as minimum
- Add compensation for deficiency: Rs. 5,000-50,000 depending on severity
- Total ZOPA = refund + compensation range

Respond ONLY in valid JSON. No text outside JSON.
{
  "win_probability": integer 0-100,
  "win_probability_band": "e.g. 80-90%",
  "confidence_level": "LOW|MEDIUM|HIGH",
  "confidence_reason": "explanation",
  "zopa_min": number,
  "zopa_max": number,
  "zopa_optimal": number,
  "zopa_reasoning": "explanation",
  "refund_amount": number,
  "compensation_above_refund_min": number,
  "compensation_above_refund_max": number,
  "total_likely_award": number,
  "forum_success_rate": integer,
  "court_cost_estimate": number,
  "time_to_resolution_months": integer,
  "recommended_path": "consumer_forum|ombudsman|company_escalation|court",
  "recommended_path_reason": "explanation",
  "settlement_urgency": "LOW|MEDIUM|HIGH",
  "settlement_urgency_reason": "explanation",
  "payment_recovery_probability": integer 0-100,
  "negotiation_anchor": number
}
"""


NON_MONETARY_ANALYTICS_PROMPT = """
You are a senior Indian dispute analyst for non-monetary disputes.
Analyze this dispute — there is no money amount to calculate.
Focus on compliance probability, leverage, and negotiation approach.

COMPLIANCE PROBABILITY FACTORS:
- Written demand from legal notice: +20%
- Ongoing relationship (neighbor/colleague): 40-60% base
- No ongoing relationship: 20-40% base
- Court injunction threat: +25%
- Reputational risk to respondent: +15%
- Strong evidence: +15%

LEVERAGE SCORE (0-100):
- 0-30: Claimant has little leverage
- 31-60: Moderate leverage — negotiation may work
- 61-80: Strong leverage — respondent will likely comply
- 81-100: Very strong leverage — respondent has strong incentive to settle

NEGOTIATION APPROACHES:
- collaborative: both parties benefit from resolution, ongoing relationship
- pressure: claimant has clear leverage, respondent has reputational risk
- formal: weak voluntary compliance likely, formal legal route better

Respond ONLY in valid JSON. No text outside JSON.
{
  "win_probability": integer 0-100,
  "win_probability_band": "e.g. 50-65%",
  "confidence_level": "LOW|MEDIUM|HIGH",
  "confidence_reason": "explanation",
  "compliance_probability": integer 0-100,
  "compliance_probability_reason": "explanation",
  "leverage_score": integer 0-100,
  "leverage_factors": ["factor1", "factor2"],
  "negotiation_approach": "collaborative|pressure|formal",
  "negotiation_approach_reason": "explanation",
  "court_cost_estimate": number,
  "time_to_resolution_months": integer,
  "injunction_success_probability": integer 0-100,
  "recommended_path": "mediation|civil_injunction|police_complaint",
  "recommended_path_reason": "explanation",
  "settlement_urgency": "LOW|MEDIUM|HIGH",
  "settlement_urgency_reason": "explanation",
  "zopa_min": null,
  "zopa_max": null,
  "zopa_optimal": null,
  "negotiation_anchor": null
}
"""


CRIMINAL_ANALYTICS_PROMPT = """
You are a senior Indian criminal law analyst.
This is a criminal matter — provide advisory analysis only.
There is no ZOPA and no mediation.

Respond ONLY in valid JSON. No text outside JSON.
{
  "advisory_only": true,
  "win_probability": null,
  "confidence_level": "MEDIUM",
  "confidence_reason": "Criminal matters depend heavily on investigation quality",
  "fir_success_probability": integer 0-100,
  "fir_success_reason": "explanation",
  "prosecution_probability": integer 0-100,
  "prosecution_reason": "explanation",
  "time_to_resolution_months": integer,
  "recommended_path": "fir|magistrate_complaint|high_court|ncw|cyber_cell",
  "recommended_path_reason": "explanation",
  "immediate_actions_urgency": "IMMEDIATE|WITHIN_7_DAYS|WITHIN_30_DAYS",
  "evidence_preservation_priority": "HIGH|MEDIUM|LOW",
  "support_resources": ["resource1", "resource2"],
  "zopa_min": null,
  "zopa_max": null,
  "zopa_optimal": null,
  "negotiation_anchor": null,
  "settlement_urgency": null
}
"""


TRACK_PROMPTS = {
    "monetary_civil": MONETARY_ANALYTICS_PROMPT,
    "employment":     EMPLOYMENT_ANALYTICS_PROMPT,
    "consumer":       CONSUMER_ANALYTICS_PROMPT,
    "non_monetary":   NON_MONETARY_ANALYTICS_PROMPT,
    "criminal":       CRIMINAL_ANALYTICS_PROMPT,
}


async def run_analytics_agent(case: dict) -> dict:
    """
    Agent 3 of 5 — Analytics Agent.
    Uses gpt-4o-mini (small model) — mostly numerical reasoning.
    Reads intake_data AND legal_data as context.
    ZOPA output is consumed by Negotiation Agent (Step 10).
    """
    track         = case.get("track", "monetary_civil")
    intake_data   = case.get("intake_data", {})
    legal_data    = case.get("legal_data", {})
    system_prompt = TRACK_PROMPTS.get(track, MONETARY_ANALYTICS_PROMPT)

    context = _build_context(case, intake_data, legal_data, track)

    user_message = f"""
Analyze this dispute and produce quantitative projections:

DISPUTE:
{case['dispute_text'][:1000]}

PARTIES:
- Claimant: {case['claimant_name']} | {case['claimant_state']}
- Respondent: {case['respondent_name']} ({case.get('respondent_type','individual')})
- Claim amount: Rs. {case.get('claim_amount', 'Not stated')}
- Track: {track}

INTAKE ANALYSIS:
{context['intake_summary']}

LEGAL ANALYSIS:
{context['legal_summary']}

QUANTITATIVE INPUTS:
{context['quant_inputs']}

Produce precise projections.
"""

    try:
        result = openai_service.call_json(
            system_prompt=system_prompt,
            user_message=user_message,
            use_large_model=False,
            temperature=0.2,
            max_tokens=2000,
        )

        result = _post_process(result, case, track, intake_data, legal_data)

        logger.info(
            f"Analytics Agent complete | track={track} | "
            f"win_prob={result.get('win_probability')} | "
            f"zopa_optimal={result.get('zopa_optimal')}"
        )
        return result

    except Exception as e:
        logger.error(f"Analytics Agent failed: {e}")
        return _fallback_analytics(case, track)


# ── Helpers ───────────────────────────────────────────────────

def _build_context(case: dict, intake: dict, legal: dict, track: str) -> dict:

    # Intake summary
    intake_lines = [
        f"- Severity: {intake.get('severity','N/A')}",
        f"- Evidence strength: {intake.get('evidence_strength_score','N/A')}/100",
        f"- Is time-barred: {intake.get('is_time_barred', False)}",
        f"- Key facts count: {len(intake.get('key_facts', []))}",
        f"- Claimant strengths: {intake.get('claimant_strengths',[])}",
        f"- Claimant weaknesses: {intake.get('claimant_weaknesses',[])}",
    ]
    if track == "employment":
        intake_lines += [
            f"- Employment duration: {intake.get('employment_duration','N/A')}",
            f"- Last drawn salary: Rs. {intake.get('last_drawn_salary','N/A')}",
            f"- Dues components: {intake.get('dues_components',[])}",
        ]

    # Legal summary
    legal_lines = [
        f"- Legal standing: {legal.get('legal_standing','N/A')}",
        f"- Forum: {legal.get('forum_name','N/A')}",
        f"- Statutes count: {len(legal.get('applicable_laws',[]))}",
        f"- Within limitation: {legal.get('is_within_limitation', True)}",
        f"- Respondent defenses: {legal.get('respondent_defenses',[])}",
        f"- Relief available: {legal.get('relief_available',[])}",
    ]
    if track == "employment":
        entitlements = legal.get("statutory_entitlements", {})
        legal_lines.append(
            f"- Total statutory dues: Rs. {legal.get('total_statutory_dues','N/A')}"
        )
        for k, v in entitlements.items():
            if isinstance(v, dict) and "amount" in v:
                legal_lines.append(f"  - {k}: Rs. {v['amount']}")

    # Quantitative inputs
    claim_amount = case.get("claim_amount", 0) or 0
    quant_lines  = [
        f"- Stated claim amount: Rs. {claim_amount:,.0f}",
        f"- Respondent type: {case.get('respondent_type','individual')}",
        f"- Respondent is company: {intake.get('respondent_is_company', False)}",
        f"- State: {case.get('claimant_state','India')}",
    ]
    if track == "employment":
        total_dues = legal.get("total_statutory_dues", 0) or 0
        quant_lines.append(f"- Confirmed statutory dues: Rs. {total_dues:,.0f}")
    if track == "consumer":
        from app.core.legal_reference import get_consumer_forum_tier
        tier = get_consumer_forum_tier(claim_amount)
        quant_lines.append(f"- Consumer forum tier: {tier}")

    return {
        "intake_summary": "\n".join(intake_lines),
        "legal_summary":  "\n".join(legal_lines),
        "quant_inputs":   "\n".join(quant_lines),
    }


def _post_process(
    result: dict,
    case: dict,
    track: str,
    intake: dict,
    legal: dict,
) -> dict:
    """Validate, clamp, and enrich analytics output."""

    # Clamp win_probability 0-100
    wp = result.get("win_probability")
    if wp is not None:
        result["win_probability"] = max(0, min(100, int(wp)))

    # Ensure ZOPA fields exist for monetary tracks
    if track in ["monetary_civil", "employment", "consumer"]:
        claim = case.get("claim_amount") or 0

        for field in ["zopa_min", "zopa_max", "zopa_optimal", "negotiation_anchor"]:
            if result.get(field) is None:
                # Fallback calculation if LLM missed it
                evidence_score = intake.get("evidence_strength_score", 50)
                legal_standing = legal.get("legal_standing", "MODERATE")
                result[field] = _calculate_zopa_fallback(
                    field, claim, evidence_score, legal_standing
                )

        # Sanity check ZOPA order: min <= optimal <= max <= claim
        zopa_min     = result.get("zopa_min", 0)
        zopa_max     = result.get("zopa_max", claim)
        zopa_optimal = result.get("zopa_optimal", (zopa_min + zopa_max) / 2)

        zopa_min     = max(0, zopa_min)
        zopa_max     = min(claim * 1.3, zopa_max)  # max 130% of claim
        zopa_optimal = max(zopa_min, min(zopa_max, zopa_optimal))

        result["zopa_min"]     = round(zopa_min, 2)
        result["zopa_max"]     = round(zopa_max, 2)
        result["zopa_optimal"] = round(zopa_optimal, 2)

        if result.get("negotiation_anchor") is None:
            result["negotiation_anchor"] = result["zopa_optimal"]

    # Add track marker
    result["track"] = track

    # Ensure confidence_level exists
    if not result.get("confidence_level"):
        result["confidence_level"] = "MEDIUM"

    # Ensure recommended_path exists
    if not result.get("recommended_path"):
        result["recommended_path"] = "mediation"

    return result


def _calculate_zopa_fallback(
    field: str,
    claim_amount: float,
    evidence_score: int,
    legal_standing: str,
) -> float:
    """
    Fallback ZOPA calculation if LLM output is missing.
    Based on evidence score and legal standing.
    """
    standing_multipliers = {
        "WEAK":        0.35,
        "MODERATE":    0.55,
        "STRONG":      0.72,
        "VERY_STRONG": 0.88,
    }
    base = standing_multipliers.get(legal_standing, 0.55)

    # Adjust for evidence
    if evidence_score >= 70:
        base += 0.08
    elif evidence_score < 40:
        base -= 0.10

    base = max(0.2, min(0.95, base))

    if field == "zopa_min":
        return round(claim_amount * (base - 0.15), 2)
    elif field == "zopa_max":
        return round(claim_amount * (base + 0.12), 2)
    elif field == "zopa_optimal":
        return round(claim_amount * base, 2)
    else:  # negotiation_anchor
        return round(claim_amount * base, 2)


def _fallback_analytics(case: dict, track: str) -> dict:
    """Safe fallback so pipeline never crashes."""
    claim = case.get("claim_amount") or 0
    return {
        "track":               track,
        "win_probability":     50,
        "win_probability_band": "40-60%",
        "confidence_level":    "LOW",
        "confidence_reason":   "Analytics agent failed — fallback values",
        "zopa_min":            round(claim * 0.40, 2),
        "zopa_max":            round(claim * 0.85, 2),
        "zopa_optimal":        round(claim * 0.62, 2),
        "negotiation_anchor":  round(claim * 0.62, 2),
        "court_cost_estimate": 75000,
        "time_to_resolution_months": 30,
        "recommended_path":    "mediation",
        "recommended_path_reason": "Fallback — mediation always preferable",
        "settlement_urgency":  "MEDIUM",
        "payment_recovery_probability": 60,
        "error": "Analytics agent failed — fallback output applied",
    }