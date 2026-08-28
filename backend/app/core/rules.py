"""规则层：LLM 提议 → 代码裁决。全部纯函数，可单测（architecture.md §5.3 / §14 R2）。"""

from ..schemas import ConversationState, EmotionProposal

MAX_INTENSITY_STEP = 20
MAX_RELATIONSHIP = 100
MAX_TOPIC_LEN = 64


def clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, value))


def apply_emotion(state: ConversationState, proposal: EmotionProposal | None) -> None:
    """情绪：枚举校验（schema 层）+ 强度阻尼（每轮最多跳 ±20）+ 夹取 0-100。"""
    if proposal is None:
        return
    intensity = proposal.intensity
    if state.emotion is not None:
        intensity = state.emotion_intensity + clamp(
            intensity - state.emotion_intensity, -MAX_INTENSITY_STEP, MAX_INTENSITY_STEP
        )
    state.emotion = proposal.emotion
    state.emotion_intensity = clamp(intensity, 0, 100)


def apply_relationship(state: ConversationState, deltas: dict[str, int]) -> None:
    """关系：只作用于已配置的轴，夹取 0-100；未知轴忽略。"""
    for axis, delta in deltas.items():
        if axis in state.relationship:
            state.relationship[axis] = clamp(
                state.relationship.get(axis, 0) + delta, 0, MAX_RELATIONSHIP
            )


def apply_topic(state: ConversationState, topic: str | None) -> None:
    """话题：非空且限长才更新。"""
    if topic and len(topic) <= MAX_TOPIC_LEN:
        state.current_topic = topic
