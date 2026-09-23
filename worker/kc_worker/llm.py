"""OpenAI-compatible chat client for local models (LM Studio by default).

Settings: KC_LLM_BASE_URL (default http://localhost:1234/v1), KC_LLM_MODEL, KC_LLM_API_KEY (optional),
KC_LLM_TIMEOUT (seconds, default 900).
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from typing import Any

THINK_BLOCK = re.compile(r"<think>.*?</think>", re.S)


class LlmError(RuntimeError):
    pass


def base_url() -> str:
    return os.environ.get("KC_LLM_BASE_URL", "http://localhost:1234/v1").rstrip("/")


def default_model() -> str:
    return os.environ.get("KC_LLM_MODEL", "qwen/qwen3-8b")


def list_models() -> list[str]:
    try:
        with urllib.request.urlopen(base_url() + "/models", timeout=5) as response:
            return [item["id"] for item in json.loads(response.read()).get("data", [])]
    except (OSError, ValueError, KeyError):
        return []


def chat_json(messages: list[dict[str, str]], schema: dict[str, Any], *, model: str | None = None,
              temperature: float = 0.2, max_tokens: int = 1500) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return (parsed JSON, stats). Uses JSON-schema constrained output where the server supports it."""
    model = model or default_model()
    body = {
        "model": model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens,
        "response_format": {"type": "json_schema", "json_schema": {"name": "result", "strict": True, "schema": schema}},
    }
    headers = {"Content-Type": "application/json"}
    if os.environ.get("KC_LLM_API_KEY"):
        headers["Authorization"] = f"Bearer {os.environ['KC_LLM_API_KEY']}"
    request = urllib.request.Request(base_url() + "/chat/completions", data=json.dumps(body).encode(),
                                     headers=headers, method="POST")
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=float(os.environ.get("KC_LLM_TIMEOUT", "900"))) as response:
            payload = json.loads(response.read())
    except urllib.error.HTTPError as error:
        raise LlmError(f"LLM server returned HTTP {error.code}: {error.read().decode('utf-8', 'replace')[:500]}") from None
    except OSError as error:
        raise LlmError(f"Could not reach the LLM server at {base_url()}: {error}. "
                       "Is LM Studio's server running with the model available?") from None
    elapsed = time.monotonic() - started
    content = payload["choices"][0]["message"].get("content") or ""
    content = THINK_BLOCK.sub("", content).strip()
    if content.startswith("```"):
        content = content.strip("`").removeprefix("json").strip()
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as error:
        raise LlmError(f"Model {model} returned invalid JSON ({error}): {content[:300]}") from None
    usage = payload.get("usage") or {}
    stats = {"model": payload.get("model", model), "seconds": round(elapsed, 1),
             "promptTokens": usage.get("prompt_tokens"), "completionTokens": usage.get("completion_tokens")}
    if usage.get("completion_tokens") and elapsed:
        stats["tokensPerSecond"] = round(usage["completion_tokens"] / elapsed, 1)
    return parsed, stats
