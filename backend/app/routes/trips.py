"""Trips: create (assign vehicle + driver atomically) and move through their lifecycle."""
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..database import get_db
from ..deps import get_current_user, require_manager
from ..models import (
    DriverStatus,
    Trip,
    TripStatus,
    User,
    VehicleLocation,
    VehicleStatus,
    utcnow,
)
from ..schemas import Place, TripCreate, TripOut, TripStatusIn
from ..services.audit import transactional
from ..services.geo import PLACES, haversine_km, path_length_km
from ..services.queries import lock_driver, lock_vehicle
from ..services.serializers import trip_out

router = APIRouter(tags=["trips"])

# Which status changes are legal. Anything else is rejected with 409.
ALLOWED_TRANSITIONS = {
    TripStatus.SCHEDULED: {TripStatus.ACTIVE, TripStatus.CANCELLED},
    TripStatus.ACTIVE: {TripStatus.COMPLETED, TripStatus.CANCELLED},
    TripStatus.COMPLETED: set(),
    TripStatus.CANCELLED: set(),
}


@router.get("/api/places", response_model=list[Place])
def list_places(_: User = Depends(get_current_user)):
    return [{"id": key, **value} for key, value in PLACES.items()]


@router.get("/api/trips", response_model=list[TripOut])
def list_trips(
    status_: list[TripStatus] | None = Query(default=None, alias="status"),
    vehicle_id: int | None = None,
    driver_id: int | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    stmt = (select(Trip).options(selectinload(Trip.vehicle), selectinload(Trip.driver))
            .order_by(Trip.created_at.desc()).limit(limit))
    if status_:
        stmt = stmt.where(Trip.status.in_(status_))
    if vehicle_id:
        stmt = stmt.where(Trip.vehicle_id == vehicle_id)
    if driver_id:
        stmt = stmt.where(Trip.driver_id == driver_id)
    return [trip_out(t) for t in db.scalars(stmt)]


@router.get("/api/trips/{trip_id}", response_model=TripOut)
def get_trip(trip_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    trip = db.get(Trip, trip_id)
    if trip is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Trip not found.")
    return trip_out(trip)


@router.post("/api/trips", response_model=TripOut, status_code=status.HTTP_201_CREATED)
def create_trip(body: TripCreate, db: Session = Depends(get_db), user: User = Depends(require_manager)):
    """Example A from the project plan: start a trip safely.

    1. Lock the vehicle row and check it is AVAILABLE.
    2. Lock the driver row and check they are AVAILABLE with a valid licence.
    3. Insert the trip and mark vehicle IN_USE and driver ON_TRIP.
    4. COMMIT all of it together, or ROLLBACK everything if any step fails.
    """
    source = PLACES.get(body.source_place_id)
    destination = PLACES.get(body.destination_place_id)
    if source is None or destination is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Choose a source and destination from the list.")
    if body.source_place_id == body.destination_place_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Source and destination must be different.")

    with transactional(db, user, "CREATE_TRIP", "trip") as tx:
        tx.details = {"vehicle_id": body.vehicle_id, "driver_id": body.driver_id,
                      "route": f"{source['name']} -> {destination['name']}"}
        # Lock order: vehicle, then driver (same order everywhere, to avoid deadlocks).
        vehicle = lock_vehicle(db, body.vehicle_id)
        if vehicle.is_demo:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Vehicle not found.")
        if vehicle.status != VehicleStatus.AVAILABLE:
            raise HTTPException(status.HTTP_409_CONFLICT,
                                f"{vehicle.registration_no} is {vehicle.status.value.replace('_', ' ').lower()} "
                                "and cannot start a new trip.")
        driver = lock_driver(db, body.driver_id)
        if driver.status != DriverStatus.AVAILABLE:
            raise HTTPException(status.HTTP_409_CONFLICT,
                                f"{driver.name} is {driver.status.value.replace('_', ' ').lower()} "
                                "and cannot take a new trip.")
        if driver.license_expiry < date.today():
            raise HTTPException(status.HTTP_409_CONFLICT,
                                f"{driver.name}'s licence expired on {driver.license_expiry:%d %b %Y}.")

        trip = Trip(
            vehicle=vehicle, driver=driver,
            source=source["name"], source_lat=source["lat"], source_lng=source["lng"],
            destination=destination["name"], dest_lat=destination["lat"], dest_lng=destination["lng"],
            status=TripStatus.SCHEDULED, notes=(body.notes or None), created_by=user.id,
        )
        db.add(trip)
        vehicle.status = VehicleStatus.IN_USE
        driver.status = DriverStatus.ON_TRIP
        db.flush()
        tx.entity_id = trip.id
        tx.message = f"Trip #{trip.id}: {vehicle.registration_no} with {driver.name}"
    return trip_out(trip)


@router.patch("/api/trips/{trip_id}/status", response_model=TripOut)
def change_trip_status(trip_id: int, body: TripStatusIn, db: Session = Depends(get_db),
                       user: User = Depends(require_manager)):
    new = body.status
    with transactional(db, user, f"TRIP_{new.value}", "trip", trip_id) as tx:
        trip = db.scalar(select(Trip).where(Trip.id == trip_id).with_for_update()
                         .execution_options(populate_existing=True))
        if trip is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Trip not found.")
        old = trip.status
        if new not in ALLOWED_TRANSITIONS[old]:
            raise HTTPException(status.HTTP_409_CONFLICT,
                                f"A {old.value.lower()} trip cannot be marked {new.value.lower()}.")
        vehicle = lock_vehicle(db, trip.vehicle_id)
        driver = lock_driver(db, trip.driver_id)
        now = utcnow()

        if new == TripStatus.ACTIVE:
            trip.start_time = now
            db.add(VehicleLocation(vehicle_id=vehicle.id, trip_id=trip.id, latitude=trip.source_lat,
                                   longitude=trip.source_lng, speed_kmh=0, is_simulated=True, recorded_at=now))

        elif new == TripStatus.COMPLETED:
            points = [(lat, lng) for lat, lng in db.execute(
                select(VehicleLocation.latitude, VehicleLocation.longitude)
                .where(VehicleLocation.trip_id == trip.id).order_by(VehicleLocation.id))]
            if not points:
                points = [(trip.source_lat, trip.source_lng)]
            points.append((trip.dest_lat, trip.dest_lng))
            distance = round(path_length_km(points), 2)
            trip.end_time = now
            trip.distance_km = Decimal(str(distance))
            vehicle.odometer_km = vehicle.odometer_km + Decimal(str(round(distance, 1)))
            db.add(VehicleLocation(vehicle_id=vehicle.id, trip_id=trip.id, latitude=trip.dest_lat,
                                   longitude=trip.dest_lng, speed_kmh=0, is_simulated=True, recorded_at=now))
            tx.details = {"distance_km": distance,
                          "straight_line_km": round(haversine_km(trip.source_lat, trip.source_lng,
                                                                 trip.dest_lat, trip.dest_lng), 2)}

        elif new == TripStatus.CANCELLED and trip.start_time is not None:
            trip.end_time = now

        if new in (TripStatus.COMPLETED, TripStatus.CANCELLED):
            # Release the vehicle and driver in the same transaction as the status change.
            if vehicle.status == VehicleStatus.IN_USE:
                vehicle.status = VehicleStatus.AVAILABLE
            if driver.status == DriverStatus.ON_TRIP:
                driver.status = DriverStatus.AVAILABLE

        trip.status = new
        tx.message = f"Trip #{trip.id}: {old.value} -> {new.value}"
    return trip_out(trip)
