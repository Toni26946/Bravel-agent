"""Dispečer zadataka mehaničaru — login-less poveznica (za WhatsApp).

Vlasnik (AI Poslovođa) generira/gasi poveznicu po mehaničaru; mehaničar je
otvori na mobitelu BEZ prijave i radi sa 3 gumba (Počinjem / Gotovo /
Nemam dijelova). Stranica pokazuje SAMO vozilo, opis i cijenu po normi.

Sigurnost:
- tajni `token` u poveznici (vrijedi samo za njegove zadatke),
- veže se na PRVI uređaj koji je otvori; drugi uređaj → „nije za tebe" + revizija,
- `aktivan` → voditelj jednim klikom ugasi sve poveznice mehaničara,
- bilježi se zadnje korištenje (kad / s kojeg uređaja).

Slanje WhatsApp poruke je POSEBNO i gateano (vidi dispecer_slanje / whatsapp.py) —
ovdje se NIŠTA ne šalje; ovo je samo stranica + akcije.
"""
import logging
import re
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import norme
from ..auth import zahtijevaj_plan_pristup, zahtijevaj_uloge
from ..database import get_db
from ..models import Korisnik, MehanicarLink, Nalog, NormaPosla, Operacija, StatusNaloga, Uloga, Vozilo, Zadatak
from ..push import obavijesti_korisnika, obavijesti_ulogu
from .nalozi import _auto_status_naloga, _pokreni_mjerac, _zatvori_kao_nije_gotovo, _zaustavi_mjerac, nalog_eager
from .plan import _AKTIVNI, _SKRIVENI_GB, _gb, _plan_status

log = logging.getLogger("dispecer")
router = APIRouter(prefix="/dispecer", tags=["dispecer"])
page_router = APIRouter()
_samo_vlasnik = zahtijevaj_plan_pristup()   # vlasnik ILI tko ima modul '/plan'
_skladiste = zahtijevaj_uloge(Uloga.skladistar, Uloga.voditelj, Uloga.poslovodja)


def _izvuci_dio(opis: str | None) -> str | None:
    """Izvuci naziv naručenog dijela iz opisa (upisao mehaničar: '[naručen dio: …]')."""
    m = re.search(r"\[naručen dio:\s*(.*?)\]", opis or "")
    return m.group(1).strip() if m else None


def osiguraj_link(db: Session, radnik_id: int) -> MehanicarLink:
    """Dohvati aktivnu poveznicu mehaničara ili je stvori (bez diranja vezanog uređaja
    ako već postoji aktivna). Koristi se pri slanju iz Plana."""
    link = db.query(MehanicarLink).filter(MehanicarLink.radnik_id == radnik_id).first()
    if link and link.aktivan:
        return link
    token = secrets.token_urlsafe(24)
    if link:
        link.token = token
        link.aktivan = True
        link.uredjaj = None
        link.zadnje_koristeno = None
        link.zadnji_uredjaj = None
    else:
        link = MehanicarLink(radnik_id=radnik_id, token=token, aktivan=True)
        db.add(link)
    db.flush()
    return link


def posalji_poveznicu(db: Session, radnik: Korisnik, gb: str, opis: str, base_url: str,
                      poruka_override: str | None = None, link_suffix: str = "") -> dict:
    """Pošalji login-less poveznicu mehaničaru preko bravel-agenta (predložak
    `poruka_dispecera`). GATED — ništa se ne šalje osim ako je izričito upaljeno:
    - `dispecer_wa_on` mora biti True i bravel-agent URL/ključ postavljeni,
    - ako je `dispecer_test_broj` postavljen → SVE ide samo na taj broj (test),
    - inače se broj mehaničara povlači iz IMENIKA (Flota OS = izvor istine) po
      imenu; bez broja u imeniku → ne šalje se. `dispecer_wa_imena` (ako je
      postavljena) dodatno ograničava slanje na navedena imena (kill-switch za test).
    `poruka_override` (s {url}) i `link_suffix` (npr. "?kraj=1") za posebne poruke
    (kraj smjene). Nikad ne prekida tok dodjele — na grešci vrati {poslano:False}.
    """
    from ..config import settings
    if not (settings.dispecer_wa_on and settings.bravel_agent_url and settings.bravel_agent_kljuc):
        return {"poslano": False, "razlog": "slanje isključeno"}
    link = osiguraj_link(db, radnik.id)
    url = f"{base_url.rstrip('/')}/z/{link.token}{link_suffix}"
    # Meta pravilo: parametar predloška bez novih redova/tabova
    sadrzaj = poruka_override.format(url=url) if poruka_override else f"Novi zadatak: GB {gb}, {opis} {url}"
    poruka = " ".join(sadrzaj.split())[:900]
    test = (settings.dispecer_test_broj or "").strip()
    body = {"poruka": poruka}
    if test:
        body["vozac"] = "test"
        body["broj"] = test
    else:
        # (opcionalno) kill-switch imena za vrijeme testa; prazno = svi mehaničari iz imenika
        imena = {x.strip().lower() for x in (settings.dispecer_wa_imena or "").split(",") if x.strip()}
        if imena and (radnik.ime or "").strip().lower() not in imena:
            return {"poslano": False, "razlog": "mehaničar nije na allowlisti"}
        # Broj iz IMENIKA (Flota OS) po imenu — samo imena s jednim jednoznačnim brojem.
        from .. import imenik
        zapis = imenik.brojevi_po_imenu((imenik.dohvati().get("zapisi")) or []).get(imenik.kljuc_imena(radnik.ime))
        if not zapis or not zapis.get("broj"):
            return {"poslano": False, "razlog": "mehaničar nema broj u imeniku"}
        body["vozac"] = radnik.ime
        body["broj"] = zapis["broj"]
    try:
        import httpx
        r = httpx.post(
            f"{settings.bravel_agent_url.rstrip('/')}/api/vozac/nalog",
            json=body, headers={"X-Api-Key": settings.bravel_agent_kljuc}, timeout=10,
        )
        ok = False
        try:
            ok = r.status_code < 300 and bool(r.json().get("ok"))
        except Exception:
            ok = False
        if not ok:
            log.warning("Dispečer slanje nije uspjelo (%s): %s", r.status_code, r.text[:200])
        return {"poslano": ok}
    except Exception as e:  # mreža/konfiguracija — ne ruši dodjelu
        log.warning("Dispečer slanje iznimka: %s", e)
        return {"poslano": False, "razlog": str(e)}


# --- pomoćno ---------------------------------------------------------------
def _link(db: Session, token: str) -> MehanicarLink | None:
    return (
        db.query(MehanicarLink)
        .filter(MehanicarLink.token == token, MehanicarLink.aktivan.is_(True))
        .first()
    )


def _provjeri_uredjaj(db: Session, link: MehanicarLink, uredjaj: str) -> None:
    """Veži poveznicu na prvi uređaj; odbij tuđi (+ revizija i obavijest voditelju)."""
    uredjaj = (uredjaj or "").strip()[:80]
    if not uredjaj:
        raise HTTPException(status_code=400, detail="Nedostaje oznaka uređaja")
    if link.uredjaj is None:
        link.uredjaj = uredjaj  # prvi uređaj preuzima poveznicu
    elif link.uredjaj != uredjaj:
        link.zadnji_uredjaj = uredjaj
        obavijesti_ulogu(
            db, Uloga.voditelj, "Poveznica s tuđeg uređaja",
            f"{link.radnik.ime}: pokušaj otvaranja s drugog uređaja", url="/plan",
        )
        db.commit()
        raise HTTPException(status_code=403, detail="Ova poveznica nije za tebe")
    link.zadnje_koristeno = datetime.now(timezone.utc)
    link.zadnji_uredjaj = uredjaj


def _red(db: Session, radnik: Korisnik) -> list[tuple[Nalog, object, Zadatak]]:
    """Mehaničarev red nezavršenih zadataka, po redoslijedu iz plana.
    Preskače zadatke koji čekaju dijelove (nisu spremni za rad)."""
    out = []
    # Eager-load (vozilo, operacije→zadaci→radnici/vremena) — bez ovoga je na Postgresu
    # svaki pristup lazy vezi novi upit (N+1), pa akcija mehaničara zna zapeti par sekundi.
    for n in db.query(Nalog).options(*nalog_eager()).filter(Nalog.status.in_(_AKTIVNI)).all():
        if _gb(n) in _SKRIVENI_GB:
            continue
        for op in n.operacije:
            for z in op.zadaci:
                if z.gotovo or z.razlog_prekida == "dijelovi":
                    continue
                if not any(r.id == radnik.id for r in z.radnici):
                    continue
                out.append((n, op, z))

    def kljuc(t):
        n, op, z = t
        rang = n.plan_rang if n.plan_rang is not None else 9999
        # 0 = u tijeku (uvijek prvi), 1 = HITNO, 2 = ostalo. Unutar „ostalog" vrijedi
        # RUČNI red po mehaničaru (red_ruc, slaže se dragom u dashboardu); čeka-potvrdu i
        # rang su samo tiebreak za zadatke bez ručnog reda. Mehaničar ne vidi da je hitno.
        if z.zapoceto:
            faza = 0
        elif n.plan_hitno:
            faza = 1
        else:
            faza = 2
        rr = z.red_ruc if z.red_ruc is not None else 10 ** 6
        cp = 0 if z.ceka_potvrdu else 1
        return (faza, rr, cp, rang, op.redoslijed or 0, z.id)

    out.sort(key=kljuc)
    return out


def _cijena(db: Session, kategorija: str | None) -> dict | None:
    kat = norme.norm_kat(kategorija)
    if not kat:
        return None
    nm = db.query(NormaPosla).filter(NormaPosla.kategorija == kat).first()
    if not nm or not nm.norma_min:
        return None
    try:
        eur = float(norme.get_postavka(db, norme.KLJUC_EUR) or 0)
    except (TypeError, ValueError):
        eur = 0.0
    iznos = round(nm.norma_min * eur / 60.0, 2) if eur > 0 else None
    return {"norma_min": nm.norma_min, "eur": iznos}


def _stanje(db: Session, radnik: Korisnik) -> dict:
    red = _red(db, radnik)
    if not red:
        return {"nema": True, "ime": radnik.ime}
    n, op, z = red[0]
    voz = n.vozilo
    vozilo = " ".join(x for x in [(voz.marka if voz else None), (voz.model if voz else None)] if x)
    return {
        "ime": radnik.ime,
        "zadatak_id": z.id,
        "gb": _gb(n),
        "vozilo": vozilo or (n.naslov or ""),
        "reg": (voz.registracija if voz else "") or "",
        "opis": z.opis,
        "kategorija": op.kategorija,
        "cijena": _cijena(db, op.kategorija),
        "stanje": _plan_status(z),   # ceka | radu | pauza | plan
        "preostalo": max(0, len(red) - 1),
    }


def provjeri_zalihu(db: Session, radnik: Korisnik) -> None:
    """Zaliha zadataka 'u pripremi' po mehaničaru: čim krene raditi zadatak iz
    pripreme i ostane manje od `dispecer_zaliha` nezapočetih u redu → obavijest
    poslovođi (voditelju) da dopuni. Zove se pri startu zadatka."""
    from ..config import settings
    prag = max(0, settings.dispecer_zaliha)
    if prag <= 0:
        return
    cekaju = sum(1 for (_n, _op, z) in _red(db, radnik) if z.zapoceto is None)
    if cekaju < prag:
        obavijesti_ulogu(
            db, Uloga.voditelj, "Dopuni zadatke",
            f"{radnik.ime}: još {cekaju} u redu — dodijeli mu zadatke", url="/plan",
        )


# --- mehaničar: token akcije (BEZ prijave) ---------------------------------
class UredjajIn(BaseModel):
    uredjaj: str


class DijeloviIn(BaseModel):
    uredjaj: str
    naziv: str | None = None


def _ucitaj(db: Session, token: str, uredjaj: str) -> MehanicarLink:
    link = _link(db, token)
    if not link:
        raise HTTPException(status_code=404, detail="Poveznica ne vrijedi ili je ugašena")
    _provjeri_uredjaj(db, link, uredjaj)
    return link


@router.post("/z/{token}/stanje")
def z_stanje(token: str, p: UredjajIn, db: Session = Depends(get_db)):
    link = _ucitaj(db, token, p.uredjaj)
    rez = _stanje(db, link.radnik)
    db.commit()
    return rez


@router.post("/z/{token}/pocinjem")
def z_pocinjem(token: str, p: UredjajIn, db: Session = Depends(get_db)):
    link = _ucitaj(db, token, p.uredjaj)
    red = _red(db, link.radnik)
    if not red:
        db.commit()
        return {"nema": True, "ime": link.radnik.ime}
    z = red[0][2]
    z.ceka_potvrdu = False
    z.razlog_prekida = None
    z.prekid_vrijeme = None
    _pokreni_mjerac(db, z, odjavi_druge=False)   # zadrži ostale zadatke u redu čekanja
    db.flush()
    _auto_status_naloga(db, z.operacija.nalog, link.radnik)
    provjeri_zalihu(db, link.radnik)   # krenuo iz pripreme → javi poslovođi ako je zaliha niska
    db.commit()
    return _stanje(db, link.radnik)


def _pripremi_sljedeci(db: Session, radnik: Korisnik) -> None:
    """Nakon što mehaničar zatvori zadatak (Gotovo / Nemam dijelova), sljedeći iz
    reda označi 'čeka potvrdu' da se odmah pokaže na ISTOJ stranici (animacija
    'Stigao novi zadatak'). NE šalje se nova WhatsApp poruka — dovoljan je prvi
    link; mehaničar preko njega vidi kamo dalje."""
    red = _red(db, radnik)
    if not red:
        return
    nz = red[0][2]
    if not nz.zapoceto:              # već radi → ne diraj (nije u 'čeka potvrdu')
        nz.ceka_potvrdu = True
    db.commit()


@router.post("/z/{token}/gotovo")
def z_gotovo(token: str, p: UredjajIn, request: Request, db: Session = Depends(get_db)):
    link = _ucitaj(db, token, p.uredjaj)
    red = _red(db, link.radnik)
    if not red:
        db.commit()
        return {"nema": True, "ime": link.radnik.ime}
    z = red[0][2]
    _zaustavi_mjerac(z)
    z.ceka_potvrdu = False
    z.gotovo = True
    z.zavrseno = datetime.now(timezone.utc)
    z.razlog_prekida = None
    z.prekid_vrijeme = None
    db.flush()
    _auto_status_naloga(db, z.operacija.nalog, link.radnik)
    db.commit()
    _pripremi_sljedeci(db, link.radnik)   # sljedeći se pokaže na istoj stranici (bez nove WA poruke)
    return _stanje(db, link.radnik)   # sljedeći zadatak ili {nema:True}


@router.post("/z/{token}/dijelovi")
def z_dijelovi(token: str, p: DijeloviIn, request: Request, db: Session = Depends(get_db)):
    link = _ucitaj(db, token, p.uredjaj)
    red = _red(db, link.radnik)
    if not red:
        db.commit()
        return {"nema": True, "ime": link.radnik.ime}
    z = red[0][2]
    _zaustavi_mjerac(z)
    z.ceka_potvrdu = False
    z.razlog_prekida = "dijelovi"
    z.prekid_vrijeme = None
    naziv = (p.naziv or "").strip()[:200]
    # Zahtjev skladištu (dio 3b — skladištarev prozorčić „Pridruži operaciji") dolazi
    # u sljedećem koraku; zasad bilježimo naziv dijela kao napomenu zadatka.
    if naziv:
        dodatak = f"[naručen dio: {naziv}]"
        z.opis = f"{z.opis} {dodatak}" if z.opis and dodatak not in (z.opis or "") else (z.opis or dodatak)
    db.flush()
    _auto_status_naloga(db, z.operacija.nalog, link.radnik)
    # Obavijesti skladište: za ovu operaciju nedostaju dijelovi (kartica na /skladiste).
    nlg = z.operacija.nalog
    obavijesti_ulogu(
        db, Uloga.skladistar, "Nedostaju dijelovi",
        f"GB {_gb(nlg)} · {naziv or z.opis or ''}".strip(" ·"), url="/skladiste",
    )
    db.commit()
    _pripremi_sljedeci(db, link.radnik)   # sljedeći se pokaže na istoj stranici (bez nove WA poruke)
    return _stanje(db, link.radnik)


@router.post("/z/{token}/nije-gotovo")
def z_nije_gotovo(token: str, p: UredjajIn, db: Session = Depends(get_db)):
    """PROMJENA PLANA tijekom dana: trenutni zadatak NIJE gotov → pauziraj ga
    (zaustavi mjerač, čuva vrijeme, ostaje u redu) i prebaci mehaničara na SLJEDEĆI
    zadatak (pokaže se na istoj stranici). Ako nema sljedećeg, samo parkira.
    (Prekid pred kraj smjene ide kroz zasebni prompt — tamo mehaničar staje.)"""
    link = _ucitaj(db, token, p.uredjaj)
    red = _red(db, link.radnik)
    if not red:
        db.commit()
        return {"nema": True, "ime": link.radnik.ime}
    z = red[0][2]
    _zatvori_kao_nije_gotovo(z)    # zabilježi vrijeme i zaustavi (ostaje u pauzi)
    db.flush()
    _auto_status_naloga(db, z.operacija.nalog, link.radnik)
    # Sljedeći = prvi iz reda koji NIJE upravo pauzirani; označi 'čeka potvrdu' da
    # iskoči ispred pauziranog i pokaže se na stranici (animacija).
    preostali = [t for t in _red(db, link.radnik) if t[2].id != z.id]
    if preostali:
        nz = preostali[0][2]
        if not nz.zapoceto:
            nz.ceka_potvrdu = True
        db.commit()
        return _stanje(db, link.radnik)
    db.commit()
    return {"parkirano": True, "ime": link.radnik.ime}


class SmjenaIn(BaseModel):
    uredjaj: str
    odgovor: str   # "ostajem" | "gotov"


@router.post("/z/{token}/smjena")
def z_smjena(token: str, p: SmjenaIn, db: Session = Depends(get_db)):
    """Odgovor mehaničara na pitanje kraja smjene (link ?kraj=1):
    - "ostajem": nastavlja raditi → zabilježi odgovor, ne dira zadatke;
    - "gotov": gotov za danas → svi njegovi pokrenuti zadaci idu u 'Nije gotovo'
      (pauza, čuvaju vrijeme). NE označava gotovim, NE šalje sljedeći."""
    link = _ucitaj(db, token, p.uredjaj)
    odgovor = (p.odgovor or "").strip().lower()
    if odgovor not in ("ostajem", "gotov"):
        raise HTTPException(status_code=400, detail="Nepoznat odgovor (ostajem/gotov)")
    link.smjena_pitano = link.smjena_pitano or datetime.now(timezone.utc)
    link.smjena_odgovor = odgovor
    if odgovor == "ostajem":
        db.commit()
        return _stanje(db, link.radnik)
    # "gotov za danas" → zatvori sve pokrenute (a i preostale u redu) kao nedovršene
    zatvoreno = 0
    for (_n, _op, z) in _red(db, link.radnik):
        if z.zapoceto or (z.utroseno_sek or 0) > 0:
            _zatvori_kao_nije_gotovo(z)
            _auto_status_naloga(db, z.operacija.nalog, link.radnik)
            zatvoreno += 1
    db.commit()
    return {"parkirano": True, "gotov_za_danas": True, "ime": link.radnik.ime, "zatvoreno": zatvoreno}


# --- vlasnik: upravljanje poveznicama --------------------------------------
def _url_za(request: Request, token: str) -> str:
    base = str(request.base_url).rstrip("/")
    return f"{base}/z/{token}"


@router.get("/linkovi")
def linkovi(_: Korisnik = Depends(_samo_vlasnik), db: Session = Depends(get_db)):
    """Popis mehaničara (serviseri) sa stanjem poveznice — za upravljanje."""
    radnici = (
        db.query(Korisnik)
        .filter(Korisnik.uloga == Uloga.radnik, Korisnik.aktivan.is_(True),
                Korisnik.prijavljuje_se.is_(True))
        .order_by(Korisnik.ime).all()
    )
    po_radniku = {l.radnik_id: l for l in db.query(MehanicarLink).all()}
    out = []
    for r in radnici:
        l = po_radniku.get(r.id)
        out.append({
            "radnik_id": r.id, "ime": r.ime,
            "ima_link": bool(l and l.aktivan),
            "vezan_uredjaj": bool(l and l.uredjaj),
            "zadnje": l.zadnje_koristeno.isoformat() if (l and l.zadnje_koristeno) else None,
        })
    return out


@router.post("/link/{radnik_id}")
def napravi_link(radnik_id: int, request: Request,
                 _: Korisnik = Depends(_samo_vlasnik), db: Session = Depends(get_db)):
    """Napravi (ili izda novu) poveznicu za mehaničara. Nova poveznica poništava staru
    i odvezuje uređaj (iduća prijava na prvi uređaj koji otvori)."""
    r = db.get(Korisnik, radnik_id)
    if not r:
        raise HTTPException(status_code=404, detail="Radnik ne postoji")
    token = secrets.token_urlsafe(24)
    link = db.query(MehanicarLink).filter(MehanicarLink.radnik_id == radnik_id).first()
    if link:
        link.token = token
        link.uredjaj = None
        link.aktivan = True
        link.zadnje_koristeno = None
        link.zadnji_uredjaj = None
    else:
        db.add(MehanicarLink(radnik_id=radnik_id, token=token, aktivan=True))
    db.commit()
    return {"ok": True, "radnik_id": radnik_id, "token": token, "url": _url_za(request, token)}


@router.post("/test-posalji")
def test_posalji(_: Korisnik = Depends(_samo_vlasnik), db: Session = Depends(get_db)):
    """Pošalji PROBNU dispečersku poruku — SAMO na `dispecer_test_broj` (vlasnik).
    Čisti tekst, BEZ poveznice i BEZ ijednog mehaničarevog reda — tako pritisak
    na gumbe ne može dirnuti pravi zadatak. Odbija ako test broj nije postavljen."""
    from ..config import settings
    broj = (settings.dispecer_test_broj or "").strip()
    if not broj:
        raise HTTPException(status_code=400,
                            detail="dispecer_test_broj nije postavljen — probna poruka se ne šalje")
    if not (settings.dispecer_wa_on and settings.bravel_agent_url and settings.bravel_agent_kljuc):
        return {"ok": False, "razlog": "slanje isključeno (dispecer_wa_on / url / ključ)"}
    poruka = "✅ Probna poruka dispečera — veza radi. (test, bez zadatka)"
    try:
        import httpx
        r = httpx.post(
            f"{settings.bravel_agent_url.rstrip('/')}/api/vozac/nalog",
            json={"poruka": poruka, "vozac": "test", "broj": broj},
            headers={"X-Api-Key": settings.bravel_agent_kljuc}, timeout=10,
        )
        ok = r.status_code < 300 and bool(r.json().get("ok"))
        return {"ok": ok, "broj": broj, "status": r.status_code}
    except Exception as e:  # mreža/konfiguracija
        return {"ok": False, "razlog": str(e)}


# --- SIGURAN probni tok mehaničara (zaseban test mehaničar + test nalog) ----
_TEST_MEH_KIME = "test.meh.tok"
_TEST_GB = "TEST"
_TEST_RN = "RN-TEST-TOK"


def _test_mehanicar(db: Session) -> Korisnik:
    meh = db.query(Korisnik).filter(Korisnik.korisnicko_ime == _TEST_MEH_KIME).first()
    if not meh:
        meh = Korisnik(ime="🧪 TEST Mehaničar", korisnicko_ime=_TEST_MEH_KIME,
                       lozinka_hash="x", uloga=Uloga.radnik, aktivan=True, prijavljuje_se=True)
        db.add(meh); db.flush()
    else:
        meh.aktivan = True
    return meh


def _obrisi_test_nalog(db: Session) -> None:
    for n in db.query(Nalog).filter(Nalog.broj == _TEST_RN).all():
        db.delete(n)   # kaskadno briše operacije, zadatke, vremena
    db.flush()


@router.post("/test-tok")
def test_tok(request: Request, _: Korisnik = Depends(_samo_vlasnik), db: Session = Depends(get_db)):
    """SIGURAN probni tok: zaseban test mehaničar + test nalog (GB TEST) s 3 zadatka,
    prvi na 'čeka potvrdu'. Pošalje poveznicu na dispecer_test_broj. NE dira prave
    naloge. Ponovni poziv resetira probne zadatke. Vrati ishod slanja."""
    from ..config import settings
    if not (settings.dispecer_test_broj or "").strip():
        raise HTTPException(status_code=400, detail="dispecer_test_broj nije postavljen — probni tok se ne šalje")
    meh = _test_mehanicar(db)
    # Svaki put izdaj SVJEŽU, nevezanu poveznicu — WhatsApp preglednik zna izgubiti
    # uređaj među otvaranjima pa bi stara (vezana) poveznica bila odbijana.
    link = db.query(MehanicarLink).filter(MehanicarLink.radnik_id == meh.id).first()
    if link:
        link.token = secrets.token_urlsafe(24)
        link.uredjaj = None
        link.aktivan = True
        link.zadnje_koristeno = None
        link.zadnji_uredjaj = None
        db.flush()
    voz = db.query(Vozilo).filter(Vozilo.gb == _TEST_GB).first()
    if not voz:
        voz = Vozilo(gb=_TEST_GB, marka="TEST"); db.add(voz); db.flush()
    _obrisi_test_nalog(db)
    n = Nalog(broj=_TEST_RN, vozilo_id=voz.id, naslov="PROBNI TOK",
              kreirao_id=meh.id, status=StatusNaloga.u_radu)
    db.add(n); db.flush()
    opisi = ["PROBNI 1 — zamjena pločica",
             "PROBNI 2 — provjera kočnica",
             "PROBNI 3 — ugradnja zračnog jastuka"]
    for i, o in enumerate(opisi):
        op = Operacija(nalog_id=n.id, kategorija="TEST", redoslijed=i + 1); db.add(op); db.flush()
        z = Zadatak(operacija_id=op.id, opis=o, ceka_potvrdu=(i == 0)); z.radnici = [meh]; db.add(z)
    db.commit()
    rez = posalji_poveznicu(db, meh, _TEST_GB, opisi[0], str(request.base_url))
    db.commit()
    return {"ok": bool(rez.get("poslano")), "detalji": rez, "zadataka": len(opisi)}


@router.post("/test-tok-stop")
def test_tok_stop(_: Korisnik = Depends(_samo_vlasnik), db: Session = Depends(get_db)):
    """Počisti probni tok: obriši test nalog i deaktiviraj test mehaničara + poveznicu."""
    _obrisi_test_nalog(db)
    meh = db.query(Korisnik).filter(Korisnik.korisnicko_ime == _TEST_MEH_KIME).first()
    if meh:
        meh.aktivan = False
        link = db.query(MehanicarLink).filter(MehanicarLink.radnik_id == meh.id).first()
        if link:
            link.aktivan = False
    db.commit()
    return {"ok": True}


@router.post("/ugasi/{radnik_id}")
def ugasi_link(radnik_id: int, _: Korisnik = Depends(_samo_vlasnik), db: Session = Depends(get_db)):
    """Ugasi sve poveznice mehaničara (kill-switch) — poveznica prestaje raditi odmah."""
    link = db.query(MehanicarLink).filter(MehanicarLink.radnik_id == radnik_id).first()
    if link:
        link.aktivan = False
        link.uredjaj = None
        db.commit()
    return {"ok": True}


# --- dijelovi: skladištar vraća zadatak mehaničaru kad dio stigne ----------
@router.get("/ceka-dijelove")
def ceka_dijelove(gb: str | None = None, _: Korisnik = Depends(_skladiste), db: Session = Depends(get_db)):
    """Operacije koje čekaju dijelove (za skladištarev prozorčić „Pridruži operaciji").
    Filtrira se po GB-u (vozilu) — što skladištar razdužuje na primci."""
    cilj = (gb or "").strip()
    out = []
    for n in db.query(Nalog).filter(Nalog.status.in_(_AKTIVNI)).all():
        g = _gb(n)
        if cilj and g != cilj:
            continue
        voz = n.vozilo
        vozilo = " ".join(x for x in [(voz.marka if voz else None), (voz.model if voz else None)] if x)
        for op in n.operacije:
            for z in op.zadaci:
                if z.razlog_prekida != "dijelovi":
                    continue
                out.append({
                    "zadatak_id": z.id, "gb": g, "vozilo": vozilo or (n.naslov or ""),
                    "opis": z.opis, "kategorija": op.kategorija,
                    "mehanicar": (z.radnici[0].ime if z.radnici else None),
                    "dio": _izvuci_dio(z.opis),
                })
    return out


@router.post("/dio-stigao/{zadatak_id}")
def dio_stigao(zadatak_id: int, request: Request,
               _: Korisnik = Depends(_skladiste), db: Session = Depends(get_db)):
    """Skladištar pridruži stigli dio ovoj operaciji → zadatak izlazi iz „čeka dijelove"
    i vraća se ISTOM mehaničaru (na potvrdu) + ponovno mu ode poveznica (gated)."""
    z = db.get(Zadatak, zadatak_id)
    if not z:
        raise HTTPException(status_code=404, detail="Zadatak ne postoji")
    if z.razlog_prekida != "dijelovi":
        raise HTTPException(status_code=409, detail="Zadatak nije u statusu 'čeka dijelove'")
    z.razlog_prekida = None
    z.ceka_potvrdu = True
    n = z.operacija.nalog
    m = z.radnici[0] if z.radnici else None
    wa = None
    if m:
        obavijesti_korisnika(db, m.id, "Dio je stigao", f"{z.opis} · GB {_gb(n)}", "/moja-radiona")
        wa = posalji_poveznicu(db, m, _gb(n), z.opis or "", str(request.base_url))
    db.commit()
    return {"ok": True, "wa": wa}


# --- login-less HTML stranica za mehaničara --------------------------------
_HTML = """<!doctype html>
<html lang="hr"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover, maximum-scale=1"/>
<meta name="theme-color" content="#0d47a1"/>
<title>Bravel — zadatak</title>
<style>
*{box-sizing:border-box} body{margin:0;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:#f4f6f8;color:#1f2a37}
.top{background:#0d47a1;color:#fff;padding:16px;font-weight:700;font-size:18px}
.wrap{padding:16px;max-width:560px;margin:0 auto}
.kart{background:#fff;border-radius:14px;padding:18px;margin-bottom:16px;box-shadow:0 1px 3px rgba(0,0,0,.08)}
.gb{font-size:34px;font-weight:800;line-height:1}
.meta{color:#5b6470;font-size:14px;margin-top:4px}
.opis{font-size:18px;margin-top:14px;line-height:1.4}
.cijena{margin-top:12px;font-size:15px;color:#0d47a1;font-weight:700}
.gumbi{display:flex;flex-direction:column;gap:12px;margin-top:8px}
button{border:0;border-radius:14px;padding:18px;font-size:19px;font-weight:700;color:#fff;cursor:pointer}
.b-poc{background:#1f7a39} .b-got{background:#0d47a1} .b-dij{background:#b26a00} .b-nije{background:#5b6470}
.b-ostaje{background:#1f7a39} .b-kraj{background:#5b6470}
.b-poc:disabled,.b-got:disabled,.b-dij:disabled,.b-nije:disabled{opacity:.5}
.banner{background:#fff4d6;border:1px solid #f0c44c;color:#7a4e00;border-radius:12px;padding:16px;font-weight:700;text-align:center;font-size:17px;margin-bottom:4px}
.info{text-align:center;color:#5b6470;padding:32px 16px;font-size:18px}
.greska{background:#fdeaea;color:#b3261e;border:1px solid #e5534b;border-radius:12px;padding:16px;font-weight:700;text-align:center}
.stanje{display:inline-block;margin-top:10px;font-size:13px;color:#5b6470}
.radi{color:#1f7a39;font-weight:700}
/* „Stigao novi zadatak" — jaka vizualna najava kad se promijeni zadatak */
.novibanner{background:#1f7a39;color:#fff;border-radius:14px;padding:18px;margin-bottom:14px;
  font-size:21px;font-weight:800;text-align:center;box-shadow:0 6px 18px rgba(31,122,57,.35);
  animation:noviPulse 1s ease-in-out 3;transition:opacity .5s}
@keyframes noviPulse{0%,100%{transform:scale(1)}50%{transform:scale(1.045)}}
.kart.novi{animation:noviUlaz .7s ease-out}
@keyframes noviUlaz{0%{transform:translateY(16px) scale(.97);opacity:.15;box-shadow:0 0 0 5px #ffe08a}
  55%{box-shadow:0 0 0 7px #ffcf4d}100%{transform:none;opacity:1;box-shadow:0 1px 3px rgba(0,0,0,.08)}}
</style></head>
<body>
<div class="top">BRAVEL · radni zadatak</div>
<div class="wrap" id="app"><div class="info">Učitavam…</div></div>
<script>
const TOKEN="__TOKEN__";
function uredjaj(){let u=localStorage.getItem('bravel_uredjaj');if(!u){u=(crypto.randomUUID?crypto.randomUUID():String(Math.random())+Date.now());localStorage.setItem('bravel_uredjaj',u);}return u;}
async function api(akcija,extra){
  const r=await fetch('/api/dispecer/z/'+TOKEN+'/'+akcija,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(Object.assign({uredjaj:uredjaj()},extra||{}))});
  let j={};try{j=await r.json()}catch(e){}
  return {status:r.status,j};
}
function esc(s){return (s==null?'':String(s)).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));}
let busy=false, prevZid=null;
function beep(){try{var C=window.AudioContext||window.webkitAudioContext;if(!C)return;var a=new C();var o=a.createOscillator(),g=a.createGain();o.connect(g);g.connect(a.destination);o.type='sine';o.frequency.value=880;g.gain.setValueAtTime(.001,a.currentTime);g.gain.exponentialRampToValueAtTime(.4,a.currentTime+.03);g.gain.exponentialRampToValueAtTime(.001,a.currentTime+.5);o.start();o.stop(a.currentTime+.52);}catch(_){}}
function najaviNovi(){try{if(navigator.vibrate)navigator.vibrate([220,110,220]);}catch(_){}beep();var b=document.getElementById('novibanner');if(b)setTimeout(function(){b.style.opacity='0';},3500);}
function render(d){
  const app=document.getElementById('app');
  if(d.greska){app.innerHTML='<div class="greska">'+esc(d.greska)+'</div>';return;}
  if(d.nema){app.innerHTML='<div class="kart"><div class="info">Nemaš više zadataka.<br/>Javi poslovođi.</div></div>';return;}
  if(d.gotov_za_danas){app.innerHTML='<div class="kart"><div class="info"><b>Gotov za danas.</b><br/>Vrijeme je spremljeno. Vidimo se sutra!</div></div>';return;}
  if(d.parkirano){app.innerHTML='<div class="kart"><div class="info">Zabilježeno — zadatak <b>nije dovršen</b> (pauza).<br/>Vrijeme je spremljeno. Doviđenja!</div></div>';return;}
  let cij='';  // iznos norme skriven za sad (dok testiramo poruke)
  const radi=d.stanje==='radu';
  app.innerHTML=
   (d._novi?'<div class="novibanner" id="novibanner">🆕 Stigao novi zadatak!</div>':'')
   +'<div class="kart'+(d._novi?' novi':'')+'"><div class="gb">'+esc(d.gb)+'</div>'
   +'<div class="meta">'+esc([d.vozilo,d.reg].filter(Boolean).join(' · '))+'</div>'
   +'<div class="opis">'+esc(d.opis)+'</div>'+cij
   +(radi?'<div class="stanje radi">▶ mjerač radi</div>':'')
   +(d.preostalo>0?'<div class="stanje">još '+d.preostalo+' u redu</div>':'')
   +'</div>'
   +'<div class="gumbi">'
   +(radi?'':'<button class="b-poc">Počinjem</button>')
   +'<button class="b-got">Gotovo</button>'
   +'<button class="b-dij">Nemam dijelova</button>'
   +'<button class="b-nije">Nije gotovo</button>'
   +'</div>';
  var bp=document.querySelector('.b-poc'); if(bp) bp.onclick=function(){akc('pocinjem')};
  var bg=document.querySelector('.b-got'); if(bg) bg.onclick=function(){akc('gotovo')};
  var bd=document.querySelector('.b-dij'); if(bd) bd.onclick=function(){dijelovi()};
  var bn=document.querySelector('.b-nije'); if(bn) bn.onclick=function(){akc('nije-gotovo')};
  if(d._novi) najaviNovi();
}
async function ucitaj(){const {status,j}=await api('stanje');if(status===403){render({greska:j.detail||'Ova poveznica nije za tebe'});return;}if(status>=400){render({greska:(j.detail||'Greška')});return;}render(j);prevZid=(j&&j.zadatak_id)||null;}
async function akc(a){if(busy)return;busy=true;const prije=prevZid;const {status,j}=await api(a);busy=false;if(status===403){render({greska:j.detail});return;}if(status>=400){render({greska:(j.detail||'Greška')});return;}if(j&&j.zadatak_id&&prije&&j.zadatak_id!==prije)j._novi=true;render(j);prevZid=(j&&j.zadatak_id)||null;}
async function dijelovi(){if(busy)return;const naziv=prompt('Koji dio nedostaje? (upiši naziv)');if(naziv===null)return;busy=true;const prije=prevZid;const {status,j}=await api('dijelovi',{naziv:naziv});busy=false;if(status>=400){render({greska:(j.detail||'Greška')});return;}if(j&&j.zadatak_id&&prije&&j.zadatak_id!==prije)j._novi=true;render(j);prevZid=(j&&j.zadatak_id)||null;}
function krajPrompt(){
  const app=document.getElementById('app');
  app.innerHTML=
   '<div class="banner">Kraj radnog vremena.<br/>Jesi gotov za danas ili ostaješ dulje?</div>'
   +'<div class="gumbi">'
   +'<button class="b-ostaje">Ostajem dulje</button>'
   +'<button class="b-kraj">Gotov za danas</button>'
   +'</div>';
  document.querySelector('.b-ostaje').onclick=function(){smjena('ostajem')};
  document.querySelector('.b-kraj').onclick=function(){smjena('gotov')};
}
async function smjena(odg){
  if(busy)return;
  if(PROBA){
    if(odg==='gotov'){render({gotov_za_danas:true});}
    else{document.getElementById('app').innerHTML='<div class="kart"><div class="info"><b>Ostajem dulje.</b><br/>(proba) Nastavljaš s radom kao inače.</div></div>';}
    return;
  }
  busy=true;const {status,j}=await api('smjena',{odgovor:odg});busy=false;
  if(status===403){render({greska:j.detail});return;}
  if(status>=400){render({greska:(j.detail||'Greška')});return;}
  render(j);
}
const PARAMS=new URLSearchParams(location.search);
const PROBA=PARAMS.get('proba')==='1';
if(PARAMS.get('kraj')==='1'){ krajPrompt(); } else { ucitaj(); }
</script>
</body></html>"""


@page_router.get("/z/{token}", response_class=HTMLResponse)
def z_stranica(token: str):
    """Login-less stranica mehaničara. Sama ljuska; podaci idu kroz /api/dispecer/z/."""
    return HTMLResponse(_HTML.replace("__TOKEN__", token))
