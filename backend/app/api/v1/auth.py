from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.api.errors import ApiError
from app.core.config import get_settings
from app.core.security import create_access_token, verify_password
from app.db.models import User
from app.services.audit import audit

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=256)


class UserOut(BaseModel):
    id: int
    email: str
    display_name: str
    role: str
    is_demo: bool


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut
    environment: str


def _user_out(u: User) -> UserOut:
    return UserOut(id=u.id, email=u.email, display_name=u.display_name, role=u.role, is_demo=u.is_demo)


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, db: DbSession) -> LoginResponse:
    s = get_settings()
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if user is None or not user.is_active or not verify_password(body.password, user.password_hash):
        raise ApiError(401, "invalid_credentials", "Invalid email or password")
    if user.is_demo and s.is_production:
        raise ApiError(403, "demo_disabled", "Demo login is disabled in production")
    audit(db, user.id, "login", "user", str(user.id))
    db.commit()
    return LoginResponse(
        access_token=create_access_token(str(user.id), user.role),
        user=_user_out(user),
        environment=s.app_env,
    )


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser) -> UserOut:
    return _user_out(user)
