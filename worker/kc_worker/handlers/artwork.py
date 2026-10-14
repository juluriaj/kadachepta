"""Cover artwork generation.

Provider (studio AI settings, sent with each job; KC_ARTWORK_PROVIDER is only the fallback):
  local-sdxl    SDXL base 1.0 + SDXL-Lightning (8-step LoRA) + the fp16-fix VAE on this machine's GPU.
                Licences: CreativeML Open RAIL++-M (SDXL, Lightning) and MIT (VAE): commercial use allowed,
                subject to the RAIL use restrictions. Needs the GPU virtualenv (scripts/setup_gpu_worker.ps1).
  pollinations  third-party internet service with unclear commercial terms; experiments only.
  disabled

Settings: KC_SDXL_MODEL, KC_SDXL_LORA_REPO, KC_SDXL_VAE (Hugging Face ids) to swap models.

Prompt (artwork-v2): one fixed house style (studio setting ai.artwork.style), then the story's main animal drawn from
a fixed description (glossary.LOOKS), then a short scene, then one expression phrase from a fixed list. All of it
fits SDXL's 77-token window: artwork-v1 prompts ran to ~86 tokens and lost their tail.
"""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import threading
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

from .. import glossary, gpu
from . import JobContext, PermanentError

_pipeline = None
_pipeline_lock = threading.Lock()
_tokenizer: Any = None

PROMPT_VERSION = "artwork-v2"
MAX_TOKENS = 77  # SDXL's CLIP text encoders, including the start and end markers
DEFAULT_STYLE = ("Indian folk art storybook illustration, gouache and watercolor, bold clean outlines, "
                 "warm earthy colors, soft light, simple composition, no text")
# The same emotion is always asked for in the same words. First matching mood word wins.
EXPRESSIONS = [
    (("funny", "playful", "silly", "humorous", "cheerful", "happy", "joyful", "fun"), "cheerful smiling faces"),
    (("sad", "emotional", "touching", "melancholy", "sorrowful", "bittersweet", "lonely"), "gentle sad eyes"),
    (("adventurous", "exciting", "thrilling", "brave", "courageous", "energetic"), "eager wide-eyed faces"),
    (("tense", "scary", "suspenseful", "dramatic", "serious", "fearful", "mysterious"), "worried wide eyes"),
    (("wise", "thoughtful", "reflective", "clever", "curious", "inspiring"), "curious bright eyes"),
    (("calm", "peaceful", "gentle", "soothing", "heartwarming", "warm", "hopeful", "tender"), "soft kind smiles"),
]
DEFAULT_EXPRESSION = "friendly expressive faces"


def count_tokens(text: str) -> int:
    """CLIP tokens SDXL reads, start and end markers included; an estimate where transformers isn't installed."""
    global _tokenizer
    if _tokenizer is None:
        try:
            from transformers import CLIPTokenizer
            _tokenizer = CLIPTokenizer.from_pretrained(
                os.environ.get("KC_SDXL_MODEL", "stabilityai/stable-diffusion-xl-base-1.0"), subfolder="tokenizer",
                local_files_only=True)
        except Exception:  # noqa: BLE001 - not installed or not downloaded yet
            _tokenizer = False
    if _tokenizer:
        return len(_tokenizer(text, truncation=False).input_ids)
    return estimate_tokens(text)


def estimate_tokens(text: str) -> int:
    """About one token per short word or punctuation mark and two per long word, plus start and end."""
    return 2 + sum(1 + (len(word) > 7) for word in re.findall(r"[A-Za-z']+|\d+|[^\sA-Za-z\d]", text))


def expression(mood: Any) -> str:
    words = re.findall(r"[a-z]+", (", ".join(mood) if isinstance(mood, list) else str(mood or "")).lower())
    for word in words:
        for moods, phrase in EXPRESSIONS:
            if word in moods:
                return phrase
    return DEFAULT_EXPRESSION


def _a(look: str) -> str:
    return f"{'an' if look[0] in 'aeiou' else 'a'} {look}"


def build_prompt(inputs: dict[str, Any], count: Callable[[str], int] | None = None) -> str:
    """House style, the cast as they always look, the scene, one expression; trimmed to fit 77 tokens."""
    count = count or count_tokens
    style = ((inputs.get("settings") or {}).get("ai.artwork.style") or DEFAULT_STYLE).strip().rstrip(".")
    teaser = " ".join(str(inputs.get("englishTeaserShort") or inputs.get("englishTeaser") or "").split())
    # Only the main animal gets a description: with two, SDXL-Lightning blends them (a monkey with a crocodile's
    # tail, a two-headed sheep where the jackal should be). The scene sentence still names the others.
    animals = glossary.cast(inputs.get("transcript") or "", teaser, inputs.get("title") or "", limit=1)
    feeling = expression(inputs.get("mood"))
    # The opening sentence is the concrete setup; later ones are questions, hooks, or turns that spoil the story.
    scene = ""
    for sentence in re.split(r"(?<=[.!?])\s+", teaser):
        if len(scene.split()) >= 8:
            break
        if "?" not in sentence:
            scene = f"{scene} {sentence}".strip()
    words = (scene or teaser or inputs.get("englishTitle") or inputs.get("title") or "a folk tale").split()

    def compose() -> str:
        parts = [style]
        if animals:
            parts.append("featuring " + " and ".join(_a(glossary.LOOKS[entry.gloss]) for entry in animals))
        if words:
            parts.append(" ".join(words).rstrip(".!?"))
        return ". ".join([*parts, feeling]) + "."

    prompt = compose()
    while count(prompt) > MAX_TOKENS:  # shorten the scene
        if words:
            words = words[:-1]
        else:
            break
        prompt = compose()
    return prompt


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
        context.log(f"provider={provider} seed={seed} tokens={count_tokens(prompt)} prompt={prompt}")
        if provider == "local-sdxl":
            data, model = _local_sdxl(context, prompt, seed, steps), "sdxl-base-1.0+lightning-8step"
        elif provider == "pollinations":
            data, model = _pollinations(context, prompt, seed), "flux (pollinations)"
        else:
            raise PermanentError(f"Artwork provider {provider!r} is turned off in the studio settings.")
        path = context.scratch / "cover.jpg"
        path.write_bytes(data)
        key = context.client.upload(context.job["id"], "cover.jpg", path)
        return {"key": key, "provider": provider, "model": model, "seed": seed, "prompt": prompt, "steps": steps,
                "promptVersion": PROMPT_VERSION}
