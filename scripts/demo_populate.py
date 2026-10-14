"""Populate a running stack with a reproducible demo story through the PUBLIC API (stdlib only).

    python scripts/demo_populate.py --base http://localhost:8000/api/v1

1. integrated runs (sequential + iterative) on every demo scenario
2. warehouse (EDD vs CP-SAT) and routing (insertion / OR-Tools / ALNS × 3 seeds) experiments on the bottleneck scenario
3. dock run (CP-SAT) on the bottleneck scenario
4. vehicle breakdown on `vehicle_breakdown` → KEEP / PARTIAL / FULL rescheduling + recommendation
Prints the run ids used for screenshots. Requires a worker (DB-poller or Celery) to be running.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request


class Api:
    def __init__(self, base: str):
        self.base = base
        self.tok = self.call("POST", "/auth/login", {"email": "demo@dilsos.local", "password": "demo1234"})[
            "access_token"]

    def call(self, method: str, path: str, body: dict | None = None, headers: dict | None = None):  # type: ignore[no-untyped-def]
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode() if body is not None else None,
                                     method=method)
        req.add_header("Content-Type", "application/json")
        if getattr(self, "tok", None):
            req.add_header("Authorization", f"Bearer {self.tok}")
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        with urllib.request.urlopen(req, timeout=300) as r:
            return json.loads(r.read() or b"{}")

    def wait(self, ids: list[int]) -> list[dict]:
        out = {}
        while len(out) < len(ids):
            for rid in ids:
                if rid in out:
                    continue
                r = self.call("GET", f"/runs/{rid}")
                if r["status"] in ("SUCCEEDED", "FAILED", "CANCELLED"):
                    out[rid] = r
            time.sleep(0.5)
        return [out[i] for i in ids]

    def run(self, sid: int, problem: str, alg: str, tl: float = 10, seed: int = 1) -> dict:
        r = self.call("POST", f"/scenarios/{sid}/runs", {"problem_type": problem, "algorithm": alg,
                                                        "time_limit_s": tl, "seed": seed})
        return self.wait([r["id"]])[0]


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="http://localhost:8000/api/v1")
    a = p.parse_args()
    api = Api(a.base)
    scs = {s["name"]: s["id"] for s in api.call("GET", "/scenarios")["items"]}
    shots: dict[str, int] = {}
    for name in ("normal_day", "peak_demand", "warehouse_bottleneck", "vehicle_breakdown"):
        seq = api.run(scs[name], "integrated", "integrated_sequential", 15)
        it = api.run(scs[name], "integrated", "integrated_iterative", 20)
        print(f"{name}: sequential #{seq['id']} {seq['objective_total']} | iterative #{it['id']} {it['objective_total']}")
        shots[f"{name}_integrated"] = it["id"]
    sid = scs["warehouse_bottleneck"]
    exp = api.call("POST", f"/scenarios/{sid}/experiments", {
        "problem_type": "routing", "algorithms": ["routing_insertion", "routing_ortools", "routing_alns"],
        "seeds": [0, 1, 2], "time_limit_s": 8, "params": {"max_iterations": 200}})
    for r in api.wait(exp["run_ids"]):
        print(f"  routing #{r['id']} {r['algorithm']} seed={r['seed']} {r['status']} {r['objective_total']}")
    exp = api.call("POST", f"/scenarios/{sid}/experiments", {
        "problem_type": "warehouse", "algorithms": ["warehouse_edd", "warehouse_cpsat", "warehouse_tabu"],
        "seeds": [0, 1], "time_limit_s": 8, "params": {"max_evaluations": 800}})
    for r in api.wait(exp["run_ids"]):
        print(f"  warehouse #{r['id']} {r['algorithm']} seed={r['seed']} {r['status']} {r['objective_total']}")
    dock = api.run(sid, "dock", "dock_cpsat", 10)
    print(f"  dock #{dock['id']} {dock['status']} {dock['objective_total']}")

    vb = scs["vehicle_breakdown"]
    base = api.run(vb, "integrated", "integrated_sequential", 15)
    sched = api.call("GET", f"/runs/{base['id']}/schedule")
    vid = sorted(r["vehicle_id"] for r in sched["routes"])[1]
    ev = api.call("POST", f"/scenarios/{vb}/events", {"event_type": "vehicle_breakdown", "event_time_min": 150,
                                                      "affected_code": vid},
                  {"Idempotency-Key": f"demo-breakdown-{base['id']}"})
    st = api.call("POST", f"/runs/{base['id']}/reschedule", {"event_id": ev["id"], "time_limit_s": 10})
    api.wait(st["new_run_ids"])
    summ = api.call("GET", f"/runs/{base['id']}/reschedules")
    for i in summ["items"]:
        print(f"  {i['policy']:7s} #{i['new_run_id']} cost={i['total_cost']} unserved={i['unserved']} "
              f"changed={i['changed_tasks']}/{i['changed_routes']} stability={i['stability_score']}")
    print("  recommendation:", summ["recommendations"][str(ev["id"])]["reason"])
    shots.update(bottleneck_scenario=sid, breakdown_scenario=vb, breakdown_base=base["id"])
    print("SHOTS", json.dumps(shots))
    return 0


if __name__ == "__main__":
    sys.exit(main())
