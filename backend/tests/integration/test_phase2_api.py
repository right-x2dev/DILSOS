from __future__ import annotations

import pytest

SMALL = {
    "name": "api-dock",
    "seed": 12,
    "n_orders": 14,
    "n_workers": 3,
    "n_pack_stations": 2,
    "n_docks": 1,
    "n_vans": 3,
    "n_trucks": 0,
}


@pytest.fixture(scope="module")
def scenario(client, auth_headers):
    r = client.post("/api/v1/scenarios", json=SMALL, headers=auth_headers)
    assert r.status_code == 201, r.text
    return r.json()


@pytest.mark.parametrize("alg", ["dock_edd", "dock_cpsat"])
def test_dock_run_publishes_loads_routes_and_shipments(client, auth_headers, scenario, alg):
    r = client.post(
        f"/api/v1/scenarios/{scenario['id']}/runs",
        json={"problem_type": "dock", "algorithm": alg, "time_limit_s": 5, "seed": 3},
        headers=auth_headers,
    )
    assert r.status_code == 202
    run = client.get(f"/api/v1/runs/{r.json()['id']}", headers=auth_headers).json()
    assert run["status"] == "SUCCEEDED", run
    sched = client.get(f"/api/v1/runs/{run['id']}/schedule", headers=auth_headers).json()
    loads = [a for a in sched["assignments"] if a["task_type"] == "LOAD"]
    assert len(loads) == len(sched["routes"]) > 0
    # single dock: loads never overlap; departure after load end; load after packing
    loads.sort(key=lambda a: a["start_min"])
    assert all(b["start_min"] >= a["end_min"] for a, b in zip(loads, loads[1:], strict=False))
    pack_end = {a["order_ids"][0]: a["end_min"] for a in sched["assignments"] if a["task_type"] == "PACK"}
    for rt in sched["routes"]:
        assert rt["departure_min"] >= rt["load_end_min"]
        assert rt["load_start_min"] >= max(pack_end[o] for o in rt["order_ids"])
    val = client.get(f"/api/v1/runs/{run['id']}/validation", headers=auth_headers).json()
    assert {"D1", "D5", "R3"} <= set(val["checked_rules"]) and val["is_feasible"]
