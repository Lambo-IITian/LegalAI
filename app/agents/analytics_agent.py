import logging
from app.services.openai_service import openai_service

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════
# SYSTEM PROMPTS — one per track
# ══════════════════════════════════════════════════════════════

MONETARY_ANALYTICS_PROMPT = """
You are a senior Indian litigation analyst and dispute economics expert.
Analyze the case and produce precise, evidence-grounded quantitative projections.
You will be given claim amount, legal standing, and evidence strength — use them to compute exact figures.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 1 — WIN PROBABILITY CALCULATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Start from legal_standing base:
  WEAK:        base = 25%
  MODERATE:    base = 45%
  STRONG:      base = 65%
  VERY_STRONG: base = 80%

Adjust for evidence_strength_score (0–100):
  score ≥ 75: +12%
  score 55–74: +5%
  score 40–54: 0%
  score 25–39: -8%
  score < 25:  -15%

Adjust for limitation:
  Comfortably within limitation: +5%
  Borderline (approaching limit): -8%
  Potentially time-barred:       -20%

Adjust for respondent type:
  Individual (known assets):  +5% (easier enforcement)
  Individual (unknown assets): 0%
  Small company:              -3%
  Large company (legal dept): -8%

Cap result: 0%–90% (Indian courts are never certainties)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 2 — ZOPA CALCULATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ZOPA = Zone of Possible Agreement (realistic settlement range).
Calculate from claim_amount using evidence_strength_score and legal_standing together:

Base settlement percentage (percentage of claim_amount):
  VERY_STRONG + score ≥ 75: base = 85%
  VERY_STRONG + score < 75: base = 78%
  STRONG + score ≥ 65:      base = 70%
  STRONG + score < 65:      base = 62%
  MODERATE + score ≥ 55:    base = 52%
  MODERATE + score < 55:    base = 42%
  WEAK + any score:         base = 30%

  zopa_optimal  = claim_amount × base_percentage
  zopa_min      = zopa_optimal × 0.75   (floor claimant should accept)
  zopa_max      = min(zopa_optimal × 1.20, claim_amount)  (ceiling respondent might pay)

  negotiation_anchor = zopa_optimal (this is the AI mediator's target)

IMPORTANT: All ZOPA values must be concrete numbers in INR, not null.
IMPORTANT: zopa_min must always be ≥ 0 and zopa_max must be ≤ claim_amount × 1.1

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 3 — COURT COSTS (Indian realistic estimates)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Filing fee:       1–2% of claim amount (min Rs. 200, max Rs. 10,000 for district court)
  Lawyer fees:      Rs. 5,000–Rs. 20,000 per hearing × 15–25 hearings average
  Miscellaneous:    Rs. 5,000–Rs. 15,000 (process fees, copies, documentation)
  Total range:      Rs. 50,000 to Rs. 2,00,000 for most district court cases
  Time to judgment: 24–60 months (2–5 years) in Indian district courts

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 4 — PAYMENT RECOVERY PROBABILITY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Even after winning a civil decree, enforcement is difficult in India.
  Solvent company with assets:      75–85%
  Small/unknown company:            40–55%
  Individual (visible assets):      60–70%
  Individual (no visible assets):   30–50%

Respond ONLY in valid JSON. No text outside JSON.
{
  "win_probability": integer 0-90,
  "win_probability_band": "e.g. 60-70%",
  "win_probability_reasoning": "step-by-step: base=X, adjustments=Y, final=Z",
  "confidence_level": "LOW|MEDIUM|HIGH",
  "confidence_reason": "Why this confidence level — what makes the outcome uncertain",
  "zopa_min": number,
  "zopa_max": number,
  "zopa_optimal": number,
  "zopa_reasoning": "Show the arithmetic: claim_amount × base_pct = optimal; ×0.75 = min; ×1.20 = max",
  "negotiation_anchor": number,
  "court_cost_estimate": number,
  "court_cost_breakdown": {
    "filing_fee": number,
    "lawyer_fees": number,
    "miscellaneous": number
  },
  "settlement_cost": 0,
  "cost_comparison": "Settling saves approximately Rs. X and Y–Z years compared to full litigation",
  "payment_recovery_probability": integer 0-100,
  "payment_recovery_notes": "Why this recovery probability based on respondent type and known assets",
  "time_to_resolution_months": integer,
  "interest_accruing_per_month": number,
  "recommended_path": "mediation|court|lok_adalat|consumer_forum|banking_ombudsman",
  "recommended_path_reason": "Specific reason comparing cost/time/probability across options",
  "settlement_urgency": "LOW|MEDIUM|HIGH",
  "settlement_urgency_reason": "Why settling now is/is not urgent for this specific case"
}
"""


EMPLOYMENT_ANALYTICS_PROMPT = """
You are a senior Indian labour law analyst and dispute economics expert.
Employment disputes have statutory floors — the claimant should NEVER accept below statutory dues.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 1 — WIN PROBABILITY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Base from legal_standing:
  WEAK: 25% | MODERATE: 48% | STRONG: 65% | VERY_STRONG: 78%

Adjust for documentation quality (evidence_strength_score):
  score ≥ 70: +10% | score 50–69: +3% | score < 50: -10%

Adjust for case type:
  Unpaid dues with payslips:          +10%
  Wrongful termination with letter:   +8%
  POSH case with ICC:                 +5%
  Only verbal account:                -15%

Adjust for employer size:
  Large company (500+ employees):  -5% (has legal resources)
  Small company:                   +5% (less legal defense)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 2 — ZOPA FOR EMPLOYMENT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The ZOPA floor is ALWAYS total_statutory_dues — never propose below this.

  statutory_floor = total_statutory_dues (from legal_data)
  zopa_min = statutory_floor (non-negotiable)
  zopa_max = statutory_floor × 1.30  (max 30% above statutory for wrongful termination damages)
  zopa_optimal = statutory_floor × 1.15  (15% above statutory is realistic settlement)

If is_posh_case = true: add Rs. 50,000–Rs. 2,00,000 for harassment damages to zopa_max.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 3 — NON-MONETARY COMPONENTS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Always assess separately — these affect the employee's career:
  Experience letter: HIGH importance — company must issue on letterhead
  Relieving letter:  HIGH importance — required for background verification by new employer
  PF transfer:       STATUTORY — employer must initiate within 30 days

Respond ONLY in valid JSON. No text outside JSON.
{
  "win_probability": integer 0-85,
  "win_probability_band": "e.g. 60-70%",
  "win_probability_reasoning": "step-by-step calculation",
  "confidence_level": "LOW|MEDIUM|HIGH",
  "confidence_reason": "explanation",
  "statutory_dues_floor": number,
  "zopa_min": number,
  "zopa_max": number,
  "zopa_optimal": number,
  "zopa_reasoning": "Show arithmetic: floor=X, optimal=X×1.15=Y, max=X×1.30=Z",
  "negotiation_anchor": number,
  "negotiation_components": {
    "monetary": {
      "floor": number,
      "optimal": number,
      "ceiling": number
    },
    "non_monetary": [
      {
        "item": "experience_letter",
        "importance": "HIGH",
        "deadline_days": 7,
        "compliance_likely": true
      },
      {
        "item": "relieving_letter",
        "importance": "HIGH",
        "deadline_days": 7,
        "compliance_likely": true
      },
      {
        "item": "pf_transfer",
        "importance": "HIGH",
        "deadline_days": 30,
        "compliance_likely": true
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
  "payment_recovery_notes": "Companies generally pay settled amounts — higher than individual respondents"
}
"""


CONSUMER_ANALYTICS_PROMPT = """
You are a senior Indian consumer rights analyst.
Consumer disputes under CPA 2019 have HIGH success rates when documentation is present.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 1 — WIN PROBABILITY (consumer forum)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Consumer Protection Act 2019 has strong consumer-protective provisions.
Base success rates by deficiency type:
  E-commerce non-delivery with order+payment proof:   85%
  Defective product with purchase proof:              75%
  Insurance claim rejection:                          60%
  Banking fraud with RBI complaint:                   68%
  Builder delay (RERA):                               65%
  Service deficiency with communication proof:        70%

Adjust:
  Evidence score ≥ 75:  +5% | score < 50: -10%
  Within 2-year limit:  +0% | borderline: -10%

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 2 — COMPENSATION STRUCTURE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CPA 2019 allows: refund + mental agony compensation + punitive damages + cost.
  refund_amount         = confirmed_claim_amount (full refund is the base)
  compensation_min      = Rs. 5,000 (minimum mental agony for any valid complaint)
  compensation_max      = Rs. 50,000 for typical cases; Rs. 2,00,000+ for egregious deficiency
  total_likely_award    = refund_amount + compensation_midpoint + Rs. 3,000 cost

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 3 — ZOPA FOR CONSUMER DISPUTES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  zopa_min     = refund_amount (company should always offer full refund minimum)
  zopa_max     = refund_amount + compensation_max
  zopa_optimal = refund_amount + compensation_midpoint

Respond ONLY in valid JSON. No text outside JSON.
{
  "win_probability": integer 0-90,
  "win_probability_band": "e.g. 80-88%",
  "win_probability_reasoning": "deficiency type base + adjustments = final",
  "confidence_level": "LOW|MEDIUM|HIGH",
  "confidence_reason": "explanation",
  "refund_amount": number,
  "compensation_above_refund_min": number,
  "compensation_above_refund_max": number,
  "total_likely_award": number,
  "zopa_min": number,
  "zopa_max": number,
  "zopa_optimal": number,
  "zopa_reasoning": "refund=X, comp_mid=Y, optimal=X+Y; min=X; max=X+comp_max",
  "negotiation_anchor": number,
  "forum_success_rate": integer,
  "court_cost_estimate": number,
  "time_to_resolution_months": integer,
  "recommended_path": "consumer_forum|ombudsman|company_escalation|rera|insurance_ombudsman",
  "recommended_path_reason": "explanation comparing paths",
  "settlement_urgency": "LOW|MEDIUM|HIGH",
  "settlement_urgency_reason": "explanation",
  "payment_recovery_probability": integer 0-100,
  "payment_recovery_notes": "Companies ordered by consumer forums generally comply — high enforcement"
}
"""


NON_MONETARY_ANALYTICS_PROMPT = """
You are a senior Indian dispute analyst for non-monetary disputes.
There is NO money amount. Analyze leverage, compliance probability, and negotiation approach.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
LEVERAGE SCORE (0–100)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Start at 40 (neutral base).
  Legal notice from advocate:           +15
  Ongoing relationship (neighbor/co):   +10 (respondent has more to lose)
  Court injunction is clearly available: +20
  Reputational risk to respondent:      +15
  Strong documentary evidence:          +15
  Police complaint is viable:           +10
  Only verbal account:                  -20
  Respondent shows no concern so far:   -10

NEGOTIATION APPROACH:
  Score ≥ 65: "pressure" — apply legal pressure, respondent will likely comply
  Score 40–64: "collaborative" — frame resolution as mutually beneficial
  Score < 40: "formal" — only court/police route likely to work

COMPLIANCE PROBABILITY:
  After legal notice + pressure approach:   60–75%
  After court injunction threat:            75–85%
  Informal request only (what claimant tried): 20–40%

Respond ONLY in valid JSON. No text outside JSON.
{
  "win_probability": integer 0-80,
  "win_probability_band": "e.g. 55-70%",
  "win_probability_reasoning": "leverage-based calculation",
  "confidence_level": "LOW|MEDIUM|HIGH",
  "confidence_reason": "explanation",
  "compliance_probability": integer 0-100,
  "compliance_probability_reason": "Step-by-step: base + adjustments = final",
  "leverage_score": integer 0-100,
  "leverage_factors": ["factor 1 with score impact", "factor 2"],
  "negotiation_approach": "collaborative|pressure|formal",
  "negotiation_approach_reason": "Why this approach for this specific respondent",
  "court_cost_estimate": number,
  "time_to_resolution_months": integer,
  "injunction_success_probability": integer 0-100,
  "recommended_path": "mediation|civil_injunction|police_complaint|consumer_forum",
  "recommended_path_reason": "explanation",
  "settlement_urgency": "LOW|MEDIUM|HIGH",
  "settlement_urgency_reason": "explanation",
  "zopa_min": null,
  "zopa_max": null,
  "zopa_optimal": null,
  "negotiation_anchor": null,
  "payment_recovery_probability": null
}
"""


CRIMINAL_ANALYTICS_PROMPT = """
You are a senior Indian criminal law analyst.
This is a criminal matter — no ZOPA, no mediation. Provide advisory analysis only.

Assess: FIR success probability, prosecution viability, evidence strength, and urgency.

FIR SUCCESS PROBABILITY:
  Strong physical evidence (medical report/photos) + clear cognizable offence: 75–85%
  Digital evidence (screenshots, call records) + cyber offence:               65–75%
  Witness testimony + clear IPC section:                                       60–70%
  Only victim account, no corroboration:                                       40–55%
  Contradictory evidence or delay > 1 year:                                    30–45%

Respond ONLY in valid JSON. No text outside JSON.
{
  "advisory_only": true,
  "win_probability": null,
  "confidence_level": "MEDIUM",
  "confidence_reason": "Criminal outcomes depend on investigation quality and prosecution",
  "fir_success_probability": integer 0-100,
  "fir_success_reason": "Step-by-step reasoning based on evidence available",
  "prosecution_probability": integer 0-100,
  "prosecution_reason": "Whether chargesheet will be filed based on evidence strength",
  "time_to_resolution_months": integer,
  "recommended_path": "fir|magistrate_complaint|high_court_writ|ncw|cyber_cell",
  "recommended_path_reason": "explanation",
  "immediate_actions_urgency": "IMMEDIATE|WITHIN_7_DAYS|WITHIN_30_DAYS",
  "evidence_preservation_priority": "HIGH|MEDIUM|LOW",
  "evidence_preservation_reason": "Why evidence preservation is critical in this case",
  "support_resources": [
    "Police Emergency: 100",
    "NCW Helpline: 181",
    "Cyber Crime Portal: cybercrime.gov.in / 1930",
    "Women Helpline: 1091"
  ],
  "zopa_min": null,
  "zopa_max": null,
  "zopa_optimal": null,
  "negotiation_anchor": null,
  "settlement_urgency": null,
  "payment_recovery_probability": null
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
    Uses gpt-4o (large model for accuracy) — quantitative reasoning.
    Reads intake_data AND legal_data as context.
    ZOPA output consumed by Negotiation Agent.
    """
    track         = case.get("track", "monetary_civil")
    intake_data   = case.get("intake_data", {})
    legal_data    = case.get("legal_data", {})
    system_prompt = TRACK_PROMPTS.get(track, MONETARY_ANALYTICS_PROMPT)

    context = _build_context(case, intake_data, legal_data, track)

    user_message = f"""
Analyze this dispute and produce precise quantitative projections.
Follow the step-by-step calculation rules in your instructions exactly.
Show your reasoning in the _reasoning fields.

DISPUTE OVERVIEW:
{case['dispute_text'][:1200]}

PARTIES:
- Claimant: {case['claimant_name']} | {case['claimant_state']}
- Respondent: {case['respondent_name']} ({case.get('respondent_type', 'individual')})
- Stated claim amount: Rs. {case.get('claim_amount', 0):,.0f}
- Track: {track}

INTAKE ANALYSIS:
{context['intake_summary']}

LEGAL ANALYSIS:
{context['legal_summary']}

KEY QUANTITATIVE INPUTS:
{context['quant_inputs']}

INSTRUCTIONS:
- Calculate win_probability using the exact step-by-step formula in your instructions.
- Calculate ZOPA using the exact formula — show arithmetic in zopa_reasoning.
- For employment: zopa_min MUST equal statutory_dues_floor — never go below it.
- All monetary values must be numbers (not null, not strings) for monetary tracks.
- Return ONLY valid JSON.
"""

    try:
        result = openai_service.call_json(
            system_prompt=system_prompt,
            user_message=user_message,
            use_large_model=True,   # gpt-4o for calculation accuracy
            temperature=0.1,        # low temperature for consistent arithmetic
            max_tokens=2000,
        )

        result = _post_process(result, case, track, intake_data, legal_data)

        logger.info(
            f"Analytics Agent complete | track={track} | "
            f"win_prob={result.get('win_probability')} | "
            f"zopa_min={result.get('zopa_min')} | "
            f"zopa_optimal={result.get('zopa_optimal')} | "
            f"zopa_max={result.get('zopa_max')}"
        )
        return result

    except Exception as e:
        logger.error(f"Analytics Agent failed: {e}")
        return _fallback_analytics(case, track, intake_data, legal_data)


# ── Context Builder ───────────────────────────────────────────

def _build_context(case: dict, intake: dict, legal: dict, track: str) -> dict:

    intake_lines = [
        f"- Severity: {intake.get('severity', 'N/A')}",
        f"- Evidence strength score: {intake.get('evidence_strength_score', 'N/A')}/100",
        f"- Evidence available: {intake.get('evidence_available', [])}",
        f"- Missing proof: {intake.get('missing_proof_checklist', [])}",
        f"- Is time-barred: {intake.get('is_time_barred', False)}",
        f"- Key facts: {intake.get('key_facts', [])}",
        f"- Claimant strengths: {intake.get('claimant_strengths', [])}",
        f"- Claimant weaknesses: {intake.get('claimant_weaknesses', [])}",
    ]
    if track == "employment":
        intake_lines += [
            f"- Employment duration: {intake.get('employment_duration', 'N/A')}",
            f"- Last drawn salary: Rs. {intake.get('last_drawn_salary', 'N/A')}",
            f"- Notice period months: {intake.get('notice_period_months', 'N/A')}",
            f"- Gratuity eligible: {intake.get('gratuity_eligible', False)}",
            f"- Calculated notice pay: Rs. {intake.get('calculated_notice_pay', 0)}",
            f"- Calculated gratuity: Rs. {intake.get('calculated_gratuity', 0)}",
            f"- Dues components: {intake.get('dues_components', [])}",
            f"- Is POSH case: {intake.get('is_posh_case', False)}",
        ]

    legal_lines = [
        f"- Legal standing: {legal.get('legal_standing', 'N/A')}",
        f"- Legal standing reason: {legal.get('legal_standing_reason', 'N/A')}",
        f"- Forum: {legal.get('forum_name', 'N/A')}",
        f"- Within limitation: {legal.get('is_within_limitation', True)}",
        f"- Limitation notes: {legal.get('limitation_notes', 'N/A')}",
        f"- Number of applicable statutes: {len(legal.get('applicable_laws', []))}",
        f"- Respondent defenses: {legal.get('respondent_defenses', [])}",
        f"- Relief available: {legal.get('relief_available', [])}",
    ]
    if track == "employment":
        total_dues = legal.get("total_statutory_dues", 0) or 0
        legal_lines.append(f"- Total statutory dues (confirmed by legal agent): Rs. {total_dues:,.0f}")
        entitlements = legal.get("statutory_entitlements", {})
        for k, v in entitlements.items():
            if isinstance(v, dict) and v.get("amount", 0) > 0:
                legal_lines.append(f"  → {k}: Rs. {v['amount']:,.0f} ({v.get('basis', '')})")

    claim_amount = case.get("claim_amount", 0) or 0
    quant_lines = [
        f"- Confirmed claim amount: Rs. {claim_amount:,.0f}",
        f"- Respondent type: {case.get('respondent_type', 'individual')}",
        f"- Respondent is company: {intake.get('respondent_is_company', False)}",
        f"- State: {case.get('claimant_state', 'India')}",
    ]
    if track == "employment":
        quant_lines.append(
            f"- Statutory dues floor for ZOPA: Rs. {legal.get('total_statutory_dues', 0):,.0f}"
        )
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
    """Validate, clamp, and ensure all ZOPA fields are correct numbers."""

    # Clamp win_probability 0–90
    wp = result.get("win_probability")
    if wp is not None:
        try:
            result["win_probability"] = max(0, min(90, int(wp)))
        except (TypeError, ValueError):
            result["win_probability"] = 50

    if track in ["monetary_civil", "employment", "consumer"]:
        claim = case.get("claim_amount") or 0
        evidence_score = intake.get("evidence_strength_score", 50)
        legal_standing = legal.get("legal_standing", "MODERATE")

        # Validate ZOPA values are present and numeric
        for field in ["zopa_min", "zopa_max", "zopa_optimal", "negotiation_anchor"]:
            val = result.get(field)
            if val is None or not isinstance(val, (int, float)) or val < 0:
                result[field] = _calculate_zopa_fallback(field, claim, evidence_score, legal_standing, track, legal)

        # Employment: zopa_min must be >= statutory_dues_floor
        if track == "employment":
            statutory_floor = legal.get("total_statutory_dues", 0) or 0
            result["statutory_dues_floor"] = statutory_floor
            if statutory_floor > 0:
                result["zopa_min"] = max(result["zopa_min"], statutory_floor)
                result["zopa_optimal"] = max(result["zopa_optimal"], statutory_floor * 1.15)
                result["zopa_max"] = max(result["zopa_max"], statutory_floor * 1.30)

        # Sanity check ordering: min <= optimal <= max
        zopa_min     = max(0, result["zopa_min"])
        zopa_max     = min(claim * 1.3, result["zopa_max"])
        zopa_optimal = max(zopa_min, min(zopa_max, result["zopa_optimal"]))

        result["zopa_min"]     = round(zopa_min, 2)
        result["zopa_max"]     = round(zopa_max, 2)
        result["zopa_optimal"] = round(zopa_optimal, 2)
        result["negotiation_anchor"] = result["zopa_optimal"]

        # Ensure court_cost_estimate is reasonable
        if not result.get("court_cost_estimate") or result["court_cost_estimate"] < 10000:
            result["court_cost_estimate"] = max(50000, claim * 0.05)

    result["track"] = track
    if not result.get("confidence_level"):
        result["confidence_level"] = "MEDIUM"
    if not result.get("recommended_path"):
        result["recommended_path"] = "mediation"

    return result


def _calculate_zopa_fallback(
    field: str,
    claim_amount: float,
    evidence_score: int,
    legal_standing: str,
    track: str,
    legal: dict,
) -> float:
    """Robust fallback ZOPA calculation matching the prompt formula."""
    base_map = {
        ("VERY_STRONG", True):  0.85,
        ("VERY_STRONG", False): 0.78,
        ("STRONG", True):       0.70,
        ("STRONG", False):      0.62,
        ("MODERATE", True):     0.52,
        ("MODERATE", False):    0.42,
        ("WEAK", True):         0.30,
        ("WEAK", False):        0.30,
    }
    high_evidence = evidence_score >= 65
    base = base_map.get((legal_standing, high_evidence), 0.50)
    optimal = claim_amount * base

    if field == "zopa_min":
        if track == "employment":
            return max(legal.get("total_statutory_dues", 0) or 0, round(optimal * 0.75, 2))
        return round(optimal * 0.75, 2)
    elif field == "zopa_max":
        return round(min(optimal * 1.20, claim_amount), 2)
    else:
        return round(optimal, 2)


def _fallback_analytics(case: dict, track: str, intake: dict, legal: dict) -> dict:
    """Safe fallback analytics — always produces concrete ZOPA numbers."""
    claim = case.get("claim_amount") or 0
    evidence_score = intake.get("evidence_strength_score", 40)
    legal_standing = legal.get("legal_standing", "MODERATE")

    if track in ["monetary_civil", "employment", "consumer"]:
        optimal = _calculate_zopa_fallback("zopa_optimal", claim, evidence_score, legal_standing, track, legal)
        zopa_min = _calculate_zopa_fallback("zopa_min", claim, evidence_score, legal_standing, track, legal)
        zopa_max = _calculate_zopa_fallback("zopa_max", claim, evidence_score, legal_standing, track, legal)
    else:
        optimal = zopa_min = zopa_max = None

    return {
        "track":               track,
        "win_probability":     50,
        "win_probability_band": "40–60%",
        "confidence_level":    "LOW",
        "confidence_reason":   "Analytics agent failed — fallback estimates used",
        "zopa_min":            zopa_min,
        "zopa_max":            zopa_max,
        "zopa_optimal":        optimal,
        "negotiation_anchor":  optimal,
        "zopa_reasoning":      "Fallback calculation: base percentage applied to claim amount",
        "court_cost_estimate": max(50000, (claim or 0) * 0.05),
        "court_cost_breakdown": {"filing_fee": 5000, "lawyer_fees": 40000, "miscellaneous": 10000},
        "time_to_resolution_months": 30,
        "recommended_path":    "mediation",
        "recommended_path_reason": "Fallback — mediation always preferable to costly litigation",
        "settlement_urgency":  "MEDIUM",
        "payment_recovery_probability": 60,
        "payment_recovery_notes": "Fallback estimate",
        "error": "Analytics agent failed — fallback output applied",
    }
