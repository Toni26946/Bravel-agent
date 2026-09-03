"""Jednostavne idempotentne migracije — dodaje stupce koji nedostaju.

create_all() stvara nove tablice, ali ne mijenja postojeće. Ovdje dodajemo
nove stupce na tablicu `nalozi` ako još ne postoje (radi na SQLite i Postgresu).
"""
import logging

from sqlalchemy import Engine, text

log = logging.getLogger("migrate")

# (tablica, stupac, SQL tip)
_STUPCI = [
    ("nalozi", "vozac_id", "INTEGER"),
    ("nalozi", "voditelj_id", "INTEGER"),
    ("zadaci", "zaduzeni_id", "INTEGER"),
    ("zadaci", "zapoceto", "TIMESTAMP"),
    ("zadaci", "zavrseno", "TIMESTAMP"),
    ("zadaci", "utroseno_sek", "INTEGER DEFAULT 0"),
]


def _postojeci_stupci(conn, tablica: str, dialect: str) -> set[str]:
    if dialect == "sqlite":
        rows = conn.exec_driver_sql(f"PRAGMA table_info({tablica})").fetchall()
        return {r[1] for r in rows}
    rows = conn.execute(
        text("SELECT column_name FROM information_schema.columns WHERE table_name = :t"),
        {"t": tablica},
    ).fetchall()
    return {r[0] for r in rows}


def migrate(engine: Engine) -> None:
    dialect = engine.dialect.name
    with engine.begin() as conn:
        for tablica, stupac, tip in _STUPCI:
            postojeci = _postojeci_stupci(conn, tablica, dialect)
            if not postojeci:
                # Tablica ne postoji (npr. create_all je nije stigao stvoriti) — preskoči.
                continue
            if stupac not in postojeci:
                conn.exec_driver_sql(f"ALTER TABLE {tablica} ADD COLUMN {stupac} {tip}")
                log.info("Migracija: dodan stupac %s.%s", tablica, stupac)
