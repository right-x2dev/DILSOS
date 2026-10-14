from __future__ import annotations

import pytest

SMALL = {
    "name": "api-route",
    "seed": 13,
    "n_orders": 15,
    "n_workers": 3,
    "n_pack_stations": 2,
    "n_docks": 1,
    "n_vans": 3,
    "n_trucks": 1,
}


@pytest.fixture(scope="module")
def scenario(client, auth_headers):
    r = client.post("/api/v1/scenarios", json=SMALL, headers=auth_headers)
    assert r.status_code == 201, r.text
    return r.json()


@pytest.mark.parametrize("alg", ["routing_nn", "routing_insertion", "routing_ortools"])
def test_routing_run_publishes_routes_and_stops(client, auth_headers, scenario, alg, db):
    r = client.post(
        f"/api/v1/scenarios/{scenario['id']}/runs",
        json={"problem_type": "routing", "algorithm": alg, "time_limit_s": 3, "seed": 1},
        headers=auth_headers,
    )
    assert r.status_code == 202
    run = client.get(f"/api/v1/runs/{r.json()['id']}", headers=auth_headers).json()
    assert run["status"] == "SUCCEEDED", run
    assert run["kpis"]["total_distance_km"] > 0
    sched = client.get(f"/api/v1/runs/{run['id']}/schedule", headers=auth_headers).json()
    assert sched["assignments"] == [] and sched["routes"]
    served = sorted(o for rt in sched["routes"] for s in rt["stops"] for o in s["order_ids"])
    unserved = sorted(u["order_id"] for u in sched["unserved"])
    assert len(served) + len(unserved) == 15 and not set(served) & set(unserved)
    assert "schematic" in sched["geometry_note"] or "직선" in sched["geometry_note"]
    from sqlalchemy import func, select

    from app.db import models as m

    n_stops = db.scalar(
        select(func.count()).select_from(m.RouteStopRow).join(m.RouteRow).where(m.RouteRow.run_id == run["id"])
    )
    assert n_stops == sum(len(rt["stops"]) for rt in sched["routes"])
    met = client.get(f"/api/v1/runs/{run['id']}/metrics", headers=auth_headers).json()
    assert met["gap"] is None  # routing never reports a fake optimality gap
