"""Transaction lab endpoints, the audit log and consistency checks."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import Session, aliased, selectinload

from ..database import get_db
from ..deps import get_current_user, require_manager
from ..models import (
    AuditStatus,
    Driver,
    DriverStatus,
    Expense,
    ExpenseCategory,
    FuelRecord,
    MaintenanceRecord,
    TransactionAudit,
    Trip,
    TripStatus,
    User,
    Vehicle,
    VehicleStatus,
)
from ..schemas import AuditOut, ConcurrencyDemoIn, ConsistencyCheck, DemoResult, RollbackDemoIn
from ..services import lab
from ..services.queries import OPEN_TRIP_STATUSES

router = APIRouter(prefix="/api/transactions", tags=["transactions"])


@router.get("", response_model=list[AuditOut])
def audit_log(
    status_: AuditStatus | None = Query(default=None, alias="status"),
    operation: str | None = Query(default=None, max_length=60),
    limit: int = Query(default=100, ge=1, le=1000),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    stmt = (select(TransactionAudit).options(selectinload(TransactionAudit.user))
            .order_by(TransactionAudit.id.desc()).limit(limit))
    if status_:
        stmt = stmt.where(TransactionAudit.status == status_)
    if operation:
        stmt = stmt.where(TransactionAudit.operation.like(f"{operation.upper()}%"))
    return [{
        "id": a.id, "user_id": a.user_id, "user_name": a.user.name if a.user else None,
        "operation": a.operation, "status": a.status, "entity": a.entity, "entity_id": a.entity_id,
        "message": a.message, "details": a.details, "duration_ms": a.duration_ms, "created_at": a.created_at,
    } for a in db.scalars(stmt)]


@router.post("/demo/commit", response_model=DemoResult)
def demo_commit(db: Session = Depends(get_db), user: User = Depends(require_manager)):
    return lab.run_commit_demo(db, user)


@router.post("/demo/rollback", response_model=DemoResult)
def demo_rollback(body: RollbackDemoIn, db: Session = Depends(get_db), user: User = Depends(require_manager)):
    return lab.run_rollback_demo(db, user, body.failure)


@router.post("/demo/concurrency", response_model=DemoResult)
def demo_concurrency(body: ConcurrencyDemoIn, user: User = Depends(require_manager)):
    return lab.run_concurrency_demo(user, body.mode)


@router.post("/demo/reset")
def demo_reset(user: User = Depends(require_manager)):
    return lab.reset_demo(user)


@router.get("/consistency", response_model=list[ConsistencyCheck])
def consistency_checks(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    """Queries that should always return 0 rows if every transaction kept the data consistent."""
    open_trip_for_vehicle = exists().where(Trip.vehicle_id == Vehicle.id, Trip.status.in_(OPEN_TRIP_STATUSES))
    open_trip_for_driver = exists().where(Trip.driver_id == Driver.id, Trip.status.in_(OPEN_TRIP_STATUSES))
    v = aliased(Vehicle)
    d = aliased(Driver)

    checks = [
        ("Vehicles in use have an open trip",
         "A vehicle marked IN_USE must belong to a scheduled or active trip.",
         "SELECT COUNT(*) FROM vehicles v WHERE v.status = 'IN_USE' AND v.is_demo = FALSE\n"
         "  AND NOT EXISTS (SELECT 1 FROM trips t WHERE t.vehicle_id = v.id\n"
         "                  AND t.status IN ('SCHEDULED','ACTIVE'));",
         select(func.count(Vehicle.id)).where(Vehicle.status == VehicleStatus.IN_USE,
                                              Vehicle.is_demo.is_(False), ~open_trip_for_vehicle)),
        ("Drivers on a trip have an open trip",
         "A driver marked ON_TRIP must belong to a scheduled or active trip.",
         "SELECT COUNT(*) FROM drivers d WHERE d.status = 'ON_TRIP'\n"
         "  AND NOT EXISTS (SELECT 1 FROM trips t WHERE t.driver_id = d.id\n"
         "                  AND t.status IN ('SCHEDULED','ACTIVE'));",
         select(func.count(Driver.id)).where(Driver.status == DriverStatus.ON_TRIP, ~open_trip_for_driver)),
        ("Open trips hold their vehicle and driver",
         "Every scheduled or active trip's vehicle is IN_USE and its driver is ON_TRIP.",
         "SELECT COUNT(*) FROM trips t JOIN vehicles v ON v.id = t.vehicle_id\n"
         "  JOIN drivers d ON d.id = t.driver_id\n"
         "  WHERE t.status IN ('SCHEDULED','ACTIVE')\n"
         "  AND (v.status <> 'IN_USE' OR d.status <> 'ON_TRIP');",
         select(func.count(Trip.id)).join(v, v.id == Trip.vehicle_id).join(d, d.id == Trip.driver_id)
         .where(Trip.status.in_(OPEN_TRIP_STATUSES),
                or_(v.status != VehicleStatus.IN_USE, d.status != DriverStatus.ON_TRIP))),
        ("Fuel records match their expenses",
         "Each fuel record has a FUEL expense with exactly the same amount.",
         "SELECT COUNT(*) FROM fuel_records f JOIN expenses e ON e.id = f.expense_id\n"
         "  WHERE e.category <> 'FUEL' OR e.amount <> f.total_cost;",
         select(func.count(FuelRecord.id)).join(Expense, Expense.id == FuelRecord.expense_id)
         .where(or_(Expense.category != ExpenseCategory.FUEL, Expense.amount != FuelRecord.total_cost))),
        ("Maintenance records match their expenses",
         "Each service record has a MAINTENANCE expense with exactly the same amount.",
         "SELECT COUNT(*) FROM maintenance_records m JOIN expenses e ON e.id = m.expense_id\n"
         "  WHERE e.category <> 'MAINTENANCE' OR e.amount <> m.cost;",
         select(func.count(MaintenanceRecord.id)).join(Expense, Expense.id == MaintenanceRecord.expense_id)
         .where(or_(Expense.category != ExpenseCategory.MAINTENANCE, Expense.amount != MaintenanceRecord.cost))),
        ("Completed trips are fully recorded",
         "A completed trip has a start time, an end time after it, and a distance.",
         "SELECT COUNT(*) FROM trips WHERE status = 'COMPLETED'\n"
         "  AND (start_time IS NULL OR end_time IS NULL\n"
         "       OR end_time < start_time OR distance_km IS NULL);",
         select(func.count(Trip.id)).where(Trip.status == TripStatus.COMPLETED,
                                           or_(Trip.start_time.is_(None), Trip.end_time.is_(None),
                                               Trip.end_time < Trip.start_time, Trip.distance_km.is_(None)))),
        ("No vehicle is double-booked",
         "No vehicle appears in more than one scheduled or active trip.",
         "SELECT COUNT(*) FROM (SELECT vehicle_id FROM trips\n"
         "  WHERE status IN ('SCHEDULED','ACTIVE')\n"
         "  GROUP BY vehicle_id HAVING COUNT(*) > 1) AS x;",
         select(func.count()).select_from(
             select(Trip.vehicle_id).where(Trip.status.in_(OPEN_TRIP_STATUSES))
             .group_by(Trip.vehicle_id).having(func.count(Trip.id) > 1).subquery())),
    ]
    results = []
    for name, description, sql, query in checks:
        violations = int(db.scalar(query) or 0)
        results.append({"name": name, "description": description, "sql": sql,
                        "violations": violations, "passed": violations == 0})
    return results
