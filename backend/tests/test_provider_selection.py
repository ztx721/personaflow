from app.config import settings
from app.llm import get_llm
from app.llm.anthropic import AnthropicLLMClient
from app.llm.mock import MockLLMClient


def test_provider_selection_supports_mock_and_anthropic():
    original = settings.llm_provider
    try:
        settings.llm_provider = "mock"
        get_llm.cache_clear()
        assert isinstance(get_llm(), MockLLMClient)

        settings.llm_provider = "anthropic"
        get_llm.cache_clear()
        assert isinstance(get_llm(), AnthropicLLMClient)
    finally:
        settings.llm_provider = original
        get_llm.cache_clear()
