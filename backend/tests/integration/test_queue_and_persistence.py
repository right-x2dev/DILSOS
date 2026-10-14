"""DB queue worker, atomic claiming, cancellation, failure paths, definition round-trip."""

from __future__ import annotations

from sqlalchemy import select

from app.db import models as m
from app.optimization.common.contracts import SolveConfig
from app.optimization.common.runner import run_algorithm
from app.seed.cli import ensure_demo_scenarios
from app.seed.generator import GeneratorConfig, generate
from app.services import runs as run_svc
from app.services.scenario_store import current_snapshot, load_definition, persist_definition, snapshot_from_row
from app.services.snapshot_builder import build_snapshot


def _scenario(db, seed: int = 21, code: str = "DC-Q"):
    d = generate(
        GeneratorConfig(
            name=f"q{seed}", seed=seed, facility_code=f"{code}{seed}", n_orders=8, n_workers=3, n_pack_stations=1
        )
    )
    sc = persist_definition(db, d)
    db.commit()
    return sc, d


def test_definition_round_trip_is_lossless(db):
    sc, d = _scenario(db, 31)
    back = load_definition(db, sc)
    s1 = build_snapshot(d, scenario_id="x")
    s2 = build_snapshot(back, scenario_id="x")
    assert s1.model_dump() == s2.model_dump()


def test_db_worker_claims_and_runs(db):
    sc, _ = _scenario(db, 32)
    run = run_svc.enqueue_run(db, sc, "warehouse", "warehouse_fifo", 2, 0, {}, None, dispatch=False)
    assert db.get(m.ScheduleRun, run.id).status == "QUEUED"
    from app.tasks.db_worker import run_forever

    n = run_forever(poll_s=0.01, once=True)
    assert n >= 1
    db.expire_all()
    assert db.get(m.ScheduleRun, run.id).status == "SUCCEEDED"


def test_claim_is_atomic(db):
    sc, _ = _scenario(db, 33)
    run = run_svc.enqueue_run(db, sc, "warehouse", "warehouse_fifo", 2, 0, {}, None, dispatch=False)
    assert run_svc.claim_run(db, run.id, "w1") is True
    assert run_svc.claim_run(db, run.id, "w2") is False
    db.expire_all()
    assert db.get(m.ScheduleRun, run.id).worker_id == "w1"


def test_cancel_queued_run(db):
    sc, _ = _scenario(db, 34)
    run = run_svc.enqueue_run(db, sc, "warehouse", "warehouse_fifo", 2, 0, {}, None, dispatch=False)
    run_svc.request_cancel(db, run)
    assert run.status == "CANCELLED"
    assert run_svc.execute_run(run.id, "w") == "CANCELLED"  # never executes


def test_invalid_schedule_is_never_published(db, monkeypatch):
    sc, _ = _scenario(db, 35)
    run = run_svc.enqueue_run(db, sc, "warehouse", "warehouse_edd", 2, 0, {}, None, dispatch=False)
    snap = snapshot_from_row(db.get(m.ScenarioSnapshotRow, run.snapshot_id))
    good = run_algorithm(snap, "warehouse_edd", SolveConfig(problem_type="warehouse"))
    bad = good.model_copy(deep=True)
    bad.assignments[0].end_min += 7  # corrupt → validator error

    def fake_run(*a, **k):  # type: ignore[no-untyped-def]
        from app.optimization.common.validator import validate_schedule

        bad.validation = validate_schedule(snap, bad)
        return bad

    monkeypatch.setattr(run_svc, "run_algorithm", fake_run)
    status = run_svc.execute_run(run.id, "w")
    assert status == "FAILED"
    db.expire_all()
    r = db.get(m.ScheduleRun, run.id)
    assert r.is_feasible is False and "validation error" in r.error_message
    assert db.scalar(select(m.ScheduleAssignment).where(m.ScheduleAssignment.run_id == run.id)) is None


def test_solver_exception_marks_failed(db, monkeypatch):
    sc, _ = _scenario(db, 36)
    run = run_svc.enqueue_run(db, sc, "warehouse", "warehouse_edd", 2, 0, {}, None, dispatch=False)

    def boom(*a, **k):  # type: ignore[no-untyped-def]
        raise RuntimeError("solver exploded")

    from app.optimization.warehouse import heuristics

    monkeypatch.setattr(heuristics.DispatchRuleScheduler, "solve", boom)
    assert run_svc.execute_run(run.id, "w") == "FAILED"
    db.expire_all()
    assert "solver exploded" in db.get(m.ScheduleRun, run.id).error_message


def test_snapshot_versioning_on_master_change(db):
    sc, _ = _scenario(db, 37)
    a = current_snapshot(db, sc)
    b = current_snapshot(db, sc)
    assert a.id == b.id
    w = db.scalar(select(m.Worker).where(m.Worker.facility_id == sc.facility_id).limit(1))
    w.active = False
    db.flush()
    c = current_snapshot(db, sc)
    assert c.version == a.version + 1
    assert snapshot_from_row(a).resource_map().get(w.code) is not None  # old snapshot unchanged
    db.commit()


def test_demo_scenarios_seed_idempotent(db):
    first = ensure_demo_scenarios(db)
    db.commit()
    second = ensure_demo_scenarios(db)
    assert [s.id for s in first] == [s.id for s in second]
    assert [s.name for s in first] == ["normal_day", "peak_demand", "vehicle_breakdown", "warehouse_bottleneck"]
