import pytest

from app.eval_metrics import analyze_visible_reply
from app.llm.prompts import generator_system_prompt
from app.schemas import ChatTurn, ConversationState, GeneratorContext, PersonaConfig, PlannerOutput


def context(user_message: str, recent_messages: list[ChatTurn] | None = None) -> GeneratorContext:
    return GeneratorContext(
        persona=PersonaConfig(role_id="miko_cafe", display_name="林小满"),
        state=ConversationState(conversation_id="c", role_id="miko_cafe"),
        recent_messages=recent_messages or [],
        user_message=user_message,
        planner=PlannerOutput(response_intent="自然回应"),
    )


@pytest.mark.parametrize(
    "feedback",
    ["你说话好像AI", "AI味有点重", "你好像机器人", "说话太生硬了", "说话太官方了", "你怎么像客服", "别这么端着"],
)
def test_meta_style_comments_use_existing_style_feedback_channel(feedback):
    prompt = generator_system_prompt(context(feedback))

    assert "style_feedback_active: true" in prompt
    assert "never imply that an AI identity was discovered" in prompt
    assert "do not apologize like customer support" in prompt


def test_recent_meta_feedback_keeps_following_reply_plain_without_reacknowledging():
    prompt = generator_system_prompt(context(
        "行",
        [
            ChatTurn(sender="user", content="你说话AI味有点重"),
            ChatTurn(sender="character", content="行，我少端着点。"),
            ChatTurn(sender="user", content="行"),
        ],
    ))

    assert "style_feedback_active: false" in prompt
    assert "recent_style_feedback: true" in prompt
    assert "silently use plainer, looser, more direct social wording" in prompt


def test_social_chat_guidance_discourages_service_offer_and_self_summary():
    prompt = generator_system_prompt(context("我喜欢研究你可以吗"))

    assert "avoid service-style offers" in prompt
    assert "Natural replies may simply stop" in prompt


def test_soft_metrics_detect_service_offer_and_unnecessary_self_summary():
    offer = analyze_visible_reply("我喜欢研究你可以吗", "有什么想知道的都可以问我。")
    summary = analyze_visible_reply("你喜欢什么", "我喜欢旧书。总之我就是这样的人。")
    summary_variant = analyze_visible_reply("哦", "唔，其实也就是些琐碎事。")
    direct = analyze_visible_reply("我喜欢研究你可以吗", "你想研究啥？")

    assert offer["assistant_offer"] is True
    assert summary["self_summary"] is True
    assert summary_variant["self_summary"] is True
    assert direct["assistant_offer"] is False
    assert direct["self_summary"] is False
