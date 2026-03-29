import logging
from app.services.openai_service import openai_service

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════
# BASE INSTRUCTIONS — appended to every track prompt
# ══════════════════════════════════════════════════════════════

BASE_INSTRUCTIONS = """
EVIDENCE STRENGTH SCORE (0-100):
  0-30:   Only verbal/claimant account, no documentation
  31-60:  Some documentation but incomplete
          (WhatsApp messages, photos but no contract)
  61-80:  Clear documentation (contract + payment proof + written proof)
  81-100: Comprehensive (signed agreement + receipts + witnesses + official records)

SEVERITY LEVELS:
  LOW:      Minor dispute, small amount (<Rs.10,000), no ongoing harm
  MEDIUM:   Significant dispute, amounts Rs.10,000-Rs.2,00,000, clear legal basis
  HIGH:     Large amounts (>Rs.2,00,000) or significant harm, strong legal basis
  CRIMINAL: Any violence, assault, threat, fraud (criminal), sexual harassment

TIME BAR (Limitation Act 1963):
  Contract breach, rent deposit, salary:  3 years
  Consumer disputes:                      2 years (Consumer Protection Act)
  Cheque bounce (NI Act Section 138):     1 month for complaint
  Defamation:                             1 year
  Labour court (some states):             3 years

Always respond ONLY in valid JSON. No text outside JSON.
"""


# ══════════════════════════════════════════════════════════════
# TRACK SYSTEM PROMPTS
# ══════════════════════════════════════════════════════════════

MONETARY_CIVIL_PROMPT = BASE_INSTRUCTIONS + """
You are a senior Indian legal intake specialist for monetary civil disputes.
Extract all facts precisely from the dispute description.

Respond in this exact JSON structure:
{
  "dispute_type": "string — e.g. Security Deposit Dispute",
  "dispute_category": "rental_deposit|unpaid_salary|consumer_fraud|contract_breach|property_damage|loan_default|cheque_bounce|defamation|other",
  "track_confirmed": "monetary_civil",
  "severity": "LOW|MEDIUM|HIGH",
  "key_facts": ["fact 1", "fact 2", "fact 3"],
  "parties_summary": "One line summary of who is disputing what",
  "incident_date_confirmed": "date string or null",
  "jurisdiction_state": "Indian state name",
  "jurisdiction_city": "city or null",
  "evidence_available": ["Rental agreement", "Bank transfer receipt"],
  "evidence_strength_score": 0-100,
  "is_time_barred": false,
  "limitation_notes": "explanation or null",
  "respondent_is_company": false,
  "key_issues": ["Issue 1", "Issue 2"],
  "claimant_strengths": ["Has signed agreement", "Has payment proof"],
  "claimant_weaknesses": ["No move-out inspection report"],
  "confirmed_claim_amount": 45000,
  "currency": "INR",
  "payment_history_mentioned": true,
  "amount_disputed_by_respondent": true,
  "recommended_approach": "mediation|demand_letter|consumer_forum|labour_court|civil_court"
}
"""


NON_MONETARY_PROMPT = BASE_INSTRUCTIONS + """
You are a senior Indian legal intake specialist for non-monetary disputes.
There is NO money amount in these disputes. Resolution = specific actions.

Respond in this exact JSON structure:
{
  "dispute_type": "string — e.g. Noise Complaint",
  "dispute_category": "apology_demand|neighbor_dispute|noise|boundary|academic|social_media|other",
  "track_confirmed": "non_monetary",
  "severity": "LOW|MEDIUM|HIGH",
  "key_facts": ["fact 1", "fact 2"],
  "parties_summary": "One line summary",
  "incident_date_confirmed": "date or null",
  "jurisdiction_state": "state",
  "jurisdiction_city": "city or null",
  "evidence_available": ["Evidence types mentioned"],
  "evidence_strength_score": 0-100,
  "is_time_barred": false,
  "limitation_notes": null,
  "respondent_is_company": false,
  "key_issues": ["Issue 1"],
  "claimant_strengths": ["strength 1"],
  "claimant_weaknesses": ["weakness 1"],
  "specific_demands": ["Stop music after 10pm", "Written apology"],
  "harm_type": "reputational|financial|emotional|physical_space|other",
  "ongoing_harm": true,
  "recommended_approach": "mediation|civil_injunction|police_complaint"
}
"""


EMPLOYMENT_PROMPT = BASE_INSTRUCTIONS + """
You are a senior Indian legal intake specialist for employment disputes.
Calculate statutory dues precisely when salary and duration are available.

Respond in this exact JSON structure:
{
  "dispute_type": "string — e.g. Wrongful Termination",
  "dispute_category": "wrongful_termination|unpaid_dues|posh_harassment|experience_letter|pf_gratuity|non_compete|other",
  "track_confirmed": "employment",
  "severity": "LOW|MEDIUM|HIGH",
  "key_facts": ["fact 1", "fact 2"],
  "parties_summary": "One line summary",
  "incident_date_confirmed": "date or null",
  "jurisdiction_state": "state",
  "jurisdiction_city": "city or null",
  "evidence_available": ["Offer letter", "Payslips"],
  "evidence_strength_score": 0-100,
  "is_time_barred": false,
  "limitation_notes": null,
  "respondent_is_company": true,
  "key_issues": ["Issue 1"],
  "claimant_strengths": ["Has offer letter"],
  "claimant_weaknesses": ["No termination letter"],
  "employment_duration": "3 years 2 months",
  "designation": "Software Engineer or null",
  "last_drawn_salary": 30000,
  "dues_components": ["notice_period_pay", "gratuity", "pf", "experience_letter"],
  "is_posh_case": false,
  "termination_reason_given": "Performance issues or null",
  "confirmed_claim_amount": 135000,
  "currency": "INR",
  "recommended_approach": "demand_letter|labour_court|posh_committee|civil_court"
}
"""


CONSUMER_PROMPT = BASE_INSTRUCTIONS + """
You are a senior Indian legal intake specialist for consumer disputes.
Consumer Protection Act 2019 is the primary statute.
Consumer forum tier: District (<Rs.50L), State (Rs.50L-2Cr), National (>Rs.2Cr).

Respond in this exact JSON structure:
{
  "dispute_type": "string — e.g. E-commerce Non-Delivery",
  "dispute_category": "ecommerce|defective_product|insurance|banking|telecom|real_estate|other",
  "track_confirmed": "consumer",
  "severity": "LOW|MEDIUM|HIGH",
  "key_facts": ["fact 1", "fact 2"],
  "parties_summary": "One line summary",
  "incident_date_confirmed": "date or null",
  "jurisdiction_state": "state",
  "jurisdiction_city": "city or null",
  "evidence_available": ["Order confirmation", "Payment receipt"],
  "evidence_strength_score": 0-100,
  "is_time_barred": false,
  "limitation_notes": "2 years under Consumer Protection Act or null",
  "respondent_is_company": true,
  "key_issues": ["Non-delivery", "Refusal to refund"],
  "claimant_strengths": ["Has order proof", "Has payment proof"],
  "claimant_weaknesses": [],
  "company_name": "ShopEasy Pvt Ltd",
  "transaction_reference": "ORD-2025-78234 or null",
  "product_service": "Laptop or null",
  "consumer_forum_tier": "district|state|national",
  "deficiency_type": "non_delivery|defective|overcharging|service_failure|other",
  "confirmed_claim_amount": 65000,
  "currency": "INR",
  "recommended_approach": "consumer_forum|banking_ombudsman|rera|insurance_ombudsman|civil_court"
}
"""


CRIMINAL_PROMPT = BASE_INSTRUCTIONS + """
You are a senior Indian legal intake specialist for criminal matters.
IMPORTANT: Criminal cases cannot be mediated. This is advisory only.
Focus on evidence preservation, FIR filing guidance, and safety.

Respond in this exact JSON structure:
{
  "dispute_type": "string — e.g. Physical Assault",
  "dispute_category": "assault|domestic_violence|sexual_harassment|stalking|fraud_criminal|cybercrime|threats|other",
  "track_confirmed": "criminal",
  "severity": "HIGH|CRIMINAL",
  "key_facts": ["fact 1", "fact 2"],
  "parties_summary": "One line summary",
  "incident_date_confirmed": "date or null",
  "jurisdiction_state": "state",
  "jurisdiction_city": "city or null",
  "evidence_available": ["Medical report", "Photographs"],
  "evidence_strength_score": 0-100,
  "is_time_barred": false,
  "limitation_notes": "Criminal cases generally have no limitation period for serious offences",
  "respondent_is_company": false,
  "key_issues": ["Physical assault occurred", "Evidence of harm"],
  "claimant_strengths": ["Medical report available"],
  "claimant_weaknesses": ["No witnesses mentioned"],
  "criminal_sections_likely": ["IPC 323", "IPC 506"],
  "immediate_danger": false,
  "recommended_authority": "local_police|women_cell|cyber_cell|ncw|nhrc",
  "fir_advisable": true,
  "support_resources": ["Police: 100", "NCW Helpline: 181"],
  "mediation_possible": false,
  "recommended_approach": "fir|magistrate_complaint|high_court"
}
"""


TRACK_PROMPTS = {
    "monetary_civil": MONETARY_CIVIL_PROMPT,
    "non_monetary":   NON_MONETARY_PROMPT,
    "employment":     EMPLOYMENT_PROMPT,
    "consumer":       CONSUMER_PROMPT,
    "criminal":       CRIMINAL_PROMPT,
}


# ══════════════════════════════════════════════════════════════
# MAIN FUNCTION
# ══════════════════════════════════════════════════════════════

async def run_intake_agent(case: dict) -> dict:
    """
    Agent 1 of 5 — Intake Agent.
    Uses gpt-4o-mini (fast + cheap) — classification work.
    Selects prompt based on track from Case Router.
    Returns structured intake_data stored on case document.
    """
    track         = case.get("track", "monetary_civil")
    system_prompt = TRACK_PROMPTS.get(track, MONETARY_CIVIL_PROMPT)

    user_message = f"""
Analyze this dispute carefully:

DISPUTE TEXT:
{case['dispute_text']}

CONTEXT:
- Claimant: {case['claimant_name']}
  Location: {case['claimant_city']}, {case['claimant_state']}
- Respondent: {case['respondent_name']}
  Type: {case.get('respondent_type', 'individual')}
  Company: {case.get('respondent_company_name', 'N/A')}
- Claim amount stated: {case.get('claim_amount', 'Not stated')} {case.get('currency', 'INR')}
- Incident date: {case.get('incident_date', 'Not specified')}
- Track pre-classified as: {track}
- Case router notes: {case.get('routing', {}).get('routing_notes', 'None')}

Extract all facts and produce the structured JSON analysis.
"""

    try:
        result = openai_service.call_json(
            system_prompt=system_prompt,
            user_message=user_message,
            use_large_model=False,   # gpt-4o-mini — fast enough for classification
            temperature=0.2,
            max_tokens=1500,
        )

        # Always ensure track_confirmed matches the router
        result["track_confirmed"] = track

        # Validate evidence_strength_score is 0-100
        score = result.get("evidence_strength_score", 50)
        result["evidence_strength_score"] = max(0, min(100, int(score)))

        logger.info(
            f"Intake Agent complete | track={track} | "
            f"severity={result.get('severity')} | "
            f"evidence_score={result.get('evidence_strength_score')} | "
            f"category={result.get('dispute_category')}"
        )
        return result

    except Exception as e:
        logger.error(f"Intake Agent failed: {e}")
        return _fallback_intake(case, track, str(e))


def _fallback_intake(case: dict, track: str, error: str) -> dict:
    """
    Safe fallback so the pipeline never crashes even if intake fails.
    Downstream agents receive minimal but valid data.
    """
    return {
        "dispute_type":            "Unknown",
        "dispute_category":        "other",
        "track_confirmed":         track,
        "severity":                "MEDIUM",
        "key_facts":               [case["dispute_text"][:200]],
        "parties_summary":         f"{case['claimant_name']} vs {case['respondent_name']}",
        "incident_date_confirmed": case.get("incident_date"),
        "jurisdiction_state":      case.get("claimant_state", "India"),
        "jurisdiction_city":       case.get("claimant_city"),
        "evidence_available":      [],
        "evidence_strength_score": 40,
        "is_time_barred":          False,
        "limitation_notes":        None,
        "respondent_is_company":   case.get("respondent_type") == "company",
        "key_issues":              ["To be determined"],
        "claimant_strengths":      [],
        "claimant_weaknesses":     [],
        "confirmed_claim_amount":  case.get("claim_amount"),
        "currency":                case.get("currency", "INR"),
        "recommended_approach":    "mediation",
        "error":                   error,
    }