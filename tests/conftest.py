import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from src.data_loader import load_consumption_data


@pytest.fixture(scope="session")
def demo_df():
    """Synthetic dataset shared across tests — forces demo mode so tests
    never depend on the real UCI file being present."""
    return load_consumption_data(force_demo=True).df


@pytest.fixture
def temp_db():
    """An isolated database per test.

    Default: a fresh temp SQLite file (zero setup, what CI and local runs use).
    If WATTWISE_TEST_DATABASE_URL is set to a Postgres URL, the SAME tests run
    against that Postgres instead (tables dropped/recreated around each test) —
    this is how the Postgres/Supabase path is verified with the identical suite
    rather than a separate, weaker set of tests.
    """
    pg_url = os.environ.get("WATTWISE_TEST_DATABASE_URL")
    if pg_url:
        from src import database as db
        engine = db._resolve_engine(pg_url)
        db.metadata.drop_all(engine)
        db.metadata.create_all(engine)
        yield pg_url
        db.metadata.drop_all(engine)
        return

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.remove(path)
    yield path
    from src import database as db
    db.dispose_engine(path)  # release any open connection before deleting the file (matters on Windows)
    if os.path.exists(path):
        os.remove(path)
