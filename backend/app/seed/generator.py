"""Deterministic synthetic scenario generator (same seed ⇒ byte-identical definition).

Knobs: workload (#orders, lines), deadline tightness, resource scarcity, bottleneck severity
(pack-station count / downtime), travel area, inventory shortages, vehicle mix.
Coordinates are synthetic (km offsets around a Seoul-area anchor); lat/lon are derived only for
map display and are labelled synthetic everywhere.
"""

from __future__ import annotations

import math
import random
from datetime import date

from pydantic import BaseModel, Field

from app.optimization.common.contracts import ObjectiveWeights, ScenarioParams
from app.schemas.scenario_def import (
    CustomerDef,
    DockDef,
    DowntimeDef,
    EquipmentDef,
    FacilityDef,
    OrderDef,
    OrderLineDef,
    PackStationDef,
    ScenarioDefinition,
    SkuDef,
    VehicleDef,
    WorkerDef,
)

ANCHOR_LAT, ANCHOR_LON = 37.5000, 127.0000  # synthetic DC anchor (Seoul area); display only

TW_SLOTS = [(540, 720), (600, 840), (780, 1020), (840, 1080), (540, 1080), (660, 900)]  # local minutes


class GeneratorConfig(BaseModel):
    name: str = "synthetic"
    facility_code: str = "DC1"
    seed: int = 1
    operating_date: date = date(2026, 10, 15)
    n_orders: int = Field(default=30, ge=1, le=600)
    n_customers: int | None = None
    n_skus: int = 60
    n_workers: int = 5
    n_pack_stations: int = 2
    n_forklifts: int | None = None
    n_docks: int = 2
    n_vans: int = 3
    n_trucks: int = 1
    area_km: float = 15.0
    release_span: tuple[int, int] = (360, 660)  # orders arrive 06:00–11:00
    deadline_tightness: float = 1.0  # >1 → tighter cutoffs
    max_lines: int = 4
    max_qty: int = 6
    inventory_shortage_skus: int = 0
    station_downtime: tuple[int, int] | None = None  # (start_local, end_local) on station PS1
    time_window_mode: str = "soft"
    description: str = ""


def _latlon(x_km: float, y_km: float) -> tuple[float, float]:
    lat = ANCHOR_LAT + y_km / 110.574
    lon = ANCHOR_LON + x_km / (111.320 * math.cos(math.radians(ANCHOR_LAT)))
    return round(lat, 6), round(lon, 6)


def generate(cfg: GeneratorConfig) -> ScenarioDefinition:
    rng = random.Random(cfg.seed)
    n_cust = cfg.n_customers or max(1, int(cfg.n_orders * 0.75))

    lat, lon = _latlon(0, 0)
    facility = FacilityDef(
        code=cfg.facility_code,
        name=f"수도권 합성 물류센터 {cfg.facility_code} (synthetic)",
        timezone="Asia/Seoul",
        x_km=0,
        y_km=0,
        lat=lat,
        lon=lon,
    )
    customers = []
    for i in range(n_cust):
        r = cfg.area_km * math.sqrt(rng.random())
        th = rng.uniform(0, 2 * math.pi)
        x, y = round(r * math.cos(th), 3), round(r * math.sin(th), 3)
        tws, twe = rng.choice(TW_SLOTS)
        la, lo = _latlon(x, y)
        customers.append(
            CustomerDef(
                code=f"C{i + 1:03d}",
                name=f"고객 {i + 1:03d}",
                x_km=x,
                y_km=y,
                lat=la,
                lon=lo,
                service_min=rng.randint(5, 12),
                tw_start_local=tws,
                tw_end_local=twe,
            )
        )

    skus = []
    for i in range(cfg.n_skus):
        zone = rng.choices(["A", "B", "C"], weights=[6, 3, 1])[0]
        skus.append(
            SkuDef(
                code=f"SKU{i + 1:03d}",
                name=f"상품 {i + 1:03d}",
                zone=zone,
                unit_weight_g=rng.randint(200, 12000),
                unit_volume_ml=rng.randint(500, 30000),
                pick_sec_per_unit=rng.randint(10, 40),
            )
        )

    orders, demand = [], {s.code: 0 for s in skus}
    cust_by_code = {c.code: c for c in customers}
    for i in range(cfg.n_orders):
        c = customers[i] if i < n_cust else rng.choice(customers)
        rel = rng.randint(*cfg.release_span)
        travel_est = math.ceil(math.hypot(c.x_km, c.y_km) * 1.3 / 30 * 60)
        slack = int((rng.randint(45, 120)) / cfg.deadline_tightness)
        due = cust_by_code[c.code].tw_end_local - travel_est - slack
        due = max(due, rel + int(90 / cfg.deadline_tightness))
        lines = []
        for sku in rng.sample(skus, rng.randint(1, cfg.max_lines)):
            q = rng.randint(1, cfg.max_qty)
            lines.append(OrderLineDef(sku_code=sku.code, qty=q))
            demand[sku.code] += q
        pr = rng.choices([1, 2, 3], weights=[80, 15, 5])[0]
        orders.append(
            OrderDef(
                code=f"O{i + 1:04d}", customer_code=c.code, release_local=rel, due_local=due, priority=pr, lines=lines
            )
        )

    inventory = {s: math.ceil(q * rng.uniform(1.1, 2.0)) + rng.randint(0, 5) for s, q in demand.items()}
    short = [s for s in sorted(demand, key=lambda k: -demand[k]) if demand[s] > 0][: cfg.inventory_shortage_skus]
    for s in short:
        inventory[s] = max(0, demand[s] // 2)

    shifts = [(360, 900, 840), (420, 960, 900), (480, 1020, 960), (600, 1140, 1080)]
    workers = []
    for i in range(cfg.n_workers):
        s, e, reg = shifts[i % len(shifts)]
        skills = ["pick"]
        if i % 2 == 0 or cfg.n_workers <= 2:
            skills.append("pack")
        if i % 3 == 0:
            skills.append("cold")
        workers.append(
            WorkerDef(
                code=f"W{i + 1:02d}",
                name=f"작업자 {i + 1:02d}",
                skills=skills,
                hourly_cost=rng.choice([14000, 15000, 16500]),
                shift_start_local=s,
                shift_end_local=e,
                regular_end_local=reg,
            )
        )
    n_fl = cfg.n_forklifts if cfg.n_forklifts is not None else max(1, cfg.n_workers // 4)
    equipment = [EquipmentDef(code=f"FL{i + 1}", kind="forklift", name=f"지게차 {i + 1}") for i in range(n_fl)]
    stations = [
        PackStationDef(code=f"PS{i + 1}", name=f"포장대 {i + 1}", open_start_local=360, open_end_local=1200)
        for i in range(cfg.n_pack_stations)
    ]
    docks = [
        DockDef(
            code=f"D{i + 1}",
            name=f"도크 {i + 1}",
            vehicle_classes=["van", "truck"] if i % 2 == 0 else ["van"],
            open_start_local=420,
            open_end_local=1290,
        )
        for i in range(cfg.n_docks)
    ]
    vehicles = [
        VehicleDef(
            code=f"V{i + 1:02d}",
            vehicle_class="van",
            capacity_kg=700,
            capacity_l=4000,
            fixed_cost=70000,
            cost_per_km=850,
            shift_start_local=480,
            shift_end_local=1320,
        )
        for i in range(cfg.n_vans)
    ]
    vehicles += [
        VehicleDef(
            code=f"T{i + 1:02d}",
            vehicle_class="truck",
            capacity_kg=2000,
            capacity_l=12000,
            fixed_cost=120000,
            cost_per_km=1300,
            shift_start_local=480,
            shift_end_local=1320,
        )
        for i in range(cfg.n_trucks)
    ]
    downtimes = []
    if cfg.station_downtime and stations:
        downtimes.append(
            DowntimeDef(
                resource_type="pack_station",
                resource_code="PS1",
                start_local=cfg.station_downtime[0],
                end_local=cfg.station_downtime[1],
                reason="scheduled_maintenance",
            )
        )

    return ScenarioDefinition(
        name=cfg.name,
        description=cfg.description,
        seed=cfg.seed,
        operating_date=cfg.operating_date,
        horizon_start_local=360,
        horizon_min=960,
        facility=facility,
        customers=customers,
        skus=skus,
        inventory=inventory,
        orders=orders,
        workers=workers,
        equipment=equipment,
        pack_stations=stations,
        docks=docks,
        vehicles=vehicles,
        downtimes=downtimes,
        params=ScenarioParams(time_window_mode=cfg.time_window_mode),  # type: ignore[arg-type]
        weights=ObjectiveWeights(),
    )


DEMO_SCENARIOS: dict[str, GeneratorConfig] = {
    "normal_day": GeneratorConfig(
        name="normal_day",
        facility_code="DC-NORMAL",
        seed=101,
        n_orders=40,
        n_workers=6,
        n_pack_stations=3,
        n_docks=2,
        n_vans=4,
        n_trucks=1,
        description="평일 일반 물동량: 40건 주문, 작업자 6명, 포장대 3, 도크 2, 차량 5",
    ),
    "peak_demand": GeneratorConfig(
        name="peak_demand",
        facility_code="DC-PEAK",
        seed=202,
        n_orders=120,
        n_workers=9,
        n_pack_stations=4,
        n_docks=3,
        n_vans=7,
        n_trucks=2,
        deadline_tightness=1.3,
        inventory_shortage_skus=2,
        description="성수기 피크: 120건 주문, 마감 1.3배 타이트, 일부 SKU 재고 부족(명시적 백오더)",
    ),
    "vehicle_breakdown": GeneratorConfig(
        name="vehicle_breakdown",
        facility_code="DC-BREAKDOWN",
        seed=303,
        n_orders=50,
        n_workers=6,
        n_pack_stations=3,
        n_docks=2,
        n_vans=4,
        n_trucks=1,
        description="차량 고장 데모: 기준 계획 수립 후 교란 시뮬레이터에서 V02 고장 이벤트를 주입",
    ),
    "warehouse_bottleneck": GeneratorConfig(
        name="warehouse_bottleneck",
        facility_code="DC-BOTTLENECK",
        seed=404,
        n_orders=70,
        n_workers=5,
        n_pack_stations=2,
        n_docks=2,
        n_vans=5,
        n_trucks=1,
        station_downtime=(600, 720),
        description="창고 병목: 포장대 2개 중 PS1 10:00–12:00 정비, 작업자 5명",
    ),
}
