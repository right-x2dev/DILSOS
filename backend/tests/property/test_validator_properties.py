"""Property-based: randomly corrupted schedules must never pass the validator."""

from __future__ import annotations

from functools import lru_cache

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.optimization.common.contracts import ScheduleResult, SolveConfig
from app.optimization.common.runner import run_algorithm
from app.optimization.common.validator import validate_schedule
from app.seed.generator import GeneratorConfig, generate
from app.services.snapshot_builder import build_snapshot


@lru_cache
def _base(seed: int):  # type: ignore[no-untyped-def]
    snap = build_snapshot(generate(GeneratorConfig(seed=seed, n_orders=12, n_workers=3, n_pack_stations=1)))
    res = run_algorithm(snap, "warehouse_edd", SolveConfig(problem_type="warehouse"))
    assert res.validation.is_feasible
    return snap, res


def _errors(snap, r: ScheduleResult) -> int:
    return sum(1 for v in validate_schedule(snap, r).violations if v.severity == "error")


SEEDS = st.integers(min_value=1, max_value=4)
CFG = settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.too_slow])


@CFG
@given(seed=SEEDS, data=st.data())
def test_dropping_a_task_is_caught(seed, data):
    snap, res = _base(seed)
    r = res.model_copy(deep=True)
    i = data.draw(st.integers(0, len(r.assignments) - 1))
    del r.assignments[i]
    assert _errors(snap, r) > 0


@CFG
@given(seed=SEEDS, data=st.data())
def test_duplicating_a_task_is_caught(seed, data):
    snap, res = _base(seed)
    r = res.model_copy(deep=True)
    i = data.draw(st.integers(0, len(r.assignments) - 1))
    r.assignments.append(r.assignments[i].model_copy(deep=True))
    assert _errors(snap, r) > 0


@CFG
@given(seed=SEEDS, data=st.data())
def test_forcing_an_overlap_is_caught(seed, data):
    snap, res = _base(seed)
    r = res.model_copy(deep=True)
    by_res: dict[str, list[int]] = {}
    for i, a in enumerate(r.assignments):
        by_res.setdefault(a.resource_id, []).append(i)
    lanes = [v for v in by_res.values() if len(v) >= 2]
    lane = data.draw(st.sampled_from(lanes))
    i, j = data.draw(st.sampled_from([(a, b) for a in lane for b in lane if a != b]))
    d = r.assignments[j].end_min - r.assignments[j].start_min
    off = data.draw(st.integers(0, max(0, r.assignments[i].end_min - r.assignments[i].start_min - 1)))
    r.assignments[j].start_min = r.assignments[i].start_min + off
    r.assignments[j].end_min = r.assignments[j].start_min + d
    assert _errors(snap, r) > 0


@CFG
@given(seed=SEEDS, data=st.data())
def test_pack_before_pick_is_caught(seed, data):
    snap, res = _base(seed)
    r = res.model_copy(deep=True)
    packs = [a for a in r.assignments if a.task_type == "PACK"]
    pk = data.draw(st.sampled_from(packs))
    pick = next(a for a in r.assignments if a.task_id == pk.task_id.replace("PACK", "PICK"))
    d = pk.end_min - pk.start_min
    pk.start_min = pick.end_min - data.draw(st.integers(1, pick.end_min - pick.start_min))
    pk.end_min = pk.start_min + d
    assert _errors(snap, r) > 0


@CFG
@given(seed=SEEDS, extra=st.integers(min_value=1, max_value=50))
def test_negative_inventory_is_caught(seed, extra):
    snap, res = _base(seed)
    sku = snap.orders[0].lines[0].sku_id
    use = sum(ln.qty for o in snap.orders if o.id not in res.unserved_order_ids for ln in o.lines if ln.sku_id == sku)
    tight = snap.model_copy(update={"inventory": {**snap.inventory, sku: max(0, use - extra)}})
    assert _errors(tight, res) > 0


@CFG
@given(seed=SEEDS, data=st.data(), shift=st.integers(min_value=1, max_value=30))
def test_shifting_any_task_never_silently_breaks_constraints(seed, data, shift):
    """Shift one task later: either still feasible (re-verified by brute force) or flagged."""
    snap, res = _base(seed)
    r = res.model_copy(deep=True)
    i = data.draw(st.integers(0, len(r.assignments) - 1))
    r.assignments[i].start_min += shift
    r.assignments[i].end_min += shift
    rep = validate_schedule(snap, r)
    # brute-force overlap/precedence/window check independent of the validator
    tm = snap.task_map()
    rm = snap.resource_map()
    ok = True
    for a in r.assignments:
        for b in r.assignments:
            shared = a is not b and set(a.resources.values()) & set(b.resources.values())
            if shared and a.start_min < b.end_min and b.start_min < a.end_min:
                ok = False
        t = tm[a.task_id]
        for p in t.predecessors:
            pa = next(x for x in r.assignments if x.task_id == p)
            if a.start_min < pa.end_min:
                ok = False
        for rid in a.resources.values():
            if not any(w.start <= a.start_min and a.end_min <= w.end for w in rm[rid].available):
                ok = False
        if a.end_min > snap.horizon_min:
            ok = False
    assert rep.is_feasible == ok
