import pytest


@pytest.fixture(autouse=True)
def isolated_database(clean_database) -> None:
    """Give every security test an empty database and media directory."""
