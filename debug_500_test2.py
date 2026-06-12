import sys
from fastapi.testclient import TestClient
from app.main import app
from app.database import Base, get_db
from app.config import settings
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

TEST_DATABASE_URL = "sqlite:///./debug.db"
engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db
Base.metadata.drop_all(bind=engine)
Base.metadata.create_all(bind=engine)
client = TestClient(app)

payload = {"latitude": -1.2921, "longitude": 36.8219, "battery": 85}
response = client.post("/track", json=payload, headers={"X-API-Key": settings.api_key})
print("STATUS:", response.status_code)
print("BODY:", response.json())
