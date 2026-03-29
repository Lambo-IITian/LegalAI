import logging
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
import io
from app.core.dependencies import get_current_user
from app.core.exceptions import CaseNotFound, UnauthorizedAccess
from app.services.cosmos_service import cosmos_service
from app.services.blob_service import blob_service

router = APIRouter()
logger = logging.getLogger(__name__)


def _get_case_and_verify(case_id: str, user_email: str) -> dict:
    """Fetch case and verify user is claimant or respondent."""
    case = cosmos_service.get_case(case_id)
    if not case:
        raise CaseNotFound(case_id)
    if (case["claimant_email"] != user_email and
            case["respondent_email"] != user_email):
        raise UnauthorizedAccess()
    return case


@router.get("/{case_id}/demand-letter")
async def get_demand_letter(
    case_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Returns SAS download URL for demand letter PDF."""
    case = _get_case_and_verify(case_id, current_user["email"])

    docs_data = case.get("documents_data", {})
    url       = docs_data.get("demand_letter_url")

    if not url:
        raise HTTPException(
            status_code=404,
            detail="Demand letter not yet generated. Case must be ANALYZED first.",
        )
    return {"download_url": url, "doc_type": "demand_letter"}


@router.get("/{case_id}/court-file")
async def get_court_file(
    case_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Returns SAS download URL for court-ready case file."""
    case = _get_case_and_verify(case_id, current_user["email"])

    docs_data = case.get("documents_data", {})
    url       = docs_data.get("court_file_url")

    if not url:
        raise HTTPException(
            status_code=404,
            detail="Court file not available for this case type or not yet generated.",
        )
    return {"download_url": url, "doc_type": "court_file"}


@router.get("/{case_id}/settlement")
async def get_settlement(
    case_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Returns SAS download URL for settlement agreement."""
    case = _get_case_and_verify(case_id, current_user["email"])

    if case["status"] != "SETTLED":
        raise HTTPException(
            status_code=409,
            detail="Settlement agreement only available for SETTLED cases.",
        )

    url = case.get("settlement_url") or (
        case.get("documents_data") or {}
    ).get("settlement_url")

    if not url:
        raise HTTPException(
            status_code=404,
            detail="Settlement agreement not found.",
        )
    return {"download_url": url, "doc_type": "settlement_agreement"}


@router.get("/{case_id}/fir-advisory")
async def get_fir_advisory(
    case_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Returns SAS download URL for FIR advisory (criminal track only)."""
    case = _get_case_and_verify(case_id, current_user["email"])

    if case.get("track") != "criminal":
        raise HTTPException(
            status_code=400,
            detail="FIR advisory only available for criminal track cases.",
        )

    docs_data = case.get("documents_data", {})
    url       = docs_data.get("fir_advisory_url")

    if not url:
        raise HTTPException(status_code=404, detail="FIR advisory not found.")
    return {"download_url": url, "doc_type": "fir_advisory"}


@router.get("/{case_id}/mediation-certificate")
async def get_mediation_certificate(
    case_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Returns SAS download URL for mediation certificate."""
    case = _get_case_and_verify(case_id, current_user["email"])

    docs_data = case.get("documents_data", {})
    url       = docs_data.get("mediation_certificate_url")

    if not url:
        raise HTTPException(
            status_code=404,
            detail="Mediation certificate not yet generated.",
        )
    return {"download_url": url, "doc_type": "mediation_certificate"}


@router.get("/{case_id}/breach-notice")
async def get_breach_notice(
    case_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Returns SAS download URL for breach of settlement notice."""
    case = _get_case_and_verify(case_id, current_user["email"])

    url = case.get("breach_notice_url")
    if not url:
        raise HTTPException(
            status_code=404,
            detail="Breach notice not generated. Confirm payment first.",
        )
    return {"download_url": url, "doc_type": "breach_notice"}


@router.get("/{case_id}/all")
async def get_all_documents(
    case_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Returns all available document URLs for a case."""
    case = _get_case_and_verify(case_id, current_user["email"])

    docs_data = case.get("documents_data") or {}
    records   = cosmos_service.get_documents_by_case(case_id)

    return {
        "case_id":   case_id,
        "status":    case["status"],
        "documents": {
            "demand_letter":         docs_data.get("demand_letter_url"),
            "court_file":            docs_data.get("court_file_url"),
            "fir_advisory":          docs_data.get("fir_advisory_url"),
            "settlement_agreement":  case.get("settlement_url"),
            "mediation_certificate": docs_data.get("mediation_certificate_url"),
            "breach_notice":         case.get("breach_notice_url"),
        },
        "document_records": records,
    }