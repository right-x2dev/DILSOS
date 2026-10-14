from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession
from app.db import models as m
from app.schemas.api import Page

router = APIRouter(prefix="/audit-logs", tags=["audit"])


class AuditOut(BaseModel):
    id: int
    user_email: str | None
    action: str
    entity_type: str
    entity_id: str | None
    before_ref: str | None
    after_ref: str | None
    detail: dict[str, Any] | None
    request_id: str | None
    created_at: datetime


@router.get("", response_model=Page[AuditOut])
def list_audit(
    db: DbSession,
    _: CurrentUser,
    entity_type: str | None = None,
    entity_id: str | None = None,
    action: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> Page[AuditOut]:
    stmt = select(m.AuditLog)
    if entity_type:
        stmt = stmt.where(m.AuditLog.entity_type == entity_type)
    if entity_id:
        stmt = stmt.where(m.AuditLog.entity_id == entity_id)
    if action:
        stmt = stmt.where(m.AuditLog.action == action)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = list(db.scalars(stmt.order_by(m.AuditLog.id.desc()).limit(limit).offset(offset)))
    users = {u.id: u.email for u in db.scalars(select(m.User).where(m.User.id.in_({r.user_id for r in rows})))}
    return Page(
        items=[
            AuditOut(
                id=r.id,
                user_email=users.get(r.user_id) if r.user_id else None,
                action=r.action,
                entity_type=r.entity_type,
                entity_id=r.entity_id,
                before_ref=r.before_ref,
                after_ref=r.after_ref,
                detail=r.detail,
                request_id=r.request_id,
                created_at=r.created_at,
            )
            for r in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )
