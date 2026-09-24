"""Cover artwork generation.

Provider (studio AI settings, sent with each job; KC_ARTWORK_PROVIDER is only the fallback):
  local-sdxl    SDXL base 1.0 + SDXL-Lightning (8-step LoRA) + the fp16-fix VAE on this machine's GPU.
                Licences: CreativeML Open RAIL++-M (SDXL, Lightning) and MIT (VAE): commercial use allowed,
                subject to the RAIL use restrictions. Needs the GPU virtualenv (scripts/setup_gpu_worker.ps1).
  pollinations  third-party internet service with unclear commercial terms; experiments only.
  disabled

Settings: KC_SDXL_MODEL, KC_SDXL_LORA_REPO, KC_SDXL_VAE (Hugging Face ids) to swap models.
"""

from __future__ import annotations

import hashlib
import os
import secrets
import threading
import time
import urllib.parse
import urllib.request
from typing import Any

from .. import gpu
from . import JobContext, PermanentError

_pipeline = None
_pipeline_lock = threading.Lock()


def build_prompt(inputs: dict[str, Any]) -> str:
    """Short and concrete first: SDXL's text encoders only read about 77 tokens."""
    title = inputs.get("englishTitle") or inputs.get("title") or "a folk tale"
    scene = (inputs.get("englishTeaser") or "").strip()
    if len(scene) > 220:
        scene = scene[:220].rsplit(" ", 1)[0]
    themes = ", ".join([t for t in inputs.get("themes") or [] if str(t).isascii()][:3])  # the text encoder reads English
    mood = inputs.get("mood") or "warm, gentle"
    return (f"Children's storybook illustration for \"{title}\". {scene} "
            f"Indian folk art, gouache and watercolor, {mood}, {themes}, soft light, expressive characters, "
            "simple composition, no text").replace("  ", " ")


def _seed(inputs: dict[str, Any]) -> int:
    if inputs.get("hasArtwork"):  # regenerating: try something new
        return secrets.randbelow(2**31)
    return int(hashlib.md5(inputs["assetId"].encode()).hexdigest()[:8], 16) % 2**31


def _load_sdxl(context: JobContext):
    global _pipeline
    with _pipeline_lock:
        if _pipeline is not None:
            return _pipeline
        try:
            import torch
            from diffusers import AutoencoderKL, EulerDiscreteScheduler, StableDiffusionXLPipeline
        except ImportError as error:
            raise PermanentError("The local artwork model isn't installed on this worker. Run "
                                 "scripts/setup_gpu_worker.ps1 and start the worker with it.") from error
        if not torch.cuda.is_available():
            raise PermanentError("No CUDA GPU is visible to this worker; local artwork needs one.")
        started = time.monotonic()
        base = os.environ.get("KC_SDXL_MODEL", "stabilityai/stable-diffusion-xl-base-1.0")
        vae = AutoencoderKL.from_pretrained(os.environ.get("KC_SDXL_VAE", "madebyollin/sdxl-vae-fp16-fix"),
                                            torch_dtype=torch.float16)
        pipe = StableDiffusionXLPipeline.from_pretrained(base, vae=vae, torch_dtype=torch.float16, variant="fp16",
                                                         use_safetensors=True)
        pipe.load_lora_weights(os.environ.get("KC_SDXL_LORA_REPO", "ByteDance/SDXL-Lightning"),
                               weight_name="sdxl_lightning_8step_lora.safetensors")
        pipe.fuse_lora()
        pipe.scheduler = EulerDiscreteScheduler.from_config(pipe.scheduler.config, timestep_spacing="trailing")
        # 8 GB cards can't hold SDXL whole: keep only the active component on the GPU.
        pipe.enable_model_cpu_offload()
        context.log(f"Loaded SDXL in {time.monotonic() - started:.0f}s on {torch.cuda.get_device_name(0)}")
        _pipeline = pipe
        return pipe


def release_pipeline() -> None:
    """Drop SDXL from memory so the LLM gets the GPU back (see kc_worker/gpu.py)."""
    global _pipeline
    with _pipeline_lock:
        if _pipeline is None:
            return
        _pipeline = None
    gpu.free_torch()


def _local_sdxl(context: JobContext, prompt: str, seed: int, steps: int) -> bytes:
    import io

    import torch
    gpu.free_llm(context.log)
    pipe = _load_sdxl(context)
    started = time.monotonic()
    generator = torch.Generator(device="cpu").manual_seed(seed)
    image = pipe(prompt=prompt, num_inference_steps=steps, guidance_scale=0, width=1024, height=1024,
                 generator=generator).images[0]
    context.log(f"Generated in {time.monotonic() - started:.1f}s ({steps} steps)")
    buffer = io.BytesIO()
    image.resize((768, 768)).convert("RGB").save(buffer, format="JPEG", quality=88, optimize=True)
    return buffer.getvalue()


def _pollinations(context: JobContext, prompt: str, seed: int) -> bytes:
    url = (f"https://image.pollinations.ai/prompt/{urllib.parse.quote(prompt)}"
           f"?width=768&height=768&model=flux&nologo=true&seed={seed}")
    request = urllib.request.Request(url, headers={"User-Agent": "KathaChepta-Worker/1.0", "Accept": "image/*"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                data = response.read()
            if len(data) > 1024 and data[:3] == b"\xff\xd8\xff":
                return data
            context.log(f"Attempt {attempt + 1}: not a JPEG ({len(data)} bytes)")
        except OSError as error:
            context.log(f"Attempt {attempt + 1}: {error}")
        time.sleep(3)
    raise RuntimeError("The image service did not return a JPEG after 3 attempts.")


class ArtworkHandler:
    capability = "image"

    def describe(self) -> dict[str, Any]:
        info: dict[str, Any] = {"fallbackProvider": os.environ.get("KC_ARTWORK_PROVIDER", "disabled")}
        try:
            import torch
            info["gpu"] = torch.cuda.get_device_name(0) if torch.cuda.is_available() else None
            info["localModelInstalled"] = True
        except ImportError:
            info["localModelInstalled"] = False
        return info

    def run(self, context: JobContext) -> dict[str, Any]:
        inputs = context.inputs
        settings = inputs.get("settings") or {}
        provider = settings.get("ai.artwork.provider") or os.environ.get("KC_ARTWORK_PROVIDER", "disabled")
        steps = int(settings.get("ai.artwork.steps") or 8)
        prompt, seed = build_prompt(inputs), _seed(inputs)
        context.log(f"provider={provider} seed={seed} prompt={prompt}")
        if provider == "local-sdxl":
            data, model = _local_sdxl(context, prompt, seed, steps), "sdxl-base-1.0+lightning-8step"
        elif provider == "pollinations":
            data, model = _pollinations(context, prompt, seed), "flux (pollinations)"
        else:
            raise PermanentError(f"Artwork provider {provider!r} is turned off in the studio settings.")
        path = context.scratch / "cover.jpg"
        path.write_bytes(data)
        key = context.client.upload(context.job["id"], "cover.jpg", path)
        return {"key": key, "provider": provider, "model": model, "seed": seed, "prompt": prompt, "steps": steps}
