"""Worker loop: python -m kc_worker

Environment:
  KC_API_URL                 e.g. http://api:8000 (Docker) or http://localhost:8080 (desktop)
  KC_WORKER_TOKEN            token registered for this worker
  KC_WORKER_CAPABILITIES     subset to run here, e.g. "media,stt" or "llm,image"
  KC_WORKDIR                 scratch directory (default: system temp)
Handler-specific settings are documented in each handler module.
"""

from __future__ import annotations

import logging
import os
import platform
import shutil
import signal
import sys
import tempfile
import time
import traceback
from pathlib import Path

from .client import ApiClient, ApiError, Heartbeat
from .handlers import HANDLERS, JobContext, PermanentError

log = logging.getLogger("kc_worker")
_stopping = False


def _stop(*_):
    global _stopping
    _stopping = True
    log.info("Stopping after the current job...")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    api_url = os.environ.get("KC_API_URL", "http://localhost:8080")
    token = os.environ.get("KC_WORKER_TOKEN", "")
    capabilities = [c.strip() for c in os.environ.get("KC_WORKER_CAPABILITIES", "media,stt").split(",") if c.strip()]
    workdir = Path(os.environ.get("KC_WORKDIR") or tempfile.gettempdir()) / "kc-worker"
    if not token:
        log.error("KC_WORKER_TOKEN is not set. Create one with: docker compose exec api python -m app.cli create-worker <name> <caps>")
        return 2
    unknown = [c for c in capabilities if c not in {h.capability for h in HANDLERS.values()}]
    if unknown:
        log.error("Unknown capabilities %s. Known: %s", unknown, sorted({h.capability for h in HANDLERS.values()}))
        return 2
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    client = ApiClient(api_url, token)

    def describe() -> dict:
        # Sent with each lease; the studio settings page shows it (for example the models LM Studio has).
        return {"host": platform.node(), "python": sys.version.split()[0], "capabilities": capabilities,
                **{name: handler.describe() for name, handler in HANDLERS.items() if handler.capability in capabilities}}

    info, described_at = describe(), time.monotonic()
    log.info("Worker started: api=%s capabilities=%s", api_url, capabilities)
    idle, last_type = 1.0, None
    while not _stopping:
        if time.monotonic() - described_at > 300:
            info, described_at = describe(), time.monotonic()
        try:
            job = client.lease(capabilities, info, last_type)  # same kind of job next: fewer GPU model swaps
        except (ApiError, OSError) as error:
            log.warning("Lease failed (%s); retrying in %.0fs", error, min(idle * 2, 30))
            time.sleep(min(idle := idle * 2, 30))
            continue
        if not job:
            time.sleep(min(idle := min(idle * 1.5, 10), 10))
            continue
        idle, last_type = 1.0, job["type"]
        run_job(client, job, workdir)
    return 0


def run_job(client: ApiClient, job: dict, workdir: Path) -> None:
    handler = HANDLERS[job["type"]]
    scratch = workdir / f"job-{job['id']}"
    scratch.mkdir(parents=True, exist_ok=True)
    context = JobContext(client=client, job=job, scratch=scratch)
    started = time.monotonic()
    log.info("Job %s %s asset=%s attempt=%s", job["id"], job["type"], job["inputs"].get("assetId"), job["attempt"])
    try:
        with Heartbeat(client, job["id"], interval=max(job.get("leaseSeconds", 900) / 3, 30)):
            result = handler.run(context)
        client.complete(job["id"], result, context.log_tail())
        log.info("Job %s done in %.1fs", job["id"], time.monotonic() - started)
    except PermanentError as error:
        log.error("Job %s failed permanently: %s", job["id"], error)
        _report_failure(client, job, str(error), False, context)
    except Exception as error:  # noqa: BLE001 - report every failure to the API with diagnostics
        detail = f"{type(error).__name__}: {error}"
        context.log(traceback.format_exc())
        log.error("Job %s failed: %s", job["id"], detail)
        _report_failure(client, job, detail, True, context)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def _report_failure(client: ApiClient, job: dict, error: str, retryable: bool, context: JobContext) -> None:
    try:
        client.fail(job["id"], error, retryable=retryable, log_tail=context.log_tail())
    except (ApiError, OSError) as report_error:
        log.error("Could not report failure for job %s: %s (the lease will expire and the job will retry)",
                  job["id"], report_error)


if __name__ == "__main__":
    raise SystemExit(main())
