from app.config import settings
from app.llm import get_llm
from app.llm.anthropic import AnthropicLLMClient
from app.llm.deepseek import DeepSeekLLMClient
from app.llm.mock import MockLLMClient


def test_provider_selection_supports_mock_anthropic_and_deepseek():
    original = settings.llm_provider
    original_key = settings.deepseek_api_key
    original_model = settings.deepseek_model
    try:
        settings.llm_provider = "mock"
        get_llm.cache_clear()
        assert isinstance(get_llm(), MockLLMClient)

        settings.llm_provider = "anthropic"
        get_llm.cache_clear()
        assert isinstance(get_llm(), AnthropicLLMClient)

        settings.llm_provider = "deepseek"
        settings.deepseek_api_key = "test-key"
        settings.deepseek_model = "deepseek-v4-flash"
        get_llm.cache_clear()
        assert isinstance(get_llm(), DeepSeekLLMClient)
    finally:
        settings.llm_provider = original
        settings.deepseek_api_key = original_key
        settings.deepseek_model = original_model
        get_llm.cache_clear()


def test_deepseek_provider_requires_api_key():
    original_provider = settings.llm_provider
    original_key = settings.deepseek_api_key
    try:
        settings.llm_provider = "deepseek"
        settings.deepseek_api_key = None
        get_llm.cache_clear()
        try:
            get_llm()
        except ValueError as exc:
            assert str(exc) == "DEEPSEEK_API_KEY is required when LLM_PROVIDER=deepseek"
        else:
            raise AssertionError("missing DeepSeek key was accepted")
    finally:
        settings.llm_provider = original_provider
        settings.deepseek_api_key = original_key
        get_llm.cache_clear()
