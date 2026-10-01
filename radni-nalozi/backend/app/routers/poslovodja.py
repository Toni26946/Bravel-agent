"""AI Poslovođa — Faza 1: norme (cijene posla), postavke i shadow učinak.

Norme se računaju iz povijesti rada; voditelj ih korigira. Učinak (shadow)
pokazuje što bi tko zaradio po novom modelu, bez diranja stvarne plaće.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import zahtijevaj_uloge
from ..database import get_db
from ..models import Korisnik, NormaPosla, PovijestRada, Uloga
from ..norme import (
    KLJUC_EUR,
    KLJUC_OSNOVICA,
    KLJUC_SHADOW,
    get_postavka,
    izracunaj_norme,
    norm_kat,
    set_postavka,
)
from ..schemas import (
    NormaOut,
    NormaUpdate,
    PostavkeOut,
    PostavkeUpdate,
    UcinakOut,
    UcinakRedak,
)

router = APIRouter(prefix="/poslovodja", tags=["poslovodja"])

voditelj_ili_poslovodja = zahtijevaj_uloge(Uloga.voditelj, Uloga.poslovodja)
samo_voditelj = zahtijevaj_uloge(Uloga.voditelj)


def _fnum(s, zadano=0.0) -> float:
    try:
        return float(s)
    except (TypeError, ValueError):
        return zadano


# --- Norme -------------------------------------------------------------------
@router.get("/norme", response_model=list[NormaOut])
def norme(db: Session = Depends(get_db), _: Korisnik = Depends(voditelj_ili_poslovodja)):
    eur = _fnum(get_postavka(db, KLJUC_EUR, "0"))
    redovi = db.execute(select(NormaPosla).order_by(NormaPosla.broj_uzoraka.desc())).scalars().all()
    out = []
    for n in redovi:
        o = NormaOut.model_validate(n)
        o.cijena_eur = round((n.norma_min or 0) * eur / 60.0, 2)
        out.append(o)
    return out


@router.patch("/norme/{norma_id}", response_model=NormaOut)
def azuriraj_normu(norma_id: int, izmjene: NormaUpdate,
                   db: Session = Depends(get_db), _: Korisnik = Depends(voditelj_ili_poslovodja)):
    n = db.get(NormaPosla, norma_id)
    if not n:
        raise HTTPException(status_code=404, detail="Norma ne postoji")
    podaci = izmjene.model_dump(exclude_unset=True)
    if "rucno" in podaci and podaci["rucno"] is False:
        # vrati na izračunatu (medijan)
        n.rucno = False
        if n.medijan_min is not None:
            n.norma_min = n.medijan_min
    else:
        if podaci.get("norma_min") is not None:
            n.norma_min = int(podaci["norma_min"])
            n.rucno = True
    db.commit()
    db.refresh(n)
    return n


@router.post("/norme/preracunaj")
def preracunaj(db: Session = Depends(get_db), _: Korisnik = Depends(samo_voditelj)):
    broj = izracunaj_norme(db)
    return {"preracunato": broj}


# --- Obračun radione (živo povezivanje) --------------------------------------
@router.get("/obracun-info")
def obracun_info(db: Session = Depends(get_db), _: Korisnik = Depends(voditelj_ili_poslovodja)):
    from ..obracun_radione import info
    return info(db)


@router.post("/rekalibriraj")
def rekalibriraj(db: Session = Depends(get_db), _: Korisnik = Depends(samo_voditelj)):
    """Dohvati obračun radione i (ako je valjano) postavi €/norma-sat."""
    from ..obracun_radione import sinkroniziraj
    return sinkroniziraj(db, primijeni=True)


# --- Postavke ----------------------------------------------------------------
@router.get("/postavke", response_model=PostavkeOut)
def postavke(db: Session = Depends(get_db), _: Korisnik = Depends(voditelj_ili_poslovodja)):
    return PostavkeOut(
        eur_po_normi=_fnum(get_postavka(db, KLJUC_EUR, "0")),
        osnovica=_fnum(get_postavka(db, KLJUC_OSNOVICA, "0")),
        shadow=(get_postavka(db, KLJUC_SHADOW, "1") == "1"),
    )


@router.patch("/postavke", response_model=PostavkeOut)
def azuriraj_postavke(izmjene: PostavkeUpdate,
                      db: Session = Depends(get_db), _: Korisnik = Depends(samo_voditelj)):
    podaci = izmjene.model_dump(exclude_unset=True)
    if "eur_po_normi" in podaci and podaci["eur_po_normi"] is not None:
        set_postavka(db, KLJUC_EUR, str(podaci["eur_po_normi"]))
    if "osnovica" in podaci and podaci["osnovica"] is not None:
        set_postavka(db, KLJUC_OSNOVICA, str(podaci["osnovica"]))
    if "shadow" in podaci and podaci["shadow"] is not None:
        set_postavka(db, KLJUC_SHADOW, "1" if podaci["shadow"] else "0")
    db.commit()
    return postavke(db)  # type: ignore[arg-type]


# --- Učinak (shadow) ---------------------------------------------------------
@router.get("/ucinak", response_model=UcinakOut)
def ucinak(dana: int = Query(default=30, ge=1, le=365),
           db: Session = Depends(get_db), _: Korisnik = Depends(voditelj_ili_poslovodja)):
    """Što bi tko zaradio po novom modelu u zadnjih N dana (iz povijesti rada).

    Za svaki zapis povijesti s poznatom kategorijom pribroji normu tom radniku;
    suma norma-minuta × (€/norma-sat)/60 = procijenjena zarada. Stvarna plaća
    se NE dira (shadow)."""
    do = date.today()
    od = do - timedelta(days=dana)
    eur = _fnum(get_postavka(db, KLJUC_EUR, "0"))
    shadow = (get_postavka(db, KLJUC_SHADOW, "1") == "1")

    norme_map = {n.kategorija: n.norma_min for n in db.execute(select(NormaPosla)).scalars().all()}

    po_radniku_min: dict[str, int] = defaultdict(int)
    po_radniku_broj: dict[str, int] = defaultdict(int)
    bez_norme = 0
    red = db.execute(
        select(PovijestRada.radnik, PovijestRada.operacija)
        .where(PovijestRada.datum >= od, PovijestRada.datum <= do)
    ).all()
    for radnik, operacija in red:
        ime = (radnik or "").strip()
        if not ime:
            continue
        norma = norme_map.get(norm_kat(operacija))
        if norma is None:
            bez_norme += 1
            continue
        po_radniku_min[ime] += int(norma)
        po_radniku_broj[ime] += 1

    redovi = []
    for ime, minute in po_radniku_min.items():
        sati = round(minute / 60.0, 1)
        redovi.append(UcinakRedak(
            radnik=ime,
            broj_poslova=po_radniku_broj[ime],
            norma_min=minute,
            norma_sati=sati,
            procijenjena_zarada=round(sati * eur, 2),
        ))
    redovi.sort(key=lambda r: r.norma_min, reverse=True)
    return UcinakOut(od=od, do=do, dana=dana, eur_po_normi=eur, shadow=shadow,
                     bez_norme=bez_norme, redovi=redovi)
