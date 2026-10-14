"""Each warehouse rule must catch a deliberately injected violation."""

from __future__ import annotations

import pytest

from app.optimization.common.contracts import FrozenAssignment, ScheduleResult, SolveConfig
from app.optimization.common.runner import run_algorithm
from app.optimization.common.validator import validate_schedule
from tests.fixtures import tiny_snapshot


@pytest.fixture
def base():
    snap = tiny_snapshot()
    res = run_algorithm(snap, "warehouse_edd", SolveConfig(problem_type="warehouse"))
    assert res.validation.is_feasible, res.validation.violations
    return snap, res


def _rules(snap, res: ScheduleResult) -> set[str]:
    return {v.rule for v in validate_schedule(snap, res).violations if v.severity == "error"}


def _copy(res: ScheduleResult) -> ScheduleResult:
    return res.model_copy(deep=True)


def test_baseline_feasible(base):
    snap, res = base
    rep = validate_schedule(snap, res)
    assert rep.is_feasible
    assert {"U1", "W1", "W2", "W3", "W4", "W5", "W6", "W7", "W8", "W9", "W10"} <= set(rep.checked_rules)


def test_missing_task_detected(base):
    snap, res = base
    r = _copy(res)
    r.assignments = [a for a in r.assignments if a.task_id != "O1-PACK"]
    assert "W1" in _rules(snap, r)


def test_duplicate_task_detected(base):
    snap, res = base
    r = _copy(res)
    r.assignments.append(r.assignments[0].model_copy())
    assert "W1" in _rules(snap, r)


def test_preemption_or_wrong_duration_detected(base):
    snap, res = base
    r = _copy(res)
    r.assignments[0].end_min += 1
    assert "W2" in _rules(snap, r)


def test_release_violation_detected(base):
    snap, res = base
    r = _copy(res)
    a = next(a for a in r.assignments if a.task_id == "O3-PICK")
    d = a.end_min - a.start_min
    a.start_min, a.end_min = 0, d  # O3 released at 40
    assert "W3" in _rules(snap, r)


def test_precedence_violation_detected(base):
    snap, res = base
    r = _copy(res)
    pick = next(a for a in r.assignments if a.task_id == "O1-PICK")
    pack = next(a for a in r.assignments if a.task_id == "O1-PACK")
    d = pack.end_min - pack.start_min
    pack.start_min, pack.end_min = pick.start_min, pick.start_min + d
    assert "W4" in _rules(snap, r)


def test_ineligible_resource_detected(base):
    snap, res = base
    r = _copy(res)
    pack = next(a for a in r.assignments if a.task_id == "O1-PACK")
    pack.resources["worker"] = "W2"  # W2 cannot pack
    pack.resource_id = "W2"
    assert "W5" in _rules(snap, r)


def test_overlap_detected(base):
    snap, res = base
    r = _copy(res)
    a1 = next(a for a in r.assignments if a.task_id == "O1-PACK")
    a2 = next(a for a in r.assignments if a.task_id == "O3-PACK")
    d = a2.end_min - a2.start_min
    a2.start_min, a2.end_min = a1.start_min, a1.start_min + d
    assert "W7" in _rules(snap, r)


def test_outside_shift_detected(base):
    snap, res = base
    r = _copy(res)
    a = next(a for a in r.assignments if a.task_id == "O3-PICK")
    d = a.end_min - a.start_min
    a.start_min, a.end_min = 900, 900 + d  # W1/W2 shifts end at 540
    assert "W6" in _rules(snap, r)


def test_inventory_negative_detected():
    snap = tiny_snapshot(inventory={"S1": 5})
    res = run_algorithm(snap, "warehouse_edd", SolveConfig(problem_type="warehouse"))
    assert res.validation.is_feasible  # solver backorders explicitly
    assert any(u.reason == "insufficient_inventory" for u in res.unserved)
    r = _copy(res)
    r.unserved_order_ids, r.unserved = [], []
    rules = _rules(snap, r)
    assert "W9" in rules or "W1" in rules


def test_silent_unserved_detected(base):
    snap, res = base
    r = _copy(res)
    r.assignments = [a for a in r.assignments if a.order_ids != ["O2"]]
    assert "W1" in _rules(snap, r)  # dropped without being declared unserved


def test_unserved_without_reason_detected(base):
    snap, res = base
    r = _copy(res)
    r.assignments = [a for a in r.assignments if a.order_ids != ["O2"]]
    r.unserved_order_ids = ["O2"]
    r.unserved = []
    rep = validate_schedule(snap, r)
    assert any(v.rule == "U1" and v.severity == "error" for v in rep.violations)


def test_frozen_change_detected(base):
    snap, res = base
    a = next(a for a in res.assignments if a.task_id == "O1-PICK")
    snap2 = snap.model_copy(
        update={
            "frozen_assignments": [
                FrozenAssignment(
                    task_id=a.task_id,
                    resources=a.resources,
                    start_min=a.start_min,
                    end_min=a.end_min,
                    reason="completed",
                )
            ]
        }
    )
    r = _copy(res)
    x = next(x for x in r.assignments if x.task_id == "O1-PICK")
    x.start_min += 1
    x.end_min += 1
    assert "W10" in _rules(snap2, r)


def test_horizon_violation_detected(base):
    snap, res = base
    r = _copy(res)
    a = r.assignments[-1]
    d = a.end_min - a.start_min
    a.start_min, a.end_min = snap.horizon_min - 1, snap.horizon_min - 1 + d
    assert "W8" in _rules(snap, r)
