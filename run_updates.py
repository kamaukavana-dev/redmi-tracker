import os

# 1. Update app/models.py
with open("app/models.py", "r") as f:
    models_content = f.read()
models_content = models_content.replace(
    'Index("ix_locations_recorded_at_desc", "recorded_at", postgresql_ops={"recorded_at": "DESC"}),',
    'Index("ix_locations_recorded_at_desc", recorded_at.desc()),'
)
models_content = models_content.replace(
    '__table_args__ = (',
    '__table_args__ = (\n        Index("ix_geofences_is_active", "is_active"),'
, 1) # Note: we just need it in Geofence
if 'Index("ix_geofences_is_active", "is_active")' not in models_content:
    models_content = models_content.replace(
        'alerts: Mapped[list["Alert"]] = relationship("Alert", back_populates="geofence")',
        'alerts: Mapped[list["Alert"]] = relationship("Alert", back_populates="geofence")\n\n    __table_args__ = (\n        Index("ix_geofences_is_active", "is_active"),\n    )'
    )
if 'Index("ix_alerts_geofence_id_sent_at_desc"' not in models_content:
    models_content = models_content.replace(
        'geofence: Mapped["Geofence"] = relationship("Geofence", back_populates="alerts")',
        'geofence: Mapped["Geofence"] = relationship("Geofence", back_populates="alerts")\n\n    __table_args__ = (\n        Index("ix_alerts_geofence_id_sent_at_desc", "geofence_id", sent_at.desc()),\n    )'
    )
# fix missing sent_at reference
models_content = models_content.replace('sent_at.desc()', 'Alert.sent_at.desc()').replace('recorded_at.desc()', 'Location.recorded_at.desc()')
with open("app/models.py", "w") as f:
    f.write(models_content)

# 2. Update app/schemas.py
with open("app/schemas.py", "r") as f:
    schemas_content = f.read()

schemas_content = schemas_content.replace(
    "page: int",
    ""
)
schemas_content = schemas_content.replace(
    """class ErrorResponse(BaseModel):
    \"\"\"
    Standardized error response schema.

    Used by global exception handler for all error responses.
    \"\"\"

    error: str
    code: int
    path: str
    timestamp: datetime""",
    """class ErrorResponse(BaseModel):
    error: str
    code: int
    path: str
    request_id: str
    timestamp: datetime"""
)

schemas_content = schemas_content.replace(
    """class StatsResponse(BaseModel):
    \"\"\"
    Schema for system statistics endpoint.

    Used for GET /stats endpoint returning aggregate metrics.
    \"\"\"

    total_pings: int
    last_seen: Optional[datetime]
    last_battery: Optional[int]
    avg_battery_24h: Optional[float]
    uptime_score: float
    geofences_active: int
    alerts_sent_24h: int""",
    """class Position(BaseModel):
    latitude: float
    longitude: float

class StatsResponse(BaseModel):
    total_pings: int
    last_seen: Optional[datetime]
    last_known_position: Optional[Position]
    last_battery: Optional[int]
    avg_battery_24h: Optional[float]
    uptime_score_24h: float
    geofences_active: int
    alerts_sent_24h: int
    pings_last_hour: int"""
)
with open("app/schemas.py", "w") as f:
    f.write(schemas_content)

# 3. Update app/main.py
main_py = '''"""
Redmi Tracker FastAPI Application.
"""

import logging
import sys
import uuid
import asyncio
from datetime import datetime
from typing import AsyncGenerator, Callable
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from app.config import settings
from app.database import engine, get_db, SessionLocal
from app.routers import track, location, geofence, stats
from app.scheduler import start_scheduler, stop_scheduler
from app.services.notifier import validate_telegram_token
from app.schemas import ErrorResponse, HealthResponse

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

async def validate_startup() -> bool:
    logger.info("Validating startup requirements...")
    env_vars = {
        "DATABASE_URL": settings.database_url,
        "API_KEY": settings.api_key,
        "TELEGRAM_BOT_TOKEN": settings.telegram_bot_token,
        "TELEGRAM_CHAT_ID": settings.telegram_chat_id,
    }
    missing = [name for name, value in env_vars.items() if not value or value.strip() == ""]
    if missing:
        logger.error(f"Missing required environment variables: {', '.join(missing)}")
        sys.exit(1)
    logger.info("env ✅")

    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
        logger.info("db ✅")
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        sys.exit(1)
    finally:
        db.close()

    try:
        is_valid = await validate_telegram_token()
        if not is_valid:
            logger.error("Telegram token validation failed. Check TELEGRAM_BOT_TOKEN.")
            sys.exit(1)
        logger.info("telegram ✅")
    except Exception as e:
        logger.error(f"Telegram validation error: {e}")
        sys.exit(1)

    logger.info("All startup validations passed.")
    return True


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    await validate_startup()
    start_scheduler()
    logger.info("Scheduler started.")
    logger.info("Application ready.")
    yield
    stop_scheduler()
    logger.info("Application shut down.")

app = FastAPI(
    title="Redmi Tracker API",
    description="Track device locations, monitor geofences, and receive Telegram alerts.",
    version="1.0.0",
    lifespan=lifespan,
)

@app.middleware("http")
async def request_logging_middleware(request: Request, call_next: Callable) -> Response:
    start_time = datetime.utcnow()
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    request.state.request_id = request_id
    client_ip = request.client.host if request.client else "unknown"

    response = await call_next(request)

    end_time = datetime.utcnow()
    duration_ms = (end_time - start_time).total_seconds() * 1000

    log_entry = {
        "timestamp": start_time.isoformat(),
        "method": request.method,
        "path": request.url.path,
        "client_ip": client_ip,
        "status_code": response.status_code,
        "duration_ms": round(duration_ms, 2),
        "request_id": request_id,
    }
    logger.info(log_entry)
    response.headers["X-Request-ID"] = request_id
    return response

async def build_error_response(request: Request, exc: Exception, status_code: int, message: str) -> JSONResponse:
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    err_resp = ErrorResponse(
        error=message,
        code=status_code,
        path=request.url.path,
        request_id=request_id,
        timestamp=datetime.utcnow(),
    )
    return JSONResponse(status_code=status_code, content=err_resp.model_dump(mode="json"))

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return await build_error_response(request, exc, 422, "Request validation failed")

@app.exception_handler(SQLAlchemyError)
async def sqlalchemy_exception_handler(request: Request, exc: SQLAlchemyError) -> JSONResponse:
    return await build_error_response(request, exc, 500, "Database operation failed")

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return await build_error_response(request, exc, exc.status_code, exc.detail)

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    return await build_error_response(request, exc, 500, "Internal server error")

from fastapi import Depends
@app.get("/health", response_model=HealthResponse)
async def health_check(db: Session = Depends(get_db)) -> HealthResponse:
    db_healthy = False
    telegram_healthy = False
    try:
        db.execute(text("SELECT 1"))
        db_healthy = True
    except Exception:
        pass
    try:
        telegram_healthy = await validate_telegram_token()
    except Exception:
        pass
    all_healthy = db_healthy and telegram_healthy
    return HealthResponse(
        status="healthy" if all_healthy else "degraded",
        database=db_healthy,
        telegram=telegram_healthy,
        timestamp=datetime.utcnow(),
    )

app.include_router(track.router)
app.include_router(location.router)
app.include_router(geofence.router)
app.include_router(stats.router)

@app.get("/")
async def serve_dashboard():
    return FileResponse("dashboard/index.html")
'''
with open("app/main.py", "w") as f: f.write(main_py)


# 4. app/routers/track.py
with open("app/routers/track.py", "r") as f: track_py = f.read()
track_py = track_py.replace("-> Location:", "-> LocationResponse:")
with open("app/routers/track.py", "w") as f: f.write(track_py)


# 5. app/routers/location.py
with open("app/routers/location.py", "r") as f: loc_py = f.read()
loc_py = loc_py.replace("page=page,\n        per_page=limit,", "per_page=limit,")
with open("app/routers/location.py", "w") as f: f.write(loc_py)

# 6. app/routers/stats.py
stats_py = '''from fastapi import APIRouter, Depends, Security
from sqlalchemy.orm import Session
from app.database import get_db
from app.schemas import StatsResponse, Position
from app.security import verify_api_key
from app.services import location as location_svc
from app.services import geofence as geofence_svc

router = APIRouter(tags=["stats"])

@router.get("/stats", response_model=StatsResponse)
async def get_stats(db: Session = Depends(get_db), _: str = Security(verify_api_key)) -> StatsResponse:
    total_pings = location_svc.get_total_count(db)
    latest = location_svc.get_latest(db)
    
    last_seen = latest.recorded_at if latest else None
    last_battery = latest.battery if latest else None
    last_known_position = Position(latitude=latest.latitude, longitude=latest.longitude) if latest else None

    avg_battery_24h = location_svc.get_average_battery_24h(db)

    locations_24h = location_svc.get_locations_24h(db)
    expected_pings = 288
    actual_pings = len(locations_24h)
    uptime_score = (actual_pings / expected_pings * 100) if expected_pings > 0 else 0.0
    uptime_score = min(uptime_score, 100.0)

    pings_last_hour = location_svc.get_pings_last_hour(db)

    geofences_active = geofence_svc.get_active_count(db)
    alerts_sent_24h = geofence_svc.get_alerts_24h(db)

    return StatsResponse(
        total_pings=total_pings,
        last_seen=last_seen,
        last_known_position=last_known_position,
        last_battery=last_battery,
        avg_battery_24h=avg_battery_24h,
        uptime_score_24h=round(uptime_score, 2),
        geofences_active=geofences_active,
        alerts_sent_24h=alerts_sent_24h,
        pings_last_hour=pings_last_hour,
    )
'''
with open("app/routers/stats.py", "w") as f: f.write(stats_py)

# 7. app/services/location.py
with open("app/services/location.py", "r") as f: loc_svc = f.read()
if "def get_pings_last_hour" not in loc_svc:
    loc_svc += '''
def get_pings_last_hour(db: Session) -> int:
    cutoff = datetime.utcnow() - timedelta(hours=1)
    return db.query(func.count(Location.id)).filter(Location.recorded_at >= cutoff).scalar()
'''
loc_svc = loc_svc.replace("query = db.query(Location).order_by(Location.recorded_at.desc())", "query = db.query(Location).order_by(Location.id.desc())")
with open("app/services/location.py", "w") as f: f.write(loc_svc)

# 8. app/services/geofence.py
geofence_svc = '''"""
Geofence service module.
"""

import math
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import func, update, or_
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Geofence, Alert, Location

def haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6_371_000
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def create_geofence(db: Session, payload: dict) -> Geofence:
    geofence = Geofence(**payload)
    db.add(geofence)
    db.commit()
    db.refresh(geofence)
    return geofence

def list_geofences(db: Session) -> list[Geofence]:
    return db.query(Geofence).filter(Geofence.is_active == True).all()

def get_geofence(db: Session, geofence_id: int) -> Optional[Geofence]:
    return db.query(Geofence).filter(Geofence.id == geofence_id).first()

def delete_geofence(db: Session, geofence_id: int) -> Optional[Geofence]:
    geofence = db.query(Geofence).filter(Geofence.id == geofence_id).first()
    if geofence:
        geofence.is_active = False
        db.commit()
    return geofence

def is_cooldown_active(geofence: Geofence) -> bool:
    if geofence.last_alerted_at is None:
        return False
    cooldown_delta = timedelta(minutes=settings.geofence_cooldown_minutes)
    time_since_alert = datetime.utcnow() - geofence.last_alerted_at
    return time_since_alert < cooldown_delta

def check_all_geofences(db: Session, location: Location) -> list[Alert]:
    alerts: list[Alert] = []
    active_fences = list_geofences(db)
    now = datetime.utcnow()
    cooldown_cutoff = now - timedelta(minutes=settings.geofence_cooldown_minutes)

    for fence in active_fences:
        distance = haversine_meters(location.latitude, location.longitude, fence.latitude, fence.longitude)

        if distance > fence.radius_meters:
            stmt = update(Geofence).where(
                Geofence.id == fence.id,
                or_(Geofence.last_alerted_at.is_(None), Geofence.last_alerted_at <= cooldown_cutoff)
            ).values(last_alerted_at=now)
            
            result = db.execute(stmt)
            if result.rowcount > 0:
                message = (
                    f"⚠️ Redmi 14C left '{fence.name}'! "
                    f"Distance: {distance:.0f}m (limit: {fence.radius_meters:.0f}m). "
                    f"Position: {location.latitude:.5f}, {location.longitude:.5f}"
                )
                alert = Alert(geofence_id=fence.id, latitude=location.latitude, longitude=location.longitude, message=message)
                db.add(alert)
                alerts.append(alert)

    if alerts:
        db.commit()

    return alerts

def get_active_count(db: Session) -> int:
    return db.query(func.count(Geofence.id)).filter(Geofence.is_active == True).scalar()

def get_alerts_24h(db: Session) -> int:
    cutoff = datetime.utcnow() - timedelta(hours=24)
    return db.query(func.count(Alert.id)).filter(Alert.sent_at >= cutoff).scalar()
'''
with open("app/services/geofence.py", "w") as f: f.write(geofence_svc)

# 9. cli/main.py
cli_py = '''"""
Redmi Tracker CLI.
"""
import os
import csv
import sys
from datetime import datetime
from typing import Optional
import httpx
import typer
from rich.console import Console
from rich.table import Table
from dotenv import load_dotenv

load_dotenv()
app = typer.Typer(help="Redmi Tracker CLI - Manage device tracking and geofences")
console = Console()

API_BASE = os.getenv("API_BASE", "http://localhost:8000")

def get_headers() -> dict:
    api_key = os.getenv("API_KEY", "")
    if not api_key:
        console.print("[red]Error: API_KEY environment variable not set[/red]")
        sys.exit(1)
    return {"X-API-Key": api_key, "Content-Type": "application/json"}

@app.command("ping")
def show_latest_ping() -> None:
    try:
        response = httpx.get(f"{API_BASE}/location/latest", headers=get_headers())
        response.raise_for_status()
        data = response.json()
        console.print("\n[bold blue]Latest Ping[/bold blue]")
        console.print(f"  ID: {data['id']}")
        console.print(f"  Latitude: {data['latitude']:.6f}")
        console.print(f"  Longitude: {data['longitude']:.6f}")
        console.print(f"  Battery: {data['battery']}%" if data['battery'] else "  Battery: N/A")
        console.print(f"  Recorded: {data['recorded_at']}")
    except httpx.HTTPError as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)

@app.command("history")
def show_history(n: int = typer.Option(20, "--n", help="Number of records to show")) -> None:
    try:
        response = httpx.get(f"{API_BASE}/location/history?limit={n}", headers=get_headers())
        response.raise_for_status()
        data = response.json()
        table = Table(title=f"Location History (Last {data['total']} pings)")
        table.add_column("ID", style="cyan")
        table.add_column("Latitude", style="green")
        table.add_column("Longitude", style="green")
        table.add_column("Battery", style="yellow")
        table.add_column("Recorded At", style="magenta")

        for loc in data["data"]:
            battery = f"{loc['battery']}%" if loc['battery'] else "N/A"
            table.add_row(str(loc["id"]), f"{loc['latitude']:.6f}", f"{loc['longitude']:.6f}", battery, loc["recorded_at"])
        console.print(table)
    except httpx.HTTPError as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)

@app.command("stats")
def show_stats() -> None:
    try:
        response = httpx.get(f"{API_BASE}/stats", headers=get_headers())
        response.raise_for_status()
        data = response.json()
        console.print("\n[bold blue]System Statistics[/bold blue]")
        console.print(f"  Total Pings: {data['total_pings']}")
        console.print(f"  Pings Last Hour: {data['pings_last_hour']}")
        console.print(f"  Last Seen: {data['last_seen'] or 'Never'}")
        if data['last_known_position']:
            console.print(f"  Last Position: {data['last_known_position']['latitude']}, {data['last_known_position']['longitude']}")
        console.print(f"  Last Battery: {data['last_battery']}%" if data['last_battery'] else "  Last Battery: N/A")
        console.print(f"  Avg Battery (24h): {data['avg_battery_24h']:.1f}%" if data['avg_battery_24h'] else "  Avg Battery (24h): N/A")
        console.print(f"  Uptime Score (24h): {data['uptime_score_24h']:.1f}%")
        console.print(f"  Active Geofences: {data['geofences_active']}")
        console.print(f"  Alerts (24h): {data['alerts_sent_24h']}")
    except httpx.HTTPError as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)

@app.command("fence")
def manage_geofences(
    action: str = typer.Argument(..., help="Action: list, add, or delete"),
    fence_id: Optional[int] = typer.Argument(None, help="Geofence ID for delete")
) -> None:
    if action == "list":
        try:
            response = httpx.get(f"{API_BASE}/geofence", headers=get_headers())
            response.raise_for_status()
            fences = response.json()
            if not fences:
                console.print("[yellow]No active geofences[/yellow]")
                return
            table = Table(title="Active Geofences")
            table.add_column("ID", style="cyan")
            table.add_column("Name", style="green")
            table.add_column("Latitude", style="yellow")
            table.add_column("Longitude", style="yellow")
            table.add_column("Radius (m)", style="magenta")
            for fence in fences:
                table.add_row(str(fence["id"]), fence["name"], f"{fence['latitude']:.6f}", f"{fence['longitude']:.6f}", str(fence["radius_meters"]))
            console.print(table)
        except httpx.HTTPError as e:
            console.print(f"[red]Error: {e}[/red]")
            sys.exit(1)
    elif action == "add":
        name = typer.prompt("Geofence Name")
        lat = typer.prompt("Latitude", type=float)
        lon = typer.prompt("Longitude", type=float)
        radius = typer.prompt("Radius (meters)", type=float)
        payload = {"name": name, "latitude": lat, "longitude": lon, "radius_meters": radius}
        try:
            response = httpx.post(f"{API_BASE}/geofence", json=payload, headers=get_headers())
            response.raise_for_status()
            fence = response.json()
            console.print(f"[green]Geofence created: {fence['name']} (ID: {fence['id']})[/green]")
        except httpx.HTTPError as e:
            console.print(f"[red]Error: {e}[/red]")
            sys.exit(1)
    elif action == "delete":
        if fence_id is None:
            console.print("[red]Error: fence_id required for delete[/red]")
            sys.exit(1)
        try:
            response = httpx.delete(f"{API_BASE}/geofence/{fence_id}", headers=get_headers())
            response.raise_for_status()
            console.print("[green]Geofence deactivated[/green]")
        except httpx.HTTPError as e:
            console.print(f"[red]Error: {e}[/red]")
            sys.exit(1)
    else:
        console.print(f"[red]Unknown action: {action}[/red]")
        sys.exit(1)

@app.command("export")
def export_history(n: int = typer.Option(100, "--n", help="Max records to export")) -> None:
    output = f"locations_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
    try:
        response = httpx.get(f"{API_BASE}/location/history?limit={n}", headers=get_headers())
        response.raise_for_status()
        data = response.json()
        with open(output, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["id", "latitude", "longitude", "battery", "recorded_at", "created_at"])
            for loc in data["data"]:
                writer.writerow([loc["id"], loc["latitude"], loc["longitude"], loc["battery"] or "", loc["recorded_at"], loc["created_at"]])
        console.print(f"[green]Exported {len(data['data'])} records to {output}[/green]")
    except httpx.HTTPError as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)

if __name__ == "__main__":
    app()
'''
with open("cli/main.py", "w") as f: f.write(cli_py)

# 10. app/scheduler.py
scheduler_py = '''"""
Scheduler module for background jobs.
"""
import asyncio
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.database import SessionLocal
from app.services import geofence as geofence_svc
from app.services import location as location_svc
from app.services.notifier import send_telegram

logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()

async def check_geofences_job() -> None:
    def _run_job():
        db = SessionLocal()
        try:
            latest = location_svc.get_latest(db)
            if not latest:
                logger.info("No location data yet - skipping geofence check.")
                return []
            return geofence_svc.check_all_geofences(db, latest)
        except Exception as e:
            logger.exception(f"Geofence DB job failed: {e}")
            return []
        finally:
            db.close()
            
    try:
        alerts = await asyncio.to_thread(_run_job)
        for alert in alerts:
            success = await send_telegram(alert.message)
            if success:
                logger.info(f"Alert sent: {alert.message[:100]}...")
            else:
                logger.warning(f"Telegram dispatch failed for alert id={alert.id}")
    except Exception as e:
        logger.exception(f"Geofence job failed: {e}")

def start_scheduler() -> None:
    scheduler.add_job(
        check_geofences_job,
        trigger=IntervalTrigger(minutes=5),
        id="geofence_check",
        name="Geofence breach checker",
        replace_existing=True,
        misfire_grace_time=60,
    )
    scheduler.start()
    logger.info("APScheduler started.")

def stop_scheduler() -> None:
    scheduler.shutdown(wait=True)
    logger.info("APScheduler shut down.")
'''
with open("app/scheduler.py", "w") as f: f.write(scheduler_py)

# 11. dashboard/index.html
with open("dashboard/index.html", "r") as f: html = f.read()
if "batteryBar" not in html:
    html = html.replace(
        '<span id="batteryLevel">--</span>',
        '<div style="background: #e5e7eb; height: 10px; border-radius: 5px; overflow: hidden; margin-top: 5px;"><div id="batteryBar" style="height: 100%; width: 0%; transition: width 0.3s; background: #22c55e;"></div></div><span id="batteryLevel">--</span>'
    )
    html = html.replace(
        "document.getElementById('batteryLevel').innerHTML = `<span class=\"${getBatteryClass(location.battery)}\">${location.battery || 'N/A'}%</span>`;",
        "document.getElementById('batteryLevel').innerHTML = `<span class=\"${getBatteryClass(location.battery)}\">${location.battery || 'N/A'}%</span>`;\ndocument.getElementById('batteryBar').style.width = `${location.battery || 0}%`;\ndocument.getElementById('batteryBar').style.background = location.battery >= 70 ? '#22c55e' : (location.battery >= 30 ? '#f59e0b' : '#ef4444');"
    )
if "custom icon" not in html:
    html = html.replace("L.marker(latLng).addTo(map)", "L.marker(latLng, {icon: L.icon({iconUrl: 'https://cdn.rawgit.com/pointhi/leaflet-color-markers/master/img/marker-icon-2x-red.png', shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-shadow.png', iconSize: [25, 41], iconAnchor: [12, 41], popupAnchor: [1, -34], shadowSize: [41, 41]})}).addTo(map)")
if "Status Bar" not in html:
    html = html.replace("Auto-refresh:", 'Ping Count: <span id="pingCount">--</span> | Uptime: <span id="uptimeScore">--</span>% | Auto-refresh:')
    html = html.replace(
        "const [latest, history, geofences] = await Promise.all([",
        "const [latest, history, geofences, stats] = await Promise.all([\nfetchLatest(),\nfetchHistory(),\nfetchGeofences(),\nfetch(`${API_BASE}/stats`, {headers: HEADERS}).then(r=>r.json()).catch(()=>null)\n]); //"
    )
    html = html.replace(
        "if (geofences) drawGeofences(geofences);",
        "if (geofences) drawGeofences(geofences);\nif (stats) { document.getElementById('pingCount').textContent = stats.total_pings; document.getElementById('uptimeScore').textContent = stats.uptime_score_24h; }"
    )

with open("dashboard/index.html", "w") as f: f.write(html)

