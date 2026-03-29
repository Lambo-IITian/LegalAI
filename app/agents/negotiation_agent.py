import logging
from app.services.openai_service import openai_service

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════
# MONETARY NEGOTIATION PROMPT
# ══════════════════════════════════════════════════════════════

MONETARY_NEGOTIATION_PROMPT = """
You are a senior AI mediator specializing in Indian civil dispute resolution.
You have access to the ZOPA (Zone of Possible Agreement) but NEVER reveal it.

YOUR ROLE:
- Analyze both parties' offers and the gap between them
- Consider legal merits, precedents, and evidence strength
- Propose a fair settlement amount with clear reasoning
- Apply different pressure based on who is being unreasonable

PROPOSAL RULES:
- Round 1: Propose closer to ZOPA optimal. Tone is collaborative.
- Round 2: If gap narrowed — reward convergence, propose near optimal.
           If gap unchanged — apply pressure to the unreasonable party.
- Round 3: FINAL round. Tone is urgent. Be explicit that this is the last chance.
           Propose at ZOPA optimal. State exact court cost consequence.

REASONING MUST INCLUDE:
- Why this amount is fair (legal basis)
- What precedent supports it
- Cost/time comparison (settle now vs court)
- What each party gains by accepting

NEVER mention:
- The word "ZOPA"
- Internal scoring or probability numbers
- Which party has higher win probability

Respond ONLY in valid JSON:
{
  "proposed_amount": number,
  "reasoning": "paragraph shown to both parties — legally grounded, balanced",
  "claimant_pressure": "internal note — what pressure applies to claimant",
  "respondent_pressure": "internal note — what pressure applies to respondent",
  "round_assessment": "convergent|divergent|reasonable|final_push",
  "settlement_likelihood": "LOW|MEDIUM|HIGH",
  "mediator_notes": "internal — what the mediator observes about trajectory"
}
"""


# ══════════════════════════════════════════════════════════════
# NON-MONETARY NEGOTIATION PROMPT
# ══════════════════════════════════════════════════════════════

NON_MONETARY_NEGOTIATION_PROMPT = """
You are a senior AI mediator for non-monetary disputes.
There is no money amount. Resolution = specific agreed actions.

YOUR ROLE:
- Analyze claimant's demands and respondent's commitments
- Find the overlap and propose a merged, specific, time-bound action plan
- Each action must have: what, by when, verification method

ACTION PLAN RULES:
- Be specific: "Remove the social media post by [date]" not "remove post"
- Include a compliance mechanism: "Failure to comply triggers Rs. X penalty"
- Round 1: Full set of reasonable demands
- Round 2: Prioritize must-haves, drop nice-to-haves
- Round 3: Minimum viable resolution — core demand only

Respond ONLY in valid JSON:
{
  "proposed_actions": [
    {
      "action": "specific action description",
      "deadline_days": 7,
      "verification": "how compliance is verified",
      "penalty_if_breached": "Rs. 10000 or description"
    }
  ],
  "reasoning": "paragraph explaining why these actions are fair",
  "claimant_pressure": "internal note",
  "respondent_pressure": "internal note",
  "round_assessment": "convergent|divergent|reasonable|final_push",
  "settlement_likelihood": "LOW|MEDIUM|HIGH",
  "mediator_notes": "internal observation"
}
"""


# ══════════════════════════════════════════════════════════════
# EMPLOYMENT NEGOTIATION PROMPT
# ══════════════════════════════════════════════════════════════

EMPLOYMENT_NEGOTIATION_PROMPT = """
You are a senior AI mediator for employment disputes.
Employment settlements have TWO components: monetary dues + non-monetary items.
Both must be resolved simultaneously.

MONETARY COMPONENT:
- Floor = total statutory dues (never propose below this)
- Ceiling = statutory dues + 25% for wrongful termination damages
- Propose within this range based on evidence and round number

NON-MONETARY COMPONENT (always track separately):
- Experience letter (high importance — career-critical)
- Relieving letter (important)
- PF transfer initiation (statutory — must be included)
- Reference commitment (negotiate)

PROPOSAL FORMAT:
- State monetary amount clearly
- List each non-monetary item with specific deadline
- Both components must be agreed for settlement to be complete

Respond ONLY in valid JSON:
{
  "proposed_amount": number,
  "proposed_non_monetary": [
    {
      "item": "experience_letter",
      "deadline_days": 7,
      "specification": "On company letterhead, covering full employment period"
    }
  ],
  "reasoning": "paragraph shown to both parties",
  "claimant_pressure": "internal note",
  "respondent_pressure": "internal note",
  "round_assessment": "convergent|divergent|reasonable|final_push",
  "settlement_likelihood": "LOW|MEDIUM|HIGH",
  "mediator_notes": "internal observation"
}
"""


TRACK_PROMPTS = {
    "monetary_civil": MONETARY_NEGOTIATION_PROMPT,
    "non_monetary":   NON_MONETARY_NEGOTIATION_PROMPT,
    "employment":     EMPLOYMENT_NEGOTIATION_PROMPT,
    "consumer":       MONETARY_NEGOTIATION_PROMPT,   # same as monetary
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
    Uses gpt-4o (large model) — nuanced mediation needs depth.

    Parameters:
        case          Full case document from Cosmos
        negotiation   Full negotiation document (all rounds)
        round_number  Current round (1, 2, or 3)
        claimant_offer   Rs. amount or list of demands
        respondent_offer Rs. amount or list of commitments

    Returns dict with proposed_amount/actions, reasoning, internal notes.
    """
    track         = case.get("track", "monetary_civil")
    system_prompt = TRACK_PROMPTS.get(track, MONETARY_NEGOTIATION_PROMPT)

    # Build context
    analytics   = case.get("analytics_data", {})
    legal       = case.get("legal_data", {})
    intake      = case.get("intake_data", {})
    history     = negotiation.get("rounds", [])
    past_rounds = [r for r in history if r["round_number"] < round_number]

    zopa_context = _build_zopa_context(analytics, track)
    legal_context = _build_legal_context(legal, intake)
    history_context = _build_history_context(past_rounds, track)
    offer_context = _build_offer_context(
        claimant_offer, respondent_offer, track, case
    )

    user_message = f"""
CASE OVERVIEW:
- Dispute: {case['dispute_text'][:400]}
- Track: {track}
- Claimant: {case['claimant_name']} | {case['claimant_state']}
- Respondent: {case['respondent_name']}
- Original claim: Rs. {case.get('claim_amount', 0):,.0f}
- Current round: {round_number} of {case.get('max_rounds', 3)}

{zopa_context}

{legal_context}

{history_context}

{offer_context}

Generate a fair settlement proposal for Round {round_number}.
"""

    try:
        result = openai_service.call_json(
            system_prompt=system_prompt,
            user_message=user_message,
            use_large_model=True,   # gpt-4o — mediation needs reasoning depth
            temperature=0.3,
            max_tokens=2000,
        )

        result = _post_process(result, case, analytics, round_number, track)

        logger.info(
            f"Negotiation Agent | round={round_number} | track={track} | "
            f"proposed={result.get('proposed_amount')} | "
            f"likelihood={result.get('settlement_likelihood')}"
        )
        return result

    except Exception as e:
        logger.error(f"Negotiation Agent failed | round={round_number} | error={e}")
        return _fallback_proposal(case, round_number, claimant_offer, respondent_offer)


# ══════════════════════════════════════════════════════════════
# CONTEXT BUILDERS
# ══════════════════════════════════════════════════════════════

def _build_zopa_context(analytics: dict, track: str) -> str:
    if track == "non_monetary":
        return "MEDIATOR CONTEXT: Non-monetary dispute — focus on action compliance."

    zopa_min     = analytics.get("zopa_min", 0)
    zopa_max     = analytics.get("zopa_max", 0)
    zopa_optimal = analytics.get("zopa_optimal", 0)
    court_cost   = analytics.get("court_cost_estimate", 75000)
    time_months  = analytics.get("time_to_resolution_months", 30)
    recovery_pct = analytics.get("payment_recovery_probability", 60)

    return f"""MEDIATOR CONTEXT (CONFIDENTIAL — never reveal to parties):
- Realistic settlement range: Rs. {zopa_min:,.0f} to Rs. {zopa_max:,.0f}
- Optimal settlement point: Rs. {zopa_optimal:,.0f}
- Court cost if escalated: Rs. {court_cost:,.0f}
- Time to judgment: {time_months} months
- Payment recovery probability if court wins: {recovery_pct}%
- Win probability: {analytics.get('win_probability', 50)}%"""


def _build_legal_context(legal: dict, intake: dict) -> str:
    laws = legal.get("applicable_laws", [])
    law_str = "; ".join(
        f"{l.get('act')} S.{l.get('section')}"
        for l in laws[:4]
    )
    return f"""LEGAL CONTEXT:
- Legal standing: {legal.get('legal_standing', 'MODERATE')}
- Primary statutes: {law_str or 'To be determined'}
- Evidence strength: {intake.get('evidence_strength_score', 50)}/100
- Respondent likely defenses: {legal.get('respondent_defenses', [])}
- Relief available: {legal.get('relief_available', [])}"""


def _build_history_context(past_rounds: list, track: str) -> str:
    if not past_rounds:
        return "NEGOTIATION HISTORY: Round 1 — no prior rounds."

    lines = ["NEGOTIATION HISTORY:"]
    for r in past_rounds:
        rn = r["round_number"]
        claimant = r.get("claimant") or {}
        respondent = r.get("respondent") or {}
        if track == "non_monetary":
            lines.append(
                f"Round {rn}: "
                f"Claimant demanded {claimant.get('actions', r.get('claimant_demands', []))} | "
                f"Respondent offered {respondent.get('actions', r.get('respondent_commitments', []))} | "
                f"AI proposed {r.get('ai_proposed_actions', [])} | "
                f"Claimant: {claimant.get('decision', r.get('claimant_decision'))} | "
                f"Respondent: {respondent.get('decision', r.get('respondent_decision'))}"
            )
        else:
            lines.append(
                f"Round {rn}: "
                f"Claimant offered Rs. {(claimant.get('amount', r.get('claimant_offer')) or 0):,.0f} | "
                f"Respondent offered Rs. {(respondent.get('amount', r.get('respondent_offer')) or 0):,.0f} | "
                f"AI proposed Rs. {r.get('ai_proposed_amount', 0):,.0f} | "
                f"Claimant: {claimant.get('decision', r.get('claimant_decision'))} | "
                f"Respondent: {respondent.get('decision', r.get('respondent_decision'))}"
            )

    # Trajectory analysis
    if len(past_rounds) >= 2 and track != "non_monetary":
        prev = past_rounds[-2]
        curr = past_rounds[-1]
        claimant_moved = abs(
            ((curr.get("claimant") or {}).get("amount", curr.get("claimant_offer")) or 0) -
            ((prev.get("claimant") or {}).get("amount", prev.get("claimant_offer")) or 0)
        )
        respondent_moved = abs(
            ((curr.get("respondent") or {}).get("amount", curr.get("respondent_offer")) or 0) -
            ((prev.get("respondent") or {}).get("amount", prev.get("respondent_offer")) or 0)
        )
        lines.append(
            f"TRAJECTORY: Claimant moved Rs. {claimant_moved:,.0f} | "
            f"Respondent moved Rs. {respondent_moved:,.0f}"
        )
        if claimant_moved < 1000 and respondent_moved < 1000:
            lines.append("ALERT: Both parties showing low flexibility — final push needed.")

    return "\n".join(lines)


def _build_offer_context(
    claimant_offer,
    respondent_offer,
    track: str,
    case: dict,
) -> str:
    if track == "non_monetary":
        return f"""CURRENT ROUND OFFERS:
Claimant demands: {claimant_offer}
Respondent commitments: {respondent_offer}"""

    cl = claimant_offer or 0
    rs = respondent_offer or 0
    gap = abs(cl - rs)
    claim = case.get("claim_amount") or 0

    gap_pct = (gap / claim * 100) if claim > 0 else 0

    return f"""CURRENT ROUND OFFERS:
- Claimant offer: Rs. {cl:,.0f}
- Respondent offer: Rs. {rs:,.0f}
- Gap: Rs. {gap:,.0f} ({gap_pct:.0f}% of original claim)
- Gap assessment: {'LARGE (>40%)' if gap_pct > 40 else 'MODERATE (20-40%)' if gap_pct > 20 else 'SMALL (<20%) — settlement close'}"""


# ══════════════════════════════════════════════════════════════
# POST-PROCESSING + FALLBACK
# ══════════════════════════════════════════════════════════════

def _post_process(
    result: dict,
    case: dict,
    analytics: dict,
    round_number: int,
    track: str,
) -> dict:
    """Validate and enrich negotiation output."""

    if track != "non_monetary":
        # Ensure proposed_amount exists and is reasonable
        proposed = result.get("proposed_amount")
        zopa_min = analytics.get("zopa_min", 0)
        zopa_max = analytics.get("zopa_max", case.get("claim_amount", 0))

        if not proposed or proposed <= 0:
            result["proposed_amount"] = analytics.get(
                "zopa_optimal",
                (zopa_min + zopa_max) / 2,
            )

        # Clamp to reasonable range (0 to 130% of claim)
        claim = case.get("claim_amount") or 0
        if claim > 0:
            result["proposed_amount"] = max(
                0,
                min(claim * 1.3, result["proposed_amount"])
            )
        result["proposed_amount"] = round(result["proposed_amount"], 2)

    # Ensure reasoning exists and is substantial
    if not result.get("reasoning") or len(result.get("reasoning", "")) < 50:
        result["reasoning"] = _fallback_reasoning(
            case, round_number, result.get("proposed_amount", 0)
        )

    # Add round metadata
    result["round_number"] = round_number
    result["track"]        = track

    return result


def _fallback_reasoning(case: dict, round_number: int, amount: float) -> str:
    return (
        f"Based on the facts presented, applicable Indian law, and the "
        f"offers submitted by both parties in Round {round_number}, the AI "
        f"Mediator proposes a settlement of Rs. {amount:,.0f}. This amount "
        f"reflects a balanced consideration of the claimant's legal rights "
        f"and the respondent's position. Accepting this proposal avoids "
        f"the time and cost of litigation."
    )


def _fallback_proposal(
    case: dict,
    round_number: int,
    claimant_offer,
    respondent_offer,
) -> dict:
    """Safe fallback if negotiation agent fails."""
    track = case.get("track", "monetary_civil")

    if track == "non_monetary":
        return {
            "proposed_actions": [],
            "reasoning":        "AI mediation temporarily unavailable. Please try again.",
            "round_assessment": "divergent",
            "settlement_likelihood": "LOW",
            "error":            "Negotiation agent failed",
        }

    cl = claimant_offer or 0
    rs = respondent_offer or 0
    midpoint = (cl + rs) / 2 if (cl and rs) else (cl or rs)

    return {
        "proposed_amount":    round(midpoint, 2),
        "reasoning":          _fallback_reasoning(case, round_number, midpoint),
        "claimant_pressure":  "Review carefully",
        "respondent_pressure": "Review carefully",
        "round_assessment":   "reasonable",
        "settlement_likelihood": "MEDIUM",
        "error":              "Negotiation agent failed — midpoint fallback applied",
    }
