# TrackTech: Fleet Management and Vehicle Tracking

A web dashboard for monitoring vehicles on a map, managing drivers and trips, recording fuel and maintenance costs, and demonstrating database transactions (COMMIT, ROLLBACK and concurrency control) on MySQL.

Vehicle positions come from a software GPS simulator and are labelled as simulated everywhere they appear.

| Layer | Technology |
|---|---|
| Frontend | React 18, Vite 6, Tailwind CSS 4, React Router, Recharts, Leaflet with OpenStreetMap |
| Backend | Python, FastAPI, SQLAlchemy 2, Pydantic 2 |
| Database | MySQL 8.0.16 or newer, InnoDB engine |
| Auth | JWT bearer tokens, bcrypt password hashing, role-based access (admin, manager, viewer) |

## 1. Prerequisites

Install these once:

- **Python 3.11 or 3.12** (tick "Add Python to PATH" in the installer)
- **Node.js 20 LTS or 22 LTS**
- **MySQL 8.0.16 or newer** (MySQL Installer for Windows, "Server only" is enough)
- **VS Code** and **Git**

Check the versions in a terminal:

```powershell
python --version
node --version
mysql --version
```

## 2. Create the database

Open a terminal in the `TrackTech` folder:

```powershell
mysql -u root -p < database/schema.sql
```

Then create a dedicated application account, so the API never connects as `root`. Run `mysql -u root -p` and paste this with a password you choose:

```sql
CREATE USER 'tracktech_app'@'localhost' IDENTIFIED BY 'choose-a-strong-password';
GRANT SELECT, INSERT, UPDATE, DELETE ON tracktech_db.* TO 'tracktech_app'@'localhost';
FLUSH PRIVILEGES;
```

## 3. Start the backend

```powershell
cd backend
py -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
copy .env.example .env
```

If PowerShell refuses to run the activation script, use Command Prompt and run `venv\Scripts\activate.bat` instead.

Edit `backend/.env`:

1. Put your MySQL password into `DATABASE_URL`. If it contains `@`, `:` or `/`, URL-encode it (`@` becomes `%40`).
2. Generate a secret and paste it into `JWT_SECRET`:
   ```powershell
   python -c "import secrets; print(secrets.token_urlsafe(48))"
   ```
3. Optionally set `SEED_ADMIN_PASSWORD`, `SEED_MANAGER_PASSWORD` and `SEED_VIEWER_PASSWORD`. If you leave them empty, the seed script generates passwords and prints them once.

Load the user accounts and sample data, then start the API:

```powershell
python -m app.seed
python -m uvicorn app.main:app --reload
```

Open <http://127.0.0.1:8000/docs> for the interactive API documentation. To call protected endpoints there, click **Authorize** and type your email into the *username* box.

> Keep uvicorn at a single worker while `SIMULATOR_ENABLED=true`. Each worker would otherwise run its own simulator.

## 4. Start the frontend

In a second terminal:

```powershell
cd frontend
npm install
npm run dev
```

Open <http://localhost:5173> and sign in with an account printed by the seed script.

During development, Vite forwards every `/api` request to the backend on port 8000, so no CORS setup is needed.

## 5. Accounts and roles

| Role | Can do |
|---|---|
| Viewer | See every page, the audit log and consistency checks. Cannot change anything. |
| Manager | Everything a viewer can, plus add and edit vehicles, drivers, trips, fuel, services and expenses, and run the transaction lab. |
| Admin | Everything, plus manage users, deactivate vehicles and drivers, and delete cost records. |

The roles are enforced by the API. The UI hides buttons a role can't use, but that is a convenience and not the protection.

## 6. Run the tests

```powershell
cd backend
python -m pytest -v
```

The tests use a temporary SQLite file, so they never touch your MySQL data. SQLite ignores `SELECT ... FOR UPDATE`, so the row-lock demo must be verified on MySQL (see the demo script below). Constraints, conditional updates, rollbacks, authentication and role checks are all covered.

## 7. Demo script for the presentation

About 8 minutes. Sign in as the manager.

1. **Dashboard.** Two trips are already on the road, one is scheduled, one vehicle is in the workshop. Point out the alerts: an expired licence, a licence expiring soon, an overdue and an upcoming service.
2. **Live tracking.** Click a moving vehicle. The amber trail grows every few seconds, and the progress bar fills. Mention that positions are simulated, and what real GPS hardware would replace (`services/simulator.py`).
3. **Trips.** Schedule a trip for the vehicle whose regular driver is Harish Joshi. It is refused because the licence has expired, and nothing is changed. Pick another driver and it succeeds. Start it, and it appears on the map.
4. **Double booking.** Open the app in two browser windows and try to schedule the same vehicle in both. One succeeds; the other gets a clear conflict message.
5. **Fuel.** Record a fuel purchase with an odometer reading lower than the last one. It is rejected. Record a valid one, and show that the matching expense appeared.
6. **Transaction lab, commit.** The step list shows that another connection cannot see the changes before COMMIT.
7. **Transaction lab, rollback.** Choose the foreign key failure. Before and after are identical, and the audit row survived because it was written in a separate transaction.
8. **Transaction lab, race.** Run *No protection*: both users book the vehicle and two fees are charged. Run *Row lock*: User B waits for the lock (visible in the timing column), then is refused.
9. **Consistency checks.** Every check returns zero rows. Open one to show its SQL.
10. **Sign in as the viewer** and show that the edit buttons are gone and the API returns 403 if called directly from `/docs`.

## 8. Project structure

```
TrackTech/
├── backend/
│   ├── app/
│   │   ├── main.py            app setup, CORS, routers, simulator start-up
│   │   ├── config.py          settings from .env
│   │   ├── database.py        engine and sessions (explicit transactions)
│   │   ├── models.py          ORM tables, mirrors database/schema.sql
│   │   ├── schemas.py         request validation and response shapes
│   │   ├── security.py        bcrypt, JWT, login lockout
│   │   ├── deps.py            current user and role checks
│   │   ├── seed.py            accounts and sample data
│   │   ├── routes/            one file per module of the API
│   │   └── services/
│   │       ├── audit.py       transactional() helper and audit trail
│   │       ├── lab.py         commit, rollback and concurrency demos
│   │       ├── simulator.py   software GPS
│   │       ├── queries.py     row locks and shared queries
│   │       └── geo.py         distances and preset locations
│   └── tests/                 pytest suite
├── database/schema.sql        MySQL DDL, the source of truth
├── docs/architecture.md       diagrams and design decisions
└── frontend/src/
    ├── pages/                 one file per screen
    ├── components/            layout, table, map, shared UI
    └── lib/                   API client, auth, hooks, formatting
```

## 9. Troubleshooting

| Symptom | Fix |
|---|---|
| `JWT_SECRET must be at least 32 characters` | Generate one as shown in step 3. |
| `Access denied for user` | The password in `DATABASE_URL` is wrong or not URL-encoded. |
| `cryptography package is required` | Run `python -m pip install -r requirements.txt` inside the venv. |
| `Tables not found` from the seed script | Run `database/schema.sql` first. |
| Login page says it cannot reach the server | The backend is not running on port 8000. |
| CHECK constraint rollback demo shows a warning | Your MySQL is older than 8.0.16. Upgrade, or use the foreign key failure. |
| Map tiles are grey | No internet connection. OpenStreetMap tiles load from the web. |

## 10. Known limitations and next steps

- Vehicles move in a straight line between preset places. A routing service such as OSRM would give road-following paths.
- The map polls every 3 seconds. WebSockets would push updates and reduce load at larger scale.
- The login lockout is kept in memory, so it resets on restart and isn't shared between servers.
- The token is stored in `localStorage` for simplicity. Production systems usually prefer an httpOnly cookie with CSRF protection.
- OpenStreetMap's public tile servers have a fair-use policy. Use a tile provider for anything beyond a class demo.
