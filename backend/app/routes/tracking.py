"""Live positions and location history."""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..config import get_settings
from ..database import get_db
from ..deps import get_current_user
from ..models import Trip, TripStatus, User, Vehicle, VehicleAssignment, VehicleLocation, VehicleStatus
from ..schemas import LiveVehicle, LocationOut
from ..services.geo import haversine_km
from ..services.queries import OPEN_TRIP_STATUSES, latest_locations

router = APIRouter(tags=["tracking"])
settings = get_settings()


def trip_progress(trip: Trip, location: VehicleLocation | None) -> float | None:
    if trip.status != TripStatus.ACTIVE or location is None:
        return None
    total = haversine_km(trip.source_lat, trip.source_lng, trip.dest_lat, trip.dest_lng)
    if total < 0.01:
        return 1.0
    remaining = haversine_km(location.latitude, location.longitude, trip.dest_lat, trip.dest_lng)
    return round(max(0.0, min(1.0, 1 - remaining / total)), 3)


@router.get("/api/tracking/live", response_model=list[LiveVehicle])
def live_positions(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    vehicles = db.scalars(select(Vehicle).where(Vehicle.is_demo.is_(False),
                                                Vehicle.status != VehicleStatus.INACTIVE)
                          .order_by(Vehicle.registration_no)).all()
    ids = [v.id for v in vehicles]
    locations = latest_locations(db, ids)
    trips = {t.vehicle_id: t for t in db.scalars(
        select(Trip).where(Trip.status.in_(OPEN_TRIP_STATUSES)).options(selectinload(Trip.driver)))}
    assigned = {a.vehicle_id: a.driver.name for a in db.scalars(
        select(VehicleAssignment).where(VehicleAssignment.end_date.is_(None))
        .options(selectinload(VehicleAssignment.driver)))}

    result = []
    for v in vehicles:
        trip = trips.get(v.id)
        location = locations.get(v.id)
        result.append({
            "vehicle_id": v.id,
            "registration_no": v.registration_no,
            "model": v.model,
            "status": v.status,
            "driver_name": trip.driver.name if trip else assigned.get(v.id),
            "trip": {
                "id": trip.id, "status": trip.status, "source": trip.source, "destination": trip.destination,
                "dest_lat": trip.dest_lat, "dest_lng": trip.dest_lng,
                "progress": trip_progress(trip, location),
            } if trip else None,
            "location": LocationOut.model_validate(location) if location else None,
        })
    return result


@router.get("/api/vehicles/{vehicle_id}/location", response_model=LocationOut)
def latest_location(vehicle_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    location = latest_locations(db, [vehicle_id]).get(vehicle_id)
    if location is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No location recorded for this vehicle yet.")
    return location


@router.get("/api/vehicles/{vehicle_id}/history", response_model=list[LocationOut])
def location_history(
    vehicle_id: int,
    trip_id: int | None = None,
    limit: int = Query(default=500, ge=1, le=5000),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Positions in time order. Defaults to the vehicle's active trip if it has one."""
    if trip_id is None:
        trip_id = db.scalar(select(Trip.id).where(Trip.vehicle_id == vehicle_id,
                                                  Trip.status == TripStatus.ACTIVE))
    stmt = select(VehicleLocation).where(VehicleLocation.vehicle_id == vehicle_id)
    if trip_id is not None:
        stmt = stmt.where(VehicleLocation.trip_id == trip_id)
    # Take the newest `limit` rows, then return them oldest-first for drawing a trail.
    rows = db.scalars(stmt.order_by(VehicleLocation.id.desc()).limit(limit)).all()
    return list(reversed(rows))


@router.get("/api/tracking/simulator")
def simulator_status(_: User = Depends(get_current_user)):
    return {
        "enabled": settings.simulator_enabled,
        "interval_seconds": settings.simulator_interval_seconds,
        "speed_multiplier": settings.simulator_speed_multiplier,
        "note": "All positions are simulated in software; no GPS hardware is connected.",
    }
