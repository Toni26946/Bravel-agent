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


def test_obnovi_pomijesana_operacija():
    """Operacija s DVA zadatka (jedan gotov, jedan ne): gotov ostaje na zatvorenom
    nalogu (→ povijest), nedovršen se preseli u novi — ne smije pasti na 'nema gotovih'."""
    db = _session()
    vod = Korisnik(ime="Vod", korisnicko_ime="vod", lozinka_hash="x", uloga=Uloga.voditelj)
    meh = Korisnik(ime="Meh", korisnicko_ime="meh", lozinka_hash="x", uloga=Uloga.radnik)
    voz = Vozilo(gb="400", marka="RADIONA"); db.add_all([vod, meh, voz]); db.flush()
    n = Nalog(broj="RN-400-B", vozilo_id=voz.id, naslov="RADIONA", kreirao_id=vod.id,
              status=StatusNaloga.u_radu, plan_rang=1)
    db.add(n); db.flush()
    op = Operacija(nalog_id=n.id, kategorija="RAZNO", redoslijed=0); db.add(op); db.flush()
    zg = Zadatak(operacija_id=op.id, opis="gotov dio", gotovo=True,
                 zavrseno=datetime.now(timezone.utc))
    zn = Zadatak(operacija_id=op.id, opis="nedovrsen dio"); zn.radnici = [meh]
    db.add_all([zg, zn]); db.commit()

    rez = obnovi_nalog(n.id, korisnik=vod, db=db)
    assert rez["arhivirano"] == 1 and rez["preneseno"] == 1

    db.refresh(n)
    assert n.status == StatusNaloga.zatvoren
    # Na zatvorenom ostaje samo gotov zadatak; nedovršen je otišao.
    preostali = [z for o in n.operacije for z in o.zadaci]
    assert [z.opis for z in preostali] == ["gotov dio"]
    novi = db.get(Nalog, rez["novi_id"])
    preneseni = [z for o in novi.operacije for z in o.zadaci]
    assert [z.opis for z in preneseni] == ["nedovrsen dio"]
    assert novi.operacije[0].kategorija == "RAZNO"
    # Gotov dio upisan u povijest.
    pov = db.query(PovijestRada).filter(PovijestRada.nalog_id == n.id).all()
    assert len(pov) == 1 and pov[0].opis == "gotov dio"


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


def test_smije_meh_vlasnik_ne_puca_na_ai_poslovodja():
    """Regresija: dispečer/vlasnik smije kliknuti umjesto mehaničara. Prije je
    _smije_meh čitao ORM.ai_poslovodja (ne postoji) → AttributeError → 500 na /prekini."""
    from app.auth import ima_plan_pristup, je_vlasnik
    from app.routers.plan import _smije_meh

    db = _session()
    # settings.ai_poslovodja_user default = "toni" → vlasnik je korisnik "toni".
    toni = Korisnik(ime="Toni", korisnicko_ime="toni", lozinka_hash="x", uloga=Uloga.voditelj)
    meh = Korisnik(ime="Meh", korisnicko_ime="meh", lozinka_hash="x", uloga=Uloga.radnik)
    drugi = Korisnik(ime="Drugi", korisnicko_ime="drugi", lozinka_hash="x", uloga=Uloga.radnik)
    voz = Vozilo(gb="1", marka="X"); db.add_all([toni, meh, drugi, voz]); db.flush()
    n = Nalog(broj="RN-1", vozilo_id=voz.id, naslov="1", kreirao_id=toni.id, status=StatusNaloga.u_radu)
    db.add(n); db.flush()
    op = Operacija(nalog_id=n.id, kategorija="MOTOR"); db.add(op); db.flush()
    z = Zadatak(operacija_id=op.id, opis="x"); z.radnici = [meh]; db.add(z); db.commit()

    assert je_vlasnik(toni) is True and ima_plan_pristup(toni) is True
    assert _smije_meh(toni, z) is True     # vlasnik umjesto mehaničara (ne puca)
    assert _smije_meh(meh, z) is True      # sam mehaničar
    assert _smije_meh(drugi, z) is False   # tuđi radnik bez pristupa planu → ne


def test_prijavi_rucno_pokrece_mjerac_i_biljezi():
    """Ručna prijava: pokrene mjerač tom mehaničaru i zabilježi KlikRucno (za klik-bonus)."""
    from app.models import KlikRucno
    from app.routers.plan import PrijaviRucnoIn, prijavi_rucno

    db = _session()
    vod = Korisnik(ime="Vod", korisnicko_ime="vod", lozinka_hash="x", uloga=Uloga.voditelj)
    meh = Korisnik(ime="Meh", korisnicko_ime="meh", lozinka_hash="x", uloga=Uloga.radnik)
    voz = Vozilo(gb="900", marka="X"); db.add_all([vod, meh, voz]); db.flush()
    n = Nalog(broj="RN-900", vozilo_id=voz.id, naslov="900", kreirao_id=vod.id,
              status=StatusNaloga.u_radu, plan_rang=0)
    db.add(n); db.flush()
    op = Operacija(nalog_id=n.id, kategorija="MOTOR"); db.add(op); db.flush()
    z = Zadatak(operacija_id=op.id, opis="x", ceka_potvrdu=True); z.radnici = [meh]
    db.add(z); db.commit()

    rez = prijavi_rucno(z.id, PrijaviRucnoIn(radnik_id=meh.id), korisnik=vod, db=db)
    assert rez["ok"] is True
    db.refresh(z)
    assert z.zapoceto is not None
    vr = {x.radnik_id: x for x in z.vremena}
    assert vr[meh.id].zapoceto is not None          # mjerač mu teče
    assert db.query(KlikRucno).filter(KlikRucno.radnik_id == meh.id).count() == 1
