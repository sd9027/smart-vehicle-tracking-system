"""API tests for authentication, CRUD rules and transactions. Run: python -m pytest -v"""
from .conftest import PASSWORD, auth


def trip_body(vehicle_id=1, driver_id=1):
    return {"vehicle_id": vehicle_id, "driver_id": driver_id,
            "source_place_id": "geu", "destination_place_id": "isbt"}


# ---------------- Authentication and roles ----------------

def test_login_returns_token_and_me_works(client):
    headers = auth(client)
    r = client.get("/api/auth/me", headers=headers)
    assert r.status_code == 200
    assert r.json()["role"] == "MANAGER"
    assert "password_hash" not in r.json()


def test_wrong_password_gives_generic_message(client):
    r = client.post("/api/auth/login", json={"email": "manager@test.local", "password": "wrong-pass-1"})
    assert r.status_code == 401
    r2 = client.post("/api/auth/login", json={"email": "nobody@test.local", "password": "wrong-pass-1"})
    assert r2.status_code == 401
    assert r.json()["detail"] == r2.json()["detail"]  # does not reveal which emails exist


def test_repeated_failures_lock_the_account(client):
    for _ in range(5):
        client.post("/api/auth/login", json={"email": "viewer@test.local", "password": "bad-pass-1"})
    r = client.post("/api/auth/login", json={"email": "viewer@test.local", "password": PASSWORD})
    assert r.status_code == 429


def test_protected_route_requires_token(client):
    assert client.get("/api/vehicles").status_code == 401
    bad = {"Authorization": "Bearer not-a-real-token"}
    assert client.get("/api/vehicles", headers=bad).status_code == 401


def test_viewer_cannot_create_but_can_read(client):
    headers = auth(client, "viewer@test.local")
    assert client.get("/api/vehicles", headers=headers).status_code == 200
    r = client.post("/api/vehicles", headers=headers,
                    json={"registration_no": "UK07BB2222", "model": "Van", "fuel_type": "DIESEL"})
    assert r.status_code == 403


def test_only_admin_manages_users(client):
    assert client.get("/api/users", headers=auth(client)).status_code == 403
    assert client.get("/api/users", headers=auth(client, "admin@test.local")).status_code == 200


def test_password_change_revokes_old_tokens(client):
    old = auth(client)
    r = client.post("/api/auth/change-password", headers=old,
                    json={"current_password": PASSWORD, "new_password": "NewPassword456!"})
    assert r.status_code == 200
    assert client.get("/api/auth/me", headers=old).status_code == 401
    new = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert client.get("/api/auth/me", headers=new).status_code == 200


# ---------------- Vehicles ----------------

def test_registration_is_normalised_and_unique(client):
    headers = auth(client)
    r = client.post("/api/vehicles", headers=headers,
                    json={"registration_no": "uk 07 bb 2222", "model": "Van", "fuel_type": "DIESEL"})
    assert r.status_code == 201
    assert r.json()["registration_no"] == "UK07BB2222"
    dup = client.post("/api/vehicles", headers=headers,
                      json={"registration_no": "UK07-BB-2222", "model": "Van", "fuel_type": "DIESEL"})
    assert dup.status_code == 409


def test_invalid_registration_rejected(client):
    r = client.post("/api/vehicles", headers=auth(client),
                    json={"registration_no": "HELLO", "model": "Van", "fuel_type": "DIESEL"})
    assert r.status_code == 422


def test_stale_version_is_rejected(client):
    headers = auth(client)
    v = client.get("/api/vehicles/1", headers=headers).json()
    first = client.put("/api/vehicles/1", headers=headers, json={"model": "Renamed", "version": v["version"]})
    assert first.status_code == 200
    stale = client.put("/api/vehicles/1", headers=headers, json={"model": "Again", "version": v["version"]})
    assert stale.status_code == 409


# ---------------- Trips (Example A) ----------------

def test_trip_lifecycle_moves_vehicle_and_driver(client):
    headers = auth(client)
    r = client.post("/api/trips", headers=headers, json=trip_body())
    assert r.status_code == 201, r.text
    trip_id = r.json()["id"]
    assert client.get("/api/vehicles/1", headers=headers).json()["status"] == "IN_USE"
    assert client.get("/api/drivers/1", headers=headers).json()["status"] == "ON_TRIP"

    assert client.patch(f"/api/trips/{trip_id}/status", headers=headers, json={"status": "ACTIVE"}).status_code == 200
    done = client.patch(f"/api/trips/{trip_id}/status", headers=headers, json={"status": "COMPLETED"})
    assert done.status_code == 200
    assert done.json()["distance_km"] > 0
    assert client.get("/api/vehicles/1", headers=headers).json()["status"] == "AVAILABLE"
    assert client.get("/api/drivers/1", headers=headers).json()["status"] == "AVAILABLE"


def test_illegal_status_change_rejected(client):
    headers = auth(client)
    trip_id = client.post("/api/trips", headers=headers, json=trip_body()).json()["id"]
    r = client.patch(f"/api/trips/{trip_id}/status", headers=headers, json={"status": "COMPLETED"})
    assert r.status_code == 409  # must be ACTIVE before COMPLETED


def test_vehicle_cannot_be_double_booked_and_failure_is_audited(client):
    headers = auth(client)
    assert client.post("/api/trips", headers=headers, json=trip_body(1, 1)).status_code == 201
    second = client.post("/api/trips", headers=headers, json=trip_body(1, 2))
    assert second.status_code == 409
    # Driver 2 must not have been changed by the failed transaction.
    assert client.get("/api/drivers/2", headers=headers).json()["status"] == "AVAILABLE"
    log = client.get("/api/transactions?status=ROLLED_BACK", headers=headers).json()
    assert any(row["operation"] == "CREATE_TRIP" for row in log)


# ---------------- Fuel ----------------

def test_fuel_creates_matching_expense_and_rejects_lower_odometer(client):
    headers = auth(client)
    r = client.post("/api/fuel-records", headers=headers,
                    json={"vehicle_id": 1, "quantity_l": "20", "price_per_l": "90.50", "odometer_km": "100"})
    assert r.status_code == 201, r.text
    assert r.json()["total_cost"] == 1810.0
    expenses = client.get("/api/expenses?category=FUEL", headers=headers).json()
    assert len(expenses) == 1 and expenses[0]["amount"] == 1810.0
    lower = client.post("/api/fuel-records", headers=headers,
                        json={"vehicle_id": 1, "quantity_l": "5", "price_per_l": "90", "odometer_km": "50"})
    assert lower.status_code == 422
    assert len(client.get("/api/expenses?category=FUEL", headers=headers).json()) == 1


# ---------------- Transaction lab ----------------

def test_commit_demo_persists(client):
    r = client.post("/api/transactions/demo/commit", headers=auth(client))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["final_status"] == "COMMITTED"
    assert body["after"]["expense_rows"] == body["before"]["expense_rows"] + 1


def test_rollback_demo_leaves_no_changes(client):
    headers = auth(client)
    for failure in ("foreign_key", "check_constraint", "application"):
        r = client.post("/api/transactions/demo/rollback", headers=headers, json={"failure": failure})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["final_status"] == "ROLLED_BACK", (failure, body)
        assert body["before"] == body["after"]
        assert body["audit_ids"], "failure must be audited outside the rolled-back transaction"


def test_conditional_update_prevents_double_booking(client):
    r = client.post("/api/transactions/demo/concurrency", headers=auth(client), json={"mode": "conditional"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["final_status"] == "PROTECTED", body
    assert body["after"]["booking_charges"] == 1


def test_naive_mode_shows_the_race(client):
    r = client.post("/api/transactions/demo/concurrency", headers=auth(client), json={"mode": "naive"})
    assert r.json()["final_status"] == "DOUBLE_BOOKED"


def test_consistency_checks_pass_after_activity(client):
    headers = auth(client)
    client.post("/api/trips", headers=headers, json=trip_body())
    client.post("/api/transactions/demo/concurrency", headers=headers, json={"mode": "naive"})
    checks = client.get("/api/transactions/consistency", headers=headers).json()
    assert all(c["passed"] for c in checks), checks


def test_viewer_cannot_run_lab(client):
    r = client.post("/api/transactions/demo/commit", headers=auth(client, "viewer@test.local"))
    assert r.status_code == 403
