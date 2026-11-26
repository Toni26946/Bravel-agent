"""📺 Upute iz videa: link → titlovi → Claude → spremljeno uz zadatak → stranica mehaničara."""
import json
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DATABASE_URL", "sqlite://")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import database, video_upute as vu
from app.database import Base
from app.models import (Korisnik, MehanicarLink, Nalog, Operacija, StatusNaloga, Uloga,
                        VideoUputa, Vozilo, Zadatak)
from app.routers.dispecer import UredjajIn, z_stanje


def _maker():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng, autoflush=False)


def _priprema(db):
    meh = Korisnik(ime="Test Meh", korisnicko_ime="test.meh", lozinka_hash="x", uloga=Uloga.radnik)
    voz = Vozilo(gb="T778", registracija="ZG0000TV", marka="SCANIA", model="R450")
    db.add_all([meh, voz]); db.flush()
    n = Nalog(broj="RN-V-1", vozilo_id=voz.id, naslov="Test", kreirao_id=meh.id, status=StatusNaloga.u_radu)
    db.add(n); db.flush()
    op = Operacija(nalog_id=n.id, kategorija="KOČNICE")
    db.add(op); db.flush()
    z = Zadatak(operacija_id=op.id, opis="Zamjena pločica", ceka_potvrdu=True)
    z.radnici = [meh]
    db.add(z)
    db.add(MehanicarLink(radnik_id=meh.id, token="vtok", aktivan=True))
    db.commit()
    return z


def test_video_id():
    assert vu.video_id("https://www.youtube.com/watch?v=wfnbxDG_sX4&t=30s") == "wfnbxDG_sX4"
    assert vu.video_id("https://youtu.be/wfnbxDG_sX4?si=abc") == "wfnbxDG_sX4"
    assert vu.video_id("https://www.youtube.com/shorts/wfnbxDG_sX4") == "wfnbxDG_sX4"
    assert vu.video_id("https://m.youtube.com/watch?v=wfnbxDG_sX4") == "wfnbxDG_sX4"
    assert vu.video_id("https://vimeo.com/123") is None
    assert vu.video_id("") is None


def test_odaberi_titlove_prednost():
    f = lambda: [{"ext": "vtt", "url": "v"}, {"ext": "json3", "url": "j"}]  # noqa: E731
    # ručni HR ima prednost pred automatskim
    assert vu.odaberi_titlove({"hr": f()}, {"en-orig": f()}) == ("hr", "j", False)
    # automatski izvorni engleski
    assert vu.odaberi_titlove({}, {"en-orig": f(), "de": f(), "hr": f()}, "en")[0] == "en-orig"
    # izvorni ruski → izvorni ruski (ne YouTubeov prijevod na EN — taj vraća 429)
    assert vu.odaberi_titlove({}, {"ru-orig": f(), "en": f()}, "ru")[0] == "ru-orig"
    assert vu.odaberi_titlove({}, {"ru": f(), "en": f()}, "ru")[0] == "ru"
    # nema izvornog → EN prijevod kao zadnja opcija
    assert vu.odaberi_titlove({}, {"en": f()}, None)[0] == "en"
    # nema ništa
    assert vu.odaberi_titlove({}, {}) is None
    # live_chat se ignorira
    assert vu.odaberi_titlove({"live_chat": f()}, {}) is None


def test_parsiraj_i_sazmi():
    j = json.dumps({"events": [
        {"tStartMs": 0, "segs": [{"utf8": "welcome"}, {"utf8": " back"}]},
        {"tStartMs": 3000, "segs": [{"utf8": "\n"}]},
        {"tStartMs": 4000, "segs": [{"utf8": "remove the wheel"}]},
        {"tStartMs": 65000, "segs": [{"utf8": "torque to 600 Nm"}]},
    ]})
    linije = vu.parsiraj_json3(j)
    assert linije[0] == (0.0, "welcome back")
    t = vu.sazmi_transkript(linije)
    assert "[0:00] welcome back remove the wheel" in t
    assert "[1:05] torque to 600 Nm" in t
    vtt = "WEBVTT\n\n00:01:05.000 --> 00:01:07.000\n<c>torque</c> it\n"
    assert vu.parsiraj_vtt(vtt) == [(65.0, "torque it")]


def test_ocisti_upute():
    d = vu.ocisti_upute({
        "naslov": "Zamjena pločica", "koraci": [{"t": "65", "opis": "Skini kotač"}, {"t": 9999, "opis": "Pritegni"}, {"opis": ""}],
        "dijelovi": ["Pločice", {"naziv": "Senzor", "oe": "2 245 316"}], "alat": ["moment ključ", ""],
        "momenti": [{"sto": "vijci kotača", "vrijednost": "600 Nm"}, {"sto": "x"}],
        "upozorenja": ["Podupri vozilo"], "kljucni": [0, 5, "1", 0],
    }, trajanje=750)
    assert [k["t"] for k in d["koraci"]] == [65, 750]
    assert d["dijelovi"][1]["oe"] == "2 245 316" and d["dijelovi"][0]["oe"] is None
    assert d["alat"] == ["moment ključ"]
    assert d["momenti"] == [{"sto": "vijci kotača", "vrijednost": "600 Nm"}]
    assert d["kljucni"] == [0, 1]


def test_ai_odgovor_s_praznim_blokom(monkeypatch):
    """Dio odgovora bez teksta (text=None) ne smije srušiti obradu (živa proba 26.11.)."""
    import types
    blokovi = [types.SimpleNamespace(type="x", text=None),
               types.SimpleNamespace(type="text", text='{"odgovara": true, "koraci": [{"t": 5, "opis": "a"}]}')]

    class Klijent:
        def __init__(self, **_):
            self.messages = types.SimpleNamespace(create=lambda **_: types.SimpleNamespace(content=blokovi))
    import anthropic
    monkeypatch.setattr(anthropic, "Anthropic", Klijent)
    d = vu.ai_upute({"transkript": "[0:00] x", "naslov": "t"}, {"gb": "1"})
    assert d["odgovara"] is True and d["koraci"][0]["t"] == 5


def test_tocka_storyboarda():
    sb = {"rows": 3, "columns": 3, "width": 320, "height": 180,
          "fragments": [{"url": "a", "duration": 90.0}, {"url": "b", "duration": 90.0}, {"url": "c", "duration": 30.0}]}
    assert vu.tocka_storyboarda(sb, 0) == (0, 0)
    assert vu.tocka_storyboarda(sb, 95) == (1, 0)
    assert vu.tocka_storyboarda(sb, 89) == (0, 8)
    assert vu.tocka_storyboarda(sb, 500) == (2, 8)


def test_obradi_i_stranica_mehanicara(monkeypatch):
    maker = _maker()
    db = maker()
    z = _priprema(db)
    u = VideoUputa(zadatak_id=z.id, url="https://youtu.be/wfnbxDG_sX4", video_id="wfnbxDG_sX4", status="obrada")
    db.add(u); db.commit()

    # Dok je u obradi, mehaničar ne vidi ništa
    assert z_stanje("vtok", UredjajIn(uredjaj="A"), db=db)["video"] is None

    monkeypatch.setattr(database, "SessionLocal", maker)
    monkeypatch.setattr(vu.settings, "anthropic_api_key", "test")
    monkeypatch.setattr(vu, "dohvati_video", lambda vid: {
        "naslov": "Changing Brake Pads", "kanal": "K", "trajanje": 750, "jezik": "en-orig",
        "automatski": True, "transkript": "[0:00] x", "storyboard": None})
    viđeno = {}

    def ai(v, voz):
        viđeno.update(voz)
        return vu.ocisti_upute({
        "odgovara": True, "video_vozilo": "Scania R-serija", "razlog": "Ista serija",
        "naslov": "Zamjena pločica", "sazetak": "Pogonska osovina",
        "koraci": [{"t": 60, "opis": "Skini kotač"}, {"t": 300, "opis": "Izvadi pločice"}],
        "dijelovi": [{"naziv": "Kočione pločice"}], "alat": ["udarni odvijač"],
        "momenti": [], "upozorenja": ["Podupri vozilo"], "kljucni": [1]}, 750)
    monkeypatch.setattr(vu, "ai_upute", ai)
    monkeypatch.setattr(vu, "slicice", lambda sb, vremena: {300: "/uploads/yt_x.jpg"})
    vu.obradi(u.id)

    db2 = maker()
    u2 = db2.get(VideoUputa, u.id)
    assert u2.status == "gotovo", u2.greska
    p = json.loads(u2.podaci)
    assert p["koraci"][1]["slika"] == "/uploads/yt_x.jpg"
    assert p["video"]["naslov"] == "Changing Brake Pads"
    assert viđeno["gb"] == "T778" and viđeno["marka_model"] == "SCANIA R450"
    assert p["vozilo"] == "GB T778 · SCANIA R450"
    assert db2.get(Zadatak, z.id).video_status == "gotovo"

    s = z_stanje("vtok", UredjajIn(uredjaj="A"), db=db2)
    assert s["video"]["video_id"] == "wfnbxDG_sX4"
    assert s["video"]["upute"]["alat"] == ["udarni odvijač"]


def test_obradi_greska_se_sprema(monkeypatch):
    maker = _maker()
    db = maker()
    z = _priprema(db)
    u = VideoUputa(zadatak_id=z.id, url="x", video_id="wfnbxDG_sX4", status="obrada")
    db.add(u); db.commit()
    monkeypatch.setattr(database, "SessionLocal", maker)
    monkeypatch.setattr(vu.settings, "anthropic_api_key", "test")

    def puca(vid):
        raise RuntimeError("Video nema titlova")
    monkeypatch.setattr(vu, "dohvati_video", puca)
    vu.obradi(u.id)
    u2 = maker().get(VideoUputa, u.id)
    assert u2.status == "greska" and "titlova" in u2.greska


def _obradi_s(monkeypatch, ai_rezultat, marka="SCANIA", model="R450"):
    maker = _maker()
    db = maker()
    z = _priprema(db)
    voz = z.operacija.nalog.vozilo
    voz.marka, voz.model = marka, model
    u = VideoUputa(zadatak_id=z.id, url="x", video_id="wfnbxDG_sX4", status="obrada")
    db.add(u); db.commit()
    monkeypatch.setattr(database, "SessionLocal", maker)
    monkeypatch.setattr(vu.settings, "anthropic_api_key", "test")
    monkeypatch.setattr(vu, "dohvati_video", lambda vid: {
        "naslov": "MAN TGX brake pads", "kanal": "K", "trajanje": 600, "jezik": "en",
        "automatski": True, "transkript": "[0:00] x", "storyboard": None})
    pozvan = []
    monkeypatch.setattr(vu, "ai_upute", lambda v, voz: pozvan.append(1) or vu.ocisti_upute(ai_rezultat, 600))
    monkeypatch.setattr(vu, "slicice", lambda sb, vremena: {})
    vu.obradi(u.id)
    db2 = maker()
    return db2.get(VideoUputa, u.id), pozvan, db2


def test_video_za_drugi_kamion_se_odbija(monkeypatch):
    """Toni: video mora biti za kamion iz naloga, nikoji drugi — inače ništa."""
    u, _, db2 = _obradi_s(monkeypatch, {
        "odgovara": False, "video_vozilo": "MAN TGX", "razlog": "Druga marka",
        "koraci": [{"t": 1, "opis": "x"}]})
    assert u.status == "greska"
    assert "nije za ovaj kamion" in u.greska and "MAN TGX" in u.greska
    assert u.podaci is None
    assert z_stanje("vtok", UredjajIn(uredjaj="A"), db=db2)["video"] is None


def test_nepoznato_vozilo_bez_uputa(monkeypatch):
    u, pozvan, _ = _obradi_s(monkeypatch, {"odgovara": True, "koraci": [{"t": 1, "opis": "x"}]},
                             marka="TEST", model=None)
    assert u.status == "greska" and "marka i model" in u.greska
    assert pozvan == []   # Claude se ni ne zove


def test_stare_upute_bez_provjere_mehanicar_ne_vidi():
    maker = _maker()
    db = maker()
    z = _priprema(db)
    db.add(VideoUputa(zadatak_id=z.id, url="x", video_id="wfnbxDG_sX4", status="gotovo",
                      podaci=json.dumps({"koraci": [{"t": 1, "opis": "x"}]})))
    db.commit()
    assert z_stanje("vtok", UredjajIn(uredjaj="A"), db=db)["video"] is None


def _trazi_setup(monkeypatch, odgovara_za: set):
    maker = _maker()
    db = maker()
    z = _priprema(db)
    u = VideoUputa(zadatak_id=z.id, url="", video_id="", status="obrada")
    db.add(u); db.commit()
    monkeypatch.setattr(database, "SessionLocal", maker)
    monkeypatch.setattr(vu.settings, "anthropic_api_key", "test")
    viđeni_tekst = []

    def kand(tekst, voz):
        viđeni_tekst.append(tekst)
        return ["aaaaaaaaaaa", "bbbbbbbbbbb"]
    monkeypatch.setattr(vu, "kandidati", kand)
    monkeypatch.setattr(vu, "dohvati_video", lambda vid: {
        "naslov": "Video " + vid, "kanal": "K", "trajanje": 600, "jezik": "en",
        "automatski": True, "transkript": (vid + " ") * 200, "storyboard": None})
    monkeypatch.setattr(vu, "ai_upute", lambda v, voz: vu.ocisti_upute({
        "odgovara": v["transkript"].split()[0] in odgovara_za, "video_vozilo": "x", "razlog": "r",
        "koraci": [{"t": 1, "opis": "korak"}]}, 600))
    monkeypatch.setattr(vu, "slicice", lambda sb, vremena: {})
    vu.obradi(u.id)
    return maker().get(VideoUputa, u.id), viđeni_tekst


def test_nadji_video_uzme_prvi_koji_odgovara(monkeypatch):
    u, tekst = _trazi_setup(monkeypatch, {"bbbbbbbbbbb"})
    assert tekst == ["KOČNICE – Zamjena pločica"]
    assert u.status == "gotovo" and u.video_id == "bbbbbbbbbbb"
    assert u.url == "https://www.youtube.com/watch?v=bbbbbbbbbbb"
    assert json.loads(u.podaci)["odgovara"] is True


def test_nadji_video_nista_ne_odgovara(monkeypatch):
    u, _ = _trazi_setup(monkeypatch, set())
    assert u.status == "greska" and "Nisam našao video" in u.greska
    assert u.podaci is None and u.video_id == "" and u.naslov is None


def test_nadji_preskoci_video_bez_govora(monkeypatch):
    """Titlovi samo „[Music]" → preskoči bez Claude provjere."""
    maker = _maker()
    db = maker()
    z = _priprema(db)
    u = VideoUputa(zadatak_id=z.id, url="", video_id="", status="obrada")
    db.add(u); db.commit()
    monkeypatch.setattr(database, "SessionLocal", maker)
    monkeypatch.setattr(vu.settings, "anthropic_api_key", "test")
    monkeypatch.setattr(vu, "kandidati", lambda t, v: ["glazba00001", "govor000001"])
    monkeypatch.setattr(vu, "dohvati_video", lambda vid: {
        "naslov": vid, "kanal": "K", "trajanje": 600, "jezik": "en", "automatski": True,
        "transkript": "[Music]" if vid.startswith("glazba") else "rijec " * 300, "storyboard": None})
    provjereni = []

    def ai(v, voz):
        provjereni.append(v["naslov"])
        return vu.ocisti_upute({"odgovara": True, "koraci": [{"t": 1, "opis": "k"}]}, 600)
    monkeypatch.setattr(vu, "ai_upute", ai)
    monkeypatch.setattr(vu, "slicice", lambda sb, vremena: {})
    vu.obradi(u.id)
    assert provjereni == ["govor000001"]
    assert maker().get(VideoUputa, u.id).video_id == "govor000001"


def test_kandidati_filtrira_i_rangira(monkeypatch):
    odgovori = iter([{"upiti": ["Scania R brake pads", "Scania R450 pads"]},
                     {"id": ["cccccccccc1", "nepostoji"]}])
    monkeypatch.setattr(vu, "_claude_json", lambda s, t, max_tokens=400: next(odgovori))
    monkeypatch.setattr(vu, "pretrazi_youtube", lambda q, n=8: [
        {"id": "cccccccccc1", "naslov": "Scania R pads", "kanal": "k", "trajanje": 600},
        {"id": "short000001", "naslov": "short", "kanal": "k", "trajanje": 30}])
    assert vu.kandidati("KOČNICE – pločice", {"gb": "1", "marka_model": "SCANIA R450"}) == ["cccccccccc1"]


def test_html_ima_video_dio():
    from app.routers.dispecer import _HTML
    assert "videoHtml(d.video)" in _HTML and "vNaslov" in _HTML
