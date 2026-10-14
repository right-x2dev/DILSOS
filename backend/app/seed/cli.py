"""Seed commands.

    python -m app.seed.cli demo-user
"""

from __future__ import annotations

import argparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.models import User
from app.db.session import get_sessionmaker


def ensure_demo_user(db: Session) -> User:
    s = get_settings()
    email = s.demo_user_email.lower()
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(
            email=email,
            display_name="Demo Planner",
            password_hash=hash_password(s.demo_user_password),
            role="planner",
            is_demo=True,
        )
        db.add(user)
        db.flush()
    return user


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="dilsos-seed")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("demo-user")
    args = p.parse_args(argv)
    with get_sessionmaker()() as db:
        if args.cmd == "demo-user":
            u = ensure_demo_user(db)
            db.commit()
            print(f"demo user ready: {u.email} (id={u.id})")


if __name__ == "__main__":
    main()
