import logging
from datetime import datetime, timezone
from app.services.openai_service import openai_service
from app.core.legal_reference import (
    get_consumer_forum_tier,
    get_rent_control_act,
    get_limitation_period,
)

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════
# SYSTEM PROMPTS — one per track
# ══════════════════════════════════════════════════════════════

MONETARY_CIVIL_PROMPT = """
You are a senior Indian advocate with 20+ years of civil litigation experience.
Analyze the dispute and produce a complete, accurate legal assessment.

PRIMARY STATUTES FOR MONETARY CIVIL DISPUTES:
- Indian Contract Act 1872: S.73 (compensation for breach), S.74 (liquidated damages)
- Transfer of Property Act 1882: S.105-111 (lease/tenancy), S.108 (landlord/tenant duties)
- Specific Relief Act 1963: S.36-42 (injunctions), S.10-25 (specific performance)
- Code of Civil Procedure 1908: Order 37 (summary suits for money recovery)
- Consumer Protection Act 2019: S.2(7) (consumer definition), S.35 (complaints)
- Negotiable Instruments Act 1881: S.138 (cheque dishonour — criminal), S.141 (company liability)
- Payment of Wages Act 1936: S.3 (responsibility for payment), S.15 (claims authority)
- State Rent Control Acts: apply state-specific act based on jurisdiction_state
- Interest: 18% per annum is standard for commercial transactions; 12% for consumer disputes
- IPC S.420: Cheating — applicable when fraudulent intent is present alongside civil breach

PRECEDENT GUIDANCE — cite only real, verifiable Indian court decisions:
- Refer to Supreme Court and relevant High Court judgments
- Include citation format: (Year) Vol SCC PageNo or AIR (Year) SC PageNo
- If uncertain of exact citation, describe the legal principle established rather than fabricate

LEGAL STANDING ASSESSMENT CRITERIA:
- VERY_STRONG: Written contract + full payment proof + clear breach + within limitation
- STRONG: Clear documentation, minor gaps, within limitation, established legal basis
- MODERATE: Some documentation, significant gaps or limitation concerns
- WEAK: Mostly verbal/circumstantial, weak documentation, potential limitation bar

Respond ONLY in valid JSON. No text, markdown, or explanation outside JSON.
{
  "applicable_laws": [
    {
      "act": "Full Act name",
      "section": "Section number(s)",
      "relevance": "Exactly how this section applies to the specific facts of this case",
      "strength": "PRIMARY|SECONDARY|SUPPORTING"
    }
  ],
  "legal_standing": "WEAK|MODERATE|STRONG|VERY_STRONG",
  "legal_standing_reason": "Specific explanation referencing the actual facts and evidence",
  "jurisdiction_state": "State name",
  "forum": "civil_court|consumer_forum|lok_adalat|high_court|debt_recovery_tribunal",
  "forum_name": "Specific court e.g. District Civil Court, Delhi or Consumer Disputes Redressal Commission, Bengaluru",
  "limitation_period_years": 3,
  "is_within_limitation": true,
  "limitation_notes": "Specific explanation of limitation calculation for this case",
  "claimant_rights": [
    "Right to recover principal amount of Rs. X under Contract Act S.73",
    "Right to claim 18% per annum interest from date of default"
  ],
  "respondent_defenses": [
    "Specific defense 1 the respondent is likely to raise",
    "Specific defense 2"
  ],
  "key_legal_issues": [
    "Issue 1: Whether [specific factual question] gives rise to liability under [specific section]",
    "Issue 2"
  ],
  "precedent_cases": [
    {
      "case_name": "Party A vs Party B",
      "court": "Supreme Court of India / High Court name",
      "year": 2019,
      "citation": "Citation if verifiable, otherwise null",
      "principle": "The legal principle this case established that applies here"
    }
  ],
  "legal_notice_required": true,
  "legal_notice_notice_period_days": 15,
  "relief_available": [
    "Recovery of principal: Rs. [amount]",
    "Interest at 18% per annum from [date]",
    "Cost of litigation"
  ],
  "interest_rate_applicable": 18,
  "court_fee_estimate": 5000,
  "filing_steps": [
    "Step 1: Send legal notice with 15-day compliance period",
    "Step 2: If no response, file plaint under Order 37 CPC for summary decree",
    "Step 3: Attach all documentary evidence to plaint"
  ],
  "recommended_immediate_actions": [
    "Preserve all WhatsApp/email communications with timestamps",
    "Obtain bank statements proving payment"
  ]
}
"""


EMPLOYMENT_PROMPT = """
You are a senior Indian labour law advocate with deep expertise in employment disputes.
Analyze the dispute and produce a precise legal assessment with exact statutory calculations.

PRIMARY STATUTES FOR EMPLOYMENT DISPUTES:
- Industrial Disputes Act 1947: S.2(s) (workman definition), S.25F (retrenchment conditions),
  S.25G (retrenchment procedure), S.25H (re-employment priority), S.10 (reference to tribunal)
- Payment of Wages Act 1936: S.3 (liability to pay), S.15 (application to authority for unpaid wages)
- Payment of Gratuity Act 1972: S.4 (payment of gratuity — 5 years minimum), 
  S.7 (determination of gratuity), S.8 (recovery of gratuity)
- Employees Provident Fund & MP Act 1952: S.6 (contributions), S.14B (damages for default)
- Shops and Establishments Act (state-specific): notice period requirements
- POSH Act 2013: S.4 (Internal Complaints Committee), S.11 (inquiry procedure),
  S.13 (action taken report), S.16 (confidentiality)
- Factories Act 1948: applicable if manufacturing/factory context

MANDATORY STATUTORY CALCULATIONS (calculate if figures are available):
If last_drawn_salary and notice_period_months are known:
  → notice_period_pay = last_drawn_salary × notice_period_months

If last_drawn_salary and employment_duration_years are known:
  → gratuity = (last_drawn_salary × 15 × completed_years) ÷ 26
  → gratuity is ZERO if service < 5 years — state this explicitly

If employer PF default is alleged:
  → employer_pf_due = basic_salary × 0.12 × months_defaulted

LEGAL STANDING CRITERIA FOR EMPLOYMENT:
- VERY_STRONG: Written offer letter + payslips + termination letter + clear statutory violation
- STRONG: Offer letter or payslips, some documentation, clear claim
- MODERATE: Partial documentation, some gaps
- WEAK: Only verbal accounts, no written proof, limitation concerns

Respond ONLY in valid JSON. No text outside JSON.
{
  "applicable_laws": [
    {
      "act": "Full Act name",
      "section": "Section number(s)",
      "relevance": "Exactly how this section applies",
      "strength": "PRIMARY|SECONDARY|SUPPORTING"
    }
  ],
  "legal_standing": "WEAK|MODERATE|STRONG|VERY_STRONG",
  "legal_standing_reason": "Specific explanation referencing facts and evidence",
  "jurisdiction_state": "State",
  "forum": "labour_court|high_court|posh_committee|civil_court|pf_commissioner",
  "forum_name": "Specific court/committee name e.g. Labour Court, Chennai",
  "labour_court_address": "address or null",
  "limitation_period_years": 3,
  "is_within_limitation": true,
  "limitation_notes": "explanation",
  "claimant_rights": [
    "Right to X months notice period pay under Shops & Establishments Act",
    "Right to gratuity under Payment of Gratuity Act if service >= 5 years"
  ],
  "respondent_defenses": [
    "Respondent defense 1",
    "Respondent defense 2"
  ],
  "key_legal_issues": ["Issue 1", "Issue 2"],
  "precedent_cases": [
    {
      "case_name": "Name",
      "court": "Supreme Court / High Court",
      "year": 2020,
      "citation": "citation or null",
      "principle": "Legal principle established"
    }
  ],
  "legal_notice_required": true,
  "legal_notice_notice_period_days": 15,
  "statutory_entitlements": {
    "notice_period_pay": {
      "amount": 30000,
      "eligible": true,
      "basis": "1 month notice × Rs. 30,000 last drawn salary"
    },
    "gratuity": {
      "amount": 0,
      "eligible": false,
      "basis": "Service of 2 years 3 months is below the 5-year threshold under PGA 1972"
    },
    "pf_dues": {
      "amount": 0,
      "eligible": false,
      "basis": "No PF default alleged in this case"
    },
    "full_and_final_settlement": {
      "amount": 0,
      "eligible": true,
      "basis": "Any pending salary, reimbursements, or encashable leave"
    }
  },
  "total_statutory_dues": 30000,
  "posh_committee_route": false,
  "posh_notes": null,
  "relief_available": [
    "Recovery of Rs. X notice period pay",
    "Issuance of experience letter on company letterhead",
    "PF transfer to new employer PF account"
  ],
  "filing_steps": [
    "Step 1: Send legal notice to employer with 15-day deadline",
    "Step 2: If no response, file application under Payment of Wages Act S.15 before Payment of Wages Authority",
    "Step 3: For wrongful termination, file complaint under Industrial Disputes Act before Labour Court"
  ],
  "recommended_immediate_actions": [
    "Preserve all payslips, offer letter, termination email",
    "Download PF passbook from EPFO portal to verify employer contributions"
  ]
}
"""


CONSUMER_PROMPT = """
You are a senior Indian consumer law advocate specializing in Consumer Protection Act 2019.
Analyze the dispute and produce a complete legal assessment.

PRIMARY STATUTES:
- Consumer Protection Act 2019 (primary): S.2(7) (consumer), S.2(11) (deficiency),
  S.2(47) (unfair trade practice), S.35 (complaint), S.39 (reliefs), S.69 (limitation: 2 years)
- Consumer Protection (E-Commerce) Rules 2020: Rule 6 (seller duties), Rule 7 (liabilities)
- RERA Act 2016: S.31 (complaints), S.18 (compensation for delay), S.19 (allottee rights)
- Insurance Act 1938 + IRDAI Regulations: Policy repudiation grounds
- RBI Banking Ombudsman Scheme 2006/2021: Complaint procedure
- TRAI Regulations: Telecom dispute resolution
- Sale of Goods Act 1930: S.12 (implied condition as to quality), S.62 (exclusion of implied terms)

CONSUMER FORUM TIERS (mandatory — apply based on claim amount):
- District Commission:  claim ≤ Rs. 50,00,000 (50 lakh)
- State Commission:     claim Rs. 50 lakh to Rs. 2 crore
- National Commission:  claim > Rs. 2 crore

COMPENSATION STRUCTURE UNDER CPA 2019:
- Refund of amount paid (primary)
- Compensation for mental agony (Rs. 5,000–Rs. 50,000 for typical cases)
- Punitive damages in egregious/repeated deficiency cases
- Cost of litigation (typically Rs. 3,000–Rs. 10,000)
- Interest from date of complaint

LEGAL STANDING CRITERIA FOR CONSUMER:
- VERY_STRONG: Order proof + payment proof + written refusal + within 2 years
- STRONG: Order proof + payment proof, minor gap (e.g. no written refusal but tracked delivery failure)
- MODERATE: Some proof, significant gaps or approaching 2-year limit
- WEAK: Mostly verbal, no payment proof, approaching or past 2-year limit

Respond ONLY in valid JSON. No text outside JSON.
{
  "applicable_laws": [
    {
      "act": "Full Act name",
      "section": "Section number(s)",
      "relevance": "Exactly how this applies",
      "strength": "PRIMARY|SECONDARY|SUPPORTING"
    }
  ],
  "legal_standing": "WEAK|MODERATE|STRONG|VERY_STRONG",
  "legal_standing_reason": "Specific explanation",
  "jurisdiction_state": "State",
  "forum": "consumer_forum|banking_ombudsman|rera|insurance_ombudsman|telecom_ombudsman",
  "forum_name": "e.g. District Consumer Disputes Redressal Commission, Mumbai",
  "consumer_forum_tier": "district|state|national",
  "limitation_period_years": 2,
  "is_within_limitation": true,
  "limitation_notes": "2-year limitation under CPA 2019 S.69 — calculate from [specific date]",
  "claimant_rights": ["Right 1 with statutory basis", "Right 2"],
  "respondent_defenses": ["Defense 1", "Defense 2"],
  "key_legal_issues": ["Issue 1: Was there deficiency of service under CPA S.2(11)?", "Issue 2"],
  "precedent_cases": [
    {
      "case_name": "Name",
      "court": "NCDRC or State/District Commission",
      "year": 2021,
      "citation": "citation or null",
      "principle": "Legal principle established"
    }
  ],
  "legal_notice_required": true,
  "legal_notice_notice_period_days": 15,
  "relief_available": [
    "Full refund of Rs. X",
    "Compensation for mental agony (estimated Rs. Y under CPA S.39(1)(d))",
    "Cost of complaint: Rs. Z"
  ],
  "compensation_likely": 10000,
  "ombudsman_route": false,
  "ombudsman_name": null,
  "court_fee_estimate": 2000,
  "filing_steps": [
    "Step 1: Send demand email/letter to company's grievance officer with 15 days to respond",
    "Step 2: File complaint online at edaakhil.nic.in (District Commission)",
    "Step 3: Attach all evidence: order confirmation, payment receipt, communication screenshots"
  ],
  "recommended_immediate_actions": [
    "Screenshot and archive all communications immediately",
    "File consumer complaint on the company's official grievance portal and screenshot the acknowledgement"
  ]
}
"""


NON_MONETARY_PROMPT = """
You are a senior Indian civil and criminal lawyer handling non-monetary disputes.
There is no money claim. Resolution = specific behavioral actions by the respondent.
Analyze and provide the complete legal framework for obtaining those actions.

PRIMARY STATUTES FOR NON-MONETARY DISPUTES:
- Specific Relief Act 1963: S.36-42 (prohibitory/mandatory injunctions)
- Code of Civil Procedure 1908: Order 39 (temporary injunctions), Rule 1-2 (grounds)
- IPC S.268 (public nuisance), S.294 (obscene acts in public), S.441-443 (criminal trespass)
- IPC S.499-500 (defamation), S.503-506 (criminal intimidation/threats)
- IPC S.509 (word/gesture to insult modesty of woman)
- IT Act 2000: S.66A (online communication causing annoyance — read with Constitution),
  S.67 (obscene electronic content), S.72 (breach of confidentiality)
- Protection of Women from Domestic Violence Act 2005: S.12 (applications), S.18 (protection orders)
- Noise Pollution (Regulation and Control) Rules 2000: permissible decibel limits
- Apartment Owners Association laws (state-specific): for neighbour/housing society disputes

INJUNCTION CRITERIA (apply precisely):
- Mandatory injunction (compels action): "Do X" — e.g. remove the post, return the documents
- Prohibitory injunction (stops action): "Stop doing Y" — e.g. stop playing music after 10 PM
- Grounds: (a) prima facie case, (b) balance of convenience, (c) irreparable harm

Respond ONLY in valid JSON. No text outside JSON.
{
  "applicable_laws": [
    {
      "act": "Full Act name",
      "section": "Section number(s)",
      "relevance": "Exactly how this applies",
      "strength": "PRIMARY|SECONDARY|SUPPORTING"
    }
  ],
  "legal_standing": "WEAK|MODERATE|STRONG|VERY_STRONG",
  "legal_standing_reason": "Specific explanation",
  "jurisdiction_state": "State",
  "forum": "civil_court|magistrate_court|police|high_court|consumer_forum",
  "forum_name": "Specific court name",
  "limitation_period_years": 3,
  "is_within_limitation": true,
  "limitation_notes": "explanation",
  "claimant_rights": ["Right 1 with statutory basis", "Right 2"],
  "respondent_defenses": ["Defense 1", "Defense 2"],
  "key_legal_issues": ["Issue 1", "Issue 2"],
  "precedent_cases": [
    {
      "case_name": "Name",
      "court": "Court",
      "year": 2020,
      "citation": "citation or null",
      "principle": "Principle established"
    }
  ],
  "legal_notice_required": true,
  "legal_notice_notice_period_days": 15,
  "injunction_possible": true,
  "injunction_type": "mandatory|prohibitory|both|null",
  "injunction_grounds": "prima facie case exists because [specific reason]; balance of convenience favours claimant because [reason]; irreparable harm if not granted because [reason]",
  "relief_available": [
    "Mandatory injunction: Respondent to remove [specific content/item] within 48 hours",
    "Prohibitory injunction: Respondent restrained from [specific act]",
    "Written apology on [platform/in writing] within [timeframe]"
  ],
  "filing_steps": [
    "Step 1: Send cease-and-desist notice with 7-day deadline",
    "Step 2: File application for temporary injunction under Order 39 CPC if not complied"
  ],
  "recommended_immediate_actions": [
    "Screenshot/archive the offending content with timestamps immediately",
    "Gather witness statements if neighbors/colleagues can confirm the nuisance"
  ]
}
"""


CRIMINAL_PROMPT = """
You are a senior Indian criminal lawyer providing advisory on criminal matters.
THIS CASE INVOLVES CRIMINAL OFFENCES — mediation is NOT applicable.
Your role: guide the victim on safety, evidence preservation, FIR filing, and legal rights.

PRIMARY CRIMINAL STATUTES:
- IPC S.323 (voluntarily causing hurt), S.324 (hurt by dangerous weapons),
  S.325 (grievous hurt), S.326 (grievous hurt by dangerous weapons)
- IPC S.354 (assault/criminal force on woman), S.354A-D (sexual harassment, voyeurism, stalking)
- IPC S.376 (rape/sexual assault)
- IPC S.406 (criminal breach of trust), S.420 (cheating and dishonestly inducing delivery)
- IPC S.498A (cruelty by husband or relatives)
- IPC S.499-500 (defamation — criminal), S.503-506 (criminal intimidation)
- IPC S.509 (word/gesture to insult modesty)
- IT Act 2000: S.66C (identity theft), S.66D (cheating by personation), S.67 (obscene content)
- Protection of Women from Domestic Violence Act 2005 (PWDVA): S.12, S.18, S.19, S.20
- POCSO Act 2012: if victim is a minor (below 18)
- SC/ST (Prevention of Atrocities) Act 1989: if caste-based discrimination/violence

CLASSIFY OFFENCES:
- Cognizable offence (police can arrest without warrant): assault, rape, IPC 420 fraud, stalking
- Non-cognizable offence (police cannot arrest without magistrate order): minor defamation
- Bailable vs. non-bailable (based on First Schedule to CrPC)

Respond ONLY in valid JSON. No text outside JSON.
{
  "applicable_laws": [
    {
      "act": "Full Act name",
      "section": "Section number",
      "relevance": "Exactly how this applies to the specific facts",
      "strength": "PRIMARY|SECONDARY|SUPPORTING"
    }
  ],
  "legal_standing": "MODERATE|STRONG|VERY_STRONG",
  "legal_standing_reason": "explanation",
  "jurisdiction_state": "State",
  "forum": "police|magistrate_court|sessions_court|high_court|family_court",
  "forum_name": "Specific station or court",
  "ipc_sections": ["IPC 323", "IPC 506"],
  "bailable_offences": ["IPC 323"],
  "non_bailable_offences": ["IPC 376"],
  "cognizable_offences": ["IPC 323"],
  "non_cognizable_offences": [],
  "limitation_period_years": null,
  "is_within_limitation": true,
  "limitation_notes": "Serious cognizable offences under IPC have no limitation period. Complaint must be filed promptly for evidence preservation.",
  "claimant_rights": [
    "Right to file FIR under CrPC S.154 — police cannot refuse a cognizable offence FIR",
    "Right to free legal aid under Legal Services Authorities Act 1987",
    "Right to copy of FIR: CrPC S.154(2)"
  ],
  "key_legal_issues": [
    "Issue 1: Whether the offence is cognizable and FIR must be registered",
    "Issue 2: Whether evidence is sufficient for prosecution"
  ],
  "precedent_cases": [
    {
      "case_name": "Name",
      "court": "Supreme Court of India",
      "year": 2018,
      "citation": "citation or null",
      "principle": "Principle established — e.g. police cannot refuse FIR for cognizable offence"
    }
  ],
  "fir_recommended": true,
  "fir_station_type": "local_police|women_cell|cyber_cell|anti_corruption|district_crime_branch",
  "immediate_safety_steps": [
    "Step 1 if immediate danger",
    "Step 2 for evidence preservation"
  ],
  "support_resources": [
    "Police Emergency: 100",
    "NCW Helpline: 181",
    "Cyber Crime: cybercrime.gov.in / 1930",
    "Women Helpline: 1091"
  ],
  "mediation_possible": false,
  "filing_steps": [
    "Step 1: Visit local police station with written complaint",
    "Step 2: If police refuses FIR, send complaint to Superintendent of Police by registered post",
    "Step 3: If still refused, file private complaint before Judicial Magistrate under CrPC S.156(3)"
  ],
  "recommended_immediate_actions": [
    "Preserve ALL evidence immediately — screenshots, photos, medical records, witnesses",
    "File FIR as soon as safely possible — delay weakens case"
  ]
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

    intake_summary = _build_intake_summary(intake_data, track)
    state          = case.get("claimant_state", "India")
    extra_ctx      = _get_state_context(state, track, case)

    user_message = f"""
Analyze this legal dispute and produce a rigorous, fact-specific legal assessment.

DISPUTE TEXT:
{case['dispute_text']}

PARTIES:
- Claimant: {case['claimant_name']} | {case['claimant_city']}, {case['claimant_state']}
- Respondent: {case['respondent_name']} ({case.get('respondent_type', 'individual')})
  Company: {case.get('respondent_company_name', 'N/A')}
- Claim amount: Rs. {case.get('claim_amount', 'Not stated')} {case.get('currency', 'INR')}
- Incident date: {case.get('incident_date', 'Not specified')}
- Track: {track}

INTAKE AGENT FINDINGS (already extracted — build on these, do not repeat them, go deeper):
{intake_summary}

STATE-SPECIFIC LEGAL CONTEXT:
{extra_ctx}

INSTRUCTIONS:
1. Cite statutes with specific section numbers that directly apply to the FACTS of this case.
2. For respondent_defenses, think like the opposing lawyer — what are the strongest defenses they can raise?
3. For precedent_cases, cite only cases you are confident exist. If uncertain of citation, state the principle only.
4. For employment track: calculate all statutory entitlements with exact arithmetic shown in the "basis" field.
5. For consumer track: specify the exact consumer forum tier and relevant ombudsman route if applicable.
6. legal_standing must reflect evidence_strength_score and documentation quality, not just legal theory.
7. Return ONLY valid JSON.
"""

    try:
        result = openai_service.call_json(
            system_prompt=system_prompt,
            user_message=user_message,
            use_large_model=True,
            temperature=0.15,
            max_tokens=3000,
        )

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
        f"- Dispute type: {intake_data.get('dispute_type', 'N/A')}",
        f"- Dispute category: {intake_data.get('dispute_category', 'N/A')}",
        f"- Severity: {intake_data.get('severity', 'N/A')}",
        f"- Evidence strength score: {intake_data.get('evidence_strength_score', 'N/A')}/100",
        f"- Evidence available: {intake_data.get('evidence_available', [])}",
        f"- Missing proof: {intake_data.get('missing_proof_checklist', [])}",
        f"- Is time-barred: {intake_data.get('is_time_barred', False)}",
        f"- Limitation notes: {intake_data.get('limitation_notes', 'None')}",
        f"- Respondent is company: {intake_data.get('respondent_is_company', False)}",
        f"- Key facts: {intake_data.get('key_facts', [])}",
        f"- Claimant strengths: {intake_data.get('claimant_strengths', [])}",
        f"- Claimant weaknesses: {intake_data.get('claimant_weaknesses', [])}",
        f"- Key issues identified: {intake_data.get('key_issues', [])}",
        f"- Confirmed claim amount: Rs. {intake_data.get('confirmed_claim_amount', 'N/A')}",
    ]

    if track == "employment":
        lines += [
            f"- Employment duration: {intake_data.get('employment_duration', 'N/A')}",
            f"- Last drawn salary: Rs. {intake_data.get('last_drawn_salary', 'N/A')}",
            f"- Notice period months: {intake_data.get('notice_period_months', 'N/A')}",
            f"- Gratuity eligible: {intake_data.get('gratuity_eligible', False)}",
            f"- Calculated notice pay: Rs. {intake_data.get('calculated_notice_pay', 'N/A')}",
            f"- Calculated gratuity: Rs. {intake_data.get('calculated_gratuity', 'N/A')}",
            f"- Dues components: {intake_data.get('dues_components', [])}",
            f"- Is POSH case: {intake_data.get('is_posh_case', False)}",
        ]
    elif track == "consumer":
        lines += [
            f"- Company name: {intake_data.get('company_name', 'N/A')}",
            f"- Transaction reference: {intake_data.get('transaction_reference', 'N/A')}",
            f"- Deficiency type: {intake_data.get('deficiency_type', 'N/A')}",
            f"- Consumer forum tier: {intake_data.get('consumer_forum_tier', 'district')}",
        ]
    elif track == "criminal":
        lines += [
            f"- Immediate danger: {intake_data.get('immediate_danger', False)}",
            f"- Criminal sections likely: {intake_data.get('criminal_sections_likely', [])}",
            f"- FIR advisable: {intake_data.get('fir_advisable', True)}",
            f"- Recommended authority: {intake_data.get('recommended_authority', 'local_police')}",
        ]

    return "\n".join(lines)


def _get_state_context(state: str, track: str, case: dict) -> str:
    lines = [f"- Jurisdiction state: {state}"]

    if track == "monetary_civil":
        dispute_cat = case.get("intake_data", {}).get("dispute_category", "")
        if "deposit" in dispute_cat or "rent" in dispute_cat or "security" in dispute_cat:
            act = get_rent_control_act(state)
            lines.append(f"- Applicable rent control legislation: {act}")

    if track == "consumer":
        claim_amount = case.get("claim_amount")
        tier = get_consumer_forum_tier(claim_amount)
        lines.append(f"- Consumer forum tier based on claim amount: {tier}")

    dispute_category = case.get("intake_data", {}).get("dispute_category", "other")
    limitation = get_limitation_period(dispute_category)
    lines.append(f"- Standard limitation period for '{dispute_category}': {limitation} years")

    incident_date = case.get("incident_date")
    if incident_date:
        try:
            incident = datetime.fromisoformat(incident_date.replace("Z", "+00:00"))
            now = datetime.now(incident.tzinfo)
            years_elapsed = (now - incident).days / 365.25
            status = "WITHIN limitation" if years_elapsed < limitation else "POTENTIALLY OUTSIDE limitation — verify carefully"
            lines.append(
                f"- Years since incident: {years_elapsed:.1f} years ({status})"
            )
        except Exception:
            pass

    return "\n".join(lines)


def _post_process(result: dict, case: dict, track: str, intake_data: dict) -> dict:
    """Validate, compute, and enrich legal agent output."""

    if not isinstance(result.get("applicable_laws"), list):
        result["applicable_laws"] = []
    if not isinstance(result.get("precedent_cases"), list):
        result["precedent_cases"] = []
    if not isinstance(result.get("claimant_rights"), list):
        result["claimant_rights"] = []
    if not isinstance(result.get("respondent_defenses"), list):
        result["respondent_defenses"] = []
    if not isinstance(result.get("relief_available"), list):
        result["relief_available"] = []

    # Employment — calculate total statutory dues from entitlements
    if track == "employment":
        entitlements = result.get("statutory_entitlements", {})
        total = 0
        for key, val in entitlements.items():
            if isinstance(val, dict):
                amt = val.get("amount", 0)
                if isinstance(amt, (int, float)) and amt > 0:
                    total += amt
        result["total_statutory_dues"] = round(total, 2)

        # If intake calculated values exist and legal didn't recalculate, carry forward
        if total == 0:
            intake_notice = intake_data.get("calculated_notice_pay", 0) or 0
            intake_gratuity = intake_data.get("calculated_gratuity", 0) or 0
            fallback_total = (intake_notice or 0) + (intake_gratuity or 0)
            if fallback_total > 0:
                result["total_statutory_dues"] = fallback_total

    # Consumer — ensure forum tier is set
    if track == "consumer" and not result.get("consumer_forum_tier"):
        result["consumer_forum_tier"] = get_consumer_forum_tier(case.get("claim_amount"))

    result["track"] = track
    return result


def _fallback_legal_output(case: dict, track: str) -> dict:
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
        "claimant_rights":         ["Right to file civil suit", "Right to legal representation"],
        "respondent_defenses":     ["To be determined"],
        "key_legal_issues":        ["To be determined"],
        "precedent_cases":         [],
        "legal_notice_required":   True,
        "legal_notice_notice_period_days": 15,
        "relief_available":        ["To be determined"],
        "filing_steps":            ["Consult a licensed advocate"],
        "recommended_immediate_actions": ["Preserve all evidence immediately"],
        "total_statutory_dues":    0,
        "statutory_entitlements":  {},
        "error":                   "Legal agent failed — fallback output",
    }
