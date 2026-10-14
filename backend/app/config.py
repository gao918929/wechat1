"""Runtime settings, loaded from environment variables (and an optional .env file)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader (KEY=VALUE lines); real environment variables win."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(BACKEND_DIR / ".env")


def _resolve(path_str: str, default: Path) -> Path:
    if not path_str:
        return default
    p = Path(path_str)
    return p if p.is_absolute() else (BACKEND_DIR / p).resolve()


@dataclass
class Settings:
    deepseek_api_key: str = field(default_factory=lambda: os.getenv("DEEPSEEK_API_KEY", ""))
    deepseek_base_url: str = field(default_factory=lambda: os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"))
    deepseek_model: str = field(default_factory=lambda: os.getenv("DEEPSEEK_MODEL", "deepseek-chat"))
    vision_model: str = field(default_factory=lambda: os.getenv("DEEPSEEK_VISION_MODEL", "") or os.getenv("DEEPSEEK_MODEL", "deepseek-chat"))
    vision_base_url: str = field(default_factory=lambda: os.getenv("DEEPSEEK_VISION_BASE_URL", ""))
    vision_api_key: str = field(default_factory=lambda: os.getenv("DEEPSEEK_VISION_API_KEY", ""))
    llm_timeout: float = field(default_factory=lambda: float(os.getenv("LLM_TIMEOUT_SECONDS", "120")))
    force_offline: bool = field(default_factory=lambda: os.getenv("MEALAGENT_OFFLINE", "") in ("1", "true", "yes"))

    wechat_appid: str = field(default_factory=lambda: os.getenv("WECHAT_APPID", ""))
    wechat_secret: str = field(default_factory=lambda: os.getenv("WECHAT_SECRET", ""))
    wechat_plan_template_id: str = field(default_factory=lambda: os.getenv("WECHAT_PLAN_TEMPLATE_ID", ""))

    secret: str = field(default_factory=lambda: os.getenv("MEALAGENT_SECRET", "dev-secret-change-me"))
    database_url: str = field(default_factory=lambda: os.getenv(
        "MEALAGENT_DATABASE_URL", f"sqlite:///{BACKEND_DIR / 'data' / 'mealagent.db'}"))
    upload_dir: Path = field(default_factory=lambda: _resolve(
        os.getenv("MEALAGENT_UPLOAD_DIR", ""), BACKEND_DIR / "data" / "uploads"))
    wiki_dir: Path = field(default_factory=lambda: _resolve(
        os.getenv("MEALAGENT_WIKI_DIR", ""), REPO_ROOT / "llm_wiki"))
    city: str = field(default_factory=lambda: os.getenv("MEALAGENT_CITY", "北京"))

    # Orchestration knobs
    max_validation_retries: int = 3
    plan_cache_enabled: bool = True

    @property
    def llm_online(self) -> bool:
        return bool(self.deepseek_api_key) and not self.force_offline

    @property
    def wechat_enabled(self) -> bool:
        return bool(self.wechat_appid and self.wechat_secret)


settings = Settings()
