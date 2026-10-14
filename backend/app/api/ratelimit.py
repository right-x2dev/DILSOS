"""Per-user sliding-window rate limit for expensive mutations (run enqueue, experiments, imports).

In-process and best-effort (protects a single API instance from accidental floods); it is NOT a
queue and holds no business state. Behind several replicas use a shared limiter (e.g. Redis).
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from app.api.errors import ApiError
from app.core.config import get_settings

_lock = threading.Lock()
_hits: dict[tuple[int, str], deque[float]] = defaultdict(deque)


def check_rate(user_id: int, bucket: str, limit: int | None = None, window_s: float = 60.0) -> None:
    lim = limit if limit is not None else get_settings().rate_limit_per_minute
    if lim <= 0:
        return
    now = time.monotonic()
    with _lock:
        q = _hits[(user_id, bucket)]
        while q and now - q[0] > window_s:
            q.popleft()
        if len(q) >= lim:
            retry = max(1, int(window_s - (now - q[0])))
            raise ApiError(
                429,
                "rate_limited",
                f"too many {bucket} requests; retry in {retry}s",
                {"limit_per_minute": lim, "retry_after_s": retry},
            )
        q.append(now)


def reset() -> None:
    with _lock:
        _hits.clear()
