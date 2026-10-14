"""Scenarios, immutable snapshots, runs and their (append-only) outputs, disruptions, reschedules."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    Double,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UTCDateTime, utcnow
from app.db.models.user import PK

RUN_STATUSES = ("QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED")
TERMINAL = ("SUCCEEDED", "FAILED", "CANCELLED")


class Scenario(Base):
    __tablename__ = "scenarios"
    __table_args__ = (Index("ix_scenarios_facility_status", "facility_id", "status"),)
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    facility_id: Mapped[int] = mapped_column(ForeignKey("facilities.id", ondelete="RESTRICT"))
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(String(500), default="")
    operating_date: Mapped[date] = mapped_column(Date)
    horizon_start_local_min: Mapped[int] = mapped_column(Integer, default=360)
    horizon_min: Mapped[int] = mapped_column(Integer, default=960)
    seed: Mapped[int] = mapped_column(Integer, default=0)
    params: Mapped[dict] = mapped_column(JSON)  # ScenarioParams
    weights: Mapped[dict] = mapped_column(JSON)  # ObjectiveWeights
    task_model: Mapped[dict] = mapped_column(JSON)
    travel_params: Mapped[dict] = mapped_column(JSON)
    travel_matrix_id: Mapped[int | None] = mapped_column(
        ForeignKey("travel_matrices.id", ondelete="RESTRICT"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(16), default="READY")
    parent_scenario_id: Mapped[int | None] = mapped_column(
        ForeignKey("scenarios.id", ondelete="RESTRICT"), nullable=True
    )
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)
    version: Mapped[int] = mapped_column(Integer, default=1)

    __mapper_args__ = {"version_id_col": version}  # optimistic concurrency


class ScenarioOrder(Base):
    __tablename__ = "scenario_orders"
    scenario_id: Mapped[int] = mapped_column(ForeignKey("scenarios.id", ondelete="CASCADE"), primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="RESTRICT"), primary_key=True, index=True)


class ScenarioSnapshotRow(Base):
    """Immutable solver input. A schedule can be reproduced from this row alone."""

    __tablename__ = "scenario_snapshots"
    __table_args__ = (UniqueConstraint("scenario_id", "version", name="uq_snapshot_version"),)
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    scenario_id: Mapped[int] = mapped_column(ForeignKey("scenarios.id", ondelete="RESTRICT"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    content: Mapped[dict] = mapped_column(JSON)  # full ScenarioSnapshot document (reproducibility record)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    reason: Mapped[str] = mapped_column(String(120), default="initial")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class TaskRow(Base):
    __tablename__ = "tasks"
    __table_args__ = (UniqueConstraint("snapshot_id", "task_code", name="uq_tasks_snapshot_code"),)
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("scenario_snapshots.id", ondelete="CASCADE"), index=True)
    task_code: Mapped[str] = mapped_column(String(64))
    order_code: Mapped[str] = mapped_column(String(40), index=True)
    task_type: Mapped[str] = mapped_column(String(8))
    duration_min: Mapped[int] = mapped_column(Integer)
    release_min: Mapped[int] = mapped_column(Integer)
    requirements: Mapped[list] = mapped_column(JSON)


class TaskDependency(Base):
    __tablename__ = "task_dependencies"
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("scenario_snapshots.id", ondelete="CASCADE"), index=True)
    task_code: Mapped[str] = mapped_column(String(64))
    predecessor_code: Mapped[str] = mapped_column(String(64))


class ScheduleRun(Base):
    __tablename__ = "schedule_runs"
    __table_args__ = (
        Index("ix_schedule_runs_status_queued", "status", "queued_at"),
        Index("ix_schedule_runs_scenario", "scenario_id", "queued_at"),
    )
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    scenario_id: Mapped[int] = mapped_column(ForeignKey("scenarios.id", ondelete="RESTRICT"))
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("scenario_snapshots.id", ondelete="RESTRICT"), index=True)
    parent_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("schedule_runs.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    schedule_version: Mapped[int] = mapped_column(Integer, default=1)
    problem_type: Mapped[str] = mapped_column(String(16))
    algorithm: Mapped[str] = mapped_column(String(64), index=True)
    params: Mapped[dict] = mapped_column(JSON)
    seed: Mapped[int] = mapped_column(Integer, default=0)
    time_limit_s: Mapped[float] = mapped_column(Double, default=10.0)
    status: Mapped[str] = mapped_column(String(16), default="QUEUED")
    solver_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    worker_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    queued_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    runtime_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_feasible: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    objective_total: Mapped[Decimal | None] = mapped_column(Numeric(16, 2), nullable=True)
    metrics: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # ScheduleMetrics (bounded)
    validation: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # ValidationReport
    solver_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    lock_version: Mapped[int] = mapped_column(Integer, default=1)

    __mapper_args__ = {"version_id_col": lock_version}


class ScheduleAssignment(Base):
    __tablename__ = "schedule_assignments"
    __table_args__ = (
        Index("ix_assign_run_resource", "run_id", "resource_code"),
        Index("ix_assign_run_task", "run_id", "task_code"),
    )
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("schedule_runs.id", ondelete="CASCADE"))
    task_code: Mapped[str] = mapped_column(String(64))
    task_type: Mapped[str] = mapped_column(String(8))
    order_codes: Mapped[list] = mapped_column(JSON)
    resource_code: Mapped[str] = mapped_column(String(32))
    resources: Mapped[dict] = mapped_column(JSON)
    start_min: Mapped[int] = mapped_column(Integer)
    end_min: Mapped[int] = mapped_column(Integer)
    frozen: Mapped[bool] = mapped_column(Boolean, default=False)


class RouteRow(Base):
    __tablename__ = "routes"
    __table_args__ = (Index("ix_routes_run_vehicle", "run_id", "vehicle_code"),)
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("schedule_runs.id", ondelete="CASCADE"))
    vehicle_code: Mapped[str] = mapped_column(String(32))
    dock_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    order_codes: Mapped[list] = mapped_column(JSON)
    ready_min: Mapped[int] = mapped_column(Integer)
    load_start_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    load_end_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    departure_min: Mapped[int] = mapped_column(Integer)
    return_min: Mapped[int] = mapped_column(Integer)
    distance_m: Mapped[int] = mapped_column(Integer)
    load_kg: Mapped[int] = mapped_column(Integer)
    load_l: Mapped[int] = mapped_column(Integer)
    geometry: Mapped[str] = mapped_column(String(32), default="schematic_straight_line")


class RouteStopRow(Base):
    __tablename__ = "route_stops"
    __table_args__ = (UniqueConstraint("route_id", "seq", name="uq_route_stop_seq"),)
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    route_id: Mapped[int] = mapped_column(ForeignKey("routes.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    customer_code: Mapped[str] = mapped_column(String(32))
    location_code: Mapped[str] = mapped_column(String(40))
    order_codes: Mapped[list] = mapped_column(JSON)
    arrival_min: Mapped[int] = mapped_column(Integer)
    service_start_min: Mapped[int] = mapped_column(Integer)
    service_end_min: Mapped[int] = mapped_column(Integer)
    departure_min: Mapped[int] = mapped_column(Integer)
    wait_min: Mapped[int] = mapped_column(Integer, default=0)
    late_min: Mapped[int] = mapped_column(Integer, default=0)
    load_after_kg: Mapped[int] = mapped_column(Integer, default=0)
    load_after_l: Mapped[int] = mapped_column(Integer, default=0)


class Shipment(Base):
    """Per-run fulfilment status of every order: served (with route) or explicitly unserved (reason)."""

    __tablename__ = "shipments"
    __table_args__ = (UniqueConstraint("run_id", "order_code", name="uq_shipments_run_order"),)
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("schedule_runs.id", ondelete="CASCADE"), index=True)
    order_code: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(16))  # SERVED | UNSERVED
    vehicle_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ready_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    delivered_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    late_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    unserved_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    penalty: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)


class DisruptionEvent(Base):
    __tablename__ = "disruption_events"
    __table_args__ = (
        UniqueConstraint("scenario_id", "idempotency_key", name="uq_disruption_idem"),
        Index("ix_disruption_scenario_time", "scenario_id", "event_time_min"),
    )
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    scenario_id: Mapped[int] = mapped_column(ForeignKey("scenarios.id", ondelete="RESTRICT"))
    idempotency_key: Mapped[str] = mapped_column(String(80))
    event_type: Mapped[str] = mapped_column(String(32))
    event_time_min: Mapped[int] = mapped_column(Integer)
    affected_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    affected_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class RescheduleRun(Base):
    __tablename__ = "reschedule_runs"
    __table_args__ = (Index("ix_reschedule_base", "base_run_id"),)
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    base_run_id: Mapped[int] = mapped_column(ForeignKey("schedule_runs.id", ondelete="RESTRICT"))
    event_id: Mapped[int] = mapped_column(ForeignKey("disruption_events.id", ondelete="RESTRICT"), index=True)
    policy: Mapped[str] = mapped_column(String(8))  # KEEP | PARTIAL | FULL
    frozen_until_min: Mapped[int] = mapped_column(Integer)
    new_run_id: Mapped[int | None] = mapped_column(ForeignKey("schedule_runs.id", ondelete="RESTRICT"), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="QUEUED")
    changed_tasks: Mapped[int | None] = mapped_column(Integer, nullable=True)
    changed_routes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stability_score: Mapped[float | None] = mapped_column(Double, nullable=True)
    summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


# ---- immutability guard: published outputs are append-only ----
class ImmutableOutputError(RuntimeError):
    pass


def _forbid(_mapper, _conn, target) -> None:  # type: ignore[no-untyped-def]
    raise ImmutableOutputError(f"{type(target).__name__} rows are immutable once written")


for _cls in (ScheduleAssignment, RouteRow, RouteStopRow, Shipment, ScenarioSnapshotRow):
    event.listen(_cls, "before_update", _forbid)
    event.listen(_cls, "before_delete", _forbid)
