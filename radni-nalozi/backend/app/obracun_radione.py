"""Živo povezivanje s obračunom radione (bravel-obracun.surge.sh).

Aplikacija obračuna radione u sebi nosi mjesečne podatke kao `const DATA_NN=[...]`
(NN = mjesec), gdje svaki radnik ima `ime` i `zarada`. Ovdje te podatke dohvaćamo,
parsiramo i spajamo s poviješću rada (klikane operacije → norma-sati) da bismo
izračunali revenue-neutral €/norma-sat za SERVISERE NA PODU.

Namjerno NE spremamo pojedinačne plaće — samo izvedenu stopu i meta podatke o
sinkronizaciji. Poslovođe na fiksnoj osnovici (malo norma-sati) se izostavljaju
iz kalibracije jer ih model po učinku ne dira.
"""
from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from datetime import date, datetime

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .models import NormaPosla, PovijestRada
from .norme import (
    KLJUC_EUR,
    _STARE_AUTO_EUR,
    get_postavka,
    norm_kat,
    set_postavka,
)

log = logging.getLogger("obracun")

# Meta ključevi (tablica postavke)
KLJUC_SYNC = "obracun_zadnji_sync"       # ISO datum zadnje uspješne sinkronizacije
KLJUC_STOPA = "obracun_zadnja_stopa"     # izračunata €/norma-sat (string)
KLJUC_MJESECI = "obracun_mjeseci"        # npr. "2026-07,2026-08"
KLJUC_POKLOP = "obracun_poklopljeno"     # broj poklopljenih servisera (floor)

# Kalibracija se primjenjuje samo ako je rezultat razuman i dovoljno potkrijepljen.
_MIN_NORMA_H = 60        # radnik "na podu" = barem toliko norma-sati u mjesecu
_MIN_RADNIKA = 8         # minimalno poklopljenih radnika da stopa bude vjerodostojna
_STOPA_MIN = 6.0         # sanity band za €/norma-sat
_STOPA_MAX = 30.0


def _ime_set(ime: str | None) -> frozenset[str]:
    return frozenset((ime or "").upper().replace(".", " ").split())


def dohvati_html(url: str | None = None, timeout: float = 20.0) -> str | None:
    url = url or settings.obracun_url
    if not url:
        return None
    try:
        r = httpx.get(url, timeout=timeout, follow_redirects=True)
        r.raise_for_status()
        return r.text
    except Exception as e:  # mreža/blokada/404 — nikad ne ruši poziv
        log.warning("Obračun: dohvat nije uspio (%s): %s", url, e)
        return None


def _godina_iz_html(html: str) -> int:
    m = re.search(r"Obra[čc]un[^<]{0,40}?(20\d\d)", html)
    if m:
        return int(m.group(1))
    m = re.search(r"\b(20\d\d)\b", html)
    return int(m.group(1)) if m else date.today().year


def parsiraj_mjesece(html: str) -> dict[str, list[dict]]:
    """Vrati {'YYYY-MM': [ {ime, zarada}, ... ]} iz svih DATA_NN blokova."""
    godina = _godina_iz_html(html)
    out: dict[str, list[dict]] = {}
    for m in re.finditer(r"const\s+DATA_(\d{2})\s*=\s*(\[.*?\])\s*;", html, re.S):
        mj = int(m.group(1))
        try:
            arr = json.loads(m.group(2))
        except json.JSONDecodeError:
            continue
        redovi = []
        for x in arr:
            if not isinstance(x, dict):
                continue
            ime = (x.get("ime") or "").strip()
            zar = x.get("zarada")
            if ime and isinstance(zar, (int, float)) and zar > 0:
                redovi.append({"ime": ime, "zarada": float(zar)})
        if redovi:
            out[f"{godina:04d}-{mj:02d}"] = redovi
    return out


def _norma_po_radniku(db: Session, mjesec: str) -> dict[frozenset, float]:
    """Norma-sati po radniku za dani mjesec (YYYY-MM) iz povijesti rada + živih normi."""
    norme = {n.kategorija: n.norma_min for n in db.execute(select(NormaPosla)).scalars().all()}
    try:
        g, mm = mjesec.split("-")
        od = date(int(g), int(mm), 1)
        do = date(int(g) + (1 if mm == "12" else 0), 1 if mm == "12" else int(mm) + 1, 1)
    except ValueError:
        return {}
    red = db.execute(
        select(PovijestRada.radnik, PovijestRada.operacija)
        .where(PovijestRada.datum >= od, PovijestRada.datum < do)
    ).all()
    per_min: dict[frozenset, int] = defaultdict(int)
    for radnik, operacija in red:
        v = norme.get(norm_kat(operacija))
        if v:
            per_min[_ime_set(radnik)] += v
    return {k: v / 60.0 for k, v in per_min.items()}


def izracunaj_stopu(db: Session, mjeseci: dict[str, list[dict]]) -> dict:
    """Revenue-neutral €/norma-sat za servisere na podu, združeno po mjesecima."""
    uk_zar = 0.0
    uk_h = 0.0
    poklop = 0
    koristeni_mj: list[str] = []
    for mjesec, redovi in sorted(mjeseci.items()):
        nph = _norma_po_radniku(db, mjesec)
        if not nph:
            continue
        mj_poklop = 0
        for x in redovi:
            k = _ime_set(x["ime"])
            h = nph.get(k)
            if h is None:
                # fuzzy: preklapanje ≥2 tokena (različit poredak/format imena)
                for kk, vv in nph.items():
                    if len(k & kk) >= 2:
                        h = vv
                        break
            if h is not None and h >= _MIN_NORMA_H:
                uk_zar += x["zarada"]
                uk_h += h
                mj_poklop += 1
        if mj_poklop:
            poklop += mj_poklop
            koristeni_mj.append(mjesec)
    stopa = round(uk_zar / uk_h, 2) if uk_h > 0 else 0.0
    return {
        "stopa": stopa,
        "poklopljeno": poklop,
        "mjeseci": koristeni_mj,
        "norma_sati": round(uk_h, 1),
    }


def sinkroniziraj(db: Session, primijeni: bool = True) -> dict:
    """Dohvati obračun, izračunaj stopu i (opcionalno) primijeni je na €/norma-sat.

    Vrati sažetak. `primijeni` mijenja €/norma-sat samo ako je trenutna vrijednost
    automatska (nije ju voditelj ručno postavio) i ako je rezultat u razumnom
    rasponu uz dovoljno poklopljenih radnika."""
    html = dohvati_html()
    if not html:
        return {"ok": False, "razlog": "nedostupno", "stopa": 0.0, "poklopljeno": 0, "mjeseci": []}
    mjeseci = parsiraj_mjesece(html)
    if not mjeseci:
        return {"ok": False, "razlog": "nema_podataka", "stopa": 0.0, "poklopljeno": 0, "mjeseci": []}
    rez = izracunaj_stopu(db, mjeseci)
    primijenjeno = False
    valjana = (
        _STOPA_MIN <= rez["stopa"] <= _STOPA_MAX and rez["poklopljeno"] >= _MIN_RADNIKA
    )
    if valjana:
        set_postavka(db, KLJUC_SYNC, date.today().isoformat())
        set_postavka(db, KLJUC_STOPA, str(rez["stopa"]))
        set_postavka(db, KLJUC_MJESECI, ",".join(rez["mjeseci"]))
        set_postavka(db, KLJUC_POKLOP, str(rez["poklopljeno"]))
        if primijeni:
            trenutno = get_postavka(db, KLJUC_EUR)
            if trenutno in _STARE_AUTO_EUR or _je_auto(db, trenutno):
                set_postavka(db, KLJUC_EUR, str(rez["stopa"]))
                primijenjeno = True
        db.commit()
        log.info("Obračun: stopa=%.2f €, radnika=%d, mjeseci=%s, primijenjeno=%s",
                 rez["stopa"], rez["poklopljeno"], rez["mjeseci"], primijenjeno)
    else:
        log.info("Obračun: stopa %.2f (radnika %d) izvan uvjeta — ne primjenjujem.",
                 rez["stopa"], rez["poklopljeno"])
    return {
        "ok": True,
        "valjana": valjana,
        "primijenjeno": primijenjeno,
        **rez,
    }


def _je_auto(db: Session, trenutno: str | None) -> bool:
    """Je li trenutna €/norma-sat jednaka zadnjoj auto-sinkroniziranoj (dakle nije ručna)."""
    zadnja = get_postavka(db, KLJUC_STOPA)
    return bool(zadnja) and trenutno == zadnja


def auto_sync_pri_pokretanju(db: Session) -> None:
    """Pokušaj sinkronizacije pri startu ako nije rađena ≥25 dana. Nikad ne ruši start."""
    try:
        zadnji = get_postavka(db, KLJUC_SYNC)
        treba = True
        if zadnji:
            try:
                treba = (date.today() - date.fromisoformat(zadnji)).days >= 25
            except ValueError:
                treba = True
        if treba:
            sinkroniziraj(db, primijeni=True)
    except Exception as e:
        log.warning("Obračun: auto-sync preskočen (%s)", e)


def info(db: Session) -> dict:
    """Meta o zadnjoj sinkronizaciji (bez pojedinačnih plaća)."""
    return {
        "url": settings.obracun_url,
        "zadnji_sync": get_postavka(db, KLJUC_SYNC),
        "stopa": get_postavka(db, KLJUC_STOPA),
        "mjeseci": (get_postavka(db, KLJUC_MJESECI) or "").split(",") if get_postavka(db, KLJUC_MJESECI) else [],
        "poklopljeno": int(get_postavka(db, KLJUC_POKLOP) or 0),
    }
