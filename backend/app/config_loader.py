"""加载 config/ 下的 YAML 配置并做 Pydantic 校验（启动即 fail-fast）。"""

from pathlib import Path

import yaml

from .config import settings
from .schemas import PersonaConfig, StoryConfig

_personas: dict[str, PersonaConfig] | None = None
_stories: dict[str, StoryConfig] | None = None
_assets: dict[str, str] | None = None


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


def load_assets() -> dict[str, str]:
    """素材 catalog：asset_tag -> URL 路径。LLM 只回 tag，URL 由此解析（原则 #7）。"""
    global _assets
    if _assets is not None:
        return _assets

    path = Path(settings.config_dir) / "assets" / "catalog.yaml"
    if not path.is_file():
        _assets = {}
        return _assets

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    _assets = dict(raw)
    return _assets
