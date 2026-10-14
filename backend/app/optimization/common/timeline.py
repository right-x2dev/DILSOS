"""Unit-capacity resource timelines used by constructive heuristics (serial schedule generation)."""

from __future__ import annotations

import bisect
from collections.abc import Iterable

from app.optimization.common.contracts import Interval, ResourceRequirement


class Timeline:
    __slots__ = ("windows", "busy_s", "busy_e", "busy_min")

    def __init__(self, windows: Iterable[Interval]):
        self.windows = sorted((w.start, w.end) for w in windows if w.end > w.start)
        self.busy_s: list[int] = []
        self.busy_e: list[int] = []
        self.busy_min = 0

    def earliest_fit(self, est: int, dur: int) -> int | None:
        """Earliest start >= est such that [s, s+dur) lies in one window and overlaps no busy interval."""
        for ws, we in self.windows:
            if we - dur < est:
                continue
            t = max(est, ws)
            while t + dur <= we:
                # first busy interval ending after t
                i = bisect.bisect_right(self.busy_e, t)
                if i < len(self.busy_s) and self.busy_s[i] < t + dur:
                    t = self.busy_e[i]
                    continue
                return t
        return None

    def is_free(self, s: int, e: int) -> bool:
        return self.earliest_fit(s, e - s) == s

    def reserve(self, s: int, e: int) -> None:
        i = bisect.bisect_left(self.busy_s, s)
        self.busy_s.insert(i, s)
        self.busy_e.insert(i, e)
        self.busy_min += e - s

    def release(self, s: int, e: int) -> None:
        i = bisect.bisect_left(self.busy_s, s)
        while i < len(self.busy_s) and self.busy_s[i] == s:
            if self.busy_e[i] == e:
                del self.busy_s[i]
                del self.busy_e[i]
                self.busy_min -= e - s
                return
            i += 1
        raise KeyError((s, e))


def place_multi(
    timelines: dict[str, Timeline],
    requirements: list[ResourceRequirement],
    est: int,
    dur: int,
    tie_cost: dict[str, float] | None = None,
) -> tuple[int, dict[str, str]] | None:
    """Earliest common start where one eligible resource per requirement is free for ``dur``.

    Deterministic tie-break among free resources: (tie_cost, busy minutes, id).
    Returns (start, {kind: resource_id}) or None if impossible within availability windows.
    """
    t = est
    for _ in range(10_000):
        best_t: int | None = None
        for req in requirements:
            fits = [timelines[r].earliest_fit(t, dur) for r in req.eligible_ids]
            cand = [f for f in fits if f is not None]
            if not cand:
                return None
            m = min(cand)
            best_t = m if best_t is None else max(best_t, m)
        assert best_t is not None
        chosen: dict[str, str] = {}
        ok = True
        for req in requirements:
            free = [r for r in req.eligible_ids if timelines[r].earliest_fit(best_t, dur) == best_t]
            free = [r for r in free if r not in chosen.values()]
            if not free:
                ok = False
                break
            free.sort(key=lambda r: ((tie_cost or {}).get(r, 0.0), timelines[r].busy_min, r))
            chosen[req.kind] = free[0]
        if ok:
            return best_t, chosen
        t = best_t + 1 if best_t == t else best_t
    return None
