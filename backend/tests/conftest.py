import os
from pathlib import Path

# 必须在导入 app 之前设置环境：测试使用独立的 SQLite 文件 + mock LLM
_TEST_DB = Path(__file__).parent / "test_personaflow.db"
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB}"
os.environ["LLM_PROVIDER"] = "mock"

import pytest  # noqa: E402


@pytest.fixture(autouse=True, scope="session")
def _clean_test_db():
    # 每次测试会话开始前清掉旧库，避免残留 schema/数据
    if _TEST_DB.exists():
        _TEST_DB.unlink()
    yield
