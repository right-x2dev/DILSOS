from __future__ import annotations

import csv
import io
import json

import pytest

from app.api import ratelimit
from app.core.config import get_settings

SMALL = {
    "name": "api-io",
    "seed": 17,
    "n_orders": 6,
    "n_workers": 2,
    "n_pack_stations": 1,
    "n_docks": 1,
    "n_vans": 2,
    "n_trucks": 0,
}


@pytest.fixture(scope="module")
def scenario(client, auth_headers):
    r = client.post("/api/v1/scenarios", json=SMALL, headers=auth_headers)
    assert r.status_code == 201
    return r.json()


def _codes(client, auth_headers, sc):
    o = client.get(f"/api/v1/orders?scenario_id={sc['id']}&limit=1", headers=auth_headers).json()["items"][0]
    return o["customer_code"], o["lines"][0]["sku_code"]


def _csv(rows):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["order_code", "customer_code", "release_local", "due_local", "priority", "sku_code", "qty"])
    w.writerows(rows)
    return buf.getvalue().encode()


def test_csv_import_success_multi_line_order(client, auth_headers, scenario):
    cust, sku = _codes(client, auth_headers, scenario)
    data = _csv(
        [
            ["IMP-1", cust, "08:00", "11:00", 2, sku, 3],
            ["IMP-1", cust, "08:00", "11:00", 2, sku, 1],
            ["IMP-2", cust, "09:15", "13:00", 1, sku, 2],
        ]
    )
    r = client.post(
        "/api/v1/imports/orders",
        headers=auth_headers,
        data={"scenario_id": str(scenario["id"])},
        files={"file": ("orders.csv", data, "text/csv")},
    )
    assert r.status_code == 201, r.text
    assert r.json()["created_orders"] == ["IMP-1", "IMP-2"] and r.json()["lines"] == 3
    page = client.get(f"/api/v1/orders?scenario_id={scenario['id']}&q=IMP-1", headers=auth_headers).json()
    assert page["items"][0]["units"] == 4
    assert page["items"][0]["release_at"].startswith("2026-10-14T23:00:00")  # 08:00 KST in UTC


def test_csv_import_is_all_or_nothing(client, auth_headers, scenario):
    cust, sku = _codes(client, auth_headers, scenario)
    data = _csv([["IMP-OK", cust, "08:00", "11:00", 1, sku, 1], ["IMP-BAD", "NOPE", "8h", "07:00", 9, "X", 0]])
    r = client.post(
        "/api/v1/imports/orders",
        headers=auth_headers,
        data={"scenario_id": str(scenario["id"])},
        files={"file": ("orders.csv", data, "text/csv")},
    )
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "import_validation_failed"
    fields = {d["field"] for d in err["details"]}
    assert {"customer_code", "sku_code", "release_local"} <= fields
    assert (
        client.get(f"/api/v1/orders?scenario_id={scenario['id']}&q=IMP-OK", headers=auth_headers).json()["total"] == 0
    )


def test_csv_import_rejects_bad_header_and_large_files(client, auth_headers, scenario, monkeypatch):
    r = client.post(
        "/api/v1/imports/orders",
        headers=auth_headers,
        data={"scenario_id": str(scenario["id"])},
        files={"file": ("x.csv", b"a,b\n1,2\n", "text/csv")},
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_header"
    monkeypatch.setattr(get_settings(), "max_upload_bytes", 10)
    r = client.post(
        "/api/v1/imports/orders",
        headers=auth_headers,
        data={"scenario_id": str(scenario["id"])},
        files={"file": ("x.csv", b"x" * 100, "text/csv")},
    )
    assert r.status_code == 413
    r = client.post(
        "/api/v1/imports/orders",
        headers=auth_headers,
        data={"scenario_id": str(scenario["id"])},
        files={"file": ("x.png", b"x", "image/png")},
    )
    assert r.status_code in (413, 415)


def test_example_dataset_csv_imports_into_normal_day(client, auth_headers, db):
    from pathlib import Path

    from app.seed.cli import ensure_demo_scenarios

    scs = ensure_demo_scenarios(db)
    db.commit()
    normal = next(s for s in scs if s.name == "normal_day")
    path = Path(__file__).resolve().parents[3] / "datasets" / "examples" / "orders_normal_day_extra.csv"
    r = client.post(
        "/api/v1/imports/orders",
        headers=auth_headers,
        data={"scenario_id": str(normal.id)},
        files={"file": (path.name, path.read_bytes(), "text/csv")},
    )
    assert r.status_code == 201, r.text
    assert r.json()["created_orders"] == ["EXTRA-001", "EXTRA-002", "EXTRA-003"]


def test_export_csv_and_json(client, auth_headers, scenario):
    run = client.post(
        f"/api/v1/scenarios/{scenario['id']}/runs",
        json={"problem_type": "integrated", "algorithm": "integrated_sequential", "time_limit_s": 4},
        headers=auth_headers,
    ).json()
    r = client.get(f"/api/v1/exports/runs/{run['id']}?format=csv", headers=auth_headers)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    rows = list(csv.DictReader(io.StringIO(r.text)))
    kinds = {x["record"] for x in rows}
    assert {"task", "route", "stop"} <= kinds
    assert all(x["start_utc"].endswith("+00:00") for x in rows)
    j = client.get(f"/api/v1/exports/runs/{run['id']}?format=json", headers=auth_headers)
    body = json.loads(j.text)
    assert body["travel_provenance"] == "synthetic_euclidean" and body["validation"]["is_feasible"]


def test_rate_limit(client, auth_headers, scenario, monkeypatch):
    ratelimit.reset()
    monkeypatch.setattr(get_settings(), "rate_limit_per_minute", 2)
    url = f"/api/v1/scenarios/{scenario['id']}/runs"
    body = {"problem_type": "warehouse", "algorithm": "warehouse_fifo", "time_limit_s": 1}
    assert client.post(url, json=body, headers=auth_headers).status_code == 202
    assert client.post(url, json=body, headers=auth_headers).status_code == 202
    r = client.post(url, json=body, headers=auth_headers)
    assert r.status_code == 429 and r.json()["error"]["code"] == "rate_limited"
    ratelimit.reset()


def test_ops_metrics(client):
    r = client.get("/api/v1/ops/metrics")
    assert r.status_code == 200
    assert "dilsos_runs_total{" in r.text and "dilsos_http_requests_total{" in r.text
    assert "dilsos_runs_rejected_infeasible" in r.text


def test_openapi_lists_spec_endpoints(client):
    paths = client.get("/api/v1/openapi.json").json()["paths"]
    for p in [
        "/api/v1/auth/login",
        "/api/v1/orders",
        "/api/v1/resources/workers",
        "/api/v1/resources/vehicles",
        "/api/v1/resources/docks",
        "/api/v1/scenarios",
        "/api/v1/scenarios/{scenario_id}/validate",
        "/api/v1/scenarios/{scenario_id}/runs",
        "/api/v1/runs/{run_id}",
        "/api/v1/runs/{run_id}/schedule",
        "/api/v1/runs/{run_id}/validation",
        "/api/v1/runs/{run_id}/metrics",
        "/api/v1/algorithms",
        "/api/v1/scenarios/{scenario_id}/events",
        "/api/v1/runs/{run_id}/reschedule",
        "/api/v1/runs/{run_id}/compare",
        "/api/v1/imports/orders",
        "/api/v1/exports/runs/{run_id}",
        "/api/v1/health/live",
        "/api/v1/health/ready",
    ]:
        assert p in paths, p
