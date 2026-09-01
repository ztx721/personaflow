from app.eval_metrics import analyze_visible_reply
from app.llm.prompts import generator_system_prompt
from app.schemas import (
    ConversationSignals, ConversationState, EmotionalCue, GeneratorContext,
    PersonaConfig, PlannerOutput, ResponseGuidance, SocialAction, TargetLength,
)


def context(*, boundary=False):
    return GeneratorContext(
        persona=PersonaConfig(role_id="miko_cafe", display_name="林小满"),
        state=ConversationState(conversation_id="c", role_id="miko_cafe"),
        user_message="今天加班累死了",
        planner=PlannerOutput(response_intent="自然回应"),
        social_action=SocialAction.comfort,
        conversation_signals=ConversationSignals(
            emotional_cue=EmotionalCue.negative,
            user_disengagement=boundary,
        ),
        response_guidance=ResponseGuidance(
            target_length=TargetLength.short,
            may_ask_question=False,
        ),
    )


def test_generator_guidance_rejects_over_complete_support_shape():
    prompt = generator_system_prompt(context())
    assert "at most one or two" in prompt
    assert "do not automatically solve their mood" in prompt
    assert "Do not invent physical co-presence" in prompt
    assert "not proof that the user is physically present" in prompt


def test_boundary_guidance_ends_without_restarting():
    prompt = generator_system_prompt(context(boundary=True))
    assert "After an explicit boundary" in prompt
    assert "Do not replace the" in prompt


def test_soft_metrics_flag_over_complete_unsolicited_support():
    result = analyze_visible_reply(
        "今天加班累死了",
        "辛苦了，你应该早点休息。没关系，会好起来的，要不要聊聊？",
    )
    assert result["over_complete"] is True
    assert result["advice_without_request"] is True


def test_soft_metrics_allow_one_understated_reaction():
    result = analyze_visible_reply("今天加班累死了", "这么累啊。")
    assert result["over_complete"] is False
    assert result["advice_without_request"] is False


def test_soft_metrics_detect_companion_and_boundary_restart():
    assert analyze_visible_reply("今天很烦", "我一直在。")["companion_language"] is True
    assert analyze_visible_reply("今天有点累", "那就在这儿歇会儿吧。")["companion_language"] is True
    assert analyze_visible_reply("你怎么不问", "我就在这儿听着。")["companion_language"] is True
    assert analyze_visible_reply("不提了", "那要不要聊聊别的？")["boundary_restart"] is True
