"""Valjci preko aplikacije: vozila → shema osovina → mjerenje ide na odabranu osovinu →
operacije u nalogu samo za osovine koje nisu dobre."""
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DATABASE_URL", "sqlite://")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Korisnik, Nalog, RegistarVozila, StatusNaloga, Uloga, Vozilo
from app.routers import cartec, valjci
from app.routers.cartec import MjerenjeIn, OdobriIn, PrijavaIn


def _db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng, autoflush=False)()


def _okolina(db):
    vod = Korisnik(ime="Toni", korisnicko_ime="toni", lozinka_hash="x", uloga=Uloga.voditelj)
    db.add(vod)
    db.add_all([RegistarVozila(gb="425", vrsta="TEGLJAČ", tip="TEGLJAČ"),
                RegistarVozila(gb="200", vrsta="ŠLEPA", tip="ŠLEPA"),
                RegistarVozila(gb="77", vrsta="OSTALO", tip="OSTALO")])
    db.commit()
    tok = cartec.prijava_uredjaja(PrijavaIn(naziv="Valjci"), db=db)["token"]
    cartec.odobri_uredjaj(1, OdobriIn(odobren=True), db=db, _=vod)
    return vod, tok


_n = [0]


def _koci(db, tok, l, d, vrsta="radna", osovina_cartec=1):
    _n[0] += 1
    t = datetime.now(timezone.utc) + timedelta(seconds=_n[0])
    return cartec.primi_mjerenje(MjerenjeIn(sesija="x", osovina=osovina_cartec, vrsta=vrsta, vrijeme=t,
                                            sila_lijevo=l, sila_desno=d, otisak=f"otisak{_n[0]:04d}xx"),
                                 x_cartec_token=tok, db=db)


def test_shema_odabir_i_operacije_samo_za_lose():
    db = _db()
    vod, tok = _okolina(db)
    # Tegljač 425 ima otvoren nalog, poluprikolica 200 nema → otvori se novi.
    v425 = Vozilo(gb="425")
    db.add(v425)
    db.flush()
    stari = Nalog(broj="RN-1", vozilo_id=v425.id, naslov="x", kreirao_id=vod.id, status=StatusNaloga.u_radu)
    db.add(stari)
    db.commit()

    s = valjci.nova_sesija(valjci.SesijaIn(kamion_gb="425", prikolica_gb="200"), db=db, k=vod)
    assert [(v["gb"], v["vrsta"], len(v["osovine"])) for v in s["vozila"]] == [
        ("425", "tegljač", 2), ("200", "poluprikolica", 3)]
    assert s["vozila"][0]["nalog"]["id"] == stari.id and s["vozila"][1]["nalog"]["novi"]
    sid = s["id"]

    # 1. osovina tegljača (odabrana sama): dobra; ponovljeno kočenje prepiše.
    _koci(db, tok, 10000, 9000)
    _koci(db, tok, 10600, 10000, osovina_cartec=3)          # Cartecov broj se ne gleda
    # 2. osovina tegljača: radna loša, pa ručna dobra
    valjci.odabir(sid, valjci.OdabirIn(vozilo=0, osovina=2), db=db, k=vod)
    _koci(db, tok, 6000, 4000)
    valjci.odabir(sid, valjci.OdabirIn(vozilo=0, osovina=2, rucna=True), db=db, k=vod)
    _koci(db, tok, 3000, 2900)
    # Poluprikolica: 1. dobra, 2. ručna loša, 3. ne mjeri se
    valjci.odabir(sid, valjci.OdabirIn(vozilo=1, osovina=1), db=db, k=vod)
    _koci(db, tok, 5000, 5000)
    valjci.odabir(sid, valjci.OdabirIn(vozilo=1, osovina=2, rucna=True), db=db, k=vod)
    _koci(db, tok, 3000, 1000)

    st = valjci.sesija(sid, db=db, k=vod)
    o1 = st["vozila"][0]["osovine"][0]["radna"]
    assert (o1["l"], o1["d"], o1["losa"]) == (10600, 10000, False)
    assert st["vozila"][0]["osovine"][1]["radna"]["losa"] and not st["vozila"][0]["osovine"][1]["rucna"]["losa"]

    # Vozilo sišlo, ali 3. osovina poluprikolice nije izmjerena → ne završava samo.
    r = cartec.kraj_testa(cartec.KrajIn(vrijeme=datetime.now(timezone.utc)), x_cartec_token=tok, db=db)
    assert r["zavrseno"] is False

    db.refresh(stari)
    assert stari.valjci is not None            # nalog označen „🛞 valjci"
    kraj = valjci.zavrsi_sesiju(sid, db=db, k=vod)
    assert kraj["zavrsena"] and len(kraj["operacije"]) == 2
    db.refresh(stari)
    assert [o.kategorija for o in stari.operacije] == ["KOČNICE 2. OSOVINA"]
    assert "Radna kočnica: razlika 33 %" in stari.operacije[0].zadaci[0].opis
    novi = db.get(Nalog, kraj["vozila"][1]["nalog"]["id"])
    assert [o.kategorija for o in novi.operacije] == ["KOČNICE 2. OSOVINA"]
    assert novi.operacije[0].zadaci[0].opis.startswith("Ručna kočnica")
    assert novi.plan_rang is not None

    # Nakon završetka mjerenje opet ide starim putem (nerazvrstan test), ne u ovu sesiju.
    r2 = _koci(db, tok, 100, 100)
    assert r2["status"] == "nerazvrstan"


def test_valjci_imaju_svoj_manifest_u_html(tmp_path):
    from app.main import _valjci_index
    idx = tmp_path / "index.html"
    idx.write_text('<head><meta name="theme-color" content="#0d47a1" /><link rel="icon" type="image/svg+xml" href="/icons/icon.svg" />'
                   '<title>Bravel Radni Nalozi</title><link rel="manifest" href="/manifest.webmanifest"></head>', encoding="utf-8")
    html = _valjci_index(idx).body.decode("utf-8")
    assert 'href="/valjci.webmanifest"' in html and "manifest.webmanifest" not in html
    assert "<title>Valjci</title>" in html and "valjci-192.png" in html and "#e65100" in html


def test_pristup_voditelj_ili_modul():
    assert valjci.ima_pristup(Korisnik(uloga=Uloga.voditelj, moduli=None))
    assert not valjci.ima_pristup(Korisnik(uloga=Uloga.radnik, moduli=["/nalozi"]))
    assert valjci.ima_pristup(Korisnik(uloga=Uloga.radnik, moduli=["/valjci"]))


def test_nepoznata_vrsta_pita_broj_osovina():
    db = _db()
    vod, tok = _okolina(db)
    r = valjci.nova_sesija(valjci.SesijaIn(kamion_gb="77"), db=db, k=vod)
    assert r == {"treba_osovine": ["77"]}
    s = valjci.nova_sesija(valjci.SesijaIn(kamion_gb="77", osovine={"77": 4}), db=db, k=vod)
    assert len(s["vozila"][0]["osovine"]) == 4


def test_kraj_zavrsi_kad_je_sve_izmjereno_i_uzivo():
    db = _db()
    vod, tok = _okolina(db)
    s = valjci.nova_sesija(valjci.SesijaIn(kamion_gb="425"), db=db, k=vod)
    cartec.primi_uzivo(cartec.UzivoIn(l=1200, d=900, max_l=3000, max_d=2800, faza="StandardTest"),
                       x_cartec_token=tok, db=db)
    assert valjci.sesija(s["id"], db=db, k=vod)["uzivo"]["max_l"] == 3000
    _koci(db, tok, 5000, 5000)
    valjci.odabir(s["id"], valjci.OdabirIn(vozilo=0, osovina=2), db=db, k=vod)
    _koci(db, tok, 5000, 4900)
    r = cartec.kraj_testa(cartec.KrajIn(vrijeme=datetime.now(timezone.utc)), x_cartec_token=tok, db=db)
    assert r["zavrseno"] is True
    assert valjci.aktivna(db=db, k=vod) is None
