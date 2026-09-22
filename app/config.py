from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///data/app.db")
    deepseek_api_key: str = os.getenv("DEEPSEEK_API_KEY", "")
    deepseek_base_url: str = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    deepseek_model: str = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro")
    app_password: str = os.getenv("APP_PASSWORD", "change-me")
    app_password_hash: str = os.getenv("APP_PASSWORD_HASH", "")
    timezone: str = os.getenv("APP_TIMEZONE", "Asia/Shanghai")
    default_city: str = "北京"
    max_agent_calls: int = 3
    auth_token_ttl_seconds: int = int(os.getenv("AUTH_TOKEN_TTL_SECONDS", "604800"))
    login_max_attempts: int = int(os.getenv("LOGIN_MAX_ATTEMPTS", "5"))
    login_window_seconds: int = int(os.getenv("LOGIN_WINDOW_SECONDS", "900"))
    frontend_origins: str = os.getenv("FRONTEND_ORIGINS", "http://localhost:5173")
    feishu_app_id: str = os.getenv("FEISHU_APP_ID", "")
    feishu_app_secret: str = os.getenv("FEISHU_APP_SECRET", "")
    feishu_verification_token: str = os.getenv("FEISHU_VERIFICATION_TOKEN", "")
    feishu_owner_open_id: str = os.getenv("FEISHU_OWNER_OPEN_ID", "")
    review_reminder_time: str = os.getenv("REVIEW_REMINDER_TIME", "22:00")
    worker_poll_seconds: int = int(os.getenv("WORKER_POLL_SECONDS", "30"))


def get_settings() -> Settings:
    return Settings()
