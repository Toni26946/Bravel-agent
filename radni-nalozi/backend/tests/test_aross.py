"""APROSS klijent — offline provjere (bez pravog API-ja):
slaganje baznog URL-a s ključem, račun ukupnog iznosa primke i siguran blok
kad integracija nije povezana."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import aross
from app.config import settings


def test_nije_povezano_dok_nema_kljuca(monkeypatch):
    monkeypatch.setattr(settings, "aross_api_key", "", raising=False)
    monkeypatch.setattr(settings, "aross_user", "", raising=False)
    monkeypatch.setattr(settings, "aross_pass", "", raising=False)
    assert aross.konfigurirano() is False
    with pytest.raises(aross.ArossNijePovezan):
        aross.skladista()


def test_bazni_url_sadrzi_kljuc(monkeypatch):
    monkeypatch.setattr(settings, "aross_base", "https://bravel-api-test.zgdata.hr/api5", raising=False)
    monkeypatch.setattr(settings, "aross_api_key", "TAJNI-KLJUC", raising=False)
    monkeypatch.setattr(settings, "aross_user", "u", raising=False)
    monkeypatch.setattr(settings, "aross_pass", "p", raising=False)
    assert aross.konfigurirano() is True
    assert aross._baza() == "https://bravel-api-test.zgdata.hr/api5/TAJNI-KLJUC"


def test_primka_tijelo_racuna_ukupno(monkeypatch):
    """kreiraj_primku treba zbrojiti stavke u ukupanIznos i popuniti iznos kad fali."""
    poslano = {}

    def fake_post(putanja, tijelo):
        poslano["putanja"] = putanja
        poslano["tijelo"] = tijelo
        return [{"webBrojPrimke": tijelo["brojPrimke"], "erpBrojPrimke": 2476}]

    monkeypatch.setattr(aross, "_post", fake_post)
    aross.kreiraj_primku(
        broj_primke="w11112", sifra_dobavljaca=1050, datum_dokumenta="2026-11-04",
        sifra_skladista=2,
        stavke=[{"sifraArtikla": 6781, "kolicina": 10, "cijena": 2.5}],  # bez iznosa
        napomena="Test",
    )
    t = poslano["tijelo"]
    assert poslano["putanja"] == "/primka/kreiraj"
    assert t["ukupanIznos"] == 25.0
    assert t["stavke"][0]["iznos"] == 25.0
    assert t["stavke"][0]["sifraArtikla"] == 6781
    assert t["napomena"] == "Test"


def test_kreiraj_artikl_izostavi_prazna_polja(monkeypatch):
    poslano = {}
    monkeypatch.setattr(aross, "_post", lambda p, t: poslano.update(putanja=p, tijelo=t) or [])
    aross.kreiraj_artikl(id_artikla=27374, naziv="TEST ARTIKL", jmj="kom")
    t = poslano["tijelo"]
    assert t == {"idArtikla": 27374, "naziv": "TEST ARTIKL", "jmj": "kom"}  # bez katBroj/barkod
