"""Pydantic schemas: validate everything that comes in, shape everything that goes out."""
import re
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, PlainSerializer, field_validator

from .models import (
    AuditStatus,
    DriverStatus,
    ExpenseCategory,
    FuelType,
    Role,
    TripStatus,
    VehicleStatus,
)


def _to_utc_iso(value: datetime) -> str:
    """Stored datetimes are naive UTC; send them with a Z so browsers convert to local time."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


UTCDateTime = Annotated[datetime, PlainSerializer(_to_utc_iso, return_type=str)]
# DECIMAL columns arrive as Decimal; JSON clients want plain numbers.
AsFloat = Annotated[float, BeforeValidator(lambda v: float(v) if isinstance(v, Decimal) else v)]

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# Standard Indian plates (UK07AB1234) and the Bharat series (22BH1234AA).
REG_RE = re.compile(r"^([A-Z]{2}\d{1,2}[A-Z]{0,3}\d{4}|\d{2}BH\d{4}[A-Z]{1,2})$")
PHONE_RE = re.compile(r"^\+?[0-9 ]{7,18}$")


def _normalise_email(value: str) -> str:
    value = value.strip().lower()
    if not EMAIL_RE.match(value):
        raise ValueError("Enter a valid email address")
    return value


def _check_password(value: str) -> str:
    if len(value) < 8:
        raise ValueError("Password must be at least 8 characters")
    if len(value.encode("utf-8")) > 72:
        raise ValueError("Password must be at most 72 bytes")
    if value.isalpha() or value.isdigit():
        raise ValueError("Password must mix letters with numbers or symbols")
    return value


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------- Auth and users ----------

class LoginIn(BaseModel):
    email: str = Field(max_length=255)
    password: str = Field(max_length=200)


class UserOut(ORM):
    id: int
    name: str
    email: str
    role: Role
    is_active: bool
    created_at: UTCDateTime
    last_login_at: UTCDateTime | None = None


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


class PasswordChangeIn(BaseModel):
    current_password: str = Field(max_length=200)
    new_password: str

    @field_validator("new_password")
    @classmethod
    def check_new_password(cls, v: str) -> str:
        return _check_password(v)


class UserCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    email: str
    password: str
    role: Role = Role.VIEWER

    @field_validator("email")
    @classmethod
    def check_email(cls, v: str) -> str:
        return _normalise_email(v)

    @field_validator("password")
    @classmethod
    def check_password(cls, v: str) -> str:
        return _check_password(v)


class UserUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=100)
    role: Role | None = None
    is_active: bool | None = None
    password: str | None = None  # admin password reset

    @field_validator("password")
    @classmethod
    def check_password(cls, v: str | None) -> str | None:
        return None if v is None else _check_password(v)


# ---------- Vehicles ----------

class VehicleCreate(BaseModel):
    registration_no: str
    model: str = Field(min_length=2, max_length=100)
    fuel_type: FuelType
    odometer_km: Decimal = Field(default=Decimal("0"), ge=0, max_digits=10, decimal_places=1)

    @field_validator("registration_no")
    @classmethod
    def check_registration(cls, v: str) -> str:
        v = re.sub(r"[\s-]", "", v).upper()
        if not REG_RE.match(v):
            raise ValueError("Use an Indian registration format such as UK07AB1234")
        return v


class VehicleUpdate(BaseModel):
    model: str | None = Field(default=None, min_length=2, max_length=100)
    fuel_type: FuelType | None = None
    # IN_USE is controlled by trips only, so it cannot be set by hand.
    status: Literal["AVAILABLE", "MAINTENANCE", "INACTIVE"] | None = None
    odometer_km: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=1)
    version: int = Field(description="The version you loaded; stale versions are rejected")


class DriverBrief(ORM):
    id: int
    name: str


class VehicleBrief(ORM):
    id: int
    registration_no: str


class VehicleOut(ORM):
    id: int
    registration_no: str
    model: str
    fuel_type: FuelType
    status: VehicleStatus
    odometer_km: AsFloat
    is_demo: bool
    version: int
    created_at: UTCDateTime
    updated_at: UTCDateTime
    current_driver: DriverBrief | None = None


class AssignDriverIn(BaseModel):
    driver_id: int | None = None  # None removes the current assignment


# ---------- Drivers ----------

class DriverCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    license_no: str
    license_expiry: date
    phone: str

    @field_validator("license_no")
    @classmethod
    def check_license(cls, v: str) -> str:
        v = re.sub(r"[\s-]", "", v).upper()
        if not re.fullmatch(r"[A-Z]{2}[0-9A-Z]{8,20}", v):
            raise ValueError("Enter a licence number such as UK0720190012345")
        return v

    @field_validator("phone")
    @classmethod
    def check_phone(cls, v: str) -> str:
        v = v.strip()
        if not PHONE_RE.match(v):
            raise ValueError("Enter a phone number with 7 to 15 digits")
        return v


class DriverUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=100)
    license_expiry: date | None = None
    phone: str | None = None
    status: Literal["AVAILABLE", "OFF_DUTY", "INACTIVE"] | None = None
    version: int

    @field_validator("phone")
    @classmethod
    def check_phone(cls, v: str | None) -> str | None:
        if v is not None and not PHONE_RE.match(v.strip()):
            raise ValueError("Enter a phone number with 7 to 15 digits")
        return v.strip() if v else v


class DriverOut(ORM):
    id: int
    name: str
    license_no: str
    license_expiry: date
    phone: str
    status: DriverStatus
    version: int
    created_at: UTCDateTime
    assigned_vehicle: VehicleBrief | None = None


# ---------- Trips and tracking ----------

class Place(BaseModel):
    id: str
    name: str
    lat: float
    lng: float


class TripCreate(BaseModel):
    vehicle_id: int
    driver_id: int
    source_place_id: str
    destination_place_id: str
    notes: str | None = Field(default=None, max_length=500)


class TripStatusIn(BaseModel):
    status: TripStatus


class TripOut(BaseModel):
    id: int
    vehicle_id: int
    vehicle_registration: str
    driver_id: int
    driver_name: str
    source: str
    destination: str
    source_lat: float
    source_lng: float
    dest_lat: float
    dest_lng: float
    status: TripStatus
    notes: str | None
    created_at: UTCDateTime
    start_time: UTCDateTime | None
    end_time: UTCDateTime | None
    distance_km: float | None


class LocationOut(ORM):
    vehicle_id: int
    trip_id: int | None
    latitude: float
    longitude: float
    speed_kmh: float
    is_simulated: bool
    recorded_at: UTCDateTime


class LiveTrip(BaseModel):
    id: int
    status: TripStatus
    source: str
    destination: str
    dest_lat: float
    dest_lng: float
    progress: float | None


class LiveVehicle(BaseModel):
    vehicle_id: int
    registration_no: str
    model: str
    status: VehicleStatus
    driver_name: str | None
    trip: LiveTrip | None
    location: LocationOut | None


# ---------- Fuel, maintenance, expenses ----------

Money = Annotated[Decimal, Field(ge=0, max_digits=10, decimal_places=2)]


class FuelCreate(BaseModel):
    vehicle_id: int
    quantity_l: Decimal = Field(gt=0, max_digits=8, decimal_places=2)
    price_per_l: Decimal = Field(gt=0, max_digits=8, decimal_places=2)
    odometer_km: Decimal = Field(ge=0, max_digits=10, decimal_places=1)
    station: str | None = Field(default=None, max_length=120)


class FuelOut(BaseModel):
    id: int
    vehicle_id: int
    vehicle_registration: str
    expense_id: int
    quantity_l: float
    price_per_l: float
    total_cost: float
    odometer_km: float
    station: str | None
    recorded_at: UTCDateTime


class MaintenanceCreate(BaseModel):
    vehicle_id: int
    service_type: str = Field(min_length=2, max_length=60)
    description: str = Field(default="", max_length=500)
    service_date: date
    cost: Money
    odometer_km: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=1)
    next_service_date: date | None = None
    put_in_maintenance: bool = False


class MaintenanceOut(BaseModel):
    id: int
    vehicle_id: int
    vehicle_registration: str
    expense_id: int
    service_type: str
    description: str
    service_date: date
    cost: float
    odometer_km: float | None
    next_service_date: date | None


class UpcomingService(BaseModel):
    vehicle_id: int
    vehicle_registration: str
    service_type: str
    next_service_date: date
    days_left: int


class ExpenseCreate(BaseModel):
    vehicle_id: int
    # Fuel and maintenance costs are created through their own forms.
    category: Literal["TOLL", "INSURANCE", "PARKING", "OTHER"]
    amount: Money
    expense_date: date
    description: str = Field(default="", max_length=255)


class ExpenseOut(BaseModel):
    id: int
    vehicle_id: int
    vehicle_registration: str
    category: ExpenseCategory
    amount: float
    expense_date: date
    description: str
    created_at: UTCDateTime


# ---------- Transaction lab and audit ----------

class AuditOut(BaseModel):
    id: int
    user_id: int | None
    user_name: str | None
    operation: str
    status: AuditStatus
    entity: str | None
    entity_id: int | None
    message: str
    details: str | None
    duration_ms: int | None
    created_at: UTCDateTime


class DemoStep(BaseModel):
    t_ms: int
    actor: str
    action: str
    sql: str | None = None
    outcome: str = ""


class DemoResult(BaseModel):
    operation: str
    final_status: str
    message: str
    steps: list[DemoStep]
    before: dict[str, Any]
    after: dict[str, Any]
    audit_ids: list[int] = []


class RollbackDemoIn(BaseModel):
    failure: Literal["foreign_key", "check_constraint", "application"] = "foreign_key"


class ConcurrencyDemoIn(BaseModel):
    mode: Literal["naive", "conditional", "pessimistic"] = "pessimistic"


class ConsistencyCheck(BaseModel):
    name: str
    description: str
    sql: str
    violations: int
    passed: bool
