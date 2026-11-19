"""Cartec valjci — testovi kočnica s računala u radioni.

Tok:
1. Skripta na računalu s valjcima (cartec_skripta/cartec_salji.py) se jednom
   prijavi (POST /cartec/prijava) i dobije nasumičan token. Vlasnik je odobri u
   Šifrarnik → Integracije (nitko ne prepisuje ključeve ni lozinke).
2. Za svako mjerenje osovine (Cartec piše Logs\\AxleData_Service_NN.csv) skripta
   pošalje najveću silu lijevo/desno (POST /cartec/mjerenje).
3. Mjerenja istog vozila (ista Cartec „sesija" = do idućeg „novo vozilo") čine
   JEDAN test. Ponovljena osovina: vrijedi zadnje mjerenje, ranija = „ponovljeno".
4. Test se sam veže uz nalog na kojem se TOG TRENA radi (mjerač pokrenut), ili uz
   jedini otvoreni nalog s operacijom kočnica. Inače ostaje „nerazvrstan" i
   voditelj/mehaničar dobije pitanje „Test kočnica u HH:MM — koje vozilo?".
5. Vozilo = GB naloga (nikad registracija). Nalog s nerazvrstanim testom među
   kandidatima ne može se zatvoriti dok se test ne veže.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..auth import trenutni_korisnik, zahtijevaj_ai_poslovodja
from ..database import get_db
from ..models import (
    CartecUredjaj,
    Korisnik,
    MjerenjeOsovine,
    Nalog,
    Operacija,
    StatusNaloga,
    TestKocnica,
    Uloga,
    Zadatak,
)

router = APIRouter(prefix="/cartec", tags=["cartec"])
samo_vlasnik = zahtijevaj_ai_poslovodja()

OTVORENI = (StatusNaloga.otvoren, StatusNaloga.u_radu, StatusNaloga.ceka_dijelove)
MAX_NEODOBRENIH = 5          # zaštita od zatrpavanja prijavama
SESIJA_BEZ_OZNAKE_MIN = 60   # bez Cartec oznake vozila: isto vozilo = unutar 1 h


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _sad() -> datetime:
    return datetime.now(timezone.utc)


def _utc(d: datetime) -> datetime:
    """SQLite vraća naivna vremena — tretiramo ih kao UTC."""
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


# --- uređaj (računalo s valjcima) -------------------------------------------
class PrijavaIn(BaseModel):
    naziv: str = Field(default="Cartec valjci", max_length=120)


@router.post("/prijava")
def prijava_uredjaja(p: PrijavaIn, db: Session = Depends(get_db)):
    """Skripta se prijavi i dobije token. Dok vlasnik ne odobri, mjerenja se odbijaju
    (skripta ih čuva i šalje kasnije)."""
    neodobreni = db.query(CartecUredjaj).filter(CartecUredjaj.odobren.is_(False)).count()
    if neodobreni >= MAX_NEODOBRENIH:
        raise HTTPException(status_code=429, detail="Previše neodobrenih uređaja — odobri ili obriši postojeće.")
    token = secrets.token_urlsafe(32)
    u = CartecUredjaj(naziv=(p.naziv or "Cartec valjci").strip()[:120], token_hash=_hash(token))
    db.add(u)
    db.commit()
    return {"id": u.id, "token": token, "odobren": False}


def _uredjaj(db: Session, token: str | None, *, mora_biti_odobren: bool = True) -> CartecUredjaj:
    if not token:
        raise HTTPException(status_code=401, detail="Nedostaje X-Cartec-Token")
    u = db.query(CartecUredjaj).filter(CartecUredjaj.token_hash == _hash(token)).first()
    if not u:
        raise HTTPException(status_code=401, detail="Nepoznat uređaj")
    u.zadnji_kontakt = _sad()
    if mora_biti_odobren and not u.odobren:
        db.commit()
        raise HTTPException(status_code=403, detail="Uređaj čeka odobrenje vlasnika")
    return u


@router.get("/ping")
def ping(x_cartec_token: str | None = Header(default=None), db: Session = Depends(get_db)):
    u = _uredjaj(db, x_cartec_token, mora_biti_odobren=False)
    db.commit()
    return {"id": u.id, "odobren": u.odobren}


class StanjeIn(BaseModel):
    verzija: str = Field(default="", max_length=20)
    dnevnik: str = Field(default="", max_length=20000)   # zadnji redovi dnevnika skripte


@router.post("/stanje")
def javi_stanje(p: StanjeIn, x_cartec_token: str | None = Header(default=None), db: Session = Depends(get_db)):
    """Skripta svakih par minuta javi verziju i dnevnik — da se kvar vidi bez AnyDeska.
    Smije i neodobren uređaj (samo upis stanja, ništa drugo)."""
    u = _uredjaj(db, x_cartec_token, mora_biti_odobren=False)
    u.verzija = (p.verzija or "")[:20] or None
    u.stanje = p.dnevnik[-20000:] or None
    u.stanje_vrijeme = _sad()
    db.commit()
    if u.odobren:
        try:
            _rezervna_obavijest(db, u)
        except Exception:  # noqa: BLE001 — stanje se ne smije srušiti zbog obavijesti
            db.rollback()
    return {"ok": True, "odobren": u.odobren}


def _skripta_put():
    from pathlib import Path
    ovdje = Path(__file__).resolve()
    for kand in (ovdje.parents[2] / "cartec_skripta" / "cartec_salji.ps1",     # Docker: /app/cartec_skripta
                 ovdje.parents[3] / "cartec_skripta" / "cartec_salji.ps1"):    # repo: radni-nalozi/cartec_skripta
        if kand.exists():
            return kand
    return None


def _verzija_skripte(tekst: str) -> str:
    import re
    m = re.search(r"\$Verzija\s*=\s*'([^']+)'", tekst)
    return m.group(1) if m else ""


@router.get("/skripta")
def skripta(x_cartec_token: str | None = Header(default=None), db: Session = Depends(get_db)):
    """Najnovija skripta za samoažuriranje (samo odobreni uređaj)."""
    _uredjaj(db, x_cartec_token)
    db.commit()
    put = _skripta_put()
    if not put:
        raise HTTPException(status_code=404, detail="Skripta nije u paketu")
    tekst = put.read_text(encoding="utf-8-sig")
    return {"verzija": _verzija_skripte(tekst), "sadrzaj": tekst}


class MjerenjeIn(BaseModel):
    sesija: str | None = Field(default=None, max_length=40)  # vrijeme zadnjeg Cartec „novo vozilo"
    osovina: int = Field(ge=1, le=12)
    vrsta: str = Field(pattern="^(radna|parkirna)$")
    vrijeme: datetime                                        # kraj mjerenja (s vremenskom zonom)
    sila_lijevo: int = Field(ge=0, le=200000)
    sila_desno: int = Field(ge=0, le=200000)
    tezina: int | None = Field(default=None, ge=0, le=100000)
    otisak: str = Field(min_length=8, max_length=64)        # sha256 sadržaja datoteke


def _razlika(l: int, d: int) -> float:
    veca = max(l, d)
    return round(abs(l - d) / veca * 100, 1) if veca else 0.0


def _nadji_ili_kreiraj_test(db: Session, u: CartecUredjaj, p: MjerenjeIn, vrijeme: datetime) -> TestKocnica:
    sesija = (p.sesija or "").strip()
    if sesija:
        t = (db.query(TestKocnica)
             .filter(TestKocnica.uredjaj_id == u.id, TestKocnica.sesija == sesija).first())
        if t:
            return t
    else:
        # Bez oznake vozila: isto vozilo ako je prethodni test završio unutar 1 h.
        t = (db.query(TestKocnica).filter(TestKocnica.uredjaj_id == u.id)
             .order_by(TestKocnica.kraj.desc()).first())
        if t and timedelta(0) <= vrijeme - _utc(t.kraj) <= timedelta(minutes=SESIJA_BEZ_OZNAKE_MIN):
            return t
        sesija = "bez-" + vrijeme.strftime("%Y%m%d%H%M%S")
    t = TestKocnica(uredjaj_id=u.id, sesija=sesija, pocetak=vrijeme, kraj=vrijeme, status="nerazvrstan",
                    poveznica=secrets.token_urlsafe(18))
    db.add(t)
    db.flush()
    return t


def kandidati_naloga(db: Session) -> tuple[list[Nalog], set[int], set[int]]:
    """Nalozi na kojima se SAD radi (pokrenut mjerač), pa otvoreni s operacijom kočnica."""
    u_radu = (db.query(Nalog).join(Operacija, Operacija.nalog_id == Nalog.id)
              .join(Zadatak, Zadatak.operacija_id == Operacija.id)
              .filter(Nalog.status.in_(OTVORENI), Zadatak.zapoceto.isnot(None),
                      Zadatak.gotovo.is_(False))
              .all())
    kocnice = (db.query(Nalog).join(Operacija, Operacija.nalog_id == Nalog.id)
               .join(Zadatak, Zadatak.operacija_id == Operacija.id)
               .filter(Nalog.status.in_(OTVORENI), Zadatak.gotovo.is_(False))
               .all())
    kocnice = [n for n in kocnice if any(
        "koč" in (op.kategorija or "").lower() or "koc" in (op.kategorija or "").lower()
        or any("koč" in (z.opis or "").lower() for z in op.zadaci)
        for op in n.operacije)]
    # Bez DISTINCT u SQL-u (Postgres + JSON stupci) — dedupe po id-u ovdje.
    vidjeni: dict[int, Nalog] = {}
    for n in u_radu:
        vidjeni.setdefault(n.id, n)
    for n in kocnice:
        vidjeni.setdefault(n.id, n)
    return list(vidjeni.values()), {n.id for n in u_radu}, {n.id for n in kocnice}


def _broj_osovina(t: TestKocnica) -> int:
    return len({m.osovina for m in t.mjerenja if m.vrsta == "radna"})


def _prethodni_broj_osovina(db: Session, t: TestKocnica) -> int | None:
    if not t.gb:
        return None
    pr = (db.query(TestKocnica)
          .filter(TestKocnica.gb == t.gb, TestKocnica.id != t.id, TestKocnica.status == "vezan",
                  TestKocnica.pocetak < t.pocetak)
          .order_by(TestKocnica.pocetak.desc()).first())
    return _broj_osovina(pr) if pr else None


def _ocijeni(db: Session, t: TestKocnica, novi_test: bool) -> bool:
    """Postavi status testa. Vraća True kad treba pitati ljude (test je tek postao
    nerazvrstan / čeka potvrdu) — da se obavijest ne šalje za svaku osovinu."""
    if t.vezao_id or t.rucno_poveznicom:          # čovjek je vezao — ne diramo
        return False
    stari = t.status
    if t.nalog_id is None:
        svi, u_radu, kocnice = kandidati_naloga(db)
        izbor = None
        if len(u_radu) == 1:
            izbor = next(iter(u_radu))
        elif not u_radu and len(kocnice) == 1:
            izbor = next(iter(kocnice))
        t.kandidati = ",".join(str(n.id) for n in svi[:12]) or None
        if izbor:
            n = db.get(Nalog, izbor)
            t.nalog_id = n.id
            t.gb = n.vozilo.gb if n.vozilo else None
    if t.nalog_id is None:
        t.status = "nerazvrstan"
        t.napomena = "Više mogućih vozila — odaberi nalog." if t.kandidati else "Nijedan nalog nije u radu — odaberi nalog."
    else:
        prije = _prethodni_broj_osovina(db, t)
        sad = _broj_osovina(t)
        if prije is not None and sad > prije:
            t.status = "ceka_potvrdu"
            t.napomena = f"Izmjereno {sad} osovina, a prošli test GB {t.gb} imao je {prije} — potvrdi vozilo."
        else:
            t.status = "vezan"
            t.napomena = None
    return t.status != "vezan" and (novi_test or t.status != stari)


@router.post("/mjerenje")
def primi_mjerenje(p: MjerenjeIn, x_cartec_token: str | None = Header(default=None),
                   db: Session = Depends(get_db)):
    u = _uredjaj(db, x_cartec_token)
    if db.query(MjerenjeOsovine).filter(MjerenjeOsovine.otisak == p.otisak).first():
        db.commit()
        return {"ok": True, "duplikat": True}
    vrijeme = p.vrijeme if p.vrijeme.tzinfo else p.vrijeme.replace(tzinfo=timezone.utc)
    vrijeme = vrijeme.astimezone(timezone.utc)
    t = _nadji_ili_kreiraj_test(db, u, p, vrijeme)
    novi_test = not t.mjerenja
    # Ponovljeno mjerenje iste osovine: ranija više ne vrijede.
    for m in t.mjerenja:
        if m.osovina == p.osovina and m.vrsta == p.vrsta and m.vazece and _utc(m.vrijeme) <= vrijeme:
            m.vazece = False
    noviji = any(m.osovina == p.osovina and m.vrsta == p.vrsta and _utc(m.vrijeme) > vrijeme
                 for m in t.mjerenja)
    m = MjerenjeOsovine(test=t, otisak=p.otisak, osovina=p.osovina, vrsta=p.vrsta, vrijeme=vrijeme,
                        sila_lijevo=p.sila_lijevo, sila_desno=p.sila_desno,
                        razlika_pct=_razlika(p.sila_lijevo, p.sila_desno), tezina=p.tezina,
                        vazece=not noviji)
    db.add(m)
    if vrijeme < _utc(t.pocetak):
        t.pocetak = vrijeme
    if vrijeme > _utc(t.kraj):
        t.kraj = vrijeme
    # Nova osovina nakon poslane poruke = vozilo se vratilo / test se nastavio → na kraju opet poruka.
    if t.obavijesteno is not None and vrijeme > _utc(t.obavijesteno) + timedelta(minutes=1):
        t.obavijesteno = None
    db.flush()
    db.refresh(t)
    _ocijeni(db, t, novi_test)
    db.commit()
    # Obavijest NE ide ovdje (nakon prve osovine test još traje), nego kad vozilo siđe s
    # valjaka: skripta javi /cartec/kraj, a rezervno /stanje nakon KRAJ_REZERVA_MIN tišine.
    return {"ok": True, "test_id": t.id, "status": t.status, "nalog_id": t.nalog_id, "gb": t.gb}


KRAJ_REZERVA_MIN = 5    # bez znaka kraja (stara skripta) — obavijest nakon 5 min bez nove osovine
KRAJ_PROZOR_MIN = 20    # znak kraja vrijedi za test čija je zadnja osovina unutar 20 min


class KrajIn(BaseModel):
    vrijeme: datetime        # kad je vozilo sišlo s valjaka (Cartec „IDLE")


def _obavijesti_jednom(db: Session, t: TestKocnica) -> bool:
    """Toni 19.11.2026.: poruka ČIM VALJCI STANU (kraj testa), jednom po testu.
    Ne šalje se ako je čovjek već upisao vozilo."""
    if t.obavijesteno is not None:
        return False
    t.obavijesteno = _sad()
    db.commit()
    if t.vezao_id or t.rucno_poveznicom:
        return False
    _obavijesti_kraj(db, t)
    return True


@router.post("/kraj")
def kraj_testa(p: KrajIn, x_cartec_token: str | None = Header(default=None), db: Session = Depends(get_db)):
    """Skripta javlja da je vozilo sišlo s valjaka (Cartec TestProcedure.log → IDLE)."""
    u = _uredjaj(db, x_cartec_token)
    db.commit()
    kad = p.vrijeme if p.vrijeme.tzinfo else p.vrijeme.replace(tzinfo=timezone.utc)
    t = (db.query(TestKocnica).filter(TestKocnica.uredjaj_id == u.id)
         .order_by(TestKocnica.kraj.desc()).first())
    if not t or kad - _utc(t.kraj) > timedelta(minutes=KRAJ_PROZOR_MIN):
        return {"ok": True, "test_id": None, "poslano": False}
    return {"ok": True, "test_id": t.id, "poslano": _obavijesti_jednom(db, t)}


def _rezervna_obavijest(db: Session, u: CartecUredjaj) -> None:
    """Ako znak kraja nije stigao: test bez nove osovine KRAJ_REZERVA_MIN = gotov."""
    sad = _sad()
    for t in (db.query(TestKocnica)
              .filter(TestKocnica.uredjaj_id == u.id, TestKocnica.obavijesteno.is_(None))
              .order_by(TestKocnica.kraj.desc()).limit(5).all()):
        star = sad - _utc(t.kraj)
        if timedelta(minutes=KRAJ_REZERVA_MIN) <= star <= timedelta(minutes=KRAJ_PROZOR_MIN + KRAJ_REZERVA_MIN):
            _obavijesti_jednom(db, t)


def _lokalno(d: datetime) -> str:
    try:
        from zoneinfo import ZoneInfo
        return _utc(d).astimezone(ZoneInfo("Europe/Zagreb")).strftime("%H:%M")
    except Exception:  # noqa: BLE001
        return _utc(d).strftime("%H:%M")


def _poveznica(db: Session, t: TestKocnica) -> str:
    """Oznaka za poveznicu bez prijave; stari testovi je dobiju pri prvom traženju."""
    if not t.poveznica:
        t.poveznica = secrets.token_urlsafe(18)
        db.commit()
    return t.poveznica


def _sto_upisati(t: TestKocnica) -> str:
    n = _broj_osovina(t)
    osovine = f"{n} osovin{'a' if n == 1 or n >= 5 else 'e'}"
    return f"{osovine} — provjeri GB {t.gb}" if t.gb else f"{osovine} — upiši GB vozila"


def _obavijesti_kraj(db: Session, t: TestKocnica) -> None:
    try:
        from ..push import obavijesti_ulogu
        tekst = f"Test kočnica u {_lokalno(t.pocetak)} gotov, {_sto_upisati(t)}."
        # Poveznica vodi na samostalnu stranicu testa (crtež + upis GB-a), ne u aplikaciju.
        obavijesti_ulogu(db, [Uloga.voditelj, Uloga.poslovodja], "Test kočnica", tekst,
                         url=f"/kocnice/{_poveznica(db, t)}")
    except Exception:  # noqa: BLE001 — obavijest nije bitna za spremanje mjerenja
        pass
    # WhatsApp ide SAMO vlasniku (Toni 19.11.2026. „samo meni") — poruke se plaćaju.
    try:
        from ..config import settings
        ime = (settings.ai_poslovodja_user or "").strip().lower()
        vlasnik = next((k for k in db.query(Korisnik).filter(Korisnik.aktivan.is_(True)).all()
                        if (k.korisnicko_ime or "").strip().lower() == ime), None) if ime else None
        if vlasnik:
            _wa_poveznica(db, t, vlasnik, settings.javni_url)
    except Exception:  # noqa: BLE001
        pass


# --- pregled i vezanje (portal) ---------------------------------------------
def _test_out(db: Session, t: TestKocnica, nalozi: dict[int, Nalog] | None = None) -> dict:
    def nalog_mini(n: Nalog | None):
        if not n:
            return None
        return {"id": n.id, "broj": n.broj, "naslov": n.naslov,
                "gb": n.vozilo.gb if n.vozilo else None, "status": n.status.value}

    kand_ids = [int(x) for x in (t.kandidati or "").split(",") if x.strip().isdigit()]
    kand = []
    for i in kand_ids:
        n = (nalozi or {}).get(i) or db.get(Nalog, i)
        if n and n.status in OTVORENI:
            kand.append(nalog_mini(n))
    vazeca = [m for m in t.mjerenja if m.vazece]
    return {
        "id": t.id, "status": t.status, "napomena": t.napomena,
        "pocetak": _utc(t.pocetak).isoformat(), "kraj": _utc(t.kraj).isoformat(),
        "gb": t.gb, "nalog": nalog_mini(db.get(Nalog, t.nalog_id) if t.nalog_id else None),
        "kandidati": kand,
        "osovina": len({m.osovina for m in vazeca if m.vrsta == "radna"}),
        "mjerenja": [{
            "id": m.id, "osovina": m.osovina, "vrsta": m.vrsta, "vrijeme": _utc(m.vrijeme).isoformat(),
            "sila_lijevo": m.sila_lijevo, "sila_desno": m.sila_desno, "razlika_pct": m.razlika_pct,
            "tezina": m.tezina, "vazece": m.vazece,
        } for m in sorted(t.mjerenja, key=lambda m: (m.vrsta != "radna", m.osovina, m.vrijeme))],
    }


def _smije_vidjeti(k: Korisnik) -> None:
    if k.uloga == Uloga.vozac:
        raise HTTPException(status_code=403, detail="Nemate ovlasti")


def _smije_vezati(k: Korisnik) -> None:
    # Odabir vozila za test rade SAMO voditelji/poslovođe (Toni 19.11.2026.) — mehaničari ne.
    if k.uloga not in (Uloga.voditelj, Uloga.poslovodja):
        raise HTTPException(status_code=403, detail="Vozilo za test kočnica odabire voditelj")


@router.get("/testovi")
def testovi(status: str | None = Query(default=None, pattern="^(vezan|nerazvrstan|ceka_potvrdu|otvoreni)$"),
            nalog_id: int | None = None, gb: str | None = None,
            limit: int = Query(default=50, ge=1, le=500),
            db: Session = Depends(get_db), k: Korisnik = Depends(trenutni_korisnik)):
    _smije_vidjeti(k)
    q = db.query(TestKocnica)
    if status == "otvoreni":
        q = q.filter(TestKocnica.status.in_(("nerazvrstan", "ceka_potvrdu")))
    elif status:
        q = q.filter(TestKocnica.status == status)
    if nalog_id:
        q = q.filter(TestKocnica.nalog_id == nalog_id)
    if gb:
        q = q.filter(TestKocnica.gb == gb.strip())
    return [_test_out(db, t) for t in q.order_by(TestKocnica.pocetak.desc()).limit(limit).all()]


@router.get("/otvoreni-nalozi")
def otvoreni_nalozi_za_gb(gb: str = Query(min_length=1, max_length=40),
                          db: Session = Depends(get_db), k: Korisnik = Depends(trenutni_korisnik)):
    """Otvoreni nalozi vozila po GB-u — za ručni odabir kad pravog vozila nema među gumbima."""
    _smije_vezati(k)
    from ..models import Vozilo
    red = (db.query(Nalog).join(Vozilo, Vozilo.id == Nalog.vozilo_id)
           .filter(Vozilo.gb == gb.strip(), Nalog.status.in_(OTVORENI))
           .order_by(Nalog.kreiran.desc()).all())
    return [{"id": n.id, "broj": n.broj, "naslov": n.naslov, "gb": gb.strip()} for n in red]


class VeziIn(BaseModel):
    nalog_id: int


@router.post("/testovi/{test_id}/vezi")
def vezi_test(test_id: int, p: VeziIn, db: Session = Depends(get_db), k: Korisnik = Depends(trenutni_korisnik)):
    """Voditelj odabere nalog (= vozilo po GB-u) za test. Ručni izbor je konačan."""
    _smije_vezati(k)
    t = db.get(TestKocnica, test_id)
    if not t:
        raise HTTPException(status_code=404, detail="Test ne postoji")
    n = db.get(Nalog, p.nalog_id)
    if not n:
        raise HTTPException(status_code=404, detail="Nalog ne postoji")
    t.nalog_id = n.id
    t.gb = n.vozilo.gb if n.vozilo else None
    t.status = "vezan"
    t.napomena = None
    t.vezao_id = k.id
    db.commit()
    return _test_out(db, t)


@router.get("/testovi/{test_id}/poveznica")
def poveznica_testa(test_id: int, db: Session = Depends(get_db), k: Korisnik = Depends(trenutni_korisnik)):
    """Poveznica bez prijave za ovaj test (za slanje voditelju na mobitel)."""
    _smije_vezati(k)
    t = db.get(TestKocnica, test_id)
    if not t:
        raise HTTPException(status_code=404, detail="Test ne postoji")
    return {"putanja": f"/kocnice/{_poveznica(db, t)}"}


def _broj_iz_zapisa(ime: str, zapisi: list[dict]) -> str | None:
    """Broj iz imenika za korisnika portala. Točno ime; inače JEDINI zapis čije ime sadrži sve
    riječi korisnikovog imena (portal: „Toni", imenik: „JENDRIŠ TONI"). Više takvih → ništa."""
    from .. import imenik
    tocno = imenik.brojevi_po_imenu(zapisi).get(imenik.kljuc_imena(ime))
    if tocno and tocno.get("broj"):
        return tocno["broj"]
    rijeci = set(imenik.kljuc_imena(ime).split())
    if not rijeci:
        return None
    brojevi = {z.get("broj") for z in zapisi
               if z.get("broj") and rijeci <= set(imenik.kljuc_imena(z.get("ime")).split())}
    return brojevi.pop() if len(brojevi) == 1 else None


def _broj_korisnika(k: Korisnik) -> str | None:
    if (k.telefon or "").strip():
        return k.telefon.strip()
    from .. import imenik
    return _broj_iz_zapisa(k.ime, (imenik.dohvati().get("zapisi")) or [])


def _wa_poveznica(db: Session, t: TestKocnica, primatelj: Korisnik, base_url: str) -> dict:
    """Pošalji poveznicu testa na WhatsApp JEDNOM korisniku (broj iz imenika, po imenu) preko
    bravel-agenta — isti put i ista pravila kao dispečer (dispecer_wa_on, test-broj)."""
    from ..config import settings
    if not (settings.dispecer_wa_on and settings.bravel_agent_url and settings.bravel_agent_kljuc):
        return {"poslano": False, "razlog": "WhatsApp slanje je isključeno"}
    url = f"{base_url.rstrip('/')}/kocnice/{_poveznica(db, t)}"
    try:
        from zoneinfo import ZoneInfo
        kad = _utc(t.pocetak).astimezone(ZoneInfo("Europe/Zagreb")).strftime("%d.%m. u %H:%M")
    except Exception:  # noqa: BLE001
        kad = _utc(t.pocetak).strftime("%d.%m. u %H:%M")
    body = {"poruka": f"Test kočnica {kad} gotov, {_sto_upisati(t)}: {url}"}
    test = (settings.dispecer_test_broj or "").strip()
    if test:
        body["vozac"], body["broj"] = "test", test
    else:
        broj = _broj_korisnika(primatelj)
        if not broj:
            return {"poslano": False, "razlog": f"{primatelj.ime} nema (jednoznačan) broj u imeniku"}
        body["vozac"], body["broj"] = primatelj.ime, broj
    try:
        import httpx
        r = httpx.post(f"{settings.bravel_agent_url.rstrip('/')}/api/vozac/nalog", json=body,
                       headers={"X-Api-Key": settings.bravel_agent_kljuc}, timeout=10)
        ok = r.status_code < 300 and bool(r.json().get("ok"))
        return {"poslano": ok} if ok else {"poslano": False, "razlog": f"bravel-agent {r.status_code}: {r.text[:150]}"}
    except Exception as e:  # noqa: BLE001
        return {"poslano": False, "razlog": str(e)}


@router.post("/testovi/{test_id}/posalji-wa")
def posalji_test_na_whatsapp(test_id: int, request: Request, db: Session = Depends(get_db),
                             k: Korisnik = Depends(trenutni_korisnik)):
    """Voditelj si pošalje poveznicu testa na svoj WhatsApp (broj iz imenika)."""
    _smije_vezati(k)
    t = db.get(TestKocnica, test_id)
    if not t:
        raise HTTPException(status_code=404, detail="Test ne postoji")
    from ..config import settings
    return _wa_poveznica(db, t, k, settings.javni_url or str(request.base_url))


# --- poveznica bez prijave: crtež testa + upis GB-a ---------------------------
# Tko ima poveznicu (nasumična oznaka iz obavijesti), vidi JEDAN test i smije mu upisati GB.
def _test_po_poveznici(db: Session, oznaka: str) -> TestKocnica:
    t = db.query(TestKocnica).filter(TestKocnica.poveznica == (oznaka or "").strip()).first() if oznaka else None
    if not t:
        raise HTTPException(status_code=404, detail="Poveznica ne vrijedi")
    return t


def _javni_out(db: Session, t: TestKocnica) -> dict:
    o = _test_out(db, t)
    return {k: o[k] for k in ("status", "pocetak", "kraj", "gb", "nalog", "osovina", "mjerenja")}


@router.get("/javno/{oznaka}")
def javni_test(oznaka: str, db: Session = Depends(get_db)):
    return _javni_out(db, _test_po_poveznici(db, oznaka))


class JavnoGbIn(BaseModel):
    gb: str = Field(min_length=1, max_length=40)
    nalog_id: int | None = None      # kad GB ima više otvorenih naloga


@router.post("/javno/{oznaka}/gb")
def javni_upis_gb(oznaka: str, p: JavnoGbIn, db: Session = Depends(get_db)):
    """Upis GB-a za test. Veže se uz otvoren nalog tog vozila; ako ih je više, vrati izbor.
    Vozilo bez otvorenog naloga: test se veže samo uz GB (bez naloga)."""
    from ..models import Vozilo
    t = _test_po_poveznici(db, oznaka)
    gb = p.gb.strip()
    v = db.query(Vozilo).filter(Vozilo.gb == gb).first()
    if not v:
        raise HTTPException(status_code=404, detail=f"GB {gb} ne postoji u popisu vozila")
    nalozi = (db.query(Nalog).filter(Nalog.vozilo_id == v.id, Nalog.status.in_(OTVORENI))
              .order_by(Nalog.kreiran.desc()).all())
    odabran = None
    if p.nalog_id:
        odabran = next((n for n in nalozi if n.id == p.nalog_id), None)
        if not odabran:
            raise HTTPException(status_code=400, detail="Taj nalog nije otvoren za ovaj GB")
    elif len(nalozi) == 1:
        odabran = nalozi[0]
    elif len(nalozi) > 1:
        return {"izbor": [{"id": n.id, "broj": n.broj, "naslov": n.naslov} for n in nalozi]}
    t.nalog_id = odabran.id if odabran else None
    t.gb = gb
    t.status = "vezan"
    t.napomena = None if odabran else "GB upisan ručno — vozilo tada nije imalo otvoren nalog."
    t.rucno_poveznicom = True
    db.commit()
    return {"test": _javni_out(db, t)}


@router.post("/javno/{oznaka}/ponisti")
def javni_ponisti_gb(oznaka: str, db: Session = Depends(get_db)):
    """Obriši upisano vozilo — test je opet bez GB-a (krivo upisano / krivo kliknuto)."""
    t = _test_po_poveznici(db, oznaka)
    t.nalog_id = None
    t.gb = None
    t.status = "nerazvrstan"
    t.napomena = "Vozilo obrisano — upiši GB."
    t.vezao_id = None
    t.rucno_poveznicom = False
    db.commit()
    return {"test": _javni_out(db, t)}


def blokira_zatvaranje(db: Session, nalog_id: int) -> TestKocnica | None:
    """Nerazvrstan / nepotvrđen test koji bi mogao pripadati ovom nalogu."""
    for t in db.query(TestKocnica).filter(TestKocnica.status.in_(("nerazvrstan", "ceka_potvrdu"))).all():
        ids = {x for x in (t.kandidati or "").split(",") if x}
        if t.nalog_id == nalog_id or str(nalog_id) in ids:
            return t
    return None


# --- uređaji (vlasnik, Šifrarnik → Integracije) -----------------------------
@router.get("/uredjaji")
def uredjaji(db: Session = Depends(get_db), _: Korisnik = Depends(samo_vlasnik)):
    out = []
    for u in db.query(CartecUredjaj).order_by(CartecUredjaj.kreiran.desc()).all():
        out.append({"id": u.id, "naziv": u.naziv, "odobren": u.odobren,
                    "kreiran": _utc(u.kreiran).isoformat(),
                    "zadnji_kontakt": _utc(u.zadnji_kontakt).isoformat() if u.zadnji_kontakt else None,
                    "verzija": u.verzija, "stanje": u.stanje,
                    "stanje_vrijeme": _utc(u.stanje_vrijeme).isoformat() if u.stanje_vrijeme else None})
    return out


class OdobriIn(BaseModel):
    odobren: bool


@router.post("/uredjaji/{uid}")
def odobri_uredjaj(uid: int, p: OdobriIn, db: Session = Depends(get_db), _: Korisnik = Depends(samo_vlasnik)):
    u = db.get(CartecUredjaj, uid)
    if not u:
        raise HTTPException(status_code=404, detail="Uređaj ne postoji")
    u.odobren = p.odobren
    db.commit()
    return {"id": u.id, "odobren": u.odobren}


@router.delete("/uredjaji/{uid}")
def obrisi_uredjaj(uid: int, db: Session = Depends(get_db), _: Korisnik = Depends(samo_vlasnik)):
    u = db.get(CartecUredjaj, uid)
    if not u:
        raise HTTPException(status_code=404, detail="Uređaj ne postoji")
    if db.query(TestKocnica).filter(TestKocnica.uredjaj_id == uid).first():
        u.odobren = False   # ima testove — samo ga isključi (povijest ostaje)
    else:
        db.delete(u)
    db.commit()
    return {"ok": True}
