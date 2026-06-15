# COVERAGE_GAP_MAP.md

**Date:** 2026-06-15
**Auditor:** Principal Engineer (Final Coverage Closure)
**Status:** Phase 1 Complete

---

## 1. Uncovered Paths

### `app/services/notifier.py`
- Coverage: 88%
- Missing lines:
  - 119-121: Exception handler in `send_telegram_with_retry` for unexpected exceptions.
  - 158: HTTP error handler in `validate_telegram_token`.
  - 165-167: General exception handler in `validate_telegram_token`.
  - 177-184: Body of `send_health_check`.

### `app/services/geofence.py`
- Coverage: 80%
- Missing lines:
  - 93: Logging statement in `get_geofence` (if fence not found).
  - 169-219: Logic branches in `evaluate_geofence` regarding complex state transitions.
  - 294-297: Logging in `check_all_geofences`.
  - 373-418: Complex alert generation logic branches.
  - 423, 428-429: Alert persistence logic.

---

## 2. Remediation Plan
- **Notifier:** Implement tests for `send_health_check` and trigger all exception handlers with mocked `httpx` exceptions.
- **Geofence:** Add tests for `evaluate_geofence` that cover every decision branch (initial, re-entry, cooldown, etc.) and add comprehensive tests for `check_all_geofences` covering breach detection logic.
