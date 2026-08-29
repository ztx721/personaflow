import json
from types import SimpleNamespace

import pytest

from app.config_loader import load_assets, load_personas, load_stories
from app.core.conversation_service import ConversationService
from app.db import SessionLocal
from app.llm.deepseek import DeepSeekLLMClient
from app.llm.errors import LLMProviderError, UnsafeGeneratorOutputError
from app.schemas import (
    ChatTurn,
    ConversationState,
    Emotion,
    GeneratorContext,
    PersonaConfig,
    PlannerContext,
    PlannerOutput,
    StoryContext,
)


class FakeCompletions:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        output = self.outputs.pop(0)
        if isinstance(output, Exception):
            raise output
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=output))]
        )


class FakeClient:
    def __init__(self, outputs):
        self.completions = FakeCompletions(outputs)
        self.chat = SimpleNamespace(completions=self.completions)


class StatusError(RuntimeError):
    def __init__(self, status_code):
        super().__init__("sensitive upstream detail")
        self.status_code = status_code


class APITimeoutError(RuntimeError):
    pass


class APIConnectionError(RuntimeError):
    pass


VALID_PLAN = {
    "response_intent": "自然回应问候",
    "emotion_proposal": {"emotion": "happy", "intensity": 55},
    "relationship_delta": {"trust": 1},
    "topic_proposal": None,
    "asset_tag": None,
    "story_proposal": None,
    "memory_candidates": [],
}


def _persona():
    return PersonaConfig(role_id="miko_cafe", display_name="林小满")


def _state():
    return ConversationState(
        conversation_id="conv",
        role_id="miko_cafe",
        emotion=Emotion.neutral,
        emotion_intensity=50,
        relationship={"trust": 20, "affection": 30},
    )


def _story():
    return StoryContext(
        story_id="travel_photo",
        node_id="greeting",
        scene="安静的旧书店。",
        beat="自然接住用户的话题。",
    )


def _planner_context():
    return PlannerContext(
        persona=_persona(),
        state=_state(),
        story=_story(),
        recent_messages=[ChatTurn(sender="user", content="你好")],
        user_message="你好",
    )


def _generator_context():
    return GeneratorContext(
        persona=_persona(),
        state=_state(),
        story=_story(),
        recent_messages=[ChatTurn(sender="user", content="你好")],
        user_message="你好",
        planner=PlannerOutput(response_intent="自然回应问候"),
    )


def test_supported_model_is_accepted():
    DeepSeekLLMClient(client=FakeClient([]), model="deepseek-v4-flash")


def test_any_other_model_is_rejected():
    with pytest.raises(ValueError, match="currently supports only deepseek-v4-flash"):
        DeepSeekLLMClient(client=FakeClient([]), model="deepseek-chat")


def test_valid_planner_json_is_pydantic_validated():
    fake = FakeClient([json.dumps(VALID_PLAN)])
    result = DeepSeekLLMClient(client=fake).plan(_planner_context())

    assert isinstance(result, PlannerOutput)
    assert result.emotion_proposal.emotion is Emotion.happy
    call = fake.completions.calls[0]
    assert call["model"] == "deepseek-v4-flash"
    assert call["response_format"] == {"type": "json_object"}
    # The planner's fast first attempt uses thinking disabled.
    assert call["extra_body"] == {"thinking": {"type": "disabled"}}
    assert "Use exactly these PlannerOutput fields" in call["messages"][0]["content"]
    assert "Merely mentioning photos" in call["messages"][0]["content"]


def test_planner_request_never_contains_assistant_role_message():
    # DeepSeek returns whitespace-only content when json_object + thinking disabled
    # is combined with an assistant-role message; the provider must collapse recent
    # turns into a single labelled user turn instead.
    fake = FakeClient([json.dumps(VALID_PLAN)])
    ctx = _planner_context()
    ctx.recent_messages = [
        ChatTurn(sender="user", content="你好呀，今天过得怎么样？"),
        ChatTurn(sender="character", content="还不错，刚整理完书架。"),
    ]
    ctx.user_message = "今天有点累。"

    result = DeepSeekLLMClient(client=fake).plan(ctx)

    assert result.response_intent == "自然回应问候"
    call = fake.completions.calls[0]
    roles = [m["role"] for m in call["messages"]]
    assert roles == ["system", "user"]
    collapsed = call["messages"][-1]["content"]
    assert "CHARACTER: 还不错，刚整理完书架。" in collapsed
    assert "LATEST USER MESSAGE:\n今天有点累。" in collapsed


@pytest.mark.parametrize(
    ("bad_output", "expected_code"),
    [
        ("not-json", "malformed_json"),
        ("", "empty_response"),
        ('{"emotion_proposal":{"emotion":"invalid"}}', "invalid_structured_output"),
    ],
)
def test_invalid_planner_output_retries_once_then_fails(bad_output, expected_code):
    fake = FakeClient([bad_output, bad_output])
    with pytest.raises(LLMProviderError) as exc_info:
        DeepSeekLLMClient(client=fake).plan(_planner_context())

    assert exc_info.value.code == expected_code
    assert len(fake.completions.calls) == 2


def test_planner_retry_can_recover():
    fake = FakeClient(["not-json", json.dumps(VALID_PLAN)])
    result = DeepSeekLLMClient(client=fake).plan(_planner_context())
    assert result.response_intent == "自然回应问候"
    assert len(fake.completions.calls) == 2


def test_planner_retry_drops_thinking_disabled():
    # json_object + thinking disabled intermittently returns empty content on some
    # prompt shapes; the retry must switch to default thinking to recover.
    fake = FakeClient(["", json.dumps(VALID_PLAN)])
    result = DeepSeekLLMClient(client=fake).plan(_planner_context())

    assert result.response_intent == "自然回应问候"
    assert len(fake.completions.calls) == 2
    first, second = fake.completions.calls
    assert first["extra_body"] == {"thinking": {"type": "disabled"}}
    assert "extra_body" not in second


def test_repeated_planner_failure_uses_existing_controlled_fallback():
    fake = FakeClient(["not-json", "still-not-json", "自然回复。"])
    with SessionLocal() as db:
        service = ConversationService(
            db=db,
            llm=DeepSeekLLMClient(client=fake),
            personas=load_personas(),
            stories=load_stories(),
            assets=load_assets(),
        )
        conversation = service.create_conversation("miko_cafe")
        message = service.send_message(conversation.id, "你好")

        assert message.content == "自然回复。"
        log = service.list_turn_logs(conversation.id)[0]
        assert log.planner_output["response_intent"] == service.FALLBACK_INTENT
        assert log.validation_errors == ["planner:malformed_json"]


def test_generator_returns_visible_plain_text():
    fake = FakeClient(["嘿，今天过得怎么样？"])
    reply = DeepSeekLLMClient(client=fake).generate(_generator_context())
    assert reply == "嘿，今天过得怎么样？"
    call = fake.completions.calls[0]
    assert "response_format" not in call
    assert call["extra_body"] == {"thinking": {"type": "disabled"}}
    assert "greeting" not in call["messages"][0]["content"]


def test_generator_leak_guard_remains_active():
    client = DeepSeekLLMClient(client=FakeClient(["[greeting] 继续当前场景。"]))
    with pytest.raises(UnsafeGeneratorOutputError):
        client.generate(_generator_context())


@pytest.mark.parametrize(
    ("error", "expected_code"),
    [
        (StatusError(401), "authentication_failed"),
        (StatusError(402), "insufficient_balance"),
        (StatusError(429), "rate_limited"),
        (APITimeoutError(), "timeout"),
        (APIConnectionError(), "network_error"),
        (StatusError(500), "server_error"),
    ],
)
def test_provider_errors_are_classified_and_sanitized(error, expected_code):
    fake = FakeClient([error, error])
    with pytest.raises(LLMProviderError) as exc_info:
        DeepSeekLLMClient(client=fake).plan(_planner_context())

    assert exc_info.value.code == expected_code
    assert "sensitive upstream detail" not in str(exc_info.value)
