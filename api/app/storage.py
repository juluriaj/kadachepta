"""Media storage behind one interface.

Keys are forward-slash paths such as ``originals/<asset>/<file>.mp3`` or
``renditions/<asset>/v1/standard.m4a``. Keys under ``legacy/`` resolve to the
read-only prototype audio folder so 3 GB of originals are not copied.
Clients only ever receive short-lived signed URLs (``/media/<key>?e=&s=``).
"""

from __future__ import annotations

import mimetypes
import shutil
import urllib.parse
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Protocol

from .config import Settings, get_settings
from .security import sign_media

LEGACY_PREFIX = "legacy/"

mimetypes.add_type("audio/mp4", ".m4a")
mimetypes.add_type("application/json", ".json")


class StorageError(Exception):
    pass


def safe_key(key: str) -> str:
    path = PurePosixPath(key)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise StorageError(f"Unsafe storage key: {key!r}")
    return path.as_posix()


def content_type(key: str) -> str:
    return mimetypes.guess_type(key)[0] or "application/octet-stream"


class Storage(Protocol):
    def path(self, key: str) -> Path: ...
    def exists(self, key: str) -> bool: ...
    def put_stream(self, key: str, stream: BinaryIO) -> int: ...
    def put_bytes(self, key: str, data: bytes) -> int: ...
    def delete(self, key: str) -> None: ...
    def size(self, key: str) -> int: ...


class LocalStorage:
    def __init__(self, settings: Settings):
        self.root = settings.media_root
        self.legacy_root = settings.legacy_audio_root

    def path(self, key: str) -> Path:
        key = safe_key(key)
        if key.startswith(LEGACY_PREFIX):
            base, relative = self.legacy_root, key[len(LEGACY_PREFIX):]
        else:
            base, relative = self.root, key
        candidate = (base / relative).resolve()
        if base.resolve() not in candidate.parents:
            raise StorageError(f"Key escapes storage root: {key!r}")
        return candidate

    def exists(self, key: str) -> bool:
        return self.path(key).is_file()

    def size(self, key: str) -> int:
        return self.path(key).stat().st_size

    def put_stream(self, key: str, stream: BinaryIO) -> int:
        if safe_key(key).startswith(LEGACY_PREFIX):
            raise StorageError("The legacy audio folder is read-only.")
        target = self.path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_name(target.name + ".partial")
        with partial.open("wb") as handle:
            shutil.copyfileobj(stream, handle, length=1024 * 1024)
        partial.replace(target)
        return target.stat().st_size

    def put_bytes(self, key: str, data: bytes) -> int:
        import io
        return self.put_stream(key, io.BytesIO(data))

    def delete(self, key: str) -> None:
        if safe_key(key).startswith(LEGACY_PREFIX):
            raise StorageError("The legacy audio folder is read-only.")
        self.path(key).unlink(missing_ok=True)


_storage: Storage | None = None


def get_storage() -> Storage:
    global _storage
    if _storage is None:
        settings = get_settings()
        if settings.storage_backend != "local":
            raise StorageError(
                f"Storage backend {settings.storage_backend!r} is not available yet; "
                "the Lightsail bucket backend arrives in Phase 6.")
        _storage = LocalStorage(settings)
    return _storage


def media_url(key: str | None, version: str | int | None = None) -> str | None:
    if not key:
        return None
    settings = get_settings()
    expires, signature = sign_media(key, settings.secret_key, settings.media_url_ttl_seconds)
    query = {"e": expires, "s": signature}
    if version is not None:
        query["v"] = version
    return f"/media/{urllib.parse.quote(key)}?{urllib.parse.urlencode(query)}"
