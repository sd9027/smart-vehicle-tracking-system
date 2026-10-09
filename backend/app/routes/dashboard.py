"""Summary numbers and alerts for the dashboard."""
from datetime import date, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..database import get_db
from ..deps import get_current_user
from ..models import (
    Driver,
    DriverStatus,
    Expense,
    ExpenseCategory,
    Trip,
    TripStatus,
    User,
    Vehicle,
    VehicleStatus,
    utcnow,
)
from ..schemas import TripOut
from ..services.queries import latest_locations, upcoming_services
from ..services.serializers import trip_out
from .reports import monthly_expenses
from .tracking import trip_progress

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/stats")
def dashboard_stats(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    today = date.today()
    month_start = today.replace(day=1)

    by_status = {s.value: 0 for s in VehicleStatus}
    for status_, count in db.execute(select(Vehicle.status, func.count(Vehicle.id))
                                     .where(Vehicle.is_demo.is_(False)).group_by(Vehicle.status)):
        by_status[status_.value] = count

    driver_counts = {s.value: 0 for s in DriverStatus}
    for status_, count in db.execute(select(Driver.status, func.count(Driver.id)).group_by(Driver.status)):
        driver_counts[status_.value] = count

    trip_counts = {s.value: 0 for s in TripStatus}
    for status_, count in db.execute(select(Trip.status, func.count(Trip.id))
                                     .where(Trip.status.in_([TripStatus.SCHEDULED, TripStatus.ACTIVE]))
                                     .group_by(Trip.status)):
        trip_counts[status_.value] = count
    completed_this_month = db.scalar(select(func.count(Trip.id)).where(
        Trip.status == TripStatus.COMPLETED, Trip.end_time >= month_start)) or 0

    month_costs = {c.value: 0.0 for c in ExpenseCategory}
    for category, total in db.execute(
            select(Expense.category, func.sum(Expense.amount)).join(Vehicle, Vehicle.id == Expense.vehicle_id)
            .where(Vehicle.is_demo.is_(False), Expense.expense_date >= month_start).group_by(Expense.category)):
        month_costs[category.value] = round(float(total or 0), 2)

    # Six-month chart: fuel, maintenance and everything else.
    report = monthly_expenses(db, 6)
    monthly = [{"month": r["month"], "FUEL": r["FUEL"], "MAINTENANCE": r["MAINTENANCE"],
                "OTHER": round(r["total"] - r["FUEL"] - r["MAINTENANCE"], 2)} for r in report["rows"]]

    recent = db.scalars(select(Trip).options(selectinload(Trip.vehicle), selectinload(Trip.driver))
                        .order_by(Trip.created_at.desc()).limit(6)).all()

    return {
        "vehicles": {"total": sum(v for k, v in by_status.items() if k != "INACTIVE"), "by_status": by_status},
        "drivers": {"total": sum(v for k, v in driver_counts.items() if k != "INACTIVE"),
                    "available": driver_counts["AVAILABLE"], "on_trip": driver_counts["ON_TRIP"]},
        "trips": {"active": trip_counts["ACTIVE"], "scheduled": trip_counts["SCHEDULED"],
                  "completed_this_month": completed_this_month},
        "costs": {"fuel_this_month": month_costs["FUEL"],
                  "maintenance_this_month": month_costs["MAINTENANCE"],
                  "other_this_month": round(sum(v for k, v in month_costs.items()
                                                if k not in ("FUEL", "MAINTENANCE")), 2)},
        "monthly_costs": monthly,
        "recent_trips": [TripOut(**trip_out(t)).model_dump(mode="json") for t in recent],
        "alerts": _alerts(db, today),
    }


def _alerts(db: Session, today: date) -> list[dict]:
    alerts: list[dict] = []

    for d in db.scalars(select(Driver).where(Driver.status != DriverStatus.INACTIVE,
                                             Driver.license_expiry <= today + timedelta(days=30))
                        .order_by(Driver.license_expiry)):
        expired = d.license_expiry < today
        alerts.append({
            "level": "danger" if expired else "warning",
            "kind": "licence",
            "message": (f"{d.name}'s licence expired on {d.license_expiry:%d %b %Y}" if expired
                        else f"{d.name}'s licence expires on {d.license_expiry:%d %b %Y}"),
            "link": "/drivers",
        })

    for s in upcoming_services(db, days=7):
        overdue = s["days_left"] < 0
        alerts.append({
            "level": "danger" if overdue else "warning",
            "kind": "service",
            "message": (f"{s['vehicle_registration']} service overdue by {-s['days_left']} day(s)" if overdue
                        else f"{s['vehicle_registration']} service due in {s['days_left']} day(s)"),
            "link": "/expenses?tab=alerts",
        })

    for v in db.scalars(select(Vehicle).where(Vehicle.is_demo.is_(False),
                                              Vehicle.status == VehicleStatus.MAINTENANCE)):
        alerts.append({"level": "info", "kind": "maintenance",
                       "message": f"{v.registration_no} is in maintenance", "link": "/vehicles"})

    active = db.scalars(select(Trip).where(Trip.status == TripStatus.ACTIVE)
                        .options(selectinload(Trip.vehicle))).all()
    locations = latest_locations(db, [t.vehicle_id for t in active])
    for t in active:
        progress = trip_progress(t, locations.get(t.vehicle_id))
        if progress is not None and progress >= 0.99:
            alerts.append({"level": "info", "kind": "arrived",
                           "message": f"{t.vehicle.registration_no} reached {t.destination}. Mark trip #{t.id} complete.",
                           "link": "/trips"})

    stale_cutoff = utcnow() - timedelta(hours=2)
    for t in db.scalars(select(Trip).where(Trip.status == TripStatus.SCHEDULED, Trip.created_at < stale_cutoff)
                        .options(selectinload(Trip.vehicle))):
        alerts.append({"level": "warning", "kind": "scheduled",
                       "message": f"Trip #{t.id} for {t.vehicle.registration_no} was scheduled over 2 hours ago "
                                  "and has not started",
                       "link": "/trips"})
    return alerts
