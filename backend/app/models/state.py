from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base, utcnow


class ConversationState(Base):
    """短期对话状态：情绪 / 关系 / 话题（对应 architecture.md §5）。"""

    __tablename__ = "conversation_states"

    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id"), primary_key=True
    )
    emotion: Mapped[str | None] = mapped_column(String(32), nullable=True)
    emotion_intensity: Mapped[int] = mapped_column(Integer, default=50)
    relationship: Mapped[dict] = mapped_column(JSON, default=dict)
    current_topic: Mapped[str | None] = mapped_column(String(128), nullable=True)
    open_threads: Mapped[list] = mapped_column(JSON, default=list)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class StoryState(Base):
    """剧情运行时状态：当前节点、已访问节点（StoryEngine 专属）。"""

    __tablename__ = "story_states"

    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id"), primary_key=True
    )
    story_id: Mapped[str] = mapped_column(String(64))
    current_node_id: Mapped[str] = mapped_column(String(64))
    node_vars: Mapped[dict] = mapped_column(JSON, default=dict)
    visited: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(16), default="active")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
