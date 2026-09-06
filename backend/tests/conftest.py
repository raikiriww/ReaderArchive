import re
import warnings

import psycopg
import pytest
from database_support import CREATED_DATABASES
from psycopg import sql

from app.core.db import get_engine


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Pytest discovers lifecycle hooks in conftest, not ordinary test modules."""
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
