from __future__ import annotations

import unittest
from unittest.mock import patch

from backend.llm_provider import (
    DEFAULT_GEMINI_MODEL,
    DEFAULT_HOLO_BASE_URL,
    DEFAULT_HOLO_MODEL,
    DEFAULT_OPENAI_MODEL,
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

    def test_creates_openai_client_from_environment(self) -> None:
        with patch("backend.llm_provider.OpenAIClient") as openai_client:
            client = object()
            openai_client.return_value = client

            llm = LLMProvider(
                {
                    "LLM_PROVIDER": "openai",
                    "OPENAI_API_KEY": "openai-key",
                    "LLM_MODEL": "gpt-5.4",
                    "OPENAI_REASONING_EFFORT": "high",
                    "OPENAI_VERBOSITY": "low",
                }
            ).create_multimodal_llm()

        self.assertIs(llm, client)
        openai_client.assert_called_once_with(
            api_key="openai-key",
            model="gpt-5.4",
            reasoning_effort="high",
            verbosity="low",
        )

    def test_defaults_to_openai_model_and_settings(self) -> None:
        with patch("backend.llm_provider.OpenAIClient") as openai_client:
            LLMProvider(
                {
                    "LLM_PROVIDER": "openai",
                    "OPENAI_API_KEY": "openai-key",
                }
            ).create_multimodal_llm()

        openai_client.assert_called_once_with(
            api_key="openai-key",
            model=DEFAULT_OPENAI_MODEL,
            reasoning_effort="low",
            verbosity="low",
        )

    def test_creates_holo_client_from_environment(self) -> None:
        with patch("backend.llm_provider.HoloChatClient") as holo_client:
            client = object()
            holo_client.return_value = client

            llm = LLMProvider(
                {
                    "LLM_PROVIDER": "holo",
                    "HAI_API_KEY": "hai-key",
                    "HAI_BASE_URL": "https://holo.example/v1/",
                    "HOLO_MODEL": "holo-test-model",
                }
            ).create_multimodal_llm()

        self.assertIs(llm, client)
        holo_client.assert_called_once_with(
            api_key="hai-key",
            model="holo-test-model",
            base_url="https://holo.example/v1/",
        )

    def test_defaults_to_holo_model_and_base_url(self) -> None:
        with patch("backend.llm_provider.HoloChatClient") as holo_client:
            LLMProvider(
                {
                    "LLM_PROVIDER": "holo",
                    "HAI_API_KEY": "hai-key",
                }
            ).create_multimodal_llm()

        holo_client.assert_called_once_with(
            api_key="hai-key",
            model=DEFAULT_HOLO_MODEL,
            base_url=DEFAULT_HOLO_BASE_URL,
        )

    def test_rejects_unsupported_provider(self) -> None:
        with self.assertRaisesRegex(
            LLMProviderConfigurationError,
            "Unsupported LLM_PROVIDER: anthropic",
        ):
            LLMProvider({"LLM_PROVIDER": "anthropic"}).create_multimodal_llm()

    def test_requires_gemini_api_key(self) -> None:
        with self.assertRaisesRegex(
            LLMProviderConfigurationError,
            "GEMINI_API_KEY is required",
        ):
            LLMProvider({"LLM_PROVIDER": "gemini"}).create_multimodal_llm()

    def test_requires_openai_api_key(self) -> None:
        with self.assertRaisesRegex(
            LLMProviderConfigurationError,
            "OPENAI_API_KEY is required",
        ):
            LLMProvider({"LLM_PROVIDER": "openai"}).create_multimodal_llm()

    def test_requires_holo_api_key(self) -> None:
        with self.assertRaisesRegex(
            LLMProviderConfigurationError,
            "HAI_API_KEY is required",
        ):
            LLMProvider({"LLM_PROVIDER": "holo"}).create_multimodal_llm()


if __name__ == "__main__":
    unittest.main()
