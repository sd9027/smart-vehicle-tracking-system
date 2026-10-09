"""Reusable reads and row-locking helpers shared by several routes."""
from datetime import date, timedelta

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (
    Driver,
    MaintenanceRecord,
    Trip,
    TripStatus,
    Vehicle,
    VehicleAssignment,
    VehicleLocation,
)

OPEN_TRIP_STATUSES = (TripStatus.SCHEDULED, TripStatus.ACTIVE)


def lock_vehicle(db: Session, vehicle_id: int) -> Vehicle:
    """SELECT ... FOR UPDATE: other transactions wanting this row wait until we finish.

    populate_existing forces a fresh read even if the session already holds an older
    copy of this row; without it we could make decisions on stale data.
    """
    vehicle = db.scalar(
        select(Vehicle).where(Vehicle.id == vehicle_id).with_for_update()
        .execution_options(populate_existing=True)
    )
    if vehicle is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Vehicle not found.")
    return vehicle


def lock_driver(db: Session, driver_id: int) -> Driver:
    driver = db.scalar(
        select(Driver).where(Driver.id == driver_id).with_for_update()
        .execution_options(populate_existing=True)
    )
    if driver is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Driver not found.")
    return driver


def current_assignments(db: Session) -> list[VehicleAssignment]:
    return list(db.scalars(select(VehicleAssignment).where(VehicleAssignment.end_date.is_(None))))


def latest_locations(db: Session, vehicle_ids: list[int] | None = None) -> dict[int, VehicleLocation]:
    """Newest location per vehicle. Uses MAX(id) because ids increase with time."""
    newest = select(func.max(VehicleLocation.id)).group_by(VehicleLocation.vehicle_id)
    if vehicle_ids is not None:
        if not vehicle_ids:
            return {}
        newest = newest.where(VehicleLocation.vehicle_id.in_(vehicle_ids))
    rows = db.scalars(select(VehicleLocation).where(VehicleLocation.id.in_(newest)))
    return {row.vehicle_id: row for row in rows}


def upcoming_services(db: Session, days: int = 30) -> list[dict]:
    """For each vehicle, its most recent service's next due date, if due within `days` or overdue."""
    today = date.today()
    rows = db.execute(
        select(MaintenanceRecord, Vehicle.registration_no)
        .join(Vehicle, Vehicle.id == MaintenanceRecord.vehicle_id)
        .where(Vehicle.is_demo.is_(False))
        .order_by(MaintenanceRecord.vehicle_id, MaintenanceRecord.service_date.desc(), MaintenanceRecord.id.desc())
    ).all()
    seen: set[int] = set()
    result = []
    for record, registration in rows:
        if record.vehicle_id in seen:
            continue
        seen.add(record.vehicle_id)
        due = record.next_service_date
        if due is not None and due <= today + timedelta(days=days):
            result.append({
                "vehicle_id": record.vehicle_id,
                "vehicle_registration": registration,
                "service_type": record.service_type,
                "next_service_date": due,
                "days_left": (due - today).days,
            })
    return sorted(result, key=lambda r: r["days_left"])


def open_trips(db: Session) -> list[Trip]:
    return list(db.scalars(select(Trip).where(Trip.status.in_(OPEN_TRIP_STATUSES))))
