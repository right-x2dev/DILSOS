"""Use DOUBLE for coordinates and other float columns (MySQL FLOAT is 4-byte single precision).

Found by the first MySQL CI run: lat 37.509758 was stored as 37.5098, breaking the lossless
definition ⇄ DB ⇄ snapshot round trip. SQLite stores 8-byte REAL either way, so only MySQL is altered.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-14
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

COLUMNS = [
    ("facilities", "x_km", False),
    ("facilities", "y_km", False),
    ("facilities", "lat", True),
    ("facilities", "lon", True),
    ("customers", "x_km", False),
    ("customers", "y_km", False),
    ("customers", "lat", True),
    ("customers", "lon", True),
    ("schedule_runs", "time_limit_s", False),
    ("reschedule_runs", "stability_score", True),
]


def _alter(to_type, from_type) -> None:  # type: ignore[no-untyped-def]
    # SQLite REAL is already 8-byte; rebuilding parent tables there would fight FK enforcement on populated
    # databases, so only MySQL is altered (env.py ignores Float/Double differences on SQLite).
    if op.get_bind().dialect.name != "mysql":
        return
    for table, col, nullable in COLUMNS:
        op.alter_column(table, col, type_=to_type, existing_type=from_type, existing_nullable=nullable)


def upgrade() -> None:
    _alter(sa.Double(), sa.Float())


def downgrade() -> None:
    _alter(sa.Float(), sa.Double())
