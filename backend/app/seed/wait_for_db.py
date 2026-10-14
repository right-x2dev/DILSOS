"""Block until the configured database accepts connections (container start-up)."""

from __future__ import annotations

import sys
import time

from sqlalchemy import text

from app.db.session import get_engine


def main(timeout_s: int = 90) -> None:
    deadline = time.monotonic() + timeout_s
    last: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with get_engine().connect() as c:
                c.execute(text("SELECT 1"))
            print("database is reachable")
            return
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2)
    print(f"database not reachable after {timeout_s}s: {type(last).__name__}", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
