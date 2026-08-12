"""Šteta — evidencija oštećenja koja su napravili vozači + AI procjena troška."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..ai import ai_dostupan, parsiraj_stetu_govor, procijeni_stetu
from ..auth import zahtijevaj_uloge
from ..database import get_db
from ..models import Korisnik, Steta, Uloga, Vozilo
from ..schemas import (
    StetaCreate,
    StetaGlasovniOdgovor,
    StetaGlasovniZahtjev,
    StetaOut,
    StetaProcjenaOdgovor,
    StetaProcjenaZahtjev,
    StetaStavka,
    StetaUpdate,
)

router = APIRouter(prefix="/stete", tags=["stete"])

samo_voditelj = zahtijevaj_uloge(Uloga.voditelj)


def _opis_vozila(v: Vozilo | None) -> str | None:
    if not v:
        return None
    return " · ".join(x for x in [v.gb, v.marka, v.model] if x) or None


def _provjeri_veze(db: Session, vozilo_id: int | None, vozac_id: int | None) -> None:
    if vozilo_id is not None and not db.get(Vozilo, vozilo_id):
        raise HTTPException(status_code=400, detail="Vozilo ne postoji")
    if vozac_id is not None:
        v = db.get(Korisnik, vozac_id)
        if not v or v.uloga != Uloga.vozac:
            raise HTTPException(status_code=400, detail="Odabrani vozač nije valjan")


# --- AI glasovni unos --------------------------------------------------------
@router.post("/glasovni-parse", response_model=StetaGlasovniOdgovor)
def glasovni_parse(z: StetaGlasovniZahtjev, _: Korisnik = Depends(samo_voditelj)):
    if not ai_dostupan():
        raise HTTPException(status_code=503, detail="Glasovni unos nije konfiguriran (nedostaje ANTHROPIC_API_KEY).")
    if not z.tekst.strip():
        raise HTTPException(status_code=400, detail="Nema izgovorenog teksta.")
    try:
        podaci = parsiraj_stetu_govor(z.tekst, z.vozaci)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"AI nije uspio obraditi govor: {e}")
    return StetaGlasovniOdgovor(
        vozilo_gb=podaci.get("vozilo_gb") or None,
        vozac=podaci.get("vozac") or None,
        opis=(podaci.get("opis") or "").strip(),
    )


# --- AI procjena -------------------------------------------------------------
@router.post("/procjena", response_model=StetaProcjenaOdgovor)
def procjena(
    z: StetaProcjenaZahtjev, _: Korisnik = Depends(samo_voditelj), db: Session = Depends(get_db)
):
    if not ai_dostupan():
        raise HTTPException(status_code=503, detail="AI procjena nije konfigurirana (nedostaje ANTHROPIC_API_KEY).")
    if not z.opis.strip():
        raise HTTPException(status_code=400, detail="Opišite što je oštećeno.")
    vozilo_opis = _opis_vozila(db.get(Vozilo, z.vozilo_id)) if z.vozilo_id else None
    try:
        podaci = procijeni_stetu(z.opis, vozilo_opis)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"AI nije uspio procijeniti štetu: {e}")
    stavke = [
        StetaStavka(naziv=(s.get("naziv") or "").strip(), cijena=float(s.get("cijena") or 0))
        for s in (podaci.get("stavke") or [])
        if (s.get("naziv") or "").strip()
    ]
    try:
        iznos = float(podaci.get("procjena"))
    except (TypeError, ValueError):
        iznos = sum(s.cijena for s in stavke)
    return StetaProcjenaOdgovor(
        procjena=round(iznos, 2),
        stavke=stavke,
        obrazlozenje=(podaci.get("obrazlozenje") or None),
    )


# --- CRUD --------------------------------------------------------------------
@router.get("", response_model=list[StetaOut])
def popis(_: Korisnik = Depends(samo_voditelj), db: Session = Depends(get_db)):
    return db.query(Steta).order_by(Steta.kreiran.desc()).all()


@router.post("", response_model=StetaOut, status_code=201)
def kreiraj(podaci: StetaCreate, voditelj: Korisnik = Depends(samo_voditelj), db: Session = Depends(get_db)):
    if not podaci.opis.strip():
        raise HTTPException(status_code=400, detail="Opišite što je oštećeno.")
    _provjeri_veze(db, podaci.vozilo_id, podaci.vozac_id)
    s = Steta(
        vozilo_id=podaci.vozilo_id,
        vozac_id=podaci.vozac_id,
        opis=podaci.opis.strip(),
        procjena=podaci.procjena or 0,
        obrazlozenje=podaci.obrazlozenje,
        stavke=[x.model_dump() for x in podaci.stavke],
        kreirao_id=voditelj.id,
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


@router.patch("/{steta_id}", response_model=StetaOut)
def azuriraj(steta_id: int, podaci: StetaUpdate, _: Korisnik = Depends(samo_voditelj), db: Session = Depends(get_db)):
    s = db.get(Steta, steta_id)
    if not s:
        raise HTTPException(status_code=404, detail="Šteta ne postoji")
    izmjene = podaci.model_dump(exclude_unset=True)
    if "vozilo_id" in izmjene or "vozac_id" in izmjene:
        _provjeri_veze(db, izmjene.get("vozilo_id", s.vozilo_id), izmjene.get("vozac_id", s.vozac_id))
    for polje, vrijednost in izmjene.items():
        setattr(s, polje, vrijednost)
    db.commit()
    db.refresh(s)
    return s


@router.delete("/{steta_id}", status_code=204)
def obrisi(steta_id: int, _: Korisnik = Depends(samo_voditelj), db: Session = Depends(get_db)):
    s = db.get(Steta, steta_id)
    if not s:
        raise HTTPException(status_code=404, detail="Šteta ne postoji")
    db.delete(s)
    db.commit()
