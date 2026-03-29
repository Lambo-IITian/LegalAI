import uuid
import logging
from datetime import datetime, timezone
from typing import Optional
from azure.cosmos import CosmosClient, exceptions
from app.config import settings
from app.models.case import CaseStatus, TERMINAL_STATES
from app.core.state_machine import transition

logger = logging.getLogger(__name__)


class CosmosService:
    def __init__(self):
        self.client = CosmosClient.from_connection_string(
            settings.COSMOS_CONNECTION_STRING
        )
        self.db           = self.client.get_database_client(settings.COSMOS_DATABASE_NAME)
        self.cases        = self.db.get_container_client("cases")
        self.users        = self.db.get_container_client("users")
        self.negotiations = self.db.get_container_client("negotiations")
        self.documents    = self.db.get_container_client("documents")

    # ── Helpers ───────────────────────────────────────────────

    def _new_id(self) -> str:
        return str(uuid.uuid4())

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    # ── Cases ─────────────────────────────────────────────────

    def create_case(self, data: dict) -> dict:
        case = {
            "id":         self._new_id(),
            "created_at": self._now(),
            "updated_at": self._now(),
            "status":     "SUBMITTED",
            **data,
        }
        self.cases.create_item(body=case)
        logger.info(f"Case created | id={case['id']}")
        return case

    def get_case(self, case_id: str) -> Optional[dict]:
        try:
            return self.cases.read_item(item=case_id, partition_key=case_id)
        except exceptions.CosmosResourceNotFoundError:
            return None

    def update_case(self, case_id: str, updates: dict) -> dict:
        case = self.get_case(case_id)
        if not case:
            raise ValueError(f"Case {case_id} not found")
        case.update(updates)
        case["updated_at"] = self._now()
        self.cases.replace_item(item=case_id, body=case)
        logger.info(f"Case updated | id={case_id}")
        return case

    def transition_case(self, case_id: str, new_status: CaseStatus,
                        extra_updates: dict = None) -> dict:
        """
        THE ONLY WAY to change case status in the entire app.
        Validates the transition, sets deadline, saves to Cosmos.
        """
        case = self.get_case(case_id)
        if not case:
            raise ValueError(f"Case {case_id} not found")
        updated = transition(case, new_status)
        if extra_updates:
            updated.update(extra_updates)
        self.cases.replace_item(item=case_id, body=updated)
        return updated

    def get_cases_by_email(self, email: str) -> list:
        q = ("SELECT * FROM c "
             "WHERE c.claimant_email=@e OR c.respondent_email=@e "
             "ORDER BY c.created_at DESC")
        return list(self.cases.query_items(
            query=q,
            parameters=[{"name": "@e", "value": email}],
            enable_cross_partition_query=True,
        ))

    def get_cases_by_status(self, status: CaseStatus) -> list:
        q = "SELECT * FROM c WHERE c.status = @s"
        return list(self.cases.query_items(
            query=q,
            parameters=[{"name": "@s", "value": status.value}],
            enable_cross_partition_query=True,
        ))

    def get_cases_needing_expiry_check(self) -> list:
        """All non-terminal cases that have a deadline set."""
        q = ("SELECT * FROM c "
             "WHERE IS_DEFINED(c.current_deadline) "
             "AND c.status NOT IN ('SETTLED','ESCALATED',"
             "'AUTO_ESCALATED','ABANDONED','CRIMINAL_ADVISORY')")
        return list(self.cases.query_items(
            query=q,
            enable_cross_partition_query=True,
        ))

    def save_agent_output(self, case_id: str, agent_name: str, output: dict) -> dict:
        """Saves a specific agent's output. agent_name must be one of the 4 valid names."""
        valid = ['intake_data', 'legal_data', 'analytics_data', 'documents_data']
        if agent_name not in valid:
            raise ValueError(f"Invalid agent name: {agent_name}")
        return self.update_case(case_id, {agent_name: output})

    def get_case_for_respondent(self, case_id: str) -> Optional[dict]:
        """
        Filtered view of case for the respondent.
        Removes analytics_data (contains win probability + ZOPA)
        and evidence strength score.
        """
        case = self.get_case(case_id)
        if not case:
            return None
        hidden = ["analytics_data", "claimant_phone", "disclaimer_acknowledged"]
        view = {k: v for k, v in case.items() if k not in hidden}
        if view.get("intake_data"):
            ic = dict(view["intake_data"])
            ic.pop("evidence_strength_score", None)
            view["intake_data"] = ic
        return view

    def set_respondent_verified(self, case_id: str) -> dict:
        return self.update_case(case_id, {"respondent_verified": True})

    def set_settlement_honored(self, case_id: str, honored: bool) -> dict:
        return self.update_case(case_id, {"settlement_honored": honored})

    # ── Users ─────────────────────────────────────────────────

    def get_user_by_email(self, email: str) -> Optional[dict]:
        q = "SELECT * FROM c WHERE c.email = @e"
        r = list(self.users.query_items(
            query=q,
            parameters=[{"name": "@e", "value": email}],
            enable_cross_partition_query=True,
        ))
        return r[0] if r else None

    def upsert_user(self, data: dict) -> dict:
        existing = self.get_user_by_email(data.get("email", ""))
        if existing:
            existing.update(data)
            existing["updated_at"] = self._now()
            self.users.replace_item(item=existing["id"], body=existing)
            return existing
        user = {"id": self._new_id(), "created_at": self._now(), **data}
        self.users.create_item(body=user)
        return user

    def save_otp(self, email: str, otp: str, expires_at: str):
        """Store OTP. Uses deterministic ID so upsert overwrites previous OTP."""
        otp_id = f"otp_{email.replace('@','_').replace('.','_')}"
        doc = {
            "id":         otp_id,
            "email":      email,
            "otp":        otp,
            "expires_at": expires_at,
            "created_at": self._now(),
        }
        self.users.upsert_item(body=doc)

    def get_otp(self, email: str) -> Optional[dict]:
        otp_id = f"otp_{email.replace('@','_').replace('.','_')}"
        try:
            return self.users.read_item(item=otp_id, partition_key=otp_id)
        except exceptions.CosmosResourceNotFoundError:
            return None

    def delete_otp(self, email: str):
        otp_id = f"otp_{email.replace('@','_').replace('.','_')}"
        try:
            self.users.delete_item(item=otp_id, partition_key=otp_id)
        except Exception:
            pass

    # ── Negotiations ──────────────────────────────────────────

    def create_negotiation(self, case_id: str, data: dict) -> dict:
        neg = {
            "id":         self._new_id(),
            "case_id":    case_id,
            "created_at": self._now(),
            "rounds":     [],
            **data,
        }
        self.negotiations.create_item(body=neg)
        return neg

    def get_negotiation_by_case(self, case_id: str) -> Optional[dict]:
        q = "SELECT * FROM c WHERE c.case_id = @cid"
        r = list(self.negotiations.query_items(
            query=q,
            parameters=[{"name": "@cid", "value": case_id}],
            enable_cross_partition_query=True,
        ))
        return r[0] if r else None

    def update_negotiation(self, neg_id: str, updates: dict) -> dict:
        neg = self.negotiations.read_item(item=neg_id, partition_key=neg_id)
        neg.update(updates)
        neg["updated_at"] = self._now()
        self.negotiations.replace_item(item=neg_id, body=neg)
        return neg

    def add_round_to_negotiation(self, neg_id: str, round_data: dict) -> dict:
        neg = self.negotiations.read_item(item=neg_id, partition_key=neg_id)
        neg["rounds"].append(round_data)
        neg["updated_at"] = self._now()
        self.negotiations.replace_item(item=neg_id, body=neg)
        return neg

    def update_round_in_negotiation(self, neg_id: str, round_number: int,
                                    updates: dict) -> dict:
        neg = self.negotiations.read_item(item=neg_id, partition_key=neg_id)
        for i, r in enumerate(neg["rounds"]):
            if r["round_number"] == round_number:
                neg["rounds"][i].update(updates)
                break
        neg["updated_at"] = self._now()
        self.negotiations.replace_item(item=neg_id, body=neg)
        return neg

    def get_round(self, neg_id: str, round_number: int) -> Optional[dict]:
        neg = self.negotiations.read_item(item=neg_id, partition_key=neg_id)
        for r in neg["rounds"]:
            if r["round_number"] == round_number:
                return r
        return None

    # ── Documents ─────────────────────────────────────────────

    def save_document_record(self, case_id: str, doc_type: str, blob_url: str) -> dict:
        doc = {
            "id":         self._new_id(),
            "case_id":    case_id,
            "doc_type":   doc_type,
            "blob_url":   blob_url,
            "created_at": self._now(),
        }
        self.documents.create_item(body=doc)
        return doc

    def get_documents_by_case(self, case_id: str) -> list:
        q = ("SELECT * FROM c WHERE c.case_id=@cid "
             "ORDER BY c.created_at DESC")
        return list(self.documents.query_items(
            query=q,
            parameters=[{"name": "@cid", "value": case_id}],
            enable_cross_partition_query=True,
        ))
    def log_email_sent(
        self,
        case_id: str,
        to_email: str,
        email_type: str,
        subject: str,
    ) -> None:
        """
        Logs every email sent for a case.
        Useful for debugging and audit trail.
        """
        try:
            log_doc = {
                "id":         f"email_{self._new_id()}",
                "case_id":    case_id,
                "to_email":   to_email,
                "email_type": email_type,
                "subject":    subject,
                "sent_at":    self._now(),
            }
            self.documents.create_item(body=log_doc)
        except Exception as e:
            logger.warning(f"Email log failed (non-critical) | error={e}")

# Singleton — import this everywhere
cosmos_service = CosmosService()