from __future__ import annotations

import pytest

from app.optimization.common.contracts import CancellationToken, SolveConfig
from app.optimization.common.objectives import evaluate
from app.optimization.common.runner import AlgorithmNotSupported, is_publishable, run_algorithm
from app.schemas.scenario_def import WorkerDef
from app.seed.generator import DEMO_SCENARIOS, generate
from app.services.snapshot_builder import build_snapshot
from tests.fixtures import tiny_definition, tiny_snapshot

WH = ["warehouse_fifo", "warehouse_edd", "warehouse_spt", "warehouse_cpsat"]


@pytest.mark.parametrize("alg", WH)
def test_tiny_all_feasible(alg):
    snap = tiny_snapshot()
    r = run_algorithm(snap, alg, SolveConfig(problem_type="warehouse", time_limit_s=5, seed=1))
    assert r.validation.is_feasible, [v.message for v in r.validation.errors]
    assert is_publishable(r)
    assert r.unserved_order_ids == []
    assert len(r.assignments) == 6


def test_cpsat_certifies_optimality_on_tiny_and_beats_or_ties_heuristics():
    snap = tiny_snapshot()
    cp = run_algorithm(snap, "warehouse_cpsat", SolveConfig(problem_type="warehouse", time_limit_s=20, seed=1))
    assert cp.status == "OPTIMAL"
    assert cp.solver_metadata["gap"] == pytest.approx(0, abs=1e-9)

    def solver_obj(r) -> float:  # the CP-SAT objective re-evaluated in KRW (incl. 1 KRW/min completion term)
        c = r.metrics.cost
        completion = {}
        for a in r.assignments:
            completion[a.order_ids[0]] = max(completion.get(a.order_ids[0], 0), a.end_min)
        return c.labor_cost + c.overtime_cost + c.late_delivery_penalty + sum(completion.values())

    tol = len(snap.tasks)  # per-task rounding of labor coefficients in the integer model
    for h in ("warehouse_fifo", "warehouse_edd", "warehouse_spt"):
        hr = run_algorithm(snap, h, SolveConfig(problem_type="warehouse"))
        assert hr.status == "FEASIBLE"  # heuristics never claim optimality
        assert solver_obj(cp) <= solver_obj(hr) + tol


@pytest.mark.parametrize("alg", WH)
def test_no_eligible_packer_is_explicitly_unserved(alg):
    d = tiny_definition()
    d.workers = [WorkerDef(code="W2", name="w2", skills=["pick"], shift_start_local=360, shift_end_local=900)]
    snap = build_snapshot(d)
    r = run_algorithm(snap, alg, SolveConfig(problem_type="warehouse", time_limit_s=3))
    assert r.validation.is_feasible
    assert sorted(r.unserved_order_ids) == ["O1", "O2", "O3"]
    assert {u.reason for u in r.unserved} == {"no_eligible_resource"}
    assert r.metrics.cost.unserved_penalty > 0
    assert r.assignments == []


@pytest.mark.parametrize("alg", WH)
def test_capacity_shortage_in_horizon_unserved_not_dropped(alg):
    d = tiny_definition()
    for w in d.workers:  # only 10 minutes of work time
        w.shift_start_local, w.shift_end_local, w.regular_end_local = 360, 370, None
    snap = build_snapshot(d)
    r = run_algorithm(snap, alg, SolveConfig(problem_type="warehouse", time_limit_s=3))
    assert r.validation.is_feasible, [v.message for v in r.validation.errors]
    served = {a.order_ids[0] for a in r.assignments}
    assert served | set(r.unserved_order_ids) == {"O1", "O2", "O3"}
    assert len(r.unserved_order_ids) >= 2


@pytest.mark.parametrize("alg", WH)
def test_single_order(alg):
    d = tiny_definition()
    d.orders = d.orders[:1]
    r = run_algorithm(build_snapshot(d), alg, SolveConfig(problem_type="warehouse", time_limit_s=3))
    assert r.validation.is_feasible and len(r.assignments) == 2


def test_dispatch_rules_are_deterministic():
    snap = build_snapshot(generate(DEMO_SCENARIOS["normal_day"]))
    for alg in ("warehouse_fifo", "warehouse_edd", "warehouse_spt"):
        a = run_algorithm(snap, alg, SolveConfig(problem_type="warehouse"))
        b = run_algorithm(snap, alg, SolveConfig(problem_type="warehouse"))
        assert [x.model_dump() for x in a.assignments] == [x.model_dump() for x in b.assignments]


def test_edd_reduces_lateness_vs_spt_on_bottleneck():
    snap = build_snapshot(generate(DEMO_SCENARIOS["warehouse_bottleneck"]))
    edd = run_algorithm(snap, "warehouse_edd", SolveConfig(problem_type="warehouse"))
    spt = run_algorithm(snap, "warehouse_spt", SolveConfig(problem_type="warehouse"))
    assert edd.validation.is_feasible and spt.validation.is_feasible
    assert edd.metrics.total_lateness_min <= spt.metrics.total_lateness_min


@pytest.mark.slow
def test_cpsat_time_limit_has_incumbent_on_medium():
    snap = build_snapshot(generate(DEMO_SCENARIOS["peak_demand"]))
    r = run_algorithm(snap, "warehouse_cpsat", SolveConfig(problem_type="warehouse", time_limit_s=3, seed=0))
    assert r.status in ("TIME_LIMIT", "OPTIMAL", "FEASIBLE")
    assert r.validation.is_feasible and is_publishable(r)


def test_cpsat_cancellation_stops_early():
    snap = build_snapshot(generate(DEMO_SCENARIOS["warehouse_bottleneck"]))
    tok = CancellationToken()
    tok.cancel()
    r = run_algorithm(snap, "warehouse_cpsat", SolveConfig(problem_type="warehouse", time_limit_s=30), cancel=tok)
    assert r.runtime_ms < 25_000
    assert r.solver_metadata["cancelled"] is True


def test_unsupported_problem_type_rejected():
    with pytest.raises(AlgorithmNotSupported):
        run_algorithm(tiny_snapshot(), "warehouse_edd", SolveConfig(problem_type="routing"))


def test_objective_terms_are_recomputable():
    snap = tiny_snapshot()
    r = run_algorithm(snap, "warehouse_edd", SolveConfig(problem_type="warehouse"))
    c = r.metrics.cost
    rm = snap.resource_map()
    labor = sum(
        (a.end_min - a.start_min) * rm[rid].hourly_cost / 60
        for a in r.assignments
        for rid in a.resources.values()
        if rm[rid].kind == "worker"
    )
    assert c.labor_cost == pytest.approx(round(labor, 2))
    assert c.total_cost == pytest.approx(
        c.transport_fixed
        + c.distance_cost
        + c.labor_cost
        + c.overtime_cost
        + c.late_delivery_penalty
        + c.unserved_penalty
        + c.schedule_change_penalty,
        abs=0.05,
    )
    assert evaluate(snap, r).cost.total_cost == c.total_cost
