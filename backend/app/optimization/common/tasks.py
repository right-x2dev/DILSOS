"""Order → (Order, PICK, PACK) derivation shared by the snapshot builder and urgent-order events."""

from __future__ import annotations

import math
from typing import Any

from app.optimization.common.contracts import Order, OrderLine, Resource, ResourceRequirement, Sku, Task

DEFAULT_TASK_MODEL: dict[str, Any] = {
    "pick_base_min": 3,
    "pack_base_min": 4,
    "pack_sec_per_unit": 10,
    "forklift_weight_kg": 120,
    "zone_skill": {"C": "cold"},
}


def make_order(
    order_id: str,
    customer_id: str,
    release_min: int,
    due_min: int,
    priority: int,
    lines: list[tuple[str, int]],
    skus: dict[str, Sku],
    resources: list[Resource],
    task_model: dict[str, Any] | None = None,
) -> tuple[Order, list[Task]]:
    tm = {**DEFAULT_TASK_MODEL, **(task_model or {})}
    units = sum(q for _, q in lines)
    weight_kg = math.ceil(sum(q * skus[s].unit_weight_g for s, q in lines) / 1000)
    volume_l = math.ceil(sum(q * skus[s].unit_volume_ml for s, q in lines) / 1000)
    order = Order(
        id=order_id,
        customer_id=customer_id,
        release_min=release_min,
        due_min=due_min,
        priority=priority,
        lines=[OrderLine(sku_id=s, qty=q) for s, q in lines],
        weight_kg=weight_kg,
        volume_l=volume_l,
        units=units,
    )
    workers = [r for r in resources if r.kind == "worker"]
    stations = [r.id for r in resources if r.kind == "pack_station"]
    forklifts = [r.id for r in resources if r.kind == "equipment" and "forklift" in r.skills]
    zones = sorted({skus[s].zone for s, _ in lines})
    need = {"pick"} | {tm["zone_skill"][z] for z in zones if z in tm["zone_skill"]}
    pickers = [w.id for w in workers if need <= set(w.skills)]
    pick_sec = sum(q * skus[s].pick_sec_per_unit for s, q in lines)
    pick_req = [ResourceRequirement(kind="worker", eligible_ids=pickers)]
    if weight_kg > tm["forklift_weight_kg"]:
        pick_req.append(ResourceRequirement(kind="equipment", eligible_ids=forklifts))
    pick = Task(
        id=f"{order_id}-PICK",
        order_id=order_id,
        type="PICK",
        release_min=release_min,
        requirements=pick_req,
        duration_min=tm["pick_base_min"] + len(zones) * 2 + math.ceil(pick_sec / 60),
    )
    packers = [w.id for w in workers if "pack" in w.skills]
    pack = Task(
        id=f"{order_id}-PACK",
        order_id=order_id,
        type="PACK",
        release_min=release_min,
        requirements=[
            ResourceRequirement(kind="worker", eligible_ids=packers),
            ResourceRequirement(kind="pack_station", eligible_ids=stations),
        ],
        duration_min=tm["pack_base_min"] + math.ceil(units * tm["pack_sec_per_unit"] / 60),
        predecessors=[f"{order_id}-PICK"],
    )
    return order, [pick, pack]
