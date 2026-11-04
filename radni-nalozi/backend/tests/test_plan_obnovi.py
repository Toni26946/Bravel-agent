"""Test „Arhiviraj gotovo → novi nalog" (/plan/nalog/{id}/obnovi).

Zatvara nalog i prenosi NEDOVRŠENE operacije u novi nalog pod istim GB; gotove
ostaju na zatvorenom i idu u servisnu povijest."""
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DATABASE_URL", "sqlite://")

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import (
    Dodjela, Korisnik, Nalog, Operacija, PovijestRada, StatusNaloga, Uloga, Vozilo, Zadatak,
)
from app.routers.plan import obnovi_nalog


def _session():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng, autoflush=False)()


def test_obnovi_prenese_nedovrseno_i_arhivira_gotovo():
    db = _session()
    vod = Korisnik(ime="Vod", korisnicko_ime="vod", lozinka_hash="x", uloga=Uloga.voditelj)
    meh = Korisnik(ime="Meh", korisnicko_ime="meh", lozinka_hash="x", uloga=Uloga.radnik)
    voz = Vozilo(gb="400", marka="RADIONA"); db.add_all([vod, meh, voz]); db.flush()
    n = Nalog(broj="RN-400-A", vozilo_id=voz.id, naslov="RADIONA", kreirao_id=vod.id,
              status=StatusNaloga.u_radu, plan_rang=2, plan_hitno=True)
    db.add(n); db.flush()
    # Gotova operacija (→ povijest)
    op_g = Operacija(nalog_id=n.id, kategorija="PRANJE", redoslijed=0); db.add(op_g); db.flush()
    zg = Zadatak(operacija_id=op_g.id, opis="oprano", gotovo=True, utroseno_sek=600,
                 zavrseno=datetime.now(timezone.utc)); zg.radnici = [meh]
    # Nedovršena operacija, mjerač teče (→ novi nalog)
    op_n = Operacija(nalog_id=n.id, kategorija="GUME", redoslijed=1); db.add(op_n); db.flush()
    zn = Zadatak(operacija_id=op_n.id, opis="demontaza", utroseno_sek=120,
                 zapoceto=datetime.now(timezone.utc)); zn.radnici = [meh]
    db.add_all([zg, zn]); db.commit()

    rez = obnovi_nalog(n.id, korisnik=vod, db=db)
    assert rez["preneseno"] == 1 and rez["arhivirano"] == 1

    db.refresh(n)
    # Stari nalog: zatvoren, izašao iz plana, ostala mu samo gotova operacija.
    assert n.status == StatusNaloga.zatvoren
    assert n.plan_rang is None and n.plan_hitno is False
    assert [op.kategorija for op in n.operacije] == ["PRANJE"]

    # Novi nalog: isti GB, u radu, preuzeo mjesto u planu, nosi nedovršenu operaciju.
    novi = db.get(Nalog, rez["novi_id"])
    assert novi.vozilo_id == voz.id and novi.status == StatusNaloga.u_radu
    assert novi.plan_rang == 2 and novi.plan_hitno is True
    assert [op.kategorija for op in novi.operacije] == ["GUME"]
    z_novi = novi.operacije[0].zadaci[0]
    assert z_novi.zapoceto is not None and z_novi.utroseno_sek == 120
    assert [r.id for r in z_novi.radnici] == [meh.id], "radnik ostaje na zadatku"
    assert db.query(Dodjela).filter(Dodjela.nalog_id == novi.id, Dodjela.radnik_id == meh.id).count() == 1

    # Gotova operacija upisana u servisnu povijest zatvorenog naloga.
    pov = db.query(PovijestRada).filter(PovijestRada.nalog_id == n.id).all()
    assert len(pov) == 1 and pov[0].opis == "oprano"


def test_obnovi_odbija_kad_nema_gotovih():
    db = _session()
    vod = Korisnik(ime="Vod", korisnicko_ime="vod", lozinka_hash="x", uloga=Uloga.voditelj)
    voz = Vozilo(gb="401", marka="X"); db.add_all([vod, voz]); db.flush()
    n = Nalog(broj="RN-401", vozilo_id=voz.id, naslov="X", kreirao_id=vod.id, status=StatusNaloga.u_radu)
    db.add(n); db.flush()
    op = Operacija(nalog_id=n.id, kategorija="A"); db.add(op); db.flush()
    db.add(Zadatak(operacija_id=op.id, opis="nedovrseno")); db.commit()

    with pytest.raises(HTTPException) as e:
        obnovi_nalog(n.id, korisnik=vod, db=db)
    assert e.value.status_code == 409


def test_obnovi_odbija_kad_nema_nedovrsenih():
    db = _session()
    vod = Korisnik(ime="Vod", korisnicko_ime="vod", lozinka_hash="x", uloga=Uloga.voditelj)
    voz = Vozilo(gb="402", marka="X"); db.add_all([vod, voz]); db.flush()
    n = Nalog(broj="RN-402", vozilo_id=voz.id, naslov="X", kreirao_id=vod.id, status=StatusNaloga.u_radu)
    db.add(n); db.flush()
    op = Operacija(nalog_id=n.id, kategorija="A"); db.add(op); db.flush()
    db.add(Zadatak(operacija_id=op.id, opis="gotovo", gotovo=True)); db.commit()

    with pytest.raises(HTTPException) as e:
        obnovi_nalog(n.id, korisnik=vod, db=db)
    assert e.value.status_code == 409
