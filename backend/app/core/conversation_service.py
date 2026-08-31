"""会话核心服务：编排一次 turn 的完整流程（architecture.md §8）。

流程：保存用户消息 → 加载状态 → 剧情激活 → Planner(LLM#1)
      → 规则层应用（LLM 提议，代码裁决）→ Generator(LLM#2)
      → 持久化角色消息/状态/剧情/TurnLog。
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..llm import LLMClient
from ..llm.errors import error_label
from ..models import (
    Conversation,
    ConversationState as ConversationStateORM,
    MemoryFact,
    Message,
    StoryState as StoryStateORM,
    TurnLog,
)
from ..schemas import (
    ChatTurn,
    ConversationSignals,
    ConversationState,
    Emotion,
    EmotionGuidance,
    GeneratorContext,
    PlannerContext,
    PlannerOutput,
    PersonaConfig,
    PhotoAction,
    PhotoCategory,
    PhotoPolicyDecision,
    ResponseGuidance,
    RelationshipGuidance,
    SocialAction,
    StoryContext,
    StoryOpportunity,
    UserAct,
)
from .asset_service import AssetService
from .conversation_dynamics import (
    decide_social_action,
    derive_conversation_signals,
    derive_emotion_guidance,
    derive_relationship_guidance,
    derive_response_guidance,
)
from .rules import apply_emotion, apply_relationship, apply_topic, clamp
from .open_threads import active_threads, apply_thread_updates
from .photo_policy import normalize_photo_action
from .story_engine import StoryEngine
from .story_pressure import normalize_story_pressure


class ConversationService:
    FALLBACK_REPLY = "抱歉，我刚刚有点走神了。你愿意再说一遍吗？"
    FALLBACK_INTENT = "温和回应用户最后一句，不推进剧情，也不要声称发送了图片。"

    def __init__(
        self,
        db: Session,
        llm: LLMClient,
        personas: dict[str, PersonaConfig],
        stories: dict,
        assets: dict[str, str],
    ):
        self.db = db
        self.llm = llm
        self.personas = personas
        self.engine = StoryEngine(stories)
        self.assets = AssetService(assets)

    # ------------------------------------------------------------------
    # 会话管理
    # ------------------------------------------------------------------

    def create_conversation(self, role_id: str, story_id: str | None = None) -> Conversation:
        persona = self.personas.get(role_id)
        if persona is None:
            raise KeyError(role_id)

        conv = Conversation(role_id=role_id, story_id=story_id or persona.default_story)
        self.db.add(conv)
        self.db.flush()  # 拿到 conv.id

        state = ConversationStateORM(
            conversation_id=conv.id,
            emotion=persona.emotion.initial,
            emotion_intensity=persona.emotion.initial_intensity,
            relationship=dict(persona.relationship.axes),
        )
        self.db.add(state)
        self.db.commit()
        self.db.refresh(conv)
        return conv

    def get_conversation(self, conversation_id: str) -> Conversation:
        conv = self.db.get(Conversation, conversation_id)
        if conv is None:
            raise KeyError(conversation_id)
        return conv

    def get_state(self, conversation_id: str) -> ConversationStateORM:
        state = self.db.get(ConversationStateORM, conversation_id)
        if state is None:
            raise KeyError(conversation_id)
        return state

    # ------------------------------------------------------------------
    # 一次 turn
    # ------------------------------------------------------------------

    def send_message(self, conversation_id: str, content: str) -> Message:
        conv = self.get_conversation(conversation_id)
        persona = self.personas.get(conv.role_id)
        if persona is None:
            raise KeyError(conv.role_id)

        # 1) 用户消息先落库（独立 commit，保证 created_at 时序）
        user_msg = Message(conversation_id=conversation_id, sender="user", content=content)
        self.db.add(user_msg)
        self.db.commit()

        # 2) 状态视图（规则在此修改，最后回写 ORM）
        orm_state = self.get_state(conversation_id)
        state = self._to_state_view(orm_state, conv.role_id)
        recent_turns = self._recent_turns(conversation_id)
        conversation_signals = derive_conversation_signals(content, recent_turns, state)
        relationship_guidance = derive_relationship_guidance(state)
        emotion_guidance = derive_emotion_guidance(state)

        # 3) 剧情：on_first_message → 进入 entry_node
        story = self.engine.get_story(conv.story_id) if conv.story_id else None
        story_state = self.db.get(StoryStateORM, conversation_id) if story else None
        if story and story_state is None:
            story_state = StoryStateORM(
                conversation_id=conversation_id,
                story_id=story.story_id,
                current_node_id="",
                visited=[],
                status="active",
            )
            self.db.add(story_state)
            self.db.flush()

        errors: list[str] = []
        applied: dict = {}
        asset_tag: str | None = None
        ambient_asset_tag: str | None = None

        if story and story_state is not None:
            if not story_state.current_node_id or story_state.status == "idle":
                node, newly = self.engine.activate(story, story_state)
                if newly:
                    asset_tag = self._apply_on_enter(story, node, conversation_id, asset_tag)
                    ambient_asset_tag = asset_tag
                applied["story_enter"] = {"node": story.entry_node}

        # 4) 规划（LLM #1）
        planner_context = self._planner_context(
            persona, state, story, story_state, content, recent_turns,
            conversation_signals, relationship_guidance, emotion_guidance,
        )
        try:
            plan = self.llm.plan(planner_context)
        except Exception as exc:
            errors.append(error_label("planner", exc))
            plan = PlannerOutput(response_intent=self.FALLBACK_INTENT)

        turn_number = self.db.scalar(
            select(func.count(TurnLog.id)).where(TurnLog.conversation_id == conversation_id)
        ) + 1
        thread_result = apply_thread_updates(
            state,
            plan.thread_updates,
            plan.resume_thread_id,
            turn_number,
            content,
            conversation_signals,
        )

        # 5) 规则层应用提议（LLM 提议，代码裁决）
        apply_emotion(state, plan.emotion_proposal)
        apply_relationship(state, plan.relationship_delta)
        apply_topic(state, plan.topic_proposal)
        emotion_guidance = derive_emotion_guidance(state)

        social_decision = decide_social_action(
            plan.social_action,
            conversation_signals,
            recent_turns,
            persona.social_behavior,
            state,
            relationship_guidance,
            emotion_guidance,
        )
        social_action = social_decision.approved

        transition = None
        story_node_before = story_state.current_node_id if story_state is not None else None
        if plan.story_proposal is not None and story and story_state is not None:
            transition = self.engine.match_transition(
                story, story_state, plan.story_proposal.next_node_id
            )
            if transition is None:
                errors.append(f"非法剧情迁移: {plan.story_proposal.next_node_id}")

        story_pressure = normalize_story_pressure(
            plan.story_pressure,
            conversation_signals,
            social_action,
            emotion_guidance,
            active_threads(state),
            thread_result.resumed,
            content,
            transition,
            bool(story_state is not None and story_state.status == "active"),
        )
        explicit_photo_request = bool(
            conversation_signals.latest_user_act is UserAct.image_request
        )
        photo_decision: PhotoPolicyDecision | None = None
        story_photo_candidate = None
        if (
            transition is not None
            and transition.emit_asset
            and story_pressure.opportunity.eligible
        ):
            story_photo_candidate = self._asset_spec(transition.emit_asset)
            photo_decision = normalize_photo_action(
                plan.photo_action,
                plan.photo_category,
                explicit_photo_request,
                content,
                story_photo_candidate,
                persona.photo_policy,
                relationship_guidance,
                emotion_guidance,
                story_authorized=True,
            )

        transition_photo_allowed = (
            transition is None
            or not transition.emit_asset
            or bool(photo_decision is not None and photo_decision.asset_sent)
        )
        story_transition_applied = False
        if (
            transition is not None
            and story_pressure.opportunity.eligible
            and transition_photo_allowed
        ):
            prev = story_state.current_node_id
            node, newly = self.engine.apply_transition(story, story_state, transition)
            story_transition_applied = True
            applied["story"] = {
                "from": prev,
                "to": story_state.current_node_id,
                "reason": transition.reason,
            }
            if transition.emit_asset:
                asset_tag = transition.emit_asset
            if newly:
                before_on_enter = asset_tag
                asset_tag = self._apply_on_enter(story, node, conversation_id, asset_tag)
                if asset_tag != before_on_enter and not transition.emit_asset:
                    ambient_asset_tag = asset_tag

        # Legacy PlannerOutput.asset_tag is deliberately ignored. Only semantic
        # tags enter trusted catalog selection; story assets require a legal edge.

        # 会话驱动的素材：仅在用户显式请求看图 + 剧情未占位素材时，
        # 由 AssetService 在 trusted catalog 内解析；找不到相关素材则不发图。
        if photo_decision is None:
            contextual_candidate = None
            if explicit_photo_request:
                contextual_candidate = self.assets.find_best(
                    role_id=conv.role_id,
                    requested_tags=plan.asset_request.tags,
                    current_topic=state.current_topic,
                )
            photo_decision = normalize_photo_action(
                plan.photo_action,
                plan.photo_category,
                explicit_photo_request,
                content,
                contextual_candidate,
                persona.photo_policy,
                relationship_guidance,
                emotion_guidance,
            )
            if photo_decision.asset_sent and contextual_candidate is not None:
                asset_tag = contextual_candidate.id
            elif explicit_photo_request:
                asset_tag = None
            elif ambient_asset_tag is not None:
                asset_tag = ambient_asset_tag

        if photo_decision.asset_sent and story_photo_candidate is not None:
            asset_tag = story_photo_candidate.id

        for cand in plan.memory_candidates[:3]:
            self.db.add(
                MemoryFact(
                    conversation_id=conversation_id,
                    fact_type=cand.fact_type,
                    content=cand.text,
                    importance=clamp(cand.importance, 1, 5),
                )
            )

        asset_url = self.assets.resolve(asset_tag)
        story_photo_available = self._story_photo_available(story, story_state)

        response_guidance = derive_response_guidance(
            conversation_signals, recent_turns, state, social_action, emotion_guidance
        )

        # 6) 生成台词（LLM #2）
        generator_context = self._generator_context(
            persona, state, story, story_state, content, plan, asset_tag,
            recent_turns, conversation_signals, response_guidance, social_action,
            relationship_guidance, emotion_guidance, thread_result.resumed,
            story_pressure.opportunity,
            photo_decision.approved, photo_decision.category, bool(asset_url),
            story_photo_available,
        )
        try:
            reply = self.llm.generate(generator_context)
        except Exception as exc:
            errors.append(error_label("generator", exc))
            if conversation_signals.minimal_acknowledgement:
                reply = "嗯。"
            elif conversation_signals.user_disengagement:
                reply = "好。"
            else:
                reply = self.FALLBACK_REPLY

        # 7) 持久化：角色消息 + 状态 + 剧情 + 决策日志（同一事务）
        char_msg = Message(
            conversation_id=conversation_id,
            sender="character",
            content=reply,
            asset_tag=asset_tag,
        )
        self.db.add(char_msg)
        self._persist_state(orm_state, state)
        applied["emotion"] = {
            "emotion": state.emotion.value if state.emotion else None,
            "intensity": state.emotion_intensity,
        }
        applied["relationship"] = dict(state.relationship)
        applied["topic"] = state.current_topic
        applied["asset_tag"] = asset_tag
        applied["asset_url"] = asset_url
        applied["conversation_guidance"] = {
            "latest_user_act": conversation_signals.latest_user_act.value,
            "social_action": social_action.value,
            "social_action_proposed": social_decision.proposed.value,
            "social_action_approved": social_decision.approved.value,
            "persona_adjusted": social_decision.persona_adjusted,
            "persona_policy_reason": social_decision.reason,
            "relationship_band": relationship_guidance.band.value,
            "relationship_adjusted": social_decision.relationship_adjusted,
            "relationship_policy_reason": social_decision.relationship_reason,
            "emotion_guidance": {
                "emotion": emotion_guidance.emotion.value,
                "intensity_band": emotion_guidance.intensity_band.value,
                "energy": emotion_guidance.energy.value,
                "initiative_modifier": emotion_guidance.initiative_modifier.value,
            },
            "emotion_adjusted_social_action": social_decision.emotion_adjusted,
            "emotion_policy_reason": social_decision.emotion_reason,
            "emotional_cue": conversation_signals.emotional_cue.value,
            "topic_shift": conversation_signals.topic_shift,
            "response_mode": response_guidance.response_mode.value,
            "target_length": response_guidance.target_length.value,
            "may_ask_question": response_guidance.may_ask_question,
            "acknowledge_emotion": response_guidance.acknowledge_emotion,
            "avoid_repetition": response_guidance.avoid_repetition,
            "conversational_pressure": response_guidance.conversational_pressure.value,
            "active_thread_count": len(active_threads(state)),
            "opened_thread_ids": thread_result.opened,
            "touched_thread_ids": thread_result.touched,
            "resolved_thread_ids": thread_result.resolved,
            "resumed_thread_id": (
                thread_result.resumed.id if thread_result.resumed is not None else None
            ),
            "story_pressure_proposed": int(story_pressure.proposed),
            "story_pressure_approved": int(story_pressure.approved),
            "story_pressure_adjusted": story_pressure.adjusted,
            "story_pressure_reason": story_pressure.reason,
            "story_opportunity": story_pressure.opportunity.model_dump(mode="json"),
            "story_node_before": story_node_before,
            "story_node_after": (
                story_state.current_node_id if story_state is not None else None
            ),
            "story_transition_applied": story_transition_applied,
            "photo_action_proposed": photo_decision.proposed.value,
            "photo_action_approved": photo_decision.approved.value,
            "photo_category": photo_decision.category.value,
            "photo_policy_adjusted": photo_decision.adjusted,
            "photo_policy_reason": photo_decision.reason,
            "asset_candidate": photo_decision.asset_candidate,
            "asset_sent": photo_decision.asset_sent,
        }
        self.db.add(
            TurnLog(
                conversation_id=conversation_id,
                user_message_id=user_msg.id,
                planner_output=plan.model_dump(mode="json"),
                applied=applied,
                validation_errors=errors,
            )
        )
        self.db.commit()
        self.db.refresh(char_msg)
        return char_msg

    def list_messages(self, conversation_id: str, limit: int | None = None) -> list[Message]:
        self.get_conversation(conversation_id)  # 校验存在
        q = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.asc(), Message.id.asc())
        )
        if limit:
            q = q.limit(limit)
        return list(self.db.scalars(q))

    def get_story_state(self, conversation_id: str) -> StoryStateORM | None:
        self.get_conversation(conversation_id)
        return self.db.get(StoryStateORM, conversation_id)

    def list_turn_logs(self, conversation_id: str) -> list[TurnLog]:
        self.get_conversation(conversation_id)
        q = (
            select(TurnLog)
            .where(TurnLog.conversation_id == conversation_id)
            .order_by(TurnLog.created_at.asc(), TurnLog.id.asc())
        )
        return list(self.db.scalars(q))

    # ------------------------------------------------------------------
    # 上下文组装
    # ------------------------------------------------------------------

    def _planner_context(
        self,
        persona: PersonaConfig,
        state: ConversationState,
        story,
        story_state,
        content: str,
        recent_turns: list[ChatTurn],
        conversation_signals: ConversationSignals,
        relationship_guidance: RelationshipGuidance,
        emotion_guidance: EmotionGuidance,
    ) -> PlannerContext:
        return PlannerContext(
            persona=persona,
            state=state,
            story=self._story_context(story, story_state),
            memory=[],
            recent_messages=recent_turns,
            user_message=content,
            conversation_signals=conversation_signals,
            relationship_guidance=relationship_guidance,
            emotion_guidance=emotion_guidance,
            open_threads=active_threads(state),
        )

    def _generator_context(
        self,
        persona: PersonaConfig,
        state: ConversationState,
        story,
        story_state,
        content: str,
        plan,
        asset_tag: str | None,
        recent_turns: list[ChatTurn],
        conversation_signals: ConversationSignals,
        response_guidance: ResponseGuidance,
        social_action: SocialAction,
        relationship_guidance: RelationshipGuidance,
        emotion_guidance: EmotionGuidance,
        resumed_thread,
        story_opportunity: StoryOpportunity,
        photo_action: PhotoAction,
        photo_category: PhotoCategory,
        asset_attached: bool,
        story_photo_available: bool,
    ) -> GeneratorContext:
        return GeneratorContext(
            persona=persona,
            state=state,
            story=self._story_context(story, story_state),
            recent_messages=recent_turns,
            user_message=content,
            planner=plan,
            asset_tag=asset_tag,
            conversation_signals=conversation_signals,
            response_guidance=response_guidance,
            social_action=social_action,
            relationship_guidance=relationship_guidance,
            emotion_guidance=emotion_guidance,
            open_threads=active_threads(state),
            resumed_thread=resumed_thread,
            story_opportunity=story_opportunity,
            photo_action=photo_action,
            photo_category=photo_category,
            asset_attached=asset_attached,
            story_photo_available=story_photo_available,
        )

    def _story_context(self, story, story_state) -> StoryContext | None:
        if story is None or story_state is None or not story_state.current_node_id:
            return None
        node = self.engine.current_node(story, story_state)
        return StoryContext(
            story_id=story.story_id,
            node_id=story_state.current_node_id,
            scene=node.scene,
            beat=node.beat,
            transitions=node.transitions,
            status=story_state.status,
        )

    def _recent_turns(self, conversation_id: str) -> list[ChatTurn]:
        q = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(settings.context_window)
        )
        messages = list(reversed(list(self.db.scalars(q))))
        return [
            ChatTurn(sender=m.sender, content=m.content)
            for m in messages
        ]

    # ------------------------------------------------------------------
    # 副作用与状态同步
    # ------------------------------------------------------------------

    def _apply_on_enter(self, story, node, conversation_id: str, asset_tag: str | None):
        """节点首次进入的副作用：发射场景素材 + 记录记忆（幂等由 visited 保证）。"""
        if node.on_enter is None:
            return asset_tag
        if node.on_enter.emit_asset:
            asset_tag = node.on_enter.emit_asset
        for seed in node.on_enter.record_memory:
            self.db.add(
                MemoryFact(
                    conversation_id=conversation_id,
                    fact_type=seed.fact_type,
                    content=seed.text,
                    importance=clamp(seed.importance, 1, 5),
                )
            )
        return asset_tag

    def _to_state_view(self, orm: ConversationStateORM, role_id: str) -> ConversationState:
        try:
            emotion = Emotion(orm.emotion) if orm.emotion else None
        except ValueError:  # DB 里若有过期值，宽容处理
            emotion = None
        return ConversationState(
            conversation_id=orm.conversation_id,
            role_id=role_id,
            emotion=emotion,
            emotion_intensity=orm.emotion_intensity,
            relationship=dict(orm.relationship),
            current_topic=orm.current_topic,
            open_threads=orm.open_threads or [],
        )

    def _persist_state(self, orm: ConversationStateORM, state: ConversationState) -> None:
        orm.emotion = state.emotion.value if state.emotion else None
        orm.emotion_intensity = state.emotion_intensity
        orm.relationship = state.relationship
        orm.current_topic = state.current_topic
        orm.open_threads = [item.model_dump(mode="json") for item in state.open_threads]

    def _asset_spec(self, asset_id: str):
        return next((item for item in self.assets.specs if item.id == asset_id), None)

    def _story_photo_available(self, story, story_state) -> bool:
        if story is None or story_state is None or not story_state.current_node_id:
            return False
        node = self.engine.current_node(story, story_state)
        return any(
            transition.emit_asset and self._asset_spec(transition.emit_asset) is not None
            for transition in node.transitions
        )
