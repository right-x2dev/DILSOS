"""Rescheduling algorithms, driver and rolling-horizon event handling.

``RescheduleAlgorithm`` (registered as reschedule_keep / reschedule_partial / reschedule_full) runs on
a *policy snapshot* produced by ``build_policy_snapshot`` — everything it needs (frozen history,
baseline, KEEP freeze sets, current time) is inside the snapshot, so a queued run is reproducible
from the stored snapshot alone.

* KEEP    → fast constructive repair (minimal change) on the KEEP freeze.
* PARTIAL / FULL → the requested re-optimiser on the looser freeze; the KEEP plan (valid under the
  looser freeze because it freezes a superset) is evaluated as a candidate and kept if the
  re-optimised plan is not better on the shared objective (change penalties included).

``rolling_horizon`` processes a time-ordered event stream: each feasible new version becomes the
baseline for the next event; infeasible versions are never adopted.
"""

from __future__ import annotations

import time

from pydantic import BaseModel

from app.optimization.common.contracts import (
    CancellationToken,
    ScenarioSnapshot,
    ScheduleResult,
    SolveConfig,
)
from app.optimization.common.objectives import evaluate
from app.optimization.common.runner import run_algorithm
from app.optimization.common.validator import validate_schedule
from app.optimization.rescheduling.events import DisruptionSpec
from app.optimization.rescheduling.policies import FreezePlan, Policy, build_policy_snapshot

SUPPORTED_BASE = {"warehouse", "integrated"}
KEEP_ALGORITHM = {"warehouse": "warehouse_edd", "integrated": "integrated_sequential"}
DEFAULT_REOPT = {"warehouse": "warehouse_cpsat", "integrated": "integrated_iterative"}


class RescheduleAlgorithm:
    kind = "decomposition"
    supported_problem_types = {"warehouse", "integrated"}

    def __init__(self, policy: Policy):
        self.policy = policy
        self.name = f"reschedule_{policy.lower()}"
        self.description = {
            "KEEP": "KEEP: 영향 없는 작업·경로 유지, 직접 영향만 최소 수리 (예외 명시)",
            "PARTIAL": "PARTIAL: 영향 범위(자원·의존성 폐포 + 미출발 경로)만 재최적화",
            "FULL": "FULL: 실행·확정 구간 외 전부 재최적화 (실행 이력 보존)",
        }[policy]

    def solve(
        self, instance: ScenarioSnapshot, config: SolveConfig, cancel: CancellationToken | None = None
    ) -> ScheduleResult:
        t0 = time.perf_counter()
        problem = config.problem_type
        if problem not in SUPPORTED_BASE:
            raise ValueError(f"rescheduling supports {sorted(SUPPORTED_BASE)}, not {problem}")
        keep_params = {"dock": "edd"} if problem == "integrated" else {}
        sub = SolveConfig(problem_type=problem, time_limit_s=config.time_limit_s, seed=config.seed)
        keep_snap = instance.model_copy(
            update={
                "frozen_assignments": instance.keep_frozen_assignments,
                "frozen_routes": instance.keep_frozen_routes,
            }
        )
        keep = run_algorithm(
            keep_snap, KEEP_ALGORITHM[problem], sub.model_copy(update={"params": keep_params}), cancel=cancel
        )
        keep.metrics = evaluate(instance, keep)
        keep.validation = validate_schedule(instance, keep)
        meta: dict = {
            "policy": self.policy,
            "keep_algorithm": KEEP_ALGORITHM[problem],
            "keep_cost": keep.metrics.cost.total_cost,
            "keep_feasible": keep.validation.is_feasible,
        }
        chosen = keep
        selection = "keep (minimal-change repair)"
        if self.policy != "KEEP":
            alg = str(config.params.get("reoptimizer") or DEFAULT_REOPT[problem])
            reo = run_algorithm(
                instance,
                alg,
                sub.model_copy(update={"params": dict(config.params.get("reoptimizer_params", {}))}),
                cancel=cancel,
            )
            ok = bool(reo.validation and reo.validation.is_feasible and reo.metrics)
            meta.update(
                reoptimizer=alg,
                reoptimizer_feasible=ok,
                reoptimizer_cost=reo.metrics.cost.total_cost if reo.metrics else None,
            )
            if ok and (not keep.validation.is_feasible or reo.metrics.cost.total_cost <= keep.metrics.cost.total_cost):  # type: ignore[union-attr]
                chosen, selection = reo, f"re-optimised by {alg}"
            else:
                selection = f"keep candidate (re-optimiser {alg} did not improve)"
        out = chosen.model_copy(deep=True)
        out.algorithm = self.name
        out.status = "FEASIBLE"  # rescheduled plans never claim optimality
        out.runtime_ms = int((time.perf_counter() - t0) * 1000)
        out.solver_metadata = {**meta, "selection": selection, "inner_metadata": chosen.solver_metadata}
        return out


def reschedule(
    snap: ScenarioSnapshot,
    base: ScheduleResult,
    ev: DisruptionSpec,
    policy: Policy,
    algorithm: str | None = None,
    time_limit_s: float = 10.0,
    seed: int = 0,
    freeze_window_min: int = 30,
) -> tuple[ScheduleResult, FreezePlan, ScenarioSnapshot]:
    if base.problem_type not in SUPPORTED_BASE:
        raise ValueError(f"rescheduling supports {sorted(SUPPORTED_BASE)} runs, not {base.problem_type}")
    new_snap, plan = build_policy_snapshot(snap, base, ev, policy, freeze_window_min)
    params = {"reoptimizer": algorithm} if algorithm else {}
    res = run_algorithm(
        new_snap,
        f"reschedule_{policy.lower()}",
        SolveConfig(
            problem_type=base.problem_type,
            time_limit_s=time_limit_s,
            seed=seed,  # type: ignore[arg-type]
            params=params,
        ),
    )
    res.solver_metadata["freeze_plan"] = plan.model_dump()
    return res, plan, new_snap


class HorizonStep(BaseModel):
    event: DisruptionSpec
    policy: Policy
    feasible: bool
    total_cost: float | None
    changed_tasks: int | None
    changed_routes: int | None
    exceptions: list[str]


def rolling_horizon(
    snap: ScenarioSnapshot,
    base: ScheduleResult,
    events: list[DisruptionSpec],
    policy: Policy,
    algorithm: str | None = None,
    time_limit_s: float = 5.0,
    seed: int = 0,
    freeze_window_min: int = 30,
) -> tuple[ScheduleResult, ScenarioSnapshot, list[HorizonStep]]:
    steps: list[HorizonStep] = []
    cur, cur_snap = base, snap
    for ev in sorted(events, key=lambda e: e.time_min):
        res, plan, new_snap = reschedule(cur_snap, cur, ev, policy, algorithm, time_limit_s, seed, freeze_window_min)
        ok = bool(res.validation and res.validation.is_feasible)
        steps.append(
            HorizonStep(
                event=ev,
                policy=policy,
                feasible=ok,
                total_cost=res.metrics.cost.total_cost if res.metrics else None,
                changed_tasks=res.metrics.changed_tasks if res.metrics else None,
                changed_routes=res.metrics.changed_routes if res.metrics else None,
                exceptions=plan.exceptions,
            )
        )
        if not ok:  # never adopt an invalid plan: keep the previous valid version
            continue
        cur, cur_snap = res, new_snap
    return cur, cur_snap, steps
