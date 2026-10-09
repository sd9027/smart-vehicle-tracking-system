"""ORM models. These mirror database/schema.sql, which is the source of truth for MySQL.

If you change a table here, change schema.sql in the same commit.
"""
import enum
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    Double,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base

# BIGINT in MySQL; SQLite only auto-increments a plain INTEGER primary key.
BigIntPK = BigInteger().with_variant(Integer, "sqlite")


def utcnow() -> datetime:
    """All timestamps are stored as naive UTC."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Role(str, enum.Enum):
    ADMIN = "ADMIN"
    MANAGER = "MANAGER"
    VIEWER = "VIEWER"


class VehicleStatus(str, enum.Enum):
    AVAILABLE = "AVAILABLE"
    IN_USE = "IN_USE"
    MAINTENANCE = "MAINTENANCE"
    INACTIVE = "INACTIVE"


class FuelType(str, enum.Enum):
    PETROL = "PETROL"
    DIESEL = "DIESEL"
    CNG = "CNG"
    ELECTRIC = "ELECTRIC"
    HYBRID = "HYBRID"


class DriverStatus(str, enum.Enum):
    AVAILABLE = "AVAILABLE"
    ON_TRIP = "ON_TRIP"
    OFF_DUTY = "OFF_DUTY"
    INACTIVE = "INACTIVE"


class TripStatus(str, enum.Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ExpenseCategory(str, enum.Enum):
    FUEL = "FUEL"
    MAINTENANCE = "MAINTENANCE"
    TOLL = "TOLL"
    INSURANCE = "INSURANCE"
    PARKING = "PARKING"
    OTHER = "OTHER"


class AuditStatus(str, enum.Enum):
    COMMITTED = "COMMITTED"
    ROLLED_BACK = "ROLLED_BACK"


class User(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("email", name="uq_users_email"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(255))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(SAEnum(Role, name="user_role"), default=Role.VIEWER)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Incremented on password change so every previously issued token stops working.
    token_version: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime)


class Vehicle(Base):
    __tablename__ = "vehicles"
    __table_args__ = (
        UniqueConstraint("registration_no", name="uq_vehicles_registration"),
        CheckConstraint("odometer_km >= 0", name="chk_vehicles_odometer"),
        Index("ix_vehicles_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    registration_no: Mapped[str] = mapped_column(String(15))
    model: Mapped[str] = mapped_column(String(100))
    fuel_type: Mapped[FuelType] = mapped_column(SAEnum(FuelType, name="fuel_type"))
    status: Mapped[VehicleStatus] = mapped_column(
        SAEnum(VehicleStatus, name="vehicle_status"), default=VehicleStatus.AVAILABLE
    )
    odometer_km: Mapped[Decimal] = mapped_column(Numeric(10, 1), default=Decimal("0"))
    # The transaction lab uses one hidden test vehicle so demos never touch real records.
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    # Optimistic locking: every UPDATE checks and increments this number.
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    __mapper_args__ = {"version_id_col": version}


class Driver(Base):
    __tablename__ = "drivers"
    __table_args__ = (
        UniqueConstraint("license_no", name="uq_drivers_license"),
        Index("ix_drivers_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    license_no: Mapped[str] = mapped_column(String(30))
    license_expiry: Mapped[date] = mapped_column(Date)
    phone: Mapped[str] = mapped_column(String(20))
    status: Mapped[DriverStatus] = mapped_column(
        SAEnum(DriverStatus, name="driver_status"), default=DriverStatus.AVAILABLE
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    __mapper_args__ = {"version_id_col": version}


class VehicleAssignment(Base):
    """Which driver normally drives which vehicle. end_date NULL = current assignment."""

    __tablename__ = "vehicle_assignments"
    __table_args__ = (
        # Generated columns are non-NULL only for the open assignment, so these unique
        # keys guarantee at most one current driver per vehicle and vice versa.
        UniqueConstraint("open_vehicle_id", name="uq_assign_open_vehicle"),
        UniqueConstraint("open_driver_id", name="uq_assign_open_driver"),
        CheckConstraint("end_date IS NULL OR end_date >= start_date", name="chk_assign_dates"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"))
    driver_id: Mapped[int] = mapped_column(ForeignKey("drivers.id"))
    start_date: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    end_date: Mapped[datetime | None] = mapped_column(DateTime)
    open_vehicle_id: Mapped[int | None] = mapped_column(
        Integer, Computed("CASE WHEN end_date IS NULL THEN vehicle_id ELSE NULL END", persisted=True)
    )
    open_driver_id: Mapped[int | None] = mapped_column(
        Integer, Computed("CASE WHEN end_date IS NULL THEN driver_id ELSE NULL END", persisted=True)
    )

    vehicle: Mapped[Vehicle] = relationship()
    driver: Mapped[Driver] = relationship()


class Trip(Base):
    __tablename__ = "trips"
    __table_args__ = (
        # Database-level guarantee against double booking: a vehicle (or driver) can
        # appear in at most one SCHEDULED/ACTIVE trip, even if application code has a bug.
        UniqueConstraint("open_vehicle_id", name="uq_trips_open_vehicle"),
        UniqueConstraint("open_driver_id", name="uq_trips_open_driver"),
        CheckConstraint(
            "end_time IS NULL OR start_time IS NULL OR end_time >= start_time",
            name="chk_trips_time_order",
        ),
        CheckConstraint("distance_km IS NULL OR distance_km >= 0", name="chk_trips_distance"),
        Index("ix_trips_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"))
    driver_id: Mapped[int] = mapped_column(ForeignKey("drivers.id"))
    source: Mapped[str] = mapped_column(String(120))
    destination: Mapped[str] = mapped_column(String(120))
    source_lat: Mapped[float] = mapped_column(Double)
    source_lng: Mapped[float] = mapped_column(Double)
    dest_lat: Mapped[float] = mapped_column(Double)
    dest_lng: Mapped[float] = mapped_column(Double)
    status: Mapped[TripStatus] = mapped_column(
        SAEnum(TripStatus, name="trip_status"), default=TripStatus.SCHEDULED
    )
    notes: Mapped[str | None] = mapped_column(String(500))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    start_time: Mapped[datetime | None] = mapped_column(DateTime)
    end_time: Mapped[datetime | None] = mapped_column(DateTime)
    distance_km: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    open_vehicle_id: Mapped[int | None] = mapped_column(
        Integer,
        Computed(
            "CASE WHEN status IN ('SCHEDULED', 'ACTIVE') THEN vehicle_id ELSE NULL END",
            persisted=True,
        ),
    )
    open_driver_id: Mapped[int | None] = mapped_column(
        Integer,
        Computed(
            "CASE WHEN status IN ('SCHEDULED', 'ACTIVE') THEN driver_id ELSE NULL END",
            persisted=True,
        ),
    )

    vehicle: Mapped[Vehicle] = relationship()
    driver: Mapped[Driver] = relationship()


class VehicleLocation(Base):
    __tablename__ = "vehicle_locations"
    __table_args__ = (
        CheckConstraint("latitude BETWEEN -90 AND 90", name="chk_loc_lat"),
        CheckConstraint("longitude BETWEEN -180 AND 180", name="chk_loc_lng"),
        CheckConstraint("speed_kmh >= 0", name="chk_loc_speed"),
        Index("ix_locations_vehicle_time", "vehicle_id", "recorded_at"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"))
    trip_id: Mapped[int | None] = mapped_column(ForeignKey("trips.id"))
    latitude: Mapped[float] = mapped_column(Double)
    longitude: Mapped[float] = mapped_column(Double)
    speed_kmh: Mapped[float] = mapped_column(Double, default=0.0)
    # Every position in this project comes from the simulator. A real GPS feed would set False.
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Expense(Base):
    __tablename__ = "expenses"
    __table_args__ = (
        CheckConstraint("amount >= 0", name="chk_expenses_amount"),
        Index("ix_expenses_date", "expense_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"))
    category: Mapped[ExpenseCategory] = mapped_column(SAEnum(ExpenseCategory, name="expense_category"))
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    expense_date: Mapped[date] = mapped_column(Date)
    description: Mapped[str] = mapped_column(String(255), default="")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    vehicle: Mapped[Vehicle] = relationship()


class FuelRecord(Base):
    __tablename__ = "fuel_records"
    __table_args__ = (
        UniqueConstraint("expense_id", name="uq_fuel_expense"),
        CheckConstraint("quantity_l > 0", name="chk_fuel_quantity"),
        CheckConstraint("price_per_l > 0", name="chk_fuel_price"),
        CheckConstraint("total_cost >= 0", name="chk_fuel_total"),
        CheckConstraint("odometer_km >= 0", name="chk_fuel_odometer"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"))
    # Each fuel purchase is also an expense row; both are written in one transaction.
    expense_id: Mapped[int] = mapped_column(ForeignKey("expenses.id"))
    quantity_l: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    price_per_l: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    total_cost: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    odometer_km: Mapped[Decimal] = mapped_column(Numeric(10, 1))
    station: Mapped[str | None] = mapped_column(String(120))
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    vehicle: Mapped[Vehicle] = relationship()


class MaintenanceRecord(Base):
    __tablename__ = "maintenance_records"
    __table_args__ = (
        UniqueConstraint("expense_id", name="uq_maintenance_expense"),
        CheckConstraint("cost >= 0", name="chk_maint_cost"),
        CheckConstraint(
            "next_service_date IS NULL OR next_service_date >= service_date",
            name="chk_maint_next_date",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"))
    expense_id: Mapped[int] = mapped_column(ForeignKey("expenses.id"))
    service_type: Mapped[str] = mapped_column(String(60))
    description: Mapped[str] = mapped_column(String(500), default="")
    service_date: Mapped[date] = mapped_column(Date)
    cost: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    odometer_km: Mapped[Decimal | None] = mapped_column(Numeric(10, 1))
    next_service_date: Mapped[date | None] = mapped_column(Date)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    vehicle: Mapped[Vehicle] = relationship()


class TransactionAudit(Base):
    """One row per write operation. Never stores passwords or tokens."""

    __tablename__ = "transaction_audit"
    __table_args__ = (
        Index("ix_audit_created", "created_at"),
        Index("ix_audit_status", "status"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    operation: Mapped[str] = mapped_column(String(60))
    status: Mapped[AuditStatus] = mapped_column(SAEnum(AuditStatus, name="audit_status"))
    entity: Mapped[str | None] = mapped_column(String(40))
    entity_id: Mapped[int | None] = mapped_column(Integer)
    message: Mapped[str] = mapped_column(String(500), default="")
    details: Mapped[str | None] = mapped_column(Text)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    user: Mapped[User | None] = relationship()
