from pathlib import Path

from pydantic_settings import BaseSettings

BACKEND_DIR = Path(__file__).resolve().parent.parent  # backend/


class Settings(BaseSettings):
    database_url: str | None = None          # 默认 SQLite 文件见 db.py
    llm_provider: str = "mock"               # "mock" | "anthropic" | "deepseek"
    anthropic_model: str = "claude-sonnet-5"
    anthropic_api_key: str | None = None
    anthropic_timeout_seconds: float = 45.0
    anthropic_max_retries: int = 1
    anthropic_planner_max_tokens: int = 1200
    anthropic_generator_max_tokens: int = 400
    deepseek_api_key: str | None = None
    deepseek_model: str = "deepseek-v4-flash"
    deepseek_timeout_seconds: float = 45.0
    deepseek_max_retries: int = 0
    deepseek_planner_max_tokens: int = 1200
    deepseek_generator_max_tokens: int = 400
    config_dir: str = str(BACKEND_DIR / "config")
    context_window: int = 10                 # prompt 中保留的最近消息条数

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
