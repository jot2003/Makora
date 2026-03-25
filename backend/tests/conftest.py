"""Shared test fixtures."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models.database as db_module
from app.models.database import Base


@pytest.fixture()
def client():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    original = db_module.SessionLocal
    db_module.SessionLocal = TestSessionLocal

    from app.main import app

    with TestClient(app) as c:
        yield c

    db_module.SessionLocal = original
    Base.metadata.drop_all(bind=engine)
