"""SLOBODNI VOZAČI — disponenti prijavljuju koji su vozači slobodni, odnosno čiji je kamion na popravku.

WhatsApp prijava (Veljko, 19.11.2026., #328 → #331): „Treba napraviti da disponenti prijave koji
vozači su slobodni, odnosno čija vozila su na popravku, tako da imamo pregled koji su to vozači" —
i to u Radnim nalozima (tu rade radiona i disponenti). Ista funkcija kao u Flota OS-u.

Jedan zapis = jedan vozač koji trenutno ne vozi svoj kamion: razlog (kamion na popravku / slobodan /
ostalo), GB kamiona, od kada, do kada se očekuje, napomena i tko je prijavio. Vozilo se veže po
GARAŽNOM BROJU (nikad po registraciji); uz GB se prikaže vozilo iz registra i otvoreni radni nalog
(je li kamion stvarno u radioni). Kad vozač opet vozi, zapis se ZATVORI („Opet vozi") — ništa se ne
briše, zatvoreni ostaju u povijesti.

JEDAN POPIS ZA OBJE APLIKACIJE (WhatsApp #363/#364, 23.11.2026.): ovdje je prije bila vlastita tablica
pa su Radni nalozi pokazivali 3 vozača, a Flota OS 8. Sada je **Flota OS izvor istine** (kao imenik):
popis se čita i upisuje uživo preko Flotinih ruta `/api/slobodni-vozaci` zaglavljem X-Imenik-Kljuc
(isti fly secret IMENIK_KLJUC), a autor je u Floti „Radni nalozi · <ime>". Lokalna tablica
`slobodni_vozaci` se više ne puni — njeni aktivni zapisi se JEDNOM sami prenesu u Flotu (vozač kojeg
Flota već ima se samo zatvori) i zatvore uz oznaku „Preneseno u Flota OS".

Pristup: voditelj, poslovođa ili korisnik kojem je dodijeljen modul /slobodni-vozaci (disponenti).
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone

import httpx

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import imenik
from ..auth import trenutni_korisnik
from ..config import settings
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


def _iso(ts) -> str | None:
    """Flota šalje vrijeme kao epoch sekunde → ISO (UTC)."""
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat() if ts else None
    except (TypeError, ValueError):
        return None


def _out(db: Session, z: dict) -> dict:
    """Zapis iz Flote + vozilo iz NAŠEG registra i otvoreni radni nalog (po GB-u)."""
    gb = _norm_gb(z.get("gb"))
    return {
        "id": z.get("id"), "vozac": z.get("vozac"), "gb": gb, "razlog": z.get("razlog"),
        "od": z.get("od"), "do": z.get("do"),
        "napomena": z.get("napomena"), "aktivan": bool(z.get("aktivan")), "autor": z.get("autor"),
        "prijavljeno": _iso(z.get("prijavljeno")), "zatvoreno": _iso(z.get("zatvoreno")),
        "zatvorio": z.get("zatvorio"),
        "vozilo": _vozilo_info(db, gb),
    }


def _autor(k: Korisnik) -> str:
    return (k.ime or k.korisnicko_ime or "?")[:120]


# ---------- veza s Flotom OS (izvor istine) ----------
def _flota(metoda: str, putanja: str, json: dict | None = None, params: dict | None = None) -> dict:
    """Jedan poziv Flote servisnim ključem. Greške → HTTPException s porukom za korisnika."""
    if not settings.imenik_kljuc:
        raise HTTPException(status_code=503, detail="Slobodni vozači nisu povezani s Flota OS-om (nedostaje IMENIK_KLJUC).")
    base = settings.flota_api_base.rstrip("/")
    try:
        r = httpx.request(metoda, f"{base}/api/slobodni-vozaci{putanja}", json=json, params=params, timeout=20,
                          headers={"X-Imenik-Kljuc": settings.imenik_kljuc})
    except Exception as e:  # noqa: BLE001
        log.warning("Slobodni vozači: Flota OS ne odgovara (%s)", type(e).__name__)
        raise HTTPException(status_code=502, detail="Flota OS trenutno ne odgovara — pokušaj za minutu.")
    if r.status_code != 200:
        try:
            poruka = r.json().get("detail") or f"Flota OS HTTP {r.status_code}"
        except Exception:  # noqa: BLE001
            poruka = f"Flota OS HTTP {r.status_code}"
        if r.status_code == 400:
            raise HTTPException(status_code=409 if "već na popisu" in str(poruka) else 422, detail=str(poruka))
        log.warning("Slobodni vozači: Flota OS HTTP %s", r.status_code)
        raise HTTPException(status_code=502, detail="Flota OS trenutno ne odgovara — pokušaj za minutu.")
    return r.json()


def _prenesi_lokalne(db: Session, flota_aktivni: list[dict]) -> bool:
    """Jednokratni prijenos starih lokalnih prijava u Flotu. Vraća True ako je nešto preneseno."""
    lokalni = db.execute(select(SlobodanVozac).where(SlobodanVozac.aktivan.is_(True))).scalars().all()
    if not lokalni:
        return False
    u_floti = {imenik.kljuc_imena(z.get("vozac")) for z in flota_aktivni}
    preneseno = False
    for z in lokalni:
        if imenik.kljuc_imena(z.vozac) not in u_floti:
            try:
                _flota("POST", "", json={
                    "vozac": z.vozac, "gb": z.gb, "razlog": z.razlog,
                    "od": z.datum_od.isoformat() if z.datum_od else None,
                    "do": z.datum_do.isoformat() if z.datum_do else None,
                    "napomena": z.napomena, "korisnik": z.autor})
                preneseno = True
            except HTTPException as e:
                if e.status_code not in (409, 422):      # Flota nedostupna → probaj idući put
                    return preneseno
        z.aktivan = False
        z.zatvoreno = datetime.now(timezone.utc)
        z.zatvorio = "Preneseno u Flota OS"
        db.commit()
    return preneseno


@router.get("")
def popis(sve: bool = Query(default=False), db: Session = Depends(get_db)):
    """Trenutno slobodni vozači iz Flote OS (`sve=true` i zatvoreni, za povijest) + popis imena vozača
    (Flota OS imenik) i GB-ova kamiona iz registra za odabir."""
    d = _flota("GET", "", params={"sve": "true" if sve else "false"})
    if _prenesi_lokalne(db, [z for z in d.get("zapisi", []) if z.get("aktivan")]):
        d = _flota("GET", "", params={"sve": "true" if sve else "false"})
    try:
        imena = imenik.vozaci_imena()
    except Exception:  # imenik (Flota OS) nedostupan → upis ide i bez prijedloga
        log.warning("Imenik vozača nedostupan — popis imena prazan.")
        imena = []
    gbovi = [g for (g,) in db.execute(
        select(RegistarVozila.gb).where(func.upper(func.coalesce(RegistarVozila.kategorija, "")) == "KAMION"))]
    gbovi.sort(key=lambda g: (len(g), g))
    return {"zapisi": [_out(db, z) for z in d.get("zapisi", [])], "razlozi": list(RAZLOZI),
            "vozaci": imena, "gbovi": gbovi}


def _provjeri(d: SlobodanIn) -> dict:
    vozac = _t(d.vozac)
    if not vozac:
        raise HTTPException(status_code=422, detail="Upiši ime vozača.")
    razlog = (_t(d.razlog, 20) or "").upper()
    if razlog not in RAZLOZI:
        raise HTTPException(status_code=422, detail="Odaberi razlog (kamion na popravku / slobodan / ostalo).")
    od = d.od or date.today()
    if d.do and d.do < od:
        raise HTTPException(status_code=422, detail="Datum „do” ne smije biti prije datuma „od”.")
    return {"vozac": vozac, "gb": _norm_gb(d.gb), "razlog": razlog, "od": od.isoformat(),
            "do": d.do.isoformat() if d.do else None, "napomena": _t(d.napomena, 300)}


def _spremi(db: Session, polja: dict, k: Korisnik) -> dict:
    """Upis u Flotu, pa vrati svježi zapis (s vozilom iz registra)."""
    rid = _flota("POST", "", json={**polja, "korisnik": _autor(k)}).get("id")
    z = next((x for x in _flota("GET", "", params={"sve": "true"}).get("zapisi", []) if x.get("id") == rid), None)
    return _out(db, z) if z else {"id": rid, **polja}


@router.post("")
def dodaj(d: SlobodanIn, db: Session = Depends(get_db), k: Korisnik = Depends(_korisnik)):
    return _spremi(db, _provjeri(d), k)


@router.put("/{rid}")
def uredi(rid: int, d: SlobodanIn, db: Session = Depends(get_db), k: Korisnik = Depends(_korisnik)):
    return _spremi(db, {"id": rid, **_provjeri(d)}, k)


@router.post("/{rid}/zatvori")
def zatvori(rid: int, db: Session = Depends(get_db), k: Korisnik = Depends(_korisnik)):
    """Vozač opet vozi → zapis prelazi u povijest u Floti (ne briše se)."""
    try:
        _flota("POST", f"/{int(rid)}/zatvori", params={"korisnik_rn": _autor(k)})
    except HTTPException as e:
        if e.status_code in (409, 422):
            raise HTTPException(status_code=404, detail="Zapis ne postoji ili je već zatvoren.")
        raise
    z = next((x for x in _flota("GET", "", params={"sve": "true"}).get("zapisi", []) if x.get("id") == rid), None)
    return _out(db, z) if z else {"id": rid, "aktivan": False}
