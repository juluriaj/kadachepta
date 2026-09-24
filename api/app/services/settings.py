"""Admin-editable runtime settings (P2-14).

Values live in the ``app_settings`` table and are sent to workers inside each job, so a change applies
to the next job without restarting anything. Secrets (API keys, tokens) are never settings: they stay
in ``.env`` and are never sent to browsers.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import AppSetting


@dataclass(frozen=True)
class Spec:
    default: Any
    kind: str  # text | bool | int | float | choice | map | patterns
    label: str
    help: str
    choices: tuple[str, ...] = ()
    minimum: float | None = None
    maximum: float | None = None


# The Telugu channel intro ("KathaChepta.com", said many ways) that opens most catalog recordings.
DEFAULT_INTRO_PATTERNS = {
    "te-IN": [r"^\s*కథ\s*చె(?:ప్|పు|బు|ప్పు)తా(?:డు)?\s*(?:\.|డాట్)?\s*కామ్\s*(?:కి\s*స్వాగతం)?[\s.,!]*"],
}

SPECS: dict[str, Spec] = {
    "ai.llm.model": Spec(os.environ.get("KC_LLM_MODEL") or "qwen/qwen3-8b", "text", "Drafting model",
                         "LM Studio model for teasers, metadata suggestions, and safety checks."),
    "ai.llm.modelByLanguage": Spec({}, "map", "Drafting model per language",
                                   "Overrides the drafting model for specific story languages, e.g. hi-IN."),
    "ai.drafts.promptVersion": Spec("drafts-v4", "choice", "Drafting prompt",
                                    "drafts-v4 adds genres, listening moments, and the safety pre-check.",
                                    choices=("drafts-v4", "teaser-v3")),
    "ai.artwork.provider": Spec(os.environ.get("KC_ARTWORK_PROVIDER") or "local-sdxl", "choice", "Artwork provider",
                                "local-sdxl runs on the GPU worker. Pollinations is a third-party service with "
                                "unclear commercial terms; use only for experiments.",
                                choices=("local-sdxl", "pollinations", "disabled")),
    "ai.artwork.steps": Spec(8, "int", "Artwork steps",
                             "The local model is tuned for 8 steps; fewer is faster but rougher.", minimum=2, maximum=40),
    "ai.stt.model": Spec(os.environ.get("KC_STT_MODEL") or "saaras:v4", "text", "Speech-to-text model",
                         "Sarvam model used for transcription (billed per audio minute)."),
    "pipeline.autoTranscribe": Spec(True, "bool", "Transcribe narrator submissions automatically",
                                    "Paid (Sarvam). Seed-catalog stories are never transcribed without an admin action."),
    "pipeline.autoArtwork": Spec(True, "bool", "Create artwork automatically",
                                 "Generate cover art for stories that don't have any."),
    "pipeline.dailyTranscriptionMinutes": Spec(240, "int", "Daily transcription limit (minutes)",
                                               "Protects the Sarvam bill. Jobs beyond the limit wait for the next day.",
                                               minimum=0, maximum=100000),
    "pipeline.introPatterns": Spec(DEFAULT_INTRO_PATTERNS, "patterns", "Channel intro patterns",
                                   "Regular expressions per language, removed from the start of transcripts."),
    "review.transcriptConfidence": Spec(0.6, "float", "Transcript confidence needed to skip review",
                                        "Below this, the editor must read the transcript before publishing.",
                                        minimum=0, maximum=1),
    "review.slaHours": Spec(24, "int", "Review time target (hours)",
                            "Stories waiting longer are marked overdue in the studio queue.", minimum=1, maximum=720),
    "narrators.newInProgressLimit": Spec(3, "int", "Submissions in progress for new narrators",
                                         "New narrators can have this many stories being prepared or reviewed at once.",
                                         minimum=1, maximum=100),
    "narrators.trustAfterPublished": Spec(5, "int", "Suggest trusted status after",
                                          "Published stories without changes requested before the studio suggests trust.",
                                          minimum=1, maximum=1000),
}

WORKER_KEYS = {
    "teaser": ("ai.llm.model", "ai.llm.modelByLanguage", "ai.drafts.promptVersion"),
    "artwork": ("ai.artwork.provider", "ai.artwork.steps"),
    "transcription": ("ai.stt.model",),
    "media.process": (),
}


def all_settings(db: Session) -> dict[str, Any]:
    stored = {row.key: row.value for row in db.scalars(select(AppSetting))}
    return {key: stored.get(key, spec.default) for key, spec in SPECS.items()}


def get(db: Session, key: str) -> Any:
    row = db.get(AppSetting, key)
    return row.value if row else SPECS[key].default


def validate(key: str, value: Any) -> Any:
    spec = SPECS.get(key)
    if not spec:
        raise HTTPException(status_code=400, detail=f"Unknown setting {key!r}.")
    try:
        if spec.kind == "bool":
            if not isinstance(value, bool):
                raise ValueError("expected true or false")
        elif spec.kind in {"int", "float"}:
            if isinstance(value, bool):
                raise ValueError("expected a number")
            value = int(value) if spec.kind == "int" else float(value)
            if (spec.minimum is not None and value < spec.minimum) or (spec.maximum is not None and value > spec.maximum):
                raise ValueError(f"must be between {spec.minimum:g} and {spec.maximum:g}")
        elif spec.kind == "choice":
            if value not in spec.choices:
                raise ValueError(f"choose one of {', '.join(spec.choices)}")
        elif spec.kind == "text":
            value = str(value).strip()
            if not value or len(value) > 200:
                raise ValueError("must be 1-200 characters")
        elif spec.kind == "map":
            if not isinstance(value, dict) or not all(isinstance(v, str) and v.strip() for v in value.values()):
                raise ValueError("expected {language: model}")
            value = {k.strip(): v.strip() for k, v in value.items() if k.strip()}
        elif spec.kind == "patterns":
            if not isinstance(value, dict) or not all(isinstance(v, list) for v in value.values()):
                raise ValueError("expected {language: [regex, ...]}")
            for patterns in value.values():
                for pattern in patterns:
                    re.compile(pattern)
    except (TypeError, ValueError, re.error) as error:
        raise HTTPException(status_code=422, detail=f"{spec.label}: {error}") from None
    return value


def put(db: Session, key: str, value: Any, actor: str) -> Any:
    value = validate(key, value)
    row = db.get(AppSetting, key) or AppSetting(key=key)
    row.value, row.updated_by = value, actor
    db.add(row)
    return value


def for_job(db: Session, job_type: str, language: str | None = None,
            overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """The settings a worker needs for one job, with per-language model resolution done here."""
    values = {key: get(db, key) for key in WORKER_KEYS.get(job_type, ())}
    values.update({k: v for k, v in (overrides or {}).items() if k in WORKER_KEYS.get(job_type, ())})
    if job_type == "teaser":
        by_language = values.pop("ai.llm.modelByLanguage", {}) or {}
        values["ai.llm.model"] = by_language.get(language or "", values["ai.llm.model"])
    return values


def describe() -> list[dict[str, Any]]:
    return [{"key": key, "kind": spec.kind, "label": spec.label, "help": spec.help, "default": spec.default,
             "choices": list(spec.choices), "minimum": spec.minimum, "maximum": spec.maximum}
            for key, spec in SPECS.items()]
