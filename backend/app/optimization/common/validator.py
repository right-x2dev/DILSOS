"""Deterministic feasibility validator — ``validate_schedule(snapshot, result) -> ValidationReport``.

Written independently of every solver (it re-derives everything from the snapshot) so a solver bug
cannot validate itself. Rules (spec §3.2):

  U1  every order is served exactly once or explicitly unserved with a reason (no silent loss)
  W1  every task of a served order assigned exactly once; none for unserved orders (unless frozen)
  W2  duration = processing time (no preemption)          W3  release / current-time respected
  W4  precedence pick → pack                              W5  eligible resource per requirement
  W6  inside an availability window (shift, downtime)     W7  no overlap per unit-capacity resource
  W8  within horizon                                      W9  inventory never negative
  W10 frozen (executed/committed) work unchanged
  D1  route loading starts after ALL its orders are packed   D2 dock compatible with vehicle class
  D3  load inside dock availability; LOAD task matches route D4 load duration rule
  D5  departure ≥ load end                                    (dock overlap is W7 on LOAD tasks)
  R1  each served order delivered exactly once; stop customer matches order
  R2  capacity (weight & volume) at every segment          R3 time propagation (travel/service/wait)
  R4  customer time windows (hard → error, soft → lateness reported)
  R5  vehicle shift & availability; one route per vehicle  R6 distance consistent with travel matrix
  R7  starts at depot / returns when required              R8 departure ≥ goods readiness
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from app.optimization.common.contracts import (
    ScenarioSnapshot,
    ScheduleResult,
    UnservedOrder,
    ValidationReport,
    Violation,
)
from app.optimization.common.preprocess import unserved_list

SCOPES: dict[str, list[str]] = {
    "warehouse": ["warehouse"],
    "dock": ["warehouse", "dock", "routing"],
    "routing": ["routing"],
    "integrated": ["warehouse", "dock", "routing"],
}


class _V:
    def __init__(self) -> None:
        self.items: list[Violation] = []
        self.rules: set[str] = set()

    def rule(self, code: str) -> None:
        self.rules.add(code)

    def add(self, rule: str, etype: str, eid: str, msg: str, severity: str = "error", **obs: Any) -> None:
        self.items.append(
            Violation(
                rule=rule,
                severity=severity,  # type: ignore[arg-type]
                entity_type=etype,
                entity_id=eid,
                message=msg,
                observed=obs,
            )
        )


def validate_schedule(snap: ScenarioSnapshot, result: ScheduleResult) -> ValidationReport:
    scope = SCOPES[result.problem_type]
    v = _V()
    om = snap.order_map()
    tmap = snap.task_map()
    rmap = snap.resource_map()
    cmap = snap.customer_map()
    vmap = snap.vehicle_map()
    H = snap.horizon_min
    cancelled = set(snap.cancelled_order_ids)
    frozen = {f.task_id: f for f in snap.frozen_assignments}
    unserved_ids = set(result.unserved_order_ids)

    # ---------------- U1: explicit unserved ----------------
    v.rule("U1")
    for oid in unserved_ids:
        if oid not in om:
            v.add("U1", "order", oid, "unserved list references unknown order")
    for oid in cancelled:
        if oid in om and oid not in unserved_ids:
            v.add("U1", "order", oid, "cancelled order not reported as unserved")
    reasons = {u.order_id: u.reason for u in result.unserved}
    for oid in unserved_ids:
        if oid not in reasons:
            v.add("U1", "order", oid, "unserved order without reason")
    served = [o.id for o in snap.orders if o.id not in unserved_ids]

    wh = [a for a in result.assignments if a.task_type in ("PICK", "PACK")]
    loads = [a for a in result.assignments if a.task_type == "LOAD"]
    pack_ready: dict[str, int] = {}

    # ---------------- warehouse ----------------
    if "warehouse" in scope:
        for code in ("W1", "W2", "W3", "W4", "W5", "W6", "W7", "W8", "W9", "W10"):
            v.rule(code)
        seen: dict[str, int] = defaultdict(int)
        by_task = {}
        for a in wh:
            seen[a.task_id] += 1
            by_task[a.task_id] = a
        for tid, n in seen.items():
            if n > 1:
                v.add("W1", "task", tid, "task assigned more than once", count=n)
        for oid in served:
            for tk in (x for x in snap.tasks if x.order_id == oid):
                if tk.id not in by_task:
                    v.add("W1", "task", tk.id, "task of served order is missing", order_id=oid)
        for a in wh:
            t = tmap.get(a.task_id)
            if t is None:
                v.add("W1", "task", a.task_id, "assignment for unknown task")
                continue
            if t.order_id in unserved_ids and not a.frozen:
                v.add("W1", "task", t.id, "unserved order still has (non-frozen) assignments", order_id=t.order_id)
            if a.order_ids != [t.order_id]:
                v.add("W1", "task", t.id, "assignment order id mismatch", observed=a.order_ids)
            if a.end_min - a.start_min != t.duration_min:
                v.add(
                    "W2",
                    "task",
                    t.id,
                    "duration mismatch / preemption",
                    start=a.start_min,
                    end=a.end_min,
                    expected=t.duration_min,
                )
            if not a.frozen:
                if a.start_min < t.release_min:
                    v.add("W3", "task", t.id, "starts before release", start=a.start_min, release=t.release_min)
                if a.start_min < snap.current_time_min:
                    v.add(
                        "W3",
                        "task",
                        t.id,
                        "re-planned task starts in the past",
                        start=a.start_min,
                        now=snap.current_time_min,
                    )
            for p in t.predecessors:
                pa = by_task.get(p)
                if pa is None and p not in frozen:
                    v.add("W4", "task", t.id, "predecessor not scheduled", predecessor=p)
                elif pa is not None and a.start_min < pa.end_min:
                    v.add(
                        "W4",
                        "task",
                        t.id,
                        "starts before predecessor ends",
                        start=a.start_min,
                        predecessor=p,
                        predecessor_end=pa.end_min,
                    )
            kinds = {q.kind for q in t.requirements}
            if set(a.resources) != kinds:
                v.add(
                    "W5",
                    "task",
                    t.id,
                    "resource requirements not satisfied exactly",
                    got=sorted(a.resources),
                    required=sorted(kinds),
                )
            for q in t.requirements:
                rid = a.resources.get(q.kind)
                if rid is not None and rid not in q.eligible_ids:
                    v.add("W5", "task", t.id, "ineligible resource", resource=rid, kind=q.kind)
            if a.resource_id not in a.resources.values():
                v.add("W5", "task", t.id, "primary resource not among assigned resources")
            if a.start_min < 0 or a.end_min > H:
                v.add("W8", "task", t.id, "outside planning horizon", start=a.start_min, end=a.end_min, horizon=H)
        # W9 inventory
        use: dict[str, int] = defaultdict(int)
        for oid in served:
            if oid in cancelled:
                continue
            for ln in om[oid].lines:
                use[ln.sku_id] += ln.qty
        for sku, qty in use.items():
            if qty > snap.inventory.get(sku, 0):
                v.add("W9", "sku", sku, "inventory would go negative", demand=qty, on_hand=snap.inventory.get(sku, 0))
        # W10 frozen
        for f in snap.frozen_assignments:
            fa = by_task.get(f.task_id)
            if fa is None or fa.start_min != f.start_min or fa.end_min != f.end_min or fa.resources != f.resources:
                v.add("W10", "task", f.task_id, "frozen work was changed or dropped", reason=f.reason)
        for a in wh:
            for oid in a.order_ids:
                pack_ready[oid] = max(pack_ready.get(oid, 0), a.end_min)

    # ---------------- resource overlap & availability (warehouse + dock LOAD tasks) ----------------
    usage: dict[str, list[tuple[int, int, str]]] = defaultdict(list)
    for a in wh + loads:
        for rid in a.resources.values():
            usage[rid].append((a.start_min, a.end_min, a.task_id))
    for rid, items in usage.items():
        res = rmap.get(rid)
        if res is None:
            v.add("W5", "resource", rid, "unknown resource")
            continue
        items.sort()
        # sorted by start: any overlapping pair implies an overlapping consecutive pair
        for (_s1, e1, t1), (s2, _e2, t2) in zip(items, items[1:], strict=False):
            if s2 < e1:
                v.add(
                    "W7",
                    "resource",
                    rid,
                    "overlapping tasks on unit-capacity resource",
                    a=t1,
                    b=t2,
                    a_end=e1,
                    b_start=s2,
                )
        for s, e, tid in items:
            if tid in frozen:
                continue
            if not any(i.start <= s and e <= i.end for i in res.available):
                v.add(
                    "W6" if res.kind != "dock" else "D3",
                    "resource",
                    rid,
                    "task outside resource availability (shift/downtime/dock hours)",
                    task=tid,
                    start=s,
                    end=e,
                )

    # ---------------- dock ----------------
    if "dock" in scope:
        for code in ("D1", "D2", "D3", "D4", "D5"):
            v.rule(code)
        load_by_vehicle = {}
        for a in loads:
            vid = a.task_id.removeprefix("LOAD-")
            if vid in load_by_vehicle:
                v.add("D3", "vehicle", vid, "more than one LOAD task for vehicle")
            load_by_vehicle[vid] = a
        for rt in result.routes:
            if not rt.stops:
                continue
            la = load_by_vehicle.get(rt.vehicle_id)
            frozen_route = any(fr.vehicle_id == rt.vehicle_id for fr in snap.frozen_routes)
            if la is None or rt.dock_id is None:
                v.add("D3", "route", rt.vehicle_id, "route has no dock loading assignment")
                continue
            if (la.start_min, la.end_min, la.resource_id) != (rt.load_start_min, rt.load_end_min, rt.dock_id):
                v.add("D3", "route", rt.vehicle_id, "LOAD task does not match route loading times/dock")
            if sorted(la.order_ids) != sorted(rt.order_ids):
                v.add("D3", "route", rt.vehicle_id, "LOAD task orders differ from route orders")
            dock = rmap.get(rt.dock_id)
            veh = vmap.get(rt.vehicle_id)
            if dock is None or dock.kind != "dock":
                v.add("D2", "route", rt.vehicle_id, "unknown dock", dock=rt.dock_id)
            elif veh is not None and dock.vehicle_classes and veh.vehicle_class not in dock.vehicle_classes:
                v.add(
                    "D2",
                    "route",
                    rt.vehicle_id,
                    "dock incompatible with vehicle class",
                    dock=rt.dock_id,
                    vehicle_class=veh.vehicle_class,
                )
            expect = snap.params.load_base_min + snap.params.load_per_order_min * len(rt.order_ids)
            if rt.load_start_min is not None and rt.load_end_min is not None:
                if not frozen_route and rt.load_end_min - rt.load_start_min != expect:
                    v.add(
                        "D4",
                        "route",
                        rt.vehicle_id,
                        "load duration mismatch",
                        observed=rt.load_end_min - rt.load_start_min,
                        expected=expect,
                    )
                ready = max((pack_ready.get(o, 0) for o in rt.order_ids), default=0)
                if not frozen_route and rt.load_start_min < ready:
                    v.add(
                        "D1",
                        "route",
                        rt.vehicle_id,
                        "loading starts before all orders are packed",
                        load_start=rt.load_start_min,
                        ready=ready,
                    )
                if rt.departure_min < rt.load_end_min:
                    v.add(
                        "D5",
                        "route",
                        rt.vehicle_id,
                        "departs before loading ends",
                        departure=rt.departure_min,
                        load_end=rt.load_end_min,
                    )
                if veh is not None and not frozen_route and rt.load_start_min < veh.shift_start:
                    v.add("R5", "route", rt.vehicle_id, "loading before vehicle shift start")

    # ---------------- routing ----------------
    if "routing" in scope:
        for code in ("R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8"):
            v.rule(code)
        li = snap.loc_index()
        D, T = snap.travel.distance_m, snap.travel.duration_min
        depot = snap.depot_location_id
        delivered: dict[str, int] = defaultdict(int)
        vehicles_seen: set[str] = set()
        for r in result.routes:
            veh = vmap.get(r.vehicle_id)
            if veh is None:
                v.add("R5", "route", r.vehicle_id, "unknown vehicle")
                continue
            if r.vehicle_id in vehicles_seen:
                v.add("R5", "route", r.vehicle_id, "vehicle used by more than one route")
            vehicles_seen.add(r.vehicle_id)
            if not r.stops:
                continue
            if not veh.available:
                v.add("R5", "route", r.vehicle_id, "unavailable vehicle dispatched")
            stop_orders = [o for x in r.stops for o in x.order_ids]
            if sorted(stop_orders) != sorted(r.order_ids):
                v.add("R1", "route", r.vehicle_id, "route order list differs from stop orders")
            kg = sum(om[o].weight_kg for o in r.order_ids if o in om)
            lt = sum(om[o].volume_l for o in r.order_ids if o in om)
            if kg != r.load_kg or lt != r.load_l:
                v.add("R2", "route", r.vehicle_id, "reported load differs from order sum", kg=kg, l=lt)
            if kg > veh.capacity_kg or lt > veh.capacity_l:
                v.add(
                    "R2",
                    "route",
                    r.vehicle_id,
                    "capacity exceeded",
                    kg=kg,
                    cap_kg=veh.capacity_kg,
                    l=lt,
                    cap_l=veh.capacity_l,
                )
            # readiness
            if "dock" in scope:
                ready = max((pack_ready.get(o, 0) for o in r.order_ids), default=0)
            else:
                ready = max((om[o].due_min for o in r.order_ids if o in om), default=0)
            is_frozen_route = any(fr.vehicle_id == r.vehicle_id for fr in snap.frozen_routes)
            if r.departure_min < ready and not is_frozen_route:
                v.add(
                    "R8",
                    "route",
                    r.vehicle_id,
                    "departs before goods are ready",
                    departure=r.departure_min,
                    ready=ready,
                )
            if r.departure_min < veh.shift_start and not is_frozen_route:
                v.add("R5", "route", r.vehicle_id, "departs before vehicle shift", departure=r.departure_min)
            # propagation
            prev_loc, prev_dep = depot, r.departure_min
            dist = 0
            remaining_kg, remaining_l = kg, lt
            for i, st in enumerate(r.stops):
                if st.seq != i + 1:
                    v.add("R3", "stop", f"{r.vehicle_id}#{i + 1}", "stop sequence numbering broken")
                c = cmap.get(st.customer_id)
                if c is None:
                    v.add("R1", "stop", f"{r.vehicle_id}#{st.seq}", "unknown customer")
                    continue
                for oid in st.order_ids:
                    delivered[oid] += 1
                    if oid in om and om[oid].customer_id != st.customer_id:
                        v.add("R1", "order", oid, "delivered to wrong customer", stop_customer=st.customer_id)
                    if oid in om:
                        remaining_kg -= om[oid].weight_kg
                        remaining_l -= om[oid].volume_l
                if st.location_id != c.location_id:
                    v.add("R3", "stop", f"{r.vehicle_id}#{st.seq}", "stop location mismatch")
                exp_arr = prev_dep + T[li[prev_loc]][li[c.location_id]]
                dist += D[li[prev_loc]][li[c.location_id]]
                if st.arrival_min != exp_arr:
                    v.add(
                        "R3",
                        "stop",
                        f"{r.vehicle_id}#{st.seq}",
                        "arrival ≠ previous departure + travel time",
                        arrival=st.arrival_min,
                        expected=exp_arr,
                    )
                exp_start = max(st.arrival_min, c.tw_start)
                if st.service_start_min != exp_start:
                    v.add(
                        "R3",
                        "stop",
                        f"{r.vehicle_id}#{st.seq}",
                        "service start ≠ max(arrival, window start)",
                        service_start=st.service_start_min,
                        expected=exp_start,
                    )
                if st.service_end_min != st.service_start_min + c.service_min or st.departure_min != st.service_end_min:
                    v.add("R3", "stop", f"{r.vehicle_id}#{st.seq}", "service/departure time inconsistent")
                if st.wait_min != st.service_start_min - st.arrival_min:
                    v.add("R3", "stop", f"{r.vehicle_id}#{st.seq}", "wait minutes inconsistent")
                late = max(0, st.service_start_min - c.tw_end)
                if late != st.late_min:
                    v.add(
                        "R4",
                        "stop",
                        f"{r.vehicle_id}#{st.seq}",
                        "reported lateness inconsistent",
                        reported=st.late_min,
                        actual=late,
                    )
                if late > 0:
                    sev = "error" if snap.params.time_window_mode == "hard" else "warning"
                    v.add(
                        "R4",
                        "stop",
                        f"{r.vehicle_id}#{st.seq}",
                        "delivery after customer window end",
                        severity=sev,
                        late_min=late,
                        customer=c.id,
                    )
                if (st.load_after_kg, st.load_after_l) != (remaining_kg, remaining_l):
                    v.add("R2", "stop", f"{r.vehicle_id}#{st.seq}", "load trajectory inconsistent")
                prev_loc, prev_dep = c.location_id, st.departure_min
            exp_ret = prev_dep
            if snap.params.return_to_depot:
                exp_ret = prev_dep + T[li[prev_loc]][li[depot]]
                dist += D[li[prev_loc]][li[depot]]
            if r.return_min != exp_ret:
                v.add("R7", "route", r.vehicle_id, "return time inconsistent", reported=r.return_min, expected=exp_ret)
            if r.return_min > veh.shift_end:
                v.add(
                    "R5",
                    "route",
                    r.vehicle_id,
                    "route ends after vehicle shift",
                    return_min=r.return_min,
                    shift_end=veh.shift_end,
                )
            if r.return_min > H:
                v.add("R5", "route", r.vehicle_id, "route ends after horizon", return_min=r.return_min)
            if dist != r.distance_m:
                v.add(
                    "R6",
                    "route",
                    r.vehicle_id,
                    "distance inconsistent with travel matrix",
                    reported=r.distance_m,
                    expected=dist,
                )
        for oid in served:
            n = delivered.get(oid, 0)
            if n != 1:
                v.add("R1", "order", oid, "served order not delivered exactly once", deliveries=n)
        for oid in unserved_ids:
            if delivered.get(oid, 0):
                v.add("R1", "order", oid, "unserved order appears on a route")

    unserved: list[UnservedOrder] = list(result.unserved) or unserved_list(
        snap, {o: reasons.get(o, "unspecified") for o in unserved_ids}
    )
    for u in unserved:
        v.add("U1", "order", u.order_id, f"order unserved: {u.reason}", severity="info", penalty=u.penalty)

    errors = [x for x in v.items if x.severity == "error"]
    return ValidationReport(
        is_feasible=not errors,
        scope=scope,
        checked_rules=sorted(v.rules),
        violations=v.items,
        unserved=unserved,
        stats={
            "errors": len(errors),
            "warnings": sum(1 for x in v.items if x.severity == "warning"),
            "orders": len(snap.orders),
            "served": len([o for o in served if o not in cancelled]),
            "unserved": len(unserved_ids),
            "assignments": len(result.assignments),
            "routes": len([r for r in result.routes if r.stops]),
        },
    )
