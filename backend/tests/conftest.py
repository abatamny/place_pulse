import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


TEST_DATABASE_NAME = os.getenv("TEST_POSTGRES_DB", "placepulse_test")
TEST_MEDIA_ROOT = Path(os.getenv("TEST_MEDIA_ROOT", "/tmp/placepulse-test-media"))
os.environ["POSTGRES_DB"] = TEST_DATABASE_NAME
os.environ["MEDIA_ROOT"] = str(TEST_MEDIA_ROOT)
os.environ["SMS_PROVIDER"] = ""


@pytest.fixture(scope="session")
def database_ready() -> None:
    from tests.support.database import ensure_test_database

    ensure_test_database(TEST_DATABASE_NAME)
    from app.database import create_schema

    create_schema()


@pytest.fixture(scope="session")
def client(database_ready: None) -> TestClient:
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def clean_database(database_ready: None):
    from tests.support.database import clean_test_data

    clean_test_data(TEST_MEDIA_ROOT)
    yield
    clean_test_data(TEST_MEDIA_ROOT)
