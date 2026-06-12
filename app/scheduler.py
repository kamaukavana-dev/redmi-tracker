"""
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
