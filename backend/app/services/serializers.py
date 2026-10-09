"""Turn ORM rows into response dictionaries that include related names."""
from ..models import FuelRecord, MaintenanceRecord, Trip, Expense


def trip_out(trip: Trip) -> dict:
    return {
        "id": trip.id,
        "vehicle_id": trip.vehicle_id,
        "vehicle_registration": trip.vehicle.registration_no,
        "driver_id": trip.driver_id,
        "driver_name": trip.driver.name,
        "source": trip.source,
        "destination": trip.destination,
        "source_lat": trip.source_lat,
        "source_lng": trip.source_lng,
        "dest_lat": trip.dest_lat,
        "dest_lng": trip.dest_lng,
        "status": trip.status,
        "notes": trip.notes,
        "created_at": trip.created_at,
        "start_time": trip.start_time,
        "end_time": trip.end_time,
        "distance_km": float(trip.distance_km) if trip.distance_km is not None else None,
    }


def fuel_out(record: FuelRecord) -> dict:
    return {
        "id": record.id,
        "vehicle_id": record.vehicle_id,
        "vehicle_registration": record.vehicle.registration_no,
        "expense_id": record.expense_id,
        "quantity_l": float(record.quantity_l),
        "price_per_l": float(record.price_per_l),
        "total_cost": float(record.total_cost),
        "odometer_km": float(record.odometer_km),
        "station": record.station,
        "recorded_at": record.recorded_at,
    }


def maintenance_out(record: MaintenanceRecord) -> dict:
    return {
        "id": record.id,
        "vehicle_id": record.vehicle_id,
        "vehicle_registration": record.vehicle.registration_no,
        "expense_id": record.expense_id,
        "service_type": record.service_type,
        "description": record.description,
        "service_date": record.service_date,
        "cost": float(record.cost),
        "odometer_km": float(record.odometer_km) if record.odometer_km is not None else None,
        "next_service_date": record.next_service_date,
    }


def expense_out(expense: Expense) -> dict:
    return {
        "id": expense.id,
        "vehicle_id": expense.vehicle_id,
        "vehicle_registration": expense.vehicle.registration_no,
        "category": expense.category,
        "amount": float(expense.amount),
        "expense_date": expense.expense_date,
        "description": expense.description,
        "created_at": expense.created_at,
    }
