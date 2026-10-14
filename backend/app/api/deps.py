from __future__ import annotations

from typing import Annotated

import jwt
from fastapi import Depends, Header
from sqlalchemy.orm import Session

from app.api.errors import ApiError
from app.core.security import decode_access_token
from app.db.models import User
from app.db.session import get_db

DbSession = Annotated[Session, Depends(get_db)]


def get_current_user(db: DbSession, authorization: str | None = Header(default=None)) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise ApiError(401, "unauthorized", "Missing bearer token")
    token = authorization.split(" ", 1)[1]
    try:
        claims = decode_access_token(token)
    except jwt.ExpiredSignatureError as e:
        raise ApiError(401, "token_expired", "Token expired") from e
    except jwt.PyJWTError as e:
        raise ApiError(401, "unauthorized", "Invalid token") from e
    user = db.get(User, int(claims["sub"]))
    if user is None or not user.is_active:
        raise ApiError(401, "unauthorized", "Unknown or inactive user")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_writer(user: CurrentUser) -> User:
    """Mutation endpoints: viewers are read-only."""
    if user.role not in ("admin", "planner"):
        raise ApiError(403, "forbidden", "Role does not permit modifications")
    return user


WriterUser = Annotated[User, Depends(require_writer)]
