"""Test: „Učinak" (plaćanje po učinku) grupira PO POJEDINCU — zajednički posao
(dva imena u zapisu povijesti) podijeli se jednako na sudionike, svaki ima jedan red."""
import os
import sys
from datetime import date
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DATABASE_URL", "sqlite://")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import NormaPosla, PovijestRada, Vozilo
from app.norme import KLJUC_EUR, norm_kat, set_postavka
from app.routers.poslovodja import ucinak


def _session():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng, autoflush=False)()


def test_ucinak_po_pojedincu_dijeli_zajednicki():
    db = _session()
    set_postavka(db, KLJUC_EUR, "12.5")
    db.add(NormaPosla(kategorija=norm_kat("MOTOR"), norma_min=60))
    voz = Vozilo(gb="1", marka="MAN"); db.add(voz); db.flush()
    d = date.today()
    # Solo: Alen 60 min. Zajednički: Alen + Borko 60 min → svakom 30.
    db.add(PovijestRada(vozilo_id=voz.id, datum=d, radnik="Alen", operacija="MOTOR", izvor="nalog"))
    db.add(PovijestRada(vozilo_id=voz.id, datum=d, radnik="Alen, Borko", operacija="MOTOR", izvor="nalog"))
    db.commit()

    out = ucinak(dana=30, db=db, _=None)
    red = {r.radnik: r for r in out.redovi}
    # Svaki pojedinac JEDNOM — nema spojenog reda "Alen, Borko".
    assert set(red) == {"Alen", "Borko"}
    assert red["Alen"].norma_min == 90      # 60 (solo) + 30 (pola zajedničkog)
    assert red["Borko"].norma_min == 30     # pola zajedničkog
    assert red["Alen"].broj_poslova == 2
    assert red["Borko"].broj_poslova == 1
    # 90 min = 1,5 h × 12,5 €/h = 18,75 €
    assert red["Alen"].procijenjena_zarada == 18.75
