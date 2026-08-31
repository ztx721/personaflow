"""会话驱动的素材选择：显式看图请求 → AssetService 在 trusted catalog 内解析相关素材。

覆盖需求验收点 A-F：
A) 书/历史/宋代 + "给我看看" → 相关书籍素材
B) 书 + "这本书好看吗"（仅提及）→ 不发图
C) 猫 + "有照片吗？给我看看" → 猫素材
D) 海边但剧情未就绪 + "给我看看" → 仍遵守剧情策略，不发图
E) Golden Path（11/12/13 轮）保持不变
F) LLM 返回未知 tags → AssetService 安全拒绝
"""

from fastapi.testclient import TestClient

from app.config_loader import load_assets, load_personas, load_stories
from app.core.asset_service import AssetService
from app.core.conversation_service import ConversationService
from app.db import SessionLocal
from app.llm.client import LLMClient
from app.main import app
from app.schemas import AssetRequest, PlannerOutput


def _new_conversation(client) -> str:
    r = client.post("/api/conversations", json={"role_id": "miko_cafe"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _post(client, cid: str, content: str):
    r = client.post(f"/api/conversations/{cid}/messages", json={"content": content})
    assert r.status_code == 200, r.text
    return r.json()


def test_a_book_history_request_returns_history_book_asset():
    with TestClient(app) as client:
        cid = _new_conversation(client)
        _post(client, cid, "我最近在读一本讲宋代历史的书")
        body = _post(client, cid, "给我看看")

        assert body["type"] == "image"
        assert body["asset_url"] == "/static/assets/history_book.svg"
        assert "history_book" not in body["content"]  # 台词不泄漏 asset id


def test_b_mention_looks_good_does_not_send_image():
    with TestClient(app) as client:
        cid = _new_conversation(client)
        _post(client, cid, "我在读一本小说")
        body = _post(client, cid, "这本书好看吗")

        assert body["type"] == "text"
        assert body["asset_url"] is None


def test_c_cat_request_returns_cat_asset():
    with TestClient(app) as client:
        cid = _new_conversation(client)
        _post(client, cid, "你家有猫吗")
        body = _post(client, cid, "有照片吗？给我看看")

        assert body["type"] == "image"
        assert body["asset_url"] == "/static/assets/cat.svg"


def test_d_beach_request_before_story_ready_sends_nothing():
    with TestClient(app) as client:
        cid = _new_conversation(client)
        for msg in ["今天终于忙完了", "周末想出去", "想去海边"]:
            _post(client, cid, msg)

        body = _post(client, cid, "给我看看")

        # 剧情未到 photo_sent：beach_photo 是 story_locked，不得提前发图
        assert body["type"] == "text"
        assert body["asset_url"] is None
        debug = client.get(f"/api/conversations/{cid}/debug").json()
        assert debug["story"]["current_node_id"] == "beach_trip"


def test_e_golden_path_photo_timing_unchanged():
    with TestClient(app) as client:
        cid = _new_conversation(client)
        for msg in ["今天终于忙完了", "周末想出去", "想去海边", "你之前海边去过哪里"]:
            _post(client, cid, msg)

        # round 11/12：提到照片 / 问颜色 → 不发图
        r11 = _post(client, cid, "你当时拍照片了吗")
        assert r11["type"] == "text" and r11["asset_url"] is None
        r12 = _post(client, cid, "照片颜色好看吗")
        assert r12["type"] == "text" and r12["asset_url"] is None

        # round 13：显式请求 → 由剧情路径发出 beach_photo
        r13 = _post(client, cid, "给我看看")
        assert r13["type"] == "image"
        assert r13["asset_url"] == "/static/assets/beach_photo.svg"


def test_f_unknown_asset_tags_are_rejected_safely():
    catalog = load_assets()
    service = AssetService(catalog)

    # 未知 tags → 无足够相关素材 → None（绝不发明素材）
    assert service.find_best("miko_cafe", ["unicorn", "dragon"], None) is None
    # 属于其他角色的素材不可用
    assert service.find_best("other_role", ["cat"], None) is None
    # 旅行素材被 story_locked：会话驱动不提前发
    assert service.find_best("miko_cafe", ["travel", "beach", "seaside"], "travel") is None
    # 合法 tag 命中对应素材
    assert service.find_best("miko_cafe", ["cat"], "cat").id == "cat"


def test_best_book_asset_is_most_relevant():
    catalog = load_assets()
    service = AssetService(catalog)
    best = service.find_best("miko_cafe", ["book", "history", "song_dynasty"], "books")
    assert best is not None
    assert best.id == "history_book"


class UnknownTagPlanner(LLMClient):
    """Fake LLM：提议未知 tags，验证应用侧拒绝且安全落为纯文本。"""

    def plan(self, ctx):
        return PlannerOutput(
            response_intent="自然回应",
            asset_request=AssetRequest(requested=True, tags=["unicorn", "dragon"]),
        )

    def generate(self, ctx):
        return "这个嘛，我手上暂时没有可以给你看的。"


def test_f2_unknown_tags_end_to_end_no_image():
    with SessionLocal() as db:
        service = ConversationService(
            db=db,
            llm=UnknownTagPlanner(),
            personas=load_personas(),
            stories=load_stories(),
            assets=load_assets(),
        )
        conversation = service.create_conversation("miko_cafe")
        # 首轮激活剧情会合法发出开场场景 storefront；第二轮无剧情副作用，
        # 未知 tags 的 asset_request 必须被拒绝且不产生图片。
        service.send_message(conversation.id, "你好")
        message = service.send_message(conversation.id, "给我看看")

        assert message.asset_tag is None
        assert message.content  # 正常文本回复，未声称发图
