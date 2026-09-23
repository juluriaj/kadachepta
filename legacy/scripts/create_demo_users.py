"""Create local development users for each KathaChepta role."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from editor_server import ensure_auth_schema, hash_password

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "catalog" / "kadachepta.db"
DEMO_PASSWORD = "change-me"
DEMO_USERS = (
    ("listener", "listener"),
    ("parent", "parent"),
    ("narrator", "narrator"),
    ("editor", "editor"),
    ("admin", "admin"),
)


def main() -> None:
    with sqlite3.connect(DB) as connection:
        ensure_auth_schema(connection)
        for username, role in DEMO_USERS:
            existing = connection.execute(
                "SELECT id FROM editor_users WHERE username=?",
                (username,),
            ).fetchone()
            if existing:
                connection.execute(
                    "UPDATE editor_users SET role=? WHERE username=?",
                    (role, username),
                )
            else:
                connection.execute(
                    """
                    INSERT INTO editor_users
                        (username, password_hash, role, created_at)
                    VALUES (?, ?, ?, datetime('now'))
                    """,
                    (username, hash_password(DEMO_PASSWORD), role),
                )
        connection.commit()

    print("Created or updated local demo users:")
    for username, role in DEMO_USERS:
        print(f"  {username:<8} role={role:<8} password={DEMO_PASSWORD}")


if __name__ == "__main__":
    main()
