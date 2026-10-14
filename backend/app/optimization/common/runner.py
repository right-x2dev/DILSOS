"""Run one algorithm end-to-end: solve → shared evaluation → independent validation.

The returned result is *publishable as feasible* only if ``result.validation.is_feasible`` and the
solver status is FEASIBLE / OPTIMAL / TIME_LIMIT-with-incumbent.
"""

from __future__ import annotations

import logging
import time
import traceback

from app.optimization.common import registry
from app.optimization.common.contracts import (
    CancellationToken,
    ScenarioSnapshot,
    ScheduleResult,
    SolveConfig,
)
from app.optimization.common.objectives import evaluate
from app.optimization.common.validator import validate_schedule

log = logging.getLogger("dilsos.optimizer")


class AlgorithmNotSupported(ValueError):
    pass


def run_algorithm(
    snap: ScenarioSnapshot,
    algorithm: str,
    config: SolveConfig,
    run_id: str = "",
    cancel: CancellationToken | None = None,
) -> ScheduleResult:
    info = registry.get(algorithm)
    if config.problem_type not in info.problem_types:
        raise AlgorithmNotSupported(f"{algorithm} does not support problem type {config.problem_type}")
    if not info.available:
        raise AlgorithmNotSupported(f"{algorithm} requires unavailable packages: {info.requires}")
    t0 = time.perf_counter()
    try:
        result = info.factory().solve(snap, config, cancel)
    except Exception as e:  # noqa: BLE001 — solver errors become an ERROR result, never a crash
        log.exception("solver error", extra={"algorithm": algorithm, "run_id": run_id})
        result = ScheduleResult(
            run_id=run_id,
            algorithm=algorithm,
            problem_type=config.problem_type,
            status="ERROR",
            assignments=[],
            routes=[],
            unserved_order_ids=[],
            seed=config.seed,
            solver_metadata={"error": f"{type(e).__name__}: {e}", "traceback": traceback.format_exc(limit=5)},
        )
    result.run_id = run_id
    result.problem_type = config.problem_type
    result.runtime_ms = int((time.perf_counter() - t0) * 1000)
    result.seed = config.seed
    if result.status != "ERROR":
        result.metrics = evaluate(snap, result)
        result.validation = validate_schedule(snap, result)
    return result


def is_publishable(result: ScheduleResult) -> bool:
    if result.validation is None or not result.validation.is_feasible:
        return False
    if result.status in ("FEASIBLE", "OPTIMAL"):
        return True
    md = result.solver_metadata
    # TIME_LIMIT: publish the solver incumbent, or a documented validated fallback (flagged in metadata)
    return result.status == "TIME_LIMIT" and bool(md.get("has_incumbent", True) or md.get("fallback_used"))
