"""
Quick diagnostic - tests SendGrid email directly.
Run: python -m tests.test_email_diagnostic
"""
from dotenv import load_dotenv

load_dotenv(".env.local")

import httpx

from app.config import settings


def test_email():
    print("\n" + "=" * 60)
    print("SendGrid - Email Diagnostic")
    print("=" * 60)

    print("\n[CONFIG]")
    api_key = settings.SENDGRID_API_KEY
    sender = settings.SENDGRID_FROM_EMAIL
    print(f"  API key set:   {'yes' if api_key else 'no'}")
    print(f"  Sender email:  {sender}")

    if not api_key.startswith("SG."):
        print("  X SENDGRID_API_KEY is missing or invalid")
        return
    print("  OK API key format looks valid")

    if not sender or "@" not in sender:
        print(f"  X SENDGRID_FROM_EMAIL invalid: {sender!r}")
        return
    print("  OK Sender email format valid")

    to_email = "gunanimohit1221@gmail.com"
    print(f"\n[SENDING TEST EMAIL -> {to_email}]")

    payload = {
        "personalizations": [{"to": [{"email": to_email}]}],
        "from": {"email": sender},
        "subject": "LegalAI - SendGrid Diagnostic Test",
        "content": [
            {
                "type": "text/html",
                "value": "<p>Diagnostic test email from LegalAI Resolver via SendGrid.</p>",
            }
        ],
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        with httpx.Client(timeout=30) as client:
            response = client.post(
                "https://api.sendgrid.com/v3/mail/send",
                headers=headers,
                json=payload,
            )

        if response.status_code == 202:
            print("  OK Email accepted by SendGrid")
            print("  Check your inbox/spam folder.")
            print("=" * 60)
            return

        print(f"  X SendGrid returned {response.status_code}")
        print(f"  Body: {response.text[:1000]}")

        if response.status_code == 401:
            print(
                "\n  ROOT CAUSE: invalid SENDGRID_API_KEY\n"
                "  FIX: generate a new SendGrid API key with Mail Send permission\n"
                "  and update SENDGRID_API_KEY in .env.local"
            )
        elif response.status_code == 403:
            print(
                "\n  ROOT CAUSE: sender not verified or account lacks permission\n"
                "  FIX: verify the sender email/domain in SendGrid and retry"
            )
        elif response.status_code == 429:
            print(
                "\n  ROOT CAUSE: SendGrid rate limit hit\n"
                "  FIX: wait a bit, then retry once"
            )

    except Exception as e:
        print(f"\n  X Unexpected error: {type(e).__name__}: {e}")

    print("=" * 60)


if __name__ == "__main__":
    test_email()
