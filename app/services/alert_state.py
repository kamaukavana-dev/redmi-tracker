"""
Alert-state service: cooldown, edge-triggering, and deduplication.

Central home for the logic that stops alert spam:

- ``should_send_health_alert`` implements an independent per-alert-type
  cooldown (minimum 30 minutes) combined with edge-triggering, so a health
  alert fires only when its condition first becomes true and never again
  until the condition clears and re-triggers (and never inside the cooldown).

- ``is_duplicate_message`` / ``record_sent_message`` provide content-based
  deduplication so an identical Telegram message is sent at most once per
  window (default 30 minutes).

All datetimes are timezone-aware UTC.
"""

import hashlib
import logging
from datetime import timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.models import HealthAlertState, NotificationLog
from app.utils.timeutils import now_utc, as_aware

logger = logging.getLogger(__name__)

# Hard floor for every health-alert cooldown, per the post-mortem mandate.
MIN_COOLDOWN_MINUTES = 30
# Deduplication window for identical Telegram messages.
DEDUP_WINDOW_MINUTES = 30


def should_send_health_alert(
    db: Session,
    alert_type: str,
    condition_active: bool,
    cooldown_minutes: int = MIN_COOLDOWN_MINUTES,
) -> bool:
    """
    Decide whether a health alert of ``alert_type`` should fire this tick.

    An alert fires only when ALL of the following hold:
      1. the condition is currently active (e.g. battery below threshold), AND
      2. the condition was NOT already active last tick (edge trigger), AND
      3. the independent cooldown for this alert type has elapsed.

    The per-type state row is updated every call: ``active`` tracks the
    condition so it re-arms once the condition clears, and ``last_alerted_at``
    is stamped only when an alert actually fires.

    Args:
        db: Database session.
        alert_type: One of LOW_BATTERY, GPS_SIGNAL_LOST, DEVICE_OFFLINE.
        condition_active: Whether the bad condition is currently true.
        cooldown_minutes: Requested cooldown; floored at ``MIN_COOLDOWN_MINUTES``.

    Returns:
        True if an alert should be sent now, False otherwise.
    """
    cooldown_minutes = max(MIN_COOLDOWN_MINUTES, cooldown_minutes)
    now = now_utc()

    state = (
        db.query(HealthAlertState)
        .filter(HealthAlertState.alert_type == alert_type)
        .first()
    )
    if state is None:
        state = HealthAlertState(alert_type=alert_type, active=False, last_alerted_at=None)
        db.add(state)
        db.flush()

    last_alerted = as_aware(state.last_alerted_at)
    cooldown_ok = last_alerted is None or (now - last_alerted) >= timedelta(minutes=cooldown_minutes)
    was_active = bool(state.active)

    fire = condition_active and cooldown_ok and not was_active

    # Always record the current condition so the edge re-arms when it clears.
    state.active = condition_active
    if fire:
        state.last_alerted_at = now

    db.commit()

    if condition_active and not fire:
        reason = "cooldown active" if not cooldown_ok else "already alerted for this episode"
        logger.info(
            "Health alert %s suppressed (%s)", alert_type, reason,
            extra={"alert_type": alert_type, "reason": reason},
        )

    return fire


def _hash_message(message: str) -> str:
    return hashlib.sha256(message.encode("utf-8")).hexdigest()


def is_duplicate_message(
    db: Session,
    message: str,
    window_minutes: int = DEDUP_WINDOW_MINUTES,
) -> bool:
    """
    Return True if an identical message was already sent within the window.
    """
    cutoff = now_utc() - timedelta(minutes=window_minutes)
    message_hash = _hash_message(message)
    existing = (
        db.query(NotificationLog)
        .filter(
            NotificationLog.message_hash == message_hash,
            NotificationLog.sent_at >= cutoff,
        )
        .first()
    )
    return existing is not None


def record_sent_message(db: Session, message: str) -> None:
    """Record that ``message`` was just sent, for future dedup checks."""
    db.add(NotificationLog(message_hash=_hash_message(message), sent_at=now_utc()))
    db.commit()
