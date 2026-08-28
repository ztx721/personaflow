"""确定性 Mock LLM：离线开发 / 测试 / Eval 用。

用关键词规则替代真实模型的判断，保证任何输入下输出都是确定的：
- 剧情迁移：匹配当前节点 transitions[].when 关键词
- 情绪：匹配正向/负向/兴奋关键词
- 话题：匹配话题关键词
- 关系：每轮小幅升温
"""

from ..schemas import (
    Emotion,
    EmotionProposal,
    GeneratorContext,
    PlannerContext,
    PlannerOutput,
    StoryProposal,
)
from .client import LLMClient

EXCITED = ["给我看看", "看看", "照片", "哇"]
POSITIVE = ["开心", "哈哈", "不错", "棒", "喜欢", "太好了", "谢谢"]
NEGATIVE = ["难过", "伤心", "烦", "气", "讨厌", "累"]

TOPICS = [
    ("weekend", ["周末", "放假", "假期"]),
    ("travel", ["旅行", "旅游", "海边", "海"]),
    ("books", ["书", "书店"]),
    ("photos", ["照片", "拍"]),
]


class MockLLMClient(LLMClient):
    def plan(self, ctx: PlannerContext) -> PlannerOutput:
        text = ctx.user_message
        proposal = self._detect_transition(ctx)
        return PlannerOutput(
            response_intent=self._intent(ctx, proposal),
            emotion_proposal=self._detect_emotion(text),
            relationship_delta={axis: 1 for axis in ctx.state.relationship},
            topic_proposal=self._detect_topic(text),
            story_proposal=proposal,
            memory_candidates=[],
        )

    def generate(self, ctx: GeneratorContext) -> str:
        node_id = ctx.story.node_id if ctx.story else "chat"
        return f"[{node_id}] {ctx.planner.response_intent}"

    # ------------------------------------------------------------------
    # 确定性规则（都是纯函数式判断，可单测）
    # ------------------------------------------------------------------

    def _detect_emotion(self, text: str) -> EmotionProposal:
        if any(k in text for k in EXCITED):
            return EmotionProposal(emotion=Emotion.excited, intensity=70)
        if any(k in text for k in POSITIVE):
            return EmotionProposal(emotion=Emotion.happy, intensity=65)
        if any(k in text for k in NEGATIVE):
            return EmotionProposal(emotion=Emotion.worried, intensity=45)
        return EmotionProposal(emotion=Emotion.neutral, intensity=50)

    def _detect_topic(self, text: str) -> str | None:
        for topic, keywords in TOPICS:
            if any(k in text for k in keywords):
                return topic
        return None

    def _detect_transition(self, ctx: PlannerContext) -> StoryProposal | None:
        if ctx.story is None:
            return None
        for t in ctx.story.transitions:
            if any(kw and kw in ctx.user_message for kw in t.when):
                return StoryProposal(next_node_id=t.to, reason=t.reason)
        return None

    def _intent(self, ctx: PlannerContext, proposal: StoryProposal | None) -> str:
        if proposal is not None:
            return f"把话题自然引向「{proposal.next_node_id}」"
        if ctx.story is not None:
            return f"保持在「{ctx.story.node_id}」，继续当前场景的对话"
        return "自然地与顾客闲聊"
