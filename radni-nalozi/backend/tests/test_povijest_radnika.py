"""Povijest po radniku — tko je što radio (Veljko 26.11.2026., WhatsApp #438)."""
import os
import sys
from datetime import date, timedelta
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DATABASE_URL", "sqlite://")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Korisnik, Nalog, PovijestRada, StatusNaloga, Uloga, Vozilo
from app.routers.vozila import povijest_radnika


def _db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    db = sessionmaker(bind=eng, autoflush=False)()
    vod = Korisnik(ime="Voditelj", korisnicko_ime="v", lozinka_hash="x", uloga=Uloga.voditelj)
    meh = Korisnik(ime="Horvat Ivan", korisnicko_ime="h", lozinka_hash="x", uloga=Uloga.radnik)
    star = Korisnik(ime="Bivši Radnik", korisnicko_ime="b", lozinka_hash="x", uloga=Uloga.radnik, aktivan=False)
    v1, v2 = Vozilo(gb="433", registracija="ZG1"), Vozilo(gb="81", registracija="ZG2")
    db.add_all([vod, meh, star, v1, v2]); db.flush()
    n = Nalog(broj="RN-1", vozilo_id=v1.id, naslov="x", kreirao_id=vod.id, status=StatusNaloga.gotov)
    db.add(n); db.flush()
    danas = date.today()
    db.add_all([
        PovijestRada(vozilo_id=v1.id, nalog_id=n.id, datum=danas, radnik="Horvat Ivan, Kovač Marko",
                     operacija="Motor", opis="Zamjena filtera", minute=45),
        PovijestRada(vozilo_id=v2.id, datum=danas - timedelta(days=40), radnik="Horvat Ivan",
                     operacija="Kočnice", opis="Pločice", minute=30),
        PovijestRada(vozilo_id=v2.id, datum=danas, radnik="Kovač Marko", opis="Gume"),
    ])
    db.commit()
    return db


def test_poslovi_radnika_s_vozilom_i_nalogom():
    d = povijest_radnika(radnik=" horvat ", dana=None, _=None, db=_db())
    assert d["ukupno_poslova"] == 2 and d["ukupno_minuta"] == 75 and d["vozila"] == 2
    prvi = d["poslovi"][0]
    assert prvi["gb"] == "433" and prvi["nalog_broj"] == "RN-1" and prvi["opis"] == "Zamjena filtera"
    assert d["poslovi"][1]["nalog_broj"] is None


def test_filter_dana_i_popis_imena():
    db = _db()
    d = povijest_radnika(radnik="Horvat Ivan", dana=30, _=None, db=db)
    assert [p["opis"] for p in d["poslovi"]] == ["Zamjena filtera"]
    imena = povijest_radnika(radnik="", dana=None, _=None, db=db)["radnici"]
    assert "Horvat Ivan" in imena and "Kovač Marko" in imena
    assert "Bivši Radnik" not in imena and "Voditelj" not in imena
