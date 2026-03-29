import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

SENDGRID_API_URL = "https://api.sendgrid.com/v3/mail/send"
SENDGRID_TIMEOUT_SECONDS = 30


class EmailService:
    def __init__(self):
        self.api_key = settings.SENDGRID_API_KEY.strip()
        self.sender = settings.SENDGRID_FROM_EMAIL.strip()

    def is_configured(self) -> bool:
        return bool(self.api_key and self.sender)

    def send(self, to_email: str, subject: str, html_body: str) -> bool:
        if not self.is_configured():
            logger.error(
                "Email failed | provider=sendgrid | reason=missing_configuration"
            )
            return False

        payload = {
            "personalizations": [{"to": [{"email": to_email}]}],
            "from": {"email": self.sender},
            "subject": subject,
            "content": [{"type": "text/html", "value": html_body}],
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            with httpx.Client(timeout=SENDGRID_TIMEOUT_SECONDS) as client:
                response = client.post(
                    SENDGRID_API_URL,
                    headers=headers,
                    json=payload,
                )

            if response.status_code in (200, 201, 202):
                logger.info(
                    f"Email sent | provider=sendgrid | to={to_email} | subject={subject}"
                )
                return True

            logger.error(
                "Email failed | provider=sendgrid | "
                f"to={to_email} | status={response.status_code} | body={response.text[:500]}"
            )
            return False
        except Exception as e:
            logger.error(
                f"Email failed | provider=sendgrid | to={to_email} | error={e}"
            )
            return False

    def send_otp(self, to_email: str, otp: str, display_name: str = "") -> bool:
        name = display_name or to_email
        html = f"""
        <div style="font-family:Arial,sans-serif;max-width:480px;margin:0 auto;
                    background:#0F2A4A;padding:32px;border-radius:8px;">
            <h2 style="color:#06B6D4;margin-bottom:4px;">LegalAI Resolver</h2>
            <p style="color:#93C5FD;font-size:12px;margin-top:0;">
                AI-Powered Pre-Litigation Dispute Resolution
            </p>
            <p style="color:#E2E8F0;font-size:14px;">Hi {name},</p>
            <p style="color:#E2E8F0;font-size:14px;">Your login code is:</p>
            <div style="background:#1E293B;border-radius:8px;padding:24px;
                        text-align:center;margin:20px 0;">
                <span style="font-size:36px;font-weight:bold;color:#06B6D4;
                             letter-spacing:12px;">{otp}</span>
            </div>
            <p style="color:#94A3B8;font-size:12px;">
                This code expires in <b>10 minutes</b>.
                Do not share it with anyone.
            </p>
            <hr style="border-color:#1E293B;margin:20px 0;">
            <p style="color:#475569;font-size:11px;">
                If you did not request this code, ignore this email.
            </p>
        </div>
        """
        return self.send(to_email, "Your LegalAI Login Code", html)

    def send_case_invite(
        self,
        to_email: str,
        respondent_name: str,
        claimant_name: str,
        case_id: str,
        claim_amount,
        dispute_summary: str,
    ) -> bool:
        portal_url = f"{settings.BASE_URL}/respond/{case_id}"
        amount_str = (
            f"Rs. {claim_amount:,.0f}" if claim_amount else "Non-monetary dispute"
        )
        short_id = case_id[:8].upper()
        short_summary = (
            dispute_summary[:300] + "..."
            if len(dispute_summary) > 300 else dispute_summary
        )

        html = f"""
        <div style="font-family:Arial,sans-serif;max-width:520px;margin:0 auto;
                    background:#0F2A4A;padding:32px;border-radius:8px;">
            <h2 style="color:#06B6D4;margin-bottom:4px;">LegalAI Resolver</h2>
            <div style="background:#DC2626;border-radius:6px;padding:12px 16px;
                        margin:16px 0;">
                <p style="color:#fff;font-weight:bold;margin:0;font-size:14px;">
                    [Action Required] Legal Dispute Notice - Case #{short_id}
                </p>
            </div>
            <p style="color:#E2E8F0;font-size:14px;">Dear {respondent_name},</p>
            <p style="color:#E2E8F0;font-size:14px;">
                {claimant_name} has filed a formal dispute against you through
                LegalAI Resolver. You must respond within <b>7 days</b>.
            </p>
            <table style="width:100%;border-collapse:collapse;margin:16px 0;">
                <tr>
                    <td style="color:#94A3B8;padding:8px 0;font-size:13px;
                               border-bottom:1px solid #1E293B;">Claimant</td>
                    <td style="color:#E2E8F0;padding:8px 0;font-size:13px;
                               border-bottom:1px solid #1E293B;">{claimant_name}</td>
                </tr>
                <tr>
                    <td style="color:#94A3B8;padding:8px 0;font-size:13px;
                               border-bottom:1px solid #1E293B;">Claim Amount</td>
                    <td style="color:#06B6D4;padding:8px 0;font-size:13px;
                               font-weight:bold;border-bottom:1px solid #1E293B;">
                        {amount_str}
                    </td>
                </tr>
                <tr>
                    <td style="color:#94A3B8;padding:8px 0;font-size:13px;">
                        Case Reference
                    </td>
                    <td style="color:#E2E8F0;padding:8px 0;font-size:13px;">
                        {short_id}
                    </td>
                </tr>
            </table>
            <p style="color:#E2E8F0;font-size:13px;background:#1E293B;
                      padding:12px;border-radius:6px;line-height:1.5;">
                {short_summary}
            </p>
            <a href="{portal_url}"
               style="display:block;background:#06B6D4;color:#0F2A4A;
                      text-align:center;padding:14px;border-radius:6px;
                      font-weight:bold;text-decoration:none;
                      margin-top:20px;font-size:15px;">
                View Case &amp; Respond
            </a>
            <p style="color:#475569;font-size:11px;margin-top:20px;line-height:1.5;">
                Non-participation after 7 days results in automatic escalation
                and generation of a court-ready case file noting your
                non-response as evidence of bad faith.
            </p>
        </div>
        """
        return self.send(
            to_email,
            f"[Action Required] Legal Dispute Case #{short_id}",
            html,
        )

    def send_proposal(
        self,
        to_email: str,
        party_name: str,
        case_id: str,
        round_num: int,
        proposed_amount: float,
        reasoning: str,
        portal_url: str,
    ) -> bool:
        short_id = case_id[:8].upper()
        short_reason = reasoning[:400] + "..." if len(reasoning) > 400 else reasoning
        html = f"""
        <div style="font-family:Arial,sans-serif;max-width:520px;margin:0 auto;
                    background:#0F2A4A;padding:32px;border-radius:8px;">
            <h2 style="color:#06B6D4;">LegalAI Resolver</h2>
            <p style="color:#E2E8F0;font-size:14px;">Dear {party_name},</p>
            <p style="color:#E2E8F0;font-size:14px;">
                The AI Mediator has reviewed Round {round_num} offers from
                both parties and issued a settlement proposal.
            </p>
            <div style="background:#1E293B;border-radius:8px;padding:20px;
                        text-align:center;margin:16px 0;">
                <p style="color:#94A3B8;font-size:11px;margin:0 0 4px 0;
                           letter-spacing:2px;">PROPOSED SETTLEMENT</p>
                <p style="color:#06B6D4;font-size:30px;font-weight:bold;margin:0;">
                    Rs. {proposed_amount:,.0f}
                </p>
            </div>
            <div style="background:#1E3A6E;border-radius:6px;padding:14px;margin:16px 0;">
                <p style="color:#93C5FD;font-size:11px;margin:0 0 6px 0;
                           font-weight:bold;">AI MEDIATOR REASONING</p>
                <p style="color:#E2E8F0;font-size:13px;margin:0;
                           line-height:1.5;">{short_reason}</p>
            </div>
            <a href="{portal_url}"
               style="display:block;background:#06B6D4;color:#0F2A4A;
                      text-align:center;padding:14px;border-radius:6px;
                      font-weight:bold;text-decoration:none;font-size:15px;">
                View &amp; Decide - Accept or Reject
            </a>
            <p style="color:#475569;font-size:11px;margin-top:16px;">
                You have 48 hours to respond. Failure to respond will be
                treated as rejection.
            </p>
        </div>
        """
        return self.send(
            to_email,
            f"[Round {round_num}] AI Settlement Proposal - Case #{short_id}",
            html,
        )

    def send_settlement_confirmation(
        self,
        to_email: str,
        party_name: str,
        case_id: str,
        settled_amount: float,
        download_url: str,
    ) -> bool:
        short_id = case_id[:8].upper()
        html = f"""
        <div style="font-family:Arial,sans-serif;max-width:520px;margin:0 auto;
                    background:#0F2A4A;padding:32px;border-radius:8px;">
            <h2 style="color:#16A34A;">Settlement Confirmed</h2>
            <p style="color:#E2E8F0;font-size:14px;">Dear {party_name},</p>
            <p style="color:#E2E8F0;font-size:14px;">
                Both parties have accepted the settlement proposal.
                Your dispute has been resolved.
            </p>
            <div style="background:#166534;border-radius:8px;padding:20px;
                        text-align:center;margin:16px 0;">
                <p style="color:#86EFAC;font-size:11px;margin:0 0 4px 0;
                           letter-spacing:2px;">AGREED SETTLEMENT</p>
                <p style="color:#fff;font-size:30px;font-weight:bold;margin:0;">
                    Rs. {settled_amount:,.0f}
                </p>
            </div>
            <p style="color:#E2E8F0;font-size:13px;">
                Please download your Settlement Agreement below.
            </p>
            <a href="{download_url}"
               style="display:block;background:#16A34A;color:#fff;
                      text-align:center;padding:14px;border-radius:6px;
                      font-weight:bold;text-decoration:none;font-size:15px;">
                Download Settlement Agreement
            </a>
            <p style="color:#475569;font-size:11px;margin-top:16px;">
                Case Reference: {short_id} | LegalAI Resolver
            </p>
        </div>
        """
        return self.send(
            to_email,
            f"Settlement Confirmed - Case #{short_id}",
            html,
        )

    def send_escalation_notice(
        self,
        to_email: str,
        party_name: str,
        case_id: str,
        download_url: str,
    ) -> bool:
        short_id = case_id[:8].upper()
        html = f"""
        <div style="font-family:Arial,sans-serif;max-width:520px;margin:0 auto;
                    background:#0F2A4A;padding:32px;border-radius:8px;">
            <h2 style="color:#DC2626;">Mediation Concluded</h2>
            <p style="color:#E2E8F0;font-size:14px;">Dear {party_name},</p>
            <p style="color:#E2E8F0;font-size:14px;">
                The AI mediation process has concluded without reaching a
                settlement. A court-ready case file has been prepared.
            </p>
            <a href="{download_url}"
               style="display:block;background:#DC2626;color:#fff;
                      text-align:center;padding:14px;border-radius:6px;
                      font-weight:bold;text-decoration:none;font-size:15px;">
                Download Court File
            </a>
            <p style="color:#475569;font-size:11px;margin-top:16px;">
                Case Reference: {short_id} | LegalAI Resolver
            </p>
        </div>
        """
        return self.send(
            to_email,
            f"Mediation Concluded - Court File Ready - Case #{short_id}",
            html,
        )

    def send_next_round_invite(
        self,
        to_email: str,
        party_name: str,
        case_id: str,
        round_num: int,
        portal_url: str,
    ) -> bool:
        short_id = case_id[:8].upper()
        html = f"""
        <div style="font-family:Arial,sans-serif;max-width:520px;margin:0 auto;
                    background:#0F2A4A;padding:32px;border-radius:8px;">
            <h2 style="color:#D97706;">Round {round_num} - Submit Updated Offer</h2>
            <p style="color:#E2E8F0;font-size:14px;">Dear {party_name},</p>
            <p style="color:#E2E8F0;font-size:14px;">
                Round {round_num} is now open. Please submit your updated offer.
            </p>
            <a href="{portal_url}"
               style="display:block;background:#D97706;color:#fff;
                      text-align:center;padding:14px;border-radius:6px;
                      font-weight:bold;text-decoration:none;font-size:15px;">
                Submit Round {round_num} Offer
            </a>
            <p style="color:#475569;font-size:11px;margin-top:16px;">
                Round {round_num} of 3. After 3 rounds without settlement,
                the case escalates automatically.
            </p>
        </div>
        """
        return self.send(
            to_email,
            f"[Round {round_num}] Submit Updated Offer - Case #{short_id}",
            html,
        )

    def send_respondent_offer_notification(
        self,
        to_email: str,
        claimant_name: str,
        case_id: str,
        round_num: int,
    ) -> bool:
        short_id = case_id[:8].upper()
        html = f"""
        <div style="font-family:Arial,sans-serif;max-width:520px;margin:0 auto;
                    background:#0F2A4A;padding:32px;border-radius:8px;">
            <h2 style="color:#06B6D4;">LegalAI Resolver</h2>
            <p style="color:#E2E8F0;font-size:14px;">Dear {claimant_name},</p>
            <p style="color:#E2E8F0;font-size:14px;">
                The respondent has submitted their Round {round_num} offer
                for Case #{short_id}. Please login and submit your offer.
            </p>
            <a href="{settings.BASE_URL}"
               style="display:block;background:#06B6D4;color:#0F2A4A;
                      text-align:center;padding:14px;border-radius:6px;
                      font-weight:bold;text-decoration:none;font-size:15px;">
                Login and Submit Offer
            </a>
        </div>
        """
        return self.send(
            to_email,
            f"[Round {round_num}] Respondent Submitted Offer - Case #{short_id}",
            html,
        )


email_service = EmailService()
