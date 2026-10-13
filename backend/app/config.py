import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass


@dataclass
class Settings:
    db_path: str = field(default_factory=lambda: os.getenv("MEALAGENT_DB", str(ROOT / "data/mealagent.sqlite3")))
    api_key: str = field(default_factory=lambda: os.getenv("DEEPSEEK_API_KEY", ""))
    base_url: str = field(default_factory=lambda: os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"))
    model: str = field(default_factory=lambda: os.getenv("DEEPSEEK_MODEL", "deepseek-flash"))
    vision_model: str = field(default_factory=lambda: os.getenv("DEEPSEEK_VISION_MODEL", "deepseek-flash"))
    fallback_url: str = field(default_factory=lambda: os.getenv("VISION_FALLBACK_BASE_URL", ""))
    fallback_key: str = field(default_factory=lambda: os.getenv("VISION_FALLBACK_API_KEY", ""))
    fallback_model: str = field(default_factory=lambda: os.getenv("VISION_FALLBACK_MODEL", ""))
    app_id: str = field(default_factory=lambda: os.getenv("WECHAT_APP_ID", ""))
    app_secret: str = field(default_factory=lambda: os.getenv("WECHAT_APP_SECRET", ""))
    allow_dev_login: bool = field(default_factory=lambda: os.getenv("ALLOW_DEV_LOGIN", "false").lower() == "true")
    dev_key: str = field(default_factory=lambda: os.getenv("DEV_LOGIN_KEY", ""))
    session_days: int = field(default_factory=lambda: int(os.getenv("SESSION_DAYS", "7")))
    timeout: int = field(default_factory=lambda: int(os.getenv("LLM_TIMEOUT_SECONDS", "180")))
    cors: list[str] = field(default_factory=lambda: os.getenv("CORS_ORIGINS", "http://127.0.0.1:8000").split(","))
    worker_enabled: bool = True

    def __post_init__(self):
        if self.allow_dev_login and len(self.dev_key) < 16:
            raise ValueError("DEV_LOGIN_KEY must be at least 16 characters when development login is enabled")
        if not 1 <= self.session_days <= 30:
            raise ValueError("SESSION_DAYS must be between 1 and 30")
