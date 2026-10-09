"""TrackTech API. Run with:  python -m uvicorn app.main:app --reload"""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, OperationalError

from .config import get_settings
from .database import engine
from .routes import auth, dashboard, drivers, expenses, reports, tracking, transactions, trips, users, vehicles
from .services.audit import friendly_integrity_message
from .services.simulator import run_simulator

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    stop = asyncio.Event()
    task = asyncio.create_task(run_simulator(stop)) if settings.simulator_enabled else None
    yield
    stop.set()
    if task:
        await task


app = FastAPI(
    title="TrackTech Fleet API",
    version="1.0.0",
    description="Vehicle fleet management with simulated GPS tracking and a DBMS transaction lab.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,  # tokens travel in the Authorization header, not cookies
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    return response


@app.exception_handler(IntegrityError)
async def integrity_error_handler(_: Request, exc: IntegrityError):
    # Safety net for writes outside transactional(); the session is closed (rolled back) by get_db.
    return JSONResponse(status_code=status.HTTP_409_CONFLICT, content={"detail": friendly_integrity_message(exc)})


@app.exception_handler(OperationalError)
async def operational_error_handler(_: Request, exc: OperationalError):
    logging.getLogger("tracktech").error("Database error: %s", exc.orig)
    return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                        content={"detail": "The database is unavailable. Check that MySQL is running."})


for module in (auth, users, dashboard, vehicles, drivers, trips, tracking, expenses, reports, transactions):
    app.include_router(module.router)


@app.get("/api/health", tags=["health"])
def health():
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ok", "simulator": settings.simulator_enabled}
