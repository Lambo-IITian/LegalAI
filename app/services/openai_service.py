import json
import logging
from typing import Optional
from openai import AzureOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential
from app.config import settings

logger = logging.getLogger(__name__)


class OpenAIService:
    def __init__(self):
        self.client = AzureOpenAI(
            api_key=settings.AZURE_OPENAI_KEY,
            azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
            api_version="2024-08-01-preview",
        )
        self.large_model = settings.AZURE_OPENAI_DEPLOYMENT_LARGE
        self.small_model = settings.AZURE_OPENAI_DEPLOYMENT_SMALL

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    def call(
        self,
        system_prompt: str,
        user_message: str,
        use_large_model: bool = False,
        json_mode: bool = True,
        temperature: float = 0.3,
        max_tokens: int = 2000,
    ) -> str:
        """
        Single method for all LLM calls.
        use_large_model=True  → gpt-4o  (Legal Agent, Negotiation Agent)
        use_large_model=False → gpt-4o-mini (Intake, Analytics, Document)
        """
        model = self.large_model if use_large_model else self.small_model

        kwargs = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        try:
            response = self.client.chat.completions.create(**kwargs)
            content = response.choices[0].message.content
            logger.info(f"OpenAI call successful | model={model} | tokens={response.usage.total_tokens}")
            return content

        except Exception as e:
            logger.error(f"OpenAI call failed | model={model} | error={e}")
            raise

    def call_json(
        self,
        system_prompt: str,
        user_message: str,
        use_large_model: bool = False,
        temperature: float = 0.3,
        max_tokens: int = 2000,
    ) -> dict:
        """
        Calls LLM and parses JSON response.
        Use this when you need a dict back directly.
        """
        raw = self.call(
            system_prompt=system_prompt,
            user_message=user_message,
            use_large_model=use_large_model,
            json_mode=True,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            logger.error(f"JSON parse failed | raw={raw[:200]} | error={e}")
            raise ValueError(f"LLM returned invalid JSON: {e}")


# Singleton — import this everywhere
openai_service = OpenAIService()