from fastapi.testclient import TestClient

from app.main import app


def test_create_conversation_and_send_message():
    with TestClient(app) as client:
        # 创建会话 → 初始化 state
        r = client.post("/api/conversations", json={"role_id": "miko_cafe"})
        assert r.status_code == 201, r.text
        conv = r.json()
        assert conv["id"]
        assert conv["role_id"] == "miko_cafe"
        assert conv["story_id"] == "travel_photo"
        assert conv["state"]["emotion"] == "neutral"
        assert conv["state"]["relationship"]["trust"] == 20

        # 首条消息触发剧情进入 greeting 节点 → 开场场景素材（storefront）
        r2 = client.post(
            f"/api/conversations/{conv['id']}/messages", json={"content": "你好"}
        )
        assert r2.status_code == 200, r2.text
        body = r2.json()
        assert body["sender"] == "character"
        assert body["content"].startswith("[greeting]")
        assert body["type"] == "image"
        assert body["asset_url"] == "/static/assets/storefront.svg"

        # 历史：user 在前、character 在后
        r3 = client.get(f"/api/conversations/{conv['id']}/messages")
        assert r3.status_code == 200
        msgs = r3.json()
        assert [m["sender"] for m in msgs] == ["user", "character"]


def test_unknown_role_returns_404():
    with TestClient(app) as client:
        r = client.post("/api/conversations", json={"role_id": "nobody"})
        assert r.status_code == 404


def test_send_message_to_unknown_conversation_returns_404():
    with TestClient(app) as client:
        r = client.post(
            "/api/conversations/doesnotexist/messages", json={"content": "hi"}
        )
        assert r.status_code == 404
