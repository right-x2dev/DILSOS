"""Import every model module so Base.metadata is complete (Alembic autogenerate, create_all in tests)."""

from app.db.models.user import AuditLog, User

__all__ = ["AuditLog", "User"]
