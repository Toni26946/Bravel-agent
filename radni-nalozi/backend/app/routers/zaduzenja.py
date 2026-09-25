"""Zaduženje kamiona i prikolice — primopredajni obrazac s popisom opreme.

Obrazac („ZADUŽENJE KAMIONA") ima dva stupca: KAMION (dokumenti, kartice,
tablet, oprema) i PRIKOLICA (sigurnosna oprema i alat). Za svaku stavku
bilježi se je li predana (+/-), stvarna količina i napomena, uz zaglavlje
(registracije, datum) i potpisnike (odradio/predao/preuzeo).
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import trenutni_korisnik, zahtijevaj_uloge
from ..database import get_db
from ..models import DnevnikPrikapcanja, Korisnik, Uloga, Zaduzenje
from ..schemas import (
    ZaduzenjeCreate,
    ZaduzenjeListItem,
    ZaduzenjeOut,
    ZaduzenjeStavka,
    ZaduzenjeStavkaGrupa,
    ZaduzenjeUpdate,
)

router = APIRouter(prefix="/zaduzenja", tags=["zaduzenja"])

voditelj_ili_poslovodja = zahtijevaj_uloge(Uloga.voditelj, Uloga.poslovodja)


# ---------------------------------------------------------------------------
# Predložak opreme (fiksni popis iz obrasca) — (br, oprema, kom)
# ---------------------------------------------------------------------------
_KAMION: list[tuple[int, str, int]] = [
    (1, "Prometna – kamion", 1),
    (2, "Karton periodičnog – kamion", 1),
    (3, "Polica AO – kamion", 1),
    (4, "Potvrda o cestarini (CO2) i pregleda kočnica", 1),
    (5, "Zeleni karton", 1),
    (6, "Cemt", 1),
    (7, "Licenca", 1),
    (8, "Baždar tahografa", 1),
    (9, "Ugovor o leasingu", 1),
    (10, "Plaketa za Austriju", 1),
    (11, "Plaketa za Njemačku", 1),
    (12, "Adriatic polica za kabotažu", 1),
    (13, "Prometna – šlepa/prikolica", 1),
    (14, "Karton per. – šlepa/prikolica", 1),
    (15, "Potvrda o cestarini i pregledu kočnica", 1),
    (16, "Zeleni karton", 1),
    (17, "Cemt", 1),
    (18, "Polica AO – šlepa/prikolica", 1),
    (19, "Teretni list", 1),
    (20, "Putni list", 1),
    (21, "CMR prazni", 1),
    (22, "IQ Card", 1),
    (23, "Petrol na registraciju", 1),
    (24, "Kartica tifon (MOL GOLD)", 1),
    (25, "Kartica BP", 1),
    (26, "Kartica SHELL", 1),
    (27, "Kartica DKV", 1),
    (28, "Kartica Adria Oil", 1),
    (29, "Kartica AS24", 1),
    (30, "DARS GO (cest.: SLO)", 1),
    (31, "ENC uređaj (cest.: HR)", 1),
    (32, "GO BOX (cest.: A)", 1),
    (33, "MY TO CZ (cest.: CZ)", 1),
    (34, "MY TO (cest.: SK)", 1),
    (35, "cest.: H / Mobilisis", 1),
    (36, "TOL COLLECT (cest.: D)", 1),
    (37, "Viatoll", 1),
    (38, "Shell cestarina", 1),
    (39, "Nosač tableta", 1),
    (40, "Punjač za tablet", 1),
    (41, "Tablet", 1),
    (42, "Papir za tahograf", 1),
    (43, "Extender punjača (3 ulaza)", 1),
    (44, "Radna kaciga", 1),
    (45, "Kabanica", 1),
]

_PRIKOLICA: list[tuple[int, str, int]] = [
    (46, "Prva pomoć", 1),
    (47, "Reflektirajući prsluk", 1),
    (48, "Rezervne žarulje – set", 1),
    (49, "Trokut", 2),
    (50, "Tabla dugi teret", 1),
    (51, "Ključ za kotače", 1),
    (52, "Kuka", 1),
    (53, "Dizalica", 1),
    (54, "P.P. aparati (ako su novi, sa potvrdom)", 2),
    (55, "Sajla za šlepanje", 1),
    (56, "Crijevo za pumpanje guma", 1),
    (57, "Set odvijača", 1),
    (58, "Set ključeva 6–32", 1),
    (60, "Čekić", 1),
    (61, "Set torx", 1),
    (62, "Set imbusa", 1),
    (63, "Kutija za alat", 1),
    (64, "Pajser / metalna poluga", 1),
    (65, "Okasto viljuškasti ključ 36", 1),
    (66, "Rolcange", 1),
    (67, "Ručna mazalica", 1),
    (68, "Metalni izvlakač za crijeva hidraulike (teleskop) – Penz", 1),
    (69, "Manometar", 1),
    (70, "Cijev poluga", 1),
    (71, "Lanci za snijeg – set", 2),
    (72, "Gurtne", 1),
    (73, "Metla", 1),
    (74, "Lopata", 1),
    (75, "Zaštitne cipele", 1),
]


def _predlozak_stavke() -> list[dict]:
    out: list[dict] = []
    for br, oprema, kom in _KAMION:
        out.append({"br": br, "grupa": "kamion", "oprema": oprema, "kom": kom, "stanje": "", "kolicina": None, "napomena": None})
    for br, oprema, kom in _PRIKOLICA:
        out.append({"br": br, "grupa": "prikolica", "oprema": oprema, "kom": kom, "stanje": "", "kolicina": None, "napomena": None})
    return out


@router.get("/predlozak", response_model=ZaduzenjeStavkaGrupa)
def predlozak(_: Korisnik = Depends(voditelj_ili_poslovodja)):
    """Vrati prazan predložak opreme (grupe kamion/prikolica) za novi obrazac."""
    return ZaduzenjeStavkaGrupa(
        kamion=[ZaduzenjeStavka(br=br, grupa="kamion", oprema=o, kom=k) for br, o, k in _KAMION],
        prikolica=[ZaduzenjeStavka(br=br, grupa="prikolica", oprema=o, kom=k) for br, o, k in _PRIKOLICA],
    )


@router.get("/vozaci", response_model=list[str])
def vozaci(db: Session = Depends(get_db), _: Korisnik = Depends(voditelj_ili_poslovodja)):
    """Popis poznatih vozača (za padajući izbornik) — objedinjeno iz:
    korisnika uloge 'vozac', dnevnika prikapčanja i ranijih zaduženja."""
    imena: dict[str, str] = {}  # ključ = lowercase (dedup), vrijednost = prikaz

    def _dodaj(v):
        if v and v.strip():
            s = v.strip()
            imena.setdefault(s.lower(), s)

    for (ime,) in db.query(Korisnik.ime).filter(Korisnik.uloga == Uloga.vozac, Korisnik.aktivan == True).all():  # noqa: E712
        _dodaj(ime)
    for (v,) in db.query(DnevnikPrikapcanja.vozac).filter(DnevnikPrikapcanja.vozac.isnot(None)).distinct().all():
        _dodaj(v)
    for (v,) in db.query(Zaduzenje.vozac).filter(Zaduzenje.vozac.isnot(None)).distinct().all():
        _dodaj(v)
    return sorted(imena.values(), key=lambda s: s.lower())


@router.get("", response_model=list[ZaduzenjeListItem])
def popis(db: Session = Depends(get_db), _: Korisnik = Depends(voditelj_ili_poslovodja)):
    redovi = db.execute(select(Zaduzenje).order_by(Zaduzenje.kreiran.desc())).scalars().all()
    return redovi


@router.post("", response_model=ZaduzenjeOut, status_code=201)
def kreiraj(
    podaci: ZaduzenjeCreate,
    db: Session = Depends(get_db),
    korisnik: Korisnik = Depends(voditelj_ili_poslovodja),
):
    kamion = (podaci.kamion_registracija or "").strip()
    prikolica = (podaci.prikolica_registracija or "").strip()
    vozac = (podaci.vozac or "").strip()
    nedostaje = [
        naziv for naziv, vrijednost in (("kamion", kamion), ("prikolica", prikolica), ("vozač", vozac)) if not vrijednost
    ]
    if nedostaje:
        raise HTTPException(status_code=400, detail="Obavezna polja nedostaju: " + ", ".join(nedostaje))
    stavke = [s.model_dump() for s in podaci.stavke] if podaci.stavke is not None else _predlozak_stavke()
    z = Zaduzenje(
        kamion_registracija=kamion,
        kamion_gb=(podaci.kamion_gb or "").strip() or None,
        prikolica_registracija=prikolica,
        prikolica_gb=(podaci.prikolica_gb or "").strip() or None,
        vozac=vozac,
        datum=podaci.datum or date.today(),
        odradio=(podaci.odradio or "").strip() or None,
        predao=(podaci.predao or "").strip() or None,
        preuzeo=(podaci.preuzeo or "").strip() or None,
        napomena=(podaci.napomena or "").strip() or None,
        status=podaci.status or "u_tijeku",
        stavke=stavke,
        kreirao_id=korisnik.id,
    )
    db.add(z)
    db.commit()
    db.refresh(z)
    return z


@router.get("/{zaduzenje_id}", response_model=ZaduzenjeOut)
def dohvati(zaduzenje_id: int, db: Session = Depends(get_db), _: Korisnik = Depends(voditelj_ili_poslovodja)):
    z = db.get(Zaduzenje, zaduzenje_id)
    if not z:
        raise HTTPException(status_code=404, detail="Zaduženje ne postoji")
    return z


@router.patch("/{zaduzenje_id}", response_model=ZaduzenjeOut)
def azuriraj(
    zaduzenje_id: int,
    izmjene: ZaduzenjeUpdate,
    db: Session = Depends(get_db),
    _: Korisnik = Depends(voditelj_ili_poslovodja),
):
    z = db.get(Zaduzenje, zaduzenje_id)
    if not z:
        raise HTTPException(status_code=404, detail="Zaduženje ne postoji")
    podaci = izmjene.model_dump(exclude_unset=True)
    if "stavke" in podaci and podaci["stavke"] is not None:
        z.stavke = [s.model_dump() if hasattr(s, "model_dump") else s for s in izmjene.stavke]
        podaci.pop("stavke")
    # Obavezna polja se ne smiju isprazniti kad su eksplicitno poslana.
    for polje, naziv in (("kamion_registracija", "kamion"), ("prikolica_registracija", "prikolica"), ("vozac", "vozač")):
        if polje in podaci and not (podaci[polje] or "").strip():
            raise HTTPException(status_code=400, detail=f"Obavezno polje ne može biti prazno: {naziv}")
    for polje in ("kamion_registracija", "kamion_gb", "prikolica_registracija", "prikolica_gb", "vozac", "odradio", "predao", "preuzeo", "napomena"):
        if polje in podaci:
            v = podaci[polje]
            setattr(z, polje, (v or "").strip() or None if isinstance(v, str) else v)
    if "datum" in podaci and podaci["datum"] is not None:
        z.datum = podaci["datum"]
    if "status" in podaci and podaci["status"]:
        z.status = podaci["status"]
    db.commit()
    db.refresh(z)
    return z


@router.delete("/{zaduzenje_id}", status_code=204)
def obrisi(
    zaduzenje_id: int,
    db: Session = Depends(get_db),
    _: Korisnik = Depends(zahtijevaj_uloge(Uloga.voditelj)),
):
    z = db.get(Zaduzenje, zaduzenje_id)
    if not z:
        raise HTTPException(status_code=404, detail="Zaduženje ne postoji")
    db.delete(z)
    db.commit()
    return None
