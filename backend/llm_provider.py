from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

from backend.gemini_client import GeminiClient
from backend.llm import MultimodalLLM
from backend.openai_client import OpenAIClient


DEFAULT_LLM_PROVIDER = "gemini"
DEFAULT_GEMINI_MODEL = "gemini-3-flash-preview"
DEFAULT_OPENAI_MODEL = "gpt-5.4-mini"
DEFAULT_HOLO_BASE_URL = "https://api.hcompany.ai/v1/"
DEFAULT_HOLO_MODEL = "holo3-35b-a3b"
DEFAULT_OPENAI_REASONING_EFFORT = "medium"
DEFAULT_OPENAI_VERBOSITY = "medium"


class LLMProviderConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class LLMProvider:
    environment: Mapping[str, str]

    @classmethod
    def from_environment(cls) -> LLMProvider:
        return cls(os.environ)

    def create_multimodal_llm(self) -> MultimodalLLM:
        provider = self._provider_name()
        if provider == "gemini":
            return self._create_gemini_client()
        if provider == "openai":
            return self._create_openai_client()
        if provider == "holo":
            return self._create_holo_client()

        raise LLMProviderConfigurationError(f"Unsupported LLM_PROVIDER: {provider}")

    def _provider_name(self) -> str:
        return (self.environment.get("LLM_PROVIDER") or DEFAULT_LLM_PROVIDER).lower()

    def _create_gemini_client(self) -> GeminiClient:
        api_key = self._required("GEMINI_API_KEY")
        model = (
            self.environment.get("LLM_MODEL")
            or self.environment.get("GEMINI_MODEL")
            or DEFAULT_GEMINI_MODEL
        )
        return GeminiClient(api_key=api_key, model=model)

    def _create_openai_client(self) -> OpenAIClient:
        api_key = self._required("OPENAI_API_KEY")
        model = (
            self.environment.get("LLM_MODEL")
            or self.environment.get("OPENAI_MODEL")
            or DEFAULT_OPENAI_MODEL
        )
        return OpenAIClient(
            api_key=api_key,
            model=model,
            reasoning_effort=self.environment.get(
                "OPENAI_REASONING_EFFORT", DEFAULT_OPENAI_REASONING_EFFORT
            ),
            verbosity=self.environment.get(
                "OPENAI_VERBOSITY", DEFAULT_OPENAI_VERBOSITY
            ),
        )

    def _create_holo_client(self) -> OpenAIClient:
        api_key = self._required("HAI_API_KEY")
        model = (
            self.environment.get("HOLO_MODEL")
            or self.environment.get("LLM_MODEL")
            or DEFAULT_HOLO_MODEL
        )
        return OpenAIClient(
            api_key=api_key,
            model=model,
            base_url=self.environment.get("HAI_BASE_URL") or DEFAULT_HOLO_BASE_URL,
            reasoning_effort=self.environment.get(
                "OPENAI_REASONING_EFFORT", DEFAULT_OPENAI_REASONING_EFFORT
            ),
            verbosity=self.environment.get(
                "OPENAI_VERBOSITY", DEFAULT_OPENAI_VERBOSITY
            ),
        )

    def _required(self, name: str) -> str:
        value = self.environment.get(name)
        if not value:
            raise LLMProviderConfigurationError(
                f"{name} is required to stream LLM responses."
            )
        return value
