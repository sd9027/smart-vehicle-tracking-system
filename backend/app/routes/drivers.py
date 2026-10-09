"""Driver CRUD and history."""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from ..database import get_db
from ..deps import get_current_user, require_admin, require_manager
from ..models import Driver, DriverStatus, Trip, User, VehicleAssignment, utcnow
from ..schemas import DriverCreate, DriverOut, DriverUpdate, TripOut, VehicleBrief
from ..services.audit import transactional
from ..services.queries import lock_driver
from ..services.serializers import trip_out

router = APIRouter(prefix="/api/drivers", tags=["drivers"])


def _driver_out(driver: Driver, assignment: VehicleAssignment | None) -> DriverOut:
    out = DriverOut.model_validate(driver)
    if assignment is not None:
        out.assigned_vehicle = VehicleBrief(id=assignment.vehicle.id,
                                            registration_no=assignment.vehicle.registration_no)
    return out


def _assignment_for(db: Session, driver_id: int) -> VehicleAssignment | None:
    return db.scalar(select(VehicleAssignment)
                     .where(VehicleAssignment.driver_id == driver_id, VehicleAssignment.end_date.is_(None))
                     .options(selectinload(VehicleAssignment.vehicle)))


@router.get("", response_model=list[DriverOut])
def list_drivers(
    status_: DriverStatus | None = Query(default=None, alias="status"),
    q: str | None = Query(default=None, max_length=50),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    stmt = select(Driver).order_by(Driver.name)
    if status_:
        stmt = stmt.where(Driver.status == status_)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Driver.name.ilike(like), Driver.license_no.ilike(like), Driver.phone.ilike(like)))
    drivers = db.scalars(stmt).all()
    assignments = {a.driver_id: a for a in db.scalars(
        select(VehicleAssignment).where(VehicleAssignment.end_date.is_(None))
        .options(selectinload(VehicleAssignment.vehicle)))}
    return [_driver_out(d, assignments.get(d.id)) for d in drivers]


@router.get("/{driver_id}", response_model=DriverOut)
def get_driver(driver_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    driver = db.get(Driver, driver_id)
    if driver is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Driver not found.")
    return _driver_out(driver, _assignment_for(db, driver_id))


@router.get("/{driver_id}/trips", response_model=list[TripOut])
def driver_trips(driver_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    trips = db.scalars(select(Trip).where(Trip.driver_id == driver_id)
                       .options(selectinload(Trip.vehicle), selectinload(Trip.driver))
                       .order_by(Trip.created_at.desc()).limit(50)).all()
    return [trip_out(t) for t in trips]


@router.post("", response_model=DriverOut, status_code=status.HTTP_201_CREATED)
def create_driver(body: DriverCreate, db: Session = Depends(get_db), user: User = Depends(require_manager)):
    with transactional(db, user, "CREATE_DRIVER", "driver") as tx:
        if db.scalar(select(Driver.id).where(Driver.license_no == body.license_no)):
            raise HTTPException(status.HTTP_409_CONFLICT, "A driver with this licence number already exists.")
        driver = Driver(name=body.name.strip(), license_no=body.license_no,
                        license_expiry=body.license_expiry, phone=body.phone)
        db.add(driver)
        db.flush()
        tx.entity_id = driver.id
        tx.message = f"Added driver {driver.name}"
    return _driver_out(driver, None)


@router.put("/{driver_id}", response_model=DriverOut)
def update_driver(driver_id: int, body: DriverUpdate, db: Session = Depends(get_db),
                  user: User = Depends(require_manager)):
    with transactional(db, user, "UPDATE_DRIVER", "driver", driver_id) as tx:
        driver = lock_driver(db, driver_id)
        if driver.version != body.version:
            raise HTTPException(status.HTTP_409_CONFLICT,
                                "This driver was changed by someone else after you opened it. "
                                "Close the form, reload and try again.")
        changes = {}
        for field in ("name", "license_expiry", "phone"):
            value = getattr(body, field)
            if value is not None and value != getattr(driver, field):
                setattr(driver, field, value.strip() if isinstance(value, str) else value)
                changes[field] = str(value)
        if body.status is not None and body.status != driver.status.value:
            if driver.status == DriverStatus.ON_TRIP:
                raise HTTPException(status.HTTP_409_CONFLICT,
                                    "This driver is on a trip. Complete or cancel the trip first.")
            driver.status = DriverStatus(body.status)
            changes["status"] = body.status
            if driver.status == DriverStatus.INACTIVE:
                _end_driver_assignment(db, driver.id)
        tx.details = changes
        tx.message = f"Updated {driver.name}" if changes else "No changes"
    return _driver_out(driver, _assignment_for(db, driver_id))


@router.delete("/{driver_id}", response_model=DriverOut)
def deactivate_driver(driver_id: int, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    with transactional(db, user, "DEACTIVATE_DRIVER", "driver", driver_id) as tx:
        driver = lock_driver(db, driver_id)
        if driver.status == DriverStatus.ON_TRIP:
            raise HTTPException(status.HTTP_409_CONFLICT,
                                "This driver is on a trip. Complete or cancel the trip first.")
        driver.status = DriverStatus.INACTIVE
        _end_driver_assignment(db, driver.id)
        tx.message = f"Deactivated {driver.name}"
    return _driver_out(driver, None)


def _end_driver_assignment(db: Session, driver_id: int) -> None:
    for a in db.scalars(select(VehicleAssignment).where(
            VehicleAssignment.driver_id == driver_id, VehicleAssignment.end_date.is_(None)).with_for_update()):
        a.end_date = utcnow()
    db.flush()
