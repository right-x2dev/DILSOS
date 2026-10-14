"""Pre-solve input checks (POST /scenarios/{id}/validate): schema-level and obvious infeasibilities."""

from __future__ import annotations

from collections import Counter

from app.optimization.common.contracts import ScenarioSnapshot
from app.optimization.common.preprocess import prepare
from app.schemas.api import InputIssue, InputValidation


def validate_inputs(snap: ScenarioSnapshot) -> InputValidation:
    issues: list[InputIssue] = []
    H = snap.horizon_min

    def add(sev: str, code: str, entity: str, msg: str) -> None:
        issues.append(InputIssue(severity=sev, code=code, entity=entity, message=msg))  # type: ignore[arg-type]

    kinds = Counter(r.kind for r in snap.resources)
    for k in ("worker", "pack_station", "dock"):
        if kinds.get(k, 0) == 0:
            add("error", "missing_resource", k, f"no {k} defined — related tasks cannot be scheduled")
    if not any(v.available for v in snap.vehicles):
        add(
            "warning",
            "no_vehicle",
            "vehicles",
            "no available vehicle — routing/integrated runs will leave all orders unserved",
        )
    for r in snap.resources:
        if not r.available:
            add("warning", "never_available", r.id, f"{r.kind} {r.id} has no availability inside the horizon")
    for c in snap.customers:
        if c.tw_end <= 0 or c.tw_start >= H:
            add("warning", "window_outside_horizon", c.id, "customer time window lies outside the planning horizon")
    for o in snap.orders:
        if o.due_min <= o.release_min:
            add("warning", "due_before_release", o.id, "ship cutoff is not after release")
        if o.release_min >= H:
            add("error", "release_after_horizon", o.id, "order released after the horizon end")
    prep = prepare(snap, routing=True)
    reasons = Counter(prep.unserved.values())
    for oid, why in sorted(prep.unserved.items()):
        sev = "info" if why == "cancelled" else "warning"
        add(sev, why, oid, f"order will be explicitly unserved before optimization: {why}")
    for sku, left in prep.inventory_left.items():
        if left < 0:
            add("error", "negative_inventory", sku, "inventory allocation went negative (bug)")
    dock_classes = {c for r in snap.resources if r.kind == "dock" for c in r.vehicle_classes}
    for v in snap.vehicles:
        if v.vehicle_class not in dock_classes:
            add("warning", "no_compatible_dock", v.id, f"no dock accepts vehicle class {v.vehicle_class}")
    return InputValidation(
        ok=not any(i.severity == "error" for i in issues),
        issues=issues,
        summary={
            "orders": len(snap.orders),
            "tasks": len(snap.tasks),
            "resources": dict(kinds),
            "vehicles": len(snap.vehicles),
            "customers": len(snap.customers),
            "pre_unserved": dict(reasons),
            "servable_orders": len(prep.servable),
            "travel_provenance": snap.travel.provenance,
            "travel_version": snap.travel.version,
            "horizon_min": H,
        },
    )
