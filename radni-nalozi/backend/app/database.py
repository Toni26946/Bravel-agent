"""SQLAlchemy engine, sesija i deklarativna baza."""
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings

# SQLite treba poseban connect_arg za rad s više niti (dev/lokalno).
_connect_args = {}
_url = settings.database_url
_pool_kwargs = {}
if _url.startswith("sqlite"):
    _connect_args = {"check_same_thread": False}
else:
    # Postgres (produkcija): veći pool da se pod gužvom (više pollera na /api/plan)
    # ne iscrpi — inače zahtjevi čekaju vezu 30 s i padnu na 500. pool_recycle
    # reciklira stare veze koje je Postgres u međuvremenu zatvorio.
    _pool_kwargs = {"pool_size": 10, "max_overflow": 20, "pool_recycle": 1800, "pool_timeout": 30}

engine = create_engine(_url, pool_pre_ping=True, connect_args=_connect_args, **_pool_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
