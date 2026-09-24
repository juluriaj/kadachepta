"""Operator commands: python -m app.cli <command> ...

  create-user <username> <role> [--email E] [--password P]   (prints a generated password if none given)
  set-password <username> [--password P]
  set-role <username> <role>
  reset-mfa <username>
  create-worker <name> <cap1,cap2>                             (prints the worker token once)
  seed-demo                                                    (development only: demo accounts)
"""

from __future__ import annotations

import argparse
import secrets
import sys

from sqlalchemy import func, select

from .config import get_settings
from .db import get_sessionmaker
from .models import NarratorProfile, User, Worker
from .security import ROLE_PERMISSIONS, hash_password, new_token, token_hash

DEMO_ACCOUNTS = [("listener", "listener"), ("parent", "parent"), ("narrator", "narrator"),
                 ("editor", "editor"), ("admin", "admin")]


def _user(db, username: str) -> User:
    user = db.scalars(select(User).where(func.lower(User.username) == username.lower())).first()
    if not user:
        sys.exit(f"No user named {username!r}.")
    return user


def _check_role(role: str) -> None:
    if role not in ROLE_PERMISSIONS:
        sys.exit(f"Unknown role {role!r}. Roles: {', '.join(ROLE_PERMISSIONS)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create-user")
    create.add_argument("username")
    create.add_argument("role")
    create.add_argument("--email")
    create.add_argument("--password")
    password = sub.add_parser("set-password")
    password.add_argument("username")
    password.add_argument("--password")
    role = sub.add_parser("set-role")
    role.add_argument("username")
    role.add_argument("role")
    mfa = sub.add_parser("reset-mfa")
    mfa.add_argument("username")
    worker = sub.add_parser("create-worker")
    worker.add_argument("name")
    worker.add_argument("capabilities")
    sub.add_parser("seed-demo")
    args = parser.parse_args(argv)

    with get_sessionmaker()() as db:
        if args.command == "create-user":
            _check_role(args.role)
            secret = args.password or secrets.token_urlsafe(12)
            user = User(username=args.username, email=args.email, role=args.role, display_name=args.username,
                        password_hash=hash_password(secret))
            db.add(user)
            db.flush()
            if args.role == "narrator":
                db.add(NarratorProfile(user_id=user.id, display_name=args.username))
            db.commit()
            print(f"Created {args.role} {args.username!r}." + ("" if args.password else f" Password: {secret}"))
        elif args.command == "set-password":
            user = _user(db, args.username)
            secret = args.password or secrets.token_urlsafe(12)
            user.password_hash = hash_password(secret)
            db.commit()
            print("Password updated." + ("" if args.password else f" New password: {secret}"))
        elif args.command == "set-role":
            _check_role(args.role)
            _user(db, args.username).role = args.role
            db.commit()
            print("Role updated.")
        elif args.command == "reset-mfa":
            user = _user(db, args.username)
            user.totp_enabled, user.totp_secret = False, None
            db.commit()
            print("Two-factor authentication reset; the user enrolls again at next sign-in.")
        elif args.command == "create-worker":
            token = new_token()
            row = db.scalars(select(Worker).where(Worker.name == args.name)).first() or Worker(name=args.name)
            row.token_hash = token_hash(token)
            row.capabilities = [c.strip() for c in args.capabilities.split(",") if c.strip()]
            db.add(row)
            db.commit()
            print(f"Worker {args.name!r} token (shown once): {token}")
        elif args.command == "seed-demo":
            if get_settings().is_production:
                sys.exit("Refusing to create demo accounts in production.")
            for username, role_name in DEMO_ACCOUNTS:
                user = db.scalars(select(User).where(User.username == username)).first()
                if not user:
                    user = User(username=username, role=role_name, display_name=username)
                    db.add(user)
                user.password_hash = hash_password("change-me")
                db.flush()
                if role_name == "narrator" and not db.get(NarratorProfile, user.id):
                    db.add(NarratorProfile(user_id=user.id, display_name=username))
            db.commit()
            print("Demo accounts ready (development only): " + ", ".join(u for u, _ in DEMO_ACCOUNTS)
                  + " — password 'change-me'.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
