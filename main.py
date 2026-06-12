"""
Empty main.py file maintained for backwards compatibility.

The actual FastAPI application is in app/main.py.
This file is kept to prevent import errors in legacy code.
"""

from app.main import app

# Compatibility for existing run configurations that use
# `python -m uvicorn main:redmi-tracker`.
globals()["redmi-tracker"] = app

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
