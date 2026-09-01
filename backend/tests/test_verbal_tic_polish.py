from app.eval_metrics import analyze_opening_repetition
from app.llm.prompts import generator_system_prompt
from app.schemas import ChatTurn, ConversationState, GeneratorContext, PersonaConfig, PlannerOutput


def context(user_message: str, recent_messages: list[ChatTurn]) -> GeneratorContext:
    return GeneratorContext(
        persona=PersonaConfig(role_id="miko_cafe", display_name="林小满"),
        state=ConversationState(conversation_id="c", role_id="miko_cafe"),
        recent_messages=recent_messages,
        user_message=user_message,
        planner=PlannerOutput(response_intent="自然回应"),
    )


def test_three_identical_filler_openings_are_flagged_and_discouraged():
    replies = ["唔……在看书。", "唔，刚收拾完。", "唔……还好。"]
    metrics = analyze_opening_repetition(replies)
    prompt = generator_system_prompt(context(
        "哦",
        [ChatTurn(sender="character", content=reply) for reply in replies],
    ))

    assert metrics["repeated_opening_count"] == 2
    assert metrics["longest_identical_opening_streak"] == 3
    assert 'openings_to_avoid_this_turn: ["唔"]' in prompt


def test_explicit_feedback_blocks_the_disliked_opening_immediately():
    prompt = generator_system_prompt(context(
        "别老说唔",
        [ChatTurn(sender="character", content="唔……怎么了？")],
    ))

    assert "style_feedback_active: true" in prompt
    assert 'openings_to_avoid_this_turn: ["唔"]' in prompt
    assert "Briefly acknowledge and adjust only" in prompt
    assert "不解释为什么" in prompt


def test_generic_followup_inherits_recent_style_feedback():
    prompt = generator_system_prompt(context(
        "我不喜欢",
        [
            ChatTurn(sender="user", content="你为什么每次都说唔"),
            ChatTurn(sender="character", content="好像还真是。"),
            ChatTurn(sender="user", content="我不喜欢"),
        ],
    ))

    assert "style_feedback_active: true" in prompt
    assert 'openings_to_avoid_this_turn: ["唔"]' in prompt


def test_subsequent_ordinary_reply_silently_keeps_disliked_opening_avoided():
    prompt = generator_system_prompt(context(
        "行",
        [
            ChatTurn(sender="user", content="你为什么每次都说唔"),
            ChatTurn(sender="character", content="好像还真是。"),
            ChatTurn(sender="user", content="我不喜欢"),
            ChatTurn(sender="character", content="好，我注意。"),
            ChatTurn(sender="user", content="行"),
        ],
    ))

    assert "style_feedback_active: false" in prompt
    assert 'openings_to_avoid_this_turn: ["唔"]' in prompt
    assert "remains avoided silently" in prompt


def test_occasional_filler_remains_allowed_without_repetition_or_feedback():
    prompt = generator_system_prompt(context(
        "最近看什么书？",
        [ChatTurn(sender="character", content="唔……一本旧游记。")],
    ))

    assert "style_feedback_active: false" in prompt
    assert "openings_to_avoid_this_turn: []" in prompt


def test_different_openings_do_not_form_an_identical_streak():
    metrics = analyze_opening_repetition(["唔……好。", "嗯，知道了。", "哈哈，是吗。", "晚安。"])

    assert metrics["repeated_opening_count"] == 0
    assert metrics["longest_identical_opening_streak"] == 1
    assert metrics["filler_count"] == 3
    assert metrics["filler_frequency"] == 0.75
