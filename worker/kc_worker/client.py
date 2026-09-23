"""HTTP client for the KathaChepta worker API (standard library only)."""

from __future__ import annotations

import json
import shutil
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


class ApiError(RuntimeError):
    def __init__(self, status: int, message: str):
        super().__init__(f"HTTP {status}: {message}")
        self.status = status


class ApiClient:
    def __init__(self, base_url: str, token: str, timeout: float = 60):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def _request(self, method: str, path: str, body: Any = None, *, raw: bytes | None = None,
                 content_type: str = "application/json", timeout: float | None = None) -> tuple[int, Any]:
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        request = urllib.request.Request(self.base_url + path, data=data, method=method, headers={
            "Authorization": f"Worker {self.token}", "Content-Type": content_type})
        try:
            with urllib.request.urlopen(request, timeout=timeout or self.timeout) as response:
                payload = response.read()
                return response.status, (json.loads(payload) if payload else None)
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", "replace")
            try:
                detail = json.loads(detail).get("error") or detail
            except (ValueError, AttributeError):
                pass
            raise ApiError(error.code, str(detail)[:500]) from None

    def lease(self, capabilities: list[str], info: dict[str, Any]) -> dict[str, Any] | None:
        status, body = self._request("POST", "/api/worker/lease", {"capabilities": capabilities, "info": info})
        return body if status == 200 else None

    def heartbeat(self, job_id: int) -> None:
        self._request("POST", f"/api/worker/jobs/{job_id}/heartbeat", {})

    def upload(self, job_id: int, name: str, path: Path) -> str:
        data = path.read_bytes()
        _, body = self._request("POST", f"/api/worker/jobs/{job_id}/files?name={name}", raw=data,
                                content_type="application/octet-stream", timeout=600)
        return body["key"]

    def complete(self, job_id: int, result: dict[str, Any], log_tail: str | None = None) -> None:
        self._request("POST", f"/api/worker/jobs/{job_id}/complete", {"result": result, "logTail": log_tail})

    def fail(self, job_id: int, error: str, *, retryable: bool = True, log_tail: str | None = None) -> dict:
        _, body = self._request("POST", f"/api/worker/jobs/{job_id}/fail",
                                {"error": error, "retryable": retryable, "logTail": log_tail})
        return body

    def download(self, url: str, target: Path) -> Path:
        if url.startswith("/"):
            url = self.base_url + url
        target.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(url, timeout=600) as response, target.open("wb") as handle:
            shutil.copyfileobj(response, handle, length=1024 * 1024)
        return target


class Heartbeat:
    """Keeps a job lease alive while a long handler runs."""

    def __init__(self, client: ApiClient, job_id: int, interval: float):
        self.client, self.job_id, self.interval = client, job_id, interval
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._thread.join(timeout=5)

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                self.client.heartbeat(self.job_id)
            except Exception:  # noqa: BLE001 - a missed heartbeat only risks the lease expiring
                pass
