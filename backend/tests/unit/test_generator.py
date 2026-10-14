from __future__ import annotations

import pytest

from app.optimization.common.contracts import SolveConfig
from app.optimization.common.runner import run_algorithm
from app.seed.generator import DEMO_SCENARIOS, GeneratorConfig, generate
from app.services.input_validation import validate_inputs
from app.services.snapshot_builder import build_snapshot


@pytest.mark.parametrize("name", list(DEMO_SCENARIOS))
def test_reproducible_same_seed(name):
    a = generate(DEMO_SCENARIOS[name]).model_dump_json()
    b = generate(DEMO_SCENARIOS[name]).model_dump_json()
    assert a == b


def test_different_seed_differs():
    a = generate(GeneratorConfig(seed=1)).model_dump_json()
    b = generate(GeneratorConfig(seed=2)).model_dump_json()
    assert a != b


@pytest.mark.parametrize("name", list(DEMO_SCENARIOS))
def test_valid_references_and_nonnegative_durations(name):
    d = generate(DEMO_SCENARIOS[name])  # model validator checks customer/sku references
    snap = build_snapshot(d)
    om = snap.order_map()
    assert all(t.duration_min > 0 for t in snap.tasks)
    assert all(t.order_id in om for t in snap.tasks)
    assert all(c.tw_end >= c.tw_start for c in snap.customers)
    li = snap.loc_index()
    assert all(c.location_id in li for c in snap.customers)
    assert validate_inputs(snap).ok


def test_known_feasible_tiny_generated():
    snap = build_snapshot(generate(GeneratorConfig(seed=5, n_orders=5, n_workers=3, n_pack_stations=1)))
    r = run_algorithm(snap, "warehouse_edd", SolveConfig(problem_type="warehouse"))
    assert r.validation.is_feasible and not r.unserved_order_ids


def test_known_infeasible_inputs_flagged():
    d = generate(GeneratorConfig(seed=5, n_orders=5, n_workers=1, n_pack_stations=1))
    d.workers[0].skills = ["pick"]  # nobody can pack
    snap = build_snapshot(d)
    rep = validate_inputs(snap)
    assert any(i.code == "no_eligible_resource" for i in rep.issues)
    r = run_algorithm(snap, "warehouse_cpsat", SolveConfig(problem_type="warehouse", time_limit_s=2))
    assert r.validation.is_feasible  # explicit unserved, never fake success
    assert len(r.unserved_order_ids) == 5


def test_inventory_shortage_creates_backorders():
    snap = build_snapshot(generate(DEMO_SCENARIOS["peak_demand"]))
    r = run_algorithm(snap, "warehouse_edd", SolveConfig(problem_type="warehouse"))
    assert any(u.reason == "insufficient_inventory" for u in r.unserved)
    assert r.validation.is_feasible
