"""Persistent DB-polling worker (TASK_BACKEND=db) — no Redis required.

    python -m app.tasks.db_worker [--once] [--poll 1.0]

Claims QUEUED runs atomically (conditional UPDATE), so several workers may run concurrently.
"""

from __future__ import annotations

import argparse
import logging
import signal
import time

from app.core.logging import configure_logging
from app.db.session import get_sessionmaker
from app.services.runs import claim_next, execute_run, recover_stale_runs, worker_identity

log = logging.getLogger("dilsos.worker")
_stop = False


def _sig(*_: object) -> None:
    global _stop
    _stop = True


def run_forever(poll_s: float = 1.0, once: bool = False) -> int:
    configure_logging()
    wid = worker_identity()
    S = get_sessionmaker()
    with S() as db:
        n = recover_stale_runs(db)
        if n:
            log.warning(f"marked {n} stale RUNNING runs as FAILED")
    processed = 0
    log.info(f"db worker {wid} started")
    while not _stop:
        with S() as db:
            rid = claim_next(db, wid)
        if rid is None:
            if once:
                break
            time.sleep(poll_s)
            continue
        status = execute_run(rid, worker_id=wid)
        processed += 1
        log.info("run finished", extra={"run_id": rid, "status": status})
    return processed


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--once", action="store_true", help="drain the queue and exit")
    p.add_argument("--poll", type=float, default=1.0)
    a = p.parse_args()
    signal.signal(signal.SIGINT, _sig)
    signal.signal(signal.SIGTERM, _sig)
    run_forever(a.poll, a.once)


if __name__ == "__main__":
    main()
