"""What a listener account follows, for its opt-in updates (P3-09).

Narrators with an account are followed in ``narrator_follows``. Narrators the catalog credits by name only, and
series (audiobooks, and the albums of chapters in the seed catalog), have no row to point at, so the account keeps
them with its other update preferences, in ``users.contact_preferences["follows"]``:
    {"narrators": {"name:<name, case and spacing aside>": "<name as shown>"},
     "series": {"series:<id>" | "album:<album, case and spacing aside>": "<title>"}}
Following something turns on that kind of update: a listener who follows wants to hear about it.
"""

from __future__ import annotations

from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import AudioAsset, User

Kind = Literal["narrators", "series"]
SWITCH = {"narrators": "followed", "series": "series"}  # the update setting each kind of follow feeds


def _norm(text: str) -> str:
    return " ".join(text.split()).casefold()


def series_key(asset: AudioAsset) -> str | None:
    if asset.series_id:
        return f"series:{asset.series_id}"
    return f"album:{_norm(asset.album)}" if asset.album and asset.album.strip() else None


def series_title(asset: AudioAsset) -> str:
    return asset.series.title if asset.series else " ".join((asset.album or "").split())


def followed(user: User, kind: Kind) -> dict[str, str]:
    return dict(((user.contact_preferences or {}).get("follows") or {}).get(kind) or {})


def set_follow(user: User, kind: Kind, key: str, label: str, following: bool) -> None:
    preferences = dict(user.contact_preferences or {})
    follows = {name: dict(values) for name, values in (preferences.get("follows") or {}).items()}
    entries = follows.setdefault(kind, {})
    if following:
        entries[key] = label
    else:
        entries.pop(key, None)
    preferences["follows"] = follows
    user.contact_preferences = preferences  # reassign so SQLAlchemy sees the JSONB change
    if following:
        turn_on(user, SWITCH[kind])


def turn_on(user: User, switch: str) -> None:
    preferences = dict(user.contact_preferences or {})
    preferences["notifications"] = {**(preferences.get("notifications") or {}), switch: True}
    user.contact_preferences = preferences


def _following(kind: Kind, key: str):
    return User.contact_preferences["follows"][kind].has_key(key)


def followers(db: Session, kind: Kind, key: str) -> set[int]:
    return set(db.scalars(select(User.id).where(_following(kind, key))))


def follower_count(db: Session, kind: Kind, key: str) -> int:
    return db.scalar(select(func.count()).select_from(User).where(_following(kind, key))) or 0


def listing(user: User) -> list[dict[str, Any]]:
    """Name-only narrators and series this account follows, for the Updates page."""
    narrators = [{"kind": "narrator", "key": key, "name": name} for key, name in followed(user, "narrators").items()]
    series = [{"kind": "series", "key": key, "name": title} for key, title in followed(user, "series").items()]
    return sorted(narrators, key=lambda item: item["name"].casefold()) + \
        sorted(series, key=lambda item: item["name"].casefold())
