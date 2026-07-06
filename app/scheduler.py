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
from app.services import alert_state
from app.services import geofence as geofence_svc
from app.services import geofence_state as geofence_state_svc
from app.services import location as location_svc
from app.services.notifier import send_telegram_with_retry
from app.config import settings
from app.utils.timeutils import now_utc, as_aware

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
    job_start = now_utc()

    try:
        logger.info("Starting geofence evaluation job")

        # Fetch latest location
        latest = location_svc.get_latest(db)

        if not latest:
            logger.warning("No location data available - skipping geofence check")
            return

        # Stale-data guard: never evaluate geofences against a fix that is too
        # old — it produces false breach/re-entry alerts from a frozen position.
        location_age_min = (now_utc() - as_aware(latest.recorded_at)).total_seconds() / 60
        location_is_stale = location_age_min > settings.location_staleness_threshold_minutes

        if latest.latitude is not None and latest.longitude is not None:
            logger.info(
                f"Evaluating geofences for location: {latest.latitude:.5f}, {latest.longitude:.5f}",
                extra={
                    "location_id": latest.id,
                    "latitude": latest.latitude,
                    "longitude": latest.longitude,
                    "battery": latest.battery,
                    "recorded_at": latest.recorded_at.isoformat(),
                    "location_age_minutes": round(location_age_min, 1),
                },
            )

        # Check geofences using state machine — skipped when data is stale.
        if location_is_stale:
            logger.warning(
                "Latest location is stale (%.1f min old, threshold %d) - "
                "skipping geofence evaluation",
                location_age_min,
                settings.location_staleness_threshold_minutes,
            )
            alerts = []
        else:
            alerts = geofence_state_svc.check_all_geofences_stateful(db, latest)

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

        job_duration = (now_utc() - job_start).total_seconds()
        logger.info(
            f"Geofence job completed: breaches={len(alerts)}, "
            f"health_alerts={len(health_alerts)}, stale={location_is_stale}, "
            f"duration={job_duration:.2f}s",
            extra={
                "job_duration_seconds": job_duration,
                "breach_alerts": len(alerts),
                "health_alerts": len(health_alerts),
                "location_stale": location_is_stale,
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
    job_start = now_utc()

    try:
        logger.info("Starting device offline check")

        latest = location_svc.get_latest(db)

        if not latest:
            logger.warning("No location data ever received - device may be offline")
            # Could send alert here if we want to track "never connected"
            return

        time_since_update = (now_utc() - as_aware(latest.recorded_at)).total_seconds() / 60
        is_offline = time_since_update > settings.offline_threshold_minutes

        # Independent, edge-triggered 30-min cooldown for DEVICE_OFFLINE.
        # should_send_health_alert also re-arms the state when the device is
        # back online, so a single offline episode alerts at most once.
        should_alert = alert_state.should_send_health_alert(
            db, "DEVICE_OFFLINE", is_offline, settings.health_alert_cooldown_minutes
        )

        if is_offline:
            logger.warning(
                f"Device offline: last seen {time_since_update:.0f} minutes ago",
                extra={
                    "minutes_since_update": time_since_update,
                    "threshold_minutes": settings.offline_threshold_minutes,
                    "alerting": should_alert,
                },
            )
        else:
            logger.info(f"Device online: last update {time_since_update:.0f} minutes ago")

        if should_alert:
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

        job_duration = (now_utc() - job_start).total_seconds()
        logger.info(
            f"Device offline check completed: offline={is_offline}, "
            f"alerted={should_alert}, duration={job_duration:.2f}s",
            extra={"job_duration_seconds": job_duration, "device_offline": is_offline},
        )

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