"""加载 config/ 下的 YAML 配置并做 Pydantic 校验（启动即 fail-fast）。"""

from pathlib import Path

import yaml

from .config import settings
from .schemas import AssetSpec, PersonaConfig, StoryConfig

_personas: dict[str, PersonaConfig] | None = None
_stories: dict[str, StoryConfig] | None = None
_assets: "AssetCatalog | None" = None


def load_personas() -> dict[str, PersonaConfig]:
    global _personas
    if _personas is not None:
        return _personas

    personas_dir = Path(settings.config_dir) / "personas"
    if not personas_dir.is_dir():
        raise FileNotFoundError(f"personas 目录不存在: {personas_dir}")

    result: dict[str, PersonaConfig] = {}
    for path in sorted(personas_dir.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        persona = PersonaConfig.model_validate(raw)
        if persona.role_id in result:
            raise ValueError(f"重复的 role_id: {persona.role_id} ({path})")
        result[persona.role_id] = persona

    _personas = result
    return result


def get_persona(role_id: str) -> PersonaConfig | None:
    return load_personas().get(role_id)


def load_stories() -> dict[str, StoryConfig]:
    global _stories
    if _stories is not None:
        return _stories

    stories_dir = Path(settings.config_dir) / "stories"
    if not stories_dir.is_dir():
        raise FileNotFoundError(f"stories 目录不存在: {stories_dir}")

    result: dict[str, StoryConfig] = {}
    for path in sorted(stories_dir.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        story = StoryConfig.model_validate(raw)
        if story.story_id in result:
            raise ValueError(f"重复的 story_id: {story.story_id} ({path})")
        result[story.story_id] = story

    _stories = result
    return result


def get_story(story_id: str) -> StoryConfig | None:
    return load_stories().get(story_id)


class AssetCatalog:
    """已加载的素材 catalog：既有 id->url 映射（兼容旧 API / 故事路径），也保留完整元数据。

    spec 只含 trusted 静态资源；LLM 提议的语义 tags 由 AssetService.find_best 在此解析。
    """

    def __init__(self, specs: list[AssetSpec]):
        self.specs = specs
        self.url_map: dict[str, str] = {spec.id: spec.url for spec in specs}

    # dict-like 便捷访问（tag -> url），兼容既有调用（_to_response、旧测试）
    def __getitem__(self, asset_id: str) -> str:
        return self.url_map[asset_id]

    def __contains__(self, asset_id: str) -> bool:
        return asset_id in self.url_map

    def get(self, asset_id: str, default: str | None = None) -> str | None:
        return self.url_map.get(asset_id, default)

    def __len__(self) -> int:
        return len(self.specs)


def load_assets() -> AssetCatalog:
    """素材 catalog：asset id -> 语义元数据（catalog.yaml）。URL 只在本 catalog 解析（原则 #7）。"""
    global _assets
    if _assets is not None:
        return _assets

    path = Path(settings.config_dir) / "assets" / "catalog.yaml"
    if not path.is_file():
        _assets = AssetCatalog([])
        return _assets

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    specs: list[AssetSpec] = []
    for asset_id, entry in raw.items():
        if not isinstance(entry, dict):
            raise ValueError(f"素材条目必须是 dict: {asset_id}")
        specs.append(AssetSpec.model_validate({"id": asset_id, **entry}))
    _assets = AssetCatalog(specs)
    return _assets
