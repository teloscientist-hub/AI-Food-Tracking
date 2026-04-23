from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field


class Settings(BaseModel):
    app_env: str = Field(default="development")
    database_url: str = Field(default="sqlite:///./mml_food_tracking.db")
    usda_api_key: str | None = Field(default=None)
    openfoodfacts_user_agent: str = Field(
        default="MMLFoodTracking/0.1 (local-first nutrition logger)"
    )
    secret_key: str = Field(default="change-me")
    project_name: str = Field(default="MML Food Tracking")
    base_dir: Path = Field(default_factory=lambda: Path(__file__).resolve().parent.parent)


def _load_dotenv() -> None:
    env_path = Path(".env")
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    _load_dotenv()
    return Settings(
        app_env=os.getenv("APP_ENV", "development"),
        database_url=os.getenv("DATABASE_URL", "sqlite:///./mml_food_tracking.db"),
        usda_api_key=os.getenv("USDA_API_KEY") or None,
        openfoodfacts_user_agent=os.getenv(
            "OPENFOODFACTS_USER_AGENT",
            "MMLFoodTracking/0.1 (local-first nutrition logger)",
        ),
        secret_key=os.getenv("SECRET_KEY", "change-me"),
    )

