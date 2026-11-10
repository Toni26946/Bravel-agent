"""Integracije (vlasnik) — pristupni podaci za vanjske sustave spremaju se u bazu,
pa ih Toni zalijepi izravno u portal (Šifrarnik → Integracije), bez terminala.

Zasad: APROSS (Zagreb Data) — API-KEY (+ opcionalni Basic Auth). Ključ se NIKAD
ne vraća natrag klijentu; vraća se samo je li postavljen i zadnje 4 znaka.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import aross
from ..auth import zahtijevaj_ai_poslovodja, zahtijevaj_uloge
from ..database import get_db
from ..models import Korisnik, Uloga
from ..norme import get_postavka, set_postavka

router = APIRouter(prefix="/integracije", tags=["integracije"])

samo_vlasnik = zahtijevaj_ai_poslovodja()
skladiste = zahtijevaj_uloge(Uloga.skladistar, Uloga.voditelj, Uloga.poslovodja)


def _zadnje4(s: str) -> str:
    s = (s or "").strip()
    return ("…" + s[-4:]) if len(s) >= 4 else ("•" * len(s))


class ArossIn(BaseModel):
    api_key: str | None = None   # None/izostavljeno = ne diraj; "" = obriši
    user: str | None = None
    lozinka: str | None = None


@router.get("/aross")
def aross_stanje(db: Session = Depends(get_db), _: Korisnik = Depends(samo_vlasnik)):
    """Stanje APROSS integracije — bez otkrivanja ključa."""
    key = (get_postavka(db, aross.P_KEY, "") or "").strip()
    user = (get_postavka(db, aross.P_USER, "") or "").strip()
    return {
        "povezano": aross.konfigurirano(db),
        "ima_kljuc": bool(key),
        "kljuc_kraj": _zadnje4(key) if key else "",
        "ima_basic": aross.ima_basic(db),
        "korisnik": user,                 # korisničko ime nije tajna; lozinka se ne vraća
        "baza": aross._baza(db) if key else "",
    }


@router.post("/aross")
def aross_spremi(p: ArossIn, db: Session = Depends(get_db), _: Korisnik = Depends(samo_vlasnik)):
    """Spremi API-KEY i (opcionalno) Basic Auth. Prazan string briše vrijednost;
    izostavljeno polje se ne dira."""
    if p.api_key is not None:
        set_postavka(db, aross.P_KEY, p.api_key.strip())
    if p.user is not None:
        set_postavka(db, aross.P_USER, p.user.strip())
    if p.lozinka is not None:
        set_postavka(db, aross.P_PASS, p.lozinka)
    db.commit()
    return aross_stanje(db, _)


@router.post("/aross/test")
def aross_test(db: Session = Depends(get_db), _: Korisnik = Depends(samo_vlasnik)):
    """Pokušaj dohvat skladišta — potvrda da ključ i mreža rade."""
    if not aross.konfigurirano(db):
        return {"ok": False, "poruka": "Nema API-KEY-a. Zalijepi ključ pa spremi."}
    try:
        skl = aross.skladista(db)
    except aross.ArossGreska as e:
        return {"ok": False, "poruka": str(e)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "poruka": f"Greška u spoju: {e}"}
    n = len(skl) if isinstance(skl, list) else 0
    return {"ok": True, "poruka": f"Spoj radi — dohvaćeno skladišta: {n}.", "skladista": n}


@router.get("/aross/debug")
def aross_debug(db: Session = Depends(get_db), _: Korisnik = Depends(samo_vlasnik)):
    """Sirovi odgovori APROSS-a — za dijagnostiku strukture (vlasnik-only)."""
    out = {}
    for ime, fn in (("skladista", aross.skladista), ("artikli", aross.artikli),
                    ("artikliStanje", aross.artikli_stanje)):
        try:
            out[ime] = fn(db)
        except Exception as e:  # noqa: BLE001
            out[ime] = {"GRESKA": str(e)}
    return out


def _na_broj(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


@router.get("/aross/zalihe")
def aross_zalihe(db: Session = Depends(get_db), _: Korisnik = Depends(skladiste)):
    """Stanje zalihe po skladištima (uživo iz APROSS-a), s imenima artikala.
    Vraća {povezano, skladista:[{sifra, naziv, artikli:[{sifra, naziv, kataloskiBroj, jmj, stanje}]}], osvjezeno}."""
    if not aross.konfigurirano(db):
        return {"povezano": False, "skladista": [], "osvjezeno": None}
    try:
        art = aross.artikli(db)
        stanje = aross.artikli_stanje(db)
    except aross.ArossGreska as e:
        raise HTTPException(status_code=502, detail=str(e))

    imena = {a.get("sifra"): a for a in (art or [])}
    skladista = []
    for s in (stanje or []):
        redovi = []
        for a in (s.get("artikli") or []):
            sa = a.get("sifraArtikla")
            meta = imena.get(sa, {})
            redovi.append({
                "sifra": sa,
                "naziv": meta.get("naziv") or f"Artikl {sa}",
                "kataloskiBroj": meta.get("kataloskiBroj"),
                "jmj": meta.get("jmj"),
                "stanje": _na_broj(a.get("stanje")),
            })
        redovi.sort(key=lambda r: (r["naziv"] or "").lower())
        skladista.append({
            "sifra": s.get("sifraSkladista"),
            "naziv": s.get("nazivSkladista") or f"Skladište {s.get('sifraSkladista')}",
            "artikli": redovi,
        })
    skladista.sort(key=lambda s: (s["naziv"] or "").lower())
    return {"povezano": True, "skladista": skladista,
            "osvjezeno": datetime.now(timezone.utc).isoformat()}
