import httpx
from fastapi.testclient import TestClient
from app.main import app

from app.config import settings

client = TestClient(app)
headers = {"X-API-Key": settings.api_key}

def audit_api():
    print(f"DEBUG: API Key from settings: {settings.api_key}")
    print("--- Phase 4: API Audit ---")
    
    # POST /track
    print("Testing POST /track...")
    resp = client.post("/track", json={"latitude": 0.0, "longitude": 0.0, "battery": 80}, headers=headers)
    assert resp.status_code == 202
    print("POST /track: SUCCESS")

    # GET /location/latest
    print("Testing GET /location/latest...")
    resp = client.get("/location/latest", headers=headers)
    assert resp.status_code == 200
    print("GET /location/latest: SUCCESS")

    # GET /stats
    print("Testing GET /stats...")
    resp = client.get("/stats", headers=headers)
    assert resp.status_code == 200
    print("GET /stats: SUCCESS")

    # Geofence
    print("Testing Geofence endpoints...")
    resp = client.post("/geofence", json={"name": "Audit", "latitude": 0.0, "longitude": 0.0, "radius_meters": 100}, headers=headers)
    assert resp.status_code == 200
    print("POST /geofence: SUCCESS")
    
    print("API Audit: VERIFIED")

if __name__ == "__main__":
    audit_api()
