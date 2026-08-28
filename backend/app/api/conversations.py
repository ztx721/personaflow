from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..config_loader import load_assets, load_personas, load_stories
from ..core.conversation_service import ConversationService
from ..db import get_db
from ..llm import get_llm
from ..schemas import (
    ConversationDebugResponse,
    CreateConversationRequest,
    CreateConversationResponse,
    DebugTurnLog,
    MessageResponse,
    RoleSummary,
    SendMessageRequest,
)

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


def _service(db: Session) -> ConversationService:
    return ConversationService(
        db=db,
        llm=get_llm(),
        personas=load_personas(),
        stories=load_stories(),
        assets=load_assets(),
    )


def _to_response(msg, catalog: dict[str, str]) -> MessageResponse:
    """msg 存的是 asset_tag（LLM 边界原则 #7）；对外响应解析为可直接展示的 URL。"""
    return MessageResponse(
        id=msg.id,
        sender=msg.sender,
        type="image" if msg.asset_tag else "text",
        content=msg.content,
        asset_url=catalog.get(msg.asset_tag) if msg.asset_tag else None,
        created_at=msg.created_at,
    )


@router.post("", response_model=CreateConversationResponse, status_code=201)
def create_conversation(req: CreateConversationRequest, db: Session = Depends(get_db)):
    service = _service(db)
    try:
        conv = service.create_conversation(req.role_id, req.story_id)
        state = service.get_state(conv.id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"未知 role_id: {req.role_id}")

    return CreateConversationResponse(
        id=conv.id,
        role_id=conv.role_id,
        story_id=conv.story_id,
        state={
            "emotion": state.emotion,
            "emotion_intensity": state.emotion_intensity,
            "relationship": state.relationship,
        },
    )


@router.post("/{conversation_id}/messages", response_model=MessageResponse)
def send_message(
    conversation_id: str, req: SendMessageRequest, db: Session = Depends(get_db)
):
    try:
        service = _service(db)
        msg = service.send_message(conversation_id, req.content)
    except KeyError:
        raise HTTPException(status_code=404, detail="对话不存在")
    return _to_response(msg, service.assets.catalog)


@router.get("/{conversation_id}/messages", response_model=list[MessageResponse])
def list_messages(conversation_id: str, db: Session = Depends(get_db)):
    try:
        service = _service(db)
        msgs = service.list_messages(conversation_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="对话不存在")
    return [_to_response(m, service.assets.catalog) for m in msgs]


@router.get("/{conversation_id}/debug", response_model=ConversationDebugResponse)
def get_conversation_debug(conversation_id: str, db: Session = Depends(get_db)):
    """Admin Debug 使用的最小只读聚合接口。"""
    try:
        service = _service(db)
        conv = service.get_conversation(conversation_id)
        state = service.get_state(conversation_id)
        story_state = service.get_story_state(conversation_id)
        logs = service.list_turn_logs(conversation_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="conversation not found")

    persona = service.personas[conv.role_id]
    turn_logs = [
        DebugTurnLog(
            id=log.id,
            planner_output=log.planner_output,
            applied=log.applied,
            validation_errors=log.validation_errors,
            created_at=log.created_at,
        )
        for log in logs
    ]
    return ConversationDebugResponse(
        conversation_id=conv.id,
        role=RoleSummary(
            role_id=persona.role_id,
            display_name=persona.display_name,
            description=persona.description,
            avatar=persona.avatar,
        ),
        state={
            "emotion": state.emotion,
            "emotion_intensity": state.emotion_intensity,
            "relationship": state.relationship,
            "current_topic": state.current_topic,
        },
        story=(
            {
                "story_id": story_state.story_id,
                "current_node_id": story_state.current_node_id,
                "status": story_state.status,
                "visited": story_state.visited,
            }
            if story_state
            else {
                "story_id": conv.story_id,
                "current_node_id": None,
                "status": "not_started",
                "visited": [],
            }
            if conv.story_id
            else None
        ),
        last_turn=turn_logs[-1] if turn_logs else None,
        turn_logs=turn_logs,
    )
