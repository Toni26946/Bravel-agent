"""Samostalni rad — mehaničar (npr. vulkanizer) sam sebi otvara posao i sam se prijavljuje.

Pristup SAMO radniku kojem je dodijeljen modul '/samostalno' (Moduli po korisniku).
Vidi i dira ISKLJUČIVO svoje zadatke. Novi posao: GB + opis → ide u aktivni nalog tog
kamiona (ili novi nalog), pod operaciju „Gume" (ili zadanu), dodijeljen njemu, i mjerač
odmah kreće. Počni / Pauza / Gotovo rade bez WhatsApp poveznice (iznimka za ovaj modul).
"""
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth import trenutni_korisnik
from ..database import get_db
from ..models import Korisnik, Nalog, Operacija, PovijestStatusa, StatusNaloga, Uloga, Vozilo, Zadatak
from .nalozi import (
    SPOJIVI_STATUSI,
    _aware,
    _auto_status_naloga,
    _pokreni_mjerac,
    _sljedeci_broj,
    _zaustavi_mjerac,
)

router = APIRouter(prefix="/samostalno", tags=["samostalno"])

MODUL = "/samostalno"
ZADANA_KATEGORIJA = "Gume"


def ima_samostalno(k: Korisnik) -> bool:
    mod = k.moduli if isinstance(k.moduli, (list, tuple)) else []
    return k.uloga == Uloga.radnik and MODUL in mod


def _samo_samostalni(korisnik: Korisnik = Depends(trenutni_korisnik)) -> Korisnik:
    if not ima_samostalno(korisnik):
        raise HTTPException(status_code=403, detail="Nemate pristup samostalnom radu")
    return korisnik


def _digits(s) -> str:
    return re.sub(r"\D", "", str(s or ""))


def _sek(z: Zadatak) -> int:
    s = int(z.utroseno_sek or 0)
    if z.zapoceto:
        s += max(0, int((datetime.now(timezone.utc) - _aware(z.zapoceto)).total_seconds()))
    return s


def _zadatak_out(z: Zadatak) -> dict:
    n = z.operacija.nalog
    v = n.vozilo
    return {
        "id": z.id,
        "nalog_id": n.id,
        "gb": (v.gb if v else n.naslov) or "",
        "vozilo": " ".join(x for x in [(v.marka if v else None), (v.model if v else None)] if x),
        "reg": (v.registracija if v else "") or "",
        "kategorija": z.operacija.kategorija,
        "opis": z.opis or "",
        "radi": bool(z.zapoceto),
        "sek": _sek(z),
        "zavrseno": z.zavrseno.isoformat() if z.zavrseno else None,
    }


def _moj(db: Session, k: Korisnik, zid: int) -> Zadatak:
    z = db.get(Zadatak, zid)
    if not z or not any(r.id == k.id for r in z.radnici):
        raise HTTPException(status_code=404, detail="Zadatak nije tvoj ili ne postoji")
    return z


def _pauziraj_ostale(db: Session, k: Korisnik, osim_id: int | None = None) -> None:
    """Radi se jedno po jedno: ostali njegovi pokrenuti zadaci idu u pauzu (dodjela ostaje)."""
    for z in (
        db.query(Zadatak).join(Zadatak.radnici)
        .filter(Korisnik.id == k.id, Zadatak.gotovo.is_(False), Zadatak.zapoceto.isnot(None))
        .all()
    ):
        if z.id != osim_id:
            _zaustavi_mjerac(z)


def _je_vlasnik(k: Korisnik) -> bool:
    from ..config import settings
    ov = (settings.ai_poslovodja_user or "").strip().lower()
    return bool(ov) and (k.korisnicko_ime or "").strip().lower() == ov


@router.get("")
def stanje(kao: int | None = None, korisnik: Korisnik = Depends(trenutni_korisnik),
           db: Session = Depends(get_db)):
    """Moji otvoreni zadaci (u tijeku prvi) + što sam danas završio.
    Vlasnik smije ?kao=<id> — PREGLED tuđeg zaslona, samo za gledanje (akcije ostaju zaključane)."""
    if ima_samostalno(korisnik):
        k = korisnik
    elif kao and _je_vlasnik(korisnik):
        k = db.get(Korisnik, kao)
        if not k or not ima_samostalno(k):
            raise HTTPException(status_code=404, detail="Radnik nema samostalni rad")
    else:
        raise HTTPException(status_code=403, detail="Nemate pristup samostalnom radu")
    svi = db.query(Zadatak).join(Zadatak.radnici).filter(Korisnik.id == k.id).all()
    otvoreni = [z for z in svi if not z.gotovo and z.operacija.nalog.status != StatusNaloga.zatvoren]
    otvoreni.sort(key=lambda z: (0 if z.zapoceto else 1, -(z.id)))
    danas = datetime.now(timezone.utc).date()
    gotovi = [z for z in svi if z.gotovo and z.zavrseno and _aware(z.zavrseno).date() == danas]
    gotovi.sort(key=lambda z: _aware(z.zavrseno), reverse=True)
    return {
        "ime": k.ime,
        "pregled": k.id != korisnik.id,
        "kategorija": ZADANA_KATEGORIJA,
        "otvoreni": [_zadatak_out(z) for z in otvoreni],
        "danas": [_zadatak_out(z) for z in gotovi],
    }


class NoviPosao(BaseModel):
    gb: str
    opis: str
    kategorija: str | None = None


@router.post("/posao")
def novi_posao(p: NoviPosao, k: Korisnik = Depends(_samo_samostalni), db: Session = Depends(get_db)):
    opis = (p.opis or "").strip()
    if not opis:
        raise HTTPException(status_code=400, detail="Upiši što radiš")
    d = _digits(p.gb)
    if not d:
        raise HTTPException(status_code=400, detail="Upiši garažni broj")
    vozilo = next((v for v in db.query(Vozilo).all() if _digits(v.gb) == d), None)
    if not vozilo:
        raise HTTPException(status_code=404, detail=f"Kamion GB {p.gb} ne postoji")
    kat = (p.kategorija or "").strip() or ZADANA_KATEGORIJA

    nalog = (
        db.query(Nalog)
        .filter(Nalog.vozilo_id == vozilo.id, Nalog.status.in_(SPOJIVI_STATUSI))
        .order_by(Nalog.kreiran.desc())
        .first()
    )
    if not nalog:
        nalog = Nalog(broj=_sljedeci_broj(db), vozilo_id=vozilo.id, naslov=vozilo.gb, kreirao_id=k.id)
        db.add(nalog)
        db.flush()
        db.add(PovijestStatusa(nalog_id=nalog.id, stari_status=None, novi_status=nalog.status.value,
                               napomena=f"Otvorio {k.ime} (samostalni rad)", promijenio_id=k.id))
    # Dodaj kroz veze (append), da _auto_status_naloga odmah vidi novi zadatak.
    op = next((o for o in nalog.operacije if (o.kategorija or "").strip().lower() == kat.lower()), None)
    if not op:
        op = Operacija(kategorija=kat, redoslijed=len(nalog.operacije))
        nalog.operacije.append(op)
    z = Zadatak(opis=opis)
    z.radnici = [k]
    op.zadaci.append(z)
    db.flush()
    _pauziraj_ostale(db, k)
    _pokreni_mjerac(db, z, odjavi_druge=False)
    db.flush()
    _auto_status_naloga(db, nalog, k)
    db.commit()
    return {"ok": True, "zadatak_id": z.id}


@router.post("/{zid}/pocni")
def pocni(zid: int, k: Korisnik = Depends(_samo_samostalni), db: Session = Depends(get_db)):
    z = _moj(db, k, zid)
    if z.gotovo:
        raise HTTPException(status_code=400, detail="Zadatak je već gotov")
    _pauziraj_ostale(db, k, osim_id=z.id)
    z.ceka_potvrdu = False
    z.razlog_prekida = None
    z.prekid_vrijeme = None
    _pokreni_mjerac(db, z, odjavi_druge=False)
    db.flush()
    _auto_status_naloga(db, z.operacija.nalog, k)
    db.commit()
    return {"ok": True}


@router.post("/{zid}/pauza")
def pauza(zid: int, k: Korisnik = Depends(_samo_samostalni), db: Session = Depends(get_db)):
    z = _moj(db, k, zid)
    _zaustavi_mjerac(z)
    db.flush()
    _auto_status_naloga(db, z.operacija.nalog, k)
    db.commit()
    return {"ok": True}


@router.post("/{zid}/gotovo")
def gotovo(zid: int, k: Korisnik = Depends(_samo_samostalni), db: Session = Depends(get_db)):
    z = _moj(db, k, zid)
    _zaustavi_mjerac(z)
    z.ceka_potvrdu = False
    z.gotovo = True
    z.zavrseno = datetime.now(timezone.utc)
    z.razlog_prekida = None
    z.prekid_vrijeme = None
    db.flush()
    _auto_status_naloga(db, z.operacija.nalog, k)
    db.commit()
    return {"ok": True}
