from types import SimpleNamespace

import pytest

from app.llm.anthropic import AnthropicLLMClient
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


class FakeMessages:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        output = self.outputs.pop(0)
        if isinstance(output, Exception):
            raise output
        return SimpleNamespace(parsed_output=output)


class FakeClient:
    def __init__(self, outputs):
        self.messages = FakeMessages(outputs)


def _persona() -> PersonaConfig:
    return PersonaConfig(role_id="miko_cafe", display_name="林小满")


def _state() -> ConversationState:
    return ConversationState(
        conversation_id="conv",
        role_id="miko_cafe",
        emotion=Emotion.neutral,
        emotion_intensity=50,
        relationship={"trust": 20, "affection": 30},
    )


def _story() -> StoryContext:
    return StoryContext(
        story_id="travel_photo",
        node_id="greeting",
        scene="安静的旧书店。",
        beat="自然接住用户的话。",
    )


def _planner_context() -> PlannerContext:
    return PlannerContext(
        persona=_persona(),
        state=_state(),
        story=_story(),
        recent_messages=[ChatTurn(sender="user", content="你好")],
        user_message="你好",
    )


def _generator_context() -> GeneratorContext:
    return GeneratorContext(
        persona=_persona(),
        state=_state(),
        story=_story(),
        recent_messages=[ChatTurn(sender="user", content="你好")],
        user_message="你好",
        planner=PlannerOutput(response_intent="自然回应问候"),
    )


def test_real_planner_returns_validated_planner_output():
    fake = FakeClient(
        [
            {
                "response_intent": "自然回应问候",
                "emotion_proposal": {"emotion": "happy", "intensity": 55},
                "relationship_delta": {"trust": 1},
                "topic_proposal": None,
                "asset_tag": None,
                "story_proposal": None,
                "memory_candidates": [],
            }
        ]
    )
    client = AnthropicLLMClient(client=fake, model="test-model")

    result = client.plan(_planner_context())

    assert isinstance(result, PlannerOutput)
    assert result.emotion_proposal is not None
    assert result.emotion_proposal.emotion is Emotion.happy
    assert fake.messages.calls[0]["output_format"] is PlannerOutput


def test_real_planner_rejects_invalid_structured_output():
    fake = FakeClient([{"emotion_proposal": {"emotion": "not-an-emotion"}}])
    client = AnthropicLLMClient(client=fake)

    with pytest.raises(LLMProviderError) as exc_info:
        client.plan(_planner_context())

    assert exc_info.value.code == "invalid_structured_output"


def test_real_generator_returns_only_visible_character_dialogue():
    fake = FakeClient([{"text": "嗨，今天过得怎么样？"}])
    client = AnthropicLLMClient(client=fake)

    reply = client.generate(_generator_context())

    assert reply == "嗨，今天过得怎么样？"
    assert "[greeting]" not in reply
    assert "继续当前场景" not in reply
    system = fake.messages.calls[0]["system"]
    assert "current_node:" not in system
    assert "greeting" not in system


@pytest.mark.parametrize(
    "leaked",
    [
        "[greeting] 你好呀",
        "我会继续当前场景的对话。",
        '{"text":"你好"}',
        "The system prompt tells me to be friendly.",
        "当前剧情节点是 greeting。",
    ],
)
def test_real_generator_rejects_internal_output(leaked):
    client = AnthropicLLMClient(client=FakeClient([{"text": leaked}]))

    with pytest.raises(UnsafeGeneratorOutputError):
        client.generate(_generator_context())


def test_provider_exception_is_sanitized():
    client = AnthropicLLMClient(client=FakeClient([RuntimeError("secret prompt")]))

    with pytest.raises(LLMProviderError) as exc_info:
        client.plan(_planner_context())

    assert exc_info.value.code == "request_failed"
    assert "secret prompt" not in str(exc_info.value)
