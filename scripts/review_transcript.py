"""Apply an explicit human review decision to a transcript version."""

from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Approve or reject a local transcript.")
    parser.add_argument("--database", type=Path, default=Path("catalog/kadachepta.db"))
    parser.add_argument("--asset-id", required=True)
    parser.add_argument("--version", type=int, default=1)
    parser.add_argument("--decision", choices=("approved", "rejected"), required=True)
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--notes", default="")
    args = parser.parse_args()

    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(args.database) as connection:
        transcript = connection.execute(
            "SELECT id FROM transcripts WHERE audio_asset_id = ? AND version = ?",
            (args.asset_id, args.version),
        ).fetchone()
        if not transcript:
            raise SystemExit(f"Transcript not found for {args.asset_id} version {args.version}.")
        connection.execute(
            """
            UPDATE transcripts
            SET status = ?, reviewer = ?, review_notes = ?, reviewed_at = ?
            WHERE id = ?
            """,
            (args.decision, args.reviewer, args.notes or None, now, transcript[0]),
        )
        connection.execute(
            """
            UPDATE processing_jobs
            SET status = ?, updated_at = ?, error = ?
            WHERE audio_asset_id = ? AND job_type = 'transcription'
            """,
            (args.decision, now, args.notes or None, args.asset_id),
        )
        connection.commit()
    print(f"Transcript {args.asset_id} v{args.version}: {args.decision}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
