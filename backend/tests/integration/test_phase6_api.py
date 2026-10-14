from __future__ import annotations

import pytest

SMALL = {
    "name": "api-resched",
    "seed": 16,
    "n_orders": 14,
    "n_workers": 3,
    "n_pack_stations": 2,
    "n_docks": 1,
    "n_vans": 3,
    "n_trucks": 0,
}


@pytest.fixture(scope="module")
def base_run(client, auth_headers):
    sc = client.post("/api/v1/scenarios", json=SMALL, headers=auth_headers).json()
    r = client.post(
        f"/api/v1/scenarios/{sc['id']}/runs",
        json={"problem_type": "integrated", "algorithm": "integrated_sequential", "time_limit_s": 5},
        headers=auth_headers,
    ).json()
    run = client.get(f"/api/v1/runs/{r['id']}", headers=auth_headers).json()
    assert run["status"] == "SUCCEEDED"
    return sc, run


def test_event_idempotency(client, auth_headers, base_run):
    sc, _ = base_run
    url = f"/api/v1/scenarios/{sc['id']}/events"
    body = {"event_type": "travel_time_increase", "event_time_min": 200, "payload": {"factor": 1.5}}
    h = {**auth_headers, "Idempotency-Key": "evt-travel-1"}
    a = client.post(url, json=body, headers=h)
    b = client.post(url, json=body, headers=h)
    assert a.status_code == 201 and b.status_code == 200 and a.json()["id"] == b.json()["id"]
    c = client.post(url, json={**body, "payload": {"factor": 2.0}}, headers=h)
    assert c.status_code == 409 and c.json()["error"]["code"] == "idempotency_conflict"
    assert (
        client.post(url, json={"event_type": "worker_absence", "event_time_min": 10}, headers=auth_headers).status_code
        == 422
    )  # affected_code required
    assert len(client.get(url, headers=auth_headers).json()) == 1


def test_reschedule_creates_versions_and_recommendation(client, auth_headers, base_run):
    sc, run = base_run
    sched = client.get(f"/api/v1/runs/{run['id']}/schedule", headers=auth_headers).json()
    vid = sched["routes"][0]["vehicle_id"]
    ev = client.post(
        f"/api/v1/scenarios/{sc['id']}/events",
        json={
            "event_type": "vehicle_breakdown",
            "event_time_min": 60,
            "affected_code": vid,
            "idempotency_key": "evt-bd-1",
        },
        headers=auth_headers,
    ).json()
    r = client.post(
        f"/api/v1/runs/{run['id']}/reschedule",
        json={"event_id": ev["id"], "time_limit_s": 4, "expected_schedule_version": 1},
        headers=auth_headers,
    )
    assert r.status_code == 202, r.text
    new_ids = r.json()["new_run_ids"]
    assert len(new_ids) == 3
    for rid in new_ids:
        nr = client.get(f"/api/v1/runs/{rid}", headers=auth_headers).json()
        assert nr["status"] == "SUCCEEDED", nr
        assert nr["parent_run_id"] == run["id"] and nr["schedule_version"] == 2
        assert nr["kpis"]["changed_tasks"] is not None
    # idempotent per (base, event, policy)
    again = client.post(f"/api/v1/runs/{run['id']}/reschedule", json={"event_id": ev["id"]}, headers=auth_headers)
    assert again.json()["new_run_ids"] == new_ids
    summ = client.get(f"/api/v1/runs/{run['id']}/reschedules", headers=auth_headers).json()
    assert {i["policy"] for i in summ["items"]} == {"KEEP", "PARTIAL", "FULL"}
    rec = summ["recommendations"][str(ev["id"])]
    assert rec["recommended"] in {"KEEP", "PARTIAL", "FULL"} and rec["reason"]
    # base run outputs untouched (immutable history)
    assert client.get(f"/api/v1/runs/{run['id']}/schedule", headers=auth_headers).json() == sched


def test_reschedule_guards(client, auth_headers, base_run):
    sc, run = base_run
    ev = client.post(
        f"/api/v1/scenarios/{sc['id']}/events",
        json={"event_type": "worker_absence", "event_time_min": 30, "affected_code": "NOPE"},
        headers=auth_headers,
    ).json()
    r = client.post(f"/api/v1/runs/{run['id']}/reschedule", json={"event_id": ev["id"]}, headers=auth_headers)
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_event"
    r = client.post(
        f"/api/v1/runs/{run['id']}/reschedule",
        json={"event_id": ev["id"], "expected_schedule_version": 7},
        headers=auth_headers,
    )
    assert r.status_code == 409
    r = client.post(
        f"/api/v1/runs/{run['id']}/reschedule",
        json={"event_id": ev["id"], "reoptimizer": "routing_nn"},
        headers=auth_headers,
    )
    assert r.status_code == 422
