"""Transaction lab demonstrations: COMMIT, ROLLBACK and concurrent updates.

Every demo works on ONE hidden test vehicle (is_demo = TRUE), so nothing here
can damage real fleet data. Reports and lists exclude this vehicle.
"""
import threading
import time
from datetime import date
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..models import (
    AuditStatus,
    Expense,
    ExpenseCategory,
    FuelRecord,
    FuelType,
    MaintenanceRecord,
    User,
    Vehicle,
    VehicleStatus,
)
from .audit import log_in_transaction, log_separately, short_db_error

DEMO_REGISTRATION = "LAB00DEMO1"
BOOKING_PREFIX = "Lab booking charge"


class Timeline:
    """Thread-safe list of timestamped steps shown on the transaction lab page."""

    def __init__(self) -> None:
        self.t0 = time.perf_counter()
        self._steps: list[dict] = []
        self._lock = threading.Lock()

    def add(self, actor: str, action: str, sql: str | None = None, outcome: str = "") -> None:
        with self._lock:
            self._steps.append({"t_ms": round((time.perf_counter() - self.t0) * 1000),
                                "actor": actor, "action": action, "sql": sql, "outcome": outcome})

    def steps(self) -> list[dict]:
        with self._lock:
            return sorted(self._steps, key=lambda s: s["t_ms"])


def ensure_demo_vehicle() -> int:
    with SessionLocal() as s:
        vid = s.scalar(select(Vehicle.id).where(Vehicle.registration_no == DEMO_REGISTRATION))
        if vid:
            return vid
        try:
            v = Vehicle(registration_no=DEMO_REGISTRATION, model="Transaction lab test vehicle",
                        fuel_type=FuelType.DIESEL, status=VehicleStatus.AVAILABLE,
                        odometer_km=Decimal("0"), is_demo=True)
            s.add(v)
            s.commit()
            return v.id
        except IntegrityError:  # another request created it at the same moment
            s.rollback()
            return s.scalar(select(Vehicle.id).where(Vehicle.registration_no == DEMO_REGISTRATION))


def snapshot(vehicle_id: int) -> dict:
    """Read committed state through a SEPARATE connection, like a second user would."""
    with SessionLocal() as s:
        v = s.get(Vehicle, vehicle_id)
        count, total = s.execute(select(func.count(Expense.id), func.coalesce(func.sum(Expense.amount), 0))
                                 .where(Expense.vehicle_id == vehicle_id)).one()
        bookings = s.scalar(select(func.count(Expense.id)).where(
            Expense.vehicle_id == vehicle_id, Expense.description.like(f"{BOOKING_PREFIX}%")))
        return {"vehicle_status": v.status.value, "odometer_km": float(v.odometer_km),
                "expense_rows": int(count), "expense_total": float(total), "booking_charges": int(bookings)}


def _multi_step_writes(db: Session, vid: int, user: User, tl: Timeline, label: str) -> None:
    """Steps shared by the commit and rollback demos: lock, insert, update."""
    v = db.scalar(select(Vehicle).where(Vehicle.id == vid).with_for_update()
                  .execution_options(populate_existing=True))
    tl.add("Transaction", "Lock the test vehicle row",
           "SELECT * FROM vehicles WHERE id = :vid FOR UPDATE;", f"odometer is {float(v.odometer_km)} km")
    expense = Expense(vehicle_id=vid, category=ExpenseCategory.OTHER, amount=Decimal("250.00"),
                      expense_date=date.today(), description=f"Transaction lab: {label}", created_by=user.id)
    db.add(expense)
    db.flush()
    tl.add("Transaction", "Insert an expense of ₹250",
           "INSERT INTO expenses (vehicle_id, category, amount, ...) VALUES (:vid, 'OTHER', 250.00, ...);",
           f"row #{expense.id} written, not yet committed")
    v.odometer_km = v.odometer_km + Decimal("10")
    db.flush()
    tl.add("Transaction", "Add 10 km to the odometer",
           "UPDATE vehicles SET odometer_km = odometer_km + 10, version = version + 1 WHERE id = :vid;",
           f"odometer is now {float(v.odometer_km)} km inside this transaction")
    other = snapshot(vid)
    tl.add("Another connection", "Read the same vehicle before COMMIT", "SELECT odometer_km FROM vehicles ...;",
           f"still sees {other['odometer_km']} km: uncommitted changes are invisible to others (isolation)")


def run_commit_demo(db: Session, user: User) -> dict:
    vid = ensure_demo_vehicle()
    tl = Timeline()
    before = snapshot(vid)
    tl.add("System", "Record the starting state", None,
           f"odometer {before['odometer_km']} km, {before['expense_rows']} expense rows")
    started = time.perf_counter()
    tl.add("Transaction", "Begin", "START TRANSACTION;")
    try:
        _multi_step_writes(db, vid, user, tl, "commit demo")
        audit = log_in_transaction(db, user_id=user.id, operation="LAB_COMMIT_DEMO", entity="vehicle",
                                   entity_id=vid, message="Commit demo: expense + odometer update",
                                   details=None, duration_ms=round((time.perf_counter() - started) * 1000))
        db.commit()
        tl.add("Transaction", "Commit", "COMMIT;", "both changes are now permanent and visible to everyone")
    except Exception as exc:
        db.rollback()
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"Commit demo failed: {short_db_error(exc)}")
    after = snapshot(vid)
    tl.add("System", "Read the final state from a separate connection", None,
           f"odometer {after['odometer_km']} km, {after['expense_rows']} expense rows")
    return {"operation": "COMMIT_DEMO", "final_status": "COMMITTED",
            "message": "Both writes were committed together. A separate connection now sees them.",
            "steps": tl.steps(), "before": before, "after": after, "audit_ids": [audit.id]}


def run_rollback_demo(db: Session, user: User, failure: str) -> dict:
    vid = ensure_demo_vehicle()
    tl = Timeline()
    before = snapshot(vid)
    tl.add("System", "Record the starting state", None,
           f"odometer {before['odometer_km']} km, {before['expense_rows']} expense rows")
    started = time.perf_counter()
    tl.add("Transaction", "Begin", "START TRANSACTION;")
    error_text = ""
    try:
        _multi_step_writes(db, vid, user, tl, "rollback demo")
        if failure == "foreign_key":
            tl.add("Transaction", "Insert a fuel record for a vehicle that does not exist",
                   "INSERT INTO fuel_records (vehicle_id, ...) VALUES (999999999, ...);")
            db.add(FuelRecord(vehicle_id=999_999_999, expense_id=999_999_999, quantity_l=Decimal("10"),
                              price_per_l=Decimal("90"), total_cost=Decimal("900"), odometer_km=Decimal("1")))
            db.flush()
        elif failure == "check_constraint":
            tl.add("Transaction", "Insert an expense with a negative amount",
                   "INSERT INTO expenses (..., amount, ...) VALUES (..., -50.00, ...);")
            db.add(Expense(vehicle_id=vid, category=ExpenseCategory.OTHER, amount=Decimal("-50.00"),
                           expense_date=date.today(), description="Transaction lab: invalid row"))
            db.flush()
        else:
            tl.add("Transaction", "Business rule check fails in application code", None)
            raise ValueError("Simulated failure: the payment service did not respond")
        raise RuntimeError("The failing step unexpectedly succeeded")  # e.g. MySQL older than 8.0.16
    except (IntegrityError, ValueError) as exc:
        error_text = short_db_error(exc)
        tl.add("Database" if isinstance(exc, IntegrityError) else "Application", "Error raised", None, error_text)
    except RuntimeError as exc:
        error_text = str(exc)
        tl.add("System", "Warning", None,
               "The database accepted the invalid row. CHECK constraints need MySQL 8.0.16 or newer.")
    db.rollback()
    tl.add("Transaction", "Roll back", "ROLLBACK;", "every change since START TRANSACTION is undone")

    audit_id = log_separately(user_id=user.id, operation="LAB_ROLLBACK_DEMO", status_=AuditStatus.ROLLED_BACK,
                              message=f"Rollback demo ({failure}): {error_text}"[:500], entity="vehicle",
                              entity_id=vid, duration_ms=round((time.perf_counter() - started) * 1000))
    tl.add("Audit log", "Write the failure record in a separate transaction",
           "INSERT INTO transaction_audit (...) VALUES (..., 'ROLLED_BACK', ...); COMMIT;",
           f"audit row #{audit_id} survives because it was not part of the rolled-back transaction")
    after = snapshot(vid)
    unchanged = after == before
    tl.add("System", "Read the final state from a separate connection", None,
           f"odometer {after['odometer_km']} km, {after['expense_rows']} expense rows: "
           + ("identical to the start" if unchanged else "DIFFERENT from the start"))
    return {"operation": "ROLLBACK_DEMO", "final_status": "ROLLED_BACK" if unchanged else "INCONSISTENT",
            "message": ("Neither the expense nor the odometer change persisted. The database is exactly as it was."
                        if unchanged else "State changed despite rollback. Check your MySQL version and engine."),
            "steps": tl.steps(), "before": before, "after": after, "audit_ids": [audit_id] if audit_id else []}


def _booking_worker(actor: str, mode: str, vid: int, tl: Timeline, delay: float, hold: float,
                    results: dict) -> None:
    """One simulated user trying to book the test vehicle."""
    time.sleep(delay)
    with SessionLocal() as s:
        try:
            tl.add(actor, "Begin", "START TRANSACTION;")
            if mode == "pessimistic":
                t = time.perf_counter()
                current = s.execute(select(Vehicle.status).where(Vehicle.id == vid).with_for_update()).scalar_one()
                waited = round((time.perf_counter() - t) * 1000)
                tl.add(actor, "Read status with an exclusive row lock",
                       "SELECT status FROM vehicles WHERE id = :vid FOR UPDATE;",
                       f"saw {current.value}" + (f" after waiting {waited} ms for the other lock" if waited > 50 else ""))
            else:
                current = s.execute(select(Vehicle.status).where(Vehicle.id == vid)).scalar_one()
                tl.add(actor, "Read status without a lock", "SELECT status FROM vehicles WHERE id = :vid;",
                       f"saw {current.value}")

            if current != VehicleStatus.AVAILABLE:
                s.rollback()
                tl.add(actor, "Vehicle already taken, roll back", "ROLLBACK;", "booking refused")
                results[actor] = "CONFLICT"
                return

            time.sleep(hold)  # pretend to do other work, widening the race window
            tl.add(actor, "Other booking checks (simulated delay)", None, f"{round(hold * 1000)} ms")

            if mode == "conditional":
                res = s.execute(update(Vehicle).where(Vehicle.id == vid, Vehicle.status == VehicleStatus.AVAILABLE)
                                .values(status=VehicleStatus.IN_USE, version=Vehicle.version + 1)
                                .execution_options(synchronize_session=False))
                if res.rowcount != 1:
                    s.rollback()
                    tl.add(actor, "Conditional update matched 0 rows",
                           "UPDATE vehicles SET status = 'IN_USE' WHERE id = :vid AND status = 'AVAILABLE';",
                           "someone else booked it first, ROLLBACK")
                    results[actor] = "CONFLICT"
                    return
                tl.add(actor, "Conditional update matched 1 row",
                       "UPDATE vehicles SET status = 'IN_USE' WHERE id = :vid AND status = 'AVAILABLE';", "booked")
            else:
                s.execute(update(Vehicle).where(Vehicle.id == vid)
                          .values(status=VehicleStatus.IN_USE, version=Vehicle.version + 1)
                          .execution_options(synchronize_session=False))
                tl.add(actor, "Mark vehicle in use", "UPDATE vehicles SET status = 'IN_USE' WHERE id = :vid;", "booked")

            s.add(Expense(vehicle_id=vid, category=ExpenseCategory.OTHER, amount=Decimal("500.00"),
                          expense_date=date.today(), description=f"{BOOKING_PREFIX} ({actor})"))
            s.flush()
            tl.add(actor, "Charge the booking fee", "INSERT INTO expenses (...) VALUES (..., 500.00, ...);", "₹500")
            s.commit()
            tl.add(actor, "Commit", "COMMIT;", "booking confirmed")
            results[actor] = "SUCCESS"
        except Exception as exc:
            s.rollback()
            tl.add(actor, "Error, roll back", "ROLLBACK;", short_db_error(exc))
            results[actor] = "ERROR"


def run_concurrency_demo(user: User, mode: str) -> dict:
    vid = ensure_demo_vehicle()
    with SessionLocal() as s:  # start from a known state: vehicle free, no booking charges
        s.execute(update(Vehicle).where(Vehicle.id == vid)
                  .values(status=VehicleStatus.AVAILABLE, version=Vehicle.version + 1)
                  .execution_options(synchronize_session=False))
        s.execute(delete(Expense).where(Expense.vehicle_id == vid, Expense.description.like(f"{BOOKING_PREFIX}%"))
                  .execution_options(synchronize_session=False))
        s.commit()

    tl = Timeline()
    before = snapshot(vid)
    tl.add("System", "Reset the test vehicle", None, "status AVAILABLE, no booking charges")
    results: dict[str, str] = {}
    # User B starts 150 ms after User A. Both hold their transaction open for 600 ms,
    # so their transactions overlap and the race is visible on every run.
    threads = [
        threading.Thread(target=_booking_worker, args=("User A", mode, vid, tl, 0.0, 0.6, results)),
        threading.Thread(target=_booking_worker, args=("User B", mode, vid, tl, 0.15, 0.6, results)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)

    after = snapshot(vid)
    successes = sum(1 for r in results.values() if r == "SUCCESS")
    conflicts = sum(1 for r in results.values() if r == "CONFLICT")

    if successes >= 2:
        final, message = "DOUBLE_BOOKED", (
            "Both users read AVAILABLE before either one wrote, so both committed. The vehicle was booked "
            f"twice and {after['booking_charges']} booking fees were charged. This is a race condition.")
    elif successes == 1 and conflicts == 1:
        final, message = "PROTECTED", (
            "Exactly one booking succeeded and the other was refused. "
            + ("The row lock made User B wait, then it saw the vehicle was taken."
               if mode == "pessimistic" else
               "The WHERE status = 'AVAILABLE' condition made User B's update match 0 rows."))
    else:
        final, message = "ERROR", f"Unexpected result: {results}"

    audit_ids = []
    for actor, outcome in sorted(results.items()):
        aid = log_separately(
            user_id=user.id, operation=f"LAB_CONCURRENCY_{mode.upper()}",
            status_=AuditStatus.COMMITTED if outcome == "SUCCESS" else AuditStatus.ROLLED_BACK,
            message=f"{actor}: {outcome.lower()} ({mode} mode)", entity="vehicle", entity_id=vid)
        if aid:
            audit_ids.append(aid)
    return {"operation": f"CONCURRENCY_{mode.upper()}", "final_status": final, "message": message,
            "steps": tl.steps(), "before": before, "after": after, "audit_ids": audit_ids}


def reset_demo(user: User) -> dict:
    vid = ensure_demo_vehicle()
    with SessionLocal() as s:
        s.execute(delete(FuelRecord).where(FuelRecord.vehicle_id == vid))
        s.execute(delete(MaintenanceRecord).where(MaintenanceRecord.vehicle_id == vid))
        s.execute(delete(Expense).where(Expense.vehicle_id == vid))
        s.execute(update(Vehicle).where(Vehicle.id == vid)
                  .values(status=VehicleStatus.AVAILABLE, odometer_km=Decimal("0"), version=Vehicle.version + 1)
                  .execution_options(synchronize_session=False))
        log_in_transaction(s, user_id=user.id, operation="LAB_RESET", entity="vehicle", entity_id=vid,
                           message="Transaction lab test data cleared", details=None, duration_ms=None)
        s.commit()
    return {"message": "Test vehicle reset: status AVAILABLE, odometer 0 km, no expenses.", "state": snapshot(vid)}
