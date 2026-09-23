from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from ..client import ApiClient


class PermanentError(Exception):
    """A failure that retrying will not fix (bad input, unsupported file, missing configuration)."""


@dataclass
class JobContext:
    client: ApiClient
    job: dict[str, Any]
    scratch: Path
    _log: deque = field(default_factory=lambda: deque(maxlen=60))

    @property
    def inputs(self) -> dict[str, Any]:
        return self.job.get("inputs") or {}

    def log(self, line: str) -> None:
        for part in str(line).splitlines():
            self._log.append(part[:400])

    def log_tail(self) -> str:
        return "\n".join(self._log)[-6000:]


class Handler(Protocol):
    capability: str

    def run(self, context: JobContext) -> dict[str, Any]: ...

    def describe(self) -> dict[str, Any]: ...


from . import artwork, media, teaser, transcription  # noqa: E402

HANDLERS: dict[str, Handler] = {
    "media.process": media.MediaHandler(),
    "transcription": transcription.TranscriptionHandler(),
    "teaser": teaser.TeaserHandler(),
    "artwork": artwork.ArtworkHandler(),
}
