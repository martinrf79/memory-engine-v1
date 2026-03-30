from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Memory Engine V1"
    app_version: str = "0.1.0"
    database_url: str = "sqlite:///./memory_engine.db"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
