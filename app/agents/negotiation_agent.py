import logging
import re
from app.services.openai_service import openai_service

logger = logging.getLogger(__name__)


def _coerce_currency_amount(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = (value.replace("Rs.", "").replace("Rs", "").replace("₹", "")
                   .replace(",", "").strip())
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def _extract_amount_from_reasoning(reasoning: str) -> float | None:
    if not reasoning:
        return None
    matches = re.findall(r"(?:Rs\.?|₹)\s*([0-9][0-9,]*)", reasoning, flags=re.IGNORECASE)
    amounts = []
    for m in matches:
        try:
            amounts.append(float(m.replace(",", "")))
        except ValueError:
            continue
    return max(amounts) if amounts else None


# ══════════════════════════════════════════════════════════════
# MONETARY NEGOTIATION PROMPT
# ══════════════════════════════════════════════════════════════

MONETARY_NEGOTIATION_PROMPT = """
You are an experienced AI Mediator specializing in Indian civil dispute resolution.
Your goal is to bring both parties to a fair, legally grounded settlement.

You have been given the ZOPA (Zone of Possible Agreement) and must propose an amount WITHIN it.
The ZOPA represents the realistic settlement range calculated from legal standing and evidence.
NEVER reveal the ZOPA to the parties. Use it as your internal compass.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PROPOSAL AMOUNT CALCULATION — MANDATORY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Your proposed_amount MUST be calculated as follows:

Step 1: Start at zopa_optimal (provided in MEDIATOR CONTEXT).
Step 2: Adjust based on round number:
  Round 1: zopa_optimal (anchoring to the realistic fair point)
  Round 2: If both parties moved closer → stay at zopa_optimal
           If claimant moved down significantly → adjust toward claimant's direction by 5–10%
           If respondent moved up significantly → adjust toward respondent's direction by 5–10%
           If neither moved → apply round 2 pressure: warn but stay at zopa_optimal
  Round 3 (FINAL): zopa_optimal — do NOT move further. State this is the final proposal.

Step 3: Check bounds:
  proposed_amount must be ≥ zopa_min at ALL times
  proposed_amount must be ≤ zopa_max at ALL times

Step 4: Output the proposed_amount as a plain integer or float in INR. No string. No "Rs." prefix.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
REASONING QUALITY RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The "reasoning" field is shown to BOTH parties. Write it to maximize acceptance:
- Be balanced — acknowledge what each party is getting right
- Ground every point in Indian law (cite the applicable act/section)
- Compare settlement vs. court: "Going to court would cost approximately Rs. X and take Y months"
- For Round 3: be explicit — "This is the final mediation proposal. After this, the claimant will proceed to [forum_name]."

NEVER mention:
- The word "ZOPA" or "Zone of Possible Agreement"
- Internal win probability percentages
- The words "fallback" or "optimal"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ROUND POSTURE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Round 1: Collaborative. Introduce the legal framework. Propose the fair midpoint.
Round 2: Analytical. Acknowledge movement. Apply targeted pressure to the unreasonable party.
Round 3: Urgent. "Last chance." State court consequences explicitly. Final proposal only.

Respond ONLY in valid JSON. No text outside JSON.
{
  "proposed_amount": number (INR integer or float — this is MANDATORY and must be within ZOPA bounds),
  "reasoning": "3–5 sentence paragraph shown to both parties. Legally grounded. Balanced. Compelling.",
  "reasoning_breakdown": {
    "amount_logic": "Why this specific amount was proposed — which legal principle supports it",
    "evidence_weight": "How the evidence quality shifted the proposal from pure midpoint",
    "court_comparison": "Rs. X court cost + Y months vs. settling today",
    "claimant_risk": "Specific risk for the claimant if they reject this proposal",
    "respondent_risk": "Specific risk for the respondent if they reject this proposal"
  },
  "live_reasoning_log": [
    "Step 1: Reviewed ZOPA — optimal is Rs. X",
    "Step 2: Round N adjustment — [explain any shift]",
    "Step 3: Gap between parties is Rs. Y — [convergent/divergent assessment]",
    "Step 4: Final proposed amount = Rs. Z — within ZOPA bounds confirmed"
  ],
  "claimant_pressure": "Internal note: what pressure applies to claimant this round",
  "respondent_pressure": "Internal note: what pressure applies to respondent this round",
  "round_assessment": "convergent|divergent|reasonable|final_push",
  "settlement_likelihood": "LOW|MEDIUM|HIGH",
  "mediator_notes": "Internal: trajectory observation and recommended next step"
}
"""


# ══════════════════════════════════════════════════════════════
# NON-MONETARY NEGOTIATION PROMPT
# ══════════════════════════════════════════════════════════════

NON_MONETARY_NEGOTIATION_PROMPT = """
You are an experienced AI Mediator for non-monetary disputes.
There is no money amount. Resolution = specific, time-bound, verifiable actions by the respondent.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PROPOSAL CONSTRUCTION RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Every proposed action MUST have:
  1. "action" — exactly what must be done (specific, not vague)
  2. "deadline_days" — integer number of days from agreement date
  3. "verification" — how compliance is confirmed (photo, email confirmation, third-party check)
  4. "penalty_if_breached" — consequence if not complied (Rs. X per day, or specific legal step)

GOOD: "Remove the defamatory post from Instagram account @[handle] within 48 hours and send screenshot confirmation to claimant's email."
BAD: "Remove the post."

Round 1: Propose the full set of claimant's reasonable demands.
Round 2: Prioritize must-haves (drop nice-to-haves if gap remains).
Round 3: Minimum viable resolution — the single core demand with strict deadline.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
REASONING RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The "reasoning" field is shown to BOTH parties:
- Explain why the proposed actions are fair and proportionate
- Reference relevant Indian law (IPC section, Noise Pollution Rules, IT Act, etc.)
- Note what legal remedy the claimant would pursue if this mediation fails
- For Round 3: "This is the final proposal. Non-compliance will result in [specific legal step]."

Respond ONLY in valid JSON. No text outside JSON.
{
  "proposed_actions": [
    {
      "action": "Specific action — exactly what must be done",
      "deadline_days": 7,
      "verification": "How compliance is verified",
      "penalty_if_breached": "Legal/financial consequence"
    }
  ],
  "reasoning": "3–4 sentence paragraph shown to both parties. References applicable Indian law.",
  "live_reasoning_log": [
    "Step 1: Reviewed claimant demands and respondent commitments",
    "Step 2: Identified overlap and core unresolved issues",
    "Step 3: Proposed actions based on legal entitlement and practical enforceability"
  ],
  "claimant_pressure": "Internal: what pressure applies to claimant",
  "respondent_pressure": "Internal: what pressure applies to respondent",
  "round_assessment": "convergent|divergent|reasonable|final_push",
  "settlement_likelihood": "LOW|MEDIUM|HIGH",
  "mediator_notes": "Internal: trajectory and recommended next step if not settled"
}
"""


# ══════════════════════════════════════════════════════════════
# EMPLOYMENT NEGOTIATION PROMPT
# ══════════════════════════════════════════════════════════════

EMPLOYMENT_NEGOTIATION_PROMPT = """
You are an experienced AI Mediator for employment disputes.
Employment settlements have TWO mandatory components: monetary dues AND non-monetary items.
Both must be resolved simultaneously. A settlement is incomplete without both.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MONETARY PROPOSAL CALCULATION — MANDATORY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The statutory_dues_floor is the ABSOLUTE MINIMUM — never propose below it.
This is required by law (Payment of Gratuity Act 1972, Payment of Wages Act 1936).

Step 1: proposed_amount starts at zopa_optimal (provided in MEDIATOR CONTEXT).
Step 2: Ensure proposed_amount ≥ statutory_dues_floor at ALL times.
Step 3: Apply round adjustments (same as monetary track):
  Round 1: zopa_optimal
  Round 2: Adjust based on movement, but floor must hold
  Round 3: Final — zopa_optimal, state consequences
Step 4: Output proposed_amount as INR number.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
NON-MONETARY COMPONENT — ALWAYS INCLUDE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Always propose ALL three unless already agreed:
1. Experience letter: On company letterhead, covering exact employment period [dates], designation, responsibilities. Due within 7 days.
2. Relieving letter: Stating employee separated on [date] and has no dues outstanding. Due within 7 days.
3. PF transfer: Employer to initiate EPFO transfer to employee's new PF account within 30 days. Provide UAN reference.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
REASONING RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Shown to both parties:
- Cite Payment of Wages Act, Gratuity Act, Industrial Disputes Act with specific sections
- Explain that statutory dues are non-negotiable minimums under Indian law
- Compare with Labour Court timelines (18–36 months) and costs
- For non-monetary items: explain career/business impact — these have real value

NEVER mention ZOPA. NEVER go below the statutory floor.

Respond ONLY in valid JSON. No text outside JSON.
{
  "proposed_amount": number (INR — MUST be ≥ statutory_dues_floor),
  "proposed_non_monetary": [
    {
      "item": "experience_letter",
      "deadline_days": 7,
      "specification": "On company letterhead, covering [start date] to [end date], designation [X], signed by HR authorized signatory"
    },
    {
      "item": "relieving_letter",
      "deadline_days": 7,
      "specification": "Stating separation date and no dues outstanding from employee"
    },
    {
      "item": "pf_transfer",
      "deadline_days": 30,
      "specification": "Employer to initiate EPFO Form 13 transfer and provide UAN acknowledgement"
    }
  ],
  "reasoning": "3–5 sentence paragraph shown to both parties. Cites employment statutes. Balanced.",
  "reasoning_breakdown": {
    "amount_logic": "Why this amount — which statutory entitlements compose it",
    "evidence_weight": "How documentation quality affects the proposal",
    "court_comparison": "Labour Court timeline and cost vs. settling today",
    "claimant_risk": "Specific risk for claimant in rejecting — delay in financial recovery and documents",
    "respondent_risk": "Specific risk for employer — Labour Court order + EPFO interest + penalties"
  },
  "live_reasoning_log": [
    "Step 1: Statutory floor = Rs. X (notice pay + gratuity if eligible + PF)",
    "Step 2: ZOPA optimal = Rs. Y (floor × 1.15 for wrongful termination premium)",
    "Step 3: Round N adjustment — [movement analysis]",
    "Step 4: Proposed = Rs. Z — confirmed ≥ statutory floor"
  ],
  "claimant_pressure": "Internal: pressure point for claimant this round",
  "respondent_pressure": "Internal: pressure point for employer this round",
  "round_assessment": "convergent|divergent|reasonable|final_push",
  "settlement_likelihood": "LOW|MEDIUM|HIGH",
  "mediator_notes": "Internal: trajectory and next step"
}
"""


TRACK_PROMPTS = {
    "monetary_civil": MONETARY_NEGOTIATION_PROMPT,
    "non_monetary":   NON_MONETARY_NEGOTIATION_PROMPT,
    "employment":     EMPLOYMENT_NEGOTIATION_PROMPT,
    "consumer":       MONETARY_NEGOTIATION_PROMPT,  # consumer uses monetary logic
}


# ══════════════════════════════════════════════════════════════
# MAIN FUNCTION
# ══════════════════════════════════════════════════════════════

async def run_negotiation_agent(
    case: dict,
    negotiation: dict,
    round_number: int,
    claimant_offer,
    respondent_offer,
) -> dict:
    """
    Agent 5 of 5 — Negotiation Agent.
    Uses gpt-4o (large model) — nuanced mediation requires deep reasoning.

    Parameters:
        case           Full case document from Cosmos
        negotiation    Full negotiation document (all rounds)
        round_number   Current round (1, 2, or 3)
        claimant_offer   Rs. amount (monetary) or list of demands (non-monetary)
        respondent_offer Rs. amount (monetary) or list of commitments (non-monetary)

    Returns dict with proposed_amount/actions, reasoning, and internal notes.
    """
    track         = case.get("track", "monetary_civil")
    system_prompt = TRACK_PROMPTS.get(track, MONETARY_NEGOTIATION_PROMPT)

    analytics   = case.get("analytics_data", {})
    legal       = case.get("legal_data", {})
    intake      = case.get("intake_data", {})
    history     = negotiation.get("rounds", [])
    past_rounds = [r for r in history if r.get("round_number", 0) < round_number]

    zopa_context    = _build_zopa_context(analytics, track, legal)
    legal_context   = _build_legal_context(legal, intake)
    history_context = _build_history_context(past_rounds, track)
    offer_context   = _build_offer_context(claimant_offer, respondent_offer, track, case, analytics)

    user_message = f"""
You are mediating Round {round_number} of {case.get('max_rounds', 3)} in this dispute.

CASE OVERVIEW:
- Dispute: {case['dispute_text'][:500]}
- Track: {track}
- Claimant: {case['claimant_name']} | {case['claimant_state']}
- Respondent: {case['respondent_name']}
- Original claim: Rs. {case.get('claim_amount', 0):,.0f}

{zopa_context}

{legal_context}

{history_context}

{offer_context}

MANDATORY INSTRUCTIONS FOR THIS ROUND:
1. Calculate proposed_amount using the step-by-step formula in your instructions.
2. proposed_amount MUST be within ZOPA bounds (zopa_min ≤ proposed ≤ zopa_max).
3. For employment: proposed_amount MUST be ≥ statutory_dues_floor.
4. Show your calculation in live_reasoning_log.
5. The reasoning paragraph must be compelling, legally grounded, and balanced.
6. Round {round_number} posture: {'COLLABORATIVE — introduce fair legal framework' if round_number == 1 else 'ANALYTICAL — acknowledge movement, apply targeted pressure' if round_number == 2 else 'URGENT — this is the FINAL round. State consequences explicitly. No further rounds after this.'}
7. Return ONLY valid JSON.
"""

    try:
        result = openai_service.call_json(
            system_prompt=system_prompt,
            user_message=user_message,
            use_large_model=True,
            temperature=0.2,
            max_tokens=2500,
        )

        result = _post_process(result, case, analytics, round_number, track, legal)

        logger.info(
            f"Negotiation Agent | round={round_number} | track={track} | "
            f"proposed={result.get('proposed_amount')} | "
            f"zopa_min={analytics.get('zopa_min')} | "
            f"zopa_max={analytics.get('zopa_max')} | "
            f"likelihood={result.get('settlement_likelihood')}"
        )
        return result

    except Exception as e:
        logger.error(f"Negotiation Agent failed | round={round_number} | error={e}")
        return _fallback_proposal(case, round_number, claimant_offer, respondent_offer, analytics)


# ══════════════════════════════════════════════════════════════
# CONTEXT BUILDERS
# ══════════════════════════════════════════════════════════════

def _build_zopa_context(analytics: dict, track: str, legal: dict) -> str:
    if track == "non_monetary":
        leverage = analytics.get("leverage_score", "N/A")
        compliance = analytics.get("compliance_probability", "N/A")
        return (
            f"MEDIATOR CONTEXT (CONFIDENTIAL):\n"
            f"- Leverage score: {leverage}/100\n"
            f"- Compliance probability if legal notice sent: {compliance}%\n"
            f"- Negotiation approach: {analytics.get('negotiation_approach', 'collaborative')}\n"
            f"- Recommended path if mediation fails: {analytics.get('recommended_path', 'civil_injunction')}"
        )

    zopa_min     = analytics.get("zopa_min", 0) or 0
    zopa_max     = analytics.get("zopa_max", 0) or 0
    zopa_optimal = analytics.get("zopa_optimal", 0) or 0
    court_cost   = analytics.get("court_cost_estimate", 75000) or 75000
    time_months  = analytics.get("time_to_resolution_months", 30) or 30
    recovery_pct = analytics.get("payment_recovery_probability", 60) or 60
    win_prob     = analytics.get("win_probability", 50) or 50

    lines = [
        "MEDIATOR CONTEXT (CONFIDENTIAL — never reveal these figures to parties):",
        f"- Realistic settlement floor (zopa_min):   Rs. {zopa_min:,.0f}",
        f"- Realistic settlement ceiling (zopa_max): Rs. {zopa_max:,.0f}",
        f"- Fair settlement target (zopa_optimal):   Rs. {zopa_optimal:,.0f}",
        f"- Your proposed_amount MUST be between Rs. {zopa_min:,.0f} and Rs. {zopa_max:,.0f}",
        f"- Court cost if escalated:                 Rs. {court_cost:,.0f}",
        f"- Expected time to judgment:               {time_months} months",
        f"- Win probability if goes to court:        {win_prob}%",
        f"- Payment recovery probability:            {recovery_pct}%",
    ]

    if track == "employment":
        statutory_floor = legal.get("total_statutory_dues", 0) or 0
        lines.append(f"- Statutory dues floor (ABSOLUTE MINIMUM): Rs. {statutory_floor:,.0f}")
        lines.append(f"- proposed_amount must NEVER go below Rs. {statutory_floor:,.0f}")

    return "\n".join(lines)


def _build_legal_context(legal: dict, intake: dict) -> str:
    laws = legal.get("applicable_laws", [])
    primary_laws = [l for l in laws if l.get("strength") == "PRIMARY"]
    law_str = "; ".join(
        f"{l.get('act')} S.{l.get('section')}" for l in primary_laws[:3]
    ) or "Applicable Indian statutes"

    return (
        f"LEGAL CONTEXT:\n"
        f"- Legal standing: {legal.get('legal_standing', 'MODERATE')}\n"
        f"- Primary statutes: {law_str}\n"
        f"- Evidence strength: {intake.get('evidence_strength_score', 50)}/100\n"
        f"- Claimant strengths: {intake.get('claimant_strengths', [])[:3]}\n"
        f"- Claimant weaknesses: {intake.get('claimant_weaknesses', [])[:2]}\n"
        f"- Missing evidence: {intake.get('missing_proof_checklist', [])[:2]}\n"
        f"- Respondent likely defenses: {legal.get('respondent_defenses', [])[:3]}\n"
        f"- Forum if escalated: {legal.get('forum_name', 'appropriate court')}\n"
        f"- Relief available: {legal.get('relief_available', [])[:3]}"
    )


def _build_history_context(past_rounds: list, track: str) -> str:
    if not past_rounds:
        return "NEGOTIATION HISTORY: This is Round 1 — no prior rounds."

    lines = ["NEGOTIATION HISTORY:"]
    for r in sorted(past_rounds, key=lambda x: x.get("round_number", 0)):
        rn = r.get("round_number", "?")
        cl = r.get("claimant") or {}
        re_ = r.get("respondent") or {}
        if track == "non_monetary":
            lines.append(
                f"Round {rn}: Claimant demanded {cl.get('actions', [])} | "
                f"Respondent offered {re_.get('actions', [])} | "
                f"AI proposed {r.get('ai_proposed_actions', [])} | "
                f"Outcome: Claimant {cl.get('decision', '?')}, Respondent {re_.get('decision', '?')}"
            )
        else:
            cl_amt = cl.get("amount") or r.get("claimant_offer") or 0
            re_amt = re_.get("amount") or r.get("respondent_offer") or 0
            ai_amt = r.get("ai_proposed_amount") or 0
            lines.append(
                f"Round {rn}: "
                f"Claimant Rs. {cl_amt:,.0f} | "
                f"Respondent Rs. {re_amt:,.0f} | "
                f"AI proposed Rs. {ai_amt:,.0f} | "
                f"Claimant: {cl.get('decision', '?')} | Respondent: {re_.get('decision', '?')}"
            )

    # Movement analysis (2+ rounds)
    monetary_rounds = [r for r in past_rounds if track != "non_monetary"]
    if len(monetary_rounds) >= 2:
        prev = sorted(monetary_rounds, key=lambda x: x.get("round_number", 0))[-2]
        curr = sorted(monetary_rounds, key=lambda x: x.get("round_number", 0))[-1]

        prev_cl = (prev.get("claimant") or {}).get("amount") or prev.get("claimant_offer") or 0
        curr_cl = (curr.get("claimant") or {}).get("amount") or curr.get("claimant_offer") or 0
        prev_re = (prev.get("respondent") or {}).get("amount") or prev.get("respondent_offer") or 0
        curr_re = (curr.get("respondent") or {}).get("amount") or curr.get("respondent_offer") or 0

        cl_moved = curr_cl - prev_cl  # negative = claimant came down
        re_moved = curr_re - prev_re  # positive = respondent went up

        lines.append(
            f"\nMOVEMENT ANALYSIS:"
            f"\n- Claimant moved: Rs. {abs(cl_moved):,.0f} {'DOWN ✓' if cl_moved < 0 else 'UP (unusual)'}"
            f"\n- Respondent moved: Rs. {abs(re_moved):,.0f} {'UP ✓' if re_moved > 0 else 'DOWN (unusual)'}"
        )
        current_gap = abs(curr_cl - curr_re)
        lines.append(f"- Current gap: Rs. {current_gap:,.0f}")
        if abs(cl_moved) < 1000 and abs(re_moved) < 1000:
            lines.append("- ⚠ STALEMATE: Neither party is moving — maximum pressure needed this round.")
        elif current_gap < 10000:
            lines.append("- ✓ CLOSE: Gap is small — settlement is very achievable this round.")

    return "\n".join(lines)


def _build_offer_context(
    claimant_offer,
    respondent_offer,
    track: str,
    case: dict,
    analytics: dict,
) -> str:
    if track == "non_monetary":
        return (
            f"CURRENT ROUND OFFERS:\n"
            f"- Claimant demands: {claimant_offer}\n"
            f"- Respondent commitments: {respondent_offer}\n"
            f"- Identify the gap and propose the minimum actions to close it."
        )

    cl = float(claimant_offer or 0)
    rs = float(respondent_offer or 0)
    claim = case.get("claim_amount") or 0
    zopa_optimal = analytics.get("zopa_optimal") or 0
    gap = abs(cl - rs)
    gap_pct = (gap / claim * 100) if claim > 0 else 0

    # Distance from ZOPA optimal
    cl_vs_optimal = cl - zopa_optimal
    rs_vs_optimal = zopa_optimal - rs

    assessment = (
        "LARGE GAP — significant pressure needed"
        if gap_pct > 40
        else "MODERATE GAP — encourage convergence"
        if gap_pct > 15
        else "SMALL GAP — settlement very close, final push should work"
    )

    return (
        f"CURRENT ROUND OFFERS:\n"
        f"- Claimant is asking: Rs. {cl:,.0f}"
        f"  (Rs. {abs(cl_vs_optimal):,.0f} {'above' if cl_vs_optimal > 0 else 'below'} fair value)\n"
        f"- Respondent is offering: Rs. {rs:,.0f}"
        f"  (Rs. {abs(rs_vs_optimal):,.0f} {'below' if rs_vs_optimal > 0 else 'above'} fair value)\n"
        f"- Gap: Rs. {gap:,.0f} ({gap_pct:.0f}% of original claim)\n"
        f"- Gap assessment: {assessment}\n"
        f"- Your proposed_amount should aim to split this gap fairly, anchored at Rs. {zopa_optimal:,.0f}"
    )


# ══════════════════════════════════════════════════════════════
# POST-PROCESSING + FALLBACK
# ══════════════════════════════════════════════════════════════

def _post_process(
    result: dict,
    case: dict,
    analytics: dict,
    round_number: int,
    track: str,
    legal: dict,
) -> dict:
    """Validate and clamp negotiation output — ensure ZOPA compliance."""

    if track != "non_monetary":
        proposed = _coerce_currency_amount(result.get("proposed_amount"))
        zopa_min  = analytics.get("zopa_min") or 0
        zopa_max  = analytics.get("zopa_max") or case.get("claim_amount") or 0
        zopa_opt  = analytics.get("zopa_optimal") or ((zopa_min + zopa_max) / 2)

        # Try to extract from reasoning if LLM returned null
        if proposed is None or proposed <= 0:
            reasoning_amount = _extract_amount_from_reasoning(result.get("reasoning", ""))
            proposed = reasoning_amount if reasoning_amount and reasoning_amount > 0 else zopa_opt

        # Employment: never below statutory floor
        if track == "employment":
            statutory_floor = legal.get("total_statutory_dues", 0) or 0
            if statutory_floor > 0:
                proposed = max(proposed, statutory_floor)
                zopa_min = max(zopa_min, statutory_floor)

        # Clamp within ZOPA bounds
        if zopa_min > 0 and zopa_max > 0:
            proposed = max(zopa_min, min(zopa_max, proposed))
        elif case.get("claim_amount", 0) > 0:
            proposed = max(0, min(case["claim_amount"] * 1.15, proposed))

        result["proposed_amount"] = round(proposed, 2)

    # Ensure reasoning is substantial
    if not result.get("reasoning") or len(result.get("reasoning", "")) < 80:
        result["reasoning"] = _fallback_reasoning(case, round_number, result.get("proposed_amount", 0), analytics)

    # Ensure reasoning_breakdown exists for monetary tracks
    if track != "non_monetary":
        result.setdefault("reasoning_breakdown", {
            "amount_logic": f"The proposal of Rs. {result.get('proposed_amount', 0):,.0f} reflects the evidence strength and legal position of both parties.",
            "evidence_weight": "Documentation quality was factored into the settlement range.",
            "court_comparison": f"Litigation could cost Rs. {analytics.get('court_cost_estimate', 75000):,.0f} and take {analytics.get('time_to_resolution_months', 30)} months.",
            "claimant_risk": "Rejecting may delay recovery and incur litigation costs.",
            "respondent_risk": "Rejecting may increase exposure through court proceedings and interest accrual.",
        })

    # Ensure live_reasoning_log exists
    result.setdefault("live_reasoning_log", [
        f"Round {round_number}: Reviewed ZOPA and parties' current positions.",
        f"ZOPA optimal: Rs. {analytics.get('zopa_optimal', 0):,.0f}",
        f"Proposed amount: Rs. {result.get('proposed_amount', 0):,.0f} — within ZOPA bounds.",
    ])

    result["round_number"] = round_number
    result["track"]        = track

    return result


def _fallback_reasoning(case: dict, round_number: int, amount: float, analytics: dict) -> str:
    court_cost = analytics.get("court_cost_estimate", 75000) or 75000
    time_months = analytics.get("time_to_resolution_months", 30) or 30
    return (
        f"Based on the facts, applicable Indian law, and both parties' positions in Round {round_number}, "
        f"the AI Mediator proposes a settlement of Rs. {amount:,.0f}. "
        f"This reflects a balanced assessment of the legal merits and evidence strength. "
        f"Pursuing this matter through court would cost approximately Rs. {court_cost:,.0f} "
        f"and take {time_months} months — settlement today avoids that outcome entirely."
    )


def _fallback_proposal(
    case: dict,
    round_number: int,
    claimant_offer,
    respondent_offer,
    analytics: dict,
) -> dict:
    """Safe fallback if negotiation agent fails."""
    track = case.get("track", "monetary_civil")

    if track == "non_monetary":
        return {
            "proposed_actions": [],
            "reasoning": "AI mediation is temporarily unavailable. Please retry.",
            "round_assessment": "divergent",
            "settlement_likelihood": "LOW",
            "round_number": round_number,
            "track": track,
            "error": "Negotiation agent failed",
        }

    # Use ZOPA optimal as the fallback proposal — NOT simple midpoint
    zopa_opt = analytics.get("zopa_optimal")
    zopa_min = analytics.get("zopa_min", 0) or 0
    zopa_max = analytics.get("zopa_max") or case.get("claim_amount") or 0

    cl = float(claimant_offer or 0)
    rs = float(respondent_offer or 0)

    if zopa_opt and zopa_min <= zopa_opt <= zopa_max:
        proposed = round(zopa_opt, 2)
    elif zopa_min > 0:
        proposed = round((zopa_min + zopa_max) / 2, 2)
    else:
        proposed = round((cl + rs) / 2, 2) if (cl and rs) else round(cl or rs, 2)

    return {
        "proposed_amount":    proposed,
        "reasoning":          _fallback_reasoning(case, round_number, proposed, analytics),
        "reasoning_breakdown": {
            "amount_logic": "Fallback: ZOPA optimal used as the fair settlement point.",
            "evidence_weight": "Full evidence weighting unavailable in fallback mode.",
            "court_comparison": f"Court would cost Rs. {analytics.get('court_cost_estimate', 75000):,.0f} and take {analytics.get('time_to_resolution_months', 30)} months.",
            "claimant_risk": "Recovery delay and litigation costs if the dispute escalates.",
            "respondent_risk": "Increased exposure through court proceedings and interest.",
        },
        "live_reasoning_log": [
            "Negotiation agent fallback activated.",
            f"Used ZOPA optimal (Rs. {proposed:,.0f}) as fair settlement point.",
            "Parties should review and respond to this proposal.",
        ],
        "claimant_pressure":  "Consider this proposal carefully — it reflects the legal fair value.",
        "respondent_pressure": "Consider this proposal carefully — court proceedings would cost significantly more.",
        "round_assessment":   "reasonable",
        "settlement_likelihood": "MEDIUM",
        "round_number":       round_number,
        "track":              track,
        "error":              "Negotiation agent failed — ZOPA-based fallback applied",
    }
