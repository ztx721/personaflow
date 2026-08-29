from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from ..config import settings
from ..schemas import GeneratorContext, PlannerContext, PlannerOutput, Utterance
from .client import LLMClient
from .errors import LLMProviderError
from .prompts import (
    conversation_messages,
    generator_system_prompt,
    planner_system_prompt,
    validate_visible_reply,
)


class AnthropicLLMClient(LLMClient):
    """Claude-backed planner and generator with Pydantic-validated outputs."""

    def __init__(
        self,
        client: Any | None = None,
        *,
        api_key: str | None = None,
        model: str | None = None,
    ):
        self._client_instance = client
        self.api_key = api_key if api_key is not None else settings.anthropic_api_key
        self.model = model or settings.anthropic_model

    def plan(self, ctx: PlannerContext) -> PlannerOutput:
        parsed = self._parse(
            stage="planner",
            output_format=PlannerOutput,
            system=planner_system_prompt(ctx),
            messages=conversation_messages(ctx.recent_messages, ctx.user_message),
            max_tokens=settings.anthropic_planner_max_tokens,
        )
        try:
            return PlannerOutput.model_validate(parsed)
        except ValidationError:
            raise LLMProviderError("planner", "invalid_structured_output") from None

    def generate(self, ctx: GeneratorContext) -> str:
        parsed = self._parse(
            stage="generator",
            output_format=Utterance,
            system=generator_system_prompt(ctx),
            messages=conversation_messages(ctx.recent_messages, ctx.user_message),
            max_tokens=settings.anthropic_generator_max_tokens,
        )
        try:
            utterance = Utterance.model_validate(parsed)
        except ValidationError:
            raise LLMProviderError("generator", "invalid_structured_output") from None
        return validate_visible_reply(utterance.text, ctx)

    def _parse(
        self,
        *,
        stage: str,
        output_format: type,
        system: str,
        messages: list[dict[str, str]],
        max_tokens: int,
    ) -> Any:
        try:
            response = self._client().messages.parse(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=messages,
                output_format=output_format,
            )
        except LLMProviderError:
            raise
        except ValidationError:
            raise LLMProviderError(stage, "invalid_structured_output") from None
        except Exception:
            raise LLMProviderError(stage, "request_failed") from None

        parsed = getattr(response, "parsed_output", None)
        if parsed is None:
            raise LLMProviderError(stage, "missing_structured_output")
        return parsed

    def _client(self) -> Any:
        if self._client_instance is not None:
            return self._client_instance
        if not self.api_key:
            raise LLMProviderError("provider", "missing_api_key")
        try:
            from anthropic import Anthropic

            self._client_instance = Anthropic(
                api_key=self.api_key,
                timeout=settings.anthropic_timeout_seconds,
                max_retries=settings.anthropic_max_retries,
            )
        except Exception:
            raise LLMProviderError("provider", "client_init_failed") from None
        return self._client_instance
