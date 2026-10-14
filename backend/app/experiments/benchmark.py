"""Reproducible benchmark harness (in-memory, no DB) — every number comes from an actual run.

    python -m app.experiments.benchmark --suite quick --out ../docs/experiments
    python -m app.experiments.benchmark --suite full  --out ../docs/experiments

Protocol (spec §5.3): fixed instance seeds per size class, identical snapshots/objective for all
algorithms of a problem type, fixed time budget per algorithm, evaluation/iteration budgets for
stochastic searches (hardware-independent), ``runs`` repetitions with seeds 0..runs-1 for
stochastic algorithms, hardware metadata recorded, validator applied to every result.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import platform
import statistics
import sys
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.optimization.common import registry
from app.optimization.common.contracts import ScenarioSnapshot, SolveConfig
from app.optimization.common.runner import is_publishable, run_algorithm
from app.seed.generator import DEMO_SCENARIOS, GeneratorConfig, generate
from app.services.snapshot_builder import build_snapshot

SIZE = {
    "small": dict(n_orders=20, n_workers=3, n_pack_stations=1, n_docks=1, n_vans=3, n_trucks=0),
    "medium": dict(n_orders=100, n_workers=8, n_pack_stations=3, n_docks=2, n_vans=6, n_trucks=2),
    "large": dict(n_orders=250, n_workers=16, n_pack_stations=6, n_docks=4, n_vans=12, n_trucks=4),
}

SUITES = {
    "quick": {
        "instances": [("small", 1), ("small", 2), ("small", 3), ("demo", "warehouse_bottleneck")],
        "problems": {
            "warehouse": [
                "warehouse_fifo",
                "warehouse_edd",
                "warehouse_spt",
                "warehouse_cpsat",
                "warehouse_sa",
                "warehouse_tabu",
                "warehouse_ga",
            ],
            "routing": ["routing_nn", "routing_insertion", "routing_ortools", "routing_alns"],
            "integrated": ["integrated_sequential", "integrated_iterative"],
        },
        "time_limit": 5.0,
        "runs": 5,
        "max_evaluations": 600,
        "alns_iterations": 150,
    },
    "full": {
        "instances": [
            ("small", 1),
            ("small", 2),
            ("small", 3),
            ("medium", 1),
            ("medium", 2),
            ("medium", 3),
            ("large", 1),
            ("demo", "normal_day"),
            ("demo", "peak_demand"),
            ("demo", "warehouse_bottleneck"),
        ],
        "problems": {
            "warehouse": ["warehouse_edd", "warehouse_cpsat", "warehouse_sa", "warehouse_tabu", "warehouse_ga"],
            "dock": ["dock_fifo", "dock_edd", "dock_cpsat"],
            "routing": ["routing_nn", "routing_insertion", "routing_ortools", "routing_alns"],
            "integrated": ["integrated_sequential", "integrated_iterative"],
        },
        "time_limit": 10.0,
        "runs": 10,
        "max_evaluations": 1500,
        "alns_iterations": 300,
    },
}


@dataclass
class Row:
    instance: str
    size: str
    orders: int
    problem: str
    algorithm: str
    stochastic: bool
    run_seed: int
    status: str
    feasible: bool
    publishable: bool
    total_cost: float | None
    late_min: int | None
    on_time_rate: float | None
    distance_km: float | None
    vehicles: int | None
    unserved: int | None
    runtime_s: float
    time_to_first_feasible_s: float | None
    gap: float | None


def instances(spec: list) -> list[tuple[str, str, ScenarioSnapshot]]:
    out = []
    for size, key in spec:
        if size == "demo":
            cfg = DEMO_SCENARIOS[key]
            out.append((key, "demo", build_snapshot(generate(cfg))))
        else:
            cfg = GeneratorConfig(name=f"{size}-s{key}", seed=1000 + int(key), **SIZE[size])  # type: ignore[arg-type]
            out.append((cfg.name, size, build_snapshot(generate(cfg))))
    return out


def hardware() -> dict:
    import ortools

    return {
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "cpu_count": os.cpu_count(),
        "processor": platform.processor() or platform.machine(),
        "ortools": ortools.__version__,
        "timestamp_utc": datetime.now(UTC).isoformat(timespec="seconds"),
    }


def run_suite(name: str, out_dir: Path, limit_instances: int | None = None) -> dict:
    suite = SUITES[name]
    rows: list[Row] = []
    insts = instances(suite["instances"])[:limit_instances]
    for inst_name, size, snap in insts:
        for problem, algs in suite["problems"].items():
            for alg in algs:
                info = registry.get(alg)
                seeds = range(suite["runs"]) if info.stochastic else [0]
                for seed in seeds:
                    params = {"max_evaluations": suite["max_evaluations"], "max_iterations": suite["alns_iterations"]}
                    if alg.endswith("cpsat") or alg == "integrated_iterative":
                        params["num_workers"] = 8
                    t0 = time.perf_counter()
                    r = run_algorithm(
                        snap,
                        alg,
                        SolveConfig(problem_type=problem, time_limit_s=suite["time_limit"], seed=seed, params=params),
                    )  # type: ignore[arg-type]
                    m = r.metrics
                    md = r.solver_metadata
                    rows.append(
                        Row(
                            instance=inst_name,
                            size=size,
                            orders=len(snap.orders),
                            problem=problem,
                            algorithm=alg,
                            stochastic=info.stochastic,
                            run_seed=seed,
                            status=r.status,
                            feasible=bool(r.validation and r.validation.is_feasible),
                            publishable=is_publishable(r),
                            total_cost=m.cost.total_cost if m else None,
                            late_min=m.total_lateness_min if m else None,
                            on_time_rate=m.on_time_rate if m else None,
                            distance_km=m.total_distance_km if m else None,
                            vehicles=m.vehicles_used if m else None,
                            unserved=m.orders_unserved if m else None,
                            runtime_s=round(time.perf_counter() - t0, 3),
                            time_to_first_feasible_s=md.get("time_to_first_feasible_s"),
                            gap=md.get("gap"),
                        )
                    )
                    print(
                        f"{inst_name:22s} {problem:10s} {alg:22s} seed={seed} {r.status:10s} "
                        f"feasible={rows[-1].feasible} cost={rows[-1].total_cost} t={rows[-1].runtime_s}s",
                        flush=True,
                    )
    out_dir.mkdir(parents=True, exist_ok=True)
    raw = out_dir / f"benchmark_{name}_raw.csv"
    with raw.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(asdict(rows[0])))
        w.writeheader()
        for row in rows:
            w.writerow(asdict(row))
    summary = summarize(rows)
    meta = {
        "suite": name,
        "config": {k: v for k, v in suite.items() if k != "instances"},
        "instances": [i[0] for i in insts],
        "hardware": hardware(),
    }
    (out_dir / f"benchmark_{name}_meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    (out_dir / f"benchmark_{name}_summary.md").write_text(render_md(name, summary, meta), encoding="utf-8")
    return {"rows": len(rows), "summary": summary, "meta": meta}


def summarize(rows: list[Row]) -> list[dict]:
    groups: dict[tuple[str, str, str], list[Row]] = {}
    for r in rows:
        groups.setdefault((r.instance, r.problem, r.algorithm), []).append(r)
    out = []
    for (inst, prob, alg), rs in groups.items():
        feas = [r for r in rs if r.feasible and r.total_cost is not None]
        costs = [r.total_cost for r in feas]
        out.append(
            {
                "instance": inst,
                "problem": prob,
                "algorithm": alg,
                "runs": len(rs),
                "infeasible_rate": round(1 - len(feas) / len(rs), 3),
                "best": round(min(costs), 2) if costs else None,
                "mean": round(statistics.fmean(costs), 2) if costs else None,
                "std": round(statistics.pstdev(costs), 2) if len(costs) > 1 else 0.0,
                "mean_late_min": round(statistics.fmean([r.late_min or 0 for r in feas]), 1) if feas else None,
                "mean_runtime_s": round(statistics.fmean([r.runtime_s for r in rs]), 3),
                "mean_ttff_s": (
                    round(
                        statistics.fmean(
                            [r.time_to_first_feasible_s for r in rs if r.time_to_first_feasible_s is not None]
                        ),
                        3,
                    )
                    if any(r.time_to_first_feasible_s is not None for r in rs)
                    else None
                ),
                "gap": next((r.gap for r in rs if r.gap is not None), None),
            }
        )
    return out


def render_md(name: str, summary: list[dict], meta: dict) -> str:
    hw = meta["hardware"]
    lines = [
        f"# Benchmark `{name}` — generated by `python -m app.experiments.benchmark --suite {name}`",
        "",
        f"Generated {hw['timestamp_utc']} on {hw['platform']} · Python {hw['python']} · {hw['cpu_count']} logical CPUs"
        f" · OR-Tools {hw['ortools']}.",
        f"Budget per run: {meta['config']['time_limit']} s; stochastic algorithms: {meta['config']['runs']} seeds; "
        f"SA/Tabu/GA max evaluations {meta['config']['max_evaluations']}; ALNS max iterations "
        f"{meta['config']['alns_iterations']}.",
        "Costs are the shared evaluator's `total_cost` (KRW, synthetic coefficients). `gap` is reported only for "
        "CP-SAT and refers to the solver's own objective. Runtimes are hardware-dependent.",
        "",
        "| instance | problem | algorithm | runs | infeasible | best | mean | std | mean late (min) | "
        "mean runtime (s) | mean TTFF (s) | gap |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for s in sorted(summary, key=lambda x: (x["instance"], x["problem"], x["mean"] or 0)):
        lines.append(
            f"| {s['instance']} | {s['problem']} | {s['algorithm']} | {s['runs']} | {s['infeasible_rate']:.0%} | "
            f"{s['best']:,.0f} | {s['mean']:,.0f} | {s['std']:,.0f} | {s['mean_late_min']} | {s['mean_runtime_s']} | "
            f"{s['mean_ttff_s'] if s['mean_ttff_s'] is not None else '–'} | "
            f"{s['gap'] if s['gap'] is not None else '–'} |"
            if s["best"] is not None
            else f"| {s['instance']} | {s['problem']} | {s['algorithm']} | {s['runs']} | "
            f"{s['infeasible_rate']:.0%} | – | – | – | – | {s['mean_runtime_s']} | – | – |"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--suite", choices=list(SUITES), default="quick")
    p.add_argument("--out", default="../docs/experiments")
    p.add_argument("--limit-instances", type=int, default=None)
    a = p.parse_args()
    res = run_suite(a.suite, Path(a.out), a.limit_instances)
    print(f"done: {res['rows']} runs → {a.out}")


if __name__ == "__main__":
    main()
