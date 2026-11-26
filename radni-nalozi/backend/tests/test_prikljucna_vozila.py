"""Priključna vozila — gdje je što (Toni 25.11.2026.): jedno stanje po prikolici/šlepi,
bez osobnih auta i RADIONE."""
import asyncio
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DATABASE_URL", "sqlite://")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import (DnevnikPrikapcanja, Korisnik, Nalog, RegistarVozila, StatusNaloga,
                        StatusVozila, Uloga, Vozilo, VrstaDogadaja)
from app.routers import vozila as v


def _session():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng, autoflush=False)()


def test_stanja_prikljucnih(monkeypatch):
    async def bez_flote():
        return None
    monkeypatch.setattr(v.flota, "vozila_flota", bez_flote)
    db = _session()
    k = Korisnik(ime="Vod", korisnicko_ime="vod", lozinka_hash="x", uloga=Uloga.voditelj)
    db.add(k); db.flush()
    P = dict(kategorija="prikolica", status=StatusVozila.aktivno)
    db.add_all([
        RegistarVozila(gb="10", vrsta="ŠLEPA", **P),                                    # u radioni
        RegistarVozila(gb="11", vrsta="PRIKOLICA", **P),                                # prikačena
        RegistarVozila(gb="12", vrsta="ŠLEPA", kategorija="prikolica", status=StatusVozila.pokvareno),
        RegistarVozila(gb="13", vrsta="ŠLEPA", kategorija="prikolica", status=StatusVozila.spremno,
                       lokacija="Apital", spreman_od=date(2026, 11, 17)),
        RegistarVozila(gb="14", vrsta="ŠLEPA", **P),                                    # za upisati
        RegistarVozila(gb="15", vrsta="PRIKOLICA", kategorija="prikolica", status=StatusVozila.nezaduzeno),
        RegistarVozila(gb="16", vrsta="ŠLEPA", **P),                                    # nepoznato
        RegistarVozila(gb="17", vrsta="ŠLEPA", kategorija="ostalo", status=StatusVozila.aktivno),  # šlepa iz 'ostalo'
        RegistarVozila(gb="1140", vrsta="AUTO", kategorija="auto", status=StatusVozila.aktivno),
        RegistarVozila(gb="400", vrsta="RADIONA", kategorija="ostalo", status=StatusVozila.aktivno),
        RegistarVozila(gb="18", vrsta="ŠLEPA", kategorija="prikolica", status=StatusVozila.prodano),
        RegistarVozila(gb="45", vrsta="DIZALICA", kategorija="kamion", registracija="ZG7669HE"),
    ])
    v10, v14 = Vozilo(gb="10"), Vozilo(gb="14")
    db.add_all([v10, v14]); db.flush()
    db.add(Nalog(broj="RN-10", vozilo_id=v10.id, naslov="x", kreirao_id=k.id, status=StatusNaloga.u_radu))
    db.add(Nalog(broj="RN-14", vozilo_id=v14.id, naslov="x", kreirao_id=k.id, status=StatusNaloga.gotov))
    sad = datetime.now(timezone.utc)
    db.add(DnevnikPrikapcanja(prikolica_gb="11", kamion_gb="45", vozac="Ivo",
                              vrsta=VrstaDogadaja.prikaceno, kreirao_id=k.id, vrijeme=sad))
    db.add(DnevnikPrikapcanja(prikolica_gb="17", vrsta=VrstaDogadaja.otkaceno, lokacija="Parking 2",
                              kreirao_id=k.id, vrijeme=sad - timedelta(days=2)))
    db.commit()

    d = asyncio.run(v.prikljucna_vozila(korisnik=k, db=db))
    st = {x["gb"]: x for x in d["stavke"]}
    assert set(st) == {"10", "11", "12", "13", "14", "15", "16", "17"}, "bez auta, radione, prodanih, kamiona"
    assert st["10"]["stanje"] == "radiona" and st["10"]["broj"] == "RN-10"
    assert st["11"]["stanje"] == "prikacena" and st["11"]["kamion_gb"] == "45" and st["11"]["kamion_reg"] == "ZG7669HE"
    assert st["12"]["stanje"] == "pokvarena"
    assert st["13"]["stanje"] == "spremna" and st["13"]["lokacija"] == "Apital"
    assert st["14"]["stanje"] == "za_upisati"
    assert st["15"]["stanje"] == "slobodna"
    assert st["16"]["stanje"] == "nepoznato"
    assert st["17"]["stanje"] == "slobodna" and st["17"]["lokacija"] == "Parking 2"
    assert d["brojevi"]["nepoznato"] == 1 and d["ukupno"] == 8
    assert [x["stanje"] for x in d["stavke"]][0] == "radiona", "poredano po stanju"

    # „Nije spremna" (26.11.2026.): nalog gotov, ali upisan parking NAKON naloga →
    # Slobodna s tim parkingom, NE opet „Za upisati".
    r14 = db.get(RegistarVozila, "14")
    r14.status, r14.lokacija = StatusVozila.nezaduzeno, "Apital"
    db.add(DnevnikPrikapcanja(prikolica_gb="14", vrsta=VrstaDogadaja.otkaceno, lokacija="Apital",
                              kreirao_id=k.id, vrijeme=datetime.now(timezone.utc) + timedelta(seconds=1)))
    db.commit()
    st = {x["gb"]: x for x in asyncio.run(v.prikljucna_vozila(korisnik=k, db=db))["stavke"]}
    assert st["14"]["stanje"] == "slobodna" and st["14"]["lokacija"] == "Apital"


def test_dodaj_parking_bez_duplikata_po_velikim_slovima():
    """Novi parking iz odabira (26.11.2026.): „bad  soden" = „Bad Soden", bez duplikata."""
    from app.schemas import ParkingCreate
    db = _session()
    k = Korisnik(ime="Posl", korisnicko_ime="posl", lozinka_hash="x", uloga=Uloga.poslovodja)
    db.add(k); db.commit()
    p1 = v.dodaj_parking(ParkingCreate(naziv="  Bad   Soden "), k, db)
    p2 = v.dodaj_parking(ParkingCreate(naziv="bad soden"), k, db)
    assert p1.naziv == "Bad Soden" and p1.id == p2.id
    assert [p.naziv for p in v.parkinzi(k, db)] == ["Bad Soden"]
