import os

from pydantic_settings import BaseSettings, SettingsConfigDict


def _testing_mode() -> bool:
    return os.getenv("GITHUB_ACTIONS") == "true" or os.getenv("USE_FAKE_FIRESTORE") == "true"


class Settings(BaseSettings):
    app_name: str = "Memory Engine V1"
    app_version: str = "0.1.0"
    app_env: str = "production"
    database_url: str = "sqlite:///./memory_engine.db"
    expose_internal_routes: bool = _testing_mode()
    expose_product_docs: bool = False
    enable_admin_panel: bool = False
    admin_token: str | None = None
    panel_mode: str = "public_frontend_private_backend"
    session_cookie_name: str = "memory_engine_session"
    session_cookie_secure: bool = False
    session_duration_seconds: int = 3600
    frontend_request_timeout_ms: int = 12000

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
