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


def test_samo_kljuc_bez_basic_je_dovoljno(monkeypatch):
    """Basic Auth je opcionalan — samo API-KEY je dovoljan (ZGData ga dodaje kasnije)."""
    monkeypatch.setattr(settings, "aross_api_key", "KLJUC", raising=False)
    monkeypatch.setattr(settings, "aross_user", "", raising=False)
    monkeypatch.setattr(settings, "aross_pass", "", raising=False)
    assert aross.konfigurirano() is True
    with aross._client() as c:   # ne diže ArossNijePovezan iako nema Basic Auth
        assert c is not None


def test_primka_tijelo_racuna_ukupno(monkeypatch):
    """kreiraj_primku treba zbrojiti stavke u ukupanIznos i popuniti iznos kad fali."""
    poslano = {}

    def fake_post(putanja, tijelo, db=None):
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


def test_izdatnica_tijelo_zbraja_iste_artikle(monkeypatch):
    poslano = {}

    def fake_post(putanja, tijelo, db=None):
        poslano.update(putanja=putanja, tijelo=tijelo)
        return [{"webBrojIzdatnice": tijelo["brojIzdatnice"], "erpBrojIzdatnice": 2029, "erpMjestoTroska": "457 - VOLVO"}]

    monkeypatch.setattr(aross, "_post", fake_post)
    rez = aross.kreiraj_izdatnicu("N5-1", "2026-11-16", 2, 457,
                                  [{"sifraArtikla": 6781, "kolicina": 2}, {"sifraArtikla": 6781, "kolicina": 1.5},
                                   {"sifraArtikla": 10, "kolicina": 1}], napomena="Nalog 5")
    t = poslano["tijelo"]
    assert poslano["putanja"] == "/izdatnica/kreiraj"
    assert t["sifraMjestaTroska"] == 457 and t["sifraSkladista"] == 2
    assert {s["sifraArtikla"]: s["kolicina"] for s in t["stavke"]} == {6781: 3.5, 10: 1.0}
    assert t["napomena"] == "Nalog 5"
    assert rez[0]["erpBrojIzdatnice"] == 2029


def test_mjesto_troska_prepozna_registraciju():
    from app.routers.integracije import _mt_registracije, _reg_norm
    assert _reg_norm("zg-3495 fr") == "ZG3495FR"
    assert _mt_registracije("ZG-4732-HC (prije DA681EC)") == {"ZG4732HC", "DA681EC"}
    assert _mt_registracije("ZG-1467-FR") == {"ZG1467FR"}
    # Pravi (neuredni) nazivi iz Aprossa
    assert _mt_registracije(" Prikolica   ZG1239HJ (stara ZG-8284-FC)") == {"ZG1239HJ", "ZG8284FC"}
    assert _mt_registracije("ZG5182HC( prijeDA-264-DB)") == {"ZG5182HC", "DA264DB"}
    assert _mt_registracije(" Prikolica ZG-2012-EZ W09000335E0R23391") == {"ZG2012EZ"}
    assert _mt_registracije("ZG-8714-GM (prije DA-658-DN, bio DA-920 CZ)") == {"ZG8714GM", "DA658DN", "DA920CZ"}


def test_mjesto_troska_po_gb():
    """Šifra mjesta troška u Aprossu JE garažni broj — registracija se ne gleda."""
    from app.routers.integracije import _mjesto_po_gb
    mjesta = [{"sifra": 37, "naziv": "ZG9464KR"}, {"sifra": 79, "naziv": " Prikolica ZG-7234-FE"}]
    assert _mjesto_po_gb("37", mjesta)["naziv"] == "ZG9464KR"
    assert _mjesto_po_gb("079", mjesta)["sifra"] == 79
    assert _mjesto_po_gb("467", mjesta) is None
    assert _mjesto_po_gb("TEST", mjesta) is None


def test_odabir_mjesta_troska_prednost_trenutnoj_reg():
    from app.routers.integracije import _odaberi_mjesto_troska
    mjesta = [
        {"sifra": 1, "naziv": "ZG-3168-HD * PRODAN"},
        {"sifra": 2, "naziv": "ZG5324KM bio ZG-3168-HD (bio DA-267-DB)"},
        {"sifra": 3, "naziv": " Prikolica ZG-7234-FE"},
        {"sifra": 4, "naziv": "ZG7234HF (stara ZG-4339-GH) VW Transporter 9s"},
    ]
    assert _odaberi_mjesto_troska({"ZG7234FE"}, mjesta)["sifra"] == 3
    assert _odaberi_mjesto_troska({"ZG5324KM"}, mjesta)["sifra"] == 2
    assert _odaberi_mjesto_troska({"ZG3168HD"}, mjesta)["sifra"] == 2   # aktivno vozilo ispred prodanog
    assert _odaberi_mjesto_troska({"ZG0000XX"}, mjesta) is None


def test_kreiraj_artikl_izostavi_prazna_polja(monkeypatch):
    poslano = {}
    monkeypatch.setattr(aross, "_post", lambda p, t, db=None: poslano.update(putanja=p, tijelo=t) or [])
    aross.kreiraj_artikl(id_artikla=27374, naziv="TEST ARTIKL", jmj="kom")
    t = poslano["tijelo"]
    assert t == {"idArtikla": 27374, "naziv": "TEST ARTIKL", "jmj": "kom"}  # bez katBroj/barkod
