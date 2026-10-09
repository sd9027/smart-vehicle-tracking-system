"""Reports: monthly costs, vehicle utilisation and CSV export.

Aggregation (SUM, COUNT, GROUP BY) is done by the database, not in Python.
"""
import csv
import io
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import extract, func, select
from sqlalchemy.orm import Session, selectinload

from ..database import get_db
from ..deps import get_current_user
from ..models import Expense, ExpenseCategory, Trip, TripStatus, User, Vehicle, VehicleStatus, utcnow

router = APIRouter(prefix="/api/reports", tags=["reports"])

CATEGORIES = [c.value for c in ExpenseCategory]


def month_keys(months: int, today: date | None = None) -> list[tuple[int, int]]:
    today = today or date.today()
    y, m = today.year, today.month
    keys = []
    for _ in range(months):
        keys.append((y, m))
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return list(reversed(keys))


def monthly_expenses(db: Session, months: int) -> dict:
    keys = month_keys(months)
    start = date(keys[0][0], keys[0][1], 1)
    year = extract("year", Expense.expense_date)
    month = extract("month", Expense.expense_date)
    # SELECT YEAR(d), MONTH(d), category, SUM(amount) ... GROUP BY YEAR(d), MONTH(d), category
    rows = db.execute(
        select(year.label("y"), month.label("m"), Expense.category, func.sum(Expense.amount))
        .join(Vehicle, Vehicle.id == Expense.vehicle_id)
        .where(Vehicle.is_demo.is_(False), Expense.expense_date >= start)
        .group_by(year, month, Expense.category)
    ).all()
    table = {f"{y:04d}-{m:02d}": {c: 0.0 for c in CATEGORIES} for y, m in keys}
    for y, m, category, total in rows:
        key = f"{int(y):04d}-{int(m):02d}"
        if key in table:
            table[key][category.value] = round(float(total or 0), 2)
    result_rows = []
    totals = {c: 0.0 for c in CATEGORIES}
    for key, values in table.items():
        row = {"month": key, **values, "total": round(sum(values.values()), 2)}
        result_rows.append(row)
        for c in CATEGORIES:
            totals[c] += values[c]
    totals = {c: round(v, 2) for c, v in totals.items()}
    totals["total"] = round(sum(totals[c] for c in CATEGORIES), 2)
    return {"months": list(table.keys()), "categories": CATEGORIES, "rows": result_rows, "totals": totals}


def utilisation(db: Session, days: int) -> list[dict]:
    since_dt = utcnow() - timedelta(days=days)
    since_date = date.today() - timedelta(days=days)
    vehicles = db.scalars(select(Vehicle).where(Vehicle.is_demo.is_(False)).order_by(Vehicle.registration_no)).all()

    trip_stats = {vid: (count, float(dist or 0)) for vid, count, dist in db.execute(
        select(Trip.vehicle_id, func.count(Trip.id), func.sum(Trip.distance_km))
        .where(Trip.status == TripStatus.COMPLETED, Trip.end_time >= since_dt)
        .group_by(Trip.vehicle_id))}

    # Hours on the road: summed in Python because date arithmetic differs between MySQL and SQLite.
    hours: dict[int, float] = {}
    for vid, start, end in db.execute(
            select(Trip.vehicle_id, Trip.start_time, Trip.end_time)
            .where(Trip.status == TripStatus.COMPLETED, Trip.end_time >= since_dt,
                   Trip.start_time.is_not(None))):
        hours[vid] = hours.get(vid, 0.0) + (end - start).total_seconds() / 3600

    costs: dict[int, dict[str, float]] = {}
    for vid, category, total in db.execute(
            select(Expense.vehicle_id, Expense.category, func.sum(Expense.amount))
            .where(Expense.expense_date >= since_date)
            .group_by(Expense.vehicle_id, Expense.category)):
        costs.setdefault(vid, {})[category.value] = float(total or 0)

    result = []
    for v in vehicles:
        count, distance = trip_stats.get(v.id, (0, 0.0))
        c = costs.get(v.id, {})
        fuel = c.get("FUEL", 0.0)
        maintenance = c.get("MAINTENANCE", 0.0)
        other = sum(val for k, val in c.items() if k not in ("FUEL", "MAINTENANCE"))
        total_cost = fuel + maintenance + other
        active_hours = hours.get(v.id, 0.0)
        result.append({
            "vehicle_id": v.id,
            "registration_no": v.registration_no,
            "model": v.model,
            "status": v.status.value,
            "completed_trips": count,
            "distance_km": round(distance, 1),
            "active_hours": round(active_hours, 1),
            "utilization_pct": round(min(100.0, active_hours / (days * 24) * 100), 1),
            "fuel_cost": round(fuel, 2),
            "maintenance_cost": round(maintenance, 2),
            "other_cost": round(other, 2),
            "total_cost": round(total_cost, 2),
            "cost_per_km": round(total_cost / distance, 2) if distance > 0 else None,
        })
    return result


@router.get("/expenses")
def expenses_report(months: int = Query(default=6, ge=1, le=24), db: Session = Depends(get_db),
                    _: User = Depends(get_current_user)):
    return monthly_expenses(db, months)


@router.get("/utilization")
def utilization_report(days: int = Query(default=30, ge=1, le=365), db: Session = Depends(get_db),
                       _: User = Depends(get_current_user)):
    return utilisation(db, days)


@router.get("/summary")
def summary(days: int = Query(default=30, ge=1, le=365), db: Session = Depends(get_db),
            _: User = Depends(get_current_user)):
    rows = utilisation(db, days)
    distance = sum(r["distance_km"] for r in rows)
    cost = sum(r["total_cost"] for r in rows)
    active = [r for r in rows if r["status"] != VehicleStatus.INACTIVE.value]
    return {
        "days": days,
        "completed_trips": sum(r["completed_trips"] for r in rows),
        "distance_km": round(distance, 1),
        "total_cost": round(cost, 2),
        "cost_per_km": round(cost / distance, 2) if distance else None,
        "avg_utilization_pct": round(sum(r["utilization_pct"] for r in active) / len(active), 1) if active else 0,
    }


def _safe_cell(value) -> str:
    """Stop spreadsheet formula injection: cells starting with = + - @ are prefixed with '."""
    text = "" if value is None else str(value)
    if text and text[0] in "=+-@\t\r":
        return "'" + text
    return text


def _csv_response(filename: str, header: list[str], rows: list[list]) -> StreamingResponse:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header)
    for row in rows:
        writer.writerow([_safe_cell(v) for v in row])
    return StreamingResponse(
        iter(["\ufeff" + buffer.getvalue()]),  # BOM so Excel reads the ₹ sign and UTF-8 correctly
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/export")
def export_csv(
    kind: str = Query(pattern="^(expenses|trips|utilization)$"),
    days: int = Query(default=30, ge=1, le=730),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    stamp = datetime.now().strftime("%Y%m%d")
    if kind == "utilization":
        rows = utilisation(db, days)
        header = list(rows[0].keys()) if rows else ["vehicle_id"]
        return _csv_response(f"tracktech-utilization-{days}d-{stamp}.csv", header,
                             [[r[h] for h in header] for r in rows])

    if kind == "expenses":
        since = date.today() - timedelta(days=days)
        expenses = db.scalars(select(Expense).join(Vehicle).where(Vehicle.is_demo.is_(False),
                                                                 Expense.expense_date >= since)
                              .options(selectinload(Expense.vehicle)).order_by(Expense.expense_date)).all()
        return _csv_response(
            f"tracktech-expenses-{days}d-{stamp}.csv",
            ["id", "date", "vehicle", "category", "amount_inr", "description"],
            [[e.id, e.expense_date.isoformat(), e.vehicle.registration_no, e.category.value,
              f"{e.amount:.2f}", e.description] for e in expenses],
        )

    since_dt = utcnow() - timedelta(days=days)
    trips = db.scalars(select(Trip).where(Trip.created_at >= since_dt)
                       .options(selectinload(Trip.vehicle), selectinload(Trip.driver))
                       .order_by(Trip.created_at)).all()
    return _csv_response(
        f"tracktech-trips-{days}d-{stamp}.csv",
        ["id", "vehicle", "driver", "source", "destination", "status", "start_utc", "end_utc", "distance_km"],
        [[t.id, t.vehicle.registration_no, t.driver.name, t.source, t.destination, t.status.value,
          t.start_time.isoformat() if t.start_time else "", t.end_time.isoformat() if t.end_time else "",
          f"{t.distance_km:.2f}" if t.distance_km is not None else ""] for t in trips],
    )
