"""
Scheduler module for background jobs.
"""
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
    db = SessionLocal()
    try:
        latest = location_svc.get_latest(db)
        if not latest:
            logger.info("No location data yet - skipping geofence check.")
            return

        logger.info(f"Latest location: {latest.latitude}, {latest.longitude}")
        messages = geofence_svc.check_all_geofences(db, latest)
        logger.info(f"Breaches found: {len(messages)}")

        for message in messages:
            logger.info(f"Sending alert: {message[:100]}")
            success = await send_telegram(message)
            if success:
                logger.info("Alert sent successfully.")
            else:
                logger.warning("Telegram dispatch failed.")

    except Exception as e:
        logger.exception(f"Geofence job failed: {e}")
    finally:
        db.close()


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