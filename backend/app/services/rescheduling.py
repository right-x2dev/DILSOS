"""DB-level orchestration of disruption events and versioned rescheduling."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models as m
from app.optimization.common.contracts import ScheduleResult, UnservedOrder
from app.optimization.rescheduling.events import DisruptionSpec
from app.optimization.rescheduling.policies import Policy, build_policy_snapshot, recommend
from app.optimization.rescheduling.rolling_horizon import SUPPORTED_BASE
from app.services.runs import RunError, enqueue_run, load_schedule
from app.services.scenario_store import snapshot_from_row, store_snapshot


class EventConflict(ValueError):
    pass


def _fingerprint(body: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()


def record_event(
    db: Session, scenario: m.Scenario, key: str, spec: DisruptionSpec, affected_type: str | None, user_id: int | None
) -> tuple[m.DisruptionEvent, bool]:
    """Idempotent insert: same key + same payload → existing row (created=False); different payload → conflict."""
    body = {
        "event_type": spec.event_type,
        "time_min": spec.time_min,
        "affected_id": spec.affected_id,
        "payload": spec.payload,
    }
    existing = db.scalar(
        select(m.DisruptionEvent).where(
            m.DisruptionEvent.scenario_id == scenario.id, m.DisruptionEvent.idempotency_key == key
        )
    )
    if existing is not None:
        old = {
            "event_type": existing.event_type,
            "time_min": existing.event_time_min,
            "affected_id": existing.affected_code,
            "payload": {k: v for k, v in existing.payload.items() if k != "_fingerprint"},
        }
        if _fingerprint(old) != _fingerprint(body):
            raise EventConflict("idempotency key already used with a different event payload")
        return existing, False
    ev = m.DisruptionEvent(
        scenario_id=scenario.id,
        idempotency_key=key,
        event_type=spec.event_type,
        event_time_min=spec.time_min,
        affected_type=affected_type,
        affected_code=spec.affected_id,
        payload=dict(spec.payload),
        created_by=user_id,
    )
    db.add(ev)
    db.flush()
    return ev, True


def event_spec(ev: m.DisruptionEvent) -> DisruptionSpec:
    return DisruptionSpec(
        event_type=ev.event_type,
        time_min=ev.event_time_min,
        affected_id=ev.affected_code,  # type: ignore[arg-type]
        payload=dict(ev.payload),
    )


def base_result(db: Session, run: m.ScheduleRun) -> ScheduleResult:
    assigns, routes = load_schedule(db, run)
    unserved = [
        UnservedOrder(order_id=s.order_code, reason=s.unserved_reason or "", penalty=float(s.penalty or 0))
        for s in db.scalars(select(m.Shipment).where(m.Shipment.run_id == run.id, m.Shipment.status == "UNSERVED"))
    ]
    return ScheduleResult(
        run_id=str(run.id),
        algorithm=run.algorithm,
        problem_type=run.problem_type,
        status="FEASIBLE",  # type: ignore[arg-type]
        assignments=assigns,
        routes=routes,
        unserved_order_ids=sorted(u.order_id for u in unserved),
        unserved=unserved,
    )


def start_reschedules(
    db: Session,
    base: m.ScheduleRun,
    ev: m.DisruptionEvent,
    policies: list[Policy],
    reoptimizer: str | None,
    time_limit_s: float,
    seed: int,
    freeze_window_min: int,
    user_id: int | None,
) -> list[m.RescheduleRun]:
    if base.status != "SUCCEEDED":
        raise RunError("base_not_published", "only a SUCCEEDED (validated) run can be rescheduled")
    if base.problem_type not in SUPPORTED_BASE:
        raise RunError("unsupported_problem", f"rescheduling supports {sorted(SUPPORTED_BASE)} runs")
    if ev.scenario_id != base.scenario_id:
        raise RunError("event_scenario_mismatch", "event belongs to a different scenario")
    sc = db.get(m.Scenario, base.scenario_id)
    assert sc is not None
    snap = snapshot_from_row(db.get(m.ScenarioSnapshotRow, base.snapshot_id))  # type: ignore[arg-type]
    base_res = base_result(db, base)
    spec = event_spec(ev)
    out: list[m.RescheduleRun] = []
    for policy in policies:
        prior = db.scalar(
            select(m.RescheduleRun).where(
                m.RescheduleRun.base_run_id == base.id,
                m.RescheduleRun.event_id == ev.id,
                m.RescheduleRun.policy == policy,
            )
        )
        if prior is not None:  # idempotent per (base, event, policy)
            out.append(prior)
            continue
        try:
            new_snap, plan = build_policy_snapshot(snap, base_res, spec, policy, freeze_window_min)
        except ValueError as e:
            raise RunError("invalid_event", str(e)) from e
        row = store_snapshot(db, sc, new_snap, reason=f"event:{ev.id}:{policy}")
        params = {"reoptimizer": reoptimizer} if reoptimizer else {}
        run = enqueue_run(
            db,
            sc,
            base.problem_type,
            f"reschedule_{policy.lower()}",
            time_limit_s,
            seed,
            params,
            user_id,
            snapshot_row=row,
            parent_run_id=base.id,
            schedule_version=base.schedule_version + 1,
            dispatch=False,
        )
        rr = m.RescheduleRun(
            base_run_id=base.id,
            event_id=ev.id,
            policy=policy,
            frozen_until_min=spec.time_min + freeze_window_min,
            new_run_id=run.id,
            status="QUEUED",
            summary=plan.model_dump(),
            created_by=user_id,
        )
        db.add(rr)
        db.flush()
        out.append(rr)
    db.commit()
    return out


def summarize(db: Session, base_run_id: int, weights: dict[str, float] | None = None) -> dict[str, Any]:
    rows = list(
        db.scalars(
            select(m.RescheduleRun)
            .where(m.RescheduleRun.base_run_id == base_run_id)
            .order_by(m.RescheduleRun.event_id, m.RescheduleRun.id)
        )
    )
    items = []
    by_event: dict[int, dict[str, dict]] = {}
    for rr in rows:
        run = db.get(m.ScheduleRun, rr.new_run_id) if rr.new_run_id else None
        mt = (run.metrics or {}) if run else {}
        if run is not None and run.status in ("SUCCEEDED", "FAILED", "CANCELLED") and rr.status != run.status:
            rr.status = run.status
            rr.changed_tasks = mt.get("changed_tasks")
            rr.changed_routes = mt.get("changed_routes")
            rr.stability_score = mt.get("stability_score")
        item = {
            "id": rr.id,
            "event_id": rr.event_id,
            "policy": rr.policy,
            "new_run_id": rr.new_run_id,
            "status": run.status if run else rr.status,
            "feasible": bool(run and run.is_feasible),
            "total_cost": float(run.objective_total) if run and run.objective_total is not None else None,
            "late_min": mt.get("total_lateness_min"),
            "unserved": mt.get("orders_unserved"),
            "changed_tasks": mt.get("changed_tasks"),
            "changed_routes": mt.get("changed_routes"),
            "stability_score": mt.get("stability_score"),
            "runtime_ms": run.runtime_ms if run else None,
            "selection": ((run.solver_metadata or {}).get("selection") if run else None),
            "frozen_until_min": rr.frozen_until_min,
            "summary": rr.summary,
            "schedule_version": run.schedule_version if run else None,
        }
        items.append(item)
        if item["status"] == "SUCCEEDED" and item["total_cost"] is not None:
            by_event.setdefault(rr.event_id, {})[rr.policy] = {
                "feasible": item["feasible"],
                "total_cost": item["total_cost"],
                "late_min": item["late_min"] or 0,
                "changed_tasks": item["changed_tasks"] or 0,
                "changed_routes": item["changed_routes"] or 0,
                "runtime_ms": item["runtime_ms"] or 1,
            }
    db.commit()
    recs = {str(eid): recommend(res, weights) for eid, res in by_event.items()}
    return {"base_run_id": base_run_id, "items": items, "recommendations": recs}
