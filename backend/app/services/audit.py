"""Transaction boundaries and the audit trail.

Design decision (important for the viva):
  * A SUCCESSFUL operation writes its audit row inside the same transaction, so the
    change and its audit row are committed together (atomically) or not at all.
  * A FAILED operation is rolled back first, and only then is its audit row written in
    a separate session/transaction. If we wrote it in the failing transaction, the
    ROLLBACK would erase the very record that explains the failure.
"""
import json
import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from ..database import SessionLocal
from ..models import AuditStatus, TransactionAudit, User

log = logging.getLogger("tracktech.audit")

# Friendly messages for constraint names (MySQL) and column names (SQLite tests).
_CONSTRAINT_MESSAGES = [
    (("uq_vehicles_registration", "vehicles.registration_no"), "A vehicle with this registration number already exists."),
    (("uq_drivers_license", "drivers.license_no"), "A driver with this licence number already exists."),
    (("uq_users_email", "users.email"), "An account with this email already exists."),
    (("uq_trips_open_vehicle", "trips.open_vehicle_id"), "This vehicle already has a scheduled or active trip."),
    (("uq_trips_open_driver", "trips.open_driver_id"), "This driver already has a scheduled or active trip."),
    (("uq_assign_open_vehicle", "vehicle_assignments.open_vehicle_id"), "This vehicle already has a current driver."),
    (("uq_assign_open_driver", "vehicle_assignments.open_driver_id"), "This driver is already assigned to another vehicle."),
    (("foreign key", "FOREIGN KEY"), "The record refers to something that does not exist."),
    (("chk_", "CHECK constraint"), "A value breaks a database rule (for example a negative amount)."),
]


def friendly_integrity_message(exc: IntegrityError) -> str:
    text = str(exc.orig)
    for needles, message in _CONSTRAINT_MESSAGES:
        if any(n in text for n in needles):
            return message
    return "The change conflicts with existing data."


def short_db_error(exc: Exception) -> str:
    text = str(getattr(exc, "orig", exc)).splitlines()[0]
    return text[:240]


def _details_json(details: dict[str, Any] | None) -> str | None:
    if not details:
        return None
    return json.dumps(details, default=str)[:4000]


def log_in_transaction(db: Session, *, user_id: int | None, operation: str, entity: str | None,
                       entity_id: int | None, message: str, details: dict | None, duration_ms: int | None) -> TransactionAudit:
    row = TransactionAudit(
        user_id=user_id, operation=operation, status=AuditStatus.COMMITTED, entity=entity,
        entity_id=entity_id, message=message[:500], details=_details_json(details), duration_ms=duration_ms,
    )
    db.add(row)
    return row


def log_separately(*, user_id: int | None, operation: str, status_: AuditStatus, message: str,
                   entity: str | None = None, entity_id: int | None = None,
                   details: dict | None = None, duration_ms: int | None = None) -> int | None:
    """Write an audit row in its own session so it survives any rollback elsewhere."""
    with SessionLocal() as s:
        try:
            row = TransactionAudit(
                user_id=user_id, operation=operation, status=status_, entity=entity, entity_id=entity_id,
                message=message[:500], details=_details_json(details), duration_ms=duration_ms,
            )
            s.add(row)
            s.commit()
            return row.id
        except Exception:  # auditing must never hide the original error
            s.rollback()
            log.exception("Could not write audit row for %s", operation)
            return None


@dataclass
class TxContext:
    entity_id: int | None = None
    message: str = "Committed"
    details: dict[str, Any] = field(default_factory=dict)


@contextmanager
def transactional(db: Session, user: User | None, operation: str, entity: str | None = None,
                  entity_id: int | None = None) -> Iterator[TxContext]:
    """Run the block as ONE transaction: commit if it finishes, roll back if anything fails.

    Usage:
        with transactional(db, user, "CREATE_TRIP", "trip") as tx:
            ...several reads/writes...
            tx.entity_id = trip.id
    """
    started = time.perf_counter()
    ctx = TxContext(entity_id=entity_id)
    user_id = user.id if user else None

    def elapsed() -> int:
        return round((time.perf_counter() - started) * 1000)

    def fail(message: str, http_exc: HTTPException) -> HTTPException:
        db.rollback()
        log_separately(user_id=user_id, operation=operation, status_=AuditStatus.ROLLED_BACK,
                       message=message, entity=entity, entity_id=ctx.entity_id,
                       details=ctx.details or None, duration_ms=elapsed())
        return http_exc

    try:
        yield ctx
        log_in_transaction(db, user_id=user_id, operation=operation, entity=entity,
                           entity_id=ctx.entity_id, message=ctx.message, details=ctx.details or None,
                           duration_ms=elapsed())
        db.commit()
    except HTTPException as exc:
        raise fail(str(exc.detail), exc)
    except StaleDataError:
        msg = "Someone else changed this record at the same moment. Reload and try again."
        raise fail(msg, HTTPException(status.HTTP_409_CONFLICT, msg))
    except IntegrityError as exc:
        msg = friendly_integrity_message(exc)
        raise fail(f"{msg} ({short_db_error(exc)})", HTTPException(status.HTTP_409_CONFLICT, msg))
    except OperationalError as exc:
        # e.g. MySQL deadlock (1213) or lock wait timeout (1205)
        msg = "The database was busy with a conflicting change. Please try again."
        raise fail(f"{msg} ({short_db_error(exc)})", HTTPException(status.HTTP_409_CONFLICT, msg))
    except Exception as exc:
        db.rollback()
        log_separately(user_id=user_id, operation=operation, status_=AuditStatus.ROLLED_BACK,
                       message=f"Unexpected error: {type(exc).__name__}", entity=entity,
                       entity_id=ctx.entity_id, duration_ms=elapsed())
        raise
