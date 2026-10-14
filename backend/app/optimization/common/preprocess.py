"""Deterministic pre-processing shared by all algorithms (so comparisons are fair).

* Cancelled orders are removed (reason ``cancelled``, no penalty).
* Inventory is allocated in (priority desc, release asc, id asc) order (independent of due dates, so a
  coordinator that tightens cutoffs never changes which orders are backordered); orders that cannot be fully
  covered become explicit backorders (reason ``insufficient_inventory``) — inventory never goes negative.
* Orders with a task that has no eligible resource are unserved (``no_eligible_resource``).
* For routing scopes, orders heavier/bulkier than every available vehicle are unserved
  (``exceeds_vehicle_capacity``).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.optimization.common.contracts import ScenarioSnapshot, UnservedOrder


@dataclass
class Prepared:
    servable: list[str]  # order ids, deterministic order
    unserved: dict[str, str] = field(default_factory=dict)  # order id -> reason
    inventory_left: dict[str, int] = field(default_factory=dict)


def prepare(snap: ScenarioSnapshot, routing: bool) -> Prepared:
    cancelled = set(snap.cancelled_order_ids)
    unserved: dict[str, str] = {}
    tasks_by_order: dict[str, list] = {}
    for t in snap.tasks:
        tasks_by_order.setdefault(t.order_id, []).append(t)
    vehicles = [v for v in snap.vehicles if v.available]
    max_kg = max((v.capacity_kg for v in vehicles), default=0)
    max_l = max((v.capacity_l for v in vehicles), default=0)

    inv = dict(snap.inventory)
    ordered = sorted(snap.orders, key=lambda o: (-o.priority, o.release_min, o.id))
    servable: list[str] = []
    for o in ordered:
        if o.id in cancelled:
            unserved[o.id] = "cancelled"
            continue
        ts = tasks_by_order.get(o.id, [])
        if not ts or any(not r.eligible_ids for t in ts for r in t.requirements):
            unserved[o.id] = "no_eligible_resource"
            continue
        if routing and (o.weight_kg > max_kg or o.volume_l > max_l):
            unserved[o.id] = "exceeds_vehicle_capacity" if vehicles else "no_vehicle_available"
            continue
        need: dict[str, int] = {}
        for ln in o.lines:
            need[ln.sku_id] = need.get(ln.sku_id, 0) + ln.qty
        if any(inv.get(s, 0) < q for s, q in need.items()):
            unserved[o.id] = "insufficient_inventory"
            continue
        for s, q in need.items():
            inv[s] -= q
        servable.append(o.id)
    # deterministic id order for downstream consumers
    servable.sort()
    return Prepared(servable=servable, unserved=unserved, inventory_left=inv)


def unserved_list(snap: ScenarioSnapshot, reasons: dict[str, str]) -> list[UnservedOrder]:
    om = snap.order_map()
    out = []
    for oid in sorted(reasons):
        r = reasons[oid]
        pen = 0.0 if r == "cancelled" else snap.weights.unserved_penalty * om[oid].priority
        out.append(UnservedOrder(order_id=oid, reason=r, penalty=pen))
    return out
