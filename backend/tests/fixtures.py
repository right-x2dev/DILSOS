"""Small hand-checkable scenario definitions for solver/validator tests."""

from __future__ import annotations

from datetime import date

from app.optimization.common.contracts import ScenarioSnapshot
from app.schemas.scenario_def import (
    CustomerDef,
    DockDef,
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
from app.services.snapshot_builder import build_snapshot


def tiny_definition(**overrides) -> ScenarioDefinition:  # type: ignore[no-untyped-def]
    """3 orders, 2 workers (one picker+packer, one picker), 1 pack station, 1 dock, 2 vans.

    Horizon 06:00–22:00 KST (960 min). SKU S1 picks in 30 s/unit.
    """
    base = dict(
        name="tiny",
        seed=7,
        operating_date=date(2026, 10, 15),
        horizon_start_local=360,
        horizon_min=960,
        facility=FacilityDef(code="T", name="tiny DC"),
        customers=[
            CustomerDef(code="C1", name="c1", x_km=3, y_km=4, service_min=5, tw_start_local=600, tw_end_local=900),
            CustomerDef(code="C2", name="c2", x_km=-6, y_km=8, service_min=5, tw_start_local=540, tw_end_local=840),
            CustomerDef(code="C3", name="c3", x_km=1, y_km=-2, service_min=5, tw_start_local=600, tw_end_local=1020),
        ],
        skus=[SkuDef(code="S1", name="s1", zone="A", unit_weight_g=2000, unit_volume_ml=3000, pick_sec_per_unit=30)],
        inventory={"S1": 100},
        orders=[
            OrderDef(
                code="O1",
                customer_code="C1",
                release_local=360,
                due_local=480,
                lines=[OrderLineDef(sku_code="S1", qty=4)],
            ),
            OrderDef(
                code="O2",
                customer_code="C2",
                release_local=380,
                due_local=450,
                priority=3,
                lines=[OrderLineDef(sku_code="S1", qty=2)],
            ),
            OrderDef(
                code="O3",
                customer_code="C3",
                release_local=400,
                due_local=600,
                lines=[OrderLineDef(sku_code="S1", qty=6)],
            ),
        ],
        workers=[
            WorkerDef(
                code="W1",
                name="w1",
                skills=["pick", "pack"],
                hourly_cost=15000,
                shift_start_local=360,
                shift_end_local=900,
                regular_end_local=840,
            ),
            WorkerDef(
                code="W2",
                name="w2",
                skills=["pick"],
                hourly_cost=12000,
                shift_start_local=360,
                shift_end_local=900,
                regular_end_local=840,
            ),
        ],
        equipment=[EquipmentDef(code="FL1")],
        pack_stations=[PackStationDef(code="P1", open_start_local=360, open_end_local=1200)],
        docks=[DockDef(code="D1", vehicle_classes=["van", "truck"], open_start_local=420, open_end_local=1290)],
        vehicles=[
            VehicleDef(code="V1", capacity_kg=300, capacity_l=2000, shift_start_local=480, shift_end_local=1320),
            VehicleDef(code="V2", capacity_kg=300, capacity_l=2000, shift_start_local=480, shift_end_local=1320),
        ],
    )
    base.update(overrides)
    return ScenarioDefinition(**base)


def tiny_snapshot(**overrides) -> ScenarioSnapshot:  # type: ignore[no-untyped-def]
    return build_snapshot(tiny_definition(**overrides))
