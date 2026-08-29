import json

from sqlalchemy import select

from app.config_loader import load_assets, load_personas, load_stories
from app.core.conversation_service import ConversationService
from app.db import SessionLocal
from app.llm.anthropic import AnthropicLLMClient
from app.models import TurnLog


class FailingMessages:
    def parse(self, **kwargs):
        raise RuntimeError("must never reach the API response or TurnLog")


class FailingClient:
    messages = FailingMessages()


def test_provider_failure_returns_safe_reply_and_records_turn_log():
    with SessionLocal() as db:
        service = ConversationService(
            db=db,
            llm=AnthropicLLMClient(client=FailingClient()),
            personas=load_personas(),
            stories=load_stories(),
            assets=load_assets(),
        )
        conversation = service.create_conversation("miko_cafe")

        message = service.send_message(conversation.id, "你好")

        assert message.content == ConversationService.FALLBACK_REPLY
        assert "[greeting]" not in message.content
        log = db.scalar(
            select(TurnLog).where(TurnLog.conversation_id == conversation.id)
        )
        assert log is not None
        assert log.validation_errors == [
            "planner:request_failed",
            "generator:request_failed",
        ]
        serialized = json.dumps(log.validation_errors, ensure_ascii=False)
        assert "must never reach" not in serialized
