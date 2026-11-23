"""Jednokratni ispravak periodičkih pregleda (WhatsApp #375): Prikolica 171 je u bazi
imala uvezeni 30.06.2026. pa je pokazivala „istekao"; ispravak smije promijeniti samo
stari uvezeni datum, ne ručno upisani."""
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


def _session():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng, autoflush=False)()


def test_ispravlja_samo_stari_uvezeni_datum(tmp_path, monkeypatch):
    monkeypatch.setattr(seed.settings, "upload_dir", str(tmp_path / "uploads"))
    db = _session()
    db.add(RegistarVozila(gb="171", periodicki_datum=date(2026, 6, 30), periodicki_int=3))
    # 174 je netko već ručno ispravio → ne dira se
    db.add(RegistarVozila(gb="174", periodicki_datum=date(2026, 11, 1), periodicki_int=3))
    db.commit()

    seed.ispravi_preglede_v2(db)

    assert db.get(RegistarVozila, "171").periodicki_datum == date(2026, 10, 30)
    assert db.get(RegistarVozila, "174").periodicki_datum == date(2026, 11, 1)
    # Zastavica: drugi prolaz ništa ne mijenja
    db.get(RegistarVozila, "171").periodicki_datum = date(2026, 6, 30)
    db.commit()
    seed.ispravi_preglede_v2(db)
    assert db.get(RegistarVozila, "171").periodicki_datum == date(2026, 6, 30)
