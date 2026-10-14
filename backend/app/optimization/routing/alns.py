"""Adaptive Large Neighbourhood Search for VRPTW (Ropke & Pisinger style, simplified).

Destroy: random, worst (largest saving), related/Shaw (distance + window similarity), route removal.
Repair:  greedy cheapest insertion, regret-2 insertion — both only insert at positions that keep the
         route hard-feasible (capacity, shift/horizon, hard windows), so every state is feasible;
         units that cannot be inserted stay explicitly unrouted (unserved penalty).
Adaptive weights per segment (σ = 33 new best / 9 improved / 13 accepted worse, reaction 0.2),
simulated-annealing acceptance (T0 accepts +5 % with p = 0.5, cooled to ~0 over the budget).
Objective = Σ route cost (fixed + distance + priority-weighted lateness) + Σ unrouted penalty — the
same terms as the shared evaluator.  Seeded ``random.Random``; ``max_iterations`` gives
hardware-independent reproducible runs.
"""

from __future__ import annotations

import math
import random
import time

from app.optimization.common.contracts import CancellationToken
from app.optimization.routing.baseline import _vehicles, best_insertion
from app.optimization.routing.units import Simulator, Unit

Routes = dict[str, list[Unit]]


class _State:
    def __init__(self, sim: Simulator, routes: Routes, unrouted: list[Unit]):
        self.sim = sim
        self.routes = {v: list(s) for v, s in routes.items()}
        self.unrouted = list(unrouted)
        self.route_cost = {v: sim.run(v, s).cost for v, s in self.routes.items()}

    def copy(self) -> _State:
        st = _State.__new__(_State)
        st.sim = self.sim
        st.routes = {v: list(s) for v, s in self.routes.items()}
        st.unrouted = list(self.unrouted)
        st.route_cost = dict(self.route_cost)
        return st

    def penalty(self, u: Unit) -> float:
        return self.sim.ctx.snap.weights.unserved_penalty * u.prio

    def cost(self) -> float:
        return sum(self.route_cost.values()) + sum(self.penalty(u) for u in self.unrouted)

    def refresh(self, v: str) -> None:
        self.route_cost[v] = self.sim.run(v, self.routes[v]).cost

    def remove(self, u: Unit) -> None:
        for v, seq in self.routes.items():
            for i, x in enumerate(seq):
                if x.id == u.id:
                    del seq[i]
                    self.refresh(v)
                    self.unrouted.append(u)
                    return


# ---------------- destroy ----------------
def _routed(st: _State) -> list[Unit]:
    return [u for seq in st.routes.values() for u in seq]


def d_random(st: _State, q: int, rng: random.Random) -> None:
    for u in rng.sample(_routed(st), min(q, len(_routed(st)))):
        st.remove(u)


def d_worst(st: _State, q: int, rng: random.Random) -> None:
    for _ in range(q):
        cand = []
        for v, seq in st.routes.items():
            for i, u in enumerate(seq):
                saving = st.route_cost[v] - st.sim.run(v, seq[:i] + seq[i + 1 :]).cost
                cand.append((saving, u.id, u))
        if not cand:
            return
        cand.sort(key=lambda x: (-x[0], x[1]))
        k = min(len(cand) - 1, int(len(cand) * rng.random() ** 3))  # randomised worst (p = 3)
        st.remove(cand[k][2])


def d_related(st: _State, q: int, rng: random.Random) -> None:
    routed = _routed(st)
    if not routed:
        return
    seed = rng.choice(routed)
    T = st.sim.T

    def rel(u: Unit) -> float:
        return T[seed.loc][u.loc] + 0.5 * abs(u.tw_start - seed.tw_start) + 0.5 * abs(u.tw_end - seed.tw_end)

    for u in sorted(routed, key=lambda u: (rel(u), u.id))[:q]:
        st.remove(u)


def d_route(st: _State, q: int, rng: random.Random) -> None:
    used = sorted(v for v, s in st.routes.items() if s)
    if not used:
        return
    v = rng.choice(used)
    for u in list(st.routes[v]):
        st.remove(u)


DESTROY = {"random": d_random, "worst": d_worst, "related": d_related, "route": d_route}


# ---------------- repair ----------------
def _repair(st: _State, regret: bool) -> None:
    sim = st.sim
    vids = sorted(st.routes)
    pending = sorted(st.unrouted, key=lambda u: u.id)
    st.unrouted = []
    cache = {u.id: {v: best_insertion(sim, v, st.routes[v], u, st.route_cost[v]) for v in vids} for u in pending}
    while pending:
        pick = None
        for u in pending:
            opts = sorted((c[0], v, c[1]) for v, c in cache[u.id].items() if c is not None)
            if not opts:
                continue
            if regret:
                second = opts[1][0] if len(opts) > 1 else st.penalty(u)
                key = (-(second - opts[0][0]), opts[0][0], u.id)
            else:
                key = (opts[0][0], 0.0, u.id)
            if pick is None or key < pick[0]:
                pick = (key, u, opts[0][1], opts[0][2])
        if pick is None:
            st.unrouted.extend(pending)
            return
        _, u, v, pos = pick
        st.routes[v].insert(pos, u)
        st.refresh(v)
        pending.remove(u)
        for w in pending:
            cache[w.id][v] = best_insertion(sim, v, st.routes[v], w, st.route_cost[v])


REPAIR = {"greedy": lambda st: _repair(st, False), "regret2": lambda st: _repair(st, True)}


def alns_search(
    sim: Simulator,
    routes: Routes,
    unrouted: list[Unit],
    time_limit_s: float,
    seed: int,
    cancel: CancellationToken | None = None,
    max_iterations: int = 100_000,
) -> tuple[Routes, list[Unit], dict]:
    t0 = time.perf_counter()
    rng = random.Random(seed)
    for v in _vehicles(sim):
        routes.setdefault(v, [])
    cur = _State(sim, routes, unrouted)
    best = cur.copy()
    c_cur = c_best = cur.cost()
    start_cost = c_cur
    n = max(1, len(_routed(cur)) + len(cur.unrouted))
    w_d = {k: 1.0 for k in DESTROY}
    w_r = {k: 1.0 for k in REPAIR}
    sc_d = {k: 0.0 for k in DESTROY}
    sc_r = {k: 0.0 for k in REPAIR}
    use_d = {k: 0 for k in DESTROY}
    use_r = {k: 0 for k in REPAIR}
    temp0 = -0.05 * max(1.0, c_cur) / math.log(0.5)
    it = 0
    trace = [(0, round(c_best, 2))]
    while it < max_iterations and time.perf_counter() - t0 < time_limit_s:
        if cancel is not None and cancel.cancelled:
            break
        it += 1
        frac = min(1.0, (time.perf_counter() - t0) / max(time_limit_s, 1e-9), it / max_iterations)
        temp = temp0 * (1 - frac) + 1e-6
        dk = rng.choices(list(w_d), weights=list(w_d.values()))[0]
        rk = rng.choices(list(w_r), weights=list(w_r.values()))[0]
        q = max(1, min(15, int(n * rng.uniform(0.1, 0.3))))
        cand = cur.copy()
        DESTROY[dk](cand, q, rng)
        REPAIR[rk](cand)
        c = cand.cost()
        score = 0.0
        if c < c_best - 1e-6:
            best, c_best, score = cand.copy(), c, 33.0
            trace.append((it, round(c_best, 2)))
        if c < c_cur - 1e-6:
            cur, c_cur = cand, c
            score = max(score, 9.0)
        elif rng.random() < math.exp(-(c - c_cur) / temp):
            cur, c_cur = cand, c
            score = max(score, 13.0)
        sc_d[dk] += score
        sc_r[rk] += score
        use_d[dk] += 1
        use_r[rk] += 1
        if it % 25 == 0:  # segment end: adapt weights
            for w, sc, us in ((w_d, sc_d, use_d), (w_r, sc_r, use_r)):
                for k in w:
                    if us[k]:
                        w[k] = max(0.05, 0.8 * w[k] + 0.2 * sc[k] / us[k])
                    sc[k], us[k] = 0.0, 0
    meta = {
        "alns_iterations": it,
        "alns_start_cost": round(start_cost, 2),
        "alns_best_cost": round(c_best, 2),
        "alns_weights_destroy": {k: round(v, 3) for k, v in w_d.items()},
        "alns_weights_repair": {k: round(v, 3) for k, v in w_r.items()},
        "alns_convergence": trace[-50:],
        "alns_wall_s": round(time.perf_counter() - t0, 3),
        "optimality": "not proven (metaheuristic)",
    }
    return best.routes, best.unrouted, meta
