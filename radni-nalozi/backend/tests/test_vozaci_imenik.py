"""Test: vozači se vuku iz Flota OS imenika (odjel VOZAČI), živo.

Ne diramo mrežu — napunimo predmemoriju imenika (imenik._kes) pa provjerimo
da vozaci_imena/vozaci_puni uzmu samo odjel VOZAČI, srede razmake i sortiraju."""
import os
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DATABASE_URL", "sqlite://")

from app import imenik


def _napuni_kes():
    imenik._kes = {"ts": time.time(), "podaci": {
        "zapisi": [
            {"id": 1, "odjel": "VOZAČI", "ime": "Ivić Ivo", "opis": "tegljač", "broj": "+385911111111"},
            {"id": 2, "odjel": "RADIONA", "ime": "Majstor Mato", "opis": None, "broj": "+385922222222"},
            {"id": 3, "odjel": "VOZAČI", "ime": "  Anić   Ana ", "opis": None, "broj": "+385933333333"},
            {"id": 4, "odjel": "VOZAČI", "ime": "", "broj": "+385944444444"},  # bez imena → preskoči
        ],
        "odjeli": [], "azurirano": None, "broj": 4,
    }}


def test_vozaci_imena_samo_vozaci_odjel():
    _napuni_kes()
    assert imenik.vozaci_imena() == ["Anić Ana", "Ivić Ivo"]  # bez radione/praznog, sređeni razmaci, sortirano


def test_vozaci_puni_mapiranje():
    _napuni_kes()
    puni = imenik.vozaci_puni()
    assert [p["ime"] for p in puni] == ["Anić Ana", "Ivić Ivo"]
    ivo = next(p for p in puni if p["ime"] == "Ivić Ivo")
    assert ivo["telefon"] == "+385911111111"
    assert ivo["sektor"] == "tegljač"
    assert ivo["aktivan"] is True
    assert ivo["id"] == 1
