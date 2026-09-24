"""Create the local .env (secrets, worker tokens) and data folders. Safe to re-run: existing values are kept.

    python scripts/setup_local.py
"""

from __future__ import annotations

import json
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / ".env"


def read_env() -> dict[str, str]:
    values = {}
    if ENV.exists():
        for line in ENV.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip()
    return values


def main() -> int:
    env = read_env()
    created = []

    def ensure(key: str, value: str) -> None:
        if not env.get(key):
            env[key] = value
            created.append(key)

    ensure("KC_ENVIRONMENT", "development")
    ensure("POSTGRES_PASSWORD", secrets.token_urlsafe(24))
    ensure("KC_SECRET_KEY", secrets.token_urlsafe(48))
    ensure("KC_MEDIA_WORKER_TOKEN", secrets.token_urlsafe(32))
    ensure("KC_GPU_WORKER_TOKEN", secrets.token_urlsafe(32))
    env["KC_BOOTSTRAP_WORKERS"] = (f"media-docker:{env['KC_MEDIA_WORKER_TOKEN']}:media,stt;"
                                   f"gpu-desktop:{env['KC_GPU_WORKER_TOKEN']}:llm,image")
    ensure("KC_LLM_MODEL", "qwen/qwen3-8b")
    ensure("KC_ARTWORK_PROVIDER", "pollinations")
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
