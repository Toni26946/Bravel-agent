"""Povijest vozila (servisna + dijelovi) vidi i poslovođa — Bahal 24.11.2026. dobivao 403."""
import os
import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DATABASE_URL", "sqlite://")

import pytest
from fastapi import HTTPException

from app.models import Uloga
from app.routers.vozila import voditelj_ili_radnik


@pytest.mark.parametrize("uloga", [Uloga.voditelj, Uloga.poslovodja, Uloga.radnik])
def test_povijest_smije(uloga):
    k = SimpleNamespace(uloga=uloga)
    assert voditelj_ili_radnik(korisnik=k) is k


@pytest.mark.parametrize("uloga", [Uloga.vozac, Uloga.skladistar])
def test_povijest_ne_smije(uloga):
    with pytest.raises(HTTPException):
        voditelj_ili_radnik(korisnik=SimpleNamespace(uloga=uloga))
