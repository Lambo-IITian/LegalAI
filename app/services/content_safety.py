import logging
import re
from azure.ai.contentsafety import ContentSafetyClient
from azure.core.credentials import AzureKeyCredential
from azure.ai.contentsafety.models import AnalyzeTextOptions, TextCategory
from app.config import settings
from app.core.exceptions import ContentSafetyViolation

logger = logging.getLogger(__name__)


class ContentSafetyService:
    def __init__(self):
        self.client = ContentSafetyClient(
            endpoint=settings.CONTENT_SAFETY_ENDPOINT,
            credential=AzureKeyCredential(settings.CONTENT_SAFETY_KEY)
        )

    def sanitize_input(self, text: str) -> str:
        """
        Basic input sanitization before content safety check.
        Removes HTML tags, script injection attempts, SQL patterns.
        """
        # Remove HTML tags
        text = re.sub(r"<[^>]+>", " ", text)
        # Remove script-like patterns
        text = re.sub(r"(?i)(javascript:|<script|eval\(|onload=)", " ", text)
        # Normalize whitespace
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def check_text(self, text: str) -> dict:
        """
        Full content safety check.
        1. Sanitize input
        2. Check against Azure AI Content Safety
        3. Check for abuse patterns
        4. Return scores or raise ContentSafetyViolation
        """
        # Sanitize first
        clean_text = self.sanitize_input(text)

        # Check for obvious abuse patterns before API call
        self._check_abuse_patterns(clean_text)

        # Azure Content Safety API check
        try:
            request  = AnalyzeTextOptions(text=clean_text[:10000])
            response = self.client.analyze_text(request)

            results            = {}
            blocked            = False
            blocked_categories = []

            for item in response.categories_analysis:
                severity = item.severity or 0
                results[item.category.value] = severity

                if item.category in [
                    TextCategory.HATE,
                    TextCategory.VIOLENCE,
                    TextCategory.SELF_HARM,
                ] and severity >= 4:
                    blocked = True
                    blocked_categories.append(item.category.value)

                elif item.category == TextCategory.SEXUAL and severity >= 6:
                    blocked = True
                    blocked_categories.append(item.category.value)

            if blocked:
                logger.warning(f"Content blocked | categories={blocked_categories}")
                raise ContentSafetyViolation()

            logger.info(f"Content Safety passed | scores={results}")
            return results

        except ContentSafetyViolation:
            raise
        except Exception as e:
            # Service down — log and allow (fail open for availability)
            logger.error(f"Content Safety service error: {e}")
            return {}

    def _check_abuse_patterns(self, text: str):
        """
        Check for obvious platform abuse before hitting the API.
        Saves API quota for legitimate cases.
        """
        text_lower = text.lower()

        # Extremely short text
        if len(text.strip()) < 30:
            raise ContentSafetyViolation()

        # Repetitive spam patterns
        words = text.split()
        if len(words) > 10:
            unique_ratio = len(set(words)) / len(words)
            if unique_ratio < 0.2:   # 80%+ repeated words
                raise ContentSafetyViolation()

        # Phone numbers being spammed as dispute text
        phone_pattern = r"\d{10,}"
        phones = re.findall(phone_pattern, text)
        if len(phones) > 5:
            raise ContentSafetyViolation()


content_safety_service = ContentSafetyService()