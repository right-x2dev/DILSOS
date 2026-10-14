from __future__ import annotations

import pytest

from app.optimization.common.contracts import SolveConfig
from app.optimization.common.routes import Ctx
from app.optimization.common.runner import run_algorithm
from app.optimization.routing.units import Simulator, build_units
from app.schemas.scenario_def import CustomerDef, OrderDef, OrderLineDef, VehicleDef
from app.seed.generator import DEMO_SCENARIOS, generate
from app.services.snapshot_builder import build_snapshot
from tests.fixtures import tiny_definition, tiny_snapshot

R = ["routing_nn", "routing_insertion", "routing_ortools"]
CFG = SolveConfig(problem_type="routing", time_limit_s=3, seed=1)


@pytest.mark.parametrize("alg", R)
def test_tiny_routes_feasible_and_complete(alg):
    snap = tiny_snapshot()
    r = run_algorithm(snap, alg, CFG)
    assert r.validation.is_feasible, [v.message for v in r.validation.errors]
    delivered = sorted(o for rt in r.routes for s in rt.stops for o in s.order_ids)
    assert delivered == ["O1", "O2", "O3"]
    for rt in r.routes:
        assert rt.stops and rt.distance_m > 0 and rt.geometry == "schematic_straight_line"
        assert rt.return_min <= snap.vehicle_map()[rt.vehicle_id].shift_end


@pytest.mark.parametrize("alg", R)
def test_capacity_is_respected(alg):
    d = tiny_definition()
    d.vehicles = [
        VehicleDef(code=f"V{i}", capacity_kg=13, capacity_l=100, shift_start_local=420, shift_end_local=1320)
        for i in range(3)
    ]
    snap = build_snapshot(d)  # O1=8kg O2=4kg O3=12kg → cannot share beyond 13 kg
    r = run_algorithm(snap, alg, CFG)
    assert r.validation.is_feasible
    assert all(rt.load_kg <= 13 for rt in r.routes)
    assert sum(len(rt.order_ids) for rt in r.routes) == 3


@pytest.mark.parametrize("alg", R)
def test_zero_vehicles_all_unserved(alg):
    d = tiny_definition()
    for v in d.vehicles:
        v.status = "BROKEN"
    r = run_algorithm(build_snapshot(d), alg, CFG)
    assert r.validation.is_feasible
    assert sorted(r.unserved_order_ids) == ["O1", "O2", "O3"]
    assert {u.reason for u in r.unserved} == {"no_vehicle_available"}


@pytest.mark.parametrize("alg", R)
def test_hard_windows_never_violated(alg):
    snap = build_snapshot(
        generate(DEMO_SCENARIOS["normal_day"]).model_copy(
            update={
                "params": generate(DEMO_SCENARIOS["normal_day"]).params.model_copy(update={"time_window_mode": "hard"})
            }
        )
    )
    r = run_algorithm(snap, alg, CFG)
    assert r.validation.is_feasible, [v.message for v in r.validation.errors]
    assert all(s.late_min == 0 for rt in r.routes for s in rt.stops)


@pytest.mark.parametrize("alg", R)
def test_identical_time_windows_and_single_order(alg):
    d = tiny_definition()
    for c in d.customers:
        c.tw_start_local, c.tw_end_local = 600, 660
    r = run_algorithm(build_snapshot(d), alg, CFG)
    assert r.validation.is_feasible
    d2 = tiny_definition()
    d2.orders = d2.orders[:1]
    r2 = run_algorithm(build_snapshot(d2), alg, CFG)
    assert r2.validation.is_feasible and len(r2.routes) == 1 and r2.routes[0].order_ids == ["O1"]


def test_same_customer_orders_share_one_stop():
    d = tiny_definition()
    d.orders.append(
        OrderDef(
            code="O4", customer_code="C1", release_local=360, due_local=500, lines=[OrderLineDef(sku_code="S1", qty=1)]
        )
    )
    snap = build_snapshot(d)
    units = build_units(Ctx(snap), [o.id for o in snap.orders], {o.id: 0 for o in snap.orders})
    assert any(u.order_ids == ("O1", "O4") for u in units)
    r = run_algorithm(snap, "routing_insertion", CFG)
    stop = next(s for rt in r.routes for s in rt.stops if s.customer_id == "C1")
    assert sorted(stop.order_ids) == ["O1", "O4"]
    assert r.validation.is_feasible


def test_simulator_matches_shared_timing():
    snap = build_snapshot(generate(DEMO_SCENARIOS["normal_day"]))
    r = run_algorithm(snap, "routing_insertion", CFG)
    ctx = Ctx(snap)
    sim = Simulator(ctx)
    units = {
        u.order_ids: u
        for u in build_units(ctx, [o.id for o in snap.orders], {o.id: o.release_min for o in snap.orders})
    }
    for rt in r.routes:
        seq = [units[tuple(sorted(s.order_ids))] for s in rt.stops]
        s = sim.run(rt.vehicle_id, seq)
        assert (s.ret, s.dist_m, s.late_min) == (rt.return_min, rt.distance_m, sum(x.late_min for x in rt.stops))


def test_ortools_not_worse_than_insertion_warm_start():
    snap = build_snapshot(generate(DEMO_SCENARIOS["normal_day"]))
    ins = run_algorithm(snap, "routing_insertion", CFG)
    ort = run_algorithm(snap, "routing_ortools", SolveConfig(problem_type="routing", time_limit_s=5, seed=1))
    assert ort.validation.is_feasible
    assert ort.metrics.cost.total_cost <= ins.metrics.cost.total_cost * 1.001
    assert ort.status == "FEASIBLE"  # routing local search never claims optimality
    assert ort.solver_metadata["optimality"].startswith("not proven")


def test_far_customer_beyond_shift_is_unserved_not_dropped_silently():
    d = tiny_definition()
    d.customers.append(
        CustomerDef(code="CFAR", name="far", x_km=400, y_km=0, service_min=5, tw_start_local=480, tw_end_local=1300)
    )
    d.orders.append(
        OrderDef(
            code="OFAR",
            customer_code="CFAR",
            release_local=360,
            due_local=600,
            lines=[OrderLineDef(sku_code="S1", qty=1)],
        )
    )
    snap = build_snapshot(d)
    for alg in R:
        r = run_algorithm(snap, alg, CFG)
        assert r.validation.is_feasible
        assert "OFAR" in r.unserved_order_ids
        assert sorted(o for rt in r.routes for o in rt.order_ids) == ["O1", "O2", "O3"]
