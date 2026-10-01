"""Mozak cijena — norme (standardna vremena) po vrsti posla iz povijesti rada.

Za svaku kategoriju posla iz `povijest_rada` (gdje imamo izmjereno trajanje)
računamo medijan i 60. percentil trajanja. Medijan je zadana norma; voditelj
ga može ručno korigirati. Cijena posla = norma_min × (€/norma-sat)/60.
"""
from __future__ import annotations

import logging
import statistics
from collections import defaultdict
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .models import NormaPosla, Postavka, PovijestRada

log = logging.getLogger("norme")

# Zadane postavke (ključevi u tablici `postavke`).
KLJUC_EUR = "eur_po_normi"      # € po jednom norma-satu
KLJUC_OSNOVICA = "osnovica"     # mjesečna osnovica (€) — informativno
KLJUC_SHADOW = "shadow_mode"    # '1' = samo mjerimo, ne mijenjamo plaću

_SEED_VERZIJA = ".norme_seed_v1"
_MIN_UZORAKA = 3                # ispod ovoga normu treba ručno potvrditi


def norm_kat(s: str | None) -> str:
    """Normaliziraj ime kategorije (veliko, bez viška razmaka)."""
    return " ".join((s or "").strip().upper().split())


def get_postavka(db: Session, kljuc: str, zadano: str | None = None) -> str | None:
    p = db.get(Postavka, kljuc)
    return p.vrijednost if p and p.vrijednost is not None else zadano


def set_postavka(db: Session, kljuc: str, vrijednost: str | None) -> None:
    p = db.get(Postavka, kljuc)
    if p is None:
        db.add(Postavka(kljuc=kljuc, vrijednost=vrijednost))
    else:
        p.vrijednost = vrijednost


def _statistika_po_kategoriji(db: Session) -> dict[str, list[int]]:
    """Prikupi trajanja (minute) po normaliziranoj kategoriji iz povijesti."""
    po_kat: dict[str, list[int]] = defaultdict(list)
    red = db.execute(
        select(PovijestRada.operacija, PovijestRada.minute).where(PovijestRada.minute.isnot(None))
    ).all()
    for operacija, minute in red:
        k = norm_kat(operacija)
        if not k or not minute or minute <= 0:
            continue
        # odbaci očite outliere (>24 h u jednom zapisu = greška unosa)
        if minute > 24 * 60:
            continue
        po_kat[k].append(int(minute))
    return po_kat


def izracunaj_norme(db: Session) -> int:
    """Preračunaj norme iz povijesti. Ne dira ručno postavljene (rucno=True).
    Vrati broj dodanih/ažuriranih kategorija."""
    po_kat = _statistika_po_kategoriji(db)
    postojeci = {n.kategorija: n for n in db.execute(select(NormaPosla)).scalars().all()}
    promijenjeno = 0
    for kat, ms in po_kat.items():
        if not ms:
            continue
        med = int(round(statistics.median(ms)))
        try:
            p60 = int(round(statistics.quantiles(ms, n=5)[2])) if len(ms) >= 5 else med  # ~60. percentil
        except statistics.StatisticsError:
            p60 = med
        n = postojeci.get(kat)
        if n is None:
            n = NormaPosla(kategorija=kat, norma_min=med, medijan_min=med, p60_min=p60,
                           broj_uzoraka=len(ms), rucno=False)
            db.add(n)
            promijenjeno += 1
        else:
            n.medijan_min = med
            n.p60_min = p60
            n.broj_uzoraka = len(ms)
            if not n.rucno:
                n.norma_min = med
            promijenjeno += 1
    db.commit()
    log.info("Norme: preračunato %d kategorija.", promijenjeno)
    return promijenjeno


def seed_norme(db: Session) -> None:
    """Jednokratno (po verziji) inicijaliziraj norme i zadane postavke."""
    zastavica = Path(settings.upload_dir).parent / _SEED_VERZIJA
    try:
        if zastavica.exists():
            return
    except OSError:
        pass
    # zadane postavke ako ne postoje
    if get_postavka(db, KLJUC_EUR) is None:
        set_postavka(db, KLJUC_EUR, "0")       # voditelj upisuje €/norma-sat
    if get_postavka(db, KLJUC_OSNOVICA) is None:
        set_postavka(db, KLJUC_OSNOVICA, "0")
    if get_postavka(db, KLJUC_SHADOW) is None:
        set_postavka(db, KLJUC_SHADOW, "1")    # kreni u shadow modu
    db.commit()
    izracunaj_norme(db)
    try:
        zastavica.parent.mkdir(parents=True, exist_ok=True)
        zastavica.write_text("done", encoding="utf-8")
    except OSError:
        pass
