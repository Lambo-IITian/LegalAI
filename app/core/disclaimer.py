"""
Disclaimer constants used across the application.
All PDFs, all API responses involving legal output,
and the frontend must reference these.
"""

DPDP_CONSENT_TEXT = (
    "I consent to the processing of my personal data and the personal data "
    "of the other party for the purposes of dispute resolution, under India's "
    "Digital Personal Data Protection Act 2023. I understand that my data will "
    "be stored securely and used only for resolving this dispute."
)

AI_DISCLAIMER_TEXT = (
    "LegalAI Resolver provides AI-assisted document drafting, legal information, "
    "and mediation support. It is not a law firm and does not provide legal advice. "
    "The documents generated are AI-drafted and have not been reviewed by a licensed "
    "advocate. They should be reviewed by a qualified lawyer before use in court "
    "proceedings. The AI analysis is based on publicly available legal information "
    "and may not account for jurisdiction-specific nuances or recent legal changes."
)

SETTLEMENT_DISCLAIMER = (
    "This Settlement Agreement is AI-generated and has not been reviewed by a "
    "licensed advocate. It constitutes a legally binding contract once signed by "
    "both parties. Both parties are strongly advised to seek independent legal "
    "counsel before signing. LegalAI Resolver is not liable for the enforcement "
    "or outcome of this agreement."
)

CRIMINAL_DISCLAIMER = (
    "This advisory is AI-generated for informational purposes only. Criminal "
    "matters require immediate consultation with a qualified criminal lawyer. "
    "Do not delay seeking professional legal help or contacting the police in "
    "emergency situations. LegalAI Resolver cannot mediate criminal disputes."
)

PDF_WATERMARK_TEXT = "AI-GENERATED DOCUMENT — NOT LEGAL ADVICE — REVIEW BY ADVOCATE RECOMMENDED"