"""Runtime configuration, read from environment variables (see .env.example)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="KC_", env_file=".env", extra="ignore")

    environment: str = "development"  # development | test | production
    database_url: str = "postgresql+psycopg://kathachepta:kathachepta@localhost:5432/kathachepta"
    secret_key: str = "dev-only-secret-change-me"
    public_base_url: str = "http://localhost:8080"

    # Storage: "local" keeps files under media_root; "s3" is wired for Lightsail buckets in Phase 6.
    storage_backend: str = "local"
    media_root: Path = Path("/data/media")
    legacy_audio_root: Path = Path("/data/legacy-audio")
    media_url_ttl_seconds: int = 6 * 60 * 60
    max_upload_bytes: int = 500 * 1024 * 1024

    web_root: Path = Path(__file__).resolve().parents[2] / "web"
    # Expo web export of the listener app (app/dist). When present it is served at "/".
    app_root: Path = Path(__file__).resolve().parents[2] / "app" / "dist"

    session_ttl_hours: int = 12
    access_token_minutes: int = 15
    refresh_token_days: int = 60
    otp_ttl_minutes: int = 10
    staff_mfa_required: bool = False  # forced on in production by validate()
    cookie_secure: bool = False

    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = "KathaChepta <no-reply@kathachepta.com>"

    # "name:token:cap1,cap2;name2:token2:cap3" — registered or updated at startup.
    bootstrap_workers: str = ""
    job_lease_seconds: int = 900

    default_language: str = "te-IN"

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    def validate_for_runtime(self) -> list[str]:
        problems = []
        if self.is_production:
            if self.secret_key.startswith("dev-only") or len(self.secret_key) < 32:
                problems.append("KC_SECRET_KEY must be a random value of at least 32 characters in production.")
            if not self.cookie_secure:
                problems.append("KC_COOKIE_SECURE must be true in production.")
            if not self.staff_mfa_required:
                problems.append("KC_STAFF_MFA_REQUIRED must be true in production.")
        return problems


@lru_cache
def get_settings() -> Settings:
    return Settings()
