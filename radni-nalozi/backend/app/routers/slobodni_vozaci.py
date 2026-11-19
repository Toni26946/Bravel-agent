"""SLOBODNI VOZAČI — disponenti prijavljuju koji su vozači slobodni, odnosno čiji je kamion na popravku.

WhatsApp prijava (Veljko, 19.11.2026., #328 → #331): „Treba napraviti da disponenti prijave koji
vozači su slobodni, odnosno čija vozila su na popravku, tako da imamo pregled koji su to vozači" —
i to u Radnim nalozima (tu rade radiona i disponenti). Ista funkcija kao u Flota OS-u.

Jedan zapis = jedan vozač koji trenutno ne vozi svoj kamion: razlog (kamion na popravku / slobodan /
ostalo), GB kamiona, od kada, do kada se očekuje, napomena i tko je prijavio. Vozilo se veže po
GARAŽNOM BROJU (nikad po registraciji); uz GB se prikaže vozilo iz registra i otvoreni radni nalog
(je li kamion stvarno u radioni). Kad vozač opet vozi, zapis se ZATVORI („Opet vozi") — ništa se ne
briše, zatvoreni ostaju u povijesti.

Pristup: voditelj, poslovođa ili korisnik kojem je dodijeljen modul /slobodni-vozaci (disponenti).
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import imenik
from ..auth import trenutni_korisnik
from ..database import get_db
from ..models import Korisnik, Nalog, RegistarVozila, SlobodanVozac, StatusNaloga, Uloga, Vozilo

log = logging.getLogger("slobodni_vozaci")

MODUL = "/slobodni-vozaci"
RAZLOZI = ("POPRAVAK", "SLOBODAN", "OSTALO")   # POPRAVAK = kamion na popravku, SLOBODAN = bez posla/kamiona
_AKTIVNI_NALOZI = (StatusNaloga.otvoren, StatusNaloga.u_radu, StatusNaloga.ceka_dijelove)


def ima_pristup(k: Korisnik) -> bool:
    """Voditelj/poslovođa ili korisnik kojem je dodijeljen modul /slobodni-vozaci."""
    mod = k.moduli if isinstance(k.moduli, (list, tuple)) else []
    return k.uloga in (Uloga.voditelj, Uloga.poslovodja) or MODUL in mod


def _korisnik(k: Korisnik = Depends(trenutni_korisnik)) -> Korisnik:
    if not ima_pristup(k):
        raise HTTPException(status_code=403, detail="Nemaš pristup Slobodnim vozačima.")
    return k


router = APIRouter(prefix="/slobodni-vozaci", tags=["slobodni-vozaci"], dependencies=[Depends(_korisnik)])


class SlobodanIn(BaseModel):
    vozac: str
    gb: str | None = None
    razlog: str
    od: date | None = None
    do: date | None = None
    napomena: str | None = None


def _t(v, n: int = 120) -> str | None:
    v = " ".join(str(v or "").split())[:n]
    return v or None


def _norm_gb(gb) -> str | None:
    """GB bez razmaka; vodeće nule se ne čuvaju („083" = „83")."""
    s = "".join(str(gb or "").split()).upper()
    if not s:
        return None
    return s.lstrip("0") or s


def _vozilo_info(db: Session, gb: str | None) -> dict | None:
    """Vozilo iz registra (po GB-u) + otvoreni radni nalog ako je kamion u radioni."""
    if not gb:
        return None
    r = db.get(RegistarVozila, gb)
    info = {"vozilo": (r.vozilo or r.tip) if r else None, "vrsta": r.vrsta if r else None,
            "u_registru": r is not None, "nalog": None}
    v = db.execute(select(Vozilo).where(Vozilo.gb == gb)).scalars().first()
    if v:
        n = db.execute(select(Nalog).where(Nalog.vozilo_id == v.id, Nalog.status.in_(_AKTIVNI_NALOZI))
                       .order_by(Nalog.id.desc())).scalars().first()
        if n:
            info["nalog"] = {"id": n.id, "broj": n.broj, "status": n.status.value}
    return info


def _out(db: Session, z: SlobodanVozac) -> dict:
    return {
        "id": z.id, "vozac": z.vozac, "gb": z.gb, "razlog": z.razlog,
        "od": z.datum_od.isoformat() if z.datum_od else None,
        "do": z.datum_do.isoformat() if z.datum_do else None,
        "napomena": z.napomena, "aktivan": bool(z.aktivan), "autor": z.autor,
        "prijavljeno": z.prijavljeno.isoformat() if z.prijavljeno else None,
        "zatvoreno": z.zatvoreno.isoformat() if z.zatvoreno else None,
        "zatvorio": z.zatvorio,
        "vozilo": _vozilo_info(db, z.gb),
    }


def _autor(k: Korisnik) -> str:
    return (k.ime or k.korisnicko_ime or "?")[:120]


@router.get("")
def popis(sve: bool = Query(default=False), db: Session = Depends(get_db)):
    """Trenutno slobodni vozači (`sve=true` i zatvoreni, za povijest) + popis imena vozača
    (Flota OS imenik) i GB-ova kamiona iz registra za odabir."""
    q = select(SlobodanVozac)
    if not sve:
        q = q.where(SlobodanVozac.aktivan.is_(True))
    zapisi = db.execute(q).scalars().all()
    red = {r: i for i, r in enumerate(RAZLOZI)}
    _min = datetime.min.replace(tzinfo=timezone.utc)

    def _kljuc(z: SlobodanVozac):
        if z.aktivan:
            return (0, red.get(z.razlog, 9), (z.vozac or "").lower(), 0.0)
        zt = z.zatvoreno or _min
        zt = zt if zt.tzinfo else zt.replace(tzinfo=timezone.utc)
        return (1, 0, "", -zt.timestamp())

    zapisi = sorted(zapisi, key=_kljuc)
    try:
        imena = imenik.vozaci_imena()
    except Exception:  # imenik (Flota OS) nedostupan → upis ide i bez prijedloga
        log.warning("Imenik vozača nedostupan — popis imena prazan.")
        imena = []
    gbovi = [g for (g,) in db.execute(
        select(RegistarVozila.gb).where(func.upper(func.coalesce(RegistarVozila.kategorija, "")) == "KAMION"))]
    gbovi.sort(key=lambda g: (len(g), g))
    return {"zapisi": [_out(db, z) for z in zapisi], "razlozi": list(RAZLOZI), "vozaci": imena, "gbovi": gbovi}


def _provjeri(db: Session, d: SlobodanIn, rid: int | None) -> dict:
    vozac = _t(d.vozac)
    if not vozac:
        raise HTTPException(status_code=422, detail="Upiši ime vozača.")
    razlog = (_t(d.razlog, 20) or "").upper()
    if razlog not in RAZLOZI:
        raise HTTPException(status_code=422, detail="Odaberi razlog (kamion na popravku / slobodan / ostalo).")
    od = d.od or date.today()
    if d.do and d.do < od:
        raise HTTPException(status_code=422, detail="Datum „do” ne smije biti prije datuma „od”.")
    # Isti vozač ne smije imati dvije aktivne prijave — bolje urediti postojeću.
    q = select(SlobodanVozac).where(SlobodanVozac.aktivan.is_(True),
                                    func.lower(SlobodanVozac.vozac) == vozac.lower())
    if rid:
        q = q.where(SlobodanVozac.id != rid)
    if db.execute(q).scalars().first():
        raise HTTPException(status_code=409, detail=f"{vozac} je već na popisu slobodnih — uredi postojeći zapis.")
    return {"vozac": vozac, "gb": _norm_gb(d.gb), "razlog": razlog, "datum_od": od, "datum_do": d.do,
            "napomena": _t(d.napomena, 300)}


@router.post("")
def dodaj(d: SlobodanIn, db: Session = Depends(get_db), k: Korisnik = Depends(_korisnik)):
    polja = _provjeri(db, d, None)
    z = SlobodanVozac(**polja, aktivan=True, autor=_autor(k))
    db.add(z)
    db.commit()
    db.refresh(z)
    return _out(db, z)


@router.put("/{rid}")
def uredi(rid: int, d: SlobodanIn, db: Session = Depends(get_db), k: Korisnik = Depends(_korisnik)):
    z = db.get(SlobodanVozac, rid)
    if not z:
        raise HTTPException(status_code=404, detail="Zapis ne postoji.")
    for kljuc, v in _provjeri(db, d, rid).items():
        setattr(z, kljuc, v)
    z.autor = _autor(k)
    db.commit()
    db.refresh(z)
    return _out(db, z)


@router.post("/{rid}/zatvori")
def zatvori(rid: int, db: Session = Depends(get_db), k: Korisnik = Depends(_korisnik)):
    """Vozač opet vozi → zapis prelazi u povijest (ne briše se)."""
    z = db.get(SlobodanVozac, rid)
    if not z or not z.aktivan:
        raise HTTPException(status_code=404, detail="Zapis ne postoji ili je već zatvoren.")
    z.aktivan = False
    z.zatvoreno = datetime.now(timezone.utc)
    z.zatvorio = _autor(k)
    db.commit()
    db.refresh(z)
    return _out(db, z)
