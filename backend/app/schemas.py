from datetime import datetime
from enum import Enum, IntEnum
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


class SocialAction(str, Enum):
    acknowledge = "acknowledge"
    reply = "reply"
    short_reply = "short_reply"
    answer = "answer"
    ask_back = "ask_back"
    tease = "tease"
    comfort = "comfort"
    avoid = "avoid"
    change_topic = "change_topic"
    open_up = "open_up"
    refuse = "refuse"


class PhotoAction(str, Enum):
    none = "none"
    offer = "offer"
    send = "send"
    delay = "delay"
    refuse = "refuse"


class PhotoCategory(str, Enum):
    public_object = "public_object"
    book = "book"
    bookstore = "bookstore"
    coffee = "coffee"
    cat = "cat"
    food = "food"
    travel = "travel"
    personal = "personal"
    selfie = "selfie"
    other = "other"


class PhotoCategoryPolicy(BaseModel):
    min_relationship: Literal["low", "medium", "high"] = "medium"
    default_action: PhotoAction = PhotoAction.delay


class PersonaPhotoPolicy(BaseModel):
    willingness: Literal["guarded", "moderate", "open"] = "guarded"
    categories: dict[PhotoCategory, PhotoCategoryPolicy] = Field(default_factory=dict)
    stranger_request: PhotoAction = PhotoAction.delay
    familiar_request: PhotoAction = PhotoAction.delay
    close_request: PhotoAction = PhotoAction.send
    story_offer_action: PhotoAction = PhotoAction.send


class PhotoPolicyDecision(BaseModel):
    proposed: PhotoAction = PhotoAction.none
    approved: PhotoAction = PhotoAction.none
    category: PhotoCategory = PhotoCategory.other
    adjusted: bool = False
    reason: str = "no_photo_request"
    asset_candidate: str | None = None
    asset_sent: bool = False


class SocialTraitLevel(str, Enum):
    low = "low"
    medium_low = "medium_low"
    medium = "medium"
    medium_high = "medium_high"
    high = "high"


class PersonaSocialPolicy(BaseModel):
    preferred_reply_length: Literal["very_short", "short", "normal"] = "short"
    initiative: SocialTraitLevel = SocialTraitLevel.medium
    warmth: SocialTraitLevel = SocialTraitLevel.medium
    teasing: SocialTraitLevel = SocialTraitLevel.medium
    shyness: SocialTraitLevel = SocialTraitLevel.medium
    directness: SocialTraitLevel = SocialTraitLevel.medium
    openness: SocialTraitLevel = SocialTraitLevel.medium
    patience: SocialTraitLevel = SocialTraitLevel.medium
    followup_question_frequency: SocialTraitLevel = SocialTraitLevel.medium
    preferred_actions: list[SocialAction] = Field(default_factory=list)
    restrained_actions: list[SocialAction] = Field(default_factory=list)
    habits: list[str] = Field(default_factory=list)
    avoids: list[str] = Field(default_factory=list)


class PersonaConfig(BaseModel):
    role_id: str
    display_name: str
    description: str = ""
    avatar: str | None = None
    persona: PersonaDetails = Field(default_factory=PersonaDetails)
    emotion: EmotionInit = Field(default_factory=EmotionInit)
    relationship: RelationshipInit = Field(default_factory=RelationshipInit)
    social_behavior: PersonaSocialPolicy = Field(default_factory=PersonaSocialPolicy)
    photo_policy: PersonaPhotoPolicy = Field(default_factory=PersonaPhotoPolicy)
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
    canonical_facts: list[str] = Field(default_factory=list)
    nodes: dict[str, StoryNode]


class AssetSpec(BaseModel):
    """可信素材条目（config/assets/catalog.yaml）。语义元数据供会话驱动素材选择。

    story_locked: true 表示该素材只能由剧情 transition.emit_asset 发出
    （如 beach_photo 必须等剧情推进到 photo_sent），会话驱动选择会跳过它。
    """

    id: str
    role_id: str
    url: str
    type: str = "image"
    tags: list[str] = Field(default_factory=list)
    description: str = ""
    topics: list[str] = Field(default_factory=list)
    story_locked: bool = False


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


class StoryPressure(IntEnum):
    none = 0
    opportunistic = 1
    active = 2
    strong = 3


class StoryOpportunity(BaseModel):
    eligible: bool = False
    pressure: StoryPressure = StoryPressure.none
    natural_trigger: str | None = None
    blocked_reason: str | None = None
    candidate_transition: str | None = None


class StoryPressureDecision(BaseModel):
    proposed: StoryPressure = StoryPressure.none
    approved: StoryPressure = StoryPressure.none
    adjusted: bool = False
    reason: str = "no_story_opportunity"
    opportunity: StoryOpportunity = Field(default_factory=StoryOpportunity)


class OpenThreadStatus(str, Enum):
    open = "open"
    resolved = "resolved"


class OpenThreadOwner(str, Enum):
    user = "user"
    character = "character"
    shared = "shared"


class ThreadUpdateAction(str, Enum):
    open = "open"
    touch = "touch"
    resolve = "resolve"


class OpenThread(BaseModel):
    id: str
    topic: str
    summary: str
    owner: OpenThreadOwner = OpenThreadOwner.user
    created_turn: int
    last_touched_turn: int
    priority: int = Field(default=3, ge=1, le=5)
    status: OpenThreadStatus = OpenThreadStatus.open


class ThreadUpdate(BaseModel):
    """Planner proposal; the application owns IDs and the persisted list."""

    action: ThreadUpdateAction
    thread_id: str | None = None
    topic: str = ""
    summary: str = ""
    owner: OpenThreadOwner = OpenThreadOwner.user
    priority: int = Field(default=3, ge=1, le=5)


class AssetRequest(BaseModel):
    """Planner 对『会话驱动的素材』的提议。只含语义 tags，绝不允许 URL/路径/资产 id。

    应用侧（AssetService.find_best）负责在 trusted catalog 内解析真正的素材，
    找不到足够相关的素材时不会发送任何图片（原则：LLM 提议 → 应用裁决）。
    """

    requested: bool = False
    tags: list[str] = Field(default_factory=list)


class PlannerOutput(BaseModel):
    """Planner 的输出 = 一份『行为提案』，不是指令（原则 A：LLM 只提议，代码才裁决）。"""

    response_intent: str = ""
    social_action: SocialAction = SocialAction.reply
    emotion_proposal: EmotionProposal | None = None
    relationship_delta: dict[str, int] = Field(default_factory=dict)
    topic_proposal: str | None = None
    asset_tag: str | None = None  # 只允许 tag，绝不允许 URL
    story_proposal: StoryProposal | None = None
    memory_candidates: list[MemoryCandidate] = Field(default_factory=list)
    asset_request: AssetRequest = Field(default_factory=AssetRequest)
    thread_updates: list[ThreadUpdate] = Field(default_factory=list)
    resume_thread_id: str | None = None
    story_pressure: StoryPressure = StoryPressure.none
    photo_action: PhotoAction = PhotoAction.none
    photo_category: PhotoCategory = PhotoCategory.other


class Utterance(BaseModel):
    text: str


# ---------------------------------------------------------------------------
# LLM 调用上下文（LLMClient.plan / generate 的输入，provider 无关）
# ---------------------------------------------------------------------------

class UserAct(str, Enum):
    statement = "statement"
    direct_question = "direct_question"
    clarification = "clarification"
    acknowledgement = "acknowledgement"
    emotional_disclosure = "emotional_disclosure"
    topic_switch = "topic_switch"
    image_request = "image_request"
    other = "other"


class EmotionalCue(str, Enum):
    none = "none"
    negative = "negative"
    positive = "positive"
    recovery = "recovery"


class ResponseMode(str, Enum):
    brief = "brief"
    normal = "normal"
    direct = "direct"
    clarify = "clarify"
    supportive = "supportive"


class TargetLength(str, Enum):
    very_short = "very_short"
    short = "short"
    normal = "normal"


class FollowupPreference(str, Enum):
    none = "none"
    optional = "optional"
    useful_only = "useful_only"


class ConversationSignals(BaseModel):
    latest_user_act: UserAct = UserAct.statement
    emotional_cue: EmotionalCue = EmotionalCue.none
    topic_shift: bool = False
    asks_direct_question: bool = False
    asks_for_clarification: bool = False
    references_previous_turn: bool = False
    minimal_acknowledgement: bool = False
    user_requests_detail: bool = False
    repetition_risk: bool = False
    user_disengagement: bool = False
    asks_personal_question: bool = False


class ConversationalPressure(str, Enum):
    low = "low"
    normal = "normal"


class ResponseGuidance(BaseModel):
    response_mode: ResponseMode = ResponseMode.normal
    target_length: TargetLength = TargetLength.short
    acknowledge_emotion: bool = False
    answer_before_followup: bool = False
    may_ask_question: bool = False
    followup_preference: FollowupPreference = FollowupPreference.useful_only
    continuity_anchor: str | None = None
    avoid_repetition: bool = False
    conversational_pressure: ConversationalPressure = ConversationalPressure.normal


class SocialActionDecision(BaseModel):
    proposed: SocialAction
    approved: SocialAction
    persona_adjusted: bool = False
    reason: str | None = None
    relationship_adjusted: bool = False
    relationship_reason: str | None = None
    emotion_adjusted: bool = False
    emotion_reason: str | None = None


class RelationshipBand(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class DisclosurePermission(str, Enum):
    guarded = "guarded"
    moderate = "moderate"
    open = "open"


class TeasingPermission(str, Enum):
    restrained = "restrained"
    normal = "normal"
    relaxed = "relaxed"


class ConversationalWarmth(str, Enum):
    reserved = "reserved"
    warm = "warm"
    close = "close"


class RelationshipGuidance(BaseModel):
    band: RelationshipBand = RelationshipBand.low
    disclosure_permission: DisclosurePermission = DisclosurePermission.guarded
    teasing_permission: TeasingPermission = TeasingPermission.restrained
    conversational_warmth: ConversationalWarmth = ConversationalWarmth.reserved
    shorthand_preference: bool = False
    personal_question_tolerance: RelationshipBand = RelationshipBand.low


class EmotionIntensityBand(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class EmotionModifier(str, Enum):
    restrained = "restrained"
    baseline = "baseline"
    elevated = "elevated"


class ReplyLengthModifier(str, Enum):
    shorter = "shorter"
    baseline = "baseline"


class EmotionGuidance(BaseModel):
    emotion: Emotion = Emotion.neutral
    intensity_band: EmotionIntensityBand = EmotionIntensityBand.medium
    energy: EmotionModifier = EmotionModifier.baseline
    warmth_modifier: EmotionModifier = EmotionModifier.baseline
    reply_length_modifier: ReplyLengthModifier = ReplyLengthModifier.baseline
    teasing_modifier: EmotionModifier = EmotionModifier.baseline
    openness_modifier: EmotionModifier = EmotionModifier.baseline
    initiative_modifier: EmotionModifier = EmotionModifier.baseline


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
    open_threads: list[OpenThread] = Field(default_factory=list)


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
    conversation_signals: ConversationSignals = Field(default_factory=ConversationSignals)
    relationship_guidance: RelationshipGuidance = Field(default_factory=RelationshipGuidance)
    emotion_guidance: EmotionGuidance = Field(default_factory=EmotionGuidance)
    open_threads: list[OpenThread] = Field(default_factory=list)


class GeneratorContext(BaseModel):
    persona: PersonaConfig
    state: ConversationState
    story: StoryContext | None = None
    recent_messages: list[ChatTurn] = Field(default_factory=list)
    user_message: str
    planner: PlannerOutput
    asset_tag: str | None = None
    conversation_signals: ConversationSignals = Field(default_factory=ConversationSignals)
    response_guidance: ResponseGuidance = Field(default_factory=ResponseGuidance)
    social_action: SocialAction = SocialAction.reply
    relationship_guidance: RelationshipGuidance = Field(default_factory=RelationshipGuidance)
    emotion_guidance: EmotionGuidance = Field(default_factory=EmotionGuidance)
    open_threads: list[OpenThread] = Field(default_factory=list)
    resumed_thread: OpenThread | None = None
    story_opportunity: StoryOpportunity = Field(default_factory=StoryOpportunity)
    photo_action: PhotoAction = PhotoAction.none
    photo_category: PhotoCategory = PhotoCategory.other
    asset_attached: bool = False
    story_photo_available: bool = False
    canonical_story_facts: list[str] = Field(default_factory=list)


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
