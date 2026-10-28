"""SQLAlchemy engine, sesija i deklarativna baza."""
from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings

# SQLite treba poseban connect_arg za rad s više niti (dev/lokalno).
_connect_args = {}
_url = settings.database_url
# Fly/Heroku daju "postgres://"; SQLAlchemy 2.0 traži "postgresql://".
if _url.startswith("postgres://"):
    _url = "postgresql://" + _url[len("postgres://"):]
_pool_kwargs = {}
_je_sqlite = _url.startswith("sqlite")
_je_sqlite_memorija = _je_sqlite and (":memory:" in _url or _url == "sqlite://")
if _je_sqlite:
    # check_same_thread=False → rad iz više niti (FastAPI threadpool).
    # timeout=30 → ako je baza zaključana (SQLite ima jednog pisca), čekaj do 30 s
    # umjesto da odmah padne na "database is locked" i drži vezu uzalud.
    _connect_args = {"check_same_thread": False, "timeout": 30}
    # Datotečni SQLite (produkcija) koristi QueuePool → podesi veličinu. In-memory
    # (testovi) koristi SingletonThreadPool koji te parametre NE prima, pa ih preskačemo.
    if not _je_sqlite_memorija:
        _pool_kwargs = {"pool_size": 10, "max_overflow": 20, "pool_timeout": 30}
else:
    # Postgres (produkcija): veći pool da se pod gužvom (više pollera na /api/plan)
    # ne iscrpi — inače zahtjevi čekaju vezu 30 s i padnu na 500. pool_recycle
    # reciklira stare veze koje je Postgres u međuvremenu zatvorio.
    _pool_kwargs = {"pool_size": 10, "max_overflow": 20, "pool_recycle": 1800, "pool_timeout": 30}

engine = create_engine(_url, pool_pre_ping=True, connect_args=_connect_args, **_pool_kwargs)

if _je_sqlite:
    # WAL: čitači ne blokiraju pisca i obrnuto → puno bolja istovremenost pod pollingom.
    # Bez ovoga svako pisanje zaključa cijelu bazu i /api/plan pollovi se gomilaju dok
    # pool ne pukne (QueuePool timeout). busy_timeout = čekanje na zaključanu bazu.
    @event.listens_for(engine, "connect")
    def _postavi_sqlite_pragme(dbapi_conn, _rec):  # noqa: ANN001
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA busy_timeout=30000")
        cur.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
