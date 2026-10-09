"""Vehicle CRUD, driver assignment and per-vehicle records."""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from ..database import get_db
from ..deps import get_current_user, require_admin, require_manager
from ..models import (
    Driver,
    DriverStatus,
    FuelRecord,
    MaintenanceRecord,
    Trip,
    User,
    Vehicle,
    VehicleAssignment,
    VehicleStatus,
    utcnow,
)
from ..schemas import (
    AssignDriverIn,
    DriverBrief,
    FuelOut,
    MaintenanceOut,
    TripOut,
    VehicleCreate,
    VehicleOut,
    VehicleUpdate,
)
from ..services.audit import transactional
from ..services.queries import lock_driver, lock_vehicle
from ..services.serializers import fuel_out, maintenance_out, trip_out

router = APIRouter(prefix="/api/vehicles", tags=["vehicles"])


def _vehicle_out(vehicle: Vehicle, driver: Driver | None) -> VehicleOut:
    out = VehicleOut.model_validate(vehicle)
    if driver is not None:
        out.current_driver = DriverBrief(id=driver.id, name=driver.name)
    return out


def _driver_for(db: Session, vehicle_id: int) -> Driver | None:
    return db.scalar(
        select(Driver).join(VehicleAssignment, VehicleAssignment.driver_id == Driver.id)
        .where(VehicleAssignment.vehicle_id == vehicle_id, VehicleAssignment.end_date.is_(None))
    )


def _get_real_vehicle(db: Session, vehicle_id: int) -> Vehicle:
    vehicle = db.get(Vehicle, vehicle_id)
    if vehicle is None or vehicle.is_demo:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Vehicle not found.")
    return vehicle


@router.get("", response_model=list[VehicleOut])
def list_vehicles(
    status_: VehicleStatus | None = Query(default=None, alias="status"),
    q: str | None = Query(default=None, max_length=50),
    include_inactive: bool = True,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    stmt = select(Vehicle).where(Vehicle.is_demo.is_(False)).order_by(Vehicle.registration_no)
    if status_:
        stmt = stmt.where(Vehicle.status == status_)
    if not include_inactive:
        stmt = stmt.where(Vehicle.status != VehicleStatus.INACTIVE)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Vehicle.registration_no.ilike(like), Vehicle.model.ilike(like)))
    vehicles = db.scalars(stmt).all()
    drivers = {a.vehicle_id: a.driver for a in
               db.scalars(select(VehicleAssignment).where(VehicleAssignment.end_date.is_(None))
                          .options(selectinload(VehicleAssignment.driver)))}
    return [_vehicle_out(v, drivers.get(v.id)) for v in vehicles]


@router.get("/{vehicle_id}", response_model=VehicleOut)
def get_vehicle(vehicle_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    vehicle = _get_real_vehicle(db, vehicle_id)
    return _vehicle_out(vehicle, _driver_for(db, vehicle_id))


@router.post("", response_model=VehicleOut, status_code=status.HTTP_201_CREATED)
def create_vehicle(body: VehicleCreate, db: Session = Depends(get_db), user: User = Depends(require_manager)):
    with transactional(db, user, "CREATE_VEHICLE", "vehicle") as tx:
        # Checking first gives a clear message; the UNIQUE key still protects against races.
        if db.scalar(select(Vehicle.id).where(Vehicle.registration_no == body.registration_no)):
            raise HTTPException(status.HTTP_409_CONFLICT, "A vehicle with this registration number already exists.")
        vehicle = Vehicle(registration_no=body.registration_no, model=body.model.strip(),
                          fuel_type=body.fuel_type, odometer_km=body.odometer_km)
        db.add(vehicle)
        db.flush()
        tx.entity_id = vehicle.id
        tx.message = f"Added vehicle {vehicle.registration_no}"
    return _vehicle_out(vehicle, None)


@router.put("/{vehicle_id}", response_model=VehicleOut)
def update_vehicle(vehicle_id: int, body: VehicleUpdate, db: Session = Depends(get_db),
                   user: User = Depends(require_manager)):
    with transactional(db, user, "UPDATE_VEHICLE", "vehicle", vehicle_id) as tx:
        vehicle = lock_vehicle(db, vehicle_id)
        if vehicle.is_demo:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Vehicle not found.")
        # Optimistic concurrency: the form carries the version it was loaded with.
        if vehicle.version != body.version:
            raise HTTPException(status.HTTP_409_CONFLICT,
                                "This vehicle was changed by someone else after you opened it. "
                                "Close the form, reload and try again.")
        changes = {}
        if body.model is not None and body.model.strip() != vehicle.model:
            vehicle.model = body.model.strip()
            changes["model"] = vehicle.model
        if body.fuel_type is not None and body.fuel_type != vehicle.fuel_type:
            vehicle.fuel_type = body.fuel_type
            changes["fuel_type"] = body.fuel_type.value
        if body.odometer_km is not None and body.odometer_km != vehicle.odometer_km:
            if body.odometer_km < vehicle.odometer_km:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                    "The odometer reading cannot go backwards.")
            vehicle.odometer_km = body.odometer_km
            changes["odometer_km"] = float(body.odometer_km)
        if body.status is not None and body.status != vehicle.status.value:
            if vehicle.status == VehicleStatus.IN_USE:
                raise HTTPException(status.HTTP_409_CONFLICT,
                                    "This vehicle is on a trip. Complete or cancel the trip first.")
            vehicle.status = VehicleStatus(body.status)
            changes["status"] = body.status
            if vehicle.status == VehicleStatus.INACTIVE:
                _end_assignment(db, vehicle_id=vehicle.id)
        tx.details = changes
        tx.message = f"Updated {vehicle.registration_no}" if changes else "No changes"
    return _vehicle_out(vehicle, _driver_for(db, vehicle_id))


@router.delete("/{vehicle_id}", response_model=VehicleOut)
def deactivate_vehicle(vehicle_id: int, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    """Soft delete: history (trips, fuel, costs) must keep pointing at the vehicle."""
    with transactional(db, user, "DEACTIVATE_VEHICLE", "vehicle", vehicle_id) as tx:
        vehicle = lock_vehicle(db, vehicle_id)
        if vehicle.is_demo:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Vehicle not found.")
        if vehicle.status == VehicleStatus.IN_USE:
            raise HTTPException(status.HTTP_409_CONFLICT,
                                "This vehicle is on a trip. Complete or cancel the trip first.")
        vehicle.status = VehicleStatus.INACTIVE
        _end_assignment(db, vehicle_id=vehicle.id)
        tx.message = f"Deactivated {vehicle.registration_no}"
    return _vehicle_out(vehicle, None)


def _end_assignment(db: Session, *, vehicle_id: int | None = None, driver_id: int | None = None) -> None:
    stmt = select(VehicleAssignment).where(VehicleAssignment.end_date.is_(None)).with_for_update()
    if vehicle_id is not None:
        stmt = stmt.where(VehicleAssignment.vehicle_id == vehicle_id)
    if driver_id is not None:
        stmt = stmt.where(VehicleAssignment.driver_id == driver_id)
    for assignment in db.scalars(stmt):
        assignment.end_date = utcnow()
    db.flush()


@router.post("/{vehicle_id}/assign-driver", response_model=VehicleOut)
def assign_driver(vehicle_id: int, body: AssignDriverIn, db: Session = Depends(get_db),
                  user: User = Depends(require_manager)):
    """End the vehicle's current assignment and the driver's current one, then create a new one."""
    with transactional(db, user, "ASSIGN_DRIVER", "vehicle", vehicle_id) as tx:
        # Lock order is always vehicle first, then driver, everywhere in the code.
        # A consistent order means two transactions can never wait on each other in a cycle (deadlock).
        vehicle = lock_vehicle(db, vehicle_id)
        if vehicle.is_demo or vehicle.status == VehicleStatus.INACTIVE:
            raise HTTPException(status.HTTP_409_CONFLICT, "Inactive vehicles cannot be assigned a driver.")
        driver = None
        if body.driver_id is not None:
            driver = lock_driver(db, body.driver_id)
            if driver.status == DriverStatus.INACTIVE:
                raise HTTPException(status.HTTP_409_CONFLICT, "This driver is inactive.")
        current = _driver_for(db, vehicle_id)
        if current is not None and driver is not None and current.id == driver.id:
            tx.message = "Driver already assigned"
            return _vehicle_out(vehicle, driver)
        _end_assignment(db, vehicle_id=vehicle_id)
        if driver is not None:
            _end_assignment(db, driver_id=driver.id)
            db.add(VehicleAssignment(vehicle_id=vehicle_id, driver_id=driver.id, start_date=utcnow()))
        tx.details = {"driver_id": body.driver_id}
        tx.message = (f"Assigned {driver.name} to {vehicle.registration_no}" if driver
                      else f"Removed driver from {vehicle.registration_no}")
    return _vehicle_out(vehicle, driver)


@router.get("/{vehicle_id}/records")
def vehicle_records(vehicle_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    """Trips, fuel, maintenance and driver assignments for one vehicle."""
    vehicle = _get_real_vehicle(db, vehicle_id)
    trips = db.scalars(select(Trip).where(Trip.vehicle_id == vehicle_id)
                       .options(selectinload(Trip.vehicle), selectinload(Trip.driver))
                       .order_by(Trip.created_at.desc()).limit(50)).all()
    fuel = db.scalars(select(FuelRecord).where(FuelRecord.vehicle_id == vehicle_id)
                      .options(selectinload(FuelRecord.vehicle))
                      .order_by(FuelRecord.recorded_at.desc()).limit(50)).all()
    maintenance = db.scalars(select(MaintenanceRecord).where(MaintenanceRecord.vehicle_id == vehicle_id)
                             .options(selectinload(MaintenanceRecord.vehicle))
                             .order_by(MaintenanceRecord.service_date.desc()).limit(50)).all()
    assignments = db.scalars(select(VehicleAssignment).where(VehicleAssignment.vehicle_id == vehicle_id)
                             .options(selectinload(VehicleAssignment.driver))
                             .order_by(VehicleAssignment.start_date.desc())).all()
    return {
        "vehicle": _vehicle_out(vehicle, _driver_for(db, vehicle_id)).model_dump(mode="json"),
        "trips": [TripOut(**trip_out(t)).model_dump(mode="json") for t in trips],
        "fuel": [FuelOut(**fuel_out(f)).model_dump(mode="json") for f in fuel],
        "maintenance": [MaintenanceOut(**maintenance_out(m)).model_dump(mode="json") for m in maintenance],
        "assignments": [
            {"driver_id": a.driver_id, "driver_name": a.driver.name,
             "start_date": a.start_date.isoformat() + "Z",
             "end_date": a.end_date.isoformat() + "Z" if a.end_date else None}
            for a in assignments
        ],
    }
