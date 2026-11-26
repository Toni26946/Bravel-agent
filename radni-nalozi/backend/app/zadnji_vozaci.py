"""Zadnji vozač uz garažni broj — zajednička logika za sve ekrane (Veljko 26.11.2026., #433, #436).

Kamion (i sve što nije priključno): zadnji vozač iz Flota OS-a (keš u `flota`, bez
čekanja mreže; nepoznat GB ide u red pozadinske petlje), rezerva je ime iz registra.
Priključno vozilo: vozač sa ZADNJEG prikapčanja u dnevniku (ili zadnji vozač kamiona
na koji je bilo prikačeno, ako ime nije upisano)."""
from sqlalchemy.orm import Session

from . import flota
from .models import DnevnikPrikapcanja, RegistarVozila, VrstaDogadaja, je_prikljucno_vozilo


def _kljuc(gb: str) -> str:
    return gb.lstrip("0") or gb


def za_gbove(db: Session, gbovi, reg_map: dict | None = None) -> dict:
    """{gb: ime zadnjeg vozača} za zadane GB-ove (GB bez vozača se izostavlja)."""
    gbovi = [str(g).strip() for g in dict.fromkeys(gbovi or []) if g and str(g).strip()]
    if not gbovi:
        return {}
    if reg_map is None:
        reg_map = {}
        trazeni = set(gbovi) | {_kljuc(g) for g in gbovi}
        for rv in db.query(RegistarVozila).filter(RegistarVozila.gb.in_(trazeni)).all():
            reg_map[rv.gb] = rv
            reg_map.setdefault(_kljuc(rv.gb), rv)
    out: dict = {}
    prikljucna: list = []
    for gb in gbovi:
        rv = reg_map.get(gb) or reg_map.get(_kljuc(gb))
        if rv is not None and je_prikljucno_vozilo(rv.kategorija):
            prikljucna.append(gb)
            continue
        ime = flota.zadnji_vozac(gb)
        if not ime and rv is not None:
            ime = (rv.vozac or "").strip() or None   # rezerva: ime iz registra (sync s Flotom)
        if ime:
            out[gb] = ime
    if prikljucna:
        trazeni = set(prikljucna) | {_kljuc(g) for g in prikljucna}
        zadnji: dict = {}
        for e in (db.query(DnevnikPrikapcanja)
                  .filter(DnevnikPrikapcanja.prikolica_gb.in_(trazeni),
                          DnevnikPrikapcanja.vrsta == VrstaDogadaja.prikaceno)
                  .order_by(DnevnikPrikapcanja.vrijeme.desc(), DnevnikPrikapcanja.id.desc()).all()):
            zadnji.setdefault(_kljuc(e.prikolica_gb), e)
        for gb in prikljucna:
            e = zadnji.get(_kljuc(gb))
            if e is None:
                continue
            ime = (e.vozac or "").strip() or (flota.zadnji_vozac(e.kamion_gb) if e.kamion_gb else None)
            if ime:
                out[gb] = ime
    return out


def svi(db: Session) -> dict:
    """{gb: ime} za sva vozila iz registra (za prikaz na svim ekranima)."""
    redovi = db.query(RegistarVozila).all()
    reg_map: dict = {}
    for rv in redovi:
        reg_map[rv.gb] = rv
        reg_map.setdefault(_kljuc(rv.gb), rv)
    return za_gbove(db, [rv.gb for rv in redovi], reg_map)
