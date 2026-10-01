"""Faza 2 — učinak servisera: ljestvica (score) i osobni red poslova.

Cijena posla = norma(kategorija operacije) × (€/norma-sat)/60. Kad je zadatak
označen gotovim, njegov dio cijene (cijena operacije / broj zadataka u operaciji,
podijeljeno na radnike koji su radili zadatak) pribraja se učinku tih radnika.
Tako „stisni gotovo" odmah donosi zaradu i motivira samostalnost.

Shadow mode i dalje vrijedi za stvarnu plaću — ovo je prikaz učinka.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import trenutni_korisnik, zahtijevaj_uloge
from ..database import get_db
from ..models import (
    Korisnik,
    NormaPosla,
    Uloga,
    Zadatak,
    zadatak_radnici,
)
from ..norme import KLJUC_EUR, get_postavka, norm_kat

router = APIRouter(prefix="/ucinak", tags=["ucinak"])

voditelj_ili_poslovodja = zahtijevaj_uloge(Uloga.voditelj, Uloga.poslovodja)


def _eur(db: Session) -> float:
    try:
        return float(get_postavka(db, KLJUC_EUR, "0") or 0)
    except (TypeError, ValueError):
        return 0.0


def _norme_map(db: Session) -> dict[str, int]:
    return {n.kategorija: n.norma_min for n in db.execute(select(NormaPosla)).scalars().all()}


def _cijena_op(norma_min: int | None, eur: float) -> float:
    return round((norma_min or 0) * eur / 60.0, 2)


def _radnici_zadatka(z: Zadatak) -> list[Korisnik]:
    r = list(z.radnici)
    if not r and z.zaduzeni is not None:
        r = [z.zaduzeni]
    return r


def _skor(db: Session, od: datetime, do: datetime) -> tuple[dict[int, float], dict[int, int]]:
    """Vrati (zarada_po_radniku, broj_poslova_po_radniku) za gotove zadatke u razdoblju."""
    eur = _eur(db)
    norme = _norme_map(db)
    zadaci = db.execute(
        select(Zadatak).where(
            Zadatak.zavrseno.isnot(None),
            Zadatak.zavrseno >= od,
            Zadatak.zavrseno <= do,
        )
    ).scalars().all()
    op_broj_zad: dict[int, int] = {}
    zarada: dict[int, float] = defaultdict(float)
    broj: dict[int, int] = defaultdict(int)
    for z in zadaci:
        op = z.operacija
        if op is None:
            continue
        if op.id not in op_broj_zad:
            op_broj_zad[op.id] = db.scalar(
                select(func.count()).select_from(Zadatak).where(Zadatak.operacija_id == op.id)
            ) or 1
        norma = norme.get(norm_kat(op.kategorija))
        if not norma:
            continue
        cij = _cijena_op(norma, eur) / max(1, op_broj_zad[op.id])
        rad = _radnici_zadatka(z)
        if not rad:
            continue
        dio = cij / len(rad)
        for r in rad:
            zarada[r.id] += dio
            broj[r.id] += 1
    return zarada, broj


def _raspon(dana: int) -> tuple[datetime, datetime]:
    do = datetime.now(timezone.utc)
    od = do - timedelta(days=dana)
    return od, do


@router.get("/ljestvica")
def ljestvica(dana: int = Query(default=7, ge=1, le=365),
              db: Session = Depends(get_db), _: Korisnik = Depends(voditelj_ili_poslovodja)):
    od, do = _raspon(dana)
    zarada, broj = _skor(db, od, do)
    imena = {k.id: k.ime for k in db.execute(
        select(Korisnik).where(Korisnik.id.in_(list(zarada.keys()) or [0]))
    ).scalars().all()}
    redovi = [
        {
            "radnik_id": rid,
            "ime": imena.get(rid, "—"),
            "zarada_eur": round(z, 2),
            "broj_poslova": broj.get(rid, 0),
        }
        for rid, z in zarada.items()
    ]
    redovi.sort(key=lambda r: r["zarada_eur"], reverse=True)
    for i, r in enumerate(redovi):
        r["mjesto"] = i + 1
    ukupno = round(sum(r["zarada_eur"] for r in redovi), 2)
    return {"dana": dana, "eur_po_normi": _eur(db), "ukupno_eur": ukupno, "redovi": redovi}


@router.get("/moj")
def moj_ucinak(dana: int = Query(default=7, ge=1, le=365),
               db: Session = Depends(get_db), ja: Korisnik = Depends(trenutni_korisnik)):
    od, do = _raspon(dana)
    zarada, broj = _skor(db, od, do)
    poredak = sorted(zarada.items(), key=lambda kv: kv[1], reverse=True)
    mjesto = next((i + 1 for i, (rid, _z) in enumerate(poredak) if rid == ja.id), None)
    eur = _eur(db)
    norme = _norme_map(db)

    # Otvoreni red poslova dodijeljenih meni (nezavršeni zadaci).
    red = db.execute(
        select(Zadatak)
        .join(zadatak_radnici, zadatak_radnici.c.zadatak_id == Zadatak.id)
        .where(zadatak_radnici.c.radnik_id == ja.id, Zadatak.gotovo.is_(False))
        .order_by(Zadatak.zapoceto.isnot(None).desc(), Zadatak.redoslijed, Zadatak.id)
    ).scalars().all()
    poslovi = []
    for z in red:
        op = z.operacija
        if op is None:
            continue
        nalog = op.nalog
        vozilo = nalog.vozilo if nalog else None
        norma = norme.get(norm_kat(op.kategorija))
        poslovi.append({
            "zadatak_id": z.id,
            "nalog_id": nalog.id if nalog else None,
            "nalog_broj": nalog.broj if nalog else None,
            "vozilo": (vozilo.gb if vozilo else None),
            "registracija": (vozilo.registracija if vozilo else None),
            "operacija": op.kategorija,
            "opis": z.opis,
            "cijena_eur": _cijena_op(norma, eur),
            "mjeri": z.zapoceto is not None,
        })
    return {
        "dana": dana,
        "zarada_eur": round(zarada.get(ja.id, 0.0), 2),
        "broj_poslova": broj.get(ja.id, 0),
        "mjesto": mjesto,
        "ukupno_servisera": len(poredak),
        "red": poslovi,
    }
