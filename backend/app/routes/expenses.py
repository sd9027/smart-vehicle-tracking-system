"""Fuel purchases, maintenance and other expenses.

Fuel and maintenance entries are multi-step transactions: they insert the record,
insert the matching expense row and update the vehicle, all or nothing.
"""
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..database import get_db
from ..deps import get_current_user, require_admin, require_manager
from ..models import (
    Expense,
    ExpenseCategory,
    FuelRecord,
    FuelType,
    MaintenanceRecord,
    User,
    Vehicle,
    VehicleStatus,
)
from ..schemas import (
    ExpenseCreate,
    ExpenseOut,
    FuelCreate,
    FuelOut,
    MaintenanceCreate,
    MaintenanceOut,
    UpcomingService,
)
from ..services.audit import transactional
from ..services.queries import lock_vehicle, upcoming_services
from ..services.serializers import expense_out, fuel_out, maintenance_out

router = APIRouter(tags=["expenses"])


def _usable_vehicle(db: Session, vehicle_id: int) -> Vehicle:
    vehicle = lock_vehicle(db, vehicle_id)
    if vehicle.is_demo:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Vehicle not found.")
    if vehicle.status == VehicleStatus.INACTIVE:
        raise HTTPException(status.HTTP_409_CONFLICT, "This vehicle is inactive.")
    return vehicle


# ----------------------------- Fuel -----------------------------

@router.get("/api/fuel-records", response_model=list[FuelOut])
def list_fuel(vehicle_id: int | None = None, limit: int = Query(default=300, ge=1, le=2000),
              db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    stmt = (select(FuelRecord).join(Vehicle).where(Vehicle.is_demo.is_(False))
            .options(selectinload(FuelRecord.vehicle))
            .order_by(FuelRecord.recorded_at.desc()).limit(limit))
    if vehicle_id:
        stmt = stmt.where(FuelRecord.vehicle_id == vehicle_id)
    return [fuel_out(r) for r in db.scalars(stmt)]


@router.post("/api/fuel-records", response_model=FuelOut, status_code=status.HTTP_201_CREATED)
def add_fuel(body: FuelCreate, db: Session = Depends(get_db), user: User = Depends(require_manager)):
    with transactional(db, user, "ADD_FUEL", "fuel_record") as tx:
        vehicle = _usable_vehicle(db, body.vehicle_id)
        if vehicle.fuel_type == FuelType.ELECTRIC:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "Electric vehicles do not take fuel. Record charging as an expense instead.")
        if body.odometer_km < vehicle.odometer_km:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                f"Odometer {body.odometer_km} km is lower than the last reading "
                                f"({vehicle.odometer_km} km).")
        total = (body.quantity_l * body.price_per_l).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        expense = Expense(vehicle_id=vehicle.id, category=ExpenseCategory.FUEL, amount=total,
                          expense_date=date.today(), created_by=user.id,
                          description=f"{body.quantity_l} L at {body.price_per_l}/L"
                                      + (f", {body.station}" if body.station else ""))
        db.add(expense)
        db.flush()  # get expense.id for the fuel record's foreign key
        record = FuelRecord(vehicle=vehicle, expense_id=expense.id, quantity_l=body.quantity_l,
                            price_per_l=body.price_per_l, total_cost=total, odometer_km=body.odometer_km,
                            station=(body.station or None), created_by=user.id)
        db.add(record)
        vehicle.odometer_km = body.odometer_km
        db.flush()
        tx.entity_id = record.id
        tx.message = f"Fuel {body.quantity_l} L for {vehicle.registration_no}"
        tx.details = {"expense_id": expense.id, "total_cost": float(total)}
    return fuel_out(record)


@router.delete("/api/fuel-records/{record_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_fuel(record_id: int, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    with transactional(db, user, "DELETE_FUEL", "fuel_record", record_id):
        record = db.get(FuelRecord, record_id)
        if record is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Fuel record not found.")
        expense = db.get(Expense, record.expense_id)
        db.delete(record)
        db.flush()  # the fuel row references the expense, so it must go first
        if expense is not None:
            db.delete(expense)


# -------------------------- Maintenance --------------------------

@router.get("/api/maintenance", response_model=list[MaintenanceOut])
def list_maintenance(vehicle_id: int | None = None, limit: int = Query(default=300, ge=1, le=2000),
                     db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    stmt = (select(MaintenanceRecord).join(Vehicle).where(Vehicle.is_demo.is_(False))
            .options(selectinload(MaintenanceRecord.vehicle))
            .order_by(MaintenanceRecord.service_date.desc(), MaintenanceRecord.id.desc()).limit(limit))
    if vehicle_id:
        stmt = stmt.where(MaintenanceRecord.vehicle_id == vehicle_id)
    return [maintenance_out(r) for r in db.scalars(stmt)]


@router.get("/api/maintenance/upcoming", response_model=list[UpcomingService])
def list_upcoming(days: int = Query(default=30, ge=1, le=365), db: Session = Depends(get_db),
                  _: User = Depends(get_current_user)):
    return upcoming_services(db, days)


@router.post("/api/maintenance", response_model=MaintenanceOut, status_code=status.HTTP_201_CREATED)
def add_maintenance(body: MaintenanceCreate, db: Session = Depends(get_db), user: User = Depends(require_manager)):
    if body.next_service_date and body.next_service_date < body.service_date:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "The next service date must be on or after the service date.")
    if body.service_date > date.today():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "The service date cannot be in the future.")
    with transactional(db, user, "ADD_MAINTENANCE", "maintenance") as tx:
        vehicle = _usable_vehicle(db, body.vehicle_id)
        expense = Expense(vehicle_id=vehicle.id, category=ExpenseCategory.MAINTENANCE, amount=body.cost,
                          expense_date=body.service_date, created_by=user.id,
                          description=body.service_type.strip())
        db.add(expense)
        db.flush()
        record = MaintenanceRecord(vehicle=vehicle, expense_id=expense.id, service_type=body.service_type.strip(),
                                   description=body.description.strip(), service_date=body.service_date,
                                   cost=body.cost, odometer_km=body.odometer_km,
                                   next_service_date=body.next_service_date, created_by=user.id)
        db.add(record)
        if body.odometer_km is not None and body.odometer_km > vehicle.odometer_km:
            vehicle.odometer_km = body.odometer_km
        if body.put_in_maintenance:
            if vehicle.status == VehicleStatus.IN_USE:
                raise HTTPException(status.HTTP_409_CONFLICT,
                                    "The vehicle is on a trip, so it cannot be put into maintenance now.")
            vehicle.status = VehicleStatus.MAINTENANCE
        db.flush()
        tx.entity_id = record.id
        tx.message = f"{body.service_type} for {vehicle.registration_no}"
        tx.details = {"expense_id": expense.id, "cost": float(body.cost),
                      "put_in_maintenance": body.put_in_maintenance}
    return maintenance_out(record)


@router.delete("/api/maintenance/{record_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_maintenance(record_id: int, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    with transactional(db, user, "DELETE_MAINTENANCE", "maintenance", record_id):
        record = db.get(MaintenanceRecord, record_id)
        if record is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Maintenance record not found.")
        expense = db.get(Expense, record.expense_id)
        db.delete(record)
        db.flush()
        if expense is not None:
            db.delete(expense)


# ---------------------------- Expenses ----------------------------

@router.get("/api/expenses", response_model=list[ExpenseOut])
def list_expenses(
    category: ExpenseCategory | None = None,
    vehicle_id: int | None = None,
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
    limit: int = Query(default=500, ge=1, le=5000),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    stmt = (select(Expense).join(Vehicle).where(Vehicle.is_demo.is_(False))
            .options(selectinload(Expense.vehicle))
            .order_by(Expense.expense_date.desc(), Expense.id.desc()).limit(limit))
    if category:
        stmt = stmt.where(Expense.category == category)
    if vehicle_id:
        stmt = stmt.where(Expense.vehicle_id == vehicle_id)
    if date_from:
        stmt = stmt.where(Expense.expense_date >= date_from)
    if date_to:
        stmt = stmt.where(Expense.expense_date <= date_to)
    return [expense_out(e) for e in db.scalars(stmt)]


@router.post("/api/expenses", response_model=ExpenseOut, status_code=status.HTTP_201_CREATED)
def add_expense(body: ExpenseCreate, db: Session = Depends(get_db), user: User = Depends(require_manager)):
    if body.expense_date > date.today():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "The expense date cannot be in the future.")
    with transactional(db, user, "ADD_EXPENSE", "expense") as tx:
        vehicle = db.get(Vehicle, body.vehicle_id)
        if vehicle is None or vehicle.is_demo:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Vehicle not found.")
        expense = Expense(vehicle=vehicle, category=ExpenseCategory(body.category), amount=body.amount,
                          expense_date=body.expense_date, description=body.description.strip(),
                          created_by=user.id)
        db.add(expense)
        db.flush()
        tx.entity_id = expense.id
        tx.message = f"{body.category.title()} expense for {vehicle.registration_no}"
    return expense_out(expense)


@router.delete("/api/expenses/{expense_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_expense(expense_id: int, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    with transactional(db, user, "DELETE_EXPENSE", "expense", expense_id):
        expense = db.get(Expense, expense_id)
        if expense is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Expense not found.")
        if expense.category in (ExpenseCategory.FUEL, ExpenseCategory.MAINTENANCE):
            raise HTTPException(status.HTTP_409_CONFLICT,
                                "This expense belongs to a fuel or maintenance record. Delete that record instead.")
        db.delete(expense)
