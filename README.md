# Redmi Tracker

Real-time GPS tracking system with geofence alerts and Telegram notifications. Built for monitoring devices remotely with automatic breach detection.

## Architecture

```
┌─────────────────┐     ┌─────────────────────────────────────────────────────┐
│   MacroDroid    │────▶│              FastAPI Application                    │
│   (Android)     │     │  ┌──────────┐  ┌──────────┐  ┌──────────────────┐  │
│                 │     │  │ Location │  │ Geofence │  │ Stats/Scheduler  │  │
│  • GPS polling  │     │  │ Service  │  │ Service  │  │                  │  │
│  • HTTP POST    │     │  └────┬─────┘  └────┬─────┘  └──────────────────┘  │
└─────────────────┘     │       │             │                               │
                        │       ▼             ▼                               │
                        │  ┌─────────────────────────┐                        │
                        │  │   PostgreSQL Database   │                        │
                        │  │  - locations            │                        │
                        │  │  - geofences            │                        │
                        │  │  - alerts               │                        │
                        │  └─────────────────────────┘                        │
                        └─────────────────────────────────────────────────────┘
                                                │
                                                ▼
                                    ┌─────────────────────────┐
                                    │   Telegram Bot API      │
                                    │   (Push Notifications)  │
                                    └─────────────────────────┘
```

## Tech Stack

| Layer | Technology |
|-------|------------|
| **Backend** | Python 3.12, FastAPI, SQLAlchemy 2.0 |
| **Database** | PostgreSQL (production), SQLite (testing) |
| **Scheduling** | APScheduler |
| **Notifications** | Telegram Bot API |
| **Deployment** | Railway |
| **Testing** | pytest, pytest-asyncio |
| **Validation** | Pydantic v2 |

## Setup Instructions

### 1. Clone the Repository

```bash
git clone https://github.com/kamaukavana-dev/redmi-tracker.git
cd redmi-tracker
```

### 2. Create Virtual Environment

```bash
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# or
.venv\Scripts\activate  # Windows
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables

Create a `.env` file in the project root:

```bash
cp .env.example .env
```

Edit `.env` with your values (see [Environment Variables](#environment-variables)).

### 5. Run the Application

```bash
# Development
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Production
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

Access the API docs at `http://localhost:8000/docs`.

## API Endpoints

| Method | Path | Description | Auth Required |
|--------|------|-------------|---------------|
| `GET` | `/` | Dashboard UI | No |
| `GET` | `/health` | Health check (DB, Telegram) | No |
| `GET` | `/stats` | System statistics | Yes |
| `POST` | `/track` | Submit location from device | Yes |
| `GET` | `/location` | Get latest location | Yes |
| `GET` | `/location/history` | Paginated location history | Yes |
| `GET` | `/location/export` | Export locations as CSV | Yes |
| `POST` | `/geofence` | Create geofence | Yes |
| `GET` | `/geofence` | List active geofences | Yes |
| `DELETE` | `/geofence/{id}` | Deactivate geofence | Yes |
| `GET` | `/geofence/check` | Manual geofence breach check | Yes |

**Authentication:** Include `X-API-Key: <your_api_key>` header for protected endpoints.

## MacroDroid Setup

### Prerequisites
- Android device with MacroDroid app installed
- Server URL and API key from your deployment

### Configuration Steps

1. **Install MacroDroid** from Google Play Store

2. **Create New Macro:**
   - **Trigger:** Location Update (set interval to 5-15 minutes)
   - **Action:** HTTP POST Request

3. **HTTP Request Configuration:**

   ```
   URL: https://your-deployment.railway.app/track
   Method: POST
   Headers:
     Content-Type: application/json
     X-API-Key: your_api_key_here
   Body (JSON):
   {
     "latitude": {location_lat}
     "longitude": {location_lon}
     "battery": {battery_level}
   }
   ```

4. **Variables:** Use MacroDroid's built-in variables:
   - `{location_lat}` - Current latitude
   - `{location_lon}` - Current longitude
   - `{battery_level}` - Battery percentage

5. **Test:** Run the macro manually to verify connectivity

## Deployment (Railway)

### 1. Prepare Railway Project

```bash
# Install Railway CLI
npm install -g @railway/cli

# Login
railway login
```

### 2. Initialize Project

```bash
railway init
railway up
```

### 3. Configure Environment Variables

```bash
railway variables set \
  DATABASE_URL="postgresql://..." \
  API_KEY="your_secure_api_key" \
  TELEGRAM_BOT_TOKEN="bot_token" \
  TELEGRAM_CHAT_ID="chat_id"
```

### 4. Add PostgreSQL

```bash
railway add postgresql
```

### 5. Deploy

```bash
railway up --detach
```

Railway automatically deploys on push to the `main` branch.

## Environment Variables

| Variable | Required | Description | Example |
|----------|----------|-------------|---------|
| `DATABASE_URL` | Yes | PostgreSQL connection string | `postgresql://user:pass@host:5432/db` |
| `API_KEY` | Yes | Secret key for API authentication | `your_secret_key_here` |
| `TELEGRAM_BOT_TOKEN` | Yes | Telegram bot token from BotFather | `123456:ABC-DEF1234...` |
| `TELEGRAM_CHAT_ID` | Yes | Telegram chat ID for alerts | `-1001234567890` |
| `LOG_LEVEL` | No | Logging level (default: INFO) | `DEBUG`, `WARNING`, `ERROR` |
| `RATE_LIMIT_PER_MINUTE` | No | Max requests per API key | `20` |
| `GEOFENCE_COOLDOWN_MINUTES` | No | Cooldown between breach alerts | `30` |
| `STRICT_STARTUP_VALIDATION` | No | Fail startup on validation errors | `true`, `false` |

## Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=app --cov-report=html

# Run specific test file
pytest tests/test_geofence.py -v
```

## Project Structure

```
redmi-tracker/
├── app/
│   ├── config.py          # Environment configuration
│   ├── database.py        # SQLAlchemy setup
│   ├── main.py            # FastAPI application
│   ├── models.py          # Database models
│   ├── schemas.py         # Pydantic schemas
│   ├── services/          # Business logic
│   │   ├── geofence.py    # Geofence calculations
│   │   ├── location.py    # Location management
│   │   └── notifier.py    # Telegram notifications
│   └── routers/           # API route handlers
├── tests/                 # pytest test suite
├── dashboard/             # Static dashboard UI
├── cli/                   # Command-line interface
└── scripts/               # Utility scripts
```

## License

MIT License - See LICENSE file for details.

---

**Author:** [Daniel Maina](https://github.com/kamaukavana-dev)
