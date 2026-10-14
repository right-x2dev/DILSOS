from __future__ import annotations

import pytest

from app.optimization.common.contracts import ScenarioSnapshot, ScheduleResult, SolveConfig
from app.optimization.common.runner import is_publishable, run_algorithm
from app.seed.generator import DEMO_SCENARIOS, generate
from app.services.snapshot_builder import build_snapshot
from tests.fixtures import tiny_snapshot

INTEG = ["integrated_sequential", "integrated_iterative"]


def assert_chain_consistent(snap: ScenarioSnapshot, r: ScheduleResult) -> None:
    """pick → pack → load → depart → deliver for every served order (independent re-check)."""
    T = snap.travel.duration_min
    li = snap.loc_index()
    cm = snap.customer_map()
    om = snap.order_map()
    by = {(a.task_type, a.order_ids[0] if a.task_type != "LOAD" else a.task_id): a for a in r.assignments}
    route_of = {o: rt for rt in r.routes for o in rt.order_ids}
    served = [o.id for o in snap.orders if o.id not in r.unserved_order_ids]
    assert served, "expected some served orders"
    for oid in served:
        pick, pack = by[("PICK", oid)], by[("PACK", oid)]
        rt = route_of[oid]
        load = by[("LOAD", f"LOAD-{rt.vehicle_id}")]
        stop = next(s for s in rt.stops if oid in s.order_ids)
        assert pick.start_min >= om[oid].release_min
        assert pick.end_min <= pack.start_min
        assert pack.end_min <= load.start_min == rt.load_start_min
        assert load.end_min == rt.load_end_min <= rt.departure_min
        assert (
            stop.arrival_min
            >= rt.departure_min + T[li[snap.depot_location_id]][li[cm[om[oid].customer_id].location_id]] - 0
        )
        assert stop.service_start_min >= stop.arrival_min


@pytest.mark.parametrize("alg", INTEG)
def test_tiny_integrated_consistent(alg):
    snap = tiny_snapshot()
    r = run_algorithm(snap, alg, SolveConfig(problem_type="integrated", time_limit_s=6, seed=1))
    assert r.validation.is_feasible, [v.message for v in r.validation.errors]
    assert is_publishable(r)
    assert_chain_consistent(snap, r)


@pytest.mark.parametrize("name", ["normal_day", "warehouse_bottleneck"])
def test_demo_integrated_consistent_and_iterative_never_worse_than_its_start(name):
    snap = build_snapshot(generate(DEMO_SCENARIOS[name]))
    it = run_algorithm(snap, "integrated_iterative", SolveConfig(problem_type="integrated", time_limit_s=20, seed=1))
    assert it.validation.is_feasible
    assert_chain_consistent(snap, it)
    hist = it.solver_metadata["history"]
    assert it.metrics.cost.total_cost <= hist[0]["total_cost"] + 1e-6
    accepted = [h for h in hist[1:] if h["accepted"]]
    assert all(h.get("feasible", True) for h in accepted)
    assert it.solver_metadata["optimality"].startswith("not proven")


def test_iterative_improves_on_bottleneck():
    """Feedback of departure cutoffs measurably helps when the warehouse is the bottleneck (seeded)."""
    snap = build_snapshot(generate(DEMO_SCENARIOS["warehouse_bottleneck"]))
    seq = run_algorithm(
        snap,
        "integrated_sequential",
        SolveConfig(problem_type="integrated", time_limit_s=20, seed=1, params={"dock": "cpsat"}),
    )
    it = run_algorithm(snap, "integrated_iterative", SolveConfig(problem_type="integrated", time_limit_s=20, seed=1))
    assert seq.validation.is_feasible and it.validation.is_feasible
    assert it.metrics.cost.total_cost <= seq.metrics.cost.total_cost


@pytest.mark.slow
def test_integrated_with_exact_subsolvers():
    snap = build_snapshot(generate(DEMO_SCENARIOS["normal_day"]))
    r = run_algorithm(
        snap,
        "integrated_iterative",
        SolveConfig(
            problem_type="integrated",
            time_limit_s=30,
            seed=2,
            params={"warehouse": "cpsat", "routing": "ortools", "dock": "cpsat", "max_iterations": 2},
        ),
    )
    assert r.validation.is_feasible
    assert_chain_consistent(snap, r)


def test_integrated_no_vehicles_everything_explicitly_unserved():
    from tests.fixtures import tiny_definition

    d = tiny_definition()
    for v in d.vehicles:
        v.status = "BROKEN"
    snap = build_snapshot(d)
    for alg in INTEG:
        r = run_algorithm(snap, alg, SolveConfig(problem_type="integrated", time_limit_s=3))
        assert r.validation.is_feasible
        assert sorted(r.unserved_order_ids) == ["O1", "O2", "O3"]
        assert [a for a in r.assignments if not a.frozen] == []  # no silent capacity consumption
