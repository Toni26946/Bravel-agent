"""Jednokratna migracija SQLite → Postgres (privremeno).

Radi NA mašini (ima lokalni SQLite + doseže Postgres preko interne mreže), pa nije
potreban produkcijski shell. Čita sve tablice iz trenutne (SQLite) baze i prepisuje ih
u Postgres zadan preko PG_TARGET_URL, u ispravnom redoslijedu (FK-safe), pa popravi
sekvence. Gateano: vlasnik + tajni MIGRACIJA_TOKEN. Nakon migracije se uklanja.
"""
import logging
import os

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Integer, create_engine, func, insert, select, text

from ..auth import zahtijevaj_plan_pristup
from ..database import Base, engine as izvor_engine
from ..models import Korisnik

log = logging.getLogger("migracija")
router = APIRouter(prefix="/migracija", tags=["migracija"])
_vlasnik = zahtijevaj_plan_pristup()


def _norm(u: str) -> str:
    return ("postgresql://" + u[len("postgres://"):]) if u.startswith("postgres://") else u


@router.post("/u-postgres")
def u_postgres(token: str = Query(...), force: bool = Query(False),
               _: Korisnik = Depends(_vlasnik)) -> dict:
    tajna = os.getenv("MIGRACIJA_TOKEN", "")
    if not tajna or token != tajna:
        raise HTTPException(status_code=403, detail="Kriv ili nepostavljen token")
    pg_url = _norm(os.getenv("PG_TARGET_URL", "").strip())
    if not pg_url:
        raise HTTPException(status_code=400, detail="PG_TARGET_URL nije postavljen")

    pg = create_engine(pg_url, pool_pre_ping=True)
    Base.metadata.create_all(pg)   # stvori shemu u Postgresu

    rez: dict[str, int] = {}
    with izvor_engine.connect() as sc, pg.begin() as pc:
        # sigurnost: ne prepisuj ako PG već ima podatke (osim force)
        if not force:
            for t in Base.metadata.sorted_tables:
                n = pc.execute(select(func.count()).select_from(t)).scalar() or 0
                if n:
                    raise HTTPException(status_code=409,
                                        detail=f"PG tablica {t.name} nije prazna ({n}). force=1 ako namjerno.")
        # Isključi FK provjeru tijekom punjenja (SQLite ne provjerava FK pa postoje
        # siročad reference; app ih tolerira). Superuser može session_replication_role.
        pc.execute(text("SET session_replication_role = replica"))
        for t in Base.metadata.sorted_tables:
            rows = [dict(r._mapping) for r in sc.execute(select(t))]
            if rows:
                pc.execute(insert(t), rows)
            rez[t.name] = len(rows)
        pc.execute(text("SET session_replication_role = origin"))
        # popravi sekvence (no-op ako tablica nema serial PK)
        for t in Base.metadata.sorted_tables:
            for col in t.primary_key.columns:
                if not isinstance(col.type, Integer):
                    continue   # sekvenca samo za cjelobrojne PK-ove (ne npr. postavke.kljuc)
                pc.execute(text(
                    "SELECT setval(seq, GREATEST(COALESCE(maxid, 1), 1), true) "
                    "FROM (SELECT pg_get_serial_sequence(:tbl, :col) AS seq, "
                    f'(SELECT MAX("{col.name}") FROM "{t.name}") AS maxid) q WHERE seq IS NOT NULL'
                ), {"tbl": t.name, "col": col.name})
    log.info("Migracija u Postgres gotova: %s", rez)
    return {"ok": True, "tablice": rez, "ukupno_tablica": len(rez)}
