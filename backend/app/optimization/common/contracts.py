"""Typed, ORM-independent contracts shared by every optimizer, the validator and the evaluator.

Time unit: integer minutes relative to ``ScenarioSnapshot.horizon_start`` (UTC).  Distance: integer meters.
Weight: integer kg.  Volume: integer liters.  Money: float in the scenario currency (KRW by default),
rounded to 2 decimals only at reporting time.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

TaskType = Literal["PICK", "PACK", "LOAD"]
ProblemType = Literal["warehouse", "dock", "routing", "integrated"]
SolverStatus = Literal["FEASIBLE", "OPTIMAL", "INFEASIBLE", "TIME_LIMIT", "ERROR"]
Severity = Literal["error", "warning", "info"]


class _M(BaseModel):
    model_config = ConfigDict(frozen=False, extra="forbid")


class Interval(_M):
    start: int
    end: int


# ----------------------------------------------------------------------------------------------
# Scenario snapshot (immutable solver input)
# ----------------------------------------------------------------------------------------------
class Location(_M):
    id: str
    x_km: float
    y_km: float
    lat: float | None = None
    lon: float | None = None


class Customer(_M):
    id: str
    name: str
    location_id: str
    service_min: int = Field(ge=0)
    tw_start: int
    tw_end: int


class Sku(_M):
    id: str
    zone: str
    unit_weight_g: int = Field(ge=0)
    unit_volume_ml: int = Field(ge=0)
    pick_sec_per_unit: int = Field(ge=0)


class OrderLine(_M):
    sku_id: str
    qty: int = Field(gt=0)


class Order(_M):
    id: str
    customer_id: str
    release_min: int
    due_min: int  # warehouse ship cutoff (packing must finish by then; soft, penalised)
    priority: int = Field(default=1, ge=1, le=3)  # 1=normal, 2=high, 3=urgent
    lines: list[OrderLine]
    weight_kg: int = Field(ge=0)
    volume_l: int = Field(ge=0)
    units: int = Field(ge=0)


class ResourceRequirement(_M):
    kind: Literal["worker", "pack_station", "equipment"]
    eligible_ids: list[str]


class Task(_M):
    id: str
    order_id: str
    type: Literal["PICK", "PACK"]
    duration_min: int = Field(gt=0)
    release_min: int
    requirements: list[ResourceRequirement]
    predecessors: list[str] = []


class Resource(_M):
    """Unit-capacity renewable resource (worker, pack station, equipment unit, dock)."""

    id: str
    kind: Literal["worker", "pack_station", "equipment", "dock"]
    name: str
    available: list[Interval]  # disjoint, sorted; shifts minus downtime
    skills: list[str] = []
    hourly_cost: float = 0.0
    regular_end: int | None = None  # minutes after this are overtime (workers)
    vehicle_classes: list[str] = []  # docks only


class Vehicle(_M):
    id: str
    vehicle_class: str
    capacity_kg: int = Field(ge=0)
    capacity_l: int = Field(ge=0)
    fixed_cost: float = 0.0
    cost_per_km: float = 0.0
    shift_start: int
    shift_end: int
    depot_location_id: str
    available: bool = True


class TravelMatrix(_M):
    version: str
    provenance: Literal["synthetic_euclidean", "osrm", "imported"]
    location_ids: list[str]
    distance_m: list[list[int]]
    duration_min: list[list[int]]
    symmetric: bool = True
    notes: str = ""


class ScenarioParams(_M):
    time_window_mode: Literal["soft", "hard"] = "soft"  # tw_start always hard (wait); tw_end soft or hard
    return_to_depot: bool = True
    load_base_min: int = 10
    load_per_order_min: int = 2
    aggregate_same_customer: bool = True  # orders of one customer on one vehicle share a stop


class ObjectiveWeights(_M):
    currency: str = "KRW"
    late_penalty_per_min: float = 1000.0  # multiplied by order priority
    unserved_penalty: float = 300_000.0  # per order, multiplied by priority
    overtime_premium: float = 0.5  # fraction of hourly cost added for overtime minutes
    change_penalty_per_task: float = 5_000.0  # rescheduling stability
    change_penalty_per_route: float = 20_000.0


class FrozenAssignment(_M):
    task_id: str
    resources: dict[str, str]
    start_min: int
    end_min: int
    reason: Literal["completed", "in_progress", "committed"] = "committed"


class FrozenRoute(_M):
    """A route that must not change (executed history or committed near-term plan).

    ``route`` is the full timed record copied verbatim into any new schedule version, so historical
    execution is never re-computed or rewritten (even if travel times change afterwards).
    """

    vehicle_id: str
    order_ids: list[str]
    dock_id: str | None
    load_start: int
    load_end: int
    departure_min: int
    reason: Literal["completed", "in_progress", "committed"] = "committed"
    route: VehicleRoute | None = None


class ScenarioSnapshot(_M):
    scenario_id: str
    snapshot_version: int = 1
    name: str
    seed: int = 0
    horizon_start: datetime
    horizon_min: int = Field(gt=0)
    timezone: str = "Asia/Seoul"
    depot_location_id: str
    locations: list[Location]
    customers: list[Customer]
    skus: list[Sku]
    inventory: dict[str, int]
    orders: list[Order]
    tasks: list[Task]
    resources: list[Resource]
    vehicles: list[Vehicle]
    travel: TravelMatrix
    params: ScenarioParams = ScenarioParams()
    weights: ObjectiveWeights = ObjectiveWeights()
    task_model: dict[str, Any] = {}  # TaskModelParams used to derive tasks (needed for urgent orders)
    events_applied: list[dict[str, Any]] = []  # provenance of disruption events folded into this snapshot
    # Rescheduling context
    current_time_min: int = 0  # nothing new may start before this
    frozen_assignments: list[FrozenAssignment] = []
    frozen_routes: list[FrozenRoute] = []
    cancelled_order_ids: list[str] = []
    baseline_assignments: list[TaskAssignment] = []  # previous plan (stability measurement)
    baseline_routes: list[VehicleRoute] = []
    # KEEP-policy freeze sets (superset of this snapshot's freeze) → minimal-change candidate
    keep_frozen_assignments: list[FrozenAssignment] = []
    keep_frozen_routes: list[FrozenRoute] = []
    reschedule_policy: str | None = None

    def order_map(self) -> dict[str, Order]:
        return {o.id: o for o in self.orders}

    def task_map(self) -> dict[str, Task]:
        return {t.id: t for t in self.tasks}

    def resource_map(self) -> dict[str, Resource]:
        return {r.id: r for r in self.resources}

    def customer_map(self) -> dict[str, Customer]:
        return {c.id: c for c in self.customers}

    def vehicle_map(self) -> dict[str, Vehicle]:
        return {v.id: v for v in self.vehicles}

    def loc_index(self) -> dict[str, int]:
        return {lid: i for i, lid in enumerate(self.travel.location_ids)}


# ----------------------------------------------------------------------------------------------
# Solve configuration & results
# ----------------------------------------------------------------------------------------------
class SolveConfig(_M):
    problem_type: ProblemType
    time_limit_s: float = Field(default=10.0, gt=0, le=600)
    seed: int = 0
    params: dict[str, Any] = {}


class CancellationToken:
    """Cooperative cancellation checked by iterative solvers between iterations."""

    def __init__(self, check: Any = None):
        self._check = check
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    @property
    def cancelled(self) -> bool:
        if self._cancelled:
            return True
        if self._check is not None and self._check():
            self._cancelled = True
        return self._cancelled


class TaskAssignment(_M):
    task_id: str
    task_type: TaskType
    order_ids: list[str]
    resource_id: str  # primary resource (Gantt lane)
    resources: dict[str, str]  # kind -> resource id (all requirements)
    start_min: int
    end_min: int
    frozen: bool = False


class RouteStop(_M):
    seq: int
    customer_id: str
    location_id: str
    order_ids: list[str]
    arrival_min: int
    service_start_min: int
    service_end_min: int
    departure_min: int
    wait_min: int = 0
    late_min: int = 0
    load_after_kg: int = 0
    load_after_l: int = 0


class VehicleRoute(_M):
    vehicle_id: str
    dock_id: str | None = None
    order_ids: list[str]
    ready_min: int = 0  # all orders packed (max pack end) — 0 for routing-only scope uses cutoffs
    load_start_min: int | None = None
    load_end_min: int | None = None
    departure_min: int
    return_min: int
    stops: list[RouteStop]
    distance_m: int
    load_kg: int
    load_l: int
    geometry: Literal["schematic_straight_line", "road"] = "schematic_straight_line"


class UnservedOrder(_M):
    order_id: str
    reason: str
    penalty: float = 0.0


class Violation(_M):
    rule: str
    severity: Severity = "error"
    entity_type: str
    entity_id: str
    message: str
    observed: dict[str, Any] = {}


class ValidationReport(_M):
    is_feasible: bool
    scope: list[str]
    checked_rules: list[str]
    violations: list[Violation]
    unserved: list[UnservedOrder] = []
    stats: dict[str, Any] = {}

    @property
    def errors(self) -> list[Violation]:
        return [v for v in self.violations if v.severity == "error"]


class CostBreakdown(_M):
    currency: str = "KRW"
    transport_fixed: float = 0.0
    distance_cost: float = 0.0
    labor_cost: float = 0.0
    overtime_cost: float = 0.0
    late_delivery_penalty: float = 0.0
    unserved_penalty: float = 0.0
    schedule_change_penalty: float = 0.0
    total_cost: float = 0.0
    coefficients: dict[str, Any] = {}


class ScheduleMetrics(_M):
    cost: CostBreakdown
    orders_total: int = 0
    orders_served: int = 0
    orders_unserved: int = 0
    on_time_rate: float | None = None  # share of served orders on time (delivery if routed, else cutoff)
    total_lateness_min: int = 0
    max_lateness_min: int = 0
    warehouse_makespan_min: int | None = None
    end_to_end_makespan_min: int | None = None
    total_distance_km: float = 0.0
    vehicles_used: int = 0
    resource_utilization: dict[str, float] = {}  # resource id -> busy / available (0..1)
    avg_utilization: dict[str, float] = {}  # by resource kind
    overtime_min: int = 0
    changed_tasks: int | None = None
    changed_routes: int | None = None
    stability_score: float | None = None


class ScheduleResult(_M):
    run_id: str
    algorithm: str
    problem_type: ProblemType
    status: SolverStatus
    assignments: list[TaskAssignment]
    routes: list[VehicleRoute]
    unserved_order_ids: list[str]
    unserved: list[UnservedOrder] = []
    metrics: ScheduleMetrics | None = None
    runtime_ms: int = 0
    seed: int | None = None
    solver_metadata: dict[str, Any] = {}
    validation: ValidationReport | None = None


class SchedulingAlgorithm(Protocol):
    name: str
    supported_problem_types: set[str]
    description: str
    kind: str  # "heuristic" | "exact" | "metaheuristic" | "decomposition"

    def solve(
        self, instance: ScenarioSnapshot, config: SolveConfig, cancel: CancellationToken | None = None
    ) -> ScheduleResult: ...


FrozenRoute.model_rebuild()
ScenarioSnapshot.model_rebuild()
