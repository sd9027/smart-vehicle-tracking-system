"""Software GPS simulator.

Every few seconds, each ACTIVE trip's vehicle gets a new position stored in
vehicle_locations with is_simulated = TRUE. Movement is a straight line from
source to destination with a little wobble, at a randomised speed; simulated
time runs SIMULATOR_SPEED_MULTIPLIER times faster so a 40 km trip finishes in
a few minutes. A real GPS device would replace this module by POSTing positions.
"""
import asyncio
import logging
import math
import random

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from ..config import get_settings
from ..database import SessionLocal
from ..models import Trip, TripStatus, VehicleLocation, utcnow
from .geo import haversine_km

log = logging.getLogger("tracktech.simulator")
settings = get_settings()

AVERAGE_SPEED_KMH = 40.0


def progress_of(trip: Trip, now) -> float:
    """Fraction of the trip completed, based on simulated elapsed time."""
    if trip.start_time is None:
        return 0.0
    total_km = haversine_km(trip.source_lat, trip.source_lng, trip.dest_lat, trip.dest_lng)
    if total_km < 0.01:
        return 1.0
    elapsed_h = (now - trip.start_time).total_seconds() / 3600 * settings.simulator_speed_multiplier
    return max(0.0, min(1.0, elapsed_h * AVERAGE_SPEED_KMH / total_km))


def simulated_position(trip: Trip, progress: float) -> tuple[float, float]:
    lat = trip.source_lat + (trip.dest_lat - trip.source_lat) * progress
    lng = trip.source_lng + (trip.dest_lng - trip.source_lng) * progress
    if 0 < progress < 1:
        # Gentle sideways wobble so the trail looks like a road, not a ruler line.
        wobble = math.sin(progress * math.pi * 6) * 0.004 * math.sin(progress * math.pi)
        lat += wobble
        lng -= wobble * 0.6
    return lat, lng


def tick() -> int:
    """Record one position for every active trip. Returns how many were written."""
    now = utcnow()
    with SessionLocal() as db:
        trips = db.scalars(
            select(Trip).where(Trip.status == TripStatus.ACTIVE).options(selectinload(Trip.vehicle))
        ).all()
        for trip in trips:
            progress = progress_of(trip, now)
            lat, lng = simulated_position(trip, progress)
            speed = 0.0 if progress >= 1 else round(random.uniform(28, 55), 1)
            db.add(VehicleLocation(
                vehicle_id=trip.vehicle_id, trip_id=trip.id, latitude=lat, longitude=lng,
                speed_kmh=speed, is_simulated=True, recorded_at=now,
            ))
        db.commit()
        return len(trips)


async def run_simulator(stop: asyncio.Event) -> None:
    log.info("GPS simulator started (every %ss)", settings.simulator_interval_seconds)
    while not stop.is_set():
        try:
            # The database work is blocking, so run it in a worker thread.
            await asyncio.to_thread(tick)
        except Exception:
            log.exception("Simulator tick failed; will retry")
        try:
            await asyncio.wait_for(stop.wait(), timeout=settings.simulator_interval_seconds)
        except asyncio.TimeoutError:
            pass
    log.info("GPS simulator stopped")
