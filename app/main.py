"""
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
    strict = settings.strict_startup_validation
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
        message = f"Database connection failed: {e}"
        if strict:
            logger.error(message)
            sys.exit(1)
        logger.warning("%s; continuing because STRICT_STARTUP_VALIDATION is false.", message)
    finally:
        db.close()

    if strict:
        try:
            is_valid = await validate_telegram_token()
            if not is_valid:
                logger.error("Telegram token validation failed. Check TELEGRAM_BOT_TOKEN.")
                sys.exit(1)
            logger.info("telegram ✅")
        except Exception as e:
            logger.error(f"Telegram validation error: {e}")
            sys.exit(1)
    else:
        logger.info("telegram validation skipped because STRICT_STARTUP_VALIDATION is false.")

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
    logger.error(f"Validation error on {request.method} {request.url.path}: {exc.errors()}")
    return await build_error_response(request, exc, 422, "Request validation failed")

@app.exception_handler(SQLAlchemyError)
async def sqlalchemy_exception_handler(request: Request, exc: SQLAlchemyError) -> JSONResponse:
    return await build_error_response(request, exc, 500, "Database operation failed")

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return await build_error_response(request, exc, exc.status_code, exc.detail)

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception(f"Unhandled exception: {exc}")
    return await build_error_response(request, exc, 500, "Internal server error")

from fastapi import Depends
@app.get("/health", response_model=HealthResponse)
async def health_check(db: Session = Depends(get_db)) -> HealthResponse:
    db_healthy = False
    telegram_healthy = not settings.strict_startup_validation
    try:
        db.execute(text("SELECT 1"))
        db_healthy = True
    except Exception as e:
        logger.error(f"Health check DB error: {e}")
    if settings.strict_startup_validation:
        try:
            telegram_healthy = await validate_telegram_token()
        except Exception as e:
            logger.error(f"Health check Telegram error: {e}")
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
# cache bust Sat Jun 13 08:55:05 PM EAT 2026
