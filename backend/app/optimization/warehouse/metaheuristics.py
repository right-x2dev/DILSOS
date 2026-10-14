"""Warehouse metaheuristics over a feasible-by-construction encoding.

Encoding: a permutation of servable orders. Decoder: serial SGS with task key
(position of order, PICK before PACK) → every candidate respects precedence, eligibility, shifts,
downtime and unit capacity. Fitness: the shared evaluator's total cost on the warehouse scope.
Every *new incumbent* is additionally checked by the independent validator before acceptance
(an invalid incumbent is rejected and counted in metadata — it should never happen).

* SA   — swap / insertion moves, geometric cooling, Metropolis acceptance.
* Tabu — best of a sampled neighbourhood of swaps, tabu on order pairs, aspiration by best cost.
* GA   — population seeded with EDD/FIFO/SPT + perturbations, tournament selection, order
         crossover (OX), swap mutation, elitism.
Budgets: wall-clock limit and ``max_evaluations`` (use the latter for hardware-independent,
reproducible benchmarks). All randomness comes from ``random.Random(seed)``.
"""

from __future__ import annotations

import math
import random
import time
from collections.abc import Callable

from app.optimization.common.contracts import (
    CancellationToken,
    ScenarioSnapshot,
    ScheduleResult,
    SolveConfig,
)
from app.optimization.common.objectives import evaluate
from app.optimization.common.preprocess import Prepared, prepare, unserved_list
from app.optimization.common.validator import validate_schedule
from app.optimization.warehouse.heuristics import RULES
from app.optimization.warehouse.sgs import SgsResult, decode

_RANK = {"PICK": 0, "PACK": 1}


class _Problem:
    def __init__(self, snap: ScenarioSnapshot, cancel: CancellationToken | None, time_limit: float, max_evals: int):
        self.snap = snap
        self.prep: Prepared = prepare(snap, routing=False)
        self.cancel = cancel
        self.deadline = time.perf_counter() + time_limit
        self.max_evals = max_evals
        self.evals = 0
        self.rejected_invalid = 0
        self.t0 = time.perf_counter()
        self.trace: list[tuple[int, float]] = []  # (evaluation, best cost)
        self.best: tuple[float, list[str], SgsResult] | None = None
        self.first_feasible_s: float | None = None

    def budget_left(self) -> bool:
        if self.cancel is not None and self.cancel.cancelled:
            return False
        return self.evals < self.max_evals and time.perf_counter() < self.deadline

    def decode(self, perm: list[str]) -> SgsResult:
        pos = {o: i for i, o in enumerate(perm)}
        return decode(self.snap, self.prep, lambda t: (pos[t.order_id], _RANK[t.type], t.id))

    def result_of(self, sgs: SgsResult, name: str) -> ScheduleResult:
        reasons = {**self.prep.unserved, **sgs.unserved}
        return ScheduleResult(
            run_id="",
            algorithm=name,
            problem_type="warehouse",
            status="FEASIBLE",
            assignments=sgs.assignments,
            routes=[],
            unserved_order_ids=sorted(reasons),
            unserved=unserved_list(self.snap, reasons),
        )

    def cost(self, perm: list[str]) -> float:
        self.evals += 1
        sgs = self.decode(perm)
        res = self.result_of(sgs, "eval")
        c = evaluate(self.snap, res).cost.total_cost
        if self.best is None or c < self.best[0] - 1e-9:
            if validate_schedule(self.snap, res).is_feasible:
                if self.first_feasible_s is None:
                    self.first_feasible_s = time.perf_counter() - self.t0
                self.best = (c, list(perm), sgs)
                self.trace.append((self.evals, round(c, 2)))
            else:
                self.rejected_invalid += 1
        return c

    def seeds(self) -> list[list[str]]:
        """Initial permutations from the EDD / FIFO / SPT dispatch priorities (EDD first)."""
        out = []
        servable = set(self.prep.servable)
        for rule in ("edd", "fifo", "spt"):
            key = RULES[rule](self.snap)
            tasks = sorted((t for t in self.snap.tasks if t.order_id in servable), key=key)
            seen: dict[str, None] = {}
            for t in tasks:
                seen.setdefault(t.order_id, None)
            out.append(list(seen))
        return out


def _swap(rng: random.Random, p: list[str]) -> tuple[list[str], tuple[str, str]]:
    q = list(p)
    i, j = rng.sample(range(len(q)), 2)
    q[i], q[j] = q[j], q[i]
    return q, (min(q[i], q[j]), max(q[i], q[j]))


def _insert(rng: random.Random, p: list[str]) -> list[str]:
    q = list(p)
    i, j = rng.sample(range(len(q)), 2)
    x = q.pop(i)
    q.insert(j, x)
    return q


def simulated_annealing(pb: _Problem, rng: random.Random, params: dict) -> dict:
    cur = pb.seeds()[0]
    c_cur = pb.cost(cur)
    t0 = float(params.get("t0_frac", 0.02)) * max(1.0, c_cur)
    alpha = float(params.get("alpha", 0.995))
    temp = t0
    accepted = 0
    while pb.budget_left() and len(cur) > 1:
        cand = _swap(rng, cur)[0] if rng.random() < 0.5 else _insert(rng, cur)
        c = pb.cost(cand)
        if c <= c_cur or rng.random() < math.exp(-(c - c_cur) / max(temp, 1e-9)):
            cur, c_cur = cand, c
            accepted += 1
        temp = max(temp * alpha, 1e-6)
    return {"t0": round(t0, 2), "alpha": alpha, "final_temperature": round(temp, 4), "accepted_moves": accepted}


def tabu_search(pb: _Problem, rng: random.Random, params: dict) -> dict:
    cur = pb.seeds()[0]
    c_cur = pb.cost(cur)
    tenure = int(params.get("tenure", 7))
    sample = int(params.get("neighbourhood", 20))
    tabu: dict[tuple[str, str], int] = {}
    it = 0
    while pb.budget_left() and len(cur) > 1:
        it += 1
        best_move = None
        for _ in range(sample):
            if not pb.budget_left():
                break
            cand, mv = _swap(rng, cur)
            c = pb.cost(cand)
            is_tabu = tabu.get(mv, 0) > it
            aspiration = pb.best is not None and c < pb.best[0]
            if (not is_tabu or aspiration) and (best_move is None or c < best_move[0]):
                best_move = (c, cand, mv)
        if best_move is None:
            continue
        c_cur, cur, mv = best_move
        tabu[mv] = it + tenure
    return {"tenure": tenure, "neighbourhood": sample, "iterations": it}


def _ox(rng: random.Random, a: list[str], b: list[str]) -> list[str]:
    n = len(a)
    i, j = sorted(rng.sample(range(n), 2))
    child: list[str | None] = [None] * n
    child[i : j + 1] = a[i : j + 1]
    kept = set(a[i : j + 1])
    fill = [x for x in b if x not in kept]
    k = 0
    for idx in range(n):
        if child[idx] is None:
            child[idx] = fill[k]
            k += 1
    return [x for x in child if x is not None]


def _tournament(rng: random.Random, pop: list[list[str]], fit: list[float]) -> list[str]:
    a, b = rng.sample(range(len(pop)), 2)
    return pop[a] if fit[a] <= fit[b] else pop[b]


def genetic_algorithm(pb: _Problem, rng: random.Random, params: dict) -> dict:
    size = int(params.get("population", 16))
    pm = float(params.get("mutation", 0.3))
    seeds = pb.seeds()
    pop = [list(s) for s in seeds]
    while len(pop) < size:
        base = list(rng.choice(seeds))
        for _ in range(max(1, len(base) // 5)):
            if len(base) > 1:
                base = _swap(rng, base)[0]
        pop.append(base)
    fit = [pb.cost(p) for p in pop]
    gens = 0
    while pb.budget_left() and len(pop[0]) > 1:
        gens += 1
        elite = min(range(len(pop)), key=lambda i: fit[i])
        new_pop, new_fit = [pop[elite]], [fit[elite]]
        while len(new_pop) < size and pb.budget_left():
            child = _ox(rng, _tournament(rng, pop, fit), _tournament(rng, pop, fit))
            if rng.random() < pm:
                child = _swap(rng, child)[0]
            new_pop.append(child)
            new_fit.append(pb.cost(child))
        pop, fit = new_pop, new_fit
    return {"population": size, "mutation": pm, "generations": gens}


Search = Callable[[_Problem, random.Random, dict], dict]
SEARCHES: dict[str, Search] = {"sa": simulated_annealing, "tabu": tabu_search, "ga": genetic_algorithm}


class WarehouseMetaheuristic:
    kind = "metaheuristic"
    supported_problem_types = {"warehouse"}

    def __init__(self, method: str):
        self.method = method
        self.name = f"warehouse_{method}"
        self.description = {
            "sa": "모의 담금질 (주문 순열 + SGS 디코더)",
            "tabu": "타부 탐색 (교환 이웃, 타부 리스트, 열망 기준)",
            "ga": "유전 알고리즘 (OX 교차, 교환 변이, 엘리트 보존)",
        }[method]

    def solve(
        self, instance: ScenarioSnapshot, config: SolveConfig, cancel: CancellationToken | None = None
    ) -> ScheduleResult:
        t0 = time.perf_counter()
        max_evals = int(config.params.get("max_evaluations", 3000))
        pb = _Problem(instance, cancel, config.time_limit_s, max_evals)
        rng = random.Random(config.seed)
        if len(pb.prep.servable) <= 1:
            pb.cost(list(pb.prep.servable))
            info: dict = {"note": "≤1 servable order; nothing to search"}
        else:
            info = SEARCHES[self.method](pb, rng, config.params)
        assert pb.best is not None
        best_cost, _perm, sgs = pb.best
        res = pb.result_of(sgs, self.name)
        res.runtime_ms = int((time.perf_counter() - t0) * 1000)
        res.seed = config.seed
        res.solver_metadata = {
            "method": self.method,
            "encoding": "order permutation → serial SGS (feasible by construction)",
            "evaluations": pb.evals,
            "max_evaluations": max_evals,
            "time_limit_s": config.time_limit_s,
            "stopped_by": "evaluations"
            if pb.evals >= max_evals
            else ("cancel" if cancel and cancel.cancelled else "time"),
            "best_cost": best_cost,
            "time_to_first_feasible_s": round(pb.first_feasible_s or 0.0, 4),
            "rejected_invalid_incumbents": pb.rejected_invalid,
            "convergence": pb.trace[-50:],
            "reproducible": "same seed + max_evaluations ⇒ identical result (time limit not binding)",
            **info,
        }
        return res
