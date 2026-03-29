import logging
from azure.storage.blob import (
    BlobServiceClient,
    generate_blob_sas,
    BlobSasPermissions,
    ContentSettings,
)
from datetime import datetime, timedelta, timezone
from app.config import settings

logger = logging.getLogger(__name__)

CONTAINERS = {
    "evidence": "evidence-uploads",
    "pdfs":     "generated-pdfs",
    "signed":   "signed-agreements",
}


class BlobService:
    def __init__(self):
        self.client = BlobServiceClient.from_connection_string(
            settings.AZURE_STORAGE_CONNECTION_STRING
        )

    def upload(
        self,
        container_key: str,
        blob_name: str,
        data: bytes,
        content_type: str = "application/pdf",
    ) -> str:
        """Upload bytes. Returns permanent blob URL."""
        container   = CONTAINERS[container_key]
        blob_client = self.client.get_blob_client(
            container=container, blob=blob_name
        )
        blob_client.upload_blob(
            data,
            overwrite=True,
            content_settings=ContentSettings(content_type=content_type),
        )
        logger.info(f"Blob uploaded | container={container} | blob={blob_name}")
        return blob_client.url

    def download(self, container_key: str, blob_name: str) -> bytes:
        container   = CONTAINERS[container_key]
        blob_client = self.client.get_blob_client(
            container=container, blob=blob_name
        )
        return blob_client.download_blob().readall()

    def generate_download_url(
        self,
        container_key: str,
        blob_name: str,
        expiry_hours: int = 72,
    ) -> str:
        """Generate a time-limited SAS URL for secure PDF download."""
        container    = CONTAINERS[container_key]
        account_name = settings.AZURE_STORAGE_ACCOUNT_NAME

        # Extract account key from connection string
        conn_parts  = dict(
            part.split("=", 1)
            for part in settings.AZURE_STORAGE_CONNECTION_STRING.split(";")
            if "=" in part
        )
        account_key = conn_parts.get("AccountKey", "")

        sas_token = generate_blob_sas(
            account_name=account_name,
            container_name=container,
            blob_name=blob_name,
            account_key=account_key,
            permission=BlobSasPermissions(read=True),
            expiry=datetime.now(timezone.utc) + timedelta(hours=expiry_hours),
        )
        return (
            f"https://{account_name}.blob.core.windows.net"
            f"/{container}/{blob_name}?{sas_token}"
        )

    def blob_exists(self, container_key: str, blob_name: str) -> bool:
        container   = CONTAINERS[container_key]
        blob_client = self.client.get_blob_client(
            container=container, blob=blob_name
        )
        try:
            blob_client.get_blob_properties()
            return True
        except Exception:
            return False

    def delete(self, container_key: str, blob_name: str):
        container   = CONTAINERS[container_key]
        blob_client = self.client.get_blob_client(
            container=container, blob=blob_name
        )
        blob_client.delete_blob()


blob_service = BlobService()