# REPOSITORY_AUDIT.md

**Date:** 2026-06-15
**Auditor:** Principal Engineer (Zero Trust Audit)
**Status:** In Progress - Phase 1

---

## 1. System Inventory

### Core Components
- `/app/`: FastAPI application code.
- `/cli/`: CLI tool code.
- `/dashboard/`: Static frontend.
- `/alembic/`: Database migrations.

### Entrypoints
- `app/main.py`: Main FastAPI application.
- `cli/main.py`: CLI entrypoint.

### Services
- `/app/services/`:
  - `alerting.py`
  - `analytics.py`
  - `geofence.py`
  - `geofence_state.py`
  - `location.py`
  - `notifier.py`

### Routers
- `/app/routers/`:
  - `analytics.py`
  - `geofence.py`
  - `location.py`
  - `stats.py`
  - `track.py`

### Database
- Models: `app/models.py`
- Migrations: `alembic/versions/`
- Connection: `app/database.py`

### Tests
- `/tests/`: Contains 17+ test files.

## 2. Infrastructure & Configuration
- `.env.example`: Template for env vars.
- `railway.toml`: Deployment config for Railway.
- `Dockerfile`: Containerization.
- `start.sh`: Entrypoint script.
- `alembic.ini`: Migrations config.
- `pytest.ini`: Testing config.
- `requirements.txt`: Dependencies.

## 3. Preliminary Observations & Risks

### Potential Issues
1. **Committed Database Files:** `local_test.db`, `test_scheduler.db`, `test_stats.db` found in root. *ACTION: Investigate why these are committed.*
2. **Duplicate/Redundant Structure?**: The `redmi-tracker/` directory (seen in initial context scan) needs investigation. If it's a mirror of the root, it's dead/duplicated code.
3. **Empty `.agents/`:** Folder is empty.
4. **`__pycache__` pollution:** Widespread.

## 4. Evidence of Inventory
- Full recursive `ls -a` command executed.
- Verified file paths against provided initial project structure.
