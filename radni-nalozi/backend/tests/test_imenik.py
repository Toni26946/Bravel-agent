"""Test imenika (samo čitanje iz Flota OS-a): predmemorija, pad Flote, siguran spoj po imenu, pristup.

Brojevi su izmišljeni. Flota se ne zove — `_dohvati_flotu` se podmeće.
"""
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DATABASE_URL", "sqlite://")

from fastapi import HTTPException  # noqa: E402

from app import imenik  # noqa: E402
from app.auth import ima_imenik_pristup, zahtijevaj_imenik_pristup  # noqa: E402
from app.config import settings  # noqa: E402
from app.models import Korisnik, Uloga  # noqa: E402
from app.schemas import KorisnikOut  # noqa: E402

FLOTA = {"zapisi": [
    {"id": 1, "odjel": "RADIONA", "ime": "KOVAČ MARKO", "broj": "+385990000001", "kratki": "2001", "aktivan": True},
    {"id": 2, "odjel": "VOZAČI", "ime": "HORVAT IVAN", "broj": "+385990000002", "kratki": "2002", "aktivan": True},
    {"id": 3, "odjel": "VOZAČI", "ime": "Ivan Horvat", "broj": "+385990000003", "kratki": None, "aktivan": True},
    {"id": 4, "odjel": "URED", "ime": "STARI", "broj": "+385990000004", "kratki": None, "aktivan": False},
], "odjeli": ["DISPONENTI", "URED", "RADIONA", "VOZAČI", "OSTALO"], "azurirano": 1.0}


def _resetiraj(monkeypatch, kljuc="k"):
    monkeypatch.setattr(settings, "imenik_kljuc", kljuc)
    imenik._kes.update({"ts": 0.0, "podaci": None})


def test_predmemorija_i_samo_aktivni(monkeypatch):
    _resetiraj(monkeypatch)
    pozivi = []
    monkeypatch.setattr(imenik, "_dohvati_flotu", lambda: pozivi.append(1) or FLOTA)
    d = imenik.dohvati()
    assert d["broj"] == 3 and d["greska"] is None and not d["zastarjelo"]
    imenik.dohvati()
    assert len(pozivi) == 1                     # drugi poziv iz predmemorije
    imenik.dohvati(osvjezi=True)
    assert len(pozivi) == 2


def test_flota_pala_ne_rusi(monkeypatch):
    _resetiraj(monkeypatch)

    def pada():
        raise RuntimeError("timeout")
    monkeypatch.setattr(imenik, "_dohvati_flotu", pada)
    d = imenik.dohvati()
    assert d["zapisi"] == [] and d["greska"] and d["zastarjelo"]
    # imamo stari dobar odgovor → vrati njega uz poruku
    monkeypatch.setattr(imenik, "_dohvati_flotu", lambda: FLOTA)
    imenik.dohvati(osvjezi=True)
    monkeypatch.setattr(imenik, "_dohvati_flotu", pada)
    d2 = imenik.dohvati(osvjezi=True)
    assert d2["broj"] == 3 and d2["zastarjelo"] and d2["greska"]


def test_bez_kljuca_poruka(monkeypatch):
    _resetiraj(monkeypatch, kljuc="")
    d = imenik.dohvati()
    assert d["zapisi"] == [] and "IMENIK_KLJUC" in d["greska"]


def test_spoj_po_imenu_samo_siguran():
    po = imenik.brojevi_po_imenu([z for z in FLOTA["zapisi"] if z["aktivan"]])
    assert po[imenik.kljuc_imena("Marko Kovac")]["broj"] == "+385990000001"
    assert imenik.kljuc_imena("Horvat Ivan") not in po      # dva broja za isto ime → ne prikazuj


def test_pristup_vlasnik_ili_modul(monkeypatch):
    monkeypatch.setattr(settings, "ai_poslovodja_user", "toni")
    vlasnik = Korisnik(ime="Toni", korisnicko_ime="toni", lozinka_hash="x", uloga=Uloga.voditelj, aktivan=True)
    portal = Korisnik(ime="Portal", korisnicko_ime="portal.voditelj", lozinka_hash="x", uloga=Uloga.voditelj, aktivan=True)
    ured = Korisnik(ime="Ured", korisnicko_ime="ured", lozinka_hash="x", uloga=Uloga.poslovodja, aktivan=True,
                    moduli=["/nalozi", "/imenik"])
    assert ima_imenik_pristup(vlasnik) and ima_imenik_pristup(ured)
    assert not ima_imenik_pristup(portal)                 # voditeljska uloga sama ne daje pristup
    provjera = zahtijevaj_imenik_pristup()
    assert provjera(vlasnik) is vlasnik
    try:
        provjera(portal)
        raise AssertionError("portal-korisnik ne smije vidjeti imenik")
    except HTTPException as e:
        assert e.status_code == 403
    for k, ocek in ((vlasnik, True), (portal, False), (ured, True)):
        k.id, k.prijavljuje_se, k.narucitelj = 1, True, False
        assert KorisnikOut.model_validate(k).imenik is ocek
