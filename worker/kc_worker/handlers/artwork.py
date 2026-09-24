"""Cover artwork generation.

Settings: KC_ARTWORK_PROVIDER = "pollinations" | "disabled" (default "disabled").
Pollinations is a third-party internet service with unclear commercial terms; it is kept only
for continuity with the prototype. Phase 2 replaces it with a local SDXL model on the GPU worker.
"""

from __future__ import annotations

import hashlib
import os
import secrets
import time
import urllib.parse
import urllib.request
from typing import Any

from . import JobContext, PermanentError


def build_prompt(inputs: dict[str, Any]) -> str:
    genres = ", ".join(inputs.get("genres") or []) or "folklore, fantasy"
    mood = inputs.get("mood") or "calm, enchanting"
    album = inputs.get("album")
    context_text = f"from the collection {album}" if album and album != inputs.get("title") else "a traditional Indian story"
    takeaway = f", capturing the essence of: {inputs['moralTakeaway']}" if inputs.get("moralTakeaway") else ""
    return (f"Children's storybook cover illustration for the story '{inputs.get('title')}' ({context_text}). "
            f"Genre: {genres}. Atmosphere: {mood}{takeaway}. Warm painterly gouache and watercolor, rich jewel tones, "
            "gentle Indian folklore storybook aesthetic, expressive characters, clean composition. "
            "No text, no words, no letters, no logos, no watermark.")


class ArtworkHandler:
    capability = "image"

    def describe(self) -> dict[str, Any]:
        return {"provider": os.environ.get("KC_ARTWORK_PROVIDER", "disabled")}

    def run(self, context: JobContext) -> dict[str, Any]:
        provider = os.environ.get("KC_ARTWORK_PROVIDER", "disabled")
        if provider != "pollinations":
            raise PermanentError(f"Artwork provider {provider!r} is not available on this worker "
                                 "(set KC_ARTWORK_PROVIDER=pollinations, or wait for the local SDXL provider in Phase 2).")
        inputs = context.inputs
        prompt = build_prompt(inputs)
        seed = (secrets.randbelow(1_000_000) if inputs.get("hasArtwork")
                else int(hashlib.md5(inputs["assetId"].encode()).hexdigest()[:8], 16) % 1_000_000)
        url = (f"https://image.pollinations.ai/prompt/{urllib.parse.quote(prompt)}"
               f"?width=768&height=768&model=flux&nologo=true&seed={seed}")
        request = urllib.request.Request(url, headers={"User-Agent": "KathaChepta-Worker/1.0", "Accept": "image/*"})
        data = b""
        for attempt in range(3):
            try:
                with urllib.request.urlopen(request, timeout=90) as response:
                    data = response.read()
                if len(data) > 1024 and data[:3] == b"\xff\xd8\xff":
                    break
                context.log(f"Attempt {attempt + 1}: not a JPEG ({len(data)} bytes)")
            except OSError as error:
                context.log(f"Attempt {attempt + 1}: {error}")
            time.sleep(3)
        else:
            raise RuntimeError("The image service did not return a JPEG after 3 attempts.")
        path = context.scratch / "cover.jpg"
        path.write_bytes(data)
        key = context.client.upload(context.job["id"], "cover.jpg", path)
        return {"key": key, "provider": provider, "model": "flux", "seed": seed, "prompt": prompt}
