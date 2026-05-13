from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

from backend.gemini_client import GeminiClient
from backend.llm import MultimodalLLM


DEFAULT_LLM_PROVIDER = "gemini"
DEFAULT_GEMINI_MODEL = "gemini-3-flash-preview"


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

        raise LLMProviderConfigurationError(f"Unsupported LLM_PROVIDER: {provider}")

    def _provider_name(self) -> str:
        return (self.environment.get("LLM_PROVIDER") or DEFAULT_LLM_PROVIDER).lower()

    def _create_gemini_client(self) -> GeminiClient:
        api_key = self._required("GEMINI_API_KEY")
        model = self.environment.get("LLM_MODEL") or self.environment.get(
            "GEMINI_MODEL",
            DEFAULT_GEMINI_MODEL,
        )
        return GeminiClient(api_key=api_key, model=model)

    def _required(self, name: str) -> str:
        value = self.environment.get(name)
        if not value:
            raise LLMProviderConfigurationError(
                f"{name} is required to stream LLM responses."
            )
        return value
