import pytest

from app.config_loader import load_assets, load_personas, load_stories
from app.core.conversation_dynamics import (
    decide_social_action,
    derive_conversation_signals,
    derive_response_guidance,
)
from app.core.conversation_service import ConversationService
from app.db import SessionLocal
from app.llm.mock import MockLLMClient
from app.llm.errors import UnsafeGeneratorOutputError
from app.llm.prompts import generator_system_prompt, planner_system_prompt, validate_visible_reply
from app.schemas import (
    ChatTurn,
    ConversationSignals,
    ConversationState,
    EmotionalCue,
    GeneratorContext,
    PersonaConfig,
    PersonaSocialPolicy,
    PlannerContext,
    PlannerOutput,
    SocialAction,
    SocialTraitLevel,
    TargetLength,
)


def _state(trust=20, affection=20):
    return ConversationState(
        conversation_id="conv",
        role_id="miko_cafe",
        relationship={"trust": trust, "affection": affection, "respect": 20},
    )


def test_persona_without_social_config_uses_backward_compatible_defaults():
    persona = PersonaConfig(role_id="legacy", display_name="Legacy")

    assert persona.social_behavior.preferred_reply_length == "short"
    assert persona.social_behavior.followup_question_frequency is SocialTraitLevel.medium


def test_miko_social_policy_loads_from_yaml():
    policy = load_personas()["miko_cafe"].social_behavior

    assert policy.warmth is SocialTraitLevel.medium_high
    assert policy.followup_question_frequency is SocialTraitLevel.low
    assert SocialAction.tease in policy.preferred_actions
    assert SocialAction.ask_back in policy.restrained_actions


def test_low_followup_frequency_restrains_ask_back():
    policy = PersonaSocialPolicy(followup_question_frequency=SocialTraitLevel.low)
    decision = decide_social_action(
        SocialAction.ask_back, ConversationSignals(), [], policy, _state()
    )

    assert decision.approved is SocialAction.reply
    assert decision.persona_adjusted is True
    assert decision.reason == "followup_restrained_by_persona"


def test_explicit_boundary_lowers_pressure_and_blocks_new_question():
    signals = derive_conversation_signals("这个我不想回答。", [], _state())
    decision = decide_social_action(
        SocialAction.ask_back, signals, [], PersonaSocialPolicy(), _state()
    )
    guidance = derive_response_guidance(signals, [], _state(), decision.approved)

    assert signals.user_disengagement is True
    assert decision.approved is SocialAction.acknowledge
    assert decision.persona_adjusted is False
    assert decision.reason == "explicit_user_boundary"
    assert guidance.conversational_pressure.value == "low"
    assert guidance.target_length is TargetLength.very_short
    assert guidance.may_ask_question is False


def test_teasing_is_supported_but_suppressed_during_distress():
    policy = PersonaSocialPolicy(teasing=SocialTraitLevel.medium)
    normal = decide_social_action(
        SocialAction.tease, ConversationSignals(), [], policy, _state()
    )
    distressed = decide_social_action(
        SocialAction.tease,
        ConversationSignals(emotional_cue=EmotionalCue.negative),
        [],
        policy,
        _state(),
    )

    assert normal.approved is SocialAction.tease
    assert distressed.approved is SocialAction.comfort
    assert distressed.reason == "teasing_suppressed_for_distress"


def test_low_openness_and_low_relationship_gate_personal_open_up():
    policy = PersonaSocialPolicy(openness=SocialTraitLevel.low)
    signals = ConversationSignals(asks_direct_question=True, asks_personal_question=True)
    decision = decide_social_action(
        SocialAction.open_up, signals, [], policy, _state(trust=10, affection=20)
    )

    assert decision.approved is SocialAction.avoid
    assert decision.reason == "open_up_suppressed_low_openness"


def test_shyness_does_not_override_direct_ordinary_answer():
    policy = PersonaSocialPolicy(shyness=SocialTraitLevel.high, openness=SocialTraitLevel.low)
    signals = ConversationSignals(asks_direct_question=True, asks_personal_question=False)
    decision = decide_social_action(SocialAction.answer, signals, [], policy, _state())

    assert decision.approved is SocialAction.answer


def test_high_warmth_comfort_remains_short():
    policy = PersonaSocialPolicy(warmth=SocialTraitLevel.high)
    signals = ConversationSignals(emotional_cue=EmotionalCue.negative)
    decision = decide_social_action(SocialAction.comfort, signals, [], policy, _state())
    guidance = derive_response_guidance(signals, [], _state(), decision.approved)

    assert decision.approved is SocialAction.comfort
    assert guidance.target_length is TargetLength.short


def test_persona_social_style_is_compact_and_never_visible():
    persona = load_personas()["miko_cafe"]
    planner_ctx = PlannerContext(
        persona=persona, state=_state(), user_message="你好"
    )
    generator_ctx = GeneratorContext(
        persona=persona,
        state=_state(),
        user_message="你好",
        planner=PlannerOutput(),
    )

    assert "<persona_social_style>" in planner_system_prompt(planner_ctx)
    assert "followup_questions: low" in generator_system_prompt(generator_ctx)
    with pytest.raises(UnsafeGeneratorOutputError):
        validate_visible_reply("persona_social_style says warmth=high", generator_ctx)


def test_minimal_ack_and_boundary_visible_replies_stop_after_first_sentence():
    persona = PersonaConfig(role_id="miko_cafe", display_name="Miko")
    for signals in (
        ConversationSignals(minimal_acknowledgement=True),
        ConversationSignals(user_disengagement=True),
    ):
        ctx = GeneratorContext(
            persona=persona,
            state=_state(),
            user_message="嗯",
            planner=PlannerOutput(),
            conversation_signals=signals,
        )
        assert validate_visible_reply("嗯。要不要聊聊别的？", ctx) == "嗯。"


def test_minimal_ack_generator_failure_uses_short_fallback():
    class FailingGenerator(MockLLMClient):
        def generate(self, ctx):
            raise UnsafeGeneratorOutputError()

    with SessionLocal() as db:
        service = ConversationService(
            db=db,
            llm=FailingGenerator(),
            personas=load_personas(),
            stories=load_stories(),
            assets=load_assets(),
        )
        conversation = service.create_conversation("miko_cafe")
        message = service.send_message(conversation.id, "哦")

        assert message.content == "嗯。"
        assert service.list_turn_logs(conversation.id)[0].validation_errors == [
            "generator:unsafe_output"
        ]
