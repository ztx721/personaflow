"""会话核心服务：编排一次 turn 的完整流程（architecture.md §8）。

流程：保存用户消息 → 加载状态 → 剧情激活 → Planner(LLM#1)
      → 规则层应用（LLM 提议，代码裁决）→ Generator(LLM#2)
      → 持久化角色消息/状态/剧情/TurnLog。
"""

from sqlalchemy import select
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
    ConversationState,
    Emotion,
    GeneratorContext,
    PlannerContext,
    PlannerOutput,
    PersonaConfig,
    StoryContext,
)
from .asset_service import AssetService
from .rules import apply_emotion, apply_relationship, apply_topic, clamp
from .story_engine import StoryEngine


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

        if story and story_state is not None:
            if not story_state.current_node_id or story_state.status == "idle":
                node, newly = self.engine.activate(story, story_state)
                if newly:
                    asset_tag = self._apply_on_enter(story, node, conversation_id, asset_tag)
                applied["story_enter"] = {"node": story.entry_node}

        # 4) 规划（LLM #1）
        planner_context = self._planner_context(
            persona, state, story, story_state, content
        )
        try:
            plan = self.llm.plan(planner_context)
        except Exception as exc:
            errors.append(error_label("planner", exc))
            plan = PlannerOutput(response_intent=self.FALLBACK_INTENT)

        # 5) 规则层应用提议（LLM 提议，代码裁决）
        apply_emotion(state, plan.emotion_proposal)
        apply_relationship(state, plan.relationship_delta)
        apply_topic(state, plan.topic_proposal)

        if plan.story_proposal is not None and story and story_state is not None:
            transition = self.engine.match_transition(
                story, story_state, plan.story_proposal.next_node_id
            )
            if transition is None:
                errors.append(f"非法剧情迁移: {plan.story_proposal.next_node_id}")
            else:
                prev = story_state.current_node_id
                node, newly = self.engine.apply_transition(story, story_state, transition)
                applied["story"] = {
                    "from": prev,
                    "to": story_state.current_node_id,
                    "reason": transition.reason,
                }
                if transition.emit_asset:
                    asset_tag = transition.emit_asset
                if newly:
                    asset_tag = self._apply_on_enter(story, node, conversation_id, asset_tag)

        if plan.asset_tag and asset_tag is None:
            asset_tag = plan.asset_tag  # planner 主动动作（如 SEND_PHOTO）

        # 会话驱动的素材：仅在用户显式请求看图 + 剧情未占位素材时，
        # 由 AssetService 在 trusted catalog 内解析；找不到相关素材则不发图。
        if asset_tag is None and plan.asset_request is not None and plan.asset_request.requested:
            best = self.assets.find_best(
                role_id=conv.role_id,
                requested_tags=plan.asset_request.tags,
                current_topic=state.current_topic,
            )
            if best is not None:
                asset_tag = best.id

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

        # 6) 生成台词（LLM #2）
        generator_context = self._generator_context(
            persona, state, story, story_state, content, plan, asset_tag
        )
        try:
            reply = self.llm.generate(generator_context)
        except Exception as exc:
            errors.append(error_label("generator", exc))
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
    ) -> PlannerContext:
        return PlannerContext(
            persona=persona,
            state=state,
            story=self._story_context(story, story_state),
            memory=[],
            recent_messages=self._recent_turns(state.conversation_id),
            user_message=content,
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
    ) -> GeneratorContext:
        return GeneratorContext(
            persona=persona,
            state=state,
            story=self._story_context(story, story_state),
            recent_messages=self._recent_turns(state.conversation_id),
            user_message=content,
            planner=plan,
            asset_tag=asset_tag,
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
        )

    def _persist_state(self, orm: ConversationStateORM, state: ConversationState) -> None:
        orm.emotion = state.emotion.value if state.emotion else None
        orm.emotion_intensity = state.emotion_intensity
        orm.relationship = state.relationship
        orm.current_topic = state.current_topic
