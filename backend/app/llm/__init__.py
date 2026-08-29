from functools import lru_cache

from .client import LLMClient
from .mock import MockLLMClient


@lru_cache
def get_llm() -> LLMClient:
    """按 settings.llm_provider 返回供应商客户端。默认 mock（离线/测试/CI）。"""
    from ..config import settings

    if settings.llm_provider == "mock":
        return MockLLMClient()
    if settings.llm_provider == "anthropic":
        from .anthropic import AnthropicLLMClient

        return AnthropicLLMClient()
    if settings.llm_provider == "deepseek":
        from .deepseek import DeepSeekLLMClient

        return DeepSeekLLMClient()
    raise ValueError(f"未知 LLM provider: {settings.llm_provider}")
