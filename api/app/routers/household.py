"""Household API: onboarding, listener profiles, parental PIN, family stats, account export and deletion."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..auth import SESSION_COOKIE, Identity, audit, require, utcnow
from ..db import get_db
from ..models import (
    AuthSession, Household, ListenerFavorite, ListeningDaily, ListeningProgress, Profile, User,
)
from ..services.assets import iso, normalize_language
from ..services.households import (
    AGE_BANDS, AVATARS, MOMENTS, active_profiles, hash_pin, household_for, pin_ok, require_parent,
)
from .listener import local_day, profile_stats

router = APIRouter(prefix="/api", tags=["household"])
UI_LANGUAGES = ("en", "te")


def profile_payload(profile: Profile) -> dict:
    return {"id": profile.id, "name": profile.name, "kind": profile.kind, "ageBand": profile.age_band,
            "avatar": profile.avatar, "listeningLanguages": profile.listening_languages,
            "createdAt": iso(profile.created_at)}


def household_payload(household: Household, identity: Identity) -> dict:
    return {
        "household": {"id": household.id, "name": household.name, "moments": household.moments,
                      "onboarded": bool(household.onboarded_at), "hasParentPin": bool(household.parental_pin_hash)},
        "profiles": [profile_payload(p) for p in active_profiles(household)],
        "account": {"email": identity.user.email, "username": identity.user.username,
                    "uiLanguage": identity.user.ui_language, "role": identity.role},
        "options": {"ageBands": list(AGE_BANDS), "avatars": list(AVATARS), "moments": list(MOMENTS),
                    "uiLanguages": list(UI_LANGUAGES), "listeningLanguages": ["te-IN", "en-IN", "hi-IN"]},
    }


@router.get("/household")
def get_household(identity: Identity = Depends(require("catalog.read")), db: Session = Depends(get_db)):
    return household_payload(household_for(db, identity), identity)


class ChildIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    ageBand: Literal["3-5", "6-8", "9-12"]
    avatar: str | None = None


class Onboarding(BaseModel):
    listeningLanguages: list[str] = Field(min_length=1, max_length=5)
    uiLanguage: Literal["en", "te"] = "en"
    children: list[ChildIn] = Field(default_factory=list, max_length=8)
    moments: list[str] = Field(default_factory=list)
    adultName: str | None = Field(default=None, max_length=60)


@router.post("/household/onboarding")
def onboarding(payload: Onboarding, identity: Identity = Depends(require("catalog.read")),
               db: Session = Depends(get_db)):
    household = household_for(db, identity)
    languages = list(dict.fromkeys(normalize_language(lang) for lang in payload.listeningLanguages))
    adult = next(p for p in active_profiles(household) if p.kind == "adult")
    adult.listening_languages = languages
    if payload.adultName:
        adult.name = payload.adultName.strip()
    identity.user.ui_language = payload.uiLanguage
    identity.user.listening_languages = languages
    existing = {p.name.lower() for p in active_profiles(household)}
    for index, child in enumerate(payload.children):
        if child.name.strip().lower() in existing:
            continue
        db.add(Profile(household_id=household.id, name=child.name.strip(), kind="child", age_band=child.ageBand,
                       avatar=child.avatar if child.avatar in AVATARS else AVATARS[(index + 1) % len(AVATARS)],
                       listening_languages=languages))
    household.moments = [m for m in payload.moments if m in MOMENTS] or list(MOMENTS)
    household.onboarded_at = household.onboarded_at or utcnow()
    db.commit()
    db.refresh(household)
    return household_payload(household, identity)


class ProfileIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    kind: Literal["adult", "child"] = "child"
    ageBand: Literal["3-5", "6-8", "9-12"] | None = None
    avatar: str | None = None
    listeningLanguages: list[str] | None = None


def _check_profile(payload: ProfileIn) -> None:
    if payload.kind == "child" and not payload.ageBand:
        raise HTTPException(status_code=400, detail="Choose an age band for a child profile.")
    if payload.avatar and payload.avatar not in AVATARS:
        raise HTTPException(status_code=400, detail=f"Unknown avatar. Choose one of: {', '.join(AVATARS)}.")


@router.post("/household/profiles", status_code=201)
def create_profile(payload: ProfileIn, x_parent_pin: str | None = Header(None),
                   identity: Identity = Depends(require("catalog.read")), db: Session = Depends(get_db)):
    household = household_for(db, identity)
    require_parent(household, x_parent_pin)
    _check_profile(payload)
    if len(active_profiles(household)) >= 8:
        raise HTTPException(status_code=409, detail="A household can have up to 8 listener profiles.")
    profile = Profile(household_id=household.id, name=payload.name.strip(), kind=payload.kind,
                      age_band=payload.ageBand if payload.kind == "child" else None,
                      avatar=payload.avatar or AVATARS[len(household.profiles) % len(AVATARS)],
                      listening_languages=[normalize_language(x) for x in (payload.listeningLanguages
                                                                           or identity.user.listening_languages)])
    db.add(profile)
    db.commit()
    return profile_payload(profile)


def _own_profile(db: Session, household: Household, profile_id: int) -> Profile:
    profile = db.get(Profile, profile_id)
    if not profile or profile.household_id != household.id or profile.deleted_at:
        raise HTTPException(status_code=404, detail="Profile not found.")
    return profile


@router.patch("/household/profiles/{profile_id}")
def update_profile(profile_id: int, payload: ProfileIn, x_parent_pin: str | None = Header(None),
                   identity: Identity = Depends(require("catalog.read")), db: Session = Depends(get_db)):
    household = household_for(db, identity)
    require_parent(household, x_parent_pin)
    _check_profile(payload)
    profile = _own_profile(db, household, profile_id)
    if profile.kind == "adult" and payload.kind == "child" and sum(
            p.kind == "adult" for p in active_profiles(household)) == 1:
        raise HTTPException(status_code=409, detail="A household needs at least one adult profile.")
    profile.name, profile.kind = payload.name.strip(), payload.kind
    profile.age_band = payload.ageBand if payload.kind == "child" else None
    profile.avatar = payload.avatar or profile.avatar
    if payload.listeningLanguages:
        profile.listening_languages = [normalize_language(x) for x in payload.listeningLanguages]
    db.commit()
    return profile_payload(profile)


@router.delete("/household/profiles/{profile_id}")
def delete_profile(profile_id: int, x_parent_pin: str | None = Header(None),
                   identity: Identity = Depends(require("catalog.read")), db: Session = Depends(get_db)):
    household = household_for(db, identity)
    require_parent(household, x_parent_pin)
    profile = _own_profile(db, household, profile_id)
    if profile.kind == "adult" and sum(p.kind == "adult" for p in active_profiles(household)) == 1:
        raise HTTPException(status_code=409, detail="A household needs at least one adult profile.")
    profile.deleted_at = utcnow()
    for model in (ListenerFavorite, ListeningProgress, ListeningDaily):
        db.query(model).filter(model.profile_id == profile.id).delete()
    db.commit()
    return {"ok": True}


class PinChange(BaseModel):
    pin: str | None = None  # None removes the PIN
    currentPin: str | None = None


@router.post("/household/pin")
def set_pin(payload: PinChange, request: Request, x_parent_pin: str | None = Header(None),
            identity: Identity = Depends(require("catalog.read")), db: Session = Depends(get_db)):
    household = household_for(db, identity)
    require_parent(household, payload.currentPin or x_parent_pin)
    household.parental_pin_hash = hash_pin(payload.pin) if payload.pin else None
    audit(db, "parental-pin.set" if payload.pin else "parental-pin.removed", request, identity.user.id)
    db.commit()
    return {"hasParentPin": bool(household.parental_pin_hash)}


class PinCheck(BaseModel):
    pin: str


@router.post("/household/pin/verify")
def verify_pin(payload: PinCheck, identity: Identity = Depends(require("catalog.read")),
               db: Session = Depends(get_db)):
    from .. import ratelimit
    ratelimit.check(f"parent-pin:{identity.user.id}", 10, 15 * 60)  # 4 digits: rate limiting is what protects it
    return {"ok": pin_ok(household_for(db, identity), payload.pin)}


@router.get("/household/stats")
def family_stats(today: str | None = None, x_parent_pin: str | None = Header(None),
                 identity: Identity = Depends(require("catalog.read")), db: Session = Depends(get_db)):
    household = household_for(db, identity)
    require_parent(household, x_parent_pin)
    day = local_day(today)
    return {"profiles": [{**profile_payload(p), "stats": profile_stats(db, p.id, day)} for p in active_profiles(household)]}


class Preferences(BaseModel):
    uiLanguage: Literal["en", "te"] | None = None
    moments: list[str] | None = None


@router.patch("/me/preferences")
def preferences(payload: Preferences, identity: Identity = Depends(require("catalog.read")),
                db: Session = Depends(get_db)):
    household = household_for(db, identity)
    if payload.uiLanguage:
        identity.user.ui_language = payload.uiLanguage
    if payload.moments is not None:
        household.moments = [m for m in payload.moments if m in MOMENTS]
    db.commit()
    return household_payload(household, identity)


@router.get("/me/export")
def export_data(x_parent_pin: str | None = Header(None), identity: Identity = Depends(require("catalog.read")),
                db: Session = Depends(get_db)):
    household = household_for(db, identity)
    require_parent(household, x_parent_pin)
    user = identity.user
    profiles = active_profiles(household)
    ids = [p.id for p in profiles]
    return {
        "exportedAt": iso(utcnow()),
        "account": {"email": user.email, "username": user.username, "displayName": user.display_name,
                    "role": user.role, "uiLanguage": user.ui_language, "createdAt": iso(user.created_at)},
        "profiles": [profile_payload(p) for p in profiles],
        "favorites": [{"profileId": f.profile_id, "storyId": f.audio_asset_id, "savedAt": iso(f.created_at)}
                      for f in db.scalars(select(ListenerFavorite).where(ListenerFavorite.profile_id.in_(ids)))],
        "listening": [{"profileId": p.profile_id, "storyId": p.audio_asset_id, "seconds": round(p.seconds_listened),
                       "position": round(p.last_position), "completed": p.completed,
                       "lastListenedAt": iso(p.last_listened_at)}
                      for p in db.scalars(select(ListeningProgress).where(ListeningProgress.profile_id.in_(ids)))],
        "dailyListening": [{"profileId": d.profile_id, "day": d.day.isoformat(), "seconds": round(d.seconds)}
                           for d in db.scalars(select(ListeningDaily).where(ListeningDaily.profile_id.in_(ids)))],
    }


class DeleteAccount(BaseModel):
    confirm: str


@router.post("/me/delete")
def delete_account(payload: DeleteAccount, request: Request, response: Response,
                   x_parent_pin: str | None = Header(None), identity: Identity = Depends(require("catalog.read")),
                   db: Session = Depends(get_db)):
    """In-app account deletion (App Store requirement). Personal data is removed immediately; the row stays
    anonymized so audit and payment records keep their references."""
    if identity.role != "listener" and identity.role != "parent":
        raise HTTPException(status_code=409, detail="Staff and narrator accounts are closed by an administrator.")
    if payload.confirm.strip().upper() != "DELETE":
        raise HTTPException(status_code=400, detail='Type DELETE to confirm.')
    household = household_for(db, identity)
    require_parent(household, x_parent_pin)
    user: User = identity.user
    now = utcnow()
    ids = [p.id for p in household.profiles]
    for model in (ListenerFavorite, ListeningProgress, ListeningDaily):
        db.query(model).filter(model.profile_id.in_(ids)).delete()
    db.delete(household)
    db.execute(update(AuthSession).where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
               .values(revoked_at=now))
    audit(db, "account.deleted", request, user.id)
    user.email = None
    user.username = None
    user.display_name = None
    user.password_hash = None
    user.totp_secret = None
    user.disabled_at = now
    db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}
