"""Apply an explicit human review decision to the latest teaser draft."""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Approve or reject a local teaser draft.")
    parser.add_argument("--database", type=Path, default=Path("catalog/kadachepta.db"))
    parser.add_argument("--asset-id", required=True)
    parser.add_argument("--decision", choices=("approved", "rejected"), required=True)
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--notes", default="")
    args = parser.parse_args()

    with sqlite3.connect(args.database) as connection:
        draft = connection.execute(
            """
            SELECT id FROM teaser_drafts
            WHERE audio_asset_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (args.asset_id,),
        ).fetchone()
        if not draft:
            raise SystemExit(f"No teaser draft found for {args.asset_id}.")
        connection.execute(
            """
            UPDATE teaser_drafts
            SET status = ?, reviewer = ?, review_notes = ?
            WHERE id = ?
            """,
            (args.decision, args.reviewer, args.notes or None, draft[0]),
        )
        connection.commit()
    print(f"Teaser {args.asset_id} draft {draft[0]}: {args.decision}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
