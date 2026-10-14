"""Constructive VRPTW baselines.

* Time-oriented nearest neighbour (Solomon 1987 style): extend the current vehicle's route with the
  unit minimising 0.5·travel + 0.3·waiting + 0.2·urgency among on-time, capacity- and shift-feasible
  candidates; open the next vehicle when no extension is possible; leftovers are cheapest-inserted
  (soft windows) or explicitly unserved.
* Cheapest insertion: repeatedly insert the (unit, vehicle, position) with the smallest increase of
  route cost (fixed cost when a vehicle is first used + distance cost + priority-weighted lateness),
  keeping capacity, shift and (hard-mode) windows. Insertion costs are cached per route and only
  recomputed for the route that changed.
"""

from __future__ import annotations

from app.optimization.routing.units import Simulator, Unit


def _vehicles(sim: Simulator) -> list[str]:
    frozen = {fr.vehicle_id for fr in sim.ctx.snap.frozen_routes}
    vs = [v for v in sim.ctx.snap.vehicles if v.available and v.id not in frozen]
    return [v.id for v in sorted(vs, key=lambda v: (v.fixed_cost, -v.capacity_kg, v.id))]


def best_insertion(sim: Simulator, vid: str, seq: list[Unit], u: Unit, base_cost: float) -> tuple[float, int] | None:
    best: tuple[float, int] | None = None
    for pos in range(len(seq) + 1):
        trial = seq[:pos] + [u] + seq[pos:]
        r = sim.run(vid, trial)
        if not r.ok:
            continue
        delta = r.cost - base_cost
        if best is None or delta < best[0] - 1e-9:
            best = (delta, pos)
    return best


def cheapest_insertion(
    sim: Simulator, units: list[Unit], routes: dict[str, list[Unit]] | None = None
) -> tuple[dict[str, list[Unit]], list[Unit]]:
    vids = _vehicles(sim)
    routes = routes or {v: [] for v in vids}
    for v in vids:
        routes.setdefault(v, [])
    base = {v: sim.run(v, routes[v]).cost for v in vids}
    pending = sorted(units, key=lambda u: (u.tw_end, u.id))
    cache: dict[str, dict[str, tuple[float, int] | None]] = {
        u.id: {v: best_insertion(sim, v, routes[v], u, base[v]) for v in vids} for u in pending
    }
    unrouted: list[Unit] = []
    while pending:
        choice = None
        for u in pending:
            for v in vids:
                c = cache[u.id][v]
                if c is not None and (choice is None or (c[0], u.id, v) < (choice[0], choice[1].id, choice[2])):
                    choice = (c[0], u, v, c[1])
        if choice is None:
            unrouted.extend(pending)
            break
        _, u, v, pos = choice
        routes[v].insert(pos, u)
        pending.remove(u)
        base[v] = sim.run(v, routes[v]).cost
        for w in pending:
            cache[w.id][v] = best_insertion(sim, v, routes[v], w, base[v])
    return routes, unrouted


def nearest_neighbour(sim: Simulator, units: list[Unit]) -> tuple[dict[str, list[Unit]], list[Unit]]:
    vids = _vehicles(sim)
    left = sorted(units, key=lambda u: u.id)
    routes: dict[str, list[Unit]] = {v: [] for v in vids}
    T = sim.T
    for v in vids:
        seq: list[Unit] = []
        while left:
            cur = sim.run(v, seq) if seq else None
            t = cur.ret - (T[seq[-1].loc][sim.depot] if seq and sim.ret_depot else 0) if cur else None
            prev = seq[-1].loc if seq else sim.depot
            best = None
            for u in left:
                trial = sim.run(v, seq + [u])
                if not trial.ok or trial.late_min > (cur.late_min if cur else 0):
                    continue  # NN only extends on-time
                ready_t = t if t is not None else sim.departure(v, [u])
                arr = ready_t + T[prev][u.loc]
                wait = max(0, u.tw_start - arr)
                urg = u.tw_end - arr
                score = 0.5 * T[prev][u.loc] + 0.3 * wait + 0.2 * urg
                if best is None or (score, u.id) < (best[0], best[1].id):
                    best = (score, u)
            if best is None:
                break
            seq.append(best[1])
            left.remove(best[1])
        routes[v] = seq
        if not left:
            break
    if left:  # leftovers: cheapest insertion (may be late in soft mode) or unserved
        routes, left = cheapest_insertion(sim, left, routes)
    return routes, left
