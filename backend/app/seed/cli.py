"""Seed commands (idempotent).

python -m app.seed.cli demo-user
python -m app.seed.cli demo-scenarios          # normal_day, peak_demand, vehicle_breakdown, warehouse_bottleneck
python -m app.seed.cli export-datasets OUT_DIR # write generator outputs as JSON (datasets/synthetic)
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import hash_password
from app.db import models as m
from app.db.session import get_sessionmaker
from app.seed.generator import DEMO_SCENARIOS, generate


def ensure_demo_user(db: Session) -> m.User:
    s = get_settings()
    email = s.demo_user_email.lower()
    user = db.scalar(select(m.User).where(m.User.email == email))
    if user is None:
        user = m.User(
            email=email,
            display_name="Demo Planner",
            password_hash=hash_password(s.demo_user_password),
            role="planner",
            is_demo=True,
        )
        db.add(user)
        db.flush()
    return user


def ensure_demo_scenarios(db: Session, user_id: int | None = None) -> list[m.Scenario]:
    from app.services.scenario_store import persist_definition

    out = []
    for name, cfg in DEMO_SCENARIOS.items():
        existing = db.scalar(
            select(m.Scenario)
            .join(m.Facility, m.Facility.id == m.Scenario.facility_id)
            .where(m.Scenario.name == name, m.Facility.code == cfg.facility_code)
        )
        if existing is not None:
            out.append(existing)
            continue
        out.append(persist_definition(db, generate(cfg), user_id))
        db.flush()
    return out


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="dilsos-seed")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("demo-user")
    sub.add_parser("demo-scenarios")
    ex = sub.add_parser("export-datasets")
    ex.add_argument("out_dir")
    args = p.parse_args(argv)
    if args.cmd == "export-datasets":
        out = Path(args.out_dir)
        out.mkdir(parents=True, exist_ok=True)
        for name, cfg in DEMO_SCENARIOS.items():
            (out / f"{name}.json").write_text(
                json.dumps(generate(cfg).model_dump(mode="json"), ensure_ascii=False, indent=1), encoding="utf-8"
            )
            print(f"wrote {out / (name + '.json')}")
        return
    with get_sessionmaker()() as db:
        if args.cmd == "demo-user":
            u = ensure_demo_user(db)
            db.commit()
            print(f"demo user ready: {u.email} (id={u.id})")
        elif args.cmd == "demo-scenarios":
            u = ensure_demo_user(db)
            scs = ensure_demo_scenarios(db, u.id)
            db.commit()
            for sc in scs:
                print(f"scenario #{sc.id}: {sc.name}")


if __name__ == "__main__":
    main()
