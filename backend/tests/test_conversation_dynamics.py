from app.config_loader import load_assets, load_personas, load_stories
from app.core.conversation_dynamics import (
    derive_conversation_signals,
    derive_response_guidance,
)
from app.core.conversation_service import ConversationService
from app.db import SessionLocal
from app.llm.mock import MockLLMClient
from app.llm.prompts import generator_system_prompt
from app.schemas import (
    ChatTurn,
    ConversationState,
    EmotionalCue,
    GeneratorContext,
    PersonaConfig,
    PlannerOutput,
    ResponseGuidance,
    TargetLength,
    UserAct,
)


def _state() -> ConversationState:
    return ConversationState(
        conversation_id="conv",
        role_id="miko_cafe",
        relationship={"trust": 20, "affection": 30, "respect": 20},
    )


def _derive(message: str, recent: list[ChatTurn] | None = None):
    recent = recent or []
    signals = derive_conversation_signals(message, recent, _state())
    guidance = derive_response_guidance(signals, recent, _state())
    return signals, guidance


def test_minimal_acknowledgement_stays_very_short_without_question():
    signals, guidance = _derive("嗯")

    assert signals.latest_user_act is UserAct.acknowledgement
    assert signals.minimal_acknowledgement is True
    assert guidance.target_length is TargetLength.very_short
    assert guidance.may_ask_question is False


def test_direct_question_is_answered_before_followup():
    signals, guidance = _derive("你平时看什么书？")

    assert signals.latest_user_act is UserAct.direct_question
    assert signals.asks_direct_question is True
    assert guidance.answer_before_followup is True


def test_clarification_anchors_latest_character_message():
    recent = [
        ChatTurn(sender="character", content="我以前在城里做设计。"),
        ChatTurn(sender="user", content="这样啊。"),
        ChatTurn(sender="character", content="现在守着书店，反而觉得踏实。"),
    ]
    signals, guidance = _derive("你刚才说的是什么意思？", recent)

    assert signals.latest_user_act is UserAct.clarification
    assert signals.asks_for_clarification is True
    assert guidance.continuity_anchor == "现在守着书店，反而觉得踏实。"


def test_explicit_topic_switch_is_followed_directly():
    signals, guidance = _derive("先不聊海边了，说说做饭吧。")

    assert signals.topic_shift is True
    assert signals.latest_user_act is UserAct.topic_switch
    assert guidance.response_mode.value == "direct"


def test_negative_emotion_gets_brief_acknowledgement():
    signals, guidance = _derive("今天上班有点累。")

    assert signals.emotional_cue is EmotionalCue.negative
    assert guidance.acknowledge_emotion is True
    assert guidance.target_length is TargetLength.short
    assert guidance.may_ask_question is False


def test_positive_recovery_replaces_stale_negative_cue():
    recent = [
        ChatTurn(sender="user", content="今天有点难过。"),
        ChatTurn(sender="character", content="嗯，听起来今天不太顺。"),
    ]
    signals, guidance = _derive("不过刚收到好消息，心情好多了。", recent)

    assert signals.emotional_cue is EmotionalCue.recovery
    assert guidance.acknowledge_emotion is True
    assert guidance.target_length is TargetLength.short


def test_recent_character_question_suppresses_another_question():
    recent = [ChatTurn(sender="character", content="你周末有什么打算？")]
    _, guidance = _derive("还没想好。", recent)

    assert guidance.may_ask_question is False
    assert guidance.avoid_repetition is True


def test_repeated_recent_offer_sets_repetition_risk():
    recent = [
        ChatTurn(sender="character", content="要不要我给你推荐一本？"),
        ChatTurn(sender="user", content="我再想想。"),
        ChatTurn(sender="character", content="要不要我给你推荐一本旧书？"),
    ]
    signals, guidance = _derive("好吧。", recent)

    assert signals.repetition_risk is True
    assert guidance.avoid_repetition is True


def test_conversation_guidance_is_recorded_in_turn_log():
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
        guidance = log.applied["conversation_guidance"]
        assert guidance["latest_user_act"] == "acknowledgement"
    assert guidance["target_length"] == "very_short"
    assert guidance["may_ask_question"] is False
    assert guidance["avoid_repetition"] is True


def test_generator_prompt_exposes_typed_guidance_compactly():
    ctx = GeneratorContext(
        persona=PersonaConfig(role_id="miko_cafe", display_name="林小满"),
        state=_state(),
        user_message="嗯",
        planner=PlannerOutput(response_intent="简短回应"),
        response_guidance=ResponseGuidance(
            target_length=TargetLength.very_short,
            may_ask_question=False,
            avoid_repetition=True,
        ),
    )

    prompt = generator_system_prompt(ctx)

    assert "<conversation_guidance>" in prompt
    assert "target_length: very_short" in prompt
    assert "may_ask_question: false" in prompt
    assert "avoid_repetition: true" in prompt
