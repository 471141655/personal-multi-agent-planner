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


def get_settings() -> Settings:
    return Settings()

