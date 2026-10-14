from __future__ import annotations

import pytest

SMALL = {
    "name": "api-integrated",
    "seed": 14,
    "n_orders": 16,
    "n_workers": 3,
    "n_pack_stations": 1,
    "n_docks": 1,
    "n_vans": 3,
    "n_trucks": 0,
}


@pytest.fixture(scope="module")
def scenario(client, auth_headers):
    r = client.post("/api/v1/scenarios", json=SMALL, headers=auth_headers)
    assert r.status_code == 201, r.text
    return r.json()


@pytest.mark.parametrize("alg", ["integrated_sequential", "integrated_iterative"])
def test_integrated_run_has_consistent_timestamps(client, auth_headers, scenario, alg):
    r = client.post(
        f"/api/v1/scenarios/{scenario['id']}/runs",
        json={"problem_type": "integrated", "algorithm": alg, "time_limit_s": 8, "seed": 1},
        headers=auth_headers,
    )
    assert r.status_code == 202
    run = client.get(f"/api/v1/runs/{r.json()['id']}", headers=auth_headers).json()
    assert run["status"] == "SUCCEEDED", run
    s = client.get(f"/api/v1/runs/{run['id']}/schedule", headers=auth_headers).json()
    by = {(a["task_type"], a["order_ids"][0]): a for a in s["assignments"] if a["task_type"] != "LOAD"}
    for rt in s["routes"]:
        for st in rt["stops"]:
            for oid in st["order_ids"]:
                pick, pack = by[("PICK", oid)], by[("PACK", oid)]
                assert pick["end_min"] <= pack["start_min"] <= pack["end_min"] <= rt["load_start_min"]
                assert rt["load_end_min"] <= rt["departure_min"] < st["arrival_min"] <= st["service_start_min"]
    val = client.get(f"/api/v1/runs/{run['id']}/validation", headers=auth_headers).json()
    assert val["is_feasible"] and set(val["scope"]) == {"warehouse", "dock", "routing"}
    met = client.get(f"/api/v1/runs/{run['id']}/metrics", headers=auth_headers).json()
    cost = met["metrics"]["cost"]
    assert cost["labor_cost"] > 0 and cost["distance_cost"] > 0 and cost["transport_fixed"] > 0
    assert met["metrics"]["end_to_end_makespan_min"] >= met["metrics"]["warehouse_makespan_min"]
