import re
import warnings

import psycopg
import pytest
from database_support import CREATED_DATABASES
from psycopg import sql
from sqlalchemy.engine import make_url
from sqlalchemy.orm import close_all_sessions

from app.core.db import get_engine


def dispose_test_connections(databases: list[tuple[str, str]]) -> None:
    close_all_sessions()
    for admin_url, database_name in databases:
        database_url = make_url(admin_url).set(drivername="postgresql+psycopg", database=database_name)
        get_engine(database_url.render_as_string(hide_password=False)).dispose()


@pytest.fixture(autouse=True)
def release_test_connections():
    first_database = len(CREATED_DATABASES)
    yield
    dispose_test_connections(CREATED_DATABASES[first_database:])


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Pytest discovers lifecycle hooks in conftest, not ordinary test modules."""
    dispose_test_connections(CREATED_DATABASES)
    get_engine.cache_clear()
    for admin_url, database_name in CREATED_DATABASES:
        try:
            if not re.fullmatch(r"reader_test_[0-9a-f]{32}", database_name):
                raise ValueError("Refusing to remove an unrecognized test database name.")
            with psycopg.connect(admin_url, autocommit=True) as connection:
                connection.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                    sql.Identifier(database_name)))
        except Exception as exc:
            warnings.warn(f"Test database cleanup failed for {database_name}: {exc}", stacklevel=1)
            session.exitstatus = pytest.ExitCode.TESTS_FAILED
    CREATED_DATABASES.clear()
