"""Request/response models of the public REST API (OpenAPI is generated from these)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Generic, Literal, TypeVar

from pydantic import AwareDatetime, BaseModel, Field, field_validator

from app.optimization.common.contracts import (
    Interval,
    ObjectiveWeights,
    ScenarioParams,
    ScheduleMetrics,
    TaskAssignment,
    UnservedOrder,
    ValidationReport,
    VehicleRoute,
)

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


# ---------------- master data ----------------
class FacilityOut(BaseModel):
    id: int
    code: str
    name: str
    timezone: str


class OrderLineIn(BaseModel):
    sku_code: str = Field(min_length=1, max_length=32)
    qty: int = Field(gt=0, le=10_000)


class OrderLineOut(OrderLineIn):
    pass


class OrderCreate(BaseModel):
    scenario_id: int
    code: str = Field(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9_\-]+$")
    customer_code: str = Field(min_length=1, max_length=32)
    release_at: AwareDatetime
    due_at: AwareDatetime
    priority: int = Field(default=1, ge=1, le=3)
    lines: list[OrderLineIn] = Field(min_length=1, max_length=50)

    @field_validator("due_at")
    @classmethod
    def _due_after_release(cls, v: datetime, info: Any) -> datetime:
        rel = info.data.get("release_at")
        if rel is not None and v <= rel:
            raise ValueError("due_at must be after release_at")
        return v


class OrderOut(BaseModel):
    id: int
    code: str
    facility_code: str
    customer_code: str
    customer_name: str
    release_at: datetime
    due_at: datetime
    priority: int
    status: str
    units: int
    weight_kg: float
    lines: list[OrderLineOut]


class WorkerIn(BaseModel):
    facility_id: int
    code: str = Field(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9_\-]+$")
    name: str = Field(min_length=1, max_length=120)
    skills: list[Literal["pick", "pack", "cold"]] = Field(min_length=1)
    hourly_cost: float = Field(ge=0, le=1_000_000)
    shift_start_local_min: int = Field(ge=0, le=2880)
    shift_end_local_min: int = Field(ge=0, le=2880)
    regular_end_local_min: int | None = Field(default=None, ge=0, le=2880)


class WorkerOut(WorkerIn):
    id: int
    active: bool


class VehicleIn(BaseModel):
    facility_id: int
    code: str = Field(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9_\-]+$")
    vehicle_class: Literal["van", "truck"] = "van"
    capacity_kg: int = Field(gt=0, le=50_000)
    capacity_l: int = Field(gt=0, le=200_000)
    fixed_cost: float = Field(ge=0)
    cost_per_km: float = Field(ge=0)
    shift_start_local_min: int = Field(ge=0, le=2880)
    shift_end_local_min: int = Field(ge=0, le=2880)
    status: Literal["AVAILABLE", "MAINTENANCE", "BROKEN"] = "AVAILABLE"


class VehicleOut(VehicleIn):
    id: int


class DockIn(BaseModel):
    facility_id: int
    code: str = Field(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9_\-]+$")
    name: str = Field(min_length=1, max_length=120)
    vehicle_classes: list[Literal["van", "truck"]] = Field(min_length=1)
    open_start_local_min: int = Field(ge=0, le=2880)
    open_end_local_min: int = Field(ge=0, le=2880)


class DockOut(DockIn):
    id: int
    active: bool


# ---------------- scenarios ----------------
class SyntheticScenarioCreate(BaseModel):
    """Scenario builder: generate a deterministic synthetic world (seeded) and save it."""

    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    seed: int = Field(default=1, ge=0, le=2**31 - 1)
    operating_date: date = date(2026, 10, 15)
    n_orders: int = Field(default=30, ge=1, le=500)
    n_workers: int = Field(default=5, ge=1, le=60)
    n_pack_stations: int = Field(default=2, ge=1, le=20)
    n_docks: int = Field(default=2, ge=1, le=10)
    n_vans: int = Field(default=3, ge=0, le=50)
    n_trucks: int = Field(default=1, ge=0, le=20)
    area_km: float = Field(default=15.0, gt=0, le=100)
    deadline_tightness: float = Field(default=1.0, ge=0.5, le=3.0)
    inventory_shortage_skus: int = Field(default=0, ge=0, le=20)
    time_window_mode: Literal["soft", "hard"] = "soft"
    weights: ObjectiveWeights = ObjectiveWeights()


class ScenarioUpdate(BaseModel):
    version: int = Field(description="optimistic-concurrency token from GET")
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    seed: int | None = Field(default=None, ge=0)
    horizon_min: int | None = Field(default=None, ge=60, le=2880)
    params: ScenarioParams | None = None
    weights: ObjectiveWeights | None = None


class CloneRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class ScenarioOut(BaseModel):
    id: int
    name: str
    description: str
    facility: FacilityOut
    operating_date: date
    horizon_start: datetime
    horizon_min: int
    seed: int
    status: str
    version: int
    parent_scenario_id: int | None
    order_count: int
    created_at: datetime
    params: ScenarioParams
    weights: ObjectiveWeights
    task_model: dict[str, Any]
    travel_params: dict[str, Any]
    resource_counts: dict[str, int]
    snapshot_versions: int


class InputIssue(BaseModel):
    severity: Literal["error", "warning", "info"]
    code: str
    entity: str
    message: str


class InputValidation(BaseModel):
    ok: bool
    issues: list[InputIssue]
    summary: dict[str, Any]


class GeoPoint(BaseModel):
    id: str
    kind: Literal["depot", "customer"]
    name: str
    x_km: float
    y_km: float
    lat: float | None
    lon: float | None
    tw_start: int | None = None
    tw_end: int | None = None


class GeoOut(BaseModel):
    coordinate_provenance: str
    travel_provenance: str
    travel_notes: str
    points: list[GeoPoint]


# ---------------- runs ----------------
class RunCreate(BaseModel):
    problem_type: Literal["warehouse", "dock", "routing", "integrated"]
    algorithm: str = Field(min_length=1, max_length=64)
    time_limit_s: float = Field(default=10.0, gt=0, le=600)
    seed: int = Field(default=0, ge=0, le=2**31 - 1)
    params: dict[str, Any] = Field(default_factory=dict)

    @field_validator("params")
    @classmethod
    def _bounded(cls, v: dict[str, Any]) -> dict[str, Any]:
        if len(v) > 30:
            raise ValueError("too many params")
        return v


class RunOut(BaseModel):
    id: int
    scenario_id: int
    scenario_name: str
    snapshot_id: int
    snapshot_version: int
    parent_run_id: int | None
    schedule_version: int
    problem_type: str
    algorithm: str
    params: dict[str, Any]
    seed: int
    time_limit_s: float
    status: str
    solver_status: str | None
    progress: int
    cancel_requested: bool
    queued_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    runtime_ms: int | None
    is_feasible: bool | None
    objective_total: float | None
    error_message: str | None
    kpis: dict[str, Any] | None
    validation_summary: dict[str, Any] | None
    solver_metadata: dict[str, Any] | None
    horizon_start: datetime
    timezone: str


class ResourceLane(BaseModel):
    id: str
    kind: str
    name: str
    available: list[Interval]
    skills: list[str] = []
    regular_end: int | None = None
    vehicle_classes: list[str] = []


class OrderInfo(BaseModel):
    id: str
    customer_id: str
    release_min: int
    due_min: int
    priority: int
    weight_kg: int
    tw_start: int
    tw_end: int


class VehicleInfo(BaseModel):
    id: str
    vehicle_class: str
    capacity_kg: int
    capacity_l: int
    shift_start: int
    shift_end: int
    available: bool


class ScheduleOut(BaseModel):
    run_id: int
    status: str
    problem_type: str
    algorithm: str
    horizon_start: datetime
    horizon_min: int
    timezone: str
    current_time_min: int
    assignments: list[TaskAssignment]
    routes: list[VehicleRoute]
    unserved: list[UnservedOrder]
    resources: list[ResourceLane]
    vehicles: list[VehicleInfo]
    orders: list[OrderInfo]
    travel_provenance: str
    geometry_note: str


class MetricsOut(BaseModel):
    run_id: int
    algorithm: str
    metrics: ScheduleMetrics | None
    solver_status: str | None
    solver_objective: float | None = None
    best_bound: float | None = None
    gap: float | None = None
    gap_note: str


class AlgorithmOut(BaseModel):
    name: str
    problem_types: list[str]
    kind: str
    description: str
    available: bool
    stochastic: bool
    phase: str


class CompareRow(BaseModel):
    run_id: int
    algorithm: str
    problem_type: str
    status: str
    solver_status: str | None
    is_feasible: bool | None
    seed: int
    runtime_ms: int | None
    total_cost: float | None
    cost: dict[str, Any] | None
    on_time_rate: float | None
    total_lateness_min: int | None
    total_distance_km: float | None
    vehicles_used: int | None
    orders_unserved: int | None
    warehouse_makespan_min: int | None
    end_to_end_makespan_min: int | None
    avg_utilization: dict[str, float] | None
    changed_tasks: int | None
    stability_score: float | None
    gap: float | None


class CompareOut(BaseModel):
    scenario_id: int
    snapshot_ids: list[int]
    same_snapshot: bool
    objective_note: str
    rows: list[CompareRow]


class _Validation(BaseModel):
    report: ValidationReport
