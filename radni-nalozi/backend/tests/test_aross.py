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


def test_artikli_trazi_po_sifri(monkeypatch):
    """Upis šifre: točna šifra prva (ispred naziva koji samo sadrže te znamenke)."""
    from app.routers import integracije
    mapa = {
        125: {"sifra": 125, "naziv": "ŽARULJA H7", "kataloskiBroj": None},
        1250: {"sifra": 1250, "naziv": "FILTER ZRAKA", "kataloskiBroj": None},
        7: {"sifra": 7, "naziv": "BLATOBRAN 2125x670", "kataloskiBroj": "DK1685"},
    }
    monkeypatch.setattr(integracije, "_artikli_mapa", lambda db, osvjezi=False: mapa)
    monkeypatch.setattr(integracije.aross, "konfigurirano", lambda db=None: True)
    rez = integracije.aross_artikli(q="125", limit=30, db=None, _=None)
    assert [a["sifra"] for a in rez] == [125, 1250, 7]


def test_predlozi_artikl_po_kataloskom_broju():
    from app.routers.integracije import _kat_indeks, predlozi_artikl
    mapa = {
        10: {"sifra": 10, "naziv": "PLOČICE KOČIONE", "kataloskiBroj": "13.0460-2796.2"},
        11: {"sifra": 11, "naziv": "FILTER ULJA", "kataloskiBroj": "W 712/75"},
        12: {"sifra": 12, "naziv": "ŽARULJA A", "kataloskiBroj": "1987302"},
        13: {"sifra": 13, "naziv": "ŽARULJA B", "kataloskiBroj": "1987-302"},   # isti broj, 2 artikla
        14: {"sifra": 14, "naziv": "BEZ BROJA", "kataloskiBroj": None},
    }
    idx = _kat_indeks(mapa)
    assert predlozi_artikl("Disk pločice (13.0460-2796.2)", idx)["sifra"] == 10
    assert predlozi_artikl("Filter ulja W712/75 Mann", idx)["sifra"] == 11
    assert predlozi_artikl("Žarulja (1987302)", idx) is None        # dvosmisleno → ručno
    assert predlozi_artikl("Nešto nepoznato (999999)", idx) is None
    assert predlozi_artikl("", idx) is None


def test_kreiraj_artikl_izostavi_prazna_polja(monkeypatch):
    poslano = {}
    monkeypatch.setattr(aross, "_post", lambda p, t, db=None: poslano.update(putanja=p, tijelo=t) or [])
    aross.kreiraj_artikl(id_artikla=27374, naziv="TEST ARTIKL", jmj="kom")
    t = poslano["tijelo"]
    assert t == {"idArtikla": 27374, "naziv": "TEST ARTIKL", "jmj": "kom"}  # bez katBroj/barkod


def test_razdvoji_naziv_kat():
    from app.routers.integracije import razdvoji_naziv_kat
    assert razdvoji_naziv_kat("Filter goriva (190199)") == ("FILTER GORIVA", "190199")
    assert razdvoji_naziv_kat("SVJETLO REGISTRACIJE AUDI PL DESNO (15-0273-00-9)") == ("SVJETLO REGISTRACIJE AUDI PL DESNO", "15-0273-00-9")
    assert razdvoji_naziv_kat("Brtva bez broja") == ("BRTVA BEZ BROJA", None)


def test_novi_artikli_redom_bez_duplikata(monkeypatch):
    from app.routers import integracije as ig
    postojeci = {100: {"sifra": 100, "naziv": "FILTER", "kataloskiBroj": "EFF005"}}
    monkeypatch.setattr(ig.aross, "konfigurirano", lambda db=None: True)
    monkeypatch.setattr(ig, "_artikli_mapa", lambda db, osvjezi=False: postojeci)
    kreirani = []
    monkeypatch.setattr(ig.aross, "kreiraj_artikl", lambda s, n, j, k, b, db=None: kreirani.append((s, n, k)))
    r = ig.aross_novi_artikli(ig.NoviArtikliIn(stavke=[
        "Filter goriva (EFF005)",          # postoji → ne otvara se
        "Amortizer (A-123456)",            # novi → 101
        "Amortizer drugi put (A-123456)",  # isti kat. broj → isti novi artikl, ne duplikat
        "Brtva (999-777)",                 # novi → 102
    ]), db=None, _=None)
    sifre = [a["sifra"] for a in r["artikli"]]
    assert sifre == [100, 101, 101, 102]
    assert [k[0] for k in kreirani] == [101, 102]


def test_sljedeca_sifra_preskace_posebne():
    from app.routers.integracije import sljedeca_sifra
    mapa = {27373: {}, 27374: {}, 200000: {}, 200003: {}, 200004: {}}
    assert sljedeca_sifra(mapa) == 27375


def test_ne_spaja_po_viskoznosti_i_brojevima_iz_naziva():
    """Primka FRENUM 17.11.2026.: „10W40 Total Quartz 7000 (TOTAL711)" spojila se s
    TEROSON BRTVILO (kat. 7000), a „5W30 Total…" s 5W30 ELF (kat. 5W-30)."""
    from app.routers.integracije import _kat_indeks, predlozi_artikl
    mapa = {
        1: {"sifra": 1, "naziv": "TEROSON BRTVILO", "kataloskiBroj": "7000"},
        2: {"sifra": 2, "naziv": "5W30 ELF", "kataloskiBroj": "5W-30"},
        3: {"sifra": 3, "naziv": "ULJE DIFERENCIJALA", "kataloskiBroj": "75W90"},
        4: {"sifra": 4, "naziv": "SEMERING 27X47X7", "kataloskiBroj": "81-35552-00"},
    }
    idx = _kat_indeks(mapa)
    assert predlozi_artikl("10W40 Total Quartz 7000 (1L) (TOTAL711)", idx) is None
    assert predlozi_artikl("5W30 Total Quartz Ineo RCP (1L) (TOT231130)", idx) is None
    assert predlozi_artikl("75W90 Pemco iPoid 595 GI-5 (1L) (PM0595-1)", idx) is None
    assert predlozi_artikl("Semering 27X47X7 (81-35552-00)", idx)["sifra"] == 4


def test_odbijen_dokument_digne_gresku():
    """Apross odbijenu primku vraća kao HTTP 200 s [{"result": "Error", "message": …}] —
    prije se tiho gutalo pa korisnik nije znao da primka nije prošla (test 20.11.2026.)."""
    import httpx
    r = httpx.Response(200, json=[{"result": "Error", "message": "Primka 6409-03-261 je već zaprimljena."}])
    with pytest.raises(aross.ArossGreska, match="već zaprimljena"):
        aross._json(r)
    ok = httpx.Response(200, json=[{"webBrojPrimke": "X", "erpBrojPrimke": 2480}])
    assert aross._json(ok)[0]["erpBrojPrimke"] == 2480


def test_dupla_otpremnica_odbijena_osim_svjesno():
    import os
    os.environ.setdefault("DATABASE_URL", "sqlite://")
    from fastapi import HTTPException
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.database import Base
    from app.models import Korisnik, Uloga
    from app.routers.primke import kreiraj
    from app.schemas import PrimkaCreate
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    db = sessionmaker(bind=eng, autoflush=False)()
    k = Korisnik(ime="Sk", korisnicko_ime="sk", lozinka_hash="x", uloga=Uloga.skladistar)
    db.add(k); db.commit()
    kreiraj(PrimkaCreate(dobavljac="FRENUM", broj_otpremnice="6409-03-261"), korisnik=k, db=db)
    with pytest.raises(HTTPException) as e:
        kreiraj(PrimkaCreate(dobavljac="Frenum", broj_otpremnice="6409 03 261"), korisnik=k, db=db)
    assert e.value.status_code == 409 and "već upisana" in e.value.detail
    p = kreiraj(PrimkaCreate(dobavljac="Frenum", broj_otpremnice="6409-03-261", dupli=True), korisnik=k, db=db)
    assert p.id
