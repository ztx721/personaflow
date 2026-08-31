"""AssetService：asset_tag -> URL 解析 + 会话驱动的确定性素材选择（可信 catalog）。

LLM 只回语义 tag，绝不返回 URL（原则 #7）。find_best 在 trusted catalog 内按 tag 重叠
选择最相关的素材；找不到足够相关的返回 None，绝不凭空发明一个（原则：LLM 提议 → 应用裁决）。
"""

from ..config_loader import AssetCatalog
from ..schemas import AssetSpec


class AssetService:
    def __init__(self, catalog: AssetCatalog):
        self.catalog = catalog.url_map  # id -> url，兼容 API 响应 / 故事路径解析
        self.specs = catalog.specs

    def resolve(self, tag: str | None) -> str | None:
        if not tag:
            return None
        return self.catalog.get(tag)

    def has(self, tag: str) -> bool:
        return tag in self.catalog

    def find_best(
        self,
        role_id: str,
        requested_tags: list[str] | None,
        current_topic: str | None = None,
    ) -> AssetSpec | None:
        """在 trusted catalog 内选择与请求最相关的素材。

        规则：1) 属于当前角色 2) 跳过 story_locked（只能由剧情路径发出）
              3) 按 tag 重叠计分（当前话题作为辅助上下文加分）
              4) 无任何重叠则返回 None（不发送无关回退图） 5) 确定性 tie-break（id）
        """
        if not requested_tags:
            return None

        best: AssetSpec | None = None
        best_score = 0
        for spec in self.specs:
            if spec.role_id != role_id or spec.story_locked:
                continue
            score = self._relevance(spec, requested_tags, current_topic)
            if score > best_score or (score == best_score and best is not None and spec.id < best.id):
                best = spec
                best_score = score
        return best if best_score > 0 else None

    @staticmethod
    def _relevance(
        spec: AssetSpec, requested_tags: list[str], current_topic: str | None
    ) -> int:
        want = {t.strip().casefold() for t in requested_tags if t and t.strip()}
        have = {t.strip().casefold() for t in spec.tags}
        if spec.topics:
            have |= {t.strip().casefold() for t in spec.topics}
        score = len(want & have)
        if current_topic:
            topic = current_topic.strip().casefold()
            if topic and topic in have:
                score += 1  # 当前话题作为辅助上下文
        return score
