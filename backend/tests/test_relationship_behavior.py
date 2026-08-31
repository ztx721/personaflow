import pytest

from app.config_loader import load_assets, load_personas, load_stories
from app.core.conversation_dynamics import (
    decide_social_action,
    derive_relationship_guidance,
)
from app.core.conversation_service import ConversationService
from app.db import SessionLocal
from app.llm.errors import UnsafeGeneratorOutputError
from app.llm.mock import MockLLMClient
from app.llm.prompts import generator_system_prompt, validate_visible_reply
from app.schemas import (
    ConversationSignals,
    ConversationState,
    EmotionalCue,
    GeneratorContext,
    PersonaConfig,
    PersonaSocialPolicy,
    PlannerOutput,
    RelationshipBand,
    SocialAction,
)


def _state(trust: int, affection: int) -> ConversationState:
    return ConversationState(
        conversation_id="conv",
        role_id="miko_cafe",
        relationship={"trust": trust, "affection": affection, "respect": 20},
    )


@pytest.mark.parametrize(
    ("trust", "affection", "expected"),
    [
        (34, 34, RelationshipBand.low),
        (35, 35, RelationshipBand.medium),
        (69, 69, RelationshipBand.medium),
        (70, 70, RelationshipBand.high),
    ],
)
def test_relationship_band_boundaries(trust, affection, expected):
    assert derive_relationship_guidance(_state(trust, affection)).band is expected


def test_ordinary_answer_remains_valid_at_low_relationship():
    decision = decide_social_action(
        SocialAction.answer,
        ConversationSignals(asks_direct_question=True, asks_personal_question=False),
        [],
        PersonaSocialPolicy(),
        _state(10, 10),
    )

    assert decision.approved is SocialAction.answer
    assert decision.relationship_adjusted is False


def test_private_open_up_is_guarded_low_and_allowed_high():
    signals = ConversationSignals(asks_direct_question=True, asks_personal_question=True)
    low_state = _state(20, 20)
    high_state = _state(80, 80)
    low = decide_social_action(
        SocialAction.open_up, signals, [], PersonaSocialPolicy(), low_state,
        derive_relationship_guidance(low_state),
    )
    high = decide_social_action(
        SocialAction.open_up, signals, [], PersonaSocialPolicy(), high_state,
        derive_relationship_guidance(high_state),
    )

    assert low.approved is SocialAction.avoid
    assert low.relationship_adjusted is True
    assert low.relationship_reason == "private_open_up_suppressed_low_relationship"
    assert high.approved is SocialAction.open_up
    assert high.relationship_adjusted is False


def test_tease_is_restrained_low_and_allowed_high():
    low_state = _state(20, 20)
    high_state = _state(80, 80)
    low = decide_social_action(
        SocialAction.tease, ConversationSignals(), [], PersonaSocialPolicy(), low_state,
        derive_relationship_guidance(low_state),
    )
    high = decide_social_action(
        SocialAction.tease, ConversationSignals(), [], PersonaSocialPolicy(), high_state,
        derive_relationship_guidance(high_state),
    )

    assert low.approved is SocialAction.reply
    assert low.relationship_reason == "teasing_restrained_low_relationship"
    assert high.approved is SocialAction.tease


def test_distress_suppresses_tease_even_at_high_relationship():
    state = _state(90, 90)
    decision = decide_social_action(
        SocialAction.tease,
        ConversationSignals(emotional_cue=EmotionalCue.negative),
        [],
        PersonaSocialPolicy(),
        state,
        derive_relationship_guidance(state),
    )

    assert decision.approved is SocialAction.comfort
    assert decision.reason == "teasing_suppressed_for_distress"


def test_generator_context_receives_compact_relationship_guidance():
    guidance = derive_relationship_guidance(_state(80, 80))
    ctx = GeneratorContext(
        persona=PersonaConfig(role_id="miko_cafe", display_name="Miko"),
        state=_state(80, 80),
        user_message="hello",
        planner=PlannerOutput(),
        relationship_guidance=guidance,
    )
    prompt = generator_system_prompt(ctx)

    assert ctx.relationship_guidance.band is RelationshipBand.high
    assert "<relationship_context>" in prompt
    assert "band: high" in prompt
    assert "trust: 80" not in prompt


@pytest.mark.parametrize(
    "leak",
    ["relationship band is high", "relationship_context says close", "trust score is 80"],
)
def test_visible_reply_rejects_relationship_labels_and_scores(leak):
    ctx = GeneratorContext(
        persona=PersonaConfig(role_id="miko_cafe", display_name="Miko"),
        state=_state(80, 80),
        user_message="hello",
        planner=PlannerOutput(),
    )
    with pytest.raises(UnsafeGeneratorOutputError):
        validate_visible_reply(leak, ctx)


def test_relationship_diagnostics_are_recorded_in_turn_log():
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

        assert diagnostics["relationship_band"] == "low"
        assert diagnostics["relationship_adjusted"] is False
        assert diagnostics["relationship_policy_reason"] is None


def _generator_ctx(action: SocialAction, band: RelationshipBand) -> GeneratorContext:
    value = 80 if band is RelationshipBand.high else 20
    state = _state(value, value)
    return GeneratorContext(
        persona=PersonaConfig(role_id="miko_cafe", display_name="Miko"),
        state=state,
        user_message="你以前谈过几次恋爱？",
        planner=PlannerOutput(social_action=action),
        social_action=action,
        relationship_guidance=derive_relationship_guidance(state),
    )


def test_low_relationship_avoid_contract_forbids_private_fact_disclosure():
    ctx = _generator_ctx(SocialAction.avoid, RelationshipBand.low)
    prompt = generator_system_prompt(ctx)
    visible = validate_visible_reply("你怎么突然问这个。", ctx)

    assert "do not reveal it indirectly" in prompt.casefold()
    assert not any(fact in visible for fact in ("没有谈过", "谈过一次", "谈过两次"))


def test_high_relationship_open_up_still_allows_small_disclosure():
    ctx = _generator_ctx(SocialAction.open_up, RelationshipBand.high)
    visible = validate_visible_reply("谈过一次，不过很久以前了。", ctx)

    assert "谈过一次" in visible
    assert "at most one small personal fact" in generator_system_prompt(ctx)


def test_refuse_and_avoid_keep_distinct_generator_semantics():
    avoid_prompt = generator_system_prompt(
        _generator_ctx(SocialAction.avoid, RelationshipBand.low)
    )
    refuse_prompt = generator_system_prompt(
        _generator_ctx(SocialAction.refuse, RelationshipBand.low)
    )

    assert "Softly dodge" in avoid_prompt
    assert "clear but natural in-character boundary" in refuse_prompt
    assert avoid_prompt != refuse_prompt


def test_ordinary_direct_answer_visible_output_is_unaffected():
    ctx = _generator_ctx(SocialAction.answer, RelationshipBand.low)
    ctx.user_message = "你平时喜欢吃什么？"

    assert validate_visible_reply("我喜欢清淡一点的面。", ctx) == "我喜欢清淡一点的面。"
