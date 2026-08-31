from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from ..config import settings
from ..schemas import GeneratorContext, PlannerContext, PlannerOutput
from .client import LLMClient
from .errors import LLMProviderError
from .prompts import (
    conversation_messages,
    generator_system_prompt,
    planner_system_prompt,
    validate_visible_reply,
)


SUPPORTED_MODEL = "deepseek-v4-flash"
BASE_URL = "https://api.deepseek.com"

_PLANNER_EXAMPLE = {
    "response_intent": "Respond naturally to the latest message.",
    "emotion_proposal": None,
    "relationship_delta": {},
    "topic_proposal": None,
    "asset_tag": None,
    "story_proposal": None,
    "memory_candidates": [],
    "asset_request": {"requested": False, "tags": []},
}


class DeepSeekLLMClient(LLMClient):
    """DeepSeek provider using the official OpenAI-compatible Python SDK."""

    def __init__(
        self,
        client: Any | None = None,
        *,
        api_key: str | None = None,
        model: str | None = None,
    ):
        self.model = model or settings.deepseek_model
        if self.model != SUPPORTED_MODEL:
            raise ValueError("PersonaFlow currently supports only deepseek-v4-flash")

        self.api_key = api_key if api_key is not None else settings.deepseek_api_key
        if client is None and not self.api_key:
            raise ValueError("DEEPSEEK_API_KEY is required when LLM_PROVIDER=deepseek")
        self._client_instance = client

    def plan(self, ctx: PlannerContext) -> PlannerOutput:
        messages = [
            {"role": "system", "content": self._planner_prompt(ctx)},
            *self._planner_messages(ctx.recent_messages, ctx.user_message),
        ]
        last_code = "invalid_structured_output"

        for attempt in range(2):
            try:
                text = self._completion(
                    stage="planner",
                    messages=messages,
                    max_tokens=settings.deepseek_planner_max_tokens,
                    json_mode=True,
                    # First attempt is fast (thinking disabled). On failure, retry
                    # with default thinking: each mode fails on a different prompt
                    # shape, so the retry rescues the first attempt's misses.
                    thinking_disabled=(attempt == 0),
                )
                return PlannerOutput.model_validate(json.loads(text))
            except json.JSONDecodeError:
                last_code = "malformed_json"
            except ValidationError:
                last_code = "invalid_structured_output"
            except LLMProviderError as exc:
                last_code = exc.code

        raise LLMProviderError("planner", last_code)

    def generate(self, ctx: GeneratorContext) -> str:
        messages = self._messages(
            "\n\n".join(
                [
                    generator_system_prompt(ctx),
                    "Keep the reply short (usually 1-3 sentences) and do not "
                    "contradict concrete facts in the recent conversation.",
                ]
            ),
            ctx.recent_messages,
            ctx.user_message,
        )
        text = self._completion(
            stage="generator",
            messages=messages,
            max_tokens=settings.deepseek_generator_max_tokens,
            json_mode=False,
        )
        return validate_visible_reply(text, ctx)

    def _planner_prompt(self, ctx: PlannerContext) -> str:
        example = json.dumps(_PLANNER_EXAMPLE, ensure_ascii=False)
        return "\n\n".join(
            [
                planner_system_prompt(ctx),
                "Return one valid JSON object and no markdown or commentary.",
                "Only propose a USER_PHOTO_REQUEST transition when the latest user "
                "message explicitly asks to see, show, or send the photo. Merely "
                "mentioning photos, asking whether a photo was taken, or discussing "
                "how it looks is not a photo request.",
                "Use exactly these PlannerOutput fields: response_intent (string), "
                "emotion_proposal (null or object with emotion chosen from neutral, "
                "happy, excited, calm, sad, angry, worried, shy, embarrassed, or "
                "grateful, plus integer intensity from 0 to 100), relationship_delta "
                "(object whose values are integers from -2 to 2), topic_proposal "
                "(string or null), "
                "asset_tag (always null), story_proposal (null or object with "
                "string next_node_id and string-or-null reason), memory_candidates "
                "(array of objects with text, fact_type chosen from user_fact or "
                "character_fact, and integer importance from 1 to 5), and "
                "asset_request (object with boolean requested and an array of "
                "semantic string tags, as described in the contract).",
                f"Valid JSON example: {example}",
            ]
        )

    @staticmethod
    def _messages(system: str, recent_messages, user_message: str) -> list[dict[str, str]]:
        return [
            {"role": "system", "content": system},
            *conversation_messages(recent_messages, user_message),
        ]

    @staticmethod
    def _planner_messages(recent_messages, user_message: str) -> list[dict[str, str]]:
        # DeepSeek returns a whitespace-only completion when the request carries an
        # assistant-role message together with response_format=json_object and
        # thinking disabled (measured: 0/4 empties without assistant turns vs 8/8
        # with one). Collapse recent turns into a single labelled user turn so the
        # planner request never contains an assistant-role message, while keeping
        # all of the context the model needs.
        turns = conversation_messages(recent_messages, user_message)
        if turns and turns[-1]["role"] == "user" and turns[-1]["content"] == user_message:
            turns = turns[:-1]
        if not turns:
            return [{"role": "user", "content": user_message}]
        lines = [
            f"{'CHARACTER' if t['role'] == 'assistant' else 'USER'}: {t['content']}"
            for t in turns
        ]
        collapsed = (
            "Recent conversation:\n"
            + "\n".join(lines)
            + "\n\nLATEST USER MESSAGE:\n"
            + user_message
        )
        return [{"role": "user", "content": collapsed}]

    def _completion(
        self,
        *,
        stage: str,
        messages: list[dict[str, str]],
        max_tokens: int,
        json_mode: bool,
        thinking_disabled: bool = True,
    ) -> str:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0.2,
        }
        if json_mode:
            # json_object + thinking:disabled intermittently returns whitespace-only
            # or malformed content, but only on certain prompt shapes (fast path).
            # plan() retries with default thinking when it does.
            kwargs["response_format"] = {"type": "json_object"}
            if thinking_disabled:
                kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
        else:
            kwargs["extra_body"] = {"thinking": {"type": "disabled"}}

        try:
            response = self._client().chat.completions.create(**kwargs)
            text = response.choices[0].message.content
        except LLMProviderError:
            raise
        except Exception as exc:
            raise LLMProviderError(stage, self._request_error_code(exc)) from None

        if not isinstance(text, str) or not text.strip():
            raise LLMProviderError(stage, "empty_response")
        return text.strip()

    def _client(self) -> Any:
        if self._client_instance is not None:
            return self._client_instance
        try:
            from openai import OpenAI

            self._client_instance = OpenAI(
                api_key=self.api_key,
                base_url=BASE_URL,
                timeout=settings.deepseek_timeout_seconds,
                max_retries=settings.deepseek_max_retries,
            )
        except Exception:
            raise LLMProviderError("provider", "client_init_failed") from None
        return self._client_instance

    @staticmethod
    def _request_error_code(exc: Exception) -> str:
        status = getattr(exc, "status_code", None)
        if status == 401:
            return "authentication_failed"
        if status == 402:
            return "insufficient_balance"
        if status == 429:
            return "rate_limited"
        if isinstance(status, int) and status >= 500:
            return "server_error"
        name = type(exc).__name__.casefold()
        if "timeout" in name:
            return "timeout"
        if "connection" in name or "network" in name:
            return "network_error"
        return "request_failed"
