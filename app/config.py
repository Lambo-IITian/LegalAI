import os
from functools import lru_cache
from pydantic_settings import BaseSettings
from pydantic import Field
from dotenv import load_dotenv

# Load .env.local for local development only
load_dotenv(".env.local")


class Settings(BaseSettings):
    # ── App ──────────────────────────────────────────────
    ENVIRONMENT: str = Field(default="development")
    BASE_URL: str    = Field(default="http://localhost:8000")

    # ── Azure OpenAI ─────────────────────────────────────
    AZURE_OPENAI_KEY:               str = Field(default="")
    AZURE_OPENAI_ENDPOINT:          str = Field(default="")
    AZURE_OPENAI_DEPLOYMENT_LARGE:  str = Field(default="gpt-4o-legal")
    AZURE_OPENAI_DEPLOYMENT_SMALL:  str = Field(default="gpt-4o-mini-fast")

    # ── Cosmos DB ────────────────────────────────────────
    COSMOS_CONNECTION_STRING: str = Field(default="")
    COSMOS_DATABASE_NAME:     str = Field(default="legalai-db")

    # ── Blob Storage ─────────────────────────────────────
    AZURE_STORAGE_CONNECTION_STRING: str = Field(default="")
    AZURE_STORAGE_ACCOUNT_NAME:      str = Field(default="legalaiprodstore")

    # ── Communication Services ───────────────────────────
    SENDGRID_API_KEY:    str = Field(default="")
    SENDGRID_FROM_EMAIL: str = Field(default="")

    # ── Content Safety ───────────────────────────────────
    CONTENT_SAFETY_KEY:      str = Field(default="")
    CONTENT_SAFETY_ENDPOINT: str = Field(default="")

    # ── Document Intelligence ────────────────────────────
    DOC_INTELLIGENCE_KEY:      str = Field(default="")
    DOC_INTELLIGENCE_ENDPOINT: str = Field(default="")

    # ── JWT Auth ─────────────────────────────────────────
    JWT_SECRET_KEY:      str = Field(default="changeme")
    JWT_ALGORITHM:       str = Field(default="HS256")
    JWT_EXPIRE_HOURS:    int = Field(default=72)
    OTP_EXPIRE_MINUTES:  int = Field(default=10)

    # ── Monitoring ───────────────────────────────────────
    APPINSIGHTS_INSTRUMENTATION_KEY: str = Field(default="")

    class Config:
        env_file = ".env.local"
        extra    = "ignore"


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
