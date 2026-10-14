"""Human-level scenario definition (master data in *local wall-clock minutes of the operating day*).

This is what the synthetic generator produces, what gets persisted to MySQL, and what the snapshot
builder converts into the solver-facing ``ScenarioSnapshot`` (integer minutes from horizon start, UTC).
Local minutes may exceed 1440 for overnight shifts (e.g. 1500 = 01:00 next day).
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.optimization.common.contracts import ObjectiveWeights, ScenarioParams


class _D(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FacilityDef(_D):
    code: str
    name: str
    timezone: str = "Asia/Seoul"
    x_km: float = 0.0
    y_km: float = 0.0
    lat: float | None = None
    lon: float | None = None


class CustomerDef(_D):
    code: str
    name: str
    x_km: float
    y_km: float
    lat: float | None = None
    lon: float | None = None
    service_min: int = Field(default=8, ge=0)
    tw_start_local: int
    tw_end_local: int

    @model_validator(mode="after")
    def _tw(self) -> CustomerDef:
        if self.tw_end_local < self.tw_start_local:
            raise ValueError(f"customer {self.code}: tw_end before tw_start")
        return self


class SkuDef(_D):
    code: str
    name: str
    zone: str = "A"
    unit_weight_g: int = Field(ge=0)
    unit_volume_ml: int = Field(ge=0)
    pick_sec_per_unit: int = Field(default=20, ge=0)


class OrderLineDef(_D):
    sku_code: str
    qty: int = Field(gt=0)


class OrderDef(_D):
    code: str
    customer_code: str
    release_local: int
    due_local: int
    priority: int = Field(default=1, ge=1, le=3)
    lines: list[OrderLineDef] = Field(min_length=1)
    status: str = "OPEN"


class WorkerDef(_D):
    code: str
    name: str
    skills: list[str]
    hourly_cost: float = Field(default=15000, ge=0)
    shift_start_local: int
    shift_end_local: int
    regular_end_local: int | None = None


class EquipmentDef(_D):
    code: str
    kind: str = "forklift"
    name: str = ""


class PackStationDef(_D):
    code: str
    name: str = ""
    open_start_local: int
    open_end_local: int


class DockDef(_D):
    code: str
    name: str = ""
    vehicle_classes: list[str] = ["van", "truck"]
    open_start_local: int
    open_end_local: int


class VehicleDef(_D):
    code: str
    vehicle_class: str = "van"
    capacity_kg: int = Field(gt=0)
    capacity_l: int = Field(gt=0)
    fixed_cost: float = 80000
    cost_per_km: float = 900
    shift_start_local: int
    shift_end_local: int
    status: str = "AVAILABLE"


class DowntimeDef(_D):
    resource_type: str  # worker | pack_station | equipment | dock
    resource_code: str
    start_local: int
    end_local: int
    reason: str = "planned_maintenance"


class TaskModelParams(_D):
    pick_base_min: int = 3
    pack_base_min: int = 4
    pack_sec_per_unit: int = 10
    forklift_weight_kg: int = 120  # orders heavier than this need a forklift for picking
    zone_skill: dict[str, str] = {"C": "cold"}  # zone -> extra worker skill required


class TravelParams(_D):
    provenance: str = "synthetic_euclidean"
    circuity: float = 1.3  # road distance ≈ euclidean × circuity (synthetic assumption, not real roads)
    speed_kmh: float = 30.0


class ScenarioDefinition(_D):
    name: str
    description: str = ""
    seed: int = 0
    operating_date: date
    horizon_start_local: int = 360  # 06:00
    horizon_min: int = 960  # 16 h
    facility: FacilityDef
    customers: list[CustomerDef]
    skus: list[SkuDef]
    inventory: dict[str, int]
    orders: list[OrderDef]
    workers: list[WorkerDef]
    equipment: list[EquipmentDef] = []
    pack_stations: list[PackStationDef]
    docks: list[DockDef]
    vehicles: list[VehicleDef]
    downtimes: list[DowntimeDef] = []
    params: ScenarioParams = ScenarioParams()
    weights: ObjectiveWeights = ObjectiveWeights()
    task_model: TaskModelParams = TaskModelParams()
    travel: TravelParams = TravelParams()

    @model_validator(mode="after")
    def _refs(self) -> ScenarioDefinition:
        cust = {c.code for c in self.customers}
        skus = {s.code for s in self.skus}
        errs = []
        for o in self.orders:
            if o.customer_code not in cust:
                errs.append(f"order {o.code}: unknown customer {o.customer_code}")
            for ln in o.lines:
                if ln.sku_code not in skus:
                    errs.append(f"order {o.code}: unknown sku {ln.sku_code}")
        codes = [o.code for o in self.orders]
        if len(codes) != len(set(codes)):
            errs.append("duplicate order codes")
        for k in self.inventory:
            if k not in skus:
                errs.append(f"inventory for unknown sku {k}")
        if errs:
            raise ValueError("; ".join(errs[:20]))
        return self
