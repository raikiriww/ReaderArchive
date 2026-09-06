"""Track only disposable databases created by the current test process."""

import os
from uuid import uuid4

import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url

CREATED_DATABASES: list[tuple[str, str]] = []


def make_database_url() -> str:
    base_url = make_url(
        os.environ.get("READER_TEST_DATABASE_URL")
        or os.environ.get("READER_DATABASE_URL")
        or "postgresql+psycopg://reader:reader@db:5432/reader"
    )
    database_name = f"reader_test_{uuid4().hex}"
    admin_url = base_url.set(drivername="postgresql", database="postgres")
    with psycopg.connect(admin_url.render_as_string(hide_password=False), autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
    CREATED_DATABASES.append((admin_url.render_as_string(hide_password=False), database_name))
    return base_url.set(database=database_name).render_as_string(hide_password=False)
