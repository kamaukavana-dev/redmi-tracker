"""
Database configuration and session management module.

Provides SQLAlchemy engine configuration with connection pooling,
session factory, and dependency injection for FastAPI routes.
"""

from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    """SQLAlchemy declarative base class for all models."""


engine = create_engine(
    settings.database_url,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    pool_recycle=3600,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator:
    """
    FastAPI dependency that yields a database session.

    Yields:
        SQLAlchemy Session object for database operations.

    Raises:
        None: Exceptions are handled by calling code.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()