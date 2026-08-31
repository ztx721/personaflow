import pytest

from app.config_loader import load_assets, load_personas, load_stories
from app.core.conversation_dynamics import (
    derive_conversation_signals,
    derive_response_guidance,
    normalize_social_action,
)
from app.core.conversation_service import ConversationService
from app.db import SessionLocal
from app.llm.mock import MockLLMClient
from app.llm.prompts import generator_system_prompt, validate_visible_reply
from app.llm.errors import UnsafeGeneratorOutputError
from app.schemas import (
    ChatTurn,
    ConversationSignals,
    ConversationState,
    EmotionalCue,
    GeneratorContext,
    PlannerOutput,
    PersonaConfig,
    SocialAction,
    TargetLength,
)


def _state():
    return ConversationState(
        conversation_id="conv",
        role_id="miko_cafe",
        relationship={"trust": 20, "affection": 30, "respect": 20},
    )


def test_social_action_contract_is_backward_compatible_and_complete():
    assert PlannerOutput().social_action is SocialAction.reply
    assert {item.value for item in SocialAction} == {
        "acknowledge", "reply", "short_reply", "answer", "ask_back", "tease",
        "comfort", "avoid", "change_topic", "open_up", "refuse",
    }


def test_minimal_ack_normalizes_ask_back_and_stays_very_short():
    signals = ConversationSignals(minimal_acknowledgement=True)
    action = normalize_social_action(SocialAction.ask_back, signals, [])
    guidance = derive_response_guidance(signals, [], _state(), action)

    assert action is SocialAction.acknowledge
    assert guidance.target_length is TargetLength.very_short
    assert guidance.may_ask_question is False


def test_direct_question_preserves_answer_behavior():
    signals = ConversationSignals(asks_direct_question=True)
    action = normalize_social_action(SocialAction.ask_back, signals, [])
    guidance = derive_response_guidance(signals, [], _state(), action)

    assert action is SocialAction.answer
    assert guidance.answer_before_followup is True


def test_negative_disclosure_supports_short_comfort():
    signals = ConversationSignals(emotional_cue=EmotionalCue.negative)
    guidance = derive_response_guidance(signals, [], _state(), SocialAction.comfort)

    assert guidance.acknowledge_emotion is True
    assert guidance.target_length is TargetLength.short
    assert guidance.may_ask_question is False


def test_topic_shift_and_recent_question_suppress_ask_back():
    recent = [ChatTurn(sender="character", content="Do you want to talk about it?")]
    shifted = ConversationSignals(topic_shift=True)

    assert normalize_social_action(SocialAction.ask_back, shifted, recent) is SocialAction.change_topic
    assert normalize_social_action(
        SocialAction.ask_back, ConversationSignals(), recent
    ) is SocialAction.reply


@pytest.mark.parametrize("action", [SocialAction.tease, SocialAction.open_up, SocialAction.avoid, SocialAction.refuse])
def test_expressive_actions_are_valid_without_state_mutation(action):
    before = _state()
    snapshot = before.model_dump()
    plan = PlannerOutput(social_action=action)

    assert plan.social_action is action
    assert before.model_dump() == snapshot


def test_generator_context_and_prompt_carry_action_as_hidden_behavior():
    ctx = GeneratorContext(
        persona=PersonaConfig(role_id="miko_cafe", display_name="Miko"),
        state=_state(),
        user_message="hello",
        planner=PlannerOutput(social_action=SocialAction.tease),
        social_action=SocialAction.tease,
    )
    prompt = generator_system_prompt(ctx)

    assert ctx.social_action is SocialAction.tease
    assert "<social_behavior>" in prompt
    assert "action: tease" in prompt
    assert "Never name, quote, or explain the action" in prompt


@pytest.mark.parametrize(
    "leak",
    ["social_action=comfort", "My SocialAction is tease", "response guidance says short"],
)
def test_visible_reply_rejects_social_action_and_guidance_leaks(leak):
    ctx = GeneratorContext(
        persona=PersonaConfig(role_id="miko_cafe", display_name="Miko"),
        state=_state(),
        user_message="hello",
        planner=PlannerOutput(),
    )
    with pytest.raises(UnsafeGeneratorOutputError):
        validate_visible_reply(leak, ctx)


def test_visible_reply_removes_leading_action_narration_only():
    ctx = GeneratorContext(
        persona=PersonaConfig(role_id="miko_cafe", display_name="Miko"),
        state=_state(),
        user_message="hello",
        planner=PlannerOutput(),
    )

    assert validate_visible_reply("（她点了点头）好。", ctx) == "好。"


def test_mock_planner_and_turn_log_record_approved_social_action():
    with SessionLocal() as db:
        service = ConversationService(
            db=db,
            llm=MockLLMClient(),
            personas=load_personas(),
            stories=load_stories(),
            assets=load_assets(),
        )
        conversation = service.create_conversation("miko_cafe")
        service.send_message(conversation.id, "嗯")
        log = service.list_turn_logs(conversation.id)[0]

        assert log.planner_output["social_action"] == "acknowledge"
        assert log.applied["conversation_guidance"]["social_action"] == "acknowledge"
        assert log.applied["conversation_guidance"]["social_action_proposed"] == "acknowledge"
        assert log.applied["conversation_guidance"]["social_action_approved"] == "acknowledge"
        assert log.applied["conversation_guidance"]["persona_adjusted"] is False
