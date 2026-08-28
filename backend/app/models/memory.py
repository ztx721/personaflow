from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base, gen_id, utcnow


class MemoryFact(Base):
    """长期事实。fact_type: "user_fact" | "character_fact"。MVP 暂不接入检索。"""

    __tablename__ = "memory_facts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=gen_id)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id"), index=True
    )
    fact_type: Mapped[str] = mapped_column(String(32))
    content: Mapped[str] = mapped_column(Text)
    importance: Mapped[int] = mapped_column(Integer, default=3)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
