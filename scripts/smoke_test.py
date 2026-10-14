"""Stdlib-only API smoke test against a running DILSOS stack.

    python scripts/smoke_test.py --base http://localhost:8080/api/v1

Checks: liveness, readiness, demo login. Later phases extend this with a real optimization run.
Exit code != 0 on any failure.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request


def call(base: str, method: str, path: str, body: dict | None = None, token: str | None = None) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="http://localhost:8000/api/v1")
    p.add_argument("--email", default="demo@dilsos.local")
    p.add_argument("--password", default="demo1234")
    p.add_argument("--skip-run", action="store_true", help="only health + login")
    a = p.parse_args()

    st, body = call(a.base, "GET", "/health/live")
    assert st == 200, (st, body)
    st, body = call(a.base, "GET", "/health/ready")
    assert st == 200 and body["status"] == "ready", (st, body)
    print("health ok:", body)

    st, body = call(a.base, "POST", "/auth/login", {"email": a.email, "password": a.password})
    assert st == 200, (st, body)
    token = body["access_token"]
    print("login ok")
    if a.skip_run:
        return 0

    st, scenarios = call(a.base, "GET", "/scenarios", token=token)
    if st == 404:
        print("scenarios endpoint not available yet; stopping after login")
        return 0
    assert st == 200 and scenarios["items"], (st, scenarios)
    sid = scenarios["items"][0]["id"]
    st, run = call(a.base, "POST", f"/scenarios/{sid}/runs",
                   {"problem_type": "integrated", "algorithm": "integrated_sequential", "time_limit_s": 10, "seed": 1},
                   token=token)
    assert st == 202, (st, run)
    rid = run["id"]
    for _ in range(120):
        st, run = call(a.base, "GET", f"/runs/{rid}", token=token)
        if run["status"] in ("SUCCEEDED", "FAILED", "CANCELLED"):
            break
        time.sleep(1)
    print("run:", run["status"], run.get("solver_status"))
    assert run["status"] == "SUCCEEDED", run
    st, val = call(a.base, "GET", f"/runs/{rid}/validation", token=token)
    assert st == 200 and val["is_feasible"], val
    print("validated schedule ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
