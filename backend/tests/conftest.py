import os
import sys
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="mealagent-test-")
os.environ["MEALAGENT_DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["MEALAGENT_UPLOAD_DIR"] = f"{_tmp}/uploads"
os.environ["MEALAGENT_OFFLINE"] = "1"
os.environ["DEEPSEEK_API_KEY"] = ""
os.environ["WECHAT_APPID"] = ""
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from app.llm import LLMClient  # noqa: E402
from app.wiki import get_wiki  # noqa: E402


@pytest.fixture(scope="session")
def wiki():
    return get_wiki()


class FakeLLM(LLMClient):
    """Online-looking client that answers each agent from canned JSON and logs every call."""

    def __init__(self, responses=None):
        super().__init__(api_key="test", offline=False)
        self.responses = responses or {}
        self.log = []

    async def chat_json(self, system, user, *, agent="", images=None, temperature=0.3):
        self.log.append({"agent": agent, "system": system, "images": bool(images)})
        resp = self.responses.get(agent, {})
        return resp(user) if callable(resp) else resp


@pytest.fixture
def fake_llm_cls():
    return FakeLLM
