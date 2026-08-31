import pytest
from fastapi.testclient import TestClient

from app.config_loader import load_stories
from app.core.story_engine import StoryEngine
from app.core.story_pressure import normalize_story_pressure
from app.llm.errors import UnsafeGeneratorOutputError
from app.llm.prompts import generator_system_prompt, validate_visible_reply
from app.main import app
from app.models import StoryState as StoryStateORM
from app.schemas import (
    ConversationSignals,
    ConversationState,
    EmotionalCue,
    EmotionGuidance,
    GeneratorContext,
    OpenThread,
    PersonaConfig,
    PlannerOutput,
    SocialAction,
    StoryContext,
    StoryOpportunity,
    StoryPressure,
    Transition,
)


WEEKEND = Transition(
    to="weekend",
    hint="用户自然提到周末安排",
    reason="USER_WEEKEND",
    when=["周末", "放假"],
)


def decision(
    *,
    proposed=StoryPressure.opportunistic,
    signals=None,
    action=SocialAction.reply,
    threads=None,
    resumed=None,
    message="周末终于能休息了",
    transition=WEEKEND,
    active=True,
):
    return normalize_story_pressure(
        proposed,
        signals or ConversationSignals(),
        action,
        EmotionGuidance(),
        threads or [],
        resumed,
        message,
        transition,
        active,
    )


def open_thread():
    return OpenThread(
        id="thread_1_1",
        topic="老板冲突",
        summary="用户和老板的冲突还没说完",
        created_turn=1,
        last_touched_turn=1,
        priority=4,
    )


def test_negative_emotional_disclosure_suppresses_story_pressure():
    result = decision(
        signals=ConversationSignals(emotional_cue=EmotionalCue.negative),
        action=SocialAction.comfort,
    )
    assert result.approved is StoryPressure.none
    assert result.reason == "suppressed_emotional_priority"


def test_explicit_boundary_suppresses_story_pressure():
    result = decision(signals=ConversationSignals(user_disengagement=True))
    assert result.approved is StoryPressure.none
    assert result.reason == "suppressed_user_boundary"


def test_immediate_clarification_suppresses_story_pressure():
    result = decision(signals=ConversationSignals(asks_for_clarification=True))
    assert result.reason == "suppressed_clarification"


def test_unrelated_direct_question_does_not_lose_turn_to_story():
    result = decision(
        signals=ConversationSignals(asks_direct_question=True),
        message="你会做什么菜",
    )
    assert not result.opportunity.eligible
    assert result.reason == "suppressed_direct_question"


def test_natural_weekend_mention_approves_opportunistic_pressure():
    result = decision(message="周末终于能休息了")
    assert result.approved is StoryPressure.opportunistic
    assert result.opportunity.natural_trigger == "周末"


def test_strong_proposal_is_capped_for_exact_natural_match():
    result = decision(proposed=StoryPressure.strong, message="周末想出去走走")
    assert result.approved is StoryPressure.opportunistic
    assert result.adjusted is True


def test_active_open_thread_blocks_unrelated_story_pressure():
    result = decision(threads=[open_thread()], message="今天做了红烧肉")
    assert result.reason == "suppressed_active_open_thread"


def test_resolved_thread_does_not_block_natural_story_progress():
    item = open_thread()
    item.status = "resolved"
    result = decision(threads=[], message="周末想出去走走")
    assert result.opportunity.eligible


def test_open_thread_callback_has_priority_over_story():
    item = open_thread()
    result = decision(threads=[item], resumed=item, message="周末也不想说")
    assert result.reason == "suppressed_open_thread_callback"


def test_invalid_transition_still_rejected_by_unchanged_story_engine():
    story = load_stories()["travel_photo"]
    state = StoryStateORM(
        conversation_id="c",
        story_id=story.story_id,
        current_node_id="greeting",
        visited=["greeting"],
        status="active",
    )
    assert StoryEngine({story.story_id: story}).match_transition(
        story, state, "photo_sent"
    ) is None


def generator_context(opportunity: StoryOpportunity):
    return GeneratorContext(
        persona=PersonaConfig(role_id="r", display_name="角色"),
        state=ConversationState(conversation_id="c", role_id="r"),
        story=StoryContext(
            story_id="travel_photo",
            node_id="secret_node_id",
            scene="internal scene",
            beat="internal beat",
        ),
        user_message="周末想休息",
        planner=PlannerOutput(response_intent="自然回应"),
        story_opportunity=opportunity,
    )


def test_generator_prompt_never_contains_story_node_id_or_pressure_number():
    ctx = generator_context(StoryOpportunity(
        eligible=True,
        pressure=StoryPressure.opportunistic,
        candidate_transition="可以自然聊到周末安排",
    ))
    prompt = generator_system_prompt(ctx)
    assert "secret_node_id" not in prompt
    assert "story_pressure" not in prompt
    assert "internal beat" not in prompt


def test_story_pressure_internal_label_is_rejected_from_visible_reply():
    ctx = generator_context(StoryOpportunity())
    with pytest.raises(UnsafeGeneratorOutputError):
        validate_visible_reply("story_pressure is 1", ctx)


def test_story_can_pause_for_unrelated_turns_then_resume_naturally():
    with TestClient(app) as client:
        cid = client.post("/api/conversations", json={"role_id": "miko_cafe"}).json()["id"]
        for message in ["你好", "你会做什么菜", "最近读什么书"]:
            response = client.post(
                f"/api/conversations/{cid}/messages", json={"content": message}
            )
            assert response.status_code == 200
        paused = client.get(f"/api/conversations/{cid}/debug").json()
        assert paused["story"]["current_node_id"] == "greeting"

        client.post(
            f"/api/conversations/{cid}/messages", json={"content": "今天终于忙完了"}
        )
        resumed = client.get(f"/api/conversations/{cid}/debug").json()
        assert resumed["story"]["current_node_id"] == "rapport"
        guidance = resumed["last_turn"]["applied"]["conversation_guidance"]
        assert guidance["story_pressure_approved"] == 1
        assert guidance["story_transition_applied"] is True
