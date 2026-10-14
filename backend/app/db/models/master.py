"""Master data: facility, customers, SKUs, inventory, orders, resources, calendars, travel matrices."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    Double,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UTCDateTime, utcnow
from app.db.models.user import PK

MONEY = Numeric(14, 2)


class Facility(Base):
    __tablename__ = "facilities"
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Seoul")
    x_km: Mapped[float] = mapped_column(Double, default=0.0)
    y_km: Mapped[float] = mapped_column(Double, default=0.0)
    lat: Mapped[float | None] = mapped_column(Double, nullable=True)
    lon: Mapped[float | None] = mapped_column(Double, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class Customer(Base):
    __tablename__ = "customers"
    __table_args__ = (UniqueConstraint("facility_id", "code", name="uq_customers_facility_code"),)
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    facility_id: Mapped[int] = mapped_column(ForeignKey("facilities.id", ondelete="RESTRICT"), index=True)
    code: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(120))
    x_km: Mapped[float] = mapped_column(Double)
    y_km: Mapped[float] = mapped_column(Double)
    lat: Mapped[float | None] = mapped_column(Double, nullable=True)
    lon: Mapped[float | None] = mapped_column(Double, nullable=True)
    service_min: Mapped[int] = mapped_column(Integer, default=8)
    tw_start_local_min: Mapped[int] = mapped_column(Integer)
    tw_end_local_min: Mapped[int] = mapped_column(Integer)


class Sku(Base):
    __tablename__ = "skus"
    __table_args__ = (UniqueConstraint("facility_id", "code", name="uq_skus_facility_code"),)
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    facility_id: Mapped[int] = mapped_column(ForeignKey("facilities.id", ondelete="RESTRICT"), index=True)
    code: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(120))
    zone: Mapped[str] = mapped_column(String(8), default="A")
    unit_weight_g: Mapped[int] = mapped_column(Integer)
    unit_volume_ml: Mapped[int] = mapped_column(Integer)
    pick_sec_per_unit: Mapped[int] = mapped_column(Integer, default=20)


class InventoryBalance(Base):
    __tablename__ = "inventory_balances"
    __table_args__ = (UniqueConstraint("facility_id", "sku_id", name="uq_inventory_facility_sku"),)
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    facility_id: Mapped[int] = mapped_column(ForeignKey("facilities.id", ondelete="RESTRICT"))
    sku_id: Mapped[int] = mapped_column(ForeignKey("skus.id", ondelete="RESTRICT"), index=True)
    on_hand: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("facility_id", "code", name="uq_orders_facility_code"),
        Index("ix_orders_facility_status", "facility_id", "status"),
        Index("ix_orders_due_at", "due_at"),
    )
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    facility_id: Mapped[int] = mapped_column(ForeignKey("facilities.id", ondelete="RESTRICT"))
    code: Mapped[str] = mapped_column(String(40))
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id", ondelete="RESTRICT"), index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    release_at: Mapped[datetime] = mapped_column(UTCDateTime())
    due_at: Mapped[datetime] = mapped_column(UTCDateTime())
    priority: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(16), default="OPEN")  # OPEN | CANCELLED | SHIPPED
    lines: Mapped[list[OrderLine]] = relationship(
        back_populates="order", cascade="all, delete-orphan", order_by="OrderLine.id"
    )


class OrderLine(Base):
    __tablename__ = "order_lines"
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    sku_id: Mapped[int] = mapped_column(ForeignKey("skus.id", ondelete="RESTRICT"))
    qty: Mapped[int] = mapped_column(Integer)
    order: Mapped[Order] = relationship(back_populates="lines")


class Worker(Base):
    __tablename__ = "workers"
    __table_args__ = (UniqueConstraint("facility_id", "code", name="uq_workers_facility_code"),)
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    facility_id: Mapped[int] = mapped_column(ForeignKey("facilities.id", ondelete="RESTRICT"), index=True)
    code: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(120))
    skills: Mapped[list] = mapped_column(JSON)  # bounded list of skill tags
    hourly_cost: Mapped[Decimal] = mapped_column(MONEY)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Equipment(Base):
    __tablename__ = "equipment"
    __table_args__ = (UniqueConstraint("facility_id", "code", name="uq_equipment_facility_code"),)
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    facility_id: Mapped[int] = mapped_column(ForeignKey("facilities.id", ondelete="RESTRICT"), index=True)
    code: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(32), default="forklift")
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class PackStation(Base):
    __tablename__ = "pack_stations"
    __table_args__ = (UniqueConstraint("facility_id", "code", name="uq_pack_stations_facility_code"),)
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    facility_id: Mapped[int] = mapped_column(ForeignKey("facilities.id", ondelete="RESTRICT"), index=True)
    code: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(120))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Dock(Base):
    __tablename__ = "docks"
    __table_args__ = (UniqueConstraint("facility_id", "code", name="uq_docks_facility_code"),)
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    facility_id: Mapped[int] = mapped_column(ForeignKey("facilities.id", ondelete="RESTRICT"), index=True)
    code: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(120))
    vehicle_classes: Mapped[list] = mapped_column(JSON)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Vehicle(Base):
    __tablename__ = "vehicles"
    __table_args__ = (
        UniqueConstraint("facility_id", "code", name="uq_vehicles_facility_code"),
        Index("ix_vehicles_facility_status", "facility_id", "status"),
    )
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    facility_id: Mapped[int] = mapped_column(ForeignKey("facilities.id", ondelete="RESTRICT"))
    code: Mapped[str] = mapped_column(String(32))
    vehicle_class: Mapped[str] = mapped_column(String(16), default="van")
    capacity_kg: Mapped[int] = mapped_column(Integer)
    capacity_l: Mapped[int] = mapped_column(Integer)
    fixed_cost: Mapped[Decimal] = mapped_column(MONEY)
    cost_per_km: Mapped[Decimal] = mapped_column(MONEY)
    status: Mapped[str] = mapped_column(String(16), default="AVAILABLE")  # AVAILABLE | MAINTENANCE | BROKEN


class ResourceCalendar(Base):
    """Shift / opening windows and downtime in local minutes of the operating day (overnight > 1440)."""

    __tablename__ = "resource_calendars"
    __table_args__ = (Index("ix_resource_calendars_resource", "facility_id", "resource_type", "resource_code"),)
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    facility_id: Mapped[int] = mapped_column(ForeignKey("facilities.id", ondelete="RESTRICT"))
    resource_type: Mapped[str] = mapped_column(String(16))  # worker | pack_station | equipment | dock | vehicle
    resource_code: Mapped[str] = mapped_column(String(32))
    kind: Mapped[str] = mapped_column(String(16))  # shift | downtime
    start_local_min: Mapped[int] = mapped_column(Integer)
    end_local_min: Mapped[int] = mapped_column(Integer)
    regular_end_local_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reason: Mapped[str | None] = mapped_column(String(64), nullable=True)


class TravelMatrixRow(Base):
    __tablename__ = "travel_matrices"
    __table_args__ = (UniqueConstraint("facility_id", "version", name="uq_travel_matrices_version"),)
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    facility_id: Mapped[int] = mapped_column(ForeignKey("facilities.id", ondelete="RESTRICT"), index=True)
    version: Mapped[str] = mapped_column(String(64))
    provenance: Mapped[str] = mapped_column(String(32))  # synthetic_euclidean | osrm | imported
    symmetric: Mapped[bool] = mapped_column(Boolean, default=True)
    params: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class TravelMatrixEntry(Base):
    __tablename__ = "travel_matrix_entries"
    __table_args__ = (UniqueConstraint("matrix_id", "from_loc", "to_loc", name="uq_travel_entry"),)
    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    matrix_id: Mapped[int] = mapped_column(ForeignKey("travel_matrices.id", ondelete="CASCADE"), index=True)
    from_loc: Mapped[str] = mapped_column(String(40))
    to_loc: Mapped[str] = mapped_column(String(40))
    distance_m: Mapped[int] = mapped_column(Integer)
    duration_min: Mapped[int] = mapped_column(Integer)
