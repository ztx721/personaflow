from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# 领域枚举
# ---------------------------------------------------------------------------

class Emotion(str, Enum):
    neutral = "neutral"
    happy = "happy"
    excited = "excited"
    calm = "calm"
    sad = "sad"
    angry = "angry"
    worried = "worried"
    shy = "shy"
    embarrassed = "embarrassed"
    grateful = "grateful"


# ---------------------------------------------------------------------------
# Persona 配置（config/personas/*.yaml，architecture.md §6）
# ---------------------------------------------------------------------------

class PersonaDetails(BaseModel):
    identity: str = ""
    personality: list[str] = Field(default_factory=list)
    speech_style: str = ""
    likes: list[str] = Field(default_factory=list)
    dislikes: list[str] = Field(default_factory=list)
    goals: list[str] = Field(default_factory=list)
    secrets: list[str] = Field(default_factory=list)


class EmotionInit(BaseModel):
    initial: str = "neutral"
    initial_intensity: int = 50


class RelationshipInit(BaseModel):
    axes: dict[str, int] = Field(
        default_factory=lambda: {"trust": 20, "affection": 30, "respect": 20}
    )


class PersonaConfig(BaseModel):
    role_id: str
    display_name: str
    description: str = ""
    avatar: str | None = None
    persona: PersonaDetails = Field(default_factory=PersonaDetails)
    emotion: EmotionInit = Field(default_factory=EmotionInit)
    relationship: RelationshipInit = Field(default_factory=RelationshipInit)
    default_story: str | None = None


# ---------------------------------------------------------------------------
# Story 配置（config/stories/*.yaml，architecture.md §7）
# ---------------------------------------------------------------------------

class MemorySeed(BaseModel):
    text: str
    fact_type: Literal["user_fact", "character_fact"] = "user_fact"
    importance: int = 3


class OnEnter(BaseModel):
    emit_asset: str | None = None
    record_memory: list[MemorySeed] = Field(default_factory=list)


class Transition(BaseModel):
    to: str
    hint: str = ""              # 给真实 LLM 看的自然语言条件
    reason: str = ""            # 机器可读原因标签，如 USER_PHOTO_REQUEST
    when: list[str] = Field(default_factory=list)  # 关键词：Mock planner 用，保证确定性/Eval
    emit_asset: str | None = None  # 走这条边时发射的素材（如 SEND_PHOTO 的照片）


class StoryNode(BaseModel):
    scene: str = ""
    beat: str = ""
    on_enter: OnEnter | None = None
    transitions: list[Transition] = Field(default_factory=list)


class StoryConfig(BaseModel):
    story_id: str
    title: str = ""
    description: str = ""
    entry_node: str
    trigger: str = "on_first_message"  # "immediate" | "on_first_message"
    nodes: dict[str, StoryNode]


# ---------------------------------------------------------------------------
# LLM 输出契约（architecture.md §10.1，所有结构化输出必须过 Pydantic）
# ---------------------------------------------------------------------------

class EmotionProposal(BaseModel):
    emotion: Emotion
    intensity: int = 50


class MemoryCandidate(BaseModel):
    text: str
    fact_type: Literal["user_fact", "character_fact"] = "user_fact"
    importance: int = 3


class StoryProposal(BaseModel):
    next_node_id: str
    reason: str | None = None


class PlannerOutput(BaseModel):
    """Planner 的输出 = 一份『行为提案』，不是指令（原则 A：LLM 只提议，代码才裁决）。"""

    response_intent: str = ""
    emotion_proposal: EmotionProposal | None = None
    relationship_delta: dict[str, int] = Field(default_factory=dict)
    topic_proposal: str | None = None
    asset_tag: str | None = None  # 只允许 tag，绝不允许 URL
    story_proposal: StoryProposal | None = None
    memory_candidates: list[MemoryCandidate] = Field(default_factory=list)


class Utterance(BaseModel):
    text: str


# ---------------------------------------------------------------------------
# LLM 调用上下文（LLMClient.plan / generate 的输入，provider 无关）
# ---------------------------------------------------------------------------

class ChatTurn(BaseModel):
    sender: str
    content: str


class ConversationState(BaseModel):
    """运行时对话状态（Pydantic 视图，规则在此修改，最后回写 ORM）。architecture.md §5。"""

    conversation_id: str
    role_id: str
    emotion: Emotion | None = None
    emotion_intensity: int = 50
    relationship: dict[str, int] = Field(default_factory=dict)
    current_topic: str | None = None


class StoryContext(BaseModel):
    """给 planner/generator 看的当前剧情快照。"""

    story_id: str
    node_id: str
    scene: str = ""
    beat: str = ""
    transitions: list[Transition] = Field(default_factory=list)
    status: str = "active"


class PlannerContext(BaseModel):
    persona: PersonaConfig
    state: ConversationState
    story: StoryContext | None = None
    memory: list[str] = Field(default_factory=list)
    recent_messages: list[ChatTurn] = Field(default_factory=list)
    user_message: str


class GeneratorContext(BaseModel):
    persona: PersonaConfig
    state: ConversationState
    story: StoryContext | None = None
    recent_messages: list[ChatTurn] = Field(default_factory=list)
    user_message: str
    planner: PlannerOutput
    asset_tag: str | None = None


# ---------------------------------------------------------------------------
# API schemas
# ---------------------------------------------------------------------------

class CreateConversationRequest(BaseModel):
    role_id: str
    story_id: str | None = None


class CreateConversationResponse(BaseModel):
    id: str
    role_id: str
    story_id: str | None = None
    state: dict = Field(default_factory=dict)


class SendMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=2000)


class MessageResponse(BaseModel):
    id: str
    sender: str
    type: Literal["text", "image"] = "text"
    content: str
    asset_url: str | None = None
    created_at: datetime


class RoleSummary(BaseModel):
    role_id: str
    display_name: str
    description: str
    avatar: str | None = None


class DebugTurnLog(BaseModel):
    id: str
    planner_output: dict = Field(default_factory=dict)
    applied: dict = Field(default_factory=dict)
    validation_errors: list[str] = Field(default_factory=list)
    created_at: datetime


class ConversationDebugResponse(BaseModel):
    conversation_id: str
    role: RoleSummary
    state: dict = Field(default_factory=dict)
    story: dict | None = None
    last_turn: DebugTurnLog | None = None
    turn_logs: list[DebugTurnLog] = Field(default_factory=list)
