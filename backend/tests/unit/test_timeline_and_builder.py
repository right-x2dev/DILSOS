from __future__ import annotations

from datetime import UTC, datetime

from app.optimization.common.contracts import Interval, ResourceRequirement
from app.optimization.common.timeline import Timeline, place_multi
from app.services.snapshot_builder import subtract
from tests.fixtures import tiny_definition, tiny_snapshot


def test_timeline_earliest_fit_respects_windows_and_busy():
    tl = Timeline([Interval(start=0, end=100), Interval(start=200, end=300)])
    assert tl.earliest_fit(0, 50) == 0
    tl.reserve(0, 40)
    assert tl.earliest_fit(0, 50) == 40
    tl.reserve(60, 100)
    # gap 40..60 too small for 30 → next window
    assert tl.earliest_fit(0, 30) == 200
    assert tl.earliest_fit(0, 20) == 40  # gap filling
    assert tl.earliest_fit(290, 20) is None
    tl.release(60, 100)
    assert tl.earliest_fit(41, 50) == 41


def test_place_multi_needs_common_free_time():
    tls = {"W": Timeline([Interval(start=0, end=100)]), "P": Timeline([Interval(start=0, end=100)])}
    tls["W"].reserve(0, 10)
    tls["P"].reserve(10, 30)
    reqs = [
        ResourceRequirement(kind="worker", eligible_ids=["W"]),
        ResourceRequirement(kind="pack_station", eligible_ids=["P"]),
    ]
    assert place_multi(tls, reqs, 0, 15) == (30, {"worker": "W", "pack_station": "P"})
    assert place_multi(tls, reqs, 0, 80) is None


def test_subtract_downtime():
    assert subtract([(0, 100)], [(20, 30), (90, 120)]) == [Interval(start=0, end=20), Interval(start=30, end=90)]


def test_builder_converts_local_time_to_utc_minutes():
    snap = tiny_snapshot()
    # 06:00 KST == 21:00 UTC previous day
    assert snap.horizon_start == datetime(2026, 10, 14, 21, 0, tzinfo=UTC)
    c1 = snap.customer_map()["C1"]
    assert (c1.tw_start, c1.tw_end) == (600 - 360, 900 - 360)
    o2 = snap.order_map()["O2"]
    assert (o2.release_min, o2.due_min, o2.weight_kg) == (20, 90, 4)


def test_builder_tasks_and_eligibility():
    snap = tiny_snapshot()
    t = snap.task_map()
    pick, pack = t["O1-PICK"], t["O1-PACK"]
    assert pick.requirements[0].eligible_ids == ["W1", "W2"]
    assert pack.predecessors == ["O1-PICK"]
    assert {q.kind for q in pack.requirements} == {"worker", "pack_station"}
    assert pack.requirements[0].eligible_ids == ["W1"]  # only W1 can pack
    # 4 units × 30 s = 2 min + base 3 + 1 zone × 2
    assert pick.duration_min == 3 + 2 + 2
    assert all(x.duration_min > 0 for x in snap.tasks)


def test_overnight_shift_window():
    d = tiny_definition()
    d.workers[1].shift_start_local = 1200
    d.workers[1].shift_end_local = 1500  # 20:00 → 01:00 next day, clipped at horizon end 22:00
    from app.services.snapshot_builder import build_snapshot

    snap = build_snapshot(d)
    w2 = snap.resource_map()["W2"]
    assert w2.available == [Interval(start=840, end=960)]


def test_travel_matrix_labelled_synthetic():
    snap = tiny_snapshot()
    assert snap.travel.provenance == "synthetic_euclidean"
    assert "SYNTHETIC" in snap.travel.notes
    n = len(snap.travel.location_ids)
    assert all(snap.travel.distance_m[i][i] == 0 for i in range(n))
