from __future__ import annotations

from functools import lru_cache

from alembic import command
from alembic.config import Config
from sqlalchemy.engine import Engine
from sqlmodel import Session, create_engine, select

from app.core.config import settings
from app.core.security import get_password_hash
from app.models import User


@lru_cache
def get_engine(database_url: str) -> Engine:
    return create_engine(database_url, pool_pre_ping=True)


engine = get_engine(settings.database_url)


def run_migrations(database_url: str | None = None) -> None:
    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", database_url or settings.database_url)
    command.upgrade(alembic_cfg, "head")


def init_db(session: Session) -> None:
    user = session.exec(
        select(User).where(User.username == settings.bootstrap_admin_username.strip())
    ).first()
    if user:
        return
    now = User.now()
    session.add(
        User(
            username=settings.bootstrap_admin_username.strip(),
            password_hash=get_password_hash(settings.bootstrap_admin_password),
            role="admin",
            is_active=True,
            created_at=now,
            updated_at=now,
        )
    )
    session.commit()
