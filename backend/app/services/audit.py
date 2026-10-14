from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.logging import request_id_var
from app.db.models import AuditLog


def audit(
    db: Session,
    user_id: int | None,
    action: str,
    entity_type: str,
    entity_id: str | None = None,
    before_ref: str | None = None,
    after_ref: str | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    """Append an audit row inside the caller's transaction (caller commits)."""
    db.add(
        AuditLog(
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            before_ref=before_ref,
            after_ref=after_ref,
            detail=detail,
            request_id=request_id_var.get(),
        )
    )
