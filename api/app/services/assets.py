"""Shared asset serialization and metadata rules."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any

from ..models import AudioAsset
from ..storage import media_url

METADATA_LIST_FIELDS = ("genres", "listeningContexts", "contentWarnings", "keywords")
METADATA_TEXT_FIELDS = ("title", "album", "collection", "episodeNumber", "language",
                        "audienceAgeRange", "mood", "moralTakeaway", "sourceAdaptation")
COLUMN_FOR = {
    "title": "title", "album": "album", "collection": "collection", "episodeNumber": "episode_number",
    "language": "language", "audienceAgeRange": "audience_age_range", "mood": "mood",
    "moralTakeaway": "moral_takeaway", "sourceAdaptation": "source_adaptation",
    "genres": "genres", "listeningContexts": "listening_contexts", "contentWarnings": "content_warnings",
    "keywords": "keywords",
}
LANGUAGE_ALIASES = {"te": "te-IN", "telugu": "te-IN", "hi": "hi-IN", "hindi": "hi-IN", "en": "en-IN", "english": "en-IN"}


def normalize_language(value: str | None, default: str = "te-IN") -> str:
    text = (value or "").strip()
    if not text:
        return default
    alias = LANGUAGE_ALIASES.get(text.lower())
    if alias:
        return alias
    parts = text.replace("_", "-").split("-")
    return "-".join([parts[0].lower(), *[part.upper() if len(part) == 2 else part for part in parts[1:]]])


def as_list(value: Any) -> list[str]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            value = [part.strip() for part in value.split(",")]
    if not isinstance(value, (list, tuple)):
        value = [value] if value else []
    return list(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))


def clean_metadata(fields: dict[str, Any], fallback_title: str = "Untitled") -> dict[str, Any]:
    values: dict[str, Any] = {}
    for key in METADATA_TEXT_FIELDS:
        raw = fields.get(key)
        values[key] = (str(raw).strip() if raw is not None else "") or None
    values["title"] = values["title"] or fallback_title
    values["language"] = normalize_language(values["language"]) if values["language"] else None
    for key in METADATA_LIST_FIELDS:
        values[key] = as_list(fields.get(key, fields.get(f"{key}[]")))
    return values


def apply_metadata(asset: AudioAsset, metadata: dict[str, Any]) -> None:
    for key, column in COLUMN_FOR.items():
        value = metadata.get(key)
        if key == "language" and not value:
            continue
        setattr(asset, column, value if value is not None else ([] if key in METADATA_LIST_FIELDS else None))
    asset.genre = metadata["genres"][0] if metadata.get("genres") else None


def metadata_of(asset: AudioAsset) -> dict[str, Any]:
    return {key: getattr(asset, column) or ([] if key in METADATA_LIST_FIELDS else None)
            for key, column in COLUMN_FOR.items()}


def missing_publication_metadata(asset: AudioAsset) -> list[str]:
    required = {
        "title": asset.title, "genres": asset.genres, "language": asset.language,
        "audienceAgeRange": asset.audience_age_range, "moralTakeaway": asset.moral_takeaway,
        "sourceAdaptation": asset.source_adaptation,
    }
    return [name for name, value in required.items() if not value]


def iso(value: datetime | None) -> str | None:
    return value.isoformat().replace("+00:00", "Z") if value else None


def audio_urls(asset: AudioAsset, include_original: bool = False) -> dict[str, str | None]:
    renditions = asset.renditions or {}
    standard = (renditions.get("standard") or {}).get("key")
    datasaver = (renditions.get("datasaver") or {}).get("key")
    urls = {
        "audioUrl": media_url(standard or asset.source_key),
        "audioUrlDataSaver": media_url(datasaver) if datasaver else None,
    }
    if include_original:  # staff only: listeners never get the master file
        urls["originalAudioUrl"] = media_url(asset.source_key)
    return urls


def rendition_keys(asset: AudioAsset) -> list[str]:
    """Every listening-copy file of a story, including copies kept from the previous mastering run."""
    renditions = asset.renditions or {}
    keys = [value.get("key") for value in renditions.values() if isinstance(value, dict)]
    return [key for key in [*keys, *(renditions.get("previous") or [])] if key]


def mastering_payload(asset: AudioAsset) -> dict[str, Any]:
    """What mastering did to a story, for editors and its narrator (P2-18)."""
    mastering = (asset.qc or {}).get("mastering") or {}
    compare = ((asset.renditions or {}).get("compare") or {}).get("key")
    return {"choice": asset.audio_mastering or "auto", "profile": mastering.get("profile"),
            "level": mastering.get("level"), "reason": mastering.get("reason"), "fallback": mastering.get("fallback"),
            "beforeDb": mastering.get("beforeDb"), "afterDb": mastering.get("afterDb"),
            "trimmedStart": mastering.get("trimmedStart"), "trimmedEnd": mastering.get("trimmedEnd"),
            "compareUrl": media_url(compare) if compare else None}


def artwork_url(asset: AudioAsset) -> str | None:
    version = int(asset.artwork_updated_at.timestamp()) if asset.artwork_updated_at else None
    return media_url(asset.artwork_key, version)


def narrator_label(asset: AudioAsset) -> str:
    if asset.narrator_user:
        return asset.narrator_user.display_name or asset.narrator_user.handle
    return asset.narrator_name or "KathaChepta"


def asset_payload(asset: AudioAsset, *, include_original: bool = False, **extra: Any) -> dict[str, Any]:
    payload = {
        "id": asset.id,
        "assetId": asset.id,
        "title": asset.title,
        "album": asset.album,
        "collection": asset.collection,
        "narrator": narrator_label(asset),
        "narratorUsername": narrator_label(asset),
        "genre": asset.genre,
        "language": asset.language,
        "duration": asset.duration_seconds,
        "status": asset.status,
        "sourceFilename": asset.source_filename or PurePosixPath(asset.source_key).name,
        "versionNumber": asset.version_number,
        "parentAssetId": asset.parent_asset_id,
        "submittedAt": iso(asset.submitted_at),
        "publishedAt": iso(asset.published_at),
        "updatedAt": iso(asset.updated_at),
        "reviewRequired": asset.review_required,
        "isSubmission": asset.narrator_user_id is not None,
        "metadata": metadata_of(asset),
        "metadataReviewStatus": asset.metadata_review_status,
        "artworkUrl": artwork_url(asset),
        "mediaStatus": asset.media_status,
        "qc": asset.qc or {},
        **audio_urls(asset, include_original),
    }
    payload.update(extra)
    return payload
