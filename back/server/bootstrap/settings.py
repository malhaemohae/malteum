"""설정 한 곳. 환경변수·.env 로 덮어쓴다. 제품 표시 이름은 여기에만 둔다."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACK_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="APP_", extra="ignore")

    display_name: str = "말틈"
    version: str = "0.1.0"
    database_url: str = "postgresql+psycopg://app:app@localhost:5432/app"
    pack_dir: Path = BACK_DIR / "contracts" / "fixtures"
    default_pack_version: str = "DEP-2026.08-v3"
    ws_ping_interval_s: float = 30.0


def get_settings() -> Settings:
    return Settings()
