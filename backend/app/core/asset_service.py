"""AssetService：asset_tag -> URL 解析（可信 catalog）。LLM 只回 tag，绝不允许 URL（原则 #7）。"""


class AssetService:
    def __init__(self, catalog: dict[str, str]):
        self.catalog = catalog

    def resolve(self, tag: str | None) -> str | None:
        if not tag:
            return None
        return self.catalog.get(tag)

    def has(self, tag: str) -> bool:
        return tag in self.catalog
