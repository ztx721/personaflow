from app.core.rules import apply_emotion, apply_relationship, apply_topic, clamp
from app.schemas import ConversationState, Emotion, EmotionProposal


def _state(**kw) -> ConversationState:
    base = dict(
        conversation_id="c1",
        role_id="miko_cafe",
        emotion=Emotion.neutral,
        emotion_intensity=50,
        relationship={"trust": 20, "affection": 30, "respect": 20},
        current_topic=None,
    )
    base.update(kw)
    return ConversationState(**base)


def test_clamp():
    assert clamp(50, 0, 100) == 50
    assert clamp(-5, 0, 100) == 0
    assert clamp(150, 0, 100) == 100


def test_apply_emotion_damps_intensity_step():
    """强度每轮最多跳 ±20（MAX_INTENSITY_STEP）。"""
    s = _state()
    apply_emotion(s, EmotionProposal(emotion=Emotion.excited, intensity=100))
    assert s.emotion == Emotion.excited
    assert s.emotion_intensity == 70  # 50 + clamp(50, ±20)


def test_apply_emotion_clamps_to_bounds():
    s = _state(emotion=Emotion.excited, emotion_intensity=90)
    apply_emotion(s, EmotionProposal(emotion=Emotion.excited, intensity=100))
    assert s.emotion_intensity == 100


def test_apply_emotion_none_is_noop():
    s = _state()
    apply_emotion(s, None)
    assert s.emotion == Emotion.neutral
    assert s.emotion_intensity == 50


def test_apply_relationship_ignores_unknown_axis():
    """LLM 可能提议未知轴 —— 忽略，不新增轴（防止越权）。"""
    s = _state()
    apply_relationship(s, {"trust": 5, "hacker": 99})
    assert s.relationship["trust"] == 25
    assert "hacker" not in s.relationship


def test_apply_relationship_clamps():
    s = _state(relationship={"trust": 99})
    apply_relationship(s, {"trust": 10})
    assert s.relationship["trust"] == 100


def test_apply_topic_limits_length_and_none():
    s = _state()
    apply_topic(s, "旅行")
    assert s.current_topic == "旅行"
    apply_topic(s, "x" * 65)  # 超长被忽略
    assert s.current_topic == "旅行"
    apply_topic(s, None)  # None 被忽略
    assert s.current_topic == "旅行"
