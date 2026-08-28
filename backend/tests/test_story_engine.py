from app.core.story_engine import StoryEngine
from app.models import StoryState as StoryStateORM
from app.schemas import StoryConfig, StoryNode, Transition


def _story() -> StoryConfig:
    """两节点：a（有出边 b，含 emit_asset）→ b（终态，无出边）。"""
    return StoryConfig(
        story_id="demo",
        title="demo",
        entry_node="a",
        trigger="on_first_message",
        nodes={
            "a": StoryNode(
                scene="a",
                beat="beat",
                transitions=[
                    Transition(to="b", reason="NEXT", when=["go"], emit_asset="img")
                ],
            ),
            "b": StoryNode(scene="b", beat="end"),
        },
    )


def _state(current: str, visited: list[str], status: str = "active") -> StoryStateORM:
    return StoryStateORM(
        conversation_id="c1",
        story_id="demo",
        current_node_id=current,
        visited=visited,
        status=status,
    )


def test_activate_enters_entry_node():
    engine = StoryEngine({"demo": _story()})
    state = _state("", [], status="idle")
    node, newly = engine.activate(engine.get_story("demo"), state)
    assert newly is True
    assert state.current_node_id == "a"
    assert state.status == "active"
    assert state.visited == ["a"]
    assert node.scene == "a"


def test_activate_is_idempotent_on_revisit():
    """已访问过的 entry 节点再次激活：节点不变，visited 不重复。"""
    engine = StoryEngine({"demo": _story()})
    state = _state("a", ["a"], status="active")
    _, newly = engine.activate(engine.get_story("demo"), state)
    assert newly is False
    assert state.visited == ["a"]


def test_match_transition_validates_outgoing_edge():
    engine = StoryEngine({"demo": _story()})
    state = _state("a", ["a"])
    t = engine.match_transition(engine.get_story("demo"), state, "b")
    assert t is not None and t.to == "b"
    # 非法目标：不在出边上 → None（调用方记录并忽略）
    assert engine.match_transition(engine.get_story("demo"), state, "nope") is None


def test_apply_transition_to_terminal_marks_completed():
    engine = StoryEngine({"demo": _story()})
    state = _state("a", ["a"])
    node, newly = engine.apply_transition(
        engine.get_story("demo"), state, Transition(to="b", reason="NEXT")
    )
    assert newly is True
    assert state.current_node_id == "b"
    assert state.status == "completed"  # 终态（无出边）自动完成
    assert state.visited == ["a", "b"]
    assert node.beat == "end"
