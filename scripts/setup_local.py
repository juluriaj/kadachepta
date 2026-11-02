"""Create the .env (secrets, worker tokens) and data folders. Safe to re-run: existing values are kept.

    python scripts/setup_local.py                                  # the desktop (development)
    python3 scripts/setup_local.py --server app.kathachepta.com    # the Lightsail server (production)
"""

from __future__ import annotations

import argparse
import json
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / ".env"
SES_SMTP_HOST = "email-smtp.ap-south-1.amazonaws.com"


def read_env() -> dict[str, str]:
    values = {}
    if ENV.exists():
        for line in ENV.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip()
    return values


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--server", metavar="HOST", help="production settings for the web app at https://HOST")
    args = parser.parse_args()
    env = read_env()
    created = []

    def ensure(key: str, value: str) -> None:
        if not env.get(key):
            env[key] = value
            created.append(key)

    if args.server:
        # Forced on every run: these are what make it production (the API refuses to start without them).
        env.update(KC_ENVIRONMENT="production", KC_PUBLIC_BASE_URL=f"https://{args.server}",
                   KC_COOKIE_SECURE="true", KC_STAFF_MFA_REQUIRED="true")
        # Sized for the 1 GB pilot instance; on the 4 GB plan use 3 and 2.
        # Email stays off until SMTP credentials are added (KC_EMAIL_ENABLED=true): people use passwords.
        for key, value in {"KC_API_WORKERS": "2", "KC_MEDIA_WORKERS": "1", "KC_EMAIL_ENABLED": "false",
                           "KC_SMTP_HOST": SES_SMTP_HOST,
                           "KC_SMTP_PORT": "587", "KC_SMTP_USERNAME": "", "KC_SMTP_PASSWORD": "",
                           "KC_SMTP_FROM": "KathaChepta <no-reply@kathachepta.com>", "SARVAM_API_KEY": ""}.items():
            env.setdefault(key, value)
    ensure("KC_ENVIRONMENT", "development")
    ensure("POSTGRES_PASSWORD", secrets.token_urlsafe(24))
    ensure("KC_SECRET_KEY", secrets.token_urlsafe(48))
    ensure("KC_MEDIA_WORKER_TOKEN", secrets.token_urlsafe(32))
    ensure("KC_GPU_WORKER_TOKEN", secrets.token_urlsafe(32))
    env["KC_BOOTSTRAP_WORKERS"] = (f"media-docker:{env['KC_MEDIA_WORKER_TOKEN']}:media,stt;"
                                   f"gpu-desktop:{env['KC_GPU_WORKER_TOKEN']}:llm,image")
    ensure("KC_LLM_MODEL", "qwen/qwen3-8b")
    ensure("KC_ARTWORK_PROVIDER", "local-sdxl")  # fallback only; the studio AI settings decide per job
    if not env.get("SARVAM_API_KEY"):
        legacy = ROOT / "config" / "secrets.local.json"
        if legacy.exists():
            key = json.loads(legacy.read_text(encoding="utf-8")).get("sarvam", {}).get("apiKey", "")
            if key and not key.startswith("set-"):
                env["SARVAM_API_KEY"] = key
                created.append("SARVAM_API_KEY (from config/secrets.local.json)")
    ENV.write_text("# Local secrets. Never commit this file.\n"
                   + "".join(f"{key}={value}\n" for key, value in env.items()), encoding="utf-8")
    for folder in ("data/media", "data/backups"):
        (ROOT / folder).mkdir(parents=True, exist_ok=True)
    print(f".env ready ({ENV}). New values: {', '.join(created) or 'none'}")
    if not env.get("SARVAM_API_KEY"):
        print("Note: SARVAM_API_KEY is empty, so transcription jobs will fail until you add it to .env.")
    if args.server:
        if env.get("KC_EMAIL_ENABLED") == "true" and not env.get("KC_SMTP_USERNAME"):
            print("Note: KC_EMAIL_ENABLED is true but KC_SMTP_USERNAME and KC_SMTP_PASSWORD are empty, so email "
                  "sign-in codes fail until you add them.")
        print("\nAdd these lines to the desktop .env so its GPU worker serves this server:\n"
              f"  KC_GPU_API_URL=https://{args.server}\n  KC_GPU_API_TOKEN={env['KC_GPU_WORKER_TOKEN']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
