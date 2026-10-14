"""API-level vertical slice: scenario → validate → enqueue (202) → run → schedule/validation/metrics."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db import models as m
from app.db.models import ImmutableOutputError

SMALL = {
    "name": "api-small",
    "seed": 11,
    "n_orders": 12,
    "n_workers": 3,
    "n_pack_stations": 2,
    "n_docks": 1,
    "n_vans": 2,
    "n_trucks": 0,
}


@pytest.fixture(scope="module")
def scenario(client, auth_headers):
    r = client.post("/api/v1/scenarios", json=SMALL, headers=auth_headers)
    assert r.status_code == 201, r.text
    return r.json()


def test_scenario_created_and_listed(client, auth_headers, scenario):
    assert scenario["order_count"] == 12
    assert scenario["resource_counts"]["workers"] == 3
    r = client.get("/api/v1/scenarios", headers=auth_headers)
    assert r.status_code == 200
    assert any(s["id"] == scenario["id"] for s in r.json()["items"])


def test_requires_auth(client):
    assert client.get("/api/v1/scenarios").status_code == 401
    assert client.post("/api/v1/scenarios", json=SMALL).status_code == 401


def test_validate_scenario(client, auth_headers, scenario):
    r = client.post(f"/api/v1/scenarios/{scenario['id']}/validate", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["summary"]["orders"] == 12 and body["summary"]["tasks"] == 24
    assert body["summary"]["travel_provenance"] == "synthetic_euclidean"


def test_algorithms_listed(client, auth_headers):
    r = client.get("/api/v1/algorithms", headers=auth_headers)
    names = {a["name"]: a for a in r.json()}
    assert {"warehouse_fifo", "warehouse_edd", "warehouse_spt", "warehouse_cpsat"} <= set(names)
    assert names["warehouse_cpsat"]["available"] is True


@pytest.mark.parametrize("alg", ["warehouse_edd", "warehouse_cpsat"])
def test_run_lifecycle(client, auth_headers, scenario, alg):
    r = client.post(
        f"/api/v1/scenarios/{scenario['id']}/runs",
        json={"problem_type": "warehouse", "algorithm": alg, "time_limit_s": 3, "seed": 1},
        headers=auth_headers,
    )
    assert r.status_code == 202, r.text
    rid = r.json()["id"]
    run = client.get(f"/api/v1/runs/{rid}", headers=auth_headers).json()
    assert run["status"] == "SUCCEEDED", run  # eager backend in tests
    assert run["is_feasible"] is True
    assert run["kpis"]["orders_served"] + run["kpis"]["orders_unserved"] <= 12
    sched = client.get(f"/api/v1/runs/{rid}/schedule", headers=auth_headers).json()
    assert len(sched["assignments"]) == 2 * run["kpis"]["orders_served"]
    assert {x["kind"] for x in sched["resources"]} >= {"worker", "pack_station"}
    val = client.get(f"/api/v1/runs/{rid}/validation", headers=auth_headers).json()
    assert val["is_feasible"] is True and "W7" in val["checked_rules"]
    met = client.get(f"/api/v1/runs/{rid}/metrics", headers=auth_headers).json()
    assert met["metrics"]["cost"]["total_cost"] > 0
    if alg == "warehouse_edd":
        assert met["gap"] is None and "no optimality gap" in met["gap_note"]


def test_snapshot_reused_when_master_data_unchanged(client, auth_headers, scenario, db):
    runs = db.scalars(select(m.ScheduleRun).where(m.ScheduleRun.scenario_id == scenario["id"])).all()
    assert len({r.snapshot_id for r in runs}) == 1


def test_unknown_or_unsupported_algorithm(client, auth_headers, scenario):
    url = f"/api/v1/scenarios/{scenario['id']}/runs"
    r = client.post(url, json={"problem_type": "warehouse", "algorithm": "nope"}, headers=auth_headers)
    assert r.status_code == 422 and r.json()["error"]["code"] == "unknown_algorithm"
    r = client.post(url, json={"problem_type": "routing", "algorithm": "warehouse_edd"}, headers=auth_headers)
    assert r.status_code == 422 and r.json()["error"]["code"] == "unsupported_problem"
    r = client.post(
        url,
        json={"problem_type": "warehouse", "algorithm": "warehouse_edd", "time_limit_s": 9999},
        headers=auth_headers,
    )
    assert r.status_code == 422


def test_cancel_finished_run_conflict(client, auth_headers, scenario):
    rid = client.get(f"/api/v1/runs?scenario_id={scenario['id']}", headers=auth_headers).json()["items"][0]["id"]
    r = client.post(f"/api/v1/runs/{rid}/cancel", headers=auth_headers)
    assert r.status_code == 409


def test_compare_same_snapshot(client, auth_headers, scenario):
    rid = client.get(f"/api/v1/runs?scenario_id={scenario['id']}", headers=auth_headers).json()["items"][0]["id"]
    body = client.get(f"/api/v1/runs/{rid}/compare", headers=auth_headers).json()
    assert body["same_snapshot"] is True and len(body["rows"]) >= 2


def test_published_outputs_are_immutable(db, scenario):
    a = db.scalar(select(m.ScheduleAssignment).limit(1))
    a.start_min += 1
    with pytest.raises(ImmutableOutputError):
        db.flush()
    db.rollback()


def test_orders_list_and_create(client, auth_headers, scenario):
    r = client.get(f"/api/v1/orders?scenario_id={scenario['id']}&limit=5", headers=auth_headers).json()
    assert r["total"] == 12 and len(r["items"]) == 5
    o = r["items"][0]
    body = {
        "scenario_id": scenario["id"],
        "code": "API-NEW-1",
        "customer_code": o["customer_code"],
        "release_at": "2026-10-15T08:00:00+09:00",
        "due_at": "2026-10-15T12:00:00+09:00",
        "priority": 3,
        "lines": [{"sku_code": o["lines"][0]["sku_code"], "qty": 2}],
    }
    r = client.post("/api/v1/orders", json=body, headers=auth_headers)
    assert r.status_code == 201, r.text
    assert r.json()["release_at"].startswith("2026-10-14T23:00:00")  # stored/returned in UTC
    assert client.post("/api/v1/orders", json=body, headers=auth_headers).status_code == 409
    bad = dict(body, code="API-NEW-2", due_at="2026-10-15T07:00:00+09:00")
    assert client.post("/api/v1/orders", json=bad, headers=auth_headers).status_code == 422
    naive = dict(body, code="API-NEW-3", release_at="2026-10-15T08:00:00")
    assert client.post("/api/v1/orders", json=naive, headers=auth_headers).status_code == 422
    # new order changes the snapshot → next run uses version 2
    r = client.post(f"/api/v1/scenarios/{scenario['id']}/validate", headers=auth_headers).json()
    assert r["summary"]["orders"] == 13 and r["summary"]["snapshot_version"] == 2


def test_resources_crud(client, auth_headers, scenario):
    fid = scenario["facility"]["id"]
    assert len(client.get(f"/api/v1/resources/workers?facility_id={fid}", headers=auth_headers).json()) == 3
    w = {
        "facility_id": fid,
        "code": "WX",
        "name": "x",
        "skills": ["pick", "pack"],
        "hourly_cost": 15000,
        "shift_start_local_min": 1320,
        "shift_end_local_min": 1800,
    }
    assert client.post("/api/v1/resources/workers", json=w, headers=auth_headers).status_code == 201
    assert client.post("/api/v1/resources/workers", json=w, headers=auth_headers).status_code == 409
    bad = dict(w, code="WY", shift_end_local_min=100)
    assert client.post("/api/v1/resources/workers", json=bad, headers=auth_headers).status_code == 422
    v = {
        "facility_id": fid,
        "code": "VX",
        "capacity_kg": 500,
        "capacity_l": 3000,
        "fixed_cost": 1,
        "cost_per_km": 1,
        "shift_start_local_min": 480,
        "shift_end_local_min": 1200,
    }
    assert client.post("/api/v1/resources/vehicles", json=v, headers=auth_headers).status_code == 201
    d = {
        "facility_id": fid,
        "code": "DX",
        "name": "dx",
        "vehicle_classes": ["van"],
        "open_start_local_min": 420,
        "open_end_local_min": 1200,
    }
    assert client.post("/api/v1/resources/docks", json=d, headers=auth_headers).status_code == 201


def test_scenario_update_optimistic_concurrency(client, auth_headers, scenario):
    sid = scenario["id"]
    cur = client.get(f"/api/v1/scenarios/{sid}", headers=auth_headers).json()
    ok = client.patch(f"/api/v1/scenarios/{sid}", json={"version": cur["version"], "seed": 99}, headers=auth_headers)
    assert ok.status_code == 200 and ok.json()["seed"] == 99
    stale = client.patch(f"/api/v1/scenarios/{sid}", json={"version": cur["version"], "seed": 5}, headers=auth_headers)
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "version_conflict"


def test_clone_and_dashboard(client, auth_headers, scenario):
    r = client.post(f"/api/v1/scenarios/{scenario['id']}/clone", json={"name": "clone"}, headers=auth_headers)
    assert r.status_code == 201 and r.json()["parent_scenario_id"] == scenario["id"]
    d = client.get(f"/api/v1/dashboard/summary?scenario_id={scenario['id']}", headers=auth_headers).json()
    assert d["latest_success"] is not None and d["runs_by_status"]["SUCCEEDED"] >= 2


def test_geo_labels_synthetic(client, auth_headers, scenario):
    g = client.get(f"/api/v1/scenarios/{scenario['id']}/geo", headers=auth_headers).json()
    assert "synthetic" in g["coordinate_provenance"]
    assert g["points"][0]["kind"] == "depot"


def test_audit_log_written(db):
    acts = {a.action for a in db.scalars(select(m.AuditLog))}
    assert {"login", "create", "enqueue"} <= acts
