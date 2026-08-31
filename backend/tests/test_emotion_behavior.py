import pytest

from app.config_loader import load_assets, load_personas, load_stories
from app.core.conversation_dynamics import (
    decide_social_action,
    derive_emotion_guidance,
    derive_relationship_guidance,
    derive_response_guidance,
)
from app.core.conversation_service import ConversationService
from app.db import SessionLocal
from app.llm.errors import UnsafeGeneratorOutputError
from app.llm.mock import MockLLMClient
from app.llm.prompts import generator_system_prompt, planner_system_prompt, validate_visible_reply
from app.schemas import (
    ConversationSignals,
    ConversationState,
    EmotionalCue,
    Emotion,
    EmotionIntensityBand,
    EmotionModifier,
    GeneratorContext,
    PersonaConfig,
    PersonaSocialPolicy,
    PlannerOutput,
    PlannerContext,
    ReplyLengthModifier,
    SocialAction,
    TargetLength,
)


def _state(emotion=Emotion.calm, intensity=50, relationship=80):
    return ConversationState(
        conversation_id="conv",
        role_id="miko_cafe",
        emotion=emotion,
        emotion_intensity=intensity,
        relationship={
            "trust": relationship,
            "affection": relationship,
            "respect": relationship,
        },
    )


@pytest.mark.parametrize(
    ("intensity", "expected"),
    [
        (34, EmotionIntensityBand.low),
        (35, EmotionIntensityBand.medium),
        (69, EmotionIntensityBand.medium),
        (70, EmotionIntensityBand.high),
    ],
)
def test_emotion_intensity_band_boundaries(intensity, expected):
    assert derive_emotion_guidance(_state(intensity=intensity)).intensity_band is expected


def test_calm_preserves_baseline_social_action():
    state = _state(Emotion.calm, 80)
    decision = decide_social_action(
        SocialAction.tease,
        ConversationSignals(),
        [],
        PersonaSocialPolicy(),
        state,
        derive_relationship_guidance(state),
        derive_emotion_guidance(state),
    )

    assert decision.approved is SocialAction.tease
    assert decision.emotion_adjusted is False


def test_happy_playful_context_allows_tease_when_other_policies_allow_it():
    state = _state(Emotion.happy, 80)
    guidance = derive_emotion_guidance(state)
    decision = decide_social_action(
        SocialAction.tease, ConversationSignals(), [], PersonaSocialPolicy(), state,
        derive_relationship_guidance(state), guidance,
    )

    assert guidance.teasing_modifier is EmotionModifier.elevated
    assert decision.approved is SocialAction.tease


def test_user_distress_suppresses_tease_even_when_character_is_happy():
    state = _state(Emotion.happy, 80)
    decision = decide_social_action(
        SocialAction.tease,
        ConversationSignals(emotional_cue=EmotionalCue.negative),
        [],
        PersonaSocialPolicy(),
        state,
        derive_relationship_guidance(state),
        derive_emotion_guidance(state),
    )

    assert decision.approved is SocialAction.comfort
    assert decision.reason == "teasing_suppressed_for_distress"


def test_sad_high_energy_guidance_reduces_initiative_and_length():
    state = _state(Emotion.sad, 80)
    emotion = derive_emotion_guidance(state)
    response = derive_response_guidance(
        ConversationSignals(), [], state, SocialAction.ask_back, emotion
    )

    assert emotion.energy is EmotionModifier.restrained
    assert emotion.initiative_modifier is EmotionModifier.restrained
    assert response.may_ask_question is False
    assert response.target_length is TargetLength.very_short


def test_angry_high_intensity_shortens_reply_action():
    state = _state(Emotion.angry, 85)
    emotion = derive_emotion_guidance(state)
    decision = decide_social_action(
        SocialAction.reply, ConversationSignals(), [], PersonaSocialPolicy(), state,
        derive_relationship_guidance(state), emotion,
    )

    assert emotion.reply_length_modifier is ReplyLengthModifier.shorter
    assert decision.approved is SocialAction.short_reply
    assert decision.emotion_adjusted is True
    assert decision.emotion_reason == "reply_shortened_annoyed"


def test_shy_high_relationship_can_open_up_with_restrained_style():
    state = _state(Emotion.shy, 75, relationship=85)
    emotion = derive_emotion_guidance(state)
    decision = decide_social_action(
        SocialAction.open_up,
        ConversationSignals(asks_direct_question=True, asks_personal_question=True),
        [],
        PersonaSocialPolicy(),
        state,
        derive_relationship_guidance(state),
        emotion,
    )

    assert decision.approved is SocialAction.open_up
    assert emotion.openness_modifier is EmotionModifier.restrained
    assert emotion.reply_length_modifier is ReplyLengthModifier.shorter


def test_shy_low_relationship_remains_guarded_by_relationship():
    state = _state(Emotion.shy, 75, relationship=20)
    decision = decide_social_action(
        SocialAction.open_up,
        ConversationSignals(asks_direct_question=True, asks_personal_question=True),
        [],
        PersonaSocialPolicy(),
        state,
        derive_relationship_guidance(state),
        derive_emotion_guidance(state),
    )

    assert decision.approved is SocialAction.avoid
    assert decision.relationship_adjusted is True


def test_explicit_boundary_overrides_angry_initiative():
    state = _state(Emotion.angry, 90)
    decision = decide_social_action(
        SocialAction.ask_back,
        ConversationSignals(user_disengagement=True),
        [],
        PersonaSocialPolicy(),
        state,
        derive_relationship_guidance(state),
        derive_emotion_guidance(state),
    )

    assert decision.approved is SocialAction.acknowledge
    assert decision.reason == "explicit_user_boundary"


def test_generator_context_receives_compact_emotion_guidance_without_raw_score():
    state = _state(Emotion.shy, 75)
    ctx = GeneratorContext(
        persona=PersonaConfig(role_id="miko_cafe", display_name="Miko"),
        state=state,
        user_message="hello",
        planner=PlannerOutput(),
        emotion_guidance=derive_emotion_guidance(state),
    )
    prompt = generator_system_prompt(ctx)

    assert "<emotion_context>" in prompt
    assert "current: shy" in prompt
    assert "intensity: high" in prompt
    assert "emotion_intensity: 75" not in prompt


@pytest.mark.parametrize(
    "leak",
    ["emotion_context says shy", "emotion=shy", "the intensity band is high", "emotion score 75"],
)
def test_visible_reply_rejects_emotion_policy_labels(leak):
    state = _state(Emotion.shy, 75)
    ctx = GeneratorContext(
        persona=PersonaConfig(role_id="miko_cafe", display_name="Miko"),
        state=state,
        user_message="hello",
        planner=PlannerOutput(),
        emotion_guidance=derive_emotion_guidance(state),
    )
    with pytest.raises(UnsafeGeneratorOutputError):
        validate_visible_reply(leak, ctx)


def test_turn_log_records_compact_emotion_diagnostics():
    with SessionLocal() as db:
        service = ConversationService(
            db=db,
            llm=MockLLMClient(),
            personas=load_personas(),
            stories=load_stories(),
            assets=load_assets(),
        )
        conversation = service.create_conversation("miko_cafe")
        service.send_message(conversation.id, "你好")
        diagnostics = service.list_turn_logs(conversation.id)[0].applied[
            "conversation_guidance"
        ]

        assert diagnostics["emotion_guidance"] == {
            "emotion": "neutral",
            "intensity_band": "medium",
            "energy": "baseline",
            "initiative_modifier": "baseline",
        }
        assert diagnostics["emotion_adjusted_social_action"] is False
        assert diagnostics["emotion_policy_reason"] is None


def test_planner_prompt_requires_gradual_emotion_recovery():
    state = _state(Emotion.angry, 85)
    ctx = PlannerContext(
        persona=PersonaConfig(role_id="miko_cafe", display_name="Miko"),
        state=state,
        user_message="对不起，刚才开玩笑的。",
        emotion_guidance=derive_emotion_guidance(state),
    )
    prompt = planner_system_prompt(ctx)

    assert "soften the current emotion intensity toward baseline" in prompt
    assert "never jump from high anger or sadness to high happiness" in prompt
