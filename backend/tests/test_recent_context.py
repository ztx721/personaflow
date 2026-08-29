from app.config import settings
from app.config_loader import load_assets, load_personas, load_stories
from app.core.conversation_service import ConversationService
from app.db import SessionLocal
from app.llm.mock import MockLLMClient


def test_recent_turns_uses_newest_messages_in_chronological_order():
    with SessionLocal() as db:
        service = ConversationService(
            db=db,
            llm=MockLLMClient(),
            personas=load_personas(),
            stories=load_stories(),
            assets=load_assets(),
        )
        conversation = service.create_conversation("miko_cafe")
        for index in range(6):
            service.send_message(conversation.id, f"message-{index}")

        turns = service._recent_turns(conversation.id)

        assert len(turns) == settings.context_window
        assert turns[0].content == "message-1"
        assert turns[-2].content == "message-5"
        assert turns[-1].sender == "character"
