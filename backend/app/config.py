from pathlib import Path

from pydantic_settings import BaseSettings

BACKEND_DIR = Path(__file__).resolve().parent.parent  # backend/


class Settings(BaseSettings):
    database_url: str | None = None          # 默认 SQLite 文件见 db.py
    llm_provider: str = "mock"               # "mock" | "anthropic"
    anthropic_model: str = "claude-opus-5"
    anthropic_api_key: str | None = None
    config_dir: str = str(BACKEND_DIR / "config")
    context_window: int = 10                 # prompt 中保留的最近消息条数

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
