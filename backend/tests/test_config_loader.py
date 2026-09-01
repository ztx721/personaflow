from app.config_loader import load_assets, load_personas, load_stories


def test_loads_persona_from_yaml():
    personas = load_personas()
    assert "miko_cafe" in personas
    persona = personas["miko_cafe"]

    assert persona.display_name == "林小满"
    assert persona.persona.identity
    assert persona.emotion.initial == "neutral"
    assert persona.relationship.axes["trust"] == 20
    assert persona.default_story == "travel_photo"


def test_loads_travel_photo_story():
    stories = load_stories()
    assert "travel_photo" in stories
    story = stories["travel_photo"]

    assert story.entry_node == "greeting"
    assert story.trigger == "on_first_message"
    assert story.canonical_facts
    assert not any("去年" in fact or "年前" in fact for fact in story.canonical_facts)
    assert any("具体日期" in fact and "未定义" in fact for fact in story.canonical_facts)
    assert set(story.nodes) == {
        "greeting", "rapport", "weekend", "beach_trip", "photo_offer", "photo_sent",
    }

    # 关键边：photo_offer → photo_sent 带发图副作用与确定性关键词
    photo_offer = story.nodes["photo_offer"]
    assert len(photo_offer.transitions) == 1
    t = photo_offer.transitions[0]
    assert t.to == "photo_sent"
    assert t.reason == "USER_PHOTO_REQUEST"
    assert t.emit_asset == "beach_photo"
    assert "给我看看" in t.when
    assert "照片" not in t.when  # 防止普通"照片"关键词提前触发发图

    # 终态节点无出边
    assert story.nodes["photo_sent"].transitions == []

    # 入场副作用：greeting 发 storefront 场景
    assert story.nodes["greeting"].on_enter.emit_asset == "storefront"


def test_loads_asset_catalog():
    assets = load_assets()
    assert assets["storefront"]
    assert assets["beach_photo"]
    assert assets["bay_scene"]
