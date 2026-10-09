"""Application settings, read from environment variables or backend/.env."""
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "mysql+pymysql://tracktech_app:CHANGE_ME@127.0.0.1:3306/tracktech_db"

    # No default on purpose: the app refuses to start without a real secret.
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 120

    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    simulator_enabled: bool = True
    simulator_interval_seconds: float = 3.0
    simulator_speed_multiplier: float = 20.0

    login_max_attempts: int = 5
    login_lockout_minutes: int = 5

    seed_admin_password: str | None = None
    seed_manager_password: str | None = None
    seed_viewer_password: str | None = None

    @field_validator("jwt_secret")
    @classmethod
    def secret_must_be_strong(cls, value: str) -> str:
        if len(value) < 32:
            raise ValueError(
                "JWT_SECRET must be at least 32 characters. Generate one with: "
                'python -c "import secrets; print(secrets.token_urlsafe(48))"'
            )
        return value

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
