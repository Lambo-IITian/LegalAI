"""
End-to-end test covering the complete happy path:
Submit -> Analyze -> Invite -> Negotiate -> Settle -> Download PDF

Run with: python tests/test_health.py
Requires: Azure services plus SendGrid configured in .env.local
"""
import asyncio
import sys

import httpx
from dotenv import load_dotenv

load_dotenv(".env.local")

BASE = "http://localhost:8000"
CLAIMANT_EMAIL = "gunanimohit1221@gmail.com"
RESPONDENT_EMAIL = "aigunani744@gmail.com"
CLIENT_TIMEOUT = httpx.Timeout(connect=30.0, read=300.0, write=60.0, pool=60.0)


def _assert(condition: bool, msg: str, response=None):
    if not condition:
        print(f"\n    ASSERTION FAILED: {msg}")
        if response is not None:
            print(f"    STATUS: {response.status_code}")
            print(f"    BODY:   {response.text[:500]}")
        raise AssertionError(msg)


async def run():
    async with httpx.AsyncClient(base_url=BASE, timeout=CLIENT_TIMEOUT) as client:
        print("=" * 60)
        print("LegalAI Resolver - End-to-End Test")
        print("=" * 60)

        print("\n[1] Health check...")
        r = await client.get("/health")
        _assert(r.status_code == 200, "Health endpoint failed", r)
        health = r.json()
        _assert(health["status"] == "healthy", f"Health degraded: {health}")
        print("    OK All services healthy")

        print(f"\n[2] Requesting OTP for {CLAIMANT_EMAIL}...")
        r = await client.post("/api/auth/request-otp", json={
            "email": CLAIMANT_EMAIL,
            "display_name": "Test Claimant",
        })
        _assert(r.status_code == 200, "request-otp failed", r)
        print(f"    OK OTP email sent to {CLAIMANT_EMAIL}")
        otp = input("    OTP > ").strip()

        print("\n[3] Verifying OTP...")
        r = await client.post("/api/auth/verify-otp", json={
            "email": CLAIMANT_EMAIL,
            "otp": otp,
            "display_name": "Test Claimant",
            "city": "New Delhi",
            "state": "Delhi",
            "phone": "9999999999",
            "consent": True,
        })
        _assert(r.status_code == 200, "verify-otp failed", r)
        token = r.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        print("    OK JWT obtained")

        print("\n[4] Submitting case...")
        r = await client.post("/api/cases/submit", json={
            "dispute_text": (
                "My landlord Rajesh Kumar has refused to return my security "
                "deposit of Rs. 45000 after I vacated the flat on 1st February "
                "2025. He claims damages that do not exist. I have the rental "
                "agreement, bank transfer receipt, and photos of the flat on "
                "move-out day showing it was in perfect condition."
            ),
            "claimant_name": "Test Claimant",
            "claimant_email": CLAIMANT_EMAIL,
            "claimant_phone": "9999999999",
            "claimant_city": "New Delhi",
            "claimant_state": "Delhi",
            "respondent_name": "Rajesh Kumar",
            "respondent_email": RESPONDENT_EMAIL,
            "respondent_type": "individual",
            "claim_amount": 45000,
            "currency": "INR",
            "incident_date": "2025-02-01",
            "claimant_consent": True,
            "disclaimer_acknowledged": True,
        }, headers=headers)
        _assert(r.status_code == 200, "case submit failed", r)
        case_id = r.json()["case_id"]
        track = r.json()["track"]
        print(f"    OK Case submitted | id={case_id[:8].upper()} | track={track}")

        print("\n[5] Waiting for AI analysis...")
        case_status = "ANALYZING"
        for i in range(24):
            await asyncio.sleep(5)
            r = await client.get(f"/api/cases/{case_id}/status")
            case_status = r.json()["status"]
            print(f"    [{(i + 1) * 5}s] status={case_status}")
            if case_status == "ANALYZED":
                break
            if case_status in ["ESCALATED", "ABANDONED", "CRIMINAL_ADVISORY"]:
                print(f"    Unexpected terminal status: {case_status}")
                sys.exit(1)
        _assert(case_status == "ANALYZED", f"Did not reach ANALYZED. Final: {case_status}")
        print("    OK Analysis complete")

        print("\n[6] Checking analysis data...")
        r = await client.get(f"/api/cases/{case_id}", headers=headers)
        _assert(r.status_code == 200, "get case failed", r)
        case = r.json()
        _assert(bool(case.get("intake_data")), "intake_data missing")
        _assert(bool(case.get("legal_data")), "legal_data missing")
        _assert(bool(case.get("analytics_data")), "analytics_data missing")
        _assert(bool(case.get("documents_data")), "documents_data missing")
        wp = case["analytics_data"].get("win_probability")
        zopa = case["analytics_data"].get("zopa_optimal")
        ls = case["legal_data"].get("legal_standing")
        print(f"    OK Win probability: {wp}%")
        print(f"    OK ZOPA optimal: Rs. {zopa:,.0f}")
        print(f"    OK Legal standing: {ls}")

        print(f"\n[7] Sending invite to {RESPONDENT_EMAIL}...")
        r = await client.post(f"/api/cases/{case_id}/send-invite", headers=headers)
        _assert(r.status_code == 200, "send invite failed", r)
        print("    OK Invite sent")

        print("\n[8] Respondent views case...")
        r = await client.get(
            f"/api/respondent/case/{case_id}",
            params={"email": RESPONDENT_EMAIL},
        )
        _assert(r.status_code == 200, "respondent view failed", r)
        respondent_view = r.json()
        _assert(
            "analytics_data" not in respondent_view.get("case", {}),
            "analytics data leaked to respondent",
        )
        print("    OK Respondent view works")

        print("\n[9] Respondent submits offer...")
        r = await client.post("/api/negotiation/submit-respondent-offer", json={
            "case_id": case_id,
            "round_number": 1,
            "offer_amount": 20000,
        })
        _assert(r.status_code == 200, "respondent offer failed", r)
        print("    OK Respondent offer submitted")

        print("\n[10] Claimant submits offer...")
        r = await client.post("/api/negotiation/submit-claimant-offer", json={
            "case_id": case_id,
            "round_number": 1,
            "offer_amount": 42000,
        }, headers=headers)
        _assert(r.status_code == 200, "claimant offer failed", r)
        print("    OK Both offers submitted")

        print("\n[11] Waiting for AI proposal...")
        case_status = ""
        for i in range(18):
            await asyncio.sleep(5)
            r = await client.get(f"/api/cases/{case_id}/status")
            case_status = r.json()["status"]
            print(f"    [{(i + 1) * 5}s] case_status={case_status}")
            if case_status == "PROPOSAL_ISSUED":
                break
        _assert(case_status == "PROPOSAL_ISSUED", f"Proposal not issued. Status={case_status}")

        r = await client.get(f"/api/negotiation/status/{case_id}")
        _assert(r.status_code == 200, "negotiation status failed", r)
        neg_data = r.json().get("current_round_detail") or {}
        proposed = neg_data.get("proposed_amount", 0) or 0
        reasoning = neg_data.get("ai_reasoning", "") or ""
        _assert("ZOPA" not in reasoning.upper(), "ZOPA revealed in proposal reasoning")
        print(f"    OK Proposal issued: Rs. {proposed:,.0f}")

        print("\n[12] Claimant accepts proposal...")
        r = await client.post("/api/negotiation/proposal-response", json={
            "case_id": case_id,
            "round_number": 1,
            "decision": "ACCEPT",
            "party": "claimant",
        }, headers=headers)
        _assert(r.status_code == 200, "claimant accept failed", r)
        print("    OK Claimant accepted")

        print("\n[13] Respondent accepts proposal...")
        r = await client.post("/api/respondent/proposal-response", json={
            "case_id": case_id,
            "email": RESPONDENT_EMAIL,
            "decision": "ACCEPT",
        })
        _assert(r.status_code == 200, "respondent accept failed", r)
        print(f"    OK Outcome: {r.json().get('outcome')}")

        print("\n[14] Waiting for settlement...")
        case_status = ""
        for i in range(12):
            await asyncio.sleep(5)
            r = await client.get(f"/api/cases/{case_id}/status")
            case_status = r.json()["status"]
            print(f"    [{(i + 1) * 5}s] status={case_status}")
            if case_status == "SETTLED":
                break
        _assert(case_status == "SETTLED", f"Did not reach SETTLED. Final: {case_status}")
        print("    OK Case settled")

        print("\n[15] Checking documents...")
        r = await client.get(f"/api/documents/{case_id}/all", headers=headers)
        _assert(r.status_code == 200, "get docs failed", r)
        docs = r.json()["documents"]
        _assert(bool(docs.get("demand_letter")), "demand letter missing")
        _assert(bool(docs.get("settlement_agreement")), "settlement agreement missing")
        print("    OK Documents available")

        print("\n[16] Testing demand letter download URL...")
        r2 = httpx.get(docs["demand_letter"], timeout=30)
        _assert(r2.status_code == 200, f"demand letter download failed: {r2.status_code}")
        _assert(len(r2.content) > 5000, f"PDF too small: {len(r2.content)} bytes")
        _assert(r2.content[:4] == b"%PDF", "demand letter is not a valid PDF")
        print(f"    OK Demand letter PDF valid ({len(r2.content):,} bytes)")

        print("\n[17] Testing settlement agreement download URL...")
        r3 = httpx.get(docs["settlement_agreement"], timeout=30)
        _assert(r3.status_code == 200, f"settlement download failed: {r3.status_code}")
        _assert(r3.content[:4] == b"%PDF", "settlement agreement is not a valid PDF")
        print(f"    OK Settlement agreement PDF valid ({len(r3.content):,} bytes)")

        print("\n[18] Testing mediation certificate...")
        r = await client.get(f"/api/cases/{case_id}/mediation-certificate", headers=headers)
        _assert(r.status_code == 200, "mediation certificate failed", r)
        cert_url = r.json()["download_url"]
        _assert(bool(cert_url), "no mediation certificate URL")
        print("    OK Mediation certificate available")

        print("\n[19] Testing rate limiting...")
        blocked = False
        for i in range(10):
            try:
                async with httpx.AsyncClient(base_url=BASE, timeout=CLIENT_TIMEOUT) as rl_client:
                    r = await rl_client.post(
                        "/api/auth/request-otp",
                        json={"email": "ratelimitest@devtest.com", "display_name": "Rate Test"},
                        headers={"Connection": "close"},
                    )
                if r.status_code == 429:
                    blocked = True
                    print(f"    OK Rate limit triggered after {i + 1} requests")
                    break
            except (httpx.ReadError, httpx.ReadTimeout):
                blocked = True
                print(f"    OK Rate limit/connection cutoff triggered after {i + 1} requests")
                break
        _assert(blocked, "rate limiting not working")

        print("\n[20] Testing security headers...")
        r = await client.get("/health")
        _assert(r.headers.get("X-Frame-Options") == "DENY", "X-Frame-Options missing")
        _assert(r.headers.get("X-Content-Type-Options") == "nosniff", "X-Content-Type-Options missing")
        _assert("X-Request-ID" in r.headers, "X-Request-ID header missing")
        print(f"    OK X-Request-ID: {r.headers['X-Request-ID']}")

        print("\n" + "=" * 60)
        print("ALL 20 TESTS PASSED")
        print(f"Case ID: {case_id[:8].upper()}")
        print(f"Settled Amount: Rs. {proposed:,.0f}")
        print("=" * 60)


if __name__ == "__main__":
    asyncio.run(run())
