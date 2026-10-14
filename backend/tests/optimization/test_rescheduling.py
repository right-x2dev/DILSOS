from __future__ import annotations

from functools import lru_cache

import pytest

from app.optimization.common.contracts import SolveConfig
from app.optimization.common.runner import run_algorithm
from app.optimization.common.validator import validate_schedule
from app.optimization.rescheduling.events import DisruptionSpec, apply_event
from app.optimization.rescheduling.policies import build_policy_snapshot, recommend
from app.optimization.rescheduling.rolling_horizon import reschedule, rolling_horizon
from app.seed.generator import DEMO_SCENARIOS, generate
from app.services.snapshot_builder import build_snapshot

POLICIES = ["KEEP", "PARTIAL", "FULL"]


@lru_cache
def _base():
    snap = build_snapshot(generate(DEMO_SCENARIOS["vehicle_breakdown"]))
    base = run_algorithm(snap, "integrated_sequential", SolveConfig(problem_type="integrated", time_limit_s=10, seed=1))
    assert base.validation.is_feasible
    return snap, base


def _events(snap, base):
    busiest = max(
        {a.resource_id for a in base.assignments if a.task_type == "PICK"},
        key=lambda w: (sum(1 for a in base.assignments if a.resource_id == w), w),
    )
    vid = sorted(r.vehicle_id for r in base.routes)[1]
    return [
        DisruptionSpec(event_type="vehicle_breakdown", time_min=150, affected_id=vid),
        DisruptionSpec(event_type="worker_absence", time_min=120, affected_id=busiest, payload={"duration_min": 180}),
        DisruptionSpec(
            event_type="urgent_order",
            time_min=200,
            payload={
                "order_id": "URG1",
                "customer_id": snap.customers[0].id,
                "lines": [[snap.skus[0].id, 2]],
                "due_offset_min": 150,
                "priority": 3,
            },
        ),
        DisruptionSpec(event_type="travel_time_increase", time_min=240, payload={"factor": 1.4}),
        DisruptionSpec(event_type="order_cancellation", time_min=100, affected_id=snap.orders[-1].id),
        DisruptionSpec(event_type="dock_outage", time_min=200, affected_id="D1", payload={"duration_min": 120}),
        DisruptionSpec(event_type="pack_station_outage", time_min=60, affected_id="PS1", payload={"duration_min": 90}),
    ]


EVENT_NAMES = [
    "vehicle_breakdown",
    "worker_absence",
    "urgent_order",
    "travel_time_increase",
    "order_cancellation",
    "dock_outage",
    "pack_station_outage",
]


@pytest.mark.parametrize("policy", POLICIES)
@pytest.mark.parametrize("idx", range(7), ids=EVENT_NAMES)
def test_event_policy_preserves_history_and_validates(idx, policy):
    snap, base = _base()
    ev = _events(snap, base)[idx]
    res, plan, new_snap = reschedule(snap, base, ev, policy, time_limit_s=4, seed=1)
    assert res.validation.is_feasible, [v.message for v in res.validation.errors]
    now = ev.time_min
    new_by_id = {a.task_id: a for a in res.assignments}
    # 1) executed history unchanged
    for a in base.assignments:
        if a.task_type != "LOAD" and a.start_min < now:
            b = new_by_id.get(a.task_id)
            assert b is not None and (b.start_min, b.end_min, b.resources) == (a.start_min, a.end_min, a.resources)
    started = {
        r.vehicle_id: r
        for r in base.routes
        if (r.load_start_min if r.load_start_min is not None else r.departure_min) < now
    }
    for vid, r in started.items():
        assert next(x for x in res.routes if x.vehicle_id == vid).model_dump() == r.model_dump()
    # 2) nothing re-planned into the past
    for a in res.assignments:
        if not a.frozen and a.task_type != "LOAD":
            assert a.start_min >= now
    for r in res.routes:
        if r.vehicle_id not in {fr.vehicle_id for fr in new_snap.frozen_routes}:
            assert r.departure_min >= now and (r.load_start_min is None or r.load_start_min >= now)
    # 3) stability metrics measured against the baseline
    assert res.metrics.changed_tasks is not None and res.metrics.stability_score is not None
    assert res.status == "FEASIBLE"


def test_keep_changes_least_and_full_is_cheapest_or_equal_for_breakdown():
    snap, base = _base()
    ev = _events(snap, base)[0]
    r = {p: reschedule(snap, base, ev, p, time_limit_s=4, seed=1)[0] for p in POLICIES}
    chg = {p: r[p].metrics.changed_tasks + r[p].metrics.changed_routes for p in POLICIES}
    assert chg["KEEP"] <= chg["PARTIAL"] <= chg["FULL"]
    # PARTIAL/FULL re-optimise and include the KEEP plan as a candidate → never worse than KEEP
    assert r["PARTIAL"].metrics.cost.total_cost <= r["KEEP"].metrics.cost.total_cost + 1e-6
    assert r["FULL"].metrics.cost.total_cost <= r["KEEP"].metrics.cost.total_cost + 1e-6
    # breaking a used vehicle with no spare: KEEP must surface explicit unserved exceptions
    assert r["KEEP"].metrics.orders_unserved > 0
    assert {u.reason for u in r["KEEP"].unserved} <= {
        "no_feasible_route",
        "no_vehicle_capacity",
        "route_exceeds_vehicle_shift",
    }


def test_absence_respects_no_preemption():
    snap, base = _base()
    w = next(a for a in base.assignments if a.task_type == "PICK")
    t = w.start_min + 1  # in progress
    applied = apply_event(
        snap, base, DisruptionSpec(event_type="worker_absence", time_min=t, affected_id=w.resource_id)
    )
    res = applied.snapshot.resource_map()[w.resource_id]
    assert all(i.end <= w.end_min or i.start >= w.end_min for i in res.available)
    assert any(i.end == w.end_min for i in res.available)  # finishes the in-progress task first
    assert applied.exceptions


def test_breakdown_after_departure_is_reported_not_rewritten():
    snap, base = _base()
    r = base.routes[0]
    ev = DisruptionSpec(event_type="vehicle_breakdown", time_min=r.departure_min + 5, affected_id=r.vehicle_id)
    res, plan, _ = reschedule(snap, base, ev, "FULL", time_limit_s=3)
    assert any("after loading/departure" in x for x in plan.exceptions)
    assert next(x for x in res.routes if x.vehicle_id == r.vehicle_id).model_dump() == r.model_dump()
    assert res.validation.is_feasible


def test_invalid_events_rejected():
    snap, base = _base()
    with pytest.raises(ValueError):
        apply_event(snap, base, DisruptionSpec(event_type="worker_absence", time_min=10, affected_id="NOPE"))
    with pytest.raises(ValueError):
        apply_event(
            snap,
            base,
            DisruptionSpec(event_type="urgent_order", time_min=10, payload={"customer_id": "ZZZ", "lines": [["X", 1]]}),
        )
    with pytest.raises(ValueError):
        apply_event(snap, base, DisruptionSpec(event_type="travel_time_increase", time_min=10, payload={"factor": 0.5}))


def test_tampering_with_history_is_detected():
    snap, base = _base()
    ev = _events(snap, base)[3]  # travel time increase at t=240
    res, _, new_snap = reschedule(snap, base, ev, "FULL", time_limit_s=3)
    frozen = next(fr for fr in new_snap.frozen_routes) if new_snap.frozen_routes else None
    bad = res.model_copy(deep=True)
    a = next(x for x in bad.assignments if x.frozen and x.task_type != "LOAD")
    a.start_min += 1
    a.end_min += 1
    rules = {v.rule for v in validate_schedule(new_snap, bad).violations if v.severity == "error"}
    assert "W10" in rules
    if frozen is not None:
        bad2 = res.model_copy(deep=True)
        rt = next(r for r in bad2.routes if r.vehicle_id == frozen.vehicle_id)
        rt.distance_m += 1
        assert "F1" in {v.rule for v in validate_schedule(new_snap, bad2).violations}


def test_rolling_horizon_accumulates_history():
    snap, base = _base()
    evs = [_events(snap, base)[i] for i in (4, 1, 0)]  # t=100, 120, 150
    final, final_snap, steps = rolling_horizon(snap, base, evs, "PARTIAL", time_limit_s=3, seed=1)
    assert [s.event.time_min for s in steps] == [100, 120, 150]
    assert all(s.feasible for s in steps)
    assert final_snap.current_time_min == 150
    assert len(final_snap.events_applied) == 3
    assert snap.orders[-1].id in final.unserved_order_ids  # cancellation persisted across later events


def test_recommendation_is_transparent():
    rec = recommend(
        {
            "KEEP": {
                "feasible": True,
                "total_cost": 200.0,
                "late_min": 10,
                "changed_tasks": 1,
                "changed_routes": 0,
                "runtime_ms": 5,
            },
            "FULL": {
                "feasible": True,
                "total_cost": 100.0,
                "late_min": 0,
                "changed_tasks": 30,
                "changed_routes": 5,
                "runtime_ms": 500,
            },
            "PARTIAL": {
                "feasible": False,
                "total_cost": 1.0,
                "late_min": 0,
                "changed_tasks": 0,
                "changed_routes": 0,
                "runtime_ms": 1,
            },
        }
    )
    assert rec["recommended"] in {"KEEP", "FULL"}
    assert "PARTIAL" not in rec["scores"]  # infeasible results are never recommended
    assert "rule-based" in rec["reason"]


def test_recommendation_not_dominated_by_runtime_scale():
    """Regression: a 3 ms KEEP with 16 unserved orders (4.8× cost) must not beat a 3 s PARTIAL."""
    rec = recommend(
        {
            "KEEP": {
                "feasible": True,
                "total_cost": 6_996_386,
                "late_min": 159,
                "changed_tasks": 1,
                "changed_routes": 1,
                "runtime_ms": 3,
            },
            "PARTIAL": {
                "feasible": True,
                "total_cost": 1_449_576,
                "late_min": 389,
                "changed_tasks": 3,
                "changed_routes": 5,
                "runtime_ms": 3000,
            },
            "FULL": {
                "feasible": True,
                "total_cost": 1_514_949,
                "late_min": 289,
                "changed_tasks": 35,
                "changed_routes": 5,
                "runtime_ms": 3200,
            },
        }
    )
    assert rec["recommended"] == "PARTIAL"
    assert all(0 <= s <= 2.05 for s in rec["scores"].values())


def test_warehouse_only_rescheduling():
    snap, _ = _base()
    base = run_algorithm(snap, "warehouse_edd", SolveConfig(problem_type="warehouse"))
    w = base.assignments[0].resource_id
    for p in POLICIES:
        res, _, _ = reschedule(
            snap, base, DisruptionSpec(event_type="worker_absence", time_min=90, affected_id=w), p, time_limit_s=3
        )
        assert res.validation.is_feasible
        assert res.routes == []


def test_policy_snapshot_is_self_contained():
    snap, base = _base()
    ev = _events(snap, base)[0]
    new_snap, plan = build_policy_snapshot(snap, base, ev, "PARTIAL")
    assert new_snap.reschedule_policy == "PARTIAL"
    assert len(new_snap.keep_frozen_assignments) >= len(new_snap.frozen_assignments)
    assert new_snap.baseline_assignments and new_snap.events_applied[-1]["event_type"] == "vehicle_breakdown"
    # reproducible from the snapshot alone
    a = run_algorithm(new_snap, "reschedule_partial", SolveConfig(problem_type="integrated", time_limit_s=3, seed=2))
    b = run_algorithm(new_snap, "reschedule_partial", SolveConfig(problem_type="integrated", time_limit_s=3, seed=2))
    assert a.metrics.cost.total_cost == b.metrics.cost.total_cost
