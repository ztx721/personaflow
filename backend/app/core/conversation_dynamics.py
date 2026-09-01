"""Pure deterministic turn guidance for Human-like Conversation V2 Phase 1."""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from ..schemas import (
    ChatTurn,
    ConversationSignals,
    ConversationState,
    ConversationalPressure,
    ConversationalWarmth,
    DisclosurePermission,
    Emotion,
    EmotionGuidance,
    EmotionIntensityBand,
    EmotionModifier,
    EmotionalCue,
    FollowupPreference,
    PersonaSocialPolicy,
    ResponseGuidance,
    ResponseMode,
    RelationshipBand,
    RelationshipGuidance,
    ReplyLengthModifier,
    SocialAction,
    SocialActionDecision,
    SocialTraitLevel,
    TargetLength,
    TeasingPermission,
    UserAct,
)


_MINIMAL_ACKS = {
    "嗯", "嗯嗯", "哦", "噢", "啊", "好", "好的", "好吧", "行", "这样啊",
    "知道了", "明白了", "哈哈", "谢谢", "谢啦",
}
_CLARIFICATION_MARKERS = ("什么意思", "你刚才说", "刚才那句", "刚才的话", "没听懂")
_TOPIC_SWITCH_MARKERS = (
    "换个话题", "说点别的", "聊点别的", "先不聊", "不说这个了", "说到别的",
    "对了", "话说回来", "突然想聊",
)
_IMAGE_REQUEST_MARKERS = (
    "给我看看", "让我看看", "发我看看", "发张图", "发图片", "发照片",
    "给张照片", "给个图", "长什么样",
)
_PERSONAL_IMAGE_REQUEST_MARKERS = (
    "你自己的照片呢", "发张你的看看", "你的照片呢", "给我看看你的",
    "发张你自己的", "你的自拍", "发张自拍",
)
_AMBIGUOUS_IMAGE_REQUEST_MARKERS = ("你的呢",)
_PHOTO_CONTEXT_MARKERS = ("照片", "图片", "自拍", "拍照", "发张", "给我看看")
_NEGATIVE_MARKERS = (
    "难过", "伤心", "不开心", "烦", "焦虑", "害怕", "压力", "糟糕", "委屈",
    "生气", "失落", "崩溃", "累死", "有点累", "好累", "很累", "累了", "疲惫",
    "不顺", "低落",
)
_POSITIVE_MARKERS = (
    "开心", "高兴", "好多了", "好消息", "太好了", "不错", "喜欢", "谢谢", "哈哈",
)
_RECOVERY_MARKERS = ("好多了", "好一点了", "没事了", "心情好多了", "现在好了")
_REFERENCE_MARKERS = ("刚才", "刚刚", "那句话", "你说的", "这个", "那个", "前面")
_DETAIL_MARKERS = ("详细", "展开说", "多说", "具体", "为什么", "怎么回事", "然后呢")
_QUESTION_WORDS = ("吗", "呢", "什么", "为什么", "怎么", "哪", "谁", "多少", "是不是")
_OFFER_MARKERS = ("要不要", "我可以", "可以给你", "愿意的话", "想不想", "给你推荐")

_DISENGAGEMENT_MARKERS = (
    "不想回答", "不想说", "算了", "别问了", "不聊了", "先不说", "可以不回答",
)
_PERSONAL_QUESTION_MARKERS = (
    "小时候", "感情", "前任", "恋爱", "谈过", "秘密", "收入", "工资", "家里",
    "住哪", "电话", "联系方式", "私密", "隐私", "私人照片", "为什么这么安静",
)

RELATIONSHIP_MEDIUM_THRESHOLD = 35
RELATIONSHIP_HIGH_THRESHOLD = 70
EMOTION_MEDIUM_THRESHOLD = 35
EMOTION_HIGH_THRESHOLD = 70


def derive_relationship_guidance(state: ConversationState) -> RelationshipGuidance:
    """Derive request-time behavior context without adding persisted state."""
    trust = state.relationship.get("trust", 0)
    affection = state.relationship.get("affection", 0)
    score = (trust + affection) / 2
    if score >= RELATIONSHIP_HIGH_THRESHOLD:
        return RelationshipGuidance(
            band=RelationshipBand.high,
            disclosure_permission=DisclosurePermission.open,
            teasing_permission=TeasingPermission.relaxed,
            conversational_warmth=ConversationalWarmth.close,
            shorthand_preference=True,
            personal_question_tolerance=RelationshipBand.high,
        )
    if score >= RELATIONSHIP_MEDIUM_THRESHOLD:
        return RelationshipGuidance(
            band=RelationshipBand.medium,
            disclosure_permission=DisclosurePermission.moderate,
            teasing_permission=TeasingPermission.normal,
            conversational_warmth=ConversationalWarmth.warm,
            shorthand_preference=True,
            personal_question_tolerance=RelationshipBand.medium,
        )
    return RelationshipGuidance()


def derive_emotion_guidance(state: ConversationState) -> EmotionGuidance:
    """Translate the persisted mood into compact, non-persisted behavior guidance."""
    emotion = state.emotion or Emotion.neutral
    intensity = state.emotion_intensity
    if intensity >= EMOTION_HIGH_THRESHOLD:
        band = EmotionIntensityBand.high
    elif intensity >= EMOTION_MEDIUM_THRESHOLD:
        band = EmotionIntensityBand.medium
    else:
        band = EmotionIntensityBand.low

    guidance = EmotionGuidance(emotion=emotion, intensity_band=band)
    if band is EmotionIntensityBand.low:
        return guidance
    if emotion in {Emotion.happy, Emotion.excited, Emotion.grateful}:
        guidance.energy = EmotionModifier.elevated
        guidance.warmth_modifier = EmotionModifier.elevated
        guidance.teasing_modifier = EmotionModifier.elevated
        guidance.initiative_modifier = EmotionModifier.elevated
    elif emotion in {Emotion.sad, Emotion.worried}:
        guidance.energy = EmotionModifier.restrained
        guidance.reply_length_modifier = ReplyLengthModifier.shorter
        guidance.teasing_modifier = EmotionModifier.restrained
        guidance.openness_modifier = EmotionModifier.restrained
        guidance.initiative_modifier = EmotionModifier.restrained
    elif emotion in {Emotion.shy, Emotion.embarrassed}:
        guidance.energy = EmotionModifier.restrained
        guidance.reply_length_modifier = ReplyLengthModifier.shorter
        guidance.teasing_modifier = EmotionModifier.restrained
        guidance.openness_modifier = EmotionModifier.restrained
        guidance.initiative_modifier = EmotionModifier.restrained
    elif emotion is Emotion.angry:
        guidance.warmth_modifier = EmotionModifier.restrained
        guidance.reply_length_modifier = ReplyLengthModifier.shorter
        guidance.teasing_modifier = EmotionModifier.restrained
        guidance.openness_modifier = EmotionModifier.restrained
        guidance.initiative_modifier = EmotionModifier.restrained
    return guidance


def derive_conversation_signals(
    user_message: str,
    recent_messages: list[ChatTurn],
    state: ConversationState,
) -> ConversationSignals:
    """Classify the latest conversational move using conservative heuristics."""
    del state  # accepted as read-only context; Phase 1 needs no additional state rule
    text = user_message.strip()
    normalized = _normalize_short(text)
    minimal = normalized in _MINIMAL_ACKS
    clarification = any(marker in text for marker in _CLARIFICATION_MARKERS)
    topic_shift = any(marker in text for marker in _TOPIC_SWITCH_MARKERS)
    image_request = (
        any(marker in text for marker in _IMAGE_REQUEST_MARKERS)
        or any(marker in text for marker in _PERSONAL_IMAGE_REQUEST_MARKERS)
        or (
            any(marker in text for marker in _AMBIGUOUS_IMAGE_REQUEST_MARKERS)
            and _recent_has_photo_context(recent_messages)
        )
    )
    direct_question = _is_question(text)
    negative = any(marker in text for marker in _NEGATIVE_MARKERS)
    positive = any(marker in text for marker in _POSITIVE_MARKERS)
    prior_negative = _recent_user_had_negative_cue(recent_messages)
    disengagement = any(marker in text for marker in _DISENGAGEMENT_MARKERS)

    if any(marker in text for marker in _RECOVERY_MARKERS) and prior_negative:
        emotional_cue = EmotionalCue.recovery
    elif negative:
        emotional_cue = EmotionalCue.negative
    elif positive:
        emotional_cue = EmotionalCue.positive
    else:
        emotional_cue = EmotionalCue.none

    if clarification:
        act = UserAct.clarification
    elif image_request:
        act = UserAct.image_request
    elif minimal:
        act = UserAct.acknowledgement
    elif topic_shift:
        act = UserAct.topic_switch
    elif negative or emotional_cue is EmotionalCue.recovery:
        act = UserAct.emotional_disclosure
    elif direct_question:
        act = UserAct.direct_question
    elif text:
        act = UserAct.statement
    else:
        act = UserAct.other

    return ConversationSignals(
        latest_user_act=act,
        emotional_cue=emotional_cue,
        topic_shift=topic_shift,
        asks_direct_question=direct_question,
        asks_for_clarification=clarification,
        references_previous_turn=any(marker in text for marker in _REFERENCE_MARKERS),
        minimal_acknowledgement=minimal,
        user_requests_detail=any(marker in text for marker in _DETAIL_MARKERS),
        repetition_risk=_has_repetition_risk(recent_messages),
        user_disengagement=disengagement,
        asks_personal_question=(
            direct_question and any(marker in text for marker in _PERSONAL_QUESTION_MARKERS)
        ),
    )


def derive_response_guidance(
    signals: ConversationSignals,
    recent_messages: list[ChatTurn],
    state: ConversationState,
    social_action: SocialAction = SocialAction.reply,
    emotion_guidance: EmotionGuidance | None = None,
) -> ResponseGuidance:
    """Turn signals become compact approved generator guidance."""
    anchor = _latest_character_message(recent_messages) if signals.asks_for_clarification else None
    recent_question = _latest_character_asked_question(recent_messages)

    if signals.user_disengagement:
        mode, length = ResponseMode.brief, TargetLength.very_short
    elif signals.minimal_acknowledgement:
        mode, length = ResponseMode.brief, TargetLength.very_short
    elif signals.asks_for_clarification:
        mode, length = ResponseMode.clarify, TargetLength.short
    elif signals.emotional_cue in {EmotionalCue.negative, EmotionalCue.recovery}:
        mode, length = ResponseMode.supportive, TargetLength.short
    elif signals.asks_direct_question or signals.topic_shift:
        mode = ResponseMode.direct
        length = TargetLength.normal if signals.user_requests_detail else TargetLength.short
    else:
        mode, length = ResponseMode.normal, TargetLength.short

    if social_action in {SocialAction.acknowledge, SocialAction.short_reply}:
        mode = ResponseMode.brief
        length = (
            TargetLength.very_short
            if signals.minimal_acknowledgement or signals.user_disengagement
            else TargetLength.short
        )
    elif social_action is SocialAction.answer:
        mode = ResponseMode.direct
    elif social_action is SocialAction.comfort:
        mode, length = ResponseMode.supportive, TargetLength.short
    elif social_action is SocialAction.change_topic:
        mode, length = ResponseMode.direct, TargetLength.short
    elif social_action in {SocialAction.avoid, SocialAction.refuse, SocialAction.tease}:
        mode, length = ResponseMode.brief, TargetLength.short
    elif social_action is SocialAction.open_up:
        mode, length = ResponseMode.normal, TargetLength.short

    may_ask = social_action is SocialAction.ask_back and not (
        signals.minimal_acknowledgement
        or signals.user_disengagement
        or signals.asks_for_clarification
        or signals.topic_shift
        or recent_question
        or signals.repetition_risk
    )

    emotion_context = emotion_guidance or derive_emotion_guidance(state)
    if emotion_context.reply_length_modifier is ReplyLengthModifier.shorter:
        if length is TargetLength.normal:
            length = TargetLength.short
        elif length is TargetLength.short and emotion_context.intensity_band is EmotionIntensityBand.high:
            length = TargetLength.very_short
    if emotion_context.initiative_modifier is EmotionModifier.restrained:
        may_ask = False

    return ResponseGuidance(
        response_mode=mode,
        target_length=length,
        acknowledge_emotion=signals.emotional_cue in {
            EmotionalCue.negative, EmotionalCue.recovery,
        },
        answer_before_followup=signals.asks_direct_question or signals.asks_for_clarification,
        may_ask_question=may_ask,
        followup_preference=(
            FollowupPreference.none
            if signals.minimal_acknowledgement or signals.user_disengagement
            or recent_question or signals.asks_for_clarification
            else FollowupPreference.useful_only
        ),
        continuity_anchor=anchor,
        avoid_repetition=(
            signals.repetition_risk or recent_question or signals.minimal_acknowledgement
            or signals.user_disengagement
        ),
        conversational_pressure=(
            ConversationalPressure.low
            if signals.user_disengagement else ConversationalPressure.normal
        ),
    )


def decide_social_action(
    action: SocialAction,
    signals: ConversationSignals,
    recent_messages: list[ChatTurn],
    persona_policy: PersonaSocialPolicy | None = None,
    state: ConversationState | None = None,
    relationship_guidance: RelationshipGuidance | None = None,
    emotion_guidance: EmotionGuidance | None = None,
) -> SocialActionDecision:
    """Apply only small, deterministic compatibility checks to an LLM proposal."""
    policy = persona_policy or PersonaSocialPolicy()
    approved = action
    reason = None
    relationship_reason = None
    emotion_reason = None
    relationship = relationship_guidance or RelationshipGuidance(
        band=RelationshipBand.medium,
        disclosure_permission=DisclosurePermission.moderate,
        teasing_permission=TeasingPermission.normal,
        conversational_warmth=ConversationalWarmth.warm,
        shorthand_preference=True,
        personal_question_tolerance=RelationshipBand.medium,
    )
    emotion_context = emotion_guidance or EmotionGuidance()

    if signals.user_disengagement:
        if action not in {SocialAction.acknowledge, SocialAction.short_reply, SocialAction.avoid}:
            approved, reason = SocialAction.acknowledge, "explicit_user_boundary"
    elif action is SocialAction.tease and signals.emotional_cue is EmotionalCue.negative:
        approved, reason = SocialAction.comfort, "teasing_suppressed_for_distress"
    elif (
        action is SocialAction.tease
        and emotion_context.teasing_modifier is EmotionModifier.restrained
    ):
        approved = SocialAction.reply
        emotion_reason = "teasing_suppressed_low_mood"
    elif (
        action in {SocialAction.reply, SocialAction.ask_back}
        and emotion_context.emotion is Emotion.angry
        and emotion_context.intensity_band is EmotionIntensityBand.high
    ):
        approved = SocialAction.short_reply
        emotion_reason = "reply_shortened_annoyed"
    elif (
        action is SocialAction.tease
        and policy.teasing in {SocialTraitLevel.low, SocialTraitLevel.medium_low}
    ):
        approved, reason = SocialAction.reply, "teasing_restrained_by_persona"
    elif (
        action is SocialAction.open_up
        and signals.asks_personal_question
        and policy.openness in {SocialTraitLevel.low, SocialTraitLevel.medium_low}
        and _relationship_low(state)
    ):
        approved, reason = SocialAction.avoid, "open_up_suppressed_low_openness"
    elif (
        action is SocialAction.open_up
        and signals.asks_personal_question
        and relationship.band is RelationshipBand.low
    ):
        approved = SocialAction.avoid
        relationship_reason = "private_open_up_suppressed_low_relationship"
    elif (
        action is SocialAction.tease
        and relationship.teasing_permission is TeasingPermission.restrained
    ):
        approved = SocialAction.reply
        relationship_reason = "teasing_restrained_low_relationship"
    elif action is SocialAction.ask_back:
        approved, reason = _normalize_ask_back(signals, recent_messages, policy)

    return SocialActionDecision(
        proposed=action,
        approved=approved,
        persona_adjusted=reason in {
            "teasing_restrained_by_persona",
            "open_up_suppressed_low_openness",
            "followup_restrained_by_persona",
        },
        reason=reason,
        relationship_adjusted=relationship_reason is not None,
        relationship_reason=relationship_reason,
        emotion_adjusted=emotion_reason is not None,
        emotion_reason=emotion_reason,
    )


def normalize_social_action(
    action: SocialAction,
    signals: ConversationSignals,
    recent_messages: list[ChatTurn],
) -> SocialAction:
    """Backward-compatible Phase 2 normalization facade."""
    return decide_social_action(action, signals, recent_messages).approved


def _normalize_ask_back(
    signals: ConversationSignals,
    recent_messages: list[ChatTurn],
    policy: PersonaSocialPolicy,
) -> tuple[SocialAction, str | None]:
    if signals.minimal_acknowledgement:
        return SocialAction.acknowledge, "minimal_ack_low_initiative"
    if signals.asks_direct_question or signals.asks_for_clarification:
        return SocialAction.answer, "direct_question_requires_answer"
    if signals.topic_shift:
        return SocialAction.change_topic, "explicit_topic_shift"
    if signals.emotional_cue is EmotionalCue.negative:
        return SocialAction.comfort, "distress_requires_comfort"
    if signals.repetition_risk or _latest_character_asked_question(recent_messages):
        return SocialAction.reply, "repeated_question_suppressed"
    if policy.followup_question_frequency in {SocialTraitLevel.low, SocialTraitLevel.medium_low}:
        return SocialAction.reply, "followup_restrained_by_persona"
    return SocialAction.ask_back, None


def _relationship_low(state: ConversationState | None) -> bool:
    if state is None or not state.relationship:
        return True
    return min(
        state.relationship.get("trust", 50),
        state.relationship.get("affection", 50),
    ) < 30


def _normalize_short(text: str) -> str:
    return re.sub(r"[\s，。！？!?～~…]+", "", text)


def _is_question(text: str) -> bool:
    if "?" in text or "？" in text:
        return True
    compact = _normalize_short(text)
    return any(word in compact for word in _QUESTION_WORDS) and len(compact) <= 40


def _recent_user_had_negative_cue(messages: list[ChatTurn]) -> bool:
    return any(
        turn.sender == "user" and any(marker in turn.content for marker in _NEGATIVE_MARKERS)
        for turn in messages[-8:]
    )


def _recent_has_photo_context(messages: list[ChatTurn]) -> bool:
    return any(
        any(marker in turn.content for marker in _PHOTO_CONTEXT_MARKERS)
        for turn in messages[-4:]
    )


def _character_messages(messages: list[ChatTurn]) -> list[str]:
    return [turn.content.strip() for turn in messages if turn.sender == "character" and turn.content.strip()]


def _latest_character_message(messages: list[ChatTurn]) -> str | None:
    character_messages = _character_messages(messages)
    return character_messages[-1][:240] if character_messages else None


def _latest_character_asked_question(messages: list[ChatTurn]) -> bool:
    latest = _latest_character_message(messages)
    return bool(latest and ("?" in latest or "？" in latest))


def _has_repetition_risk(messages: list[ChatTurn]) -> bool:
    recent = _character_messages(messages)[-3:]
    if len(recent) < 2:
        return False
    left, right = recent[-2], recent[-1]
    if ("?" in left or "？" in left) and ("?" in right or "？" in right):
        return True
    if any(marker in left and marker in right for marker in _OFFER_MARKERS):
        return True
    left_norm = _normalize_for_similarity(left)
    right_norm = _normalize_for_similarity(right)
    return bool(
        left_norm and right_norm
        and SequenceMatcher(None, left_norm, right_norm).ratio() >= 0.72
    )


def _normalize_for_similarity(text: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff]", "", text.casefold())
