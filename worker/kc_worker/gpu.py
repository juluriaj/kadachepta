"""Sharing one small GPU between the LLM (LM Studio) and the image model.

An 8 GB card can't hold Qwen3 8B and SDXL at once; with both loaded, SDXL spills into system memory and
runs about 10x slower. So before each kind of job the worker frees the other model: LM Studio unloads
through its CLI and reloads on the next request (just-in-time loading), and SDXL is dropped from memory.
The worker also asks for jobs of the same kind as the last one, so models switch rarely.

Settings: KC_LMS_CLI (path to lms), KC_GPU_SHARING=off to disable.
"""

from __future__ import annotations

import gc
import os
import shutil
import subprocess
from pathlib import Path

_llm_unloaded = False


def enabled() -> bool:
    return os.environ.get("KC_GPU_SHARING", "on") != "off"


def lms_cli() -> str | None:
    configured = os.environ.get("KC_LMS_CLI")
    if configured:
        return configured
    found = shutil.which("lms")
    if found:
        return found
    default = Path.home() / ".lmstudio" / "bin" / ("lms.exe" if os.name == "nt" else "lms")
    return str(default) if default.exists() else None


def free_llm(log) -> None:
    """Unload LM Studio's models so the image model has the GPU to itself."""
    global _llm_unloaded
    if not enabled() or _llm_unloaded:
        return
    cli = lms_cli()
    if not cli:
        log("LM Studio CLI not found; image generation shares the GPU with the LLM (slow). Set KC_LMS_CLI.")
        return
    result = subprocess.run([cli, "unload", "--all"], capture_output=True, text=True, timeout=60)
    log(f"Freed the GPU for images: lms unload --all -> {result.returncode} {result.stdout.strip()[:120]}")
    _llm_unloaded = result.returncode == 0


def llm_will_load() -> None:
    """The next LLM request reloads the model (LM Studio's just-in-time loading)."""
    global _llm_unloaded
    _llm_unloaded = False


def free_torch() -> None:
    gc.collect()
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:
        pass
