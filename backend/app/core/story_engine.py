"""确定性 StoryEngine：剧情状态管理 + 迁移校验 + 副作用触发点。

- 不调用 LLM：激活、迁移校验、节点推进全部是确定逻辑（architecture.md §7.2）。
- 「LLM 提议，代码裁决」：match_transition 校验 planner 提议的 next_node_id
  是否在当前节点的合法出边上，非法则返回 None，由调用方记录并忽略。
"""

from ..models import StoryState as StoryStateORM
from ..schemas import StoryConfig, StoryNode, Transition


class StoryEngine:
    def __init__(self, stories: dict[str, StoryConfig]):
        self.stories = stories

    def get_story(self, story_id: str) -> StoryConfig | None:
        return self.stories.get(story_id)

    def current_node(self, story: StoryConfig, state: StoryStateORM) -> StoryNode:
        return story.nodes[state.current_node_id]

    def activate(self, story: StoryConfig, state: StoryStateORM) -> tuple[StoryNode, bool]:
        """进入 entry_node。返回 (节点, 是否首次进入)；副作用由调用方在首次进入时执行。"""
        node = story.nodes[story.entry_node]
        newly = story.entry_node not in state.visited
        state.story_id = story.story_id
        state.current_node_id = story.entry_node
        state.status = "active"
        if newly:
            state.visited = [*state.visited, story.entry_node]
        return node, newly

    def match_transition(
        self, story: StoryConfig, state: StoryStateORM, next_node_id: str
    ) -> Transition | None:
        """校验 next_node_id 是否在当前节点的合法出边上；非法返回 None。"""
        node = self.current_node(story, state)
        for t in node.transitions:
            if t.to == next_node_id:
                return t
        return None

    def apply_transition(
        self, story: StoryConfig, state: StoryStateORM, transition: Transition
    ) -> tuple[StoryNode, bool]:
        """沿合法边推进节点。返回 (新节点, 是否首次进入)。终态节点置 status=completed。"""
        node = story.nodes[transition.to]
        newly = transition.to not in state.visited
        state.current_node_id = transition.to
        if newly:
            state.visited = [*state.visited, transition.to]
        if not node.transitions:
            state.status = "completed"
        return node, newly
