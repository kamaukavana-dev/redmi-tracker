import sys
from fastapi.testclient import TestClient
from app.main import app
from app.database import Base, engine

Base.metadata.create_all(bind=engine)
client = TestClient(app, raise_server_exceptions=True)
try:
    payload = {"latitude": -1.2921, "longitude": 36.8219, "battery": 85}
    response = client.post("/track", json=payload, headers={"X-API-Key": "test-key-123"})
    print("STATUS:", response.status_code)
    print("BODY:", response.json())
except Exception as e:
    import traceback
    traceback.print_exc()
