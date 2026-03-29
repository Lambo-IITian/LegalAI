import logging
from datetime import datetime, timezone
from app.services.openai_service import openai_service
from app.core.legal_reference import (
    get_consumer_forum_tier,
    get_rent_control_act,
    get_limitation_period,
)

logger = logging.getLogger(__name__)


# ── System prompts — one per track ───────────────────────────

MONETARY_CIVIL_PROMPT = """
You are a senior Indian advocate specializing in civil litigation.
Analyze the dispute and provide a complete legal assessment.

Focus on these statutes for monetary civil disputes:
- Transfer of Property Act 1882 (rent/deposit)
- Indian Contract Act 1872 (breach of contract)
- Specific Relief Act 1963
- Code of Civil Procedure 1908
- Consumer Protection Act 2019
- Payment of Wages Act 1936 (salary)
- Negotiable Instruments Act 1881 (cheque bounce — Section 138)
- State-specific Rent Control Acts
- IPC Section 420 (fraud component if applicable)
- Interest on Delayed Payment — interest at 18% per annum is standard

For precedents, cite real Indian Supreme Court or High Court judgments.

Respond ONLY in valid JSON. No text outside JSON.
{
  "applicable_laws": [
    {
      "act": "Act name",
      "section": "Section number",
      "relevance": "How it applies to this case",
      "strength": "PRIMARY|SECONDARY|SUPPORTING"
    }
  ],
  "legal_standing": "WEAK|MODERATE|STRONG|VERY_STRONG",
  "legal_standing_reason": "One sentence explanation",
  "jurisdiction_state": "State name",
  "forum": "civil_court|consumer_forum|lok_adalat|high_court",
  "forum_name": "Specific court name e.g. District Civil Court, Delhi",
  "limitation_period_years": number,
  "is_within_limitation": true|false,
  "limitation_notes": "explanation",
  "claimant_rights": ["right1", "right2"],
  "respondent_defenses": ["likely defense1", "likely defense2"],
  "key_legal_issues": ["issue1", "issue2"],
  "precedent_cases": [
    {
      "case_name": "Party A vs Party B",
      "court": "Supreme Court of India",
      "year": 2019,
      "citation": "citation if known",
      "relevance": "how it supports claimant"
    }
  ],
  "legal_notice_required": true|false,
  "legal_notice_notice_period_days": 15,
  "relief_available": ["refund of deposit", "interest at 18% per annum", "litigation costs"],
  "interest_rate_applicable": 18,
  "court_fee_estimate": number,
  "filing_steps": ["step1", "step2"],
  "recommended_immediate_actions": ["action1", "action2"]
}
"""


EMPLOYMENT_PROMPT = """
You are a senior Indian labour law advocate.
Analyze the employment dispute and provide complete legal assessment.

Key statutes for employment disputes:
- Industrial Disputes Act 1947
- Payment of Wages Act 1936
- Payment of Gratuity Act 1972 (5 years service for gratuity eligibility)
- Employees Provident Fund Act 1952
- Shops and Establishments Act (state-specific)
- POSH Act 2013 (Sexual Harassment at Workplace)
- Factories Act 1948 (if applicable)
- Contract Labour Act 1970

STATUTORY CALCULATIONS (always calculate if data available):
- Notice period pay = last_drawn_salary x notice_months
- Gratuity = (last_drawn_salary x 15 x years_of_service) / 26
  (only if service >= 5 years)
- PF: 12% of basic salary from both employer and employee

Respond ONLY in valid JSON. No text outside JSON.
{
  "applicable_laws": [
    {
      "act": "Act name",
      "section": "Section number",
      "relevance": "How it applies",
      "strength": "PRIMARY|SECONDARY|SUPPORTING"
    }
  ],
  "legal_standing": "WEAK|MODERATE|STRONG|VERY_STRONG",
  "legal_standing_reason": "explanation",
  "jurisdiction_state": "state",
  "forum": "labour_court|high_court|posh_committee|civil_court",
  "forum_name": "Specific court/committee name",
  "labour_court_address": "address or null",
  "limitation_period_years": number,
  "is_within_limitation": true|false,
  "limitation_notes": "explanation",
  "claimant_rights": ["right1"],
  "respondent_defenses": ["defense1"],
  "key_legal_issues": ["issue1"],
  "precedent_cases": [
    {
      "case_name": "Name",
      "court": "court",
      "year": 2020,
      "relevance": "how it helps"
    }
  ],
  "legal_notice_required": true,
  "legal_notice_notice_period_days": 15,
  "statutory_entitlements": {
    "notice_period_pay": {"amount": number, "basis": "calculation explanation"},
    "gratuity": {"amount": number, "eligible": true|false, "basis": "explanation"},
    "pf_dues": {"amount": number, "basis": "explanation"},
    "other": []
  },
  "total_statutory_dues": number,
  "posh_committee_route": true|false,
  "posh_notes": "explanation or null",
  "relief_available": ["list"],
  "filing_steps": ["step1"],
  "recommended_immediate_actions": ["action1"]
}
"""


CONSUMER_PROMPT = """
You are a senior Indian consumer law advocate.
Analyze the consumer dispute under Consumer Protection Act 2019.

Key statutes:
- Consumer Protection Act 2019 (primary)
- Consumer Protection (E-Commerce) Rules 2020
- RERA Act 2016 (real estate disputes)
- Insurance Act 1938 + IRDAI regulations
- RBI Banking Ombudsman Scheme 2006
- TRAI regulations (telecom)
- Sale of Goods Act 1930

Consumer forum tiers (2019 Act):
- District Commission: up to Rs. 50 lakh
- State Commission: Rs. 50 lakh to Rs. 2 crore
- National Commission (NCDRC): above Rs. 2 crore

Compensation available: Refund + Compensation for deficiency + Punitive damages

Respond ONLY in valid JSON. No text outside JSON.
{
  "applicable_laws": [
    {
      "act": "Act name",
      "section": "Section",
      "relevance": "How it applies",
      "strength": "PRIMARY|SECONDARY|SUPPORTING"
    }
  ],
  "legal_standing": "WEAK|MODERATE|STRONG|VERY_STRONG",
  "legal_standing_reason": "explanation",
  "jurisdiction_state": "state",
  "forum": "consumer_forum|banking_ombudsman|rera|insurance_ombudsman|telecom_ombudsman",
  "forum_name": "Specific forum name",
  "consumer_forum_tier": "district|state|national",
  "limitation_period_years": 2,
  "is_within_limitation": true|false,
  "limitation_notes": "explanation",
  "claimant_rights": ["right1"],
  "respondent_defenses": ["defense1"],
  "key_legal_issues": ["issue1"],
  "precedent_cases": [
    {
      "case_name": "Name",
      "court": "NCDRC or State/District Commission",
      "year": 2021,
      "relevance": "how it helps"
    }
  ],
  "legal_notice_required": true,
  "legal_notice_notice_period_days": 15,
  "relief_available": ["refund", "compensation", "punitive_damages"],
  "compensation_likely": number,
  "ombudsman_route": true|false,
  "ombudsman_name": "Banking/Insurance/Telecom Ombudsman or null",
  "court_fee_estimate": number,
  "filing_steps": ["step1"],
  "recommended_immediate_actions": ["action1"]
}
"""


NON_MONETARY_PROMPT = """
You are a senior Indian civil and criminal lawyer.
Analyze this non-monetary dispute.

Key statutes for non-monetary disputes:
- IPC Section 268 (public nuisance)
- IPC Section 294 (obscene acts — if applicable)
- IPC Section 441-462 (property/trespass)
- IPC Section 499-500 (defamation)
- Code of Civil Procedure 1908 — injunction relief
- Specific Relief Act 1963 — mandatory/prohibitory injunction
- IT Act 2000 (online defamation/harassment)
- Protection of Women from Domestic Violence Act 2005 (if applicable)

Respond ONLY in valid JSON. No text outside JSON.
{
  "applicable_laws": [
    {
      "act": "Act name",
      "section": "Section",
      "relevance": "How it applies",
      "strength": "PRIMARY|SECONDARY|SUPPORTING"
    }
  ],
  "legal_standing": "WEAK|MODERATE|STRONG|VERY_STRONG",
  "legal_standing_reason": "explanation",
  "jurisdiction_state": "state",
  "forum": "civil_court|magistrate_court|police|high_court",
  "forum_name": "Specific court name",
  "limitation_period_years": number,
  "is_within_limitation": true|false,
  "limitation_notes": "explanation",
  "claimant_rights": ["right1"],
  "respondent_defenses": ["defense1"],
  "key_legal_issues": ["issue1"],
  "precedent_cases": [
    {
      "case_name": "Name",
      "court": "court",
      "year": 2020,
      "relevance": "relevance"
    }
  ],
  "legal_notice_required": true,
  "legal_notice_notice_period_days": 15,
  "injunction_possible": true|false,
  "injunction_type": "mandatory|prohibitory|null",
  "relief_available": ["apology", "cease and desist", "injunction"],
  "filing_steps": ["step1"],
  "recommended_immediate_actions": ["action1"]
}
"""


CRIMINAL_PROMPT = """
You are a senior Indian criminal lawyer.
This case involves criminal elements — provide legal advisory only (no mediation).

Key criminal statutes:
- IPC Section 323/324/325/326 (assault/grievous hurt)
- IPC Section 354/354A/354B/354C/354D (assault/harassment of women)
- IPC Section 376 (sexual assault)
- IPC Section 406 (criminal breach of trust)
- IPC Section 420 (cheating and fraud)
- IPC Section 498A (cruelty by husband/relatives)
- IPC Section 499/500 (defamation — criminal)
- IPC Section 506 (criminal intimidation/threats)
- IPC Section 509 (word/gesture to insult modesty)
- IT Act 2000 Section 66C/66D (cyber fraud)
- Protection of Women from Domestic Violence Act 2005
- POCSO Act 2012 (if minor involved)

Respond ONLY in valid JSON. No text outside JSON.
{
  "applicable_laws": [
    {
      "act": "Act name",
      "section": "Section",
      "relevance": "How it applies",
      "strength": "PRIMARY|SECONDARY|SUPPORTING"
    }
  ],
  "legal_standing": "MODERATE|STRONG|VERY_STRONG",
  "legal_standing_reason": "explanation",
  "jurisdiction_state": "state",
  "forum": "police|magistrate_court|sessions_court|high_court",
  "forum_name": "Specific court or station",
  "ipc_sections": ["IPC 323", "IPC 506"],
  "bailable_offences": ["IPC 323"],
  "non_bailable_offences": ["IPC 376"],
  "cognizable_offences": ["list"],
  "non_cognizable_offences": ["list"],
  "limitation_period_years": null,
  "is_within_limitation": true,
  "limitation_notes": "Criminal cases generally have no limitation period for serious offences",
  "claimant_rights": ["right1"],
  "key_legal_issues": ["issue1"],
  "precedent_cases": [
    {
      "case_name": "Name",
      "court": "Supreme Court of India",
      "year": 2018,
      "relevance": "relevance"
    }
  ],
  "fir_recommended": true,
  "fir_station_type": "local_police|women_cell|cyber_cell|anti_corruption",
  "immediate_safety_steps": ["step1"],
  "support_resources": ["NCW Helpline: 181", "Police: 100"],
  "mediation_possible": false,
  "filing_steps": ["step1"],
  "recommended_immediate_actions": ["file FIR immediately", "preserve evidence"]
}
"""


TRACK_PROMPTS = {
    "monetary_civil": MONETARY_CIVIL_PROMPT,
    "employment":     EMPLOYMENT_PROMPT,
    "consumer":       CONSUMER_PROMPT,
    "non_monetary":   NON_MONETARY_PROMPT,
    "criminal":       CRIMINAL_PROMPT,
}


async def run_legal_agent(case: dict) -> dict:
    """
    Agent 2 of 5 — Legal Agent.
    Uses gpt-4o (large model) — needs legal reasoning depth.
    Reads intake_data from the case as context.
    Returns complete legal assessment stored as legal_data.
    """
    track         = case.get("track", "monetary_civil")
    intake_data   = case.get("intake_data", {})
    system_prompt = TRACK_PROMPTS.get(track, MONETARY_CIVIL_PROMPT)

    # Build enriched context from intake output
    intake_summary = _build_intake_summary(intake_data, track)

    # State-specific context
    state      = case.get("claimant_state", "India")
    extra_ctx  = _get_state_context(state, track, case)

    user_message = f"""
Analyze this legal dispute:

DISPUTE TEXT:
{case['dispute_text']}

PARTIES:
- Claimant: {case['claimant_name']} | {case['claimant_city']}, {case['claimant_state']}
- Respondent: {case['respondent_name']} ({case.get('respondent_type', 'individual')})
  Company: {case.get('respondent_company_name', 'N/A')}
- Claim amount: {case.get('claim_amount', 'Not stated')} {case.get('currency', 'INR')}
- Incident date: {case.get('incident_date', 'Not specified')}
- Track: {track}

INTAKE AGENT ANALYSIS:
{intake_summary}

STATE-SPECIFIC CONTEXT:
{extra_ctx}

Provide complete legal assessment for this case.
"""

    try:
        result = openai_service.call_json(
            system_prompt=system_prompt,
            user_message=user_message,
            use_large_model=True,   # gpt-4o — legal reasoning needs depth
            temperature=0.2,
            max_tokens=3000,
        )

        # Validate and add computed fields
        result = _post_process(result, case, track, intake_data)

        logger.info(
            f"Legal Agent complete | track={track} | "
            f"standing={result.get('legal_standing')} | "
            f"forum={result.get('forum')}"
        )
        return result

    except Exception as e:
        logger.error(f"Legal Agent failed: {e}")
        return _fallback_legal_output(case, track)


# ── Helpers ───────────────────────────────────────────────────

def _build_intake_summary(intake_data: dict, track: str) -> str:
    if not intake_data:
        return "Intake analysis not available."

    lines = [
        f"- Dispute category: {intake_data.get('dispute_category', 'N/A')}",
        f"- Severity: {intake_data.get('severity', 'N/A')}",
        f"- Evidence strength score: {intake_data.get('evidence_strength_score', 'N/A')}/100",
        f"- Is time-barred: {intake_data.get('is_time_barred', 'Unknown')}",
        f"- Respondent is company: {intake_data.get('respondent_is_company', False)}",
        f"- Key facts: {'; '.join(intake_data.get('key_facts', [])[:3])}",
        f"- Claimant strengths: {'; '.join(intake_data.get('claimant_strengths', [])[:2])}",
        f"- Claimant weaknesses: {'; '.join(intake_data.get('claimant_weaknesses', [])[:2])}",
    ]

    # Track-specific additions
    if track == "employment":
        lines += [
            f"- Employment duration: {intake_data.get('employment_duration', 'N/A')}",
            f"- Last drawn salary: {intake_data.get('last_drawn_salary', 'N/A')}",
            f"- Dues components: {intake_data.get('dues_components', [])}",
            f"- Is POSH case: {intake_data.get('is_posh_case', False)}",
        ]
    elif track == "consumer":
        lines += [
            f"- Company name: {intake_data.get('company_name', 'N/A')}",
            f"- Transaction reference: {intake_data.get('transaction_reference', 'N/A')}",
            f"- Deficiency type: {intake_data.get('deficiency_type', 'N/A')}",
        ]
    elif track == "criminal":
        lines += [
            f"- Immediate danger: {intake_data.get('immediate_danger', False)}",
            f"- Criminal elements: {intake_data.get('criminal_elements', [])}",
            f"- FIR advisable: {intake_data.get('fir_advisable', True)}",
        ]

    return "\n".join(lines)


def _get_state_context(state: str, track: str, case: dict) -> str:
    lines = [f"- State: {state}"]

    if track == "monetary_civil":
        dispute_cat = case.get("routing", {}).get("dispute_category", "")
        if "rent" in dispute_cat or "deposit" in dispute_cat:
            act = get_rent_control_act(state)
            lines.append(f"- Applicable rent control act: {act}")

    if track == "consumer":
        claim_amount = case.get("claim_amount")
        tier = get_consumer_forum_tier(claim_amount)
        lines.append(f"- Consumer forum tier: {tier}")

    dispute_category = case.get("routing", {}).get("dispute_category", "other")
    limitation = get_limitation_period(dispute_category)
    lines.append(f"- Standard limitation period for this dispute type: {limitation} years")

    incident_date = case.get("incident_date")
    if incident_date:
        try:
            from datetime import datetime
            incident = datetime.fromisoformat(incident_date.replace("Z", "+00:00"))
            now = datetime.now(incident.tzinfo)
            years_elapsed = (now - incident).days / 365.25
            lines.append(
                f"- Years since incident: {years_elapsed:.1f} years "
                f"({'WITHIN' if years_elapsed < limitation else 'OUTSIDE'} limitation)"
            )
        except Exception:
            pass

    return "\n".join(lines)


def _post_process(result: dict, case: dict, track: str, intake_data: dict) -> dict:
    """Add computed fields and ensure required fields exist."""

    # Ensure applicable_laws is a list
    if not isinstance(result.get("applicable_laws"), list):
        result["applicable_laws"] = []

    # Ensure precedent_cases is a list
    if not isinstance(result.get("precedent_cases"), list):
        result["precedent_cases"] = []

    # Employment — calculate total statutory dues if not already done
    if track == "employment":
        entitlements = result.get("statutory_entitlements", {})
        if entitlements and "total_statutory_dues" not in result:
            total = 0
            for key, val in entitlements.items():
                if isinstance(val, dict) and "amount" in val:
                    amount = val["amount"]
                    if isinstance(amount, (int, float)):
                        total += amount
            result["total_statutory_dues"] = total

    # Consumer — set forum tier
    if track == "consumer" and "consumer_forum_tier" not in result:
        result["consumer_forum_tier"] = get_consumer_forum_tier(
            case.get("claim_amount")
        )

    # Add track marker
    result["track"] = track

    return result


def _fallback_legal_output(case: dict, track: str) -> dict:
    """Safe fallback so pipeline continues even if legal agent fails."""
    return {
        "track":                   track,
        "applicable_laws":         [],
        "legal_standing":          "MODERATE",
        "legal_standing_reason":   "Legal analysis unavailable — manual review recommended",
        "jurisdiction_state":      case.get("claimant_state", "India"),
        "forum":                   "civil_court",
        "forum_name":              "District Civil Court",
        "limitation_period_years": 3,
        "is_within_limitation":    True,
        "limitation_notes":        "Could not determine — seek legal advice",
        "claimant_rights":         ["Right to file a civil suit", "Right to legal representation"],
        "respondent_defenses":     ["To be determined"],
        "key_legal_issues":        ["To be determined"],
        "precedent_cases":         [],
        "legal_notice_required":   True,
        "legal_notice_notice_period_days": 15,
        "relief_available":        ["To be determined"],
        "filing_steps":            ["Consult a lawyer"],
        "recommended_immediate_actions": ["Preserve all evidence"],
        "error":                   "Legal agent failed — fallback output",
    }