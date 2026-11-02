"""Test dashboard povlačenja zadatka između mehaničara (/plan/premjesti)."""
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DATABASE_URL", "sqlite://")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Korisnik, Nalog, Operacija, StatusNaloga, Uloga, Vozilo, Zadatak
from app.routers.dispecer import _red
from app.routers.plan import PremjestiIn, premjesti


def _session():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng, autoflush=False)()


def test_premjesti_prebaci_na_drugog_i_slozi_red():
    db = _session()
    a = Korisnik(ime="Meh A", korisnicko_ime="meh.a", lozinka_hash="x", uloga=Uloga.radnik)
    b = Korisnik(ime="Meh B", korisnicko_ime="meh.b", lozinka_hash="x", uloga=Uloga.radnik)
    voz = Vozilo(gb="T55", marka="MAN"); db.add_all([a, b, voz]); db.flush()
    n = Nalog(broj="RN-M", vozilo_id=voz.id, naslov="T", kreirao_id=a.id, status=StatusNaloga.u_radu)
    db.add(n); db.flush()
    op = Operacija(nalog_id=n.id, kategorija="A"); db.add(op); db.flush()
    za = Zadatak(operacija_id=op.id, opis="SELI", ceka_potvrdu=True); za.radnici = [a]
    zb1 = Zadatak(operacija_id=op.id, opis="B1", red_ruc=0); zb1.radnici = [b]
    zb2 = Zadatak(operacija_id=op.id, opis="B2", red_ruc=1); zb2.radnici = [b]
    db.add_all([za, zb1, zb2]); db.commit()

    # ispušteno između B1 i B2 u retku mehaničara B
    premjesti(PremjestiIn(zadatak_id=za.id, s_radnika=a.id, na_radnika=b.id,
                          redoslijed=[zb1.id, za.id, zb2.id]), korisnik=a, db=db)
    db.refresh(za)
    assert [r.id for r in za.radnici] == [b.id], "zadatak mora prijeći na B"
    assert za.ceka_potvrdu is False, "novom mehaničaru se tek treba poslati"
    assert [t[2].opis for t in _red(db, b)] == ["B1", "SELI", "B2"]
    assert _red(db, a) == []


def test_vrati_u_plan_otvara_gotov_zadatak():
    from datetime import datetime, timezone
    from app.routers.plan import vrati_u_plan
    db = _session()
    a = Korisnik(ime="Meh A", korisnicko_ime="meh.a", lozinka_hash="x", uloga=Uloga.radnik)
    voz = Vozilo(gb="T56", marka="MAN"); db.add_all([a, voz]); db.flush()
    n = Nalog(broj="RN-V", vozilo_id=voz.id, naslov="T", kreirao_id=a.id, status=StatusNaloga.gotov)
    db.add(n); db.flush()
    op = Operacija(nalog_id=n.id, kategorija="A"); db.add(op); db.flush()
    z = Zadatak(operacija_id=op.id, opis="GOTOV", gotovo=True, utroseno_sek=600,
                zavrseno=datetime.now(timezone.utc)); z.radnici = [a]
    db.add(z); db.commit()

    vrati_u_plan(z.id, korisnik=a, db=db)
    db.refresh(z); db.refresh(n)
    assert z.gotovo is False and z.zavrseno is None and z.zapoceto is None
    assert z.utroseno_sek == 600, "dosadašnje vrijeme ostaje"
    assert n.status == StatusNaloga.u_radu
    assert [t[2].opis for t in _red(db, a)] == ["GOTOV"], "vraća se istom mehaničaru u red"
