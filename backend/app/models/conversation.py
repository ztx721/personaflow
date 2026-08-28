from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base, gen_id, utcnow


class Conversation(Base):
    """一次与某个角色的对话会话（对应 architecture.md §4 sessions）。"""

    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=gen_id)
    role_id: Mapped[str] = mapped_column(String(64), index=True)
    story_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
