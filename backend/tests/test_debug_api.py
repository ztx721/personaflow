from fastapi.testclient import TestClient

from app.main import app


def test_debug_api_exposes_state_story_and_turn_logs():
    with TestClient(app) as client:
        created = client.post("/api/conversations", json={"role_id": "miko_cafe"})
        conversation_id = created.json()["id"]

        before = client.get(f"/api/conversations/{conversation_id}/debug")
        assert before.status_code == 200
        assert before.json()["story"]["status"] == "not_started"
        assert before.json()["turn_logs"] == []

        client.post(
            f"/api/conversations/{conversation_id}/messages",
            json={"content": "今天终于忙完了"},
        )
        debug = client.get(f"/api/conversations/{conversation_id}/debug")
        assert debug.status_code == 200
        body = debug.json()
        assert body["role"]["display_name"] == "林小满"
        assert body["story"]["current_node_id"] == "rapport"
        assert body["state"]["relationship"]["trust"] == 21
        assert len(body["turn_logs"]) == 1
        assert body["last_turn"]["applied"]["story"]["to"] == "rapport"


def test_static_asset_is_served():
    with TestClient(app) as client:
        response = client.get("/static/assets/beach_photo.svg")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("image/svg+xml")
