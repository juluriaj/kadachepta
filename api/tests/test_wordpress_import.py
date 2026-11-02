from sqlalchemy import select

from app import cli
from app.models import AuditLog, User
from app.security import verify_password
from app.services.wordpress_import import ImportProblem, decode_export, plan_import, read_export

from .conftest import login, make_user

# Reference hashes of "Kathalu-2019!" made outside this code: WordPress 6.8's formula and password_hash() in PHP 8.3,
# and passlib's phpass (the format of WordPress before 6.8).
PASSWORD = "Kathalu-2019!"
WP_BCRYPT = "$wp$2y$10$fa78j8aPkKjDcsJB8WcD0.mYB32JnuJX.5iwKPN/Hqo/6mzCDNIDq"
PLAIN_BCRYPT = "$2y$10$wNtNjQwKfVI6VvoIsmFj8.XYIJKSwpLdJXD1DLybu1s8yGLCDZA5S"
PHPASS = "$P$BXy7KpQ2zLEzOQS1AHZ0cqFjAdsPzP0"
PHPASS_TELUGU = "$P$BaB3dE5gHInn7AN1E1ODsUXLM3zPnI0"  # password "కథ-story"
MD5 = "1a41bfafb3f25ed26c66cb50c2f2f607"

EXPORT = f"""ID;user_login;user_pass;user_nicename;user_email;user_registered;display_name;roles
1;sita;{WP_BCRYPT};sita;Sita@Example.com;2019-06-01 10:00:00;సీత;subscriber
2;ravi kumar;{PHPASS};ravi;ravi@example.in;2021-01-15 08:30:00;;subscriber
3;listener;NULL;listener;taken@example.com;0000-00-00 00:00:00;Taken;subscriber
4;dup;{MD5};dup;sita@example.com;2020-01-01 00:00:00;Again;subscriber
5;broken;;broken;not-an-email;2020-01-01 00:00:00;Broken;subscriber
6;gopal;;gopal;gopal@example.org;2022-03-03 03:03:03;Gopal;administrator
"""


def test_wordpress_password_hashes_are_verified_like_wordpress():
    for stored in (WP_BCRYPT, PLAIN_BCRYPT, PHPASS, MD5):
        assert verify_password(PASSWORD, stored) == (True, True), stored  # valid, and upgraded to argon2
        assert verify_password("kathalu-2019!", stored)[0] is False, stored
    assert verify_password("కథ-story", PHPASS_TELUGU)[0] is True
    assert verify_password(PASSWORD, "$P$Z" + PHPASS[4:])[0] is False  # 2^61 rounds: refused, not computed


def test_signing_in_with_a_wordpress_password_upgrades_it(client, db):
    db.add(User(username="wp-user", email="wp@example.com", role="listener", password_hash=PHPASS))
    db.commit()
    login(client, "wp@example.com", PASSWORD)
    db.expire_all()
    assert db.scalars(select(User).where(User.username == "wp-user")).one().password_hash.startswith("$argon2")
    assert client.post("/api/login", json={"username": "wp-user", "password": "wrong"}).status_code == 401


def test_export_columns_are_found_in_any_common_layout():
    text, warning = decode_export(("﻿" + "E-mail,First Name,Last Name\nrama@example.com,Rama,Rao\n").encode())
    assert warning is None and read_export(text) == [(2, {"email": "rama@example.com", "first_name": "Rama",
                                                         "last_name": "Rao"})]
    assert decode_export("Email\nlakshmi@example.com\n".encode("cp1252"))[1] is None  # plain ASCII is fine
    assert "garbled" in decode_export("Email,Name\nx@example.com,Jos\xe9\n".encode("cp1252"))[1]
    try:
        read_export("ID,user_login\n1,sita\n")
    except ImportProblem as problem:
        assert "No email column" in str(problem) and "ID, user_login" in str(problem)
    else:
        raise AssertionError("an export without emails must be refused")


def test_plan_keeps_existing_accounts_and_reports_problems(db):
    make_user(db, "listener", "listener", email="taken@example.com")
    plan = plan_import(db, read_export(EXPORT))
    by_email = {user.email: user for user in plan.new_users}
    assert sorted(by_email) == ["gopal@example.org", "ravi@example.in", "sita@example.com"]
    assert plan.existing == 1 and plan.repeated == 1 and [line for line, _ in plan.invalid] == [6]
    assert by_email["sita@example.com"].display_name == "సీత" and by_email["sita@example.com"].username == "sita"
    assert by_email["sita@example.com"].created_at.year == 2019
    assert by_email["ravi@example.in"].username is None and plan.usernames_dropped == 1  # has a space
    assert by_email["ravi@example.in"].display_name == "ravi kumar"
    assert by_email["gopal@example.org"].role == "listener" and by_email["gopal@example.org"].password_hash is None
    assert plan.with_password == 2 and plan.roles["administrator"] == 1


def test_the_command_reports_first_and_creates_listeners_only_with_apply(db, tmp_path, capsys):
    export = tmp_path / "wp_users.csv"
    export.write_text(EXPORT, encoding="utf-8")
    cli.main(["import-wordpress", str(export)])
    assert "Dry run" in capsys.readouterr().out and db.scalars(select(User)).first() is None

    cli.main(["import-wordpress", str(export), "--apply"])
    out = capsys.readouterr().out
    assert "new listener accounts:   4  (2 keep their WordPress password, 2 without a password)" in out
    assert {user.role for user in db.scalars(select(User))} == {"listener"}
    assert db.scalars(select(AuditLog).where(AuditLog.action == "accounts.imported")).one().detail["created"] == 4

    cli.main(["import-wordpress", str(export), "--apply"])  # running it again changes nothing
    assert "new listener accounts:   0" in capsys.readouterr().out
    assert len(db.scalars(select(User)).all()) == 4

    # Someone imported without a password (or who forgot theirs) gets one from the operator, found by email.
    cli.main(["set-password", "Gopal@Example.org", "--password", "a new password"])
    db.expire_all()
    gopal = db.scalars(select(User).where(User.email == "gopal@example.org")).one()
    assert verify_password("a new password", gopal.password_hash)[0]
