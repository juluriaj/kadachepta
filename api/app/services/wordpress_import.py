"""Bring listener accounts over from the old WordPress site (a CSV export of its users).

Any of these exports works (docs/lightsail-pilot.md, "Importing the WordPress users"):
  - phpMyAdmin: table wp_users > Export > CSV, with "Put columns names in the first row" ticked
  - WP-CLI: wp user list --fields=ID,user_login,user_email,user_pass,display_name,user_registered,roles --format=csv
  - an export plugin's CSV (columns such as user_email, user_login, display_name, first_name, last_name)

Everyone becomes a listener. An email that already has an account here is left exactly as it is. When the file has
password hashes (user_pass), people keep their WordPress password; security.verify_password checks it and replaces
it with argon2 at their first sign-in, with their WordPress username or their email. Without one they need an email
code (KC_EMAIL_ENABLED) or a password from "cli set-password". Nobody is emailed.
"""

from __future__ import annotations

import csv
import io
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime

from email_validator import EmailNotValidError, validate_email
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import AuditLog, User
from ..security import is_wordpress_hash

# Column names seen in WordPress exports, compared after lowercasing and turning "_" and "-" into spaces.
COLUMNS = {
    "email": ("user email", "email", "e mail", "email address"),
    "login": ("user login", "username", "login", "user name"),
    "display_name": ("display name", "name", "nickname"),
    "first_name": ("first name",),
    "last_name": ("last name",),
    "password_hash": ("user pass", "password hash"),
    "registered": ("user registered", "registered", "registration date", "date registered"),
    "roles": ("roles", "role"),
}
_USERNAME = re.compile(r"^[A-Za-z0-9._-]{2,64}$")


class ImportProblem(Exception):
    pass


@dataclass
class ImportPlan:
    rows: int = 0
    new_users: list[User] = field(default_factory=list)
    existing: int = 0
    repeated: int = 0
    invalid: list[tuple[int, str]] = field(default_factory=list)  # (line, reason)
    usernames_dropped: int = 0
    roles: Counter = field(default_factory=Counter)
    years: Counter = field(default_factory=Counter)
    domains: Counter = field(default_factory=Counter)

    @property
    def with_password(self) -> int:
        return sum(1 for user in self.new_users if user.password_hash)


def decode_export(data: bytes) -> tuple[str, str | None]:
    """The file's text and, when it isn't UTF-8 (Excel's "CSV" on Windows), a warning about names."""
    try:
        return data.decode("utf-8-sig"), None
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace"), (
            "The file isn't UTF-8, so names in Telugu or other scripts may be garbled. Export again as UTF-8 "
            "(phpMyAdmin and WP-CLI do this by default; in Excel use \"CSV UTF-8\").")


def read_export(text: str) -> list[tuple[int, dict[str, str]]]:
    """(line number, fields) for every non-empty row, with fields named as in COLUMNS."""
    try:  # phpMyAdmin uses commas, its "CSV for MS Excel" semicolons, some plugins tabs
        dialect = csv.Sniffer().sniff(text[:8192], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    header = next(reader, None) or []
    names = [re.sub(r"[_-]+", " ", cell).strip().lower() for cell in header]
    columns = {}
    for key, aliases in COLUMNS.items():
        found = [names.index(alias) for alias in aliases if alias in names]
        if found:
            columns[key] = found[0]
    if "email" not in columns:
        raise ImportProblem(
            "No email column in the first row. Found: " + (", ".join(cell for cell in header if cell) or "nothing")
            + ". In phpMyAdmin, tick \"Put columns names in the first row\" when exporting wp_users.")
    rows = []
    for line, row in enumerate(reader, start=2):
        if not any(cell.strip() for cell in row):
            continue
        values = {key: row[index].strip() for key, index in columns.items() if index < len(row)}
        rows.append((line, {key: "" if value == "NULL" else value for key, value in values.items()}))
    return rows


def _registered(value: str) -> datetime | None:
    try:  # WordPress stores user_registered in UTC; "0000-00-00 00:00:00" means unknown
        return datetime.strptime(value[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
    except ValueError:
        return None


def plan_import(db: Session, rows: list[tuple[int, dict[str, str]]]) -> ImportPlan:
    plan = ImportPlan(rows=len(rows))
    taken_emails = {email for email in db.scalars(select(func.lower(User.email)).where(User.email.is_not(None)))}
    taken_names = {name for name in db.scalars(select(func.lower(User.username)).where(User.username.is_not(None)))}
    seen: set[str] = set()
    for line, values in rows:
        try:
            email = validate_email(values.get("email", ""), check_deliverability=False).normalized.lower()
        except EmailNotValidError as error:
            plan.invalid.append((line, f"{values.get('email') or 'no email'}: {error}"))
            continue
        if email in seen:
            plan.repeated += 1
            continue
        seen.add(email)
        if email in taken_emails:
            plan.existing += 1
            continue

        login = values.get("login", "")
        username = login if _USERNAME.match(login) and login.lower() not in taken_names else None
        if login and not username:
            plan.usernames_dropped += 1  # taken here, or has spaces or "@": they sign in with their email
        if username:
            taken_names.add(username.lower())
        full_name = " ".join(part for part in (values.get("first_name"), values.get("last_name")) if part)
        display_name = (values.get("display_name") or full_name or login or email.split("@")[0])[:120]
        password_hash = values.get("password_hash", "")
        registered = _registered(values.get("registered", ""))

        plan.new_users.append(User(
            email=email, username=username, display_name=display_name, role="listener",
            password_hash=password_hash if is_wordpress_hash(password_hash) else None,
            **({"created_at": registered} if registered else {})))
        plan.domains[email.rsplit("@", 1)[1]] += 1
        plan.years[str(registered.year) if registered else "unknown"] += 1
        for role in re.split(r"[,;|\s]+", values.get("roles", "")):
            if role:
                plan.roles[role] += 1
    return plan


def apply_import(db: Session, plan: ImportPlan, source: str) -> None:
    db.add_all(plan.new_users)
    db.flush()
    db.add(AuditLog(action="accounts.imported", detail={
        "source": "wordpress", "file": source, "created": len(plan.new_users),
        "userIds": [user.id for user in plan.new_users]}))
    db.commit()


def report(plan: ImportPlan) -> str:
    new = len(plan.new_users)
    lines = [
        f"WordPress export: {plan.rows} rows",
        f"  new listener accounts:   {new}  ({plan.with_password} keep their WordPress password, "
        f"{new - plan.with_password} without a password)",
        f"  already have an account: {plan.existing}  (left unchanged)",
        f"  repeated in the file:    {plan.repeated}",
        f"  invalid email:           {len(plan.invalid)}",
    ]
    lines += [f"    line {line}: {reason}" for line, reason in plan.invalid[:10]]
    if len(plan.invalid) > 10:
        lines.append(f"    … and {len(plan.invalid) - 10} more")
    if plan.usernames_dropped:
        lines.append(f"  usernames not kept:      {plan.usernames_dropped}  (taken here, or with spaces or @; "
                     "they sign in with their email)")

    def top(counter: Counter, limit: int = 8) -> str:
        return ", ".join(f"{key} {count}" for key, count in counter.most_common(limit)) or "none in the file"

    lines += [f"WordPress roles: {top(plan.roles)}",
              f"Registered: {', '.join(f'{year} {plan.years[year]}' for year in sorted(plan.years))}",
              f"Email domains: {top(plan.domains)}",
              "Check for spam sign-ups before applying: many accounts from one odd domain or one burst year."]
    return "\n".join(lines)
