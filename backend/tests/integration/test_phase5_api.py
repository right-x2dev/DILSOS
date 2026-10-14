from __future__ import annotations

import pytest

SMALL = {
    "name": "api-exp",
    "seed": 15,
    "n_orders": 10,
    "n_workers": 2,
    "n_pack_stations": 1,
    "n_docks": 1,
    "n_vans": 2,
    "n_trucks": 0,
}


@pytest.fixture(scope="module")
def scenario(client, auth_headers):
    r = client.post("/api/v1/scenarios", json=SMALL, headers=auth_headers)
    assert r.status_code == 201, r.text
    return r.json()


def test_experiment_runs_share_snapshot_and_compare(client, auth_headers, scenario):
    body = {
        "problem_type": "routing",
        "algorithms": ["routing_insertion", "routing_alns"],
        "seeds": [0, 1, 2],
        "time_limit_s": 2,
        "params": {"max_iterations": 20},
    }
    r = client.post(f"/api/v1/scenarios/{scenario['id']}/experiments", json=body, headers=auth_headers)
    assert r.status_code == 202, r.text
    ids = r.json()["run_ids"]
    assert len(ids) == 1 + 3  # deterministic once, stochastic per seed
    cmp = client.get(f"/api/v1/runs/{ids[0]}/compare?ids={','.join(map(str, ids[1:]))}", headers=auth_headers).json()
    assert cmp["same_snapshot"] is True
    assert {row["algorithm"] for row in cmp["rows"]} == {"routing_insertion", "routing_alns"}
    assert all(row["status"] == "SUCCEEDED" and row["is_feasible"] for row in cmp["rows"])
    alns = [row for row in cmp["rows"] if row["algorithm"] == "routing_alns"]
    assert sorted(row["seed"] for row in alns) == [0, 1, 2]


def test_experiment_validation(client, auth_headers, scenario):
    url = f"/api/v1/scenarios/{scenario['id']}/experiments"
    too_many = {"problem_type": "routing", "algorithms": ["routing_alns"] * 4, "seeds": list(range(20))}
    assert client.post(url, json=too_many, headers=auth_headers).status_code == 422
    bad = {"problem_type": "routing", "algorithms": ["nope"]}
    assert client.post(url, json=bad, headers=auth_headers).json()["error"]["code"] == "unknown_algorithm"
