import logging
from app.services.openai_service import openai_service

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════
# BASE INSTRUCTIONS — shared across all tracks
# ══════════════════════════════════════════════════════════════

BASE_INSTRUCTIONS = """
You are an expert Indian legal intake specialist. Extract ALL facts precisely from the dispute text.
Do not invent facts. If information is not stated, use null.

EVIDENCE STRENGTH SCORE (0–100) — calculate rigorously:
  0–20:  Only verbal/oral account, zero documentation
  21–40: Single document or screenshot, no corroboration
  41–60: Multiple documents but gaps exist (e.g. contract but no payment proof)
  61–80: Strong documentation set (contract + payment proof + written correspondence)
  81–100: Comprehensive (signed agreement + receipts + witnesses + official records + timestamps)

SEVERITY LEVELS — apply precisely:
  LOW:      Amount < Rs.10,000 OR minor inconvenience, no ongoing harm, weak legal basis
  MEDIUM:   Amount Rs.10,000–Rs.2,00,000 OR moderate harm, clear legal basis
  HIGH:     Amount > Rs.2,00,000 OR significant ongoing harm, strong legal basis
  CRIMINAL: Any violence / assault / threat / fraud (IPC 420) / sexual offence — regardless of amount

LIMITATION ACT 1963 — apply strictly:
  Contract breach, rent deposit, salary arrears:    3 years from date of cause of action
  Consumer disputes (Consumer Protection Act 2019): 2 years from date of complaint cause
  Cheque bounce (NI Act S.138):                     30 days after demand notice expiry
  Defamation (civil):                               1 year from publication
  Labour/employment disputes:                        3 years (state labour court rules vary)
  Criminal matters:                                  No limitation for serious offences

MISSING PROOF CHECKLIST — always identify what the claimant is MISSING that would strengthen the case.

CRITICAL RULES:
- Always respond ONLY in valid JSON. No markdown, no preamble, no text outside JSON.
- confirmed_claim_amount must be a number (integer or float), never a string.
- If claim amount is not mentioned in the dispute text, use null.
- incident_date_confirmed must be ISO date string (YYYY-MM-DD) or null.
"""


# ══════════════════════════════════════════════════════════════
# TRACK SYSTEM PROMPTS
# ══════════════════════════════════════════════════════════════

MONETARY_CIVIL_PROMPT = BASE_INSTRUCTIONS + """
TRACK: MONETARY CIVIL — a specific sum of money is owed.
Applicable categories: security_deposit, unpaid_salary, contract_breach, property_damage,
loan_default, cheque_bounce, defamation_damages, other_monetary.

Respond in this EXACT JSON structure — every field is required:
{
  "dispute_type": "concise label e.g. Security Deposit Withheld",
  "dispute_category": "security_deposit|unpaid_salary|contract_breach|property_damage|loan_default|cheque_bounce|defamation_damages|other_monetary",
  "track_confirmed": "monetary_civil",
  "severity": "LOW|MEDIUM|HIGH",
  "key_facts": ["chronological fact 1", "fact 2", "fact 3", "fact 4"],
  "parties_summary": "One sentence: who owes what to whom and why",
  "incident_date_confirmed": "YYYY-MM-DD or null",
  "jurisdiction_state": "Indian state name",
  "jurisdiction_city": "city name or null",
  "evidence_available": ["list every document/proof MENTIONED by claimant"],
  "evidence_strength_score": 0-100,
  "missing_proof_checklist": ["document 1 that would strengthen the case", "document 2"],
  "is_time_barred": false,
  "limitation_notes": "explanation of limitation status or null",
  "respondent_is_company": false,
  "key_issues": ["Issue 1: e.g. Whether deposit was rightfully withheld", "Issue 2"],
  "claimant_strengths": ["strength 1", "strength 2"],
  "claimant_weaknesses": ["weakness 1", "weakness 2"],
  "confirmed_claim_amount": 45000,
  "currency": "INR",
  "payment_history_mentioned": true,
  "amount_disputed_by_respondent": true,
  "recommended_approach": "mediation|demand_letter|consumer_forum|labour_court|civil_court|lok_adalat"
}
"""


NON_MONETARY_PROMPT = BASE_INSTRUCTIONS + """
TRACK: NON-MONETARY — no money is demanded. Resolution requires specific behavioral actions.
Applicable categories: apology_demand, noise_nuisance, boundary_dispute,
neighbour_dispute, academic_dispute, social_media_defamation, other_non_monetary.

Respond in this EXACT JSON structure — every field is required:
{
  "dispute_type": "concise label e.g. Chronic Noise Nuisance",
  "dispute_category": "apology_demand|noise_nuisance|boundary_dispute|neighbour_dispute|academic_dispute|social_media_defamation|other_non_monetary",
  "track_confirmed": "non_monetary",
  "severity": "LOW|MEDIUM|HIGH",
  "key_facts": ["fact 1", "fact 2", "fact 3"],
  "parties_summary": "One sentence: who is doing what to whom",
  "incident_date_confirmed": "YYYY-MM-DD or null",
  "jurisdiction_state": "Indian state name",
  "jurisdiction_city": "city or null",
  "evidence_available": ["evidence 1", "evidence 2"],
  "evidence_strength_score": 0-100,
  "missing_proof_checklist": ["missing item 1", "missing item 2"],
  "is_time_barred": false,
  "limitation_notes": null,
  "respondent_is_company": false,
  "key_issues": ["Issue 1", "Issue 2"],
  "claimant_strengths": ["strength 1"],
  "claimant_weaknesses": ["weakness 1"],
  "specific_demands": ["Demand 1 — time-bound e.g. Remove post within 48 hours", "Demand 2"],
  "harm_type": "reputational|emotional|physical_space|privacy|other",
  "ongoing_harm": true,
  "confirmed_claim_amount": null,
  "currency": "INR",
  "recommended_approach": "mediation|civil_injunction|police_complaint|consumer_forum"
}
"""


EMPLOYMENT_PROMPT = BASE_INSTRUCTIONS + """
TRACK: EMPLOYMENT — all workplace disputes.
Applicable categories: wrongful_termination, unpaid_dues, posh_harassment,
experience_letter_withheld, pf_gratuity_default, non_compete_violation, other_employment.

STATUTORY CALCULATION RULES (apply precisely if salary and duration are provided):
- Notice period pay: last_drawn_salary × notice_period_months
- Gratuity: (last_drawn_salary × 15 × completed_years_of_service) ÷ 26
  → Gratuity ONLY applicable if service ≥ 5 years
- PF: Employer must contribute 12% of basic salary; claimant can claim unpaid employer PF
- Variable pay / bonus: only if contractually promised

Extract employment duration as "X years Y months" by calculating from joining date to termination date if both are mentioned.

Respond in this EXACT JSON structure — every field is required:
{
  "dispute_type": "concise label e.g. Wrongful Termination With Withheld Dues",
  "dispute_category": "wrongful_termination|unpaid_dues|posh_harassment|experience_letter_withheld|pf_gratuity_default|non_compete_violation|other_employment",
  "track_confirmed": "employment",
  "severity": "LOW|MEDIUM|HIGH",
  "key_facts": ["fact 1", "fact 2", "fact 3", "fact 4"],
  "parties_summary": "One sentence: who was employed where, what happened",
  "incident_date_confirmed": "YYYY-MM-DD or null",
  "jurisdiction_state": "Indian state name",
  "jurisdiction_city": "city or null",
  "evidence_available": ["Offer letter", "Payslips", "Termination email"],
  "evidence_strength_score": 0-100,
  "missing_proof_checklist": ["missing item 1", "missing item 2"],
  "is_time_barred": false,
  "limitation_notes": null,
  "respondent_is_company": true,
  "key_issues": ["Issue 1: Was termination lawful?", "Issue 2: Are statutory dues outstanding?"],
  "claimant_strengths": ["strength 1"],
  "claimant_weaknesses": ["weakness 1"],
  "employment_duration": "3 years 2 months",
  "designation": "Software Engineer or null",
  "last_drawn_salary": 30000,
  "dues_components": ["notice_period_pay", "gratuity", "pf", "experience_letter"],
  "gratuity_eligible": false,
  "notice_period_months": 1,
  "calculated_notice_pay": 30000,
  "calculated_gratuity": 0,
  "is_posh_case": false,
  "termination_reason_given": "Performance issues or null",
  "confirmed_claim_amount": 60000,
  "currency": "INR",
  "recommended_approach": "demand_letter|labour_court|posh_committee|high_court"
}
"""


CONSUMER_PROMPT = BASE_INSTRUCTIONS + """
TRACK: CONSUMER — disputes under Consumer Protection Act 2019.
Applicable categories: ecommerce_non_delivery, defective_product, insurance_rejection,
banking_fraud, telecom_billing, real_estate_delay, service_deficiency, other_consumer.

Consumer forum tiers (apply based on confirmed_claim_amount):
- District Commission:  claim ≤ Rs. 50,00,000 (50 lakh)
- State Commission:     claim Rs. 50L to Rs. 2 crore
- National Commission:  claim > Rs. 2 crore

Respond in this EXACT JSON structure — every field is required:
{
  "dispute_type": "concise label e.g. E-commerce Non-Delivery with Refund Refusal",
  "dispute_category": "ecommerce_non_delivery|defective_product|insurance_rejection|banking_fraud|telecom_billing|real_estate_delay|service_deficiency|other_consumer",
  "track_confirmed": "consumer",
  "severity": "LOW|MEDIUM|HIGH",
  "key_facts": ["fact 1", "fact 2", "fact 3"],
  "parties_summary": "One sentence: claimant bought what from whom, what went wrong",
  "incident_date_confirmed": "YYYY-MM-DD or null",
  "jurisdiction_state": "Indian state name",
  "jurisdiction_city": "city or null",
  "evidence_available": ["Order confirmation", "Payment receipt", "Screenshot of refusal"],
  "evidence_strength_score": 0-100,
  "missing_proof_checklist": ["missing item 1", "missing item 2"],
  "is_time_barred": false,
  "limitation_notes": "2 years under Consumer Protection Act 2019",
  "respondent_is_company": true,
  "key_issues": ["Issue 1: Was there deficiency of service?", "Issue 2: Is refund due?"],
  "claimant_strengths": ["strength 1"],
  "claimant_weaknesses": ["weakness 1"],
  "company_name": "ShopEasy Pvt Ltd or null",
  "transaction_reference": "ORD-2025-78234 or null",
  "product_service": "Laptop / Insurance Policy / Apartment or null",
  "consumer_forum_tier": "district|state|national",
  "deficiency_type": "non_delivery|defective|overcharging|service_failure|insurance_rejection|other",
  "confirmed_claim_amount": 65000,
  "currency": "INR",
  "recommended_approach": "consumer_forum|banking_ombudsman|rera|insurance_ombudsman|telecom_appellate"
}
"""


CRIMINAL_PROMPT = BASE_INSTRUCTIONS + """
TRACK: CRIMINAL — involves cognizable criminal offence.
IMPORTANT: Criminal cases CANNOT be mediated. This is legal advisory only.
Focus: safety, evidence preservation, FIR guidance, appropriate authority referral.

Applicable categories: physical_assault, domestic_violence, sexual_harassment_criminal,
stalking, criminal_fraud_420, cybercrime, criminal_threats_506, other_criminal.

Respond in this EXACT JSON structure — every field is required:
{
  "dispute_type": "concise label e.g. Physical Assault with Criminal Threats",
  "dispute_category": "physical_assault|domestic_violence|sexual_harassment_criminal|stalking|criminal_fraud_420|cybercrime|criminal_threats_506|other_criminal",
  "track_confirmed": "criminal",
  "severity": "HIGH|CRIMINAL",
  "key_facts": ["fact 1", "fact 2", "fact 3"],
  "parties_summary": "One sentence: what criminal act occurred",
  "incident_date_confirmed": "YYYY-MM-DD or null",
  "jurisdiction_state": "Indian state name",
  "jurisdiction_city": "city or null",
  "evidence_available": ["Medical report", "Screenshots", "Photographs"],
  "evidence_strength_score": 0-100,
  "missing_proof_checklist": ["missing item 1"],
  "is_time_barred": false,
  "limitation_notes": "Criminal cases: no limitation period for serious cognizable offences under IPC",
  "respondent_is_company": false,
  "key_issues": ["Issue 1: Whether offence is cognizable", "Issue 2: Availability of evidence"],
  "claimant_strengths": ["Medical report available"],
  "claimant_weaknesses": ["No witnesses mentioned"],
  "criminal_sections_likely": ["IPC 323", "IPC 506"],
  "immediate_danger": false,
  "recommended_authority": "local_police|women_cell|cyber_cell|ncw|nhrc|anti_corruption",
  "fir_advisable": true,
  "support_resources": ["Police Emergency: 100", "NCW Helpline: 181", "Cyber Crime: cybercrime.gov.in"],
  "mediation_possible": false,
  "confirmed_claim_amount": null,
  "currency": "INR",
  "recommended_approach": "fir|magistrate_complaint|high_court_writ"
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
    Uses gpt-4o-mini (fast + cheap) — classification and fact extraction.
    Selects prompt based on track from Case Router.
    Returns structured intake_data stored on case document.
    """
    track         = case.get("track", "monetary_civil")
    system_prompt = TRACK_PROMPTS.get(track, MONETARY_CIVIL_PROMPT)

    user_message = f"""
Analyze this dispute carefully and extract ALL facts precisely.

DISPUTE TEXT (primary source — extract everything from here):
{case['dispute_text']}

SUBMISSION CONTEXT (use to fill gaps only):
- Claimant: {case['claimant_name']}
- Location: {case['claimant_city']}, {case['claimant_state']}
- Respondent: {case['respondent_name']}
- Respondent Type: {case.get('respondent_type', 'individual')}
- Company Name: {case.get('respondent_company_name', 'N/A')}
- Claim amount as submitted by claimant: {case.get('claim_amount', 'Not stated')} {case.get('currency', 'INR')}
- Incident date as submitted: {case.get('incident_date', 'Not specified')}
- Track pre-classified as: {track}
- Router notes: {case.get('routing', {}).get('routing_notes', 'None')}

INSTRUCTIONS:
1. Extract confirmed_claim_amount from the dispute text if explicitly mentioned. If not, use the submission context amount. If neither, use null.
2. Calculate evidence_strength_score honestly — do not inflate it.
3. Identify every document the claimant DOES have and every document they are MISSING.
4. Identify all key legal issues in the dispute.
5. Return ONLY valid JSON matching the required structure.
"""

    try:
        result = openai_service.call_json(
            system_prompt=system_prompt,
            user_message=user_message,
            use_large_model=False,
            temperature=0.1,
            max_tokens=1800,
        )

        # Enforce track consistency
        result["track_confirmed"] = track

        # Validate and clamp evidence_strength_score
        score = result.get("evidence_strength_score", 40)
        try:
            result["evidence_strength_score"] = max(0, min(100, int(score)))
        except (TypeError, ValueError):
            result["evidence_strength_score"] = 40

        # Ensure missing_proof_checklist always exists
        if not isinstance(result.get("missing_proof_checklist"), list):
            result["missing_proof_checklist"] = []

        # Ensure key lists always exist
        for field in ["key_facts", "claimant_strengths", "claimant_weaknesses",
                      "evidence_available", "key_issues"]:
            if not isinstance(result.get(field), list):
                result[field] = []

        # Coerce confirmed_claim_amount to number
        raw_amount = result.get("confirmed_claim_amount")
        if isinstance(raw_amount, str):
            try:
                result["confirmed_claim_amount"] = float(
                    raw_amount.replace("Rs.", "").replace("Rs", "")
                    .replace(",", "").replace("₹", "").strip()
                )
            except ValueError:
                result["confirmed_claim_amount"] = case.get("claim_amount")
        elif raw_amount is None:
            result["confirmed_claim_amount"] = case.get("claim_amount")

        logger.info(
            f"Intake Agent complete | track={track} | "
            f"severity={result.get('severity')} | "
            f"evidence_score={result.get('evidence_strength_score')} | "
            f"category={result.get('dispute_category')} | "
            f"claim_amount={result.get('confirmed_claim_amount')}"
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
        "key_facts":               [case.get("dispute_text", "")[:200]],
        "parties_summary":         f"{case['claimant_name']} vs {case['respondent_name']}",
        "incident_date_confirmed": case.get("incident_date"),
        "jurisdiction_state":      case.get("claimant_state", "India"),
        "jurisdiction_city":       case.get("claimant_city"),
        "evidence_available":      [],
        "evidence_strength_score": 35,
        "missing_proof_checklist": ["All supporting documents — intake failed"],
        "is_time_barred":          False,
        "limitation_notes":        None,
        "respondent_is_company":   case.get("respondent_type") == "company",
        "key_issues":              ["To be determined — intake agent failed"],
        "claimant_strengths":      [],
        "claimant_weaknesses":     ["Intake analysis unavailable"],
        "confirmed_claim_amount":  case.get("claim_amount"),
        "currency":                case.get("currency", "INR"),
        "recommended_approach":    "mediation",
        "error":                   error,
    }
