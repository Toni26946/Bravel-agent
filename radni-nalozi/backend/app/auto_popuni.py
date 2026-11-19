"""Automatsko popunjavanje reda mehaničara (Plan → Radnici).

Čim nekom prisutnom mehaničaru ostane manje od `dispecer_zaliha` (2) zadataka u pripremi
(nezapočetih i ne odgođenih), sam mu se dodijeli sljedeća NEDODIJELJENA operacija iz plana:
- redom: HITNO → lista prioriteta (1, 2, 3…) → ostali po redoslijedu plana;
- kome: mehaničaru (od onih kojima treba posla) koji je najviše puta završio tu vrstu
  posla; ako nitko nije ili su izjednačeni → onaj s najmanje zadataka.

Preskaču se: operacije koje čekaju dijelove / vozilo nedostupno, nalozi koji čekaju
dijelove, vozila dalje od 200 m od radione (GPS), pregledi (rade ih pregledari),
odsutni mehaničari (godišnji, bolovanje, teren).

Prekidač: Postavka `plan_auto_popuni` ("0" = ugašeno; zadano upaljeno).
Zove se iz pozadinske petlje (svaku minutu) i odmah nakon mehaničareve akcije.
"""
import logging

from sqlalchemy import or_
from sqlalchemy.orm import Session

from . import flota, norme
from .config import settings
from .models import Korisnik, Nalog, StatusNaloga, Zadatak

log = logging.getLogger("auto_popuni")

KLJUC = "plan_auto_popuni"
KLJUC_RESET_RED = "plan_red_ruc_reset_v1"
BLIZU_M = 200
_ODGODJENO = ("dijelovi", "nedostupan")


def ukljuceno(db: Session) -> bool:
    return norme.get_postavka(db, KLJUC) != "0"


def _prio(n: Nalog) -> int:
    return n.prioritet_rang if n.prioritet_rang is not None else 10 ** 6


def _kljuc_kandidata(t) -> tuple:
    n, op, z = t
    return (
        0 if n.plan_hitno else 1,
        _prio(n),
        n.plan_rang if n.plan_rang is not None else 10 ** 6,
        op.redoslijed or 0,
        z.id,
    )


def popuni(db: Session) -> list[dict]:
    """Dopuni redove mehaničarima kojima fali posla. Vraća popis dodjela (i commita)."""
    if not ukljuceno(db):
        return []
    from .routers.nalozi import nalog_eager
    from .routers.plan import (
        _AKTIVNI, _PREGLED_KAT, _SERVISERI, _SKRIVENI_GB, _gb, _iskustvo_po_kategoriji,
        _je_odsutan, _log, _norm_kat, _set_radnici,
    )

    meh = [
        m for m in db.query(Korisnik)
        .filter(or_(Korisnik.uloga.in_(_SERVISERI), Korisnik.radi_na_nalozima.is_(True)),
                Korisnik.aktivan.is_(True),
                Korisnik.prijavljuje_se.is_(True))
        .all()
        if not _je_odsutan(m)
    ]
    if not meh:
        return []
    po_id = {m.id: m for m in meh}
    ceka = {m.id: 0 for m in meh}      # u pripremi (nezapočeto, nije odgođeno)
    ukupno = {m.id: 0 for m in meh}    # svi njegovi nezavršeni
    kandidati = []
    nalozi = db.query(Nalog).options(*nalog_eager()).filter(Nalog.status.in_(_AKTIVNI)).all()
    for n in nalozi:
        if _gb(n) in _SKRIVENI_GB:
            continue
        u_planu = bool(n.plan_hitno) or n.plan_rang is not None or n.prioritet_rang is not None
        for op in n.operacije:
            for z in op.zadaci:
                if z.gotovo:
                    continue
                if z.radnici:
                    for r in z.radnici:
                        if r.id not in ceka:
                            continue
                        zr = next((v for v in z.vremena if v.radnik_id == r.id), None)
                        if zr is not None and zr.gotovo:
                            continue   # svoj dio završio, čeka drugoga
                        ukupno[r.id] += 1
                        if not z.zapoceto and z.razlog_prekida not in _ODGODJENO:
                            ceka[r.id] += 1
                    continue
                if not u_planu or n.status == StatusNaloga.ceka_dijelove:
                    continue
                if z.razlog_prekida in _ODGODJENO:
                    continue
                if (op.kategorija or "").strip().upper() in _PREGLED_KAT:
                    continue   # preglede radi pregledar (popis), ne red mehaničara
                kandidati.append((n, op, z))

    prag = max(1, settings.dispecer_zaliha or 2)
    trebaju = {rid for rid, c in ceka.items() if c < prag}
    if not trebaju or not kandidati:
        return []
    kandidati.sort(key=_kljuc_kandidata)
    iskustvo = _iskustvo_po_kategoriji(db, list(trebaju))
    udaljenost: dict[str, float | None] = {}
    out = []
    for n, op, z in kandidati:
        if not trebaju:
            break
        gb = _gb(n)
        if gb not in udaljenost:
            try:
                udaljenost[gb] = flota.udaljenost_od_radione(gb)
            except Exception:  # noqa: BLE001 — bez GPS-a = smatra se blizu
                udaljenost[gb] = None
        if udaljenost[gb] is not None and udaljenost[gb] > BLIZU_M:
            continue   # vozilo nije u radioni
        isk = iskustvo.get(_norm_kat(op.kategorija), {})
        rid = min(trebaju, key=lambda r: (-isk.get(r, 0), ceka[r], ukupno[r], po_id[r].ime or ""))
        try:
            _set_radnici(db, z, [rid])
        except Exception as e:  # noqa: BLE001 — jedan loš ne smije srušiti ostale
            log.warning("Auto-popuni: ne mogu dodijeliti zadatak %s radniku %s: %s", z.id, rid, e)
            trebaju.discard(rid)
            continue
        z.ceka_potvrdu = False
        ceka[rid] += 1
        ukupno[rid] += 1
        if ceka[rid] >= prag:
            trebaju.discard(rid)
        ime = po_id[rid].ime
        _log(db, None, "auto-dodjela", f"GB {gb}: {z.opis or op.kategorija or ''} → {ime} (automatski)"[:250],
             nalog_id=n.id, zadatak_id=z.id, radnik_id=rid)
        out.append({"zadatak_id": z.id, "gb": gb, "radnik_id": rid, "radnik": ime})
    if out:
        db.commit()
        log.info("Auto-popuni: %s dodjela (%s)", len(out),
                 ", ".join(f"GB {d['gb']}→{d['radnik']}" for d in out))
    return out


def popuni_tiho(db: Session) -> None:
    """Kao popuni(), ali greška ne smije srušiti mehaničarevu akciju."""
    try:
        popuni(db)
    except Exception as e:  # noqa: BLE001
        db.rollback()
        log.warning("Auto-popuni iznimka: %s", e)


def jednokratno_ocisti_rucni_red(db: Session) -> None:
    """Jednokratno (19.11.2026.): red mehaničara od sada ide po prioritetima, pa se
    stari ručni redoslijed (red_ruc) briše s nezavršenih zadataka. Novi ručni pomaci
    (strelice / povlačenje u Radnicima) poslije toga opet imaju prednost."""
    if norme.get_postavka(db, KLJUC_RESET_RED) == "1":
        return
    broj = (db.query(Zadatak)
            .filter(Zadatak.gotovo.is_(False), Zadatak.red_ruc.isnot(None))
            .update({Zadatak.red_ruc: None}, synchronize_session=False))
    norme.set_postavka(db, KLJUC_RESET_RED, "1")
    db.commit()
    log.info("Ručni red mehaničara očišćen (%s zadataka) — red ide po prioritetima.", broj)
