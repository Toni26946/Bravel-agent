"""Čitanje otpremnice u POZADINI: start odmah vrati id posla, a stanje se dohvaća
dok AI radi (duga otpremnica inače prekine vezu — „Failed to fetch")."""
import os
import sys
import time
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DATABASE_URL", "sqlite://")

from fastapi import HTTPException

from app.routers import primke
from app.schemas import OtpremnicaZahtjev


def _cekaj(posao_id, sekundi=5):
    kraj = time.time() + sekundi
    while time.time() < kraj:
        p = primke.procitaj_posao(posao_id, _=None)
        if p["status"] != "radi":
            return p
        time.sleep(0.05)
    raise AssertionError("posao nije završio")


def test_pozadinsko_citanje_vrati_rezultat(monkeypatch):
    monkeypatch.setattr(primke, "ai_dostupan", lambda: True)
    monkeypatch.setattr(primke, "_ucitaj_sliku", lambda p: (b"x", "image/jpeg"))

    def sporo_citanje(slike):
        time.sleep(0.2)   # AI radi — start se mora vratiti PRIJE ovoga
        return {"dobavljac": "PREMIUM d.o.o.", "broj_otpremnice": "OT-1", "datum": "16.11.2026",
                "stavke": [{"artikl": "Filter (W712)", "kolicina": 2, "jedinica": "kom", "cijena": 5.5}]}

    monkeypatch.setattr(primke, "parsiraj_otpremnicu", sporo_citanje)
    s = primke.procitaj_start(OtpremnicaZahtjev(fotke=["/uploads/a.jpg"] * 6), _=None)
    assert s["ai"] is True and s["posao_id"]
    assert primke.procitaj_posao(s["posao_id"], _=None)["status"] == "radi"

    p = _cekaj(s["posao_id"])
    assert p["status"] == "gotovo"
    r = p["rezultat"]
    assert r["dobavljac"] == "PREMIUM d.o.o." and r["datum"] == "2026-11-16"
    assert r["stavke"][0]["artikl"] == "Filter (W712)" and r["stavke"][0]["kolicina"] == 2


def test_pozadinsko_citanje_greska(monkeypatch):
    monkeypatch.setattr(primke, "ai_dostupan", lambda: True)
    monkeypatch.setattr(primke, "_ucitaj_sliku", lambda p: (b"x", "image/jpeg"))

    def pukne(slike):
        raise RuntimeError("overloaded")

    monkeypatch.setattr(primke, "parsiraj_otpremnicu", pukne)
    s = primke.procitaj_start(OtpremnicaZahtjev(fotke=["/uploads/a.jpg"]), _=None)
    p = _cekaj(s["posao_id"])
    assert p["status"] == "greska" and "overloaded" in p["greska"]


def test_nepoznat_posao_404():
    with pytest.raises(HTTPException) as e:
        primke.procitaj_posao("nepostoji", _=None)
    assert e.value.status_code == 404


def test_stranica_vraca_dimenzije(monkeypatch, tmp_path):
    """Upload stranice vrati širinu/visinu — ekran po tome upozori na 480×640 s mobitela."""
    import io
    from PIL import Image
    from starlette.datastructures import Headers, UploadFile
    from app.config import settings
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path), raising=False)
    buf = io.BytesIO(); Image.new("RGB", (480, 640), "white").save(buf, format="JPEG"); buf.seek(0)
    up = UploadFile(file=buf, filename="s.jpg", headers=Headers({"content-type": "image/jpeg"}))
    r = primke.stranica(slika=up, _=None)
    assert r.foto.startswith("/uploads/") and (r.sirina, r.visina) == (480, 640)


def test_bez_ai_kljuca(monkeypatch):
    monkeypatch.setattr(primke, "ai_dostupan", lambda: False)
    assert primke.procitaj_start(OtpremnicaZahtjev(fotke=["/uploads/a.jpg"]), _=None) == {"ai": False}
