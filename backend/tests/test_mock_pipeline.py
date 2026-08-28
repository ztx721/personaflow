"""Golden Path 全链路（Mock LLM）：从打招呼一路推进到发照片。"""

from sqlalchemy import select
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models import ConversationState as ConversationStateORM
from app.models import Message, StoryState as StoryStateORM, TurnLog

# (用户消息, 角色回复应处的节点标记, 期望 asset_url；None 表示纯文本)
GOLDEN = [
    ("今天终于忙完了", "[rapport]", "/static/assets/storefront.svg"),
    ("周末想放松一下", "[weekend]", "/static/assets/bay_scene.svg"),
    ("你平时会出去玩吗", "[beach_trip]", None),
    ("海边听起来不错，你去过哪", "[photo_offer]", None),
    ("你当时拍照片了吗", "[photo_offer]", None),  # 普通"照片"关键词不触发发图
    ("给我看看", "[photo_sent]", "/static/assets/beach_photo.svg"),
]


def test_golden_path_reaches_photo_sent():
    with TestClient(app) as client:
        r = client.post("/api/conversations", json={"role_id": "miko_cafe"})
        assert r.status_code == 201, r.text
        conv = r.json()
        cid = conv["id"]

        for msg, node_marker, asset_url in GOLDEN:
            rr = client.post(
                f"/api/conversations/{cid}/messages", json={"content": msg}
            )
            assert rr.status_code == 200, rr.text
            body = rr.json()
            assert body["content"].startswith(node_marker), (msg, body["content"])
            if asset_url:
                assert body["type"] == "image"
                assert body["asset_url"] == asset_url, (msg, body)
            else:
                assert body["type"] == "text"
                assert body["asset_url"] is None, (msg, body)

        # ---- 持久化校验 ----
        with SessionLocal() as db:
            # 剧情推进到终态，且 visited 顺序符合 golden path
            st = db.get(StoryStateORM, cid)
            assert st is not None
            assert st.current_node_id == "photo_sent"
            assert st.status == "completed"
            assert st.visited == [
                "greeting", "rapport", "weekend", "beach_trip", "photo_offer", "photo_sent",
            ]

            # 关系随每轮小幅升温
            state = db.get(ConversationStateORM, cid)
            assert state.relationship["trust"] > 20
            assert state.relationship["affection"] > 30

            # 情绪被正向话题驱动（末轮 excited）
            assert state.emotion == "excited"

            # 每轮一条决策日志
            logs = list(
                db.scalars(
                    select(TurnLog).where(TurnLog.conversation_id == cid).order_by(TurnLog.created_at)
                )
            )
            assert len(logs) == 6

            # 最后一轮：story 迁移 + 素材解析都被记录
            last = logs[-1]
            assert last.applied["story"]["to"] == "photo_sent"
            assert last.applied["asset_tag"] == "beach_photo"
            assert last.applied["asset_url"] == "/static/assets/beach_photo.svg"
            assert last.validation_errors == []

            # 6 轮 → 12 条消息（6 user + 6 character）
            msgs = list(
                db.scalars(select(Message).where(Message.conversation_id == cid))
            )
            assert len(msgs) == 12
            assert msgs[-1].asset_tag == "beach_photo"
