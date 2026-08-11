"""Interchangeable cloud LLM adapters producing the same rule schema."""

import json
from abc import ABC, abstractmethod
from typing import Dict, List

from .schema import (
    INTERPRETATION_SCHEMA,
    SYSTEM_PROMPT,
    build_gemini_prompt,
    build_user_prompt,
)


class ProviderError(RuntimeError):
    pass


class LanguageProvider(ABC):
    @abstractmethod
    def interpret(
        self,
        message: str,
        catalog: List[Dict[str, object]],
        safety_identifier: str,
    ) -> Dict[str, object]:
        raise NotImplementedError

    @staticmethod
    def _decode(text: str) -> Dict[str, object]:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ProviderError("The language provider returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise ProviderError("The language provider returned an invalid plan")
        return payload


class OpenAIProvider(LanguageProvider):
    def __init__(self, api_key: str, model: str):
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise ProviderError("The openai package is not installed") from exc
        self.client = OpenAI(api_key=api_key, timeout=60.0, max_retries=1)
        self.model = model

    def interpret(self, message, catalog, safety_identifier):
        try:
            response = self.client.responses.create(
                model=self.model,
                instructions=SYSTEM_PROMPT,
                input=build_user_prompt(message, catalog),
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "home_automation_plan",
                        "strict": True,
                        "schema": INTERPRETATION_SCHEMA,
                    }
                },
                store=False,
                safety_identifier=safety_identifier,
            )
            return self._decode(response.output_text)
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(f"OpenAI request failed: {exc}") from exc


class AnthropicProvider(LanguageProvider):
    def __init__(self, api_key: str, model: str):
        try:
            from anthropic import Anthropic
        except ImportError as exc:
            raise ProviderError("The anthropic package is not installed") from exc
        self.client = Anthropic(api_key=api_key, timeout=60.0, max_retries=1)
        self.model = model

    def interpret(self, message, catalog, safety_identifier):
        del safety_identifier
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": build_user_prompt(message, catalog)}],
                output_config={
                    "format": {
                        "type": "json_schema",
                        "schema": INTERPRETATION_SCHEMA,
                    }
                },
            )
            text = "".join(
                str(block.text)
                for block in response.content
                if getattr(block, "type", None) == "text"
            )
            if getattr(response, "stop_reason", None) == "refusal":
                raise ProviderError("Claude refused the request")
            return self._decode(text)
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(f"Anthropic request failed: {exc}") from exc


class GeminiProvider(LanguageProvider):
    def __init__(self, api_key: str, model: str):
        try:
            from google import genai
        except ImportError as exc:
            raise ProviderError("The google-genai package is not installed") from exc
        self.client = genai.Client(api_key=api_key)
        self.model = model

    def interpret(self, message, catalog, safety_identifier):
        del safety_identifier
        try:
            response = self.client.interactions.create(
                model=self.model,
                input=build_gemini_prompt(message, catalog),
                response_format={
                    "type": "text",
                    "mime_type": "application/json",
                },
                store=False,
            )
            return self._decode(response.output_text)
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(f"Gemini request failed: {exc}") from exc


def create_provider(name: str, model: str, api_key: str) -> LanguageProvider:
    normalized = name.strip().lower()
    if normalized == "openai":
        return OpenAIProvider(api_key, model)
    if normalized in {"anthropic", "claude"}:
        return AnthropicProvider(api_key, model)
    if normalized in {"google", "gemini"}:
        return GeminiProvider(api_key, model)
    raise ProviderError(f"Unknown LLM provider: {name}")
