"""
Production-grade scheduler module for background jobs.

Implements:
- Geofence breach detection with full event lifecycle
- Device health monitoring (offline, low battery, stale GPS)
- Graceful error handling with comprehensive logging
- Structured observability for all operations
"""

import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.database import SessionLocal
from app.services import geofence as geofence_svc
from app.services import location as location_svc
from app.services.notifier import send_telegram_with_retry
from app.config import settings

logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()


async def check_geofences_job() -> None:
    """
    Geofence breach detection job with complete observability.

    Workflow:
    1. Fetch latest device location
    2. Validate location data
    3. Evaluate all active geofences
    4. Generate alerts for state transitions
    5. Send notifications with retry logic
    6. Log all decisions for audit trail

    Error Handling:
    - Database errors are caught and logged
    - Notification failures do not crash the job
    - All decisions are explainable from logs
    """
    db = SessionLocal()
    job_start = datetime.utcnow()

    try:
        logger.info("Starting geofence evaluation job")

        # Fetch latest location
        latest = location_svc.get_latest(db)

        if not latest:
            logger.warning("No location data available - skipping geofence check")
            return

        logger.info(
            f"Evaluating geofences for location: {latest.latitude:.5f}, {latest.longitude:.5f}",
            extra={
                "location_id": latest.id,
                "latitude": latest.latitude,
                "longitude": latest.longitude,
                "battery": latest.battery,
                "recorded_at": latest.recorded_at.isoformat(),
            },
        )

        # Check geofences
        alerts = geofence_svc.check_all_geofences(db, latest)

        logger.info(f"Geofence evaluation complete: {len(alerts)} breach alert(s) generated")

        # Send notifications
        for alert_ctx in alerts:
            message = geofence_svc.format_telegram_message(alert_ctx)

            logger.info(
                f"Sending breach alert: {alert_ctx.alert_id}",
                extra={
                    "alert_id": alert_ctx.alert_id,
                    "event_type": alert_ctx.event_type.value,
                    "severity": alert_ctx.severity.value,
                    "geofence_name": alert_ctx.geofence_name,
                    "distance_meters": alert_ctx.distance_meters,
                },
            )

            success = await send_telegram_with_retry(message)

            if success:
                logger.info(f"Alert {alert_ctx.alert_id} sent successfully")
            else:
                logger.error(f"Failed to send alert {alert_ctx.alert_id} after retries")

        # Check device health
        health_alerts = geofence_svc.check_device_health(db, latest)

        for alert_ctx in health_alerts:
            message = geofence_svc.format_telegram_message(alert_ctx)

            logger.info(
                f"Sending health alert: {alert_ctx.alert_id}",
                extra={
                    "alert_id": alert_ctx.alert_id,
                    "event_type": alert_ctx.event_type.value,
                    "severity": alert_ctx.severity.value,
                },
            )

            success = await send_telegram_with_retry(message)

            if success:
                logger.info(f"Health alert {alert_ctx.alert_id} sent successfully")
            else:
                logger.error(f"Failed to send health alert {alert_ctx.alert_id} after retries")

        job_duration = (datetime.utcnow() - job_start).total_seconds()
        logger.info(
            f"Geofence job completed in {job_duration:.2f}s",
            extra={
                "job_duration_seconds": job_duration,
                "breach_alerts": len(alerts),
                "health_alerts": len(health_alerts),
            },
        )

    except Exception as e:
        logger.exception(f"Geofence job failed with unexpected error: {e}")
    finally:
        db.close()


async def check_device_offline_job() -> None:
    """
    Device offline detection job.

    Checks if device has not reported location within threshold.
    Sends alert if device is considered offline.
    """
    db = SessionLocal()

    try:
        logger.info("Checking device offline status")

        latest = location_svc.get_latest(db)

        if not latest:
            logger.warning("No location data ever received - device may be offline")
            # Could send alert here if we want to track "never connected"
            return

        time_since_update = (datetime.utcnow() - latest.recorded_at).total_seconds() / 60

        if time_since_update > settings.offline_threshold_minutes:
            logger.warning(
                f"Device offline: last seen {time_since_update:.0f} minutes ago",
                extra={
                    "minutes_since_update": time_since_update,
                    "threshold_minutes": settings.offline_threshold_minutes,
                },
            )

            # Create offline alert
            from app.services.alerting import AlertContext, EventType, SeverityLevel

            alert_ctx = AlertContext.create(
                event_type=EventType.DEVICE_OFFLINE,
                severity=SeverityLevel.HIGH,
                device_name=settings.device_name,
                geofence_name=None,
                latitude=latest.latitude,
                longitude=latest.longitude,
                distance_meters=0,
                radius_meters=None,
                battery_level=latest.battery,
                previous_state=None,
                current_state=False,
            )

            message = geofence_svc.format_telegram_message(alert_ctx)
            success = await send_telegram_with_retry(message)

            if success:
                logger.info(f"Offline alert sent for device {alert_ctx.alert_id}")
            else:
                logger.error(f"Failed to send offline alert after retries")

        else:
            logger.info(f"Device online: last update {time_since_update:.0f} minutes ago")

    except Exception as e:
        logger.exception(f"Device offline check failed: {e}")
    finally:
        db.close()


def start_scheduler() -> None:
    """
    Start the APScheduler with all configured jobs.

    Jobs:
    - Geofence check: Every 5 minutes
    - Device offline check: Every 10 minutes
    """
    # Geofence breach detection
    scheduler.add_job(
        check_geofences_job,
        trigger=IntervalTrigger(minutes=5),
        id="geofence_check",
        name="Geofence breach checker",
        replace_existing=True,
        misfire_grace_time=60,
        max_instances=1,  # Prevent overlapping executions
    )

    # Device offline detection
    scheduler.add_job(
        check_device_offline_job,
        trigger=IntervalTrigger(minutes=10),
        id="device_offline_check",
        name="Device offline detector",
        replace_existing=True,
        misfire_grace_time=120,
        max_instances=1,
    )

    scheduler.start()
    logger.info("APScheduler started with geofence and device health monitoring")


def stop_scheduler() -> None:
    """Gracefully shut down the scheduler."""
    scheduler.shutdown(wait=True)
    logger.info("APScheduler shut down complete")