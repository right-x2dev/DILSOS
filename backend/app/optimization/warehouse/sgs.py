"""Serial Schedule Generation Scheme (SGS) for the multi-resource warehouse RCPSP.

Given a priority key per task, repeatedly takes the highest-priority *eligible* task (all
predecessors placed) and inserts it at the earliest time where one eligible resource of every
requirement is free inside its availability windows (gap-filling insertion, no preemption).
Feasible by construction; an order whose task cannot fit inside the horizon becomes explicitly
unserved (``no_capacity_in_horizon``) and its already-placed tasks are rolled back.

Used by the dispatch rules (FIFO/EDD/SPT) and as the decoder for SA / Tabu / GA encodings.
"""

from __future__ import annotations

import heapq
from collections.abc import Callable
from dataclasses import dataclass, field

from app.optimization.common.contracts import ScenarioSnapshot, Task, TaskAssignment
from app.optimization.common.preprocess import Prepared
from app.optimization.common.timeline import Timeline, place_multi

TaskKey = Callable[[Task], tuple]


@dataclass
class SgsResult:
    assignments: list[TaskAssignment]
    unserved: dict[str, str] = field(default_factory=dict)
    timelines: dict[str, Timeline] = field(default_factory=dict)
    pack_end: dict[str, int] = field(default_factory=dict)  # order id -> completion of its last task


def build_timelines(snap: ScenarioSnapshot) -> dict[str, Timeline]:
    return {r.id: Timeline(r.available) for r in snap.resources}


def decode(
    snap: ScenarioSnapshot,
    prep: Prepared,
    key: TaskKey,
    release_override: dict[str, int] | None = None,
) -> SgsResult:
    tl = build_timelines(snap)
    tmap = snap.task_map()
    servable = set(prep.servable)
    frozen = {f.task_id: f for f in snap.frozen_assignments}
    assignments: list[TaskAssignment] = []
    end_of: dict[str, int] = {}
    unserved: dict[str, str] = {}

    # 1) frozen work is fixed on the timelines first (never moved)
    for f in snap.frozen_assignments:
        t = tmap.get(f.task_id)
        if t is None:
            continue
        for rid in f.resources.values():
            if rid in tl:
                tl[rid].reserve(f.start_min, f.end_min)
        end_of[t.id] = f.end_min
        assignments.append(
            TaskAssignment(
                task_id=t.id,
                task_type=t.type,
                order_ids=[t.order_id],
                resource_id=next(iter(f.resources.values())),
                resources=dict(f.resources),
                start_min=f.start_min,
                end_min=f.end_min,
                frozen=True,
            )
        )

    todo = [t for t in snap.tasks if t.order_id in servable and t.id not in frozen]
    succ: dict[str, list[str]] = {}
    indeg: dict[str, int] = {}
    todo_ids = {t.id for t in todo}
    for t in todo:
        preds = [p for p in t.predecessors if p in todo_ids]
        indeg[t.id] = len(preds)
        for p in preds:
            succ.setdefault(p, []).append(t.id)
    heap = [(key(t), t.id) for t in todo if indeg[t.id] == 0]
    heapq.heapify(heap)
    cost = {r.id: r.hourly_cost for r in snap.resources}
    placed_by_order: dict[str, list[TaskAssignment]] = {}

    while heap:
        _, tid = heapq.heappop(heap)
        t = tmap[tid]
        if t.order_id in unserved:
            continue
        rel = (release_override or {}).get(t.id, t.release_min)
        est = max(rel, snap.current_time_min, *(end_of.get(p, 0) for p in t.predecessors))
        placed = place_multi(tl, t.requirements, est, t.duration_min, tie_cost=cost)
        if placed is None:
            unserved[t.order_id] = "no_capacity_in_horizon"
            for a in placed_by_order.pop(t.order_id, []):
                for rid in a.resources.values():
                    tl[rid].release(a.start_min, a.end_min)
                assignments.remove(a)
            continue
        s, chosen = placed
        e = s + t.duration_min
        for rid in chosen.values():
            tl[rid].reserve(s, e)
        primary = chosen[t.requirements[0].kind]
        a = TaskAssignment(
            task_id=t.id,
            task_type=t.type,
            order_ids=[t.order_id],
            resource_id=primary,
            resources=chosen,
            start_min=s,
            end_min=e,
        )
        assignments.append(a)
        placed_by_order.setdefault(t.order_id, []).append(a)
        end_of[t.id] = e
        for nxt in succ.get(t.id, []):
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                heapq.heappush(heap, (key(tmap[nxt]), nxt))

    pack_end: dict[str, int] = {}
    for a in assignments:
        oid = a.order_ids[0]
        if oid not in unserved:
            pack_end[oid] = max(pack_end.get(oid, 0), a.end_min)
    # executed/committed (frozen) work is history and is kept even if its order ends up unserved
    assignments = [a for a in assignments if a.frozen or a.order_ids[0] not in unserved]
    assignments.sort(key=lambda a: (a.start_min, a.task_id))
    return SgsResult(assignments=assignments, unserved=unserved, timelines=tl, pack_end=pack_end)
