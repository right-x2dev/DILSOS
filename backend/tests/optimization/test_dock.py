from __future__ import annotations

import pytest

from app.optimization.common.contracts import SolveConfig
from app.optimization.common.routes import Ctx, RoutePlan, repair_plan, time_route
from app.optimization.common.runner import run_algorithm
from app.optimization.common.validator import validate_schedule
from app.schemas.scenario_def import DockDef, DowntimeDef, VehicleDef
from app.seed.generator import DEMO_SCENARIOS, generate
from app.services.snapshot_builder import build_snapshot
from tests.fixtures import tiny_definition, tiny_snapshot

DOCK = ["dock_fifo", "dock_edd", "dock_cpsat"]


def test_route_time_propagation_by_hand():
    snap = tiny_snapshot()
    ctx = Ctx(snap)
    plan = RoutePlan("V1", [["O3"], ["O1"]], ready_min=0, dock_id="D1", load_start=100)
    r = time_route(ctx, plan, departure=114)
    T = snap.travel.duration_min
    li = snap.loc_index()
    c3, c1 = snap.customer_map()["C3"], snap.customer_map()["C1"]
    a1 = 114 + T[li["DEPOT"]][li["L-C3"]]
    s1 = max(a1, c3.tw_start)
    assert (r.stops[0].arrival_min, r.stops[0].service_start_min, r.stops[0].wait_min) == (a1, s1, s1 - a1)
    a2 = s1 + c3.service_min + T[li["L-C3"]][li["L-C1"]]
    assert r.stops[1].arrival_min == a2
    assert r.return_min == max(a2, c1.tw_start) + c1.service_min + T[li["L-C1"]][li["DEPOT"]]
    assert r.load_end_min == 100 + 10 + 2 * 2
    assert r.stops[0].load_after_kg == r.load_kg - snap.order_map()["O3"].weight_kg


def test_hard_window_repair_drops_violating_stop():
    d = tiny_definition()
    d.params.time_window_mode = "hard"
    snap = build_snapshot(d)
    ctx = Ctx(snap)
    # depart very late: C2 window ends 14:00 local (=480) → must be dropped
    plan = RoutePlan("V1", [["O2"], ["O3"]], 0, "D1", 600)
    plan2, route, dropped = repair_plan(ctx, plan, lambda p: 620)
    assert dropped == {"O2": "time_window_infeasible"}
    assert route is not None and [s.customer_id for s in route.stops] == ["C3"]


@pytest.mark.parametrize("alg", DOCK)
def test_dock_tiny_feasible_and_ready_before_load(alg):
    snap = tiny_snapshot()
    r = run_algorithm(snap, alg, SolveConfig(problem_type="dock", time_limit_s=5))
    assert r.validation.is_feasible, [v.message for v in r.validation.errors]
    pack_end = {}
    for a in r.assignments:
        if a.task_type == "PACK":
            pack_end[a.order_ids[0]] = a.end_min
    for route in r.routes:
        assert route.load_start_min >= max(pack_end[o] for o in route.order_ids)
        assert route.departure_min >= route.load_end_min
    assert {"D1", "D2", "D3", "D4", "D5", "R1", "R3"} <= set(r.validation.checked_rules)


def _contention_def():
    d = tiny_definition()
    d.docks = [DockDef(code="D1", vehicle_classes=["van"], open_start_local=420, open_end_local=1290)]
    d.vehicles = [
        VehicleDef(code=f"V{i}", capacity_kg=10, capacity_l=100, shift_start_local=420, shift_end_local=1320)
        for i in range(1, 4)
    ]  # tiny vans → one order each
    return d


@pytest.mark.parametrize("alg", DOCK)
def test_single_dock_no_overlap(alg):
    snap = build_snapshot(_contention_def())
    r = run_algorithm(snap, alg, SolveConfig(problem_type="dock", time_limit_s=5))
    assert r.validation.is_feasible, [v.message for v in r.validation.errors]
    loads = sorted((a.start_min, a.end_min) for a in r.assignments if a.task_type == "LOAD")
    assert len(loads) >= 2
    assert all(b[0] >= a[1] for a, b in zip(loads, loads[1:], strict=False))


@pytest.mark.parametrize("alg", DOCK)
def test_dock_downtime_respected(alg):
    d = _contention_def()
    d.downtimes = [DowntimeDef(resource_type="dock", resource_code="D1", start_local=420, end_local=600)]
    snap = build_snapshot(d)
    r = run_algorithm(snap, alg, SolveConfig(problem_type="dock", time_limit_s=5))
    assert r.validation.is_feasible
    assert all(a.start_min >= 600 - 360 for a in r.assignments if a.task_type == "LOAD")


def test_incompatible_docks_leave_orders_explicitly_unserved():
    d = tiny_definition()
    d.docks = [DockDef(code="D1", vehicle_classes=["truck"], open_start_local=420, open_end_local=1290)]
    snap = build_snapshot(d)
    for alg in DOCK:
        r = run_algorithm(snap, alg, SolveConfig(problem_type="dock", time_limit_s=3))
        assert r.validation.is_feasible
        assert sorted(r.unserved_order_ids) == ["O1", "O2", "O3"]
        assert r.routes == []


def test_cpsat_dock_not_worse_than_heuristics_on_bottleneck():
    snap = build_snapshot(generate(DEMO_SCENARIOS["warehouse_bottleneck"]))
    res = {a: run_algorithm(snap, a, SolveConfig(problem_type="dock", time_limit_s=10, seed=1)) for a in DOCK}
    assert all(x.validation.is_feasible for x in res.values())
    cp = res["dock_cpsat"].metrics.total_lateness_min
    # identical upstream plan & grouping → CP-SAT (warm-started from EDD) can only match or improve lateness
    assert cp <= res["dock_edd"].metrics.total_lateness_min


def test_dock_validator_catches_violations():
    snap = tiny_snapshot()
    r = run_algorithm(snap, "dock_edd", SolveConfig(problem_type="dock"))
    assert r.validation.is_feasible and r.routes
    route = r.routes[0]

    def rules(res):
        return {v.rule for v in validate_schedule(snap, res).violations if v.severity == "error"}

    bad = r.model_copy(deep=True)  # load before packing complete
    br, la = bad.routes[0], next(a for a in bad.assignments if a.task_type == "LOAD")
    shift = br.load_start_min - 1
    for obj in (br,):
        obj.load_start_min -= shift
        obj.load_end_min -= shift
    la.start_min, la.end_min = br.load_start_min, br.load_end_min
    assert "D1" in rules(bad)

    bad = r.model_copy(deep=True)  # depart before loading ends
    bad.routes[0].departure_min = route.load_end_min - 1
    assert {"D5"} & rules(bad)

    bad = r.model_copy(deep=True)  # LOAD task missing
    bad.assignments = [a for a in bad.assignments if a.task_type != "LOAD"]
    assert "D3" in rules(bad)

    bad = r.model_copy(deep=True)  # wrong arrival propagation
    bad.routes[0].stops[0].arrival_min += 3
    assert "R3" in rules(bad)

    bad = r.model_copy(deep=True)  # reported distance inconsistent with matrix
    bad.routes[0].distance_m += 100
    assert "R6" in rules(bad)

    bad = r.model_copy(deep=True)  # order delivered twice
    bad.routes[0].stops.append(bad.routes[0].stops[0].model_copy(update={"seq": len(bad.routes[0].stops) + 1}))
    assert "R1" in rules(bad)
