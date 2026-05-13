from __future__ import annotations

import unittest
from unittest.mock import patch

from backend.llm_provider import (
    DEFAULT_GEMINI_MODEL,
    LLMProvider,
    LLMProviderConfigurationError,
)


class LLMProviderTests(unittest.TestCase):
    def test_creates_gemini_client_from_environment(self) -> None:
        with patch("backend.llm_provider.GeminiClient") as gemini_client:
            client = object()
            gemini_client.return_value = client

            llm = LLMProvider(
                {
                    "LLM_PROVIDER": "gemini",
                    "GEMINI_API_KEY": "gemini-key",
                    "LLM_MODEL": "gemini-test-model",
                }
            ).create_multimodal_llm()

        self.assertIs(llm, client)
        gemini_client.assert_called_once_with(
            api_key="gemini-key",
            model="gemini-test-model",
        )

    def test_defaults_to_gemini_provider_and_model(self) -> None:
        with patch("backend.llm_provider.GeminiClient") as gemini_client:
            LLMProvider({"GEMINI_API_KEY": "gemini-key"}).create_multimodal_llm()

        gemini_client.assert_called_once_with(
            api_key="gemini-key",
            model=DEFAULT_GEMINI_MODEL,
        )

    def test_falls_back_to_legacy_gemini_model_env(self) -> None:
        with patch("backend.llm_provider.GeminiClient") as gemini_client:
            LLMProvider(
                {
                    "GEMINI_API_KEY": "gemini-key",
                    "GEMINI_MODEL": "legacy-model",
                }
            ).create_multimodal_llm()

        gemini_client.assert_called_once_with(
            api_key="gemini-key",
            model="legacy-model",
        )

    def test_rejects_unsupported_provider(self) -> None:
        with self.assertRaisesRegex(
            LLMProviderConfigurationError,
            "Unsupported LLM_PROVIDER: openai",
        ):
            LLMProvider({"LLM_PROVIDER": "openai"}).create_multimodal_llm()

    def test_requires_gemini_api_key(self) -> None:
        with self.assertRaisesRegex(
            LLMProviderConfigurationError,
            "GEMINI_API_KEY is required",
        ):
            LLMProvider({"LLM_PROVIDER": "gemini"}).create_multimodal_llm()


if __name__ == "__main__":
    unittest.main()
