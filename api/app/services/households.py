"""Households, listener profiles, the parental gate, and child-safe catalog filtering."""

from __future__ import annotations

import re

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import Identity, require
from ..db import get_db
from ..models import AudioAsset, Household, Profile
from ..security import hash_password, verify_password

AGE_BANDS = {"3-5": (3, 5), "6-8": (6, 8), "9-12": (9, 12)}
AVATARS = ("peacock", "elephant", "parrot", "tiger", "monkey", "deer", "owl", "lotus", "moon", "star")
MOMENTS = ("bedtime", "drive", "run", "work", "learn")
_RANGE = re.compile(r"(\d{1,2})\s*(?:-|–|to)\s*(\d{1,2})")
_PLUS = re.compile(r"(\d{1,2})\s*\+")


def household_for(db: Session, identity: Identity) -> Household:
    """Every listener account has exactly one household with at least one adult profile."""
    household = db.scalars(select(Household).where(Household.owner_user_id == identity.user.id)).first()
    if household:
        return household
    user = identity.user
    household = Household(owner_user_id=user.id, name=user.display_name or user.handle)
    db.add(household)
    db.flush()
    db.add(Profile(household_id=household.id, name=user.display_name or "Me", kind="adult",
                   listening_languages=user.listening_languages or ["te-IN"]))
    db.commit()
    db.refresh(household)
    return household


def active_profiles(household: Household) -> list[Profile]:
    return [profile for profile in household.profiles if not profile.deleted_at]


def current_profile(x_profile_id: str | None = Header(None), identity: Identity = Depends(require("catalog.read")),
                    db: Session = Depends(get_db)) -> Profile:
    household = household_for(db, identity)
    profiles = active_profiles(household)
    if x_profile_id:
        for profile in profiles:
            if str(profile.id) == x_profile_id:
                return profile
        raise HTTPException(status_code=404, detail="That listener profile doesn't exist in this household.")
    return next((p for p in profiles if p.kind == "adult"), profiles[0])


def story_age_range(text: str | None) -> tuple[int, int] | None:
    value = (text or "").lower()
    if not value:
        return None
    if "all" in value:
        return (0, 99)
    if match := _RANGE.search(value):
        low, high = int(match.group(1)), int(match.group(2))
        return (min(low, high), max(low, high))
    if match := _PLUS.search(value):
        return (int(match.group(1)), 99)
    return None


def suitable_for(profile: Profile, asset: AudioAsset) -> bool:
    """Child profiles only see stories whose starting age fits them. Unknown ages are hidden, never guessed."""
    if profile.kind != "child":
        return True
    band = AGE_BANDS.get(profile.age_band or "", (3, 12))
    story = story_age_range(asset.audience_age_range)
    if story is None or story[0] > band[1]:
        return False
    # Under-9s don't get stories flagged for fear, violence, death, or loss.
    return not (band[1] <= 8 and asset.content_warnings)


def pin_ok(household: Household, pin: str | None) -> bool:
    if not household.parental_pin_hash:
        return True
    return bool(pin) and verify_password(pin, household.parental_pin_hash)[0]


def require_parent(household: Household, pin: str | None) -> None:
    """Settings, profile changes, and account actions sit behind the parental PIN once one is set."""
    if not pin_ok(household, pin):
        raise HTTPException(status_code=403, detail={"error": "Enter the parent PIN to continue.",
                                                     "code": "parental-pin-required"})


def hash_pin(pin: str) -> str:
    if not re.fullmatch(r"\d{4}", pin or ""):
        raise HTTPException(status_code=400, detail="The parent PIN must be exactly 4 digits.")
    return hash_password(pin)
