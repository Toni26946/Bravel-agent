"""Pregledi vozila: rok se upisuje izravno („vrijedi do"), Toni 25.11.2026. — tehnički
piše različite datume pa „datum + 3 mj." nije dobar."""
import os
import sys
from datetime import date
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DATABASE_URL", "sqlite://")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import seed
from app.database import Base
from app.models import RegistarVozila
from app.pregledi_auto import VRSTE, _rok, rok_provjere


def _session():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng, autoflush=False)()


def test_vrijedi_do_ima_prednost():
    assert _rok(date(2026, 9, 1), 3, date(2026, 11, 17)) == date(2026, 11, 17)
    assert _rok(date(2026, 9, 1), 3) == date(2026, 12, 1)
    r = RegistarVozila(gb="1", periodicki_datum=date(2026, 9, 1), periodicki_int=3, periodicki_do=date(2027, 1, 5))
    rok_periodicki = dict((k, f) for (k, _o, f) in VRSTE)["PERIODIČKI PREGLED"]
    assert rok_periodicki(r) == date(2027, 1, 5)


def test_jednokratno_popuni_vrijedi_do(tmp_path, monkeypatch):
    monkeypatch.setattr(seed.settings, "upload_dir", str(tmp_path / "uploads"))
    db = _session()
    db.add(RegistarVozila(gb="37", periodicki_datum=date(2026, 8, 10), periodicki_int=None,
                          taho_datum=date(2025, 3, 1), taho_int=24))
    db.add(RegistarVozila(gb="45", periodicki_datum=date(2026, 9, 1), periodicki_int=6,
                          periodicki_do=date(2026, 12, 24)))   # već upisan → ne dira se
    db.commit()

    seed.popuni_vrijedi_do_v1(db)

    r37 = db.get(RegistarVozila, "37")
    assert r37.periodicki_do == date(2026, 11, 10)   # zadani interval 3 mj. (kao na ekranu)
    assert r37.taho_do == date(2027, 3, 1)
    assert r37.pp_do is None                         # nema datuma → nema roka
    assert db.get(RegistarVozila, "45").periodicki_do == date(2026, 12, 24)
    assert rok_provjere(r37, "periodicki") == date(2026, 11, 10)

    # Zastavica: drugi prolaz ništa ne mijenja (npr. ručno obrisan rok ostaje obrisan)
    r37.periodicki_do = None
    db.commit()
    seed.popuni_vrijedi_do_v1(db)
    assert db.get(RegistarVozila, "37").periodicki_do is None
