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
    public_site_url: str = "https://kathachepta.com"  # the public website, for canonical links and the sitemap

    # Storage: "local" keeps files under media_root (also on the Lightsail pilot); "s3" for a Lightsail bucket comes later.
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
    trusted_device_days: int = 30  # "remember this device": staff skip the authenticator code there for this long
    otp_ttl_minutes: int = 10
    staff_mfa_required: bool = False  # forced on in production by validate()
    cookie_secure: bool = False

    # Email: sign-in codes, confirming a new address, and narrator notices. Off for the pilot: people sign up and
    # sign in with a username and password, and nothing is sent.
    email_enabled: bool = False
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
            if not self.public_base_url.startswith("https://"):
                problems.append("KC_PUBLIC_BASE_URL must be the https:// address of the web app in production.")
        return problems

    def runtime_warnings(self) -> list[str]:
        """Settings that don't stop the server but break a feature; logged at startup."""
        warnings = []
        no_mail_server = self.smtp_host in {"mailpit", "localhost"} or not self.smtp_username
        if self.is_production and self.email_enabled and no_mail_server:
            warnings.append(f"Email can't be delivered through {self.smtp_host}:{self.smtp_port}, so email sign-in "
                            "codes fail. Set KC_SMTP_HOST, KC_SMTP_USERNAME and KC_SMTP_PASSWORD (Amazon SES or "
                            "Zoho), or KC_EMAIL_ENABLED=false.")
        return warnings


@lru_cache
def get_settings() -> Settings:
    return Settings()
