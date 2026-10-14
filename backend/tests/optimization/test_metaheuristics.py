from __future__ import annotations

import pytest

from app.optimization.common.contracts import SolveConfig
from app.optimization.common.runner import run_algorithm
from app.seed.generator import DEMO_SCENARIOS, GeneratorConfig, generate
from app.services.snapshot_builder import build_snapshot

META = ["warehouse_sa", "warehouse_tabu", "warehouse_ga"]


def _tight():
    # few workers, tight cutoffs → room for improvement over dispatch rules
    return build_snapshot(
        generate(GeneratorConfig(seed=77, n_orders=25, n_workers=2, n_pack_stations=1, deadline_tightness=2.5))
    )


@pytest.mark.parametrize("alg", META)
def test_metaheuristic_feasible_and_never_worse_than_edd_seed(alg):
    snap = _tight()
    edd = run_algorithm(snap, "warehouse_edd", SolveConfig(problem_type="warehouse"))
    r = run_algorithm(
        snap, alg, SolveConfig(problem_type="warehouse", time_limit_s=30, seed=3, params={"max_evaluations": 300})
    )
    assert r.validation.is_feasible
    assert r.solver_metadata["rejected_invalid_incumbents"] == 0
    assert r.solver_metadata["evaluations"] <= 300
    # EDD permutation is part of the initial population/start → best can only match or improve it
    assert r.metrics.cost.total_cost <= edd.metrics.cost.total_cost + 1e-6
    assert r.status == "FEASIBLE"


@pytest.mark.parametrize("alg", META)
def test_metaheuristic_reproducible_with_seed_and_eval_budget(alg):
    snap = _tight()
    cfg = SolveConfig(problem_type="warehouse", time_limit_s=60, seed=11, params={"max_evaluations": 150})
    a = run_algorithm(snap, alg, cfg)
    b = run_algorithm(snap, alg, cfg)
    assert [x.model_dump() for x in a.assignments] == [x.model_dump() for x in b.assignments]
    assert a.solver_metadata["stopped_by"] == "evaluations"


def test_metaheuristic_finds_improvement_on_tight_instance():
    snap = _tight()
    edd = run_algorithm(snap, "warehouse_edd", SolveConfig(problem_type="warehouse"))
    best = min(
        run_algorithm(
            snap, alg, SolveConfig(problem_type="warehouse", time_limit_s=30, seed=1, params={"max_evaluations": 400})
        ).metrics.cost.total_cost
        for alg in META
    )
    assert best < edd.metrics.cost.total_cost  # measured improvement, seeded


def test_alns_reproducible_and_not_worse_than_insertion():
    snap = build_snapshot(generate(DEMO_SCENARIOS["normal_day"]))
    ins = run_algorithm(snap, "routing_insertion", SolveConfig(problem_type="routing"))
    cfg = SolveConfig(problem_type="routing", time_limit_s=60, seed=5, params={"max_iterations": 60})
    a = run_algorithm(snap, "routing_alns", cfg)
    b = run_algorithm(snap, "routing_alns", cfg)
    assert a.validation.is_feasible
    assert a.metrics.cost.total_cost <= ins.metrics.cost.total_cost + 1e-6
    assert [r.model_dump() for r in a.routes] == [r.model_dump() for r in b.routes]
    assert a.solver_metadata["alns_iterations"] == 60


def test_alns_in_integrated_pipeline():
    snap = build_snapshot(generate(DEMO_SCENARIOS["warehouse_bottleneck"]))
    r = run_algorithm(
        snap,
        "integrated_sequential",
        SolveConfig(problem_type="integrated", time_limit_s=6, seed=2, params={"routing": "alns"}),
    )
    assert r.validation.is_feasible
    assert r.solver_metadata["routing"] == "alns"
