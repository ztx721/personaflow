import pytest
from fastapi.testclient import TestClient

from app.config_loader import load_personas
from app.core.photo_policy import normalize_photo_action
from app.llm.errors import UnsafeGeneratorOutputError
from app.llm.prompts import generator_system_prompt, validate_visible_reply
from app.main import app
from app.schemas import (
    AssetSpec,
    ConversationState,
    Emotion,
    EmotionGuidance,
    EmotionIntensityBand,
    GeneratorContext,
    PersonaConfig,
    PhotoAction,
    PhotoCategory,
    PlannerOutput,
    RelationshipBand,
    RelationshipGuidance,
)


def policy():
    return load_personas()["miko_cafe"].photo_policy


def relationship(band: RelationshipBand):
    return RelationshipGuidance(band=band)


def candidate(asset_id="selfie", tags=None, *, locked=False):
    return AssetSpec(
        id=asset_id,
        role_id="miko_cafe",
        url=f"/static/assets/{asset_id}.svg",
        tags=tags or ["selfie"],
        story_locked=locked,
    )


def decide(
    *,
    action=PhotoAction.send,
    category=PhotoCategory.selfie,
    explicit=True,
    message="给我看看你的自拍",
    asset=None,
    band=RelationshipBand.low,
    emotion=None,
    story=False,
):
    return normalize_photo_action(
        action,
        category,
        explicit,
        message,
        asset,
        policy(),
        relationship(band),
        emotion or EmotionGuidance(),
        story_authorized=story,
    )


def new_conversation(client):
    return client.post("/api/conversations", json={"role_id": "miko_cafe"}).json()["id"]


def post(client, cid, content):
    response = client.post(
        f"/api/conversations/{cid}/messages", json={"content": content}
    )
    assert response.status_code == 200
    return response.json()


def test_public_book_low_relationship_can_send():
    result = decide(
        category=PhotoCategory.book,
        message="给我看看那本书",
        asset=candidate("history_book", ["book", "history"]),
    )
    assert result.approved is PhotoAction.send
    assert result.asset_sent is True


def test_book_mention_without_request_is_none():
    result = decide(
        explicit=False,
        category=PhotoCategory.book,
        message="那本书看起来不错",
        asset=candidate("history_book", ["book"]),
    )
    assert result.approved is PhotoAction.none
    assert result.asset_sent is False


def test_personal_request_low_relationship_is_delayed():
    result = decide(asset=candidate())
    assert result.approved is PhotoAction.delay
    assert result.reason == "relationship_below_minimum"


def test_personal_request_high_relationship_can_send_when_asset_exists():
    result = decide(asset=candidate(), band=RelationshipBand.high)
    assert result.approved is PhotoAction.send
    assert result.asset_sent is True


def test_high_relationship_cannot_invent_missing_selfie():
    result = decide(asset=None, band=RelationshipBand.high)
    assert result.approved is PhotoAction.delay
    assert result.reason == "missing_trusted_asset"


def test_shy_emotion_delays_personal_request():
    result = decide(
        asset=candidate(),
        band=RelationshipBand.high,
        emotion=EmotionGuidance(emotion=Emotion.shy),
    )
    assert result.approved is PhotoAction.delay
    assert result.reason == "delayed_shy"


def test_high_angry_emotion_does_not_force_send():
    result = decide(
        asset=candidate(),
        band=RelationshipBand.high,
        emotion=EmotionGuidance(
            emotion=Emotion.angry,
            intensity_band=EmotionIntensityBand.high,
        ),
    )
    assert result.approved is PhotoAction.refuse


def test_user_cancellation_clears_photo_action():
    result = decide(message="算了，不看了", asset=candidate())
    assert result.approved is PhotoAction.none
    assert result.reason == "cancelled_by_user"


def test_story_locked_asset_requires_story_authorization():
    locked = candidate("beach_photo", ["travel", "beach"], locked=True)
    blocked = decide(category=PhotoCategory.travel, asset=locked, band=RelationshipBand.high)
    assert blocked.approved is PhotoAction.delay
    assert blocked.reason == "blocked_story_lock"

    allowed = decide(
        action=PhotoAction.delay,
        category=PhotoCategory.travel,
        asset=locked,
        story=True,
    )
    assert allowed.approved is PhotoAction.send
    assert allowed.asset_sent is True


def test_low_relationship_selfie_request_sends_no_unrelated_entry_image():
    with TestClient(app) as client:
        cid = new_conversation(client)
        body = post(client, cid, "给我看看你自己的自拍")
        assert body["type"] == "text"
        assert body["asset_url"] is None
        debug = client.get(f"/api/conversations/{cid}/debug").json()
        guidance = debug["last_turn"]["applied"]["conversation_guidance"]
        assert guidance["photo_action_approved"] == "delay"
        assert guidance["photo_category"] == "selfie"


def test_cat_request_still_sends_public_asset():
    with TestClient(app) as client:
        cid = new_conversation(client)
        post(client, cid, "店里有猫吗")
        body = post(client, cid, "有照片吗，给我看看")
        assert body["asset_url"] == "/static/assets/cat.svg"


def test_story_lock_then_legal_photo_offer_send():
    with TestClient(app) as client:
        cid = new_conversation(client)
        for message in ["今天终于忙完了", "周末想出去", "想去海边"]:
            post(client, cid, message)
        early = post(client, cid, "给我看看海边照片")
        assert early["asset_url"] is None
        debug = client.get(f"/api/conversations/{cid}/debug").json()
        assert debug["story"]["current_node_id"] == "photo_offer"

        sent = post(client, cid, "给我看看")
        assert sent["asset_url"] == "/static/assets/beach_photo.svg"
        debug = client.get(f"/api/conversations/{cid}/debug").json()
        assert debug["story"]["current_node_id"] == "photo_sent"


def generator_context(*, attached: bool, action: PhotoAction, available: bool = False):
    return GeneratorContext(
        persona=PersonaConfig(role_id="r", display_name="角色"),
        state=ConversationState(conversation_id="c", role_id="r"),
        user_message="给我看看",
        planner=PlannerOutput(response_intent="自然回应"),
        photo_action=action,
        photo_category=PhotoCategory.selfie,
        asset_attached=attached,
        asset_tag="trusted" if attached else None,
        story_photo_available=available,
    )


def test_generator_cannot_claim_send_when_asset_is_missing():
    prompt = generator_system_prompt(generator_context(attached=False, action=PhotoAction.delay))
    assert "No image is attached" in prompt
    assert "Never claim that you sent" in prompt


def test_generator_receives_consistent_send_guidance_when_asset_exists():
    prompt = generator_system_prompt(generator_context(attached=True, action=PhotoAction.send))
    assert "image WILL be attached" in prompt


def test_generator_knows_story_photo_exists_without_claiming_it_was_sent():
    prompt = generator_system_prompt(
        generator_context(attached=False, action=PhotoAction.none, available=True)
    )
    assert "trusted story photo exists" in prompt
    assert "No image is attached" in prompt


def test_generator_receives_safe_canonical_story_facts_without_internal_ids():
    ctx = generator_context(attached=False, action=PhotoAction.none)
    ctx.canonical_story_facts = ["林小满去过海边。", "她在那次经历中拍了照片。"]
    prompt = generator_system_prompt(ctx)
    assert "林小满去过海边" in prompt
    assert "keep it vague" in prompt
    assert "travel_photo" not in prompt
    assert "photo_offer" not in prompt


def test_photo_policy_labels_cannot_leak_visibly():
    ctx = generator_context(attached=False, action=PhotoAction.delay)
    with pytest.raises(UnsafeGeneratorOutputError):
        validate_visible_reply("photo_action is delay", ctx)


def test_personal_request_reaches_photo_policy_without_substitute_asset():
    with TestClient(app) as client:
        cid = new_conversation(client)
        body = post(client, cid, "发张你的看看")
        assert body["asset_url"] is None
        debug = client.get(f"/api/conversations/{cid}/debug").json()
        guidance = debug["last_turn"]["applied"]["conversation_guidance"]
        assert guidance["photo_category"] == "selfie"
        assert guidance["photo_action_approved"] in {"delay", "refuse"}
        assert guidance["photo_policy_reason"] != "no_explicit_request"
