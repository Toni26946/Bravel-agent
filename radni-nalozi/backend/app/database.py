"""SQLAlchemy engine, sesija i deklarativna baza."""
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings

# SQLite treba poseban connect_arg za rad s više niti (dev/lokalno).
_connect_args = {}
_url = settings.database_url
if _url.startswith("sqlite"):
    _connect_args = {"check_same_thread": False}

engine = create_engine(_url, pool_pre_ping=True, connect_args=_connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
