"""Create user accounts and sample fleet data.

    python -m app.seed                 # add users + sample data (skips data if vehicles exist)
    python -m app.seed --reset         # delete all fleet data first (keeps user accounts)
    python -m app.seed --create-tables # create tables from the models instead of schema.sql

All sample records are fictional. Fuel prices and coordinates are approximate.
"""
import argparse
import random
import secrets
import string
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import delete, inspect, select

from .config import get_settings
from .database import Base, SessionLocal, engine
from .models import (
    Driver,
    DriverStatus,
    Expense,
    ExpenseCategory,
    FuelRecord,
    FuelType,
    MaintenanceRecord,
    Role,
    TransactionAudit,
    Trip,
    TripStatus,
    User,
    Vehicle,
    VehicleAssignment,
    VehicleLocation,
    VehicleStatus,
    utcnow,
)
from .security import hash_password
from .services.geo import PLACES, haversine_km

settings = get_settings()
rng = random.Random(42)  # fixed seed: everyone on the team gets the same sample data

VEHICLES = [
    ("UK07CA1021", "Tata Ace Gold", FuelType.DIESEL),
    ("UK07CB2214", "Mahindra Bolero Pickup", FuelType.DIESEL),
    ("UK07TA3307", "Maruti Suzuki Eeco Cargo", FuelType.CNG),
    ("UK07TB4410", "Tata Intra V30", FuelType.DIESEL),
    ("UK07PA5583", "Ashok Leyland Dost Plus", FuelType.DIESEL),
    ("UK08CA6625", "Mahindra Treo Zor", FuelType.ELECTRIC),
    ("UK07CC7719", "Tata Winger", FuelType.DIESEL),
    ("UK07TC8842", "Maruti Suzuki Super Carry", FuelType.PETROL),
    ("UK14CA9031", "Eicher Pro 2049", FuelType.DIESEL),
    ("UK07CD1150", "Tata Ace EV", FuelType.ELECTRIC),
]

DRIVERS = [
    ("Rakesh Negi", "UK0720150012345", 900),
    ("Sunil Rawat", "UK0720160023456", 700),
    ("Manoj Bisht", "UK0720170034567", 1100),
    ("Deepak Thapa", "UK0820180045678", 500),
    ("Vikram Chauhan", "UK0720190056789", 1300),
    ("Anil Bhandari", "UK1420140067890", 400),
    ("Pooja Rana", "UK0720200078901", 20),   # licence expires soon -> dashboard warning
    ("Harish Joshi", "UK0720130089012", -25),  # licence expired -> cannot be given trips
]

PRICE_PER_UNIT = {FuelType.DIESEL: Decimal("90.20"), FuelType.PETROL: Decimal("94.50"),
                  FuelType.CNG: Decimal("85.00"), FuelType.HYBRID: Decimal("94.50")}
SERVICE_TYPES = ["General service", "Oil and filter change", "Brake pads", "Tyre replacement",
                 "Clutch overhaul", "Battery replacement", "Wheel alignment"]
DEPOT = "geu"


def money(value: float) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def random_password() -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(10)) + secrets.choice("!@#%") + secrets.choice(string.digits)


def ensure_users(db) -> list[tuple[str, str, str]]:
    created = []
    accounts = [
        ("TrackTech Admin", "admin@tracktech.local", Role.ADMIN, settings.seed_admin_password),
        ("Fleet Manager", "manager@tracktech.local", Role.MANAGER, settings.seed_manager_password),
        ("Read-only Viewer", "viewer@tracktech.local", Role.VIEWER, settings.seed_viewer_password),
    ]
    for name, email, role, password in accounts:
        if db.scalar(select(User.id).where(User.email == email)):
            continue
        shown = "(password from .env)" if password else None
        password = password or random_password()
        db.add(User(name=name, email=email, role=role, password_hash=hash_password(password)))
        created.append((email, role.value, shown or password))
    return created


def reset_fleet_data(db) -> None:
    for model in (TransactionAudit, VehicleLocation, FuelRecord, MaintenanceRecord, Expense, Trip,
                  VehicleAssignment, Driver, Vehicle):
        db.execute(delete(model))


def seed_fleet(db) -> None:
    today = date.today()
    now = utcnow()
    place_ids = list(PLACES)

    vehicles = [Vehicle(registration_no=r, model=m, fuel_type=f, odometer_km=Decimal(rng.randint(8000, 60000)))
                for r, m, f in VEHICLES]
    drivers = [Driver(name=n, license_no=l, license_expiry=today + timedelta(days=days),
                      phone=f"+91 90000 {10001 + i:05d}") for i, (n, l, days) in enumerate(DRIVERS)]
    db.add_all(vehicles + drivers)
    db.flush()

    # Default driver for the first eight vehicles.
    for v, d in zip(vehicles[:8], drivers[:8]):
        db.add(VehicleAssignment(vehicle_id=v.id, driver_id=d.id, start_date=now - timedelta(days=120)))

    # Completed trips over the last five months.
    usable = list(zip(vehicles[:7], drivers[:7]))
    for _ in range(45):
        v, d = rng.choice(usable)
        a, b = rng.sample(place_ids, 2)
        src, dst = PLACES[a], PLACES[b]
        km = round(haversine_km(src["lat"], src["lng"], dst["lat"], dst["lng"]) * 1.3, 2)  # roads aren't straight
        start = now - timedelta(days=rng.randint(1, 150), hours=rng.randint(0, 10))
        end = start + timedelta(minutes=int(km / rng.uniform(25, 40) * 60) + 10)
        db.add(Trip(vehicle_id=v.id, driver_id=d.id, source=src["name"], source_lat=src["lat"],
                    source_lng=src["lng"], destination=dst["name"], dest_lat=dst["lat"], dest_lng=dst["lng"],
                    status=TripStatus.COMPLETED, created_at=start - timedelta(minutes=30),
                    start_time=start, end_time=end, distance_km=Decimal(str(km))))

    # Fuel purchases every 8-14 days for fuel-burning vehicles; each one is also an expense.
    for v in vehicles:
        if v.fuel_type == FuelType.ELECTRIC:
            continue
        odometer = v.odometer_km - Decimal(rng.randint(3000, 5000))
        day = today - timedelta(days=150)
        while day < today:
            qty = Decimal(str(round(rng.uniform(20, 45), 2)))
            price = PRICE_PER_UNIT[v.fuel_type]
            total = (qty * price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            odometer += Decimal(rng.randint(250, 520))
            exp = Expense(vehicle_id=v.id, category=ExpenseCategory.FUEL, amount=total, expense_date=day,
                          description=f"{qty} L at {price}/L")
            db.add(exp)
            db.flush()
            db.add(FuelRecord(vehicle_id=v.id, expense_id=exp.id, quantity_l=qty, price_per_l=price,
                              total_cost=total, odometer_km=odometer, station="Sample fuel station",
                              recorded_at=datetime.combine(day, datetime.min.time()) + timedelta(hours=9)))
            day += timedelta(days=rng.randint(8, 14))
        v.odometer_km = odometer

    # Two services per vehicle; the latest one sets the next due date.
    for i, v in enumerate(vehicles):
        for n, days_ago in enumerate(sorted(rng.sample(range(10, 160), 2), reverse=True)):
            service_date = today - timedelta(days=days_ago)
            latest = n == 1
            if latest and i == 1:
                next_due = today + timedelta(days=4)       # due soon
            elif latest and i == 3:
                next_due = today - timedelta(days=6)       # overdue
            else:
                next_due = service_date + timedelta(days=90)
            cost = money(rng.uniform(1500, 12000))
            stype = rng.choice(SERVICE_TYPES)
            exp = Expense(vehicle_id=v.id, category=ExpenseCategory.MAINTENANCE, amount=cost,
                          expense_date=service_date, description=stype)
            db.add(exp)
            db.flush()
            db.add(MaintenanceRecord(vehicle_id=v.id, expense_id=exp.id, service_type=stype,
                                     description="Sample service record", service_date=service_date, cost=cost,
                                     next_service_date=max(next_due, service_date)))

    # Tolls, parking, insurance and EV charging.
    for _ in range(40):
        v = rng.choice(vehicles)
        category = rng.choice([ExpenseCategory.TOLL, ExpenseCategory.PARKING, ExpenseCategory.OTHER])
        amount = {ExpenseCategory.TOLL: rng.uniform(60, 320), ExpenseCategory.PARKING: rng.uniform(30, 120),
                  ExpenseCategory.OTHER: rng.uniform(150, 900)}[category]
        description = {ExpenseCategory.TOLL: "Highway toll", ExpenseCategory.PARKING: "Parking",
                       ExpenseCategory.OTHER: "EV charging" if v.fuel_type == FuelType.ELECTRIC else "Cleaning"}[category]
        db.add(Expense(vehicle_id=v.id, category=category, amount=money(amount),
                       expense_date=today - timedelta(days=rng.randint(0, 150)), description=description))
    for v in vehicles[:4]:
        db.add(Expense(vehicle_id=v.id, category=ExpenseCategory.INSURANCE, amount=money(rng.uniform(9000, 18000)),
                       expense_date=today - timedelta(days=rng.randint(20, 140)), description="Annual insurance"))

    # One vehicle in the workshop.
    vehicles[4].status = VehicleStatus.MAINTENANCE

    # Every vehicle starts parked near the depot (scattered slightly so markers don't overlap).
    depot = PLACES[DEPOT]
    for v in vehicles:
        db.add(VehicleLocation(vehicle_id=v.id, latitude=depot["lat"] + rng.uniform(-0.01, 0.01),
                               longitude=depot["lng"] + rng.uniform(-0.01, 0.01), speed_kmh=0,
                               is_simulated=True, recorded_at=now - timedelta(minutes=10)))

    # Two trips already on the road and one waiting to start, so the map moves immediately.
    def open_trip(v, d, a, b, trip_status, minutes_ago):
        src, dst = PLACES[a], PLACES[b]
        trip = Trip(vehicle_id=v.id, driver_id=d.id, source=src["name"], source_lat=src["lat"],
                    source_lng=src["lng"], destination=dst["name"], dest_lat=dst["lat"], dest_lng=dst["lng"],
                    status=trip_status, created_at=now - timedelta(minutes=minutes_ago + 5),
                    start_time=now - timedelta(minutes=minutes_ago) if trip_status == TripStatus.ACTIVE else None)
        db.add(trip)
        db.flush()
        v.status = VehicleStatus.IN_USE
        d.status = DriverStatus.ON_TRIP
        if trip_status == TripStatus.ACTIVE:
            db.add(VehicleLocation(vehicle_id=v.id, trip_id=trip.id, latitude=src["lat"], longitude=src["lng"],
                                   speed_kmh=0, is_simulated=True, recorded_at=trip.start_time))

    open_trip(vehicles[0], drivers[0], "geu", "rishikesh", TripStatus.ACTIVE, 2)
    open_trip(vehicles[1], drivers[1], "isbt", "mussoorie", TripStatus.ACTIVE, 1)
    open_trip(vehicles[2], drivers[2], "clock-tower", "haridwar", TripStatus.SCHEDULED, 0)


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed TrackTech with users and sample data")
    parser.add_argument("--reset", action="store_true", help="delete existing fleet data first (keeps users)")
    parser.add_argument("--create-tables", action="store_true",
                        help="create tables from the SQLAlchemy models (alternative to schema.sql)")
    args = parser.parse_args()

    if args.create_tables:
        Base.metadata.create_all(engine)
        print("Tables created from models.")
    if not inspect(engine).has_table("vehicles"):
        raise SystemExit("Tables not found. Run database/schema.sql in MySQL first, "
                         "or use: python -m app.seed --create-tables")

    # The whole seed is ONE transaction: if anything fails, nothing is half-inserted.
    with SessionLocal() as db:
        try:
            if args.reset:
                reset_fleet_data(db)
            created_users = ensure_users(db)
            if db.scalar(select(Vehicle.id).limit(1)) is None:
                seed_fleet(db)
                fleet_msg = "Sample fleet data inserted."
            else:
                fleet_msg = "Vehicles already exist; sample data skipped (use --reset to replace it)."
            db.commit()
        except Exception:
            db.rollback()
            raise

    print(fleet_msg)
    if created_users:
        print("\nAccounts created. Save any generated passwords now; they are not shown again:")
        for email, role, password in created_users:
            print(f"  {role:<8} {email:<28} {password}")
    else:
        print("User accounts already exist.")


if __name__ == "__main__":
    main()
