"""Enqueue optimization runs through the public API and wait for them (stdlib only).

    python scripts/run_via_api.py --scenario 4 --problem dock --algorithms dock_fifo,dock_edd,dock_cpsat
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request


def call(base: str, method: str, path: str, body: dict | None = None, token: str | None = None) -> dict:
    req = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code} {method} {path}: {e.read().decode()[:400]}", file=sys.stderr)
        raise


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="http://localhost:8000/api/v1")
    p.add_argument("--scenario", type=int, required=True)
    p.add_argument("--problem", required=True)
    p.add_argument("--algorithms", required=True)
    p.add_argument("--time-limit", type=float, default=10)
    p.add_argument("--seed", type=int, default=0)
    a = p.parse_args()
    tok = call(a.base, "POST", "/auth/login", {"email": "demo@dilsos.local", "password": "demo1234"})["access_token"]
    ids = []
    for alg in a.algorithms.split(","):
        r = call(a.base, "POST", f"/scenarios/{a.scenario}/runs",
                 {"problem_type": a.problem, "algorithm": alg, "time_limit_s": a.time_limit, "seed": a.seed}, tok)
        ids.append(r["id"])
        print(f"queued run #{r['id']} {alg}")
    pending = set(ids)
    while pending:
        for rid in sorted(pending):
            r = call(a.base, "GET", f"/runs/{rid}", token=tok)
            if r["status"] in ("SUCCEEDED", "FAILED", "CANCELLED"):
                k = r.get("kpis") or {}
                print(f"run #{rid} {r['algorithm']}: {r['status']} solver={r['solver_status']} "
                      f"cost={r['objective_total']} late={k.get('total_lateness_min')} on_time={k.get('on_time_rate')} "
                      f"err={r['error_message']}")
                pending.discard(rid)
        time.sleep(1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
