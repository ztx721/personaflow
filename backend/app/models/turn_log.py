from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base, gen_id, utcnow


class TurnLog(Base):
    """每次 turn 的决策快照（planner 原始输出 + 应用结果 + 校验错误），Admin/Eval 使用。"""

    __tablename__ = "turn_logs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=gen_id)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id"), index=True
    )
    user_message_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    planner_output: Mapped[dict] = mapped_column(JSON, default=dict)
    applied: Mapped[dict] = mapped_column(JSON, default=dict)
    validation_errors: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
